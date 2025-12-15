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
        self.semaphore = asyncio.Semaphore(3)

    def _get_opts(self, is_search: bool) -> Dict[str, Any]:
        options = {
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "source_address": "0.0.0.0",
            "no_check_certificate": True,
            "prefer_insecure": True,
            "noplaylist": True,
            "geo_bypass": True,
            "extractor_args": {'youtube': {'player_client': ['android', 'web']}},
        }
        if is_search:
            options["extract_flat"] = True
        else:
            options.update({
                "format": "bestaudio/best",
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
            })
            if self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
                options["cookiefile"] = str(self._settings.COOKIES_FILE)
        return options

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        """
        Интеллектуальный поиск как в старой версии.
        """
        # Формируем 'умный' запрос
        smart_query = f"{query} official audio topic lyrics"
        opts = self._get_opts(is_search=True)
        
        try:
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(
                None, lambda: yt_dlp.YoutubeDL(opts).extract_info(f"ytsearch{limit}:{smart_query}", download=False)
            )
            entries = info.get("entries", []) or []
            
            out = []
            for e in entries:
                if not e or not e.get("id"): continue
                
                title = e.get('title', '').lower()
                # Фильтр мусора
                if any(bad in title for bad in ['live', 'short', 'концерт', 'mix', 'сборник', 'radio']):
                    continue
                
                out.append(TrackInfo(
                    title=e.get("title", "Unknown"),
                    artist=e.get("channel") or e.get("uploader") or "Unknown",
                    duration=int(e.get("duration") or 0),
                    source=Source.YOUTUBE.value,
                    identifier=e["id"],
                ))
            return out
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def download_with_retry(self, query: str) -> DownloadResult:
        """Логика ретраев из старой версии."""
        max_retries = getattr(self._settings, "MAX_RETRIES", 3)
        for attempt in range(max_retries):
            try:
                async with self.semaphore:
                    result = await self.download(query)
                if result and result.success:
                    return result
            except Exception as e:
                logger.error(f"Attempt {attempt} failed: {e}")
            
            await asyncio.sleep(2 * (attempt + 1))
        
        return DownloadResult(success=False, error="Failed after retries")

    async def download(self, query_or_id: str) -> DownloadResult:
        """
        Исправленный метод загрузки с корректным URL.
        """
        video_id = query_or_id.strip()
        
        # Если пришел не ID, а текст — ищем ID
        if not self.YT_ID_RE.match(video_id):
            found = await self.search(video_id, limit=1)
            if not found: return DownloadResult(success=False, error="Not found")
            video_id = found[0].identifier

        cache_key = f"yt:{video_id}"
        cached = await self._cache.get(cache_key, Source.YOUTUBE)
        if cached and Path(cached.file_path).exists():
            return cached

        # ИСПРАВЛЕНО: Теперь URL формируется правильно (с /watch?v=)
        url = f"www.youtube.com{video_id}"
        opts = self._get_opts(is_search=False)

        try:
            loop = asyncio.get_running_loop()
            # Тайм-аут 80 сек, чтобы бот не висел вечно
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
            logger.error(f"Download error: {e}")
            return DownloadResult(success=False, error=str(e))
