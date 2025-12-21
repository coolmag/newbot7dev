from __future__ import annotations
import asyncio
import glob
import logging
import re
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal, Set

import yt_dlp
from config import Settings
from models import DownloadResult, Source, TrackInfo
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

    def __init__(self, settings: Settings, db_service: DatabaseService):
        self._settings = settings
        self._db = db_service
        # Increased semaphore to prevent deadlock
        self.semaphore = asyncio.Semaphore(10)
        # Separate semaphore for search to avoid blocking downloads
        self.search_semaphore = asyncio.Semaphore(5)

    def _get_opts(self, mode: str = "download") -> Dict[str, Any]:
        """Gets yt-dlp options based on mode."""
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_progress": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30, # Increased socket timeout
            "source_address": "0.0.0.0",
            "no_check_certificate": True,
            "geo_bypass": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "logger": SilentLogger(),
            # Options for stability
            "retries": 10, # Increased retries
            "fragment_retries": 10,
        }
        
        if self._settings.COOKIES_FILE.exists() and self._settings.COOKIES_FILE.stat().st_size > 0:
            opts['cookiefile'] = str(self._settings.COOKIES_FILE)

        if mode == "search":
            opts.update({
                "noplaylist": False,  # Allow playlist processing
                "extract_flat": True, # Get basic info for everything
                "skip_download": True,
                "socket_timeout": 15,
            })
        elif mode == "download":
            opts.update({
                "format": "bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "m4a",
                }],
                "writeinfojson": False,
                "max_filesize": self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024,
                "prefer_ffmpeg": True,
                "keepvideo": False,
            })
        return opts

    async def _extract_info(self, query: str, opts: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts info from YouTube with timeout."""
        loop = asyncio.get_running_loop()
        try:
            # Increased timeout for extraction (60s)
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(query, download=False)),
                timeout=60.0 
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout extracting info for '{query}'")
            raise

    def _find_downloaded_file(self, video_id: str) -> Optional[str]:
        """Finds downloaded file for given video ID."""
        base_path = self._settings.DOWNLOADS_DIR / video_id
        for ext in ["m4a", "mp3", "webm", "opus"]:
            file_path = base_path.with_suffix(f".{ext}")
            if file_path.exists(): 
                return str(file_path)
        return None

    async def search(
        self, 
        query: str, 
        search_mode: SearchMode = 'track', 
        limit: int = 30
    ) -> List[TrackInfo]:
        """
        Optimized search with efficient duplicate handling.
        """
        async with self.search_semaphore:
            logger.info(f"[Search] Starting search for: '{query}' (mode: {search_mode})")
            
            final_results: List[TrackInfo] = []
            seen_ids: Set[str] = set()

            try:
                def filter_entry(entry: Dict[str, Any]) -> bool:
                    """Filters out invalid/unwanted entries."""
                    if not (entry and entry.get("id") and len(entry.get("id")) == 11 and entry.get("title")):
                        return False
                    
                    title = entry.get('title', '').lower()
                    duration = int(entry.get('duration') or 0)

                    # Determine duration limits
                    if search_mode == 'genre':
                        min_dur = self._settings.GENRE_MIN_DURATION_S
                        max_dur = self._settings.GENRE_MAX_DURATION_S
                    else:
                        min_dur = self._settings.TRACK_MIN_DURATION_S
                        max_dur = self._settings.TRACK_MAX_DURATION_S

                    if not (min_dur <= duration <= max_dur):
                        return False

                    BANNED_KEYWORDS = ['karaoke', 'vlog', 'parody', 'reaction', 'tutorial', 'commentary']
                    if search_mode == 'artist':
                        BANNED_KEYWORDS.extend(['cover'])
                    
                    if any(keyword in title for keyword in BANNED_KEYWORDS):
                        return False
                    
                    return True

                def process_entries(entries_list: List[Dict[str, Any]]) -> List[TrackInfo]:
                    """Processes raw entries, filters them, and avoids duplicates."""
                    processed = []
                    for e in entries_list:
                        if filter_entry(e):
                            vid_id = e.get("id")
                            if vid_id not in seen_ids:
                                track = TrackInfo.from_yt_info(e)
                                processed.append(track)
                                seen_ids.add(vid_id)
                    return processed

                opts = self._get_opts("search")
                opts['match_filter'] = yt_dlp.utils.match_filter_func("!is_live")
                
                # --- STRATEGY: GENRE ---
                if search_mode == 'genre':
                    logger.info(f"[Search] Genre strategy: Playlist priority.")
                    
                    playlist_opts = opts.copy()
                    playlist_opts['default_search'] = 'ytsearch' # FIXED: Changed from invalid ytsearchplaylist
                    playlist_opts['noplaylist'] = False
                    playlist_opts['extract_flat'] = True
                    
                    # 1. Try finding playlists
                    try:
                        # FIXED: Changed invalid protocol to standard ytsearch5
                        playlist_search_query = f"ytsearch5:{query} playlist" 
                        playlist_info = await self._extract_info(playlist_search_query, playlist_opts)
                        
                        if playlist_info and playlist_info.get('entries'):
                            logger.info(f"[Search] Found {len(playlist_info['entries'])} items for '{query}' playlist search.")
                            
                            for playlist_entry in playlist_info['entries']:
                                if len(final_results) >= limit:
                                    break
                                
                                # Check if it's actually a playlist or a video that acts as a mix
                                if playlist_entry.get('_type') == 'playlist' and playlist_entry.get('url'):
                                    logger.info(f"[Search] Extracting tracks from playlist: {playlist_entry.get('title')}")
                                    try:
                                        playlist_content_opts = self._get_opts("search").copy()
                                        playlist_content_opts['extract_flat'] = False 
                                        playlist_content_opts['noplaylist'] = False
                                        
                                        content_info = await self._extract_info(playlist_entry['url'], playlist_content_opts)
                                        
                                        if content_info and content_info.get('entries'):
                                            newly_processed = process_entries(content_info['entries'])
                                            final_results.extend(newly_processed)
                                            logger.info(f"[Search] Added {len(newly_processed)} tracks from playlist.")
                                    except Exception as e:
                                        logger.warning(f"[Search] Error extracting playlist content: {e}")

                    except Exception as e:
                        logger.warning(f"[Search] Error searching playlists for '{query}': {e}")

                    # 2. Fallback: Themed searches (Crucial for Genres)
                    if len(final_results) < limit:
                        logger.info(f"[Search] Insufficient results from playlists, switching to themed search.")
                        queries_to_try = [query, f"{query} mix", f"{query} playlist"]
                        
                        for themed_query in queries_to_try:
                            if len(final_results) >= limit:
                                break
                                
                            try:
                                info = await self._extract_info(f"ytsearch{limit}:{themed_query}", opts)
                                newly_processed = process_entries(info.get("entries", []) or [])
                                final_results.extend(newly_processed)
                            except Exception as e:
                                logger.warning(f"[Search] Error on fallback query '{themed_query}': {e}")
                
                # --- STRATEGY: ARTIST ---
                elif search_mode == 'artist':
                    logger.info(f"[Search] Artist strategy: {query}")
                    suffixes = ["official audio", "topic", "", "live", "album", "remix"]
                    
                    for suffix in suffixes:
                        if len(final_results) >= limit:
                            break

                        themed_query = f"{query} {suffix}".strip()
                        try:
                            info = await self._extract_info(f"ytsearch10:{themed_query}", opts)
                            newly_processed = process_entries(info.get("entries", []) or [])
                            final_results.extend(newly_processed)
                            
                            if newly_processed:
                                logger.info(f"[Search] Added {len(newly_processed)} tracks for '{themed_query}'")
                        except Exception as e:
                            logger.warning(f"[Search] Error on artist query '{themed_query}': {e}")
                
                # --- STRATEGY: TRACK ---
                else:
                    try:
                        info = await self._extract_info(f"ytsearch{limit}:{query}", opts)
                        final_results = process_entries(info.get("entries", []) or [])
                    except Exception as e:
                        logger.error(f"[Search] Track search error: {e}")
                        return []

                logger.info(f"[Search] Total found: {len(final_results)} tracks.")
                return final_results[:limit]

            except Exception as e:
                logger.error(f"[Search] Critical search error: {e}", exc_info=True)
                return []

    async def download(self, video_id: str) -> DownloadResult:
        """
        Downloads a track with retry logic and duration checks.
        """
        async with self.semaphore:
            try:
                # Cache Check
                cache_key = f"yt:{video_id}"
                cached = await self._db.get(cache_key, Source.YOUTUBE)
                
                if cached and cached.file_path and Path(cached.file_path).exists():
                    logger.debug(f"[Download] Cache hit for {video_id}")
                    return cached
                elif cached:
                    logger.warning(f"[Download] Cache entry exists but file missing for {video_id}. Removing entry.")
                    asyncio.create_task(self._db.blacklist_track_id(video_id))

                video_url = f"https://www.youtube.com/watch?v={video_id}"
                track_info_from_download: Optional[TrackInfo] = None
                
                # Pre-check duration
                try:
                    info_for_check = await asyncio.wait_for(
                        self._extract_info(video_url, self._get_opts("search")),
                        timeout=20.0
                    )
                    track_info_from_download = TrackInfo.from_yt_info(info_for_check)
                    
                    if track_info_from_download.duration and track_info_from_download.duration > self._settings.GENRE_MAX_DURATION_S:
                        return DownloadResult(
                            success=False, 
                            error=f"Video too long ({track_info_from_download.duration / 60:.1f} min)"
                        )
                except asyncio.TimeoutError:
                    logger.warning(f"[Download] Timeout checking duration for {video_id}. Proceeding anyway.")
                except Exception as e:
                    logger.warning(f"[Download] Failed to check duration for {video_id}: {e}")

                # Download Loop
                max_retries = 2 
                for attempt in range(max_retries + 1):
                    try:
                        loop = asyncio.get_running_loop()
                        download_opts = self._get_opts("download")
                        
                        download_task = loop.run_in_executor(
                            None, 
                            lambda: yt_dlp.YoutubeDL(download_opts).download([video_url])
                        )
                        
                        # FIXED: Increased timeout from 30.0 to 300.0 (5 minutes) for long mixes
                        await asyncio.wait_for(download_task, timeout=300.0)
                        
                        final_path = self._find_downloaded_file(video_id)
                        if not final_path:
                            raise FileNotFoundError("File not found after download")
                        
                        # Post-download size check
                        try:
                            file_size = Path(final_path).stat().st_size
                            max_size = self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024
                            if file_size > max_size:
                                Path(final_path).unlink(missing_ok=True)
                                return DownloadResult(
                                    success=False, 
                                    error=f"File size exceeded ({file_size / 1024 / 1024:.1f}MB)"
                                )
                        except Exception as e:
                            logger.warning(f"Error checking file size: {e}")

                        # Create result
                        final_track_info = track_info_from_download if track_info_from_download else TrackInfo(
                            title="Unknown",
                            artist="Unknown",
                            duration=0,
                            source=Source.YOUTUBE.value,
                            identifier=video_id
                        )

                        result = DownloadResult(
                            success=True, 
                            file_path=str(final_path), 
                            track_info=final_track_info
                        )
                        
                        await self._db.set(cache_key, Source.YOUTUBE, result)
                        logger.info(f"[Download] Successfully downloaded {video_id} (attempt {attempt + 1})")
                        return result
                        
                    except asyncio.TimeoutError:
                        logger.warning(f"[Download] Download timeout {video_id} (attempt {attempt + 1})")
                        self._cleanup_partial_files(video_id)
                        if attempt < max_retries:
                            await asyncio.sleep(5) # Increased sleep
                            continue
                        return DownloadResult(success=False, error="Download timeout exceeded")
                    
                    except Exception as e:
                        logger.error(f"[Download] Error downloading {video_id} (attempt {attempt + 1}): {e}")
                        self._cleanup_partial_files(video_id)
                        if attempt < max_retries:
                            await asyncio.sleep(5)
                            continue
                        return DownloadResult(success=False, error=str(e))

            except Exception as e:
                logger.error(f"[Download] Critical error for {video_id}: {e}", exc_info=True)
                return DownloadResult(success=False, error=str(e))

    def _cleanup_partial_files(self, video_id: str):
        """Cleans up partial/incomplete download files."""
        try:
            for partial_file in glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*")):
                try:
                    path = Path(partial_file)
                    # Only delete temporary/partial extensions
                    if any(path.name.endswith(ext) for ext in ['.part', '.ytdl', '.temp', '.f251', '.f140']):
                        path.unlink(missing_ok=True)
                        logger.debug(f"[Cleanup] Deleted partial file: {partial_file}")
                except OSError as e:
                    logger.warning(f"[Cleanup] Failed to delete {partial_file}: {e}")
        except Exception as e:
            logger.error(f"[Cleanup] Error during cleanup for {video_id}: {e}")
