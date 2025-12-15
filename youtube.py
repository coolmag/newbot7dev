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
        # Ограничиваем количество одновременных закачек
        self.semaphore = asyncio.Semaphore(2)

    def _get_opts(self, is_search: bool = False) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,
            "source_address": "0.0.0.0",
            "no_check_certificate": True,
            "geo_bypass": True,
            "retries": 2,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 5, 
            "extractor_args": {'youtube': {'player_client': ['android', 'web']}},
        }

        if getattr(self._settings, "COOKIES_FILE", None) and self._settings.COOKIES_FILE.exists():
            opts["cookiefile"] = str(self._settings.COOKIES_FILE)

        if is_search:
            opts.update({"extract_flat": True})
        else:
            opts.update({
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }],
                "max_filesize": 50 * 1024 * 1024,
            })
        return opts

    async def _extract_info(self, query: str, opts: Dict[str, Any], download: bool = False) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: yt_dlp.YoutubeDL(opts).extract_info(query, download=download)
        )

    async def search(self, query: str, limit: int = 10, **kwargs) -> List[TrackInfo]:
        clean_query = f'{query} -live -radio -stream -24/7 -"10 hours"'
        search_query = f"ytsearch{limit * 2}:{clean_query}"
        opts = self._get_opts(is_search=True)

        try:
            info = await self._extract_info(search_query, opts, download=False)
            entries = info.get("entries", []) or []
            out: List[TrackInfo] = []
            
            BANNED_WORDS = ['ai cover', 'generated', '10 hours', 'full album', 'compilation', 'mix 20']

            for e in entries:
                if not e or not e.get("id"): continue
                duration = int(e.get("duration") or 0)
                if duration < 30 or duration > 600 or e.get("is_live"): continue
                if any(word in e.get("title", "").lower() for word in BANNED_WORDS): continue

                out.append(TrackInfo(
                    title=e.get("title", ""),
                    artist=e.get("channel") or "Unknown",
                    duration=duration,
                    source=Source.YOUTUBE.value,
                    identifier=e["id"],
                ))
                if len(out) >= limit: break
            return out
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def download_with_retry(self, query_or_id: str) -> DownloadResult:
        """Метод, который вызывается из radio.py"""
        max_retries = getattr(self._settings, "MAX_RETRIES", 2)
        retry_delay = getattr(self._settings, "RETRY_DELAY_S", 5)

        for attempt in range(max_retries):
            result = await self.download(query_or_id)
            if result.success:
                return result
            
            # Если ошибка в тайм-ауте или длине, не тратим время на ретраи
            if result.error and ("Timeout" in result.error or "too long" in result.error):
                return result

            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)

        return DownloadResult(success=False, error="Failed after retries.")

    async def download(self, query_or_id: str) -> DownloadResult:
        is_id = self.YT_ID_RE.match(query_or_id) is not None
        video_id = query_or_id if is_id else None

        try:
            if not video_id:
                found = await self.search(query_or_id, limit=1)
                if not found: return DownloadResult(success=False, error="Not found")
                video_id = found[0].identifier

            cache_key = f"yt:{video_id}"
            cached = await self._cache.get(cache_key, Source.YOUTUBE)
            if cached and Path(cached.file_path).exists():
                return cached

            video_url = f"www.youtube.com{video_id}"
            opts = self._get_opts(is_search=False)
            loop = asyncio.get_running_loop()

            async with self.semaphore:
                try:
                    # Ограничиваем время скачивания 85 секундами
                    info = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(video_url, download=True)),
                        timeout=85.0 
                    )
                except asyncio.TimeoutError:
                    return DownloadResult(success=False, error="Timeout: файл слишком тяжелый")

            file_path = self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            if not file_path.exists():
                return DownloadResult(success=False, error="File not created")

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
