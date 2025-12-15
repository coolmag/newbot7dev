import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import yt_dlp

from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    # Строгая регулярка для ID видео
    YT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        # Ограничение на 2 потока, чтобы избежать 403 Forbidden от YouTube
        self.semaphore = asyncio.Semaphore(2)

    def _get_opts(self, is_search: bool = False) -> Dict[str, Any]:
        """Оптимальные настройки для 2025 года."""
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "no_check_certificate": True,
            "geo_bypass": True,
            "retries": 5, # Больше попыток для стабильности
            "fragment_retries": 5,
            # Важно: используем современные клиентские заголовки
            "extractor_args": {'youtube': {'player_client': ['android', 'web']}},
        }

        if getattr(self._settings, "COOKIES_FILE", None) and self._settings.COOKIES_FILE.exists():
            opts["cookiefile"] = str(self._settings.COOKIES_FILE)

        if is_search:
            opts.update({"extract_flat": True, "force_generic_extractor": False})
        else:
            opts.update({
                # ba[ext=m4a] — самый быстрый формат без видео-фрагментов
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }],
            })
        return opts

    async def search(self, query: str, limit: int = 10) -> List[TrackInfo]:
        """Профессиональный поиск с фильтрами."""
        # ytsearch: гарантирует, что запрос уйдет именно на поиск
        search_query = f"ytsearch{limit}:{query} -live -stream -radio"
        opts = self._get_opts(is_search=True)

        try:
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(search_query, download=False))
            entries = info.get("entries", []) or []
            
            return [
                TrackInfo(
                    title=e.get("title", "Unknown"),
                    artist=e.get("uploader") or "Unknown",
                    duration=int(e.get("duration") or 0),
                    source=Source.YOUTUBE.value,
                    identifier=e["id"],
                ) for e in entries if e and e.get("id")
            ]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def download_with_retry(self, query_or_id: str) -> DownloadResult:
        """Метод с ретраями для radio.py."""
        for attempt in range(3):
            result = await self.download(query_or_id)
            if result.success: return result
            await asyncio.sleep(attempt * 2 + 1)
        return DownloadResult(success=False, error="Failed after retries")

    async def download(self, query_or_id: str) -> DownloadResult:
        """Скачивание с принудительно корректным URL."""
        video_id = query_or_id.strip()
        
        # Если пришел не ID, ищем ID
        if not self.YT_ID_RE.match(video_id):
            found = await self.search(query_or_id, limit=1)
            if not found: return DownloadResult(success=False, error="Not found")
            video_id = found[0].identifier

        cache_key = f"yt:{video_id}"
        cached = await self._cache.get(cache_key, Source.YOUTUBE)
        if cached and Path(cached.file_path).exists(): return cached

        # Гарантируем наличие протокола и слэша
        url = f"www.youtube.com{video_id}"
        opts = self._get_opts(is_search=False)

        try:
            async with self.semaphore:
                loop = asyncio.get_running_loop()
                # Тайм-аут 85 секунд для соблюдения такта 90 секунд
                info = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=True)),
                    timeout=85.0
                )

            file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            if not file_path.exists(): return DownloadResult(success=False, error="Download failed")

            result = DownloadResult(
                success=True, file_path=str(file_path),
                title=info.get("title", "Unknown"),
                duration=int(info.get("duration", 0)),
                identifier=video_id
            )
            await self._cache.set(cache_key, result, Source.YOUTUBE)
            return result
        except Exception as e:
            logger.error(f"Critical DL error: {e}")
            return DownloadResult(success=False, error=str(e))
