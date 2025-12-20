from __future__ import annotations
import asyncio
import glob
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yt_dlp
from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache import CacheService

logger = logging.getLogger(__name__)

class SilentLogger:
    """A silent logger that discards all messages."""
    def debug(self, msg):
        # For compatibility, yt-dlp expects these methods.
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass

class YouTubeDownloader:
    YT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self.semaphore = asyncio.Semaphore(3)

    def _get_opts(self, mode: str = "download") -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_progress": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,
            "source_address": "0.0.0.0",
            "no_check_certificate": True,
            "geo_bypass": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "logger": SilentLogger(),  # Use the silent logger
        }
        
        # Add cookie support to prevent "Sign in to confirm you're not a bot" errors
        if self._settings.COOKIES_FILE.exists() and self._settings.COOKIES_FILE.stat().st_size > 0:
            opts['cookiefile'] = str(self._settings.COOKIES_FILE)

        if mode == "search":
            opts.update({"extract_flat": "in_playlist", "skip_download": True})
        elif mode == "download":
            opts.update({
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
                "writeinfojson": True,
                "max_filesize": self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024,
            })
        return opts

    async def _extract_info(self, query: str, opts: Dict[str, Any]) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(query, download=False))

    def _find_downloaded_file(self, video_id: str) -> Optional[str]:
        pattern = str(self._settings.DOWNLOADS_DIR / f"{video_id}.mp3")
        files = glob.glob(pattern)
        return files[0] if files else None

    async def search(self, query: str, limit: int = 30, **kwargs) -> List[TrackInfo]:
        logger.info(f"[Search] Запуск поиска для: '{query}'")
        
        try:
            is_genre_query = len(query.split()) <= 3
            
            def filter_entry(entry: Dict[str, Any]) -> bool:
                """Unified filter for YouTube search results."""
                if not (entry and entry.get("id") and len(entry.get("id")) == 11 and entry.get("title")):
                    return False
                
                title = entry.get('title', '').lower()
                duration = int(entry.get('duration') or 0)

                # Determine duration limits based on query type
                if is_genre_query:
                    min_dur, max_dur = self._settings.PLAY_MIN_GENRE_DURATION_S, self._settings.PLAY_MAX_GENRE_DURATION_S
                else:
                    min_dur, max_dur = self._settings.PLAY_MIN_SONG_DURATION_S, self._settings.PLAY_MAX_SONG_DURATION_S

                if not (min_dur <= duration <= max_dur):
                    return False

                # A less strict ban list, focusing on non-musical content
                BANNED_KEYWORDS = ['karaoke', 'vlog', 'parody', 'reaction', 'tutorial', 'commentary']
                if any(b in title for b in BANNED_KEYWORDS):
                    return False
                
                return True

            # Use a single, broader search and filter results in Python.
            # Crucially, always filter out live streams at the yt-dlp level.
            search_query = f"ytsearch{limit}:{query}"
            opts = self._get_opts("search")
            opts['match_filter'] = yt_dlp.utils.match_filter_func("!is_live")
            
            info = await self._extract_info(search_query, opts)
            entries = info.get("entries", []) or []

            # Process and filter the results
            results = [TrackInfo.from_yt_info(e) for e in entries if filter_entry(e)]

            logger.info(f"[Search] Найдено и отфильтровано: {len(results)} треков.")
            return results[:limit]

        except Exception as e:
            logger.error(f"[Search] Критическая ошибка: {e}", exc_info=True)
            return []

    async def download(self, video_id: str) -> DownloadResult:
        try:
            cache_key = f"yt:{video_id}"
            cached = await self._cache.get(cache_key, Source.YOUTUBE)
            if cached and Path(cached.file_path).exists(): return cached
            elif cached: await self._cache.delete(cache_key)

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            # --- Pre-download Duration Check (as a preliminary filter) ---
            info_for_check = await self._extract_info(video_url, self._get_opts("search"))
            track_info_from_download = TrackInfo.from_yt_info(info_for_check)
            if track_info_from_download.duration and track_info_from_download.duration > self._settings.PLAY_MAX_GENRE_DURATION_S:
                return DownloadResult(success=False, error=f"Видео слишком длинное ({track_info_from_download.duration / 60:.1f} мин.)")
            # --- End Pre-download Check ---

            loop = asyncio.get_running_loop()
            download_opts = self._get_opts("download")
            download_task = loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(download_opts).download([video_url]))
            await asyncio.wait_for(download_task, timeout=float(self._settings.DOWNLOAD_TIMEOUT_S))

            final_path = self._find_downloaded_file(video_id)
            if not final_path:
                 return DownloadResult(success=False, error="Файл не был создан после скачивания.")
            if Path(final_path).stat().st_size > (self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024):
                Path(final_path).unlink(missing_ok=True)
                return DownloadResult(success=False, error="Финальный файл превысил лимит размера")

            result = DownloadResult(True, str(final_path), track_info_from_download)
            await self._cache.set(cache_key, Source.YOUTUBE, result)
            return result
        except asyncio.TimeoutError:
            logger.error(f"Скачивание видео {video_id} превысило таймаут {self._settings.DOWNLOAD_TIMEOUT_S}с.")
            # Попытка очистить частичные файлы
            for partial_file in glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*")):
                try: Path(partial_file).unlink(missing_ok=True)
                except OSError: pass
            return DownloadResult(success=False, error="Превышен таймаут скачивания")
        except Exception as e:
            logger.error(f"Критическая ошибка скачивания: {e}", exc_info=True)
            return DownloadResult(success=False, error=str(e))

    async def download_with_retry(self, query: str) -> DownloadResult:
        for attempt in range(self._settings.MAX_RETRIES):
            try:
                result = await self.download(query)
                if result.success: return result
                if "слишком большой" in (result.error or ""): return result
            except Exception as e:
                logger.error(f"[Downloader] Попытка {attempt+1}: {e}")
            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S)
        return DownloadResult(success=False, error="Не удалось скачать.")