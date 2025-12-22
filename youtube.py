from __future__ import annotations
import asyncio
import glob
import logging
import re
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal

import yt_dlp
import aioboto3
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

    def __init__(
        self,
        settings: Settings,
        db_service: DatabaseService,
        s3_session: Optional[aioboto3.Session] = None,
    ):
        self._settings = settings
        self._db = db_service
        self._s3_session = s3_session
        # 🆕 Увеличен семафор для предотвращения deadlock
        self.semaphore = asyncio.Semaphore(10)  # Было 3, теперь 10
        # 🆕 Отдельный семафор для поиска (чтобы не блокировать скачивания)
        self.search_semaphore = asyncio.Semaphore(5)

    def _get_opts(self, mode: str = "download") -> Dict[str, Any]:
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
            # 🆕 Дополнительные опции для стабильности
            "retries": 3,
            "fragment_retries": 3,
        }
        
        if self._settings.COOKIES_FILE.exists() and self._settings.COOKIES_FILE.stat().st_size > 0:
            opts['cookiefile'] = str(self._settings.COOKIES_FILE)

        if mode == "search":
            opts.update({
                "noplaylist": False, # 🆕 Разрешаем обработку плейлистов
                "extract_flat": True, # 🆕 Получаем базовую информацию для всего (видео, плейлисты)
                "skip_download": True,
                "socket_timeout": 10,
            })
        elif mode == "download":
            opts.update({
                "format": "bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "m4a",
                }],
                "writeinfojson": False,  # 🆕 Отключаем JSON для экономии места
                "max_filesize": self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024,
                # 🆕 Оптимизация для скорости
                "prefer_ffmpeg": True,
                "keepvideo": False,
            })
        return opts

    async def _extract_info(self, query: str, opts: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts info from YouTube with timeout."""
        loop = asyncio.get_running_loop()
        # 🆕 Обертка с таймаутом
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(query, download=False)),
                timeout=30.0  # 30 секунд для extract_info
            )
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при извлечении информации для '{query}'")
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
        🆕 УЛУЧШЕННЫЙ ПОИСК с оптимизацией запросов
        """
        async with self.search_semaphore:  # 🆕 Отдельный семафор
            logger.info(f"[Search] Запуск поиска для: '{query}' (режим: {search_mode})")
            
            try:
                def filter_entry(entry: Dict[str, Any]) -> bool:
                    """Filters out invalid/unwanted entries."""
                    if not (entry and entry.get("id") and len(entry.get("id")) == 11 and entry.get("title")):
                        return False
                    
                    title = entry.get('title', '').lower()
                    duration = int(entry.get('duration') or 0)

                    # Определяем лимиты длительности
                    if search_mode == 'genre':
                        min_dur = self._settings.GENRE_MIN_DURATION_S
                        max_dur = self._settings.GENRE_MAX_DURATION_S
                    else: # 'track' or 'artist'
                        min_dur = self._settings.TRACK_MIN_DURATION_S
                        max_dur = self._settings.TRACK_MAX_DURATION_S

                    if not (min_dur <= duration <= max_dur):
                        return False

                    # Фильтрация нежелательных ключевых слов
                    BANNED_KEYWORDS = ['karaoke', 'vlog', 'parody', 'reaction', 'tutorial', 'commentary']
                    
                    # Более строгая фильтрация для артистов
                    if search_mode == 'artist':
                        BANNED_KEYWORDS.extend(['cover'])
                    
                    if any(keyword in title for keyword in BANNED_KEYWORDS):
                        return False
                    
                    return True

                opts = self._get_opts("search")
                opts['match_filter'] = yt_dlp.utils.match_filter_func("!is_live")
                
                final_results = []
                
                # 🆕 ОПТИМИЗИРОВАННЫЕ СТРАТЕГИИ ПОИСКА
                if search_mode == 'genre':
                    logger.info(f"[Search] Жанровый поиск, стратегия: приоритет плейлистов.")
                    
                    def process_entries(entries_list: List[Dict[str, Any]]) -> List[TrackInfo]:
                        processed = []
                        for e in entries_list:
                            if filter_entry(e):
                                # Check for duplicates before adding
                                if e.get("id") not in {r.identifier for r in final_results}:
                                    processed.append(TrackInfo.from_yt_info(e))
                        return processed

                    playlist_opts = opts.copy()
                    playlist_opts['default_search'] = 'ytsearchplaylist'
                    playlist_opts['noplaylist'] = False # Explicitly allow playlist processing
                    playlist_opts['extract_flat'] = True # Get basic info for playlists
                    
                    # 1. Попытка поиска плейлистов
                    try:
                        playlist_search_query = f"ytsearchplaylist5:{query} playlist" # Ищем до 5 плейлистов
                        playlist_info = await self._extract_info(playlist_search_query, playlist_opts)
                        
                        if playlist_info and playlist_info.get('entries'):
                            logger.info(f"[Search] Найдено {len(playlist_info['entries'])} плейлистов по запросу '{query}'.")
                            for playlist_entry in playlist_info['entries']:
                                if len(final_results) >= limit:
                                    break
                                if playlist_entry.get('_type') == 'playlist' and playlist_entry.get('url'):
                                    logger.info(f"[Search] Извлекаю треки из плейлиста: {playlist_entry['title']}")
                                    try:
                                        # Извлекаем данные из самого плейлиста, а не через search
                                        # Для этого нужен ytdl_opts с extract_flat: False для получения entries
                                        playlist_content_opts = self._get_opts("search").copy()
                                        playlist_content_opts['extract_flat'] = False # Get full entries for playlist content
                                        playlist_content_opts['noplaylist'] = False # Ensure it handles it as a playlist URL
                                        
                                        content_info = await self._extract_info(playlist_entry['url'], playlist_content_opts)
                                        
                                        if content_info and content_info.get('entries'):
                                            newly_processed = process_entries(content_info['entries'])
                                            final_results.extend(newly_processed)
                                            logger.info(f"[Search] Добавлено {len(newly_processed)} треков из плейлиста '{playlist_entry['title']}'.")
                                    except Exception as e:
                                        logger.warning(f"[Search] Ошибка при извлечении треков из плейлиста '{playlist_entry['title']}': {e}")

                    except Exception as e:
                        logger.warning(f"[Search] Ошибка поиска плейлистов для '{query}': {e}")

                    # 2. Fallback: поиск тематических треков, если плейлисты не дали достаточно результатов
                    if len(final_results) < limit:
                        logger.info(f"[Search] Недостаточно треков из плейлистов, перехожу к тематическому поиску.")
                        
                        queries_to_try = [
                            query,
                            f"{query} mix",
                            f"{query} playlist"
                        ]
                        
                        for themed_query in queries_to_try:
                            if len(final_results) >= limit:
                                break
                                
                            search_query = f"ytsearch{limit}:{themed_query}"
                            try:
                                info = await self._extract_info(search_query, opts) # Use general opts here
                                entries = info.get("entries", []) or []
                                
                                newly_processed = process_entries(entries)
                                final_results.extend(newly_processed)
                                
                                if newly_processed:
                                    logger.info(f"[Search] Найдено {len(newly_processed)} новых треков с '{themed_query}'")

                            except Exception as e:
                                logger.warning(f"[Search] Ошибка запроса '{themed_query}': {e}")
                                continue
                
                elif search_mode == 'artist':
                    # Для артистов: более глубокий поиск для разнообразия
                    logger.info(f"[Search] Поиск по артисту: {query}")
                    
                    # 🆕 Расширенные суффиксы для более разнообразных результатов
                    for suffix in ["official audio", "topic", "", "live", "album", "remix"]:
                        if len(final_results) >= limit:
                            break

                        themed_query = f"{query} {suffix}".strip()
                        search_query = f"ytsearch10:{themed_query}" # Ищем по 10 на каждый суффикс
                        
                        try:
                            info = await self._extract_info(search_query, opts)
                            entries = info.get("entries", []) or []
                            
                            processed = [TrackInfo.from_yt_info(e) for e in entries if filter_entry(e)]
                            
                            # 🆕 Добавляем только уникальные треки
                            new_tracks = [p for p in processed if p.identifier not in {r.identifier for r in final_results}]
                            final_results.extend(new_tracks)
                            
                            if new_tracks:
                                logger.info(f"[Search] Найдено {len(new_tracks)} треков артиста с '{themed_query}'")

                        except Exception as e:
                            logger.warning(f"[Search] Ошибка поиска артиста '{themed_query}': {e}")
                            continue
                
                else:  # 'track' mode
                    # Для треков: один точный запрос
                    search_query = f"ytsearch{limit}:{query}"
                    
                    try:
                        info = await self._extract_info(search_query, opts)
                        entries = info.get("entries", []) or []
                        final_results = [TrackInfo.from_yt_info(e) for e in entries if filter_entry(e)]
                    except Exception as e:
                        logger.error(f"[Search] Ошибка поиска трека: {e}")
                        return []

                logger.info(f"[Search] Найдено и отфильтровано: {len(final_results)} треков.")
                return final_results[:limit]

            except Exception as e:
                logger.error(f"[Search] Критическая ошибка: {e}", exc_info=True)
                return []

    async def download(self, video_id: str) -> DownloadResult:
        """
        Downloads a track, uploads it to S3, and returns a public URL.
        This version is designed for ephemeral filesystems like Railway.
        """
        async with self.semaphore:
            try:
                # 1. Check cache for a valid S3 URL using video_id as the query
                cached = await self._db.get(video_id, Source.YOUTUBE)
                if cached and cached.url:
                    logger.debug(f"[S3 Download] Using cached URL for {video_id}: {cached.url}")
                    return cached

                # 2. Check if S3 is configured before proceeding
                if not self._s3_session:
                    logger.error("[S3 Download] S3 is not configured. Cannot download track.")
                    return DownloadResult(success=False, error="S3 storage is not configured.")

                # 3. Perform local download using yt-dlp
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                track_info_from_download = None
                try:
                    info_for_check = await asyncio.wait_for(
                        self._extract_info(video_url, self._get_opts("search")),
                        timeout=15.0
                    )
                    track_info_from_download = TrackInfo.from_yt_info(info_for_check)
                    if track_info_from_download.duration and track_info_from_download.duration > self._settings.GENRE_MAX_DURATION_S:
                        return DownloadResult(success=False, error=f"Video is too long ({track_info_from_download.duration / 60:.1f} min.)")
                except Exception as e:
                    logger.warning(f"[S3 Download] Pre-check failed for {video_id}: {e}")
                
                local_path_str = None
                try:
                    loop = asyncio.get_running_loop()
                    download_opts = self._get_opts("download")
                    await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(download_opts).download([video_url])),
                        timeout=45.0
                    )
                    local_path_str = self._find_downloaded_file(video_id)
                    if not local_path_str:
                        raise FileNotFoundError("File not found after yt-dlp download.")
                except Exception as e:
                    logger.error(f"[S3 Download] Local download failed for {video_id}: {e}")
                    self._cleanup_partial_files(video_id)
                    return DownloadResult(success=False, error=f"Local download failed: {e}")

                # 4. Upload the local file to S3
                local_path = Path(local_path_str)
                s3_object_key = f"tracks/{local_path.name}"
                public_url = ""
                
                try:
                    async with self._s3_session.client("s3", endpoint_url=self._settings.S3_ENDPOINT_URL) as s3:
                        logger.info(f"[S3] Uploading {local_path} to {self._settings.S3_BUCKET_NAME}/{s3_object_key}")
                        await s3.upload_file(
                            Filename=str(local_path),
                            Bucket=self._settings.S3_BUCKET_NAME,
                            Key=s3_object_key,
                            ExtraArgs={'ACL': 'public-read', 'ContentType': 'audio/m4a'}
                        )
                    public_url = f"{self._settings.S3_ENDPOINT_URL}/{self._settings.S3_BUCKET_NAME}/{s3_object_key}"
                    logger.info(f"[S3] Upload successful. URL: {public_url}")
                except Exception as e:
                    logger.error(f"[S3] Upload failed for {video_id}: {e}", exc_info=True)
                    return DownloadResult(success=False, error=f"S3 upload failed: {e}")
                finally:
                    # 5. Clean up the local file
                    local_path.unlink(missing_ok=True)
                    self._cleanup_partial_files(video_id)

                # 6. Create and cache the successful result
                if not track_info_from_download:
                     track_info_from_download = TrackInfo(title="Unknown", artist="Unknown", duration=0, source=Source.YOUTUBE.value, identifier=video_id)

                result = DownloadResult(
                    success=True,
                    url=public_url,
                    track_info=track_info_from_download
                )
                # Use video_id as the query for caching
                await self._db.set(video_id, Source.YOUTUBE, result)
                
                return result

            except Exception as e:
                logger.error(f"[S3 Download] Critical error for {video_id}: {e}", exc_info=True)
                return DownloadResult(success=False, error=str(e))

    def _cleanup_partial_files(self, video_id: str):
        """🆕 Cleans up partial/incomplete download files."""
        try:
            for partial_file in glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*")):
                try:
                    path = Path(partial_file)
                    # Удаляем только временные файлы (.part, .ytdl, .temp)
                    if any(path.name.endswith(ext) for ext in ['.part', '.ytdl', '.temp', '.f251', '.f140']):
                        path.unlink(missing_ok=True)
                        logger.debug(f"[Cleanup] Удален partial файл: {partial_file}")
                except OSError as e:
                    logger.warning(f"[Cleanup] Не удалось удалить {partial_file}: {e}")
        except Exception as e:
            logger.error(f"[Cleanup] Ошибка очистки для {video_id}: {e}")