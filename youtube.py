from __future__ import annotations
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
    # Строгая проверка ID видео (11 символов)
    YT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self.semaphore = asyncio.Semaphore(2)

    def _get_opts(self, is_search: bool = False) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "no_check_certificate": True,
            "geo_bypass": True,
            # Принудительно отключаем 'generic' экстрактор, чтобы не было ошибки 'not a valid URL'
            "allowed_extractors": ["youtube", "youtube:search"],
            "extractor_args": {'youtube': {'player_client': ['android', 'web']}},
        }
        if is_search:
            opts["extract_flat"] = True
        else:
            opts.update({
                "format": "bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }],
            })
        return opts

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        # Префикс ytsearch: гарантирует поиск именно на YouTube
        search_query = f"ytsearch{limit}:{query} -live -stream"
        opts = self._get_opts(is_search=True)
        try:
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(search_query, download=False))
            
            tracks = []
            for e in info.get("entries", []):
                if e and e.get("id"):
                    tracks.append(TrackInfo(
                        title=e.get("title", "Unknown"),
                        artist=e.get("uploader") or "Unknown",
                        duration=int(e.get("duration") or 0),
                        source=Source.YOUTUBE.value,
                        identifier=str(e["id"]).strip(), # Важно: только ID!
                    ))
            return tracks
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def download_with_retry(self, identifier: str) -> DownloadResult:
        """Метод, который дергает твой radio.py каждые 90 секунд"""
        for attempt in range(3):
            res = await self.download(identifier)
            if res.success:
                return res
            # Если ошибка в URL, делаем паузу и пробуем снова
            await asyncio.sleep(2)
        return DownloadResult(success=False, error="Failed after retries")

    async def download(self, identifier: str) -> DownloadResult:
        # 1. Очистка идентификатора. Убираем всё лишнее, оставляем только 11 знаков ID.
        video_id = identifier.strip()
        if "youtube.com" in video_id:
            # Если случайно прилетела ссылка, вырезаем ID
            video_id = video_id.split("v=")[-1][:11]
        
        # Если это не ID, а запрос (редкий случай для радио)
        if not self.YT_ID_RE.match(video_id):
            found = await self.search(video_id, limit=1)
            if not found: return DownloadResult(success=False, error="ID not found")
            video_id = found[0].identifier

        cache_key = f"yt:{video_id}"
        cached = await self._cache.get(cache_key, Source.YOUTUBE)
        if cached and Path(cached.file_path).exists():
            return cached

        # 2. Формируем URL ПРАВИЛЬНО (со слэшем и параметром watch?v=)
        url = f"www.youtube.com{video_id}"
        
        # Лог для проверки в консоли Railway
        logger.info(f"--- STARTING DOWNLOAD: {url} ---")

        opts = self._get_opts(is_search=False)
        try:
            async with self.semaphore:
                loop = asyncio.get_running_loop()
                # Тайм-аут 80 секунд, чтобы радио не зависло
                info = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=True)),
                    timeout=80.0
                )

            file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            
            result = DownloadResult(
                success=True,
                file_path=str(file_path),
                title=info.get("title", "Unknown"),
                duration=int(info.get("duration", 0)),
                identifier=video_id
            )
            await self._cache.set(cache_key, result, Source.YOUTUBE)
            return result
        except Exception as e:
            logger.error(f"DOWNLOAD FAIL for {video_id}: {e}")
            return DownloadResult(success=False, error=str(e))
