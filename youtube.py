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
            # Важно: используем только YouTube экстрактор
            "allowed_extractors": ["youtube", "youtube:search"],
        }
        if is_search:
            opts["extract_flat"] = True
        else:
            opts.update({
                "format": "bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
            })
        return opts

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        search_query = f"ytsearch{limit}:{query} -live -stream"
        try:
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(self._get_opts(True)).extract_info(search_query, download=False))
            return [
                TrackInfo(
                    title=e.get("title", "Unknown"),
                    artist=e.get("uploader") or "Unknown",
                    duration=int(e.get("duration") or 0),
                    source=Source.YOUTUBE.value,
                    identifier=e["id"],
                ) for e in info.get("entries", []) if e and e.get("id")
            ]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def download_with_retry(self, identifier: str) -> DownloadResult:
        for attempt in range(2):
            res = await self.download(identifier)
            if res.success: return res
            await asyncio.sleep(2)
        return DownloadResult(success=False, error="Retry failed")

    async def download(self, identifier: str) -> DownloadResult:
        # ПРИНУДИТЕЛЬНАЯ ОЧИСТКА ID
        video_id = str(identifier).strip()
        if "youtube.com" in video_id:
            video_id = video_id.split("v=")[-1][:11]
        
        # ФОРМИРОВАНИЕ ГАРАНТИРОВАННОГО URL
        # Добавляем /watch?v= вручную
        url = f"www.youtube.com{video_id}"
        
        # ЭТОТ ЛОГ ПОЯВИТСЯ В RAILWAY КОНСОЛИ
        logger.info(f"--- ATTEMPTING URL: {url} ---")

        cache_key = f"yt:{video_id}"
        cached = await self._cache.get(cache_key, Source.YOUTUBE)
        if cached and Path(cached.file_path).exists(): return cached

        try:
            async with self.semaphore:
                loop = asyncio.get_running_loop()
                # Тайм-аут 80 сек для соблюдения такта 90 сек
                info = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(self._get_opts()).extract_info(url, download=True)),
                    timeout=80.0
                )
            file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            res = DownloadResult(success=True, file_path=str(file_path), title=info["title"], duration=int(info["duration"]), identifier=video_id)
            await self._cache.set(cache_key, res, Source.YOUTUBE)
            return res
        except Exception as e:
            logger.error(f"DOWNLOAD FAIL: {e}")
            return DownloadResult(success=False, error=str(e))
