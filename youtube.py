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
    # Строгая проверка ID (11 символов)
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
            # ВАЖНО: Принудительно заставляем использовать только YouTube экстрактор
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

    async def search(self, query: str, limit: int = 10) -> List[TrackInfo]:
        # Используем префикс ytsearch для 100% точности
        search_query = f"ytsearch{limit}:{query}"
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
                        identifier=str(e["id"]).strip(), # Чистим ID
                    ))
            return tracks
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def download_with_retry(self, identifier: str) -> DownloadResult:
        # radio.py передает идентификатор (ID)
        for attempt in range(3):
            res = await self.download(identifier)
            if res.success: return res
            await asyncio.sleep(2)
        return DownloadResult(success=False, error="Failed after retries")

    async def download(self, identifier: str) -> DownloadResult:
        # 1. ОЧИСТКА. Если в identifier пришло "www.youtube.comXXXX", мы заберем только XXXX
        raw_id = identifier.strip()
        if "youtube.com" in raw_id:
            video_id = raw_id.split("/")[-1].replace("watch?v=", "")
        else:
            video_id = raw_id

        # Валидация ID
        if not self.YT_ID_RE.match(video_id):
            # Если это не ID, а поисковый запрос - ищем ID
            found = await self.search(video_id, limit=1)
            if not found: return DownloadResult(success=False, error="Invalid ID")
            video_id = found[0].identifier

        cache_key = f"yt:{video_id}"
        cached = await self._cache.get(cache_key, Source.YOUTUBE)
        if cached and Path(cached.file_path).exists(): return cached

        # 2. ФОРМИРОВАНИЕ URL (Используем короткий домен, его невозможно сломать)
        url = f"youtu.be{video_id}"
        logger.info(f"--- PRO ATTEMPT: Downloading {url} ---")

        try:
            async with self.semaphore:
                loop = asyncio.get_running_loop()
                info = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(self._get_opts()).extract_info(url, download=True)),
                    timeout=90.0
                )

            file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            return DownloadResult(
                success=True, file_path=str(file_path),
                title=info.get("title", "Unknown"),
                duration=int(info.get("duration", 0)),
                identifier=video_id
            )
        except Exception as e:
            logger.error(f"FAIL: {e}")
            return DownloadResult(success=False, error=str(e))
