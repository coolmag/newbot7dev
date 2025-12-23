from __future__ import annotations
import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal
import tempfile # Added tempfile

import yt_dlp
from config import Settings
from models import StreamInfoResult, Source, TrackInfo, StreamInfo
from database import DatabaseService

logger = logging.getLogger(__name__)

SearchMode = Literal['track', 'artist', 'genre']

class SilentLogger:
    """A silent logger that discards all messages."""
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class YouTubeDownloader:
    YT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")

    def __init__(self, settings: Settings):
        self._settings = settings
        self.semaphore = asyncio.Semaphore(10)
        self.search_semaphore = asyncio.Semaphore(5)

    def _get_opts(self, mode: str = "search") -> Dict[str, Any]:
        """Gets yt-dlp options based on mode."""
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_progress": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,
            "source_address": "0.0.0.0",
            "no_check_certificate": True,
            "geo_bypass": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "logger": SilentLogger(),
            "retries": 3,
            "fragment_retries": 3,
        }
        
        if self._settings.COOKIES_FILE.exists() and self._settings.COOKIES_FILE.stat().st_size > 0:
            opts['cookiefile'] = str(self._settings.COOKIES_FILE)

        if mode == "search":
            opts.update({
                "extract_flat": True,
                "skip_download": True,
                "socket_timeout": 10,
            })
        elif mode == "stream_info":
            opts.update({
                "format": "bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
                "skip_download": True, # Do not download the file
            })
        elif mode == "download":
            opts.update({
                "format": "bestaudio/best", # Get the best audio
                "extract_audio": True,
                "audio_format": "mp3", # Convert to mp3
                "audio_quality": 0, # Best quality
                "outtmpl": {
                    "default": str(self._settings.TEMP_DIR / "%(id)s.%(ext)s") # Save to temp dir
                },
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",
                }],
                "force_keyframes_at_cuts": True, # For more precise seeking
            })
        return opts

    async def _extract_info(self, query: str, opts: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts info from YouTube with timeout."""
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(query, download=False)),
                timeout=20.0  # Reduced timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при извлечении информации для '{query}'")
            raise

    async def get_stream_info(self, video_id: str) -> StreamInfoResult:
        """
        Gets metadata and a direct streamable URL for a video.
        Does NOT download the file.
        """
        async with self.semaphore:
            try:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                opts = self._get_opts("stream_info")
                
                info = await self._extract_info(video_url, opts)
                
                if not info:
                    return StreamInfoResult(success=False, error="Could not extract video info.")

                # yt-dlp with 'bestaudio/best' might return a single dictionary
                # or a list of formats. We need to find the URL from the processed info.
                stream_url = info.get("url")
                if not stream_url:
                    return StreamInfoResult(success=False, error="No stream URL found in metadata.")

                track_info = TrackInfo.from_yt_info(info)
                
                # Check duration constraints
                if not (self._settings.TRACK_MIN_DURATION_S <= track_info.duration <= self._settings.GENRE_MAX_DURATION_S):
                     return StreamInfoResult(success=False, error=f"Track duration ({track_info.duration}s) is outside acceptable limits.")

                stream_info = StreamInfo(stream_url=stream_url, track_info=track_info)
                
                logger.info(f"[Stream] Got stream info for {video_id}")
                return StreamInfoResult(success=True, stream_info=stream_info)

            except Exception as e:
                logger.error(f"[Stream] Critical error for {video_id}: {e}", exc_info=True)
                return StreamInfoResult(success=False, error=str(e))

    async def download_track_audio(self, track_info: TrackInfo) -> Optional[Path]:
        """
        Downloads the audio for a given TrackInfo to a temporary MP3 file.
        Returns the path to the downloaded file, or None if failed.
        """
        async with self.semaphore:
            try:
                video_url = f"https://www.youtube.com/watch?v={track_info.identifier}"
                opts = self._get_opts("download")
                
                # Ensure the temp directory exists
                self._settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)

                # yt-dlp will save to {TEMP_DIR}/{id}.mp3
                expected_filepath = self._settings.TEMP_DIR / f"{track_info.identifier}.mp3"
                
                logger.info(f"[Download] Starting download for {track_info.identifier} to {expected_filepath}")

                # Use a specific YDL instance for downloading
                ydl = yt_dlp.YoutubeDL(opts)
                loop = asyncio.get_running_loop()
                
                # Log yt-dlp options for debugging
                logger.debug(f"[Download] yt-dlp options: {opts}")

                info = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: ydl.extract_info(video_url, download=True)),
                    timeout=self._settings.TRACK_MAX_DURATION_S * 2 # Allow up to double the track duration for download
                )
                
                if expected_filepath.is_file() and expected_filepath.stat().st_size > 0:
                    logger.info(f"[Download] Successfully downloaded {track_info.identifier} to {expected_filepath}. Size: {expected_filepath.stat().st_size} bytes")
                    return expected_filepath
                else:
                    logger.error(f"[Download] Download failed or file is empty for {track_info.identifier}. Expected path: {expected_filepath}")
                    return None
            except asyncio.TimeoutError:
                logger.error(f"[Download] Timeout during download for {track_info.identifier}")
                return None
            except Exception as e:
                logger.error(f"[Download] Critical error during download for {track_info.identifier}: {e}", exc_info=True)
                return None

    async def search(
        self, 
        query: str, 
        search_mode: SearchMode = 'track', 
        limit: int = 30
    ) -> List[TrackInfo]:
        # This method remains largely the same, as it only fetches metadata.
        # I've removed the playlist-specific search logic for simplicity as it was buggy.
        async with self.search_semaphore:
            logger.info(f"[Search] Запуск поиска для: '{query}' (режим: {search_mode})")
            
            try:
                def filter_entry(entry: Dict[str, Any]) -> bool:
                    if not (entry and entry.get("id") and len(entry.get("id")) == 11 and entry.get("title")):
                        return False
                    title = entry.get('title', '').lower()
                    duration = int(entry.get('duration') or 0)
                    if search_mode == 'genre':
                        min_dur, max_dur = self._settings.GENRE_MIN_DURATION_S, self._settings.GENRE_MAX_DURATION_S
                    else:
                        min_dur, max_dur = self._settings.TRACK_MIN_DURATION_S, self._settings.TRACK_MAX_DURATION_S
                    if not (min_dur <= duration <= max_dur):
                        return False
                    BANNED_KEYWORDS = ['karaoke', 'vlog', 'parody', 'reaction', 'tutorial', 'commentary']
                    if search_mode == 'artist':
                        BANNED_KEYWORDS.extend(['cover'])
                    if any(keyword in title for keyword in BANNED_KEYWORDS):
                        return False
                    return True

                opts = self._get_opts("search")
                opts['match_filter'] = yt_dlp.utils.match_filter_func("!is_live")
                
                # Simplified search logic
                search_query = f"ytsearch{limit}:{query}"
                if search_mode == 'genre':
                    search_query += " mix" # Add "mix" for better genre results
                
                info = await self._extract_info(search_query, opts)
                entries = info.get("entries", []) or []
                
                final_results = [TrackInfo.from_yt_info(e) for e in entries if filter_entry(e)]

                logger.info(f"[Search] Найдено и отфильтровано: {len(final_results)} треков.")
                return final_results[:limit]

            except Exception as e:
                logger.error(f"[Search] Критическая ошибка: {e}", exc_info=True)
                return []