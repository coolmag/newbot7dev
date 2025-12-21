from __future__ import annotations
import asyncio
import glob
import logging
import re
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal

import yt_dlp
from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache import CacheService

logger = logging.getLogger(__name__)

SearchMode = Literal['track', 'artist', 'genre']

class SilentLogger:
    """A silent logger that discards all messages."""
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class YouTubeDownloader:
    YT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
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
                "extract_flat": "in_playlist", 
                "skip_download": True,
                "socket_timeout": 10,  # 🆕 Меньший таймаут для поиска
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
                        min_dur = self._settings.PLAY_MIN_GENRE_DURATION_S
                        max_dur = self._settings.PLAY_MAX_GENRE_DURATION_S
                    else:
                        min_dur = self._settings.PLAY_MIN_SONG_DURATION_S
                        max_dur = self._settings.PLAY_MAX_SONG_DURATION_S

                    if not (min_dur <= duration <= max_dur):
                        return False

                    # Фильтрация нежелательных ключевых слов
                    BANNED_KEYWORDS = ['karaoke', 'vlog', 'parody', 'reaction', 'tutorial', 'commentary']
                    
                    # Более строгая фильтрация для артистов
                    if search_mode == 'artist':
                        BANNED_KEYWORDS.extend(['live', 'cover', 'concert', 'performance'])
                    
                    if any(keyword in title for keyword in BANNED_KEYWORDS):
                        return False
                    
                    return True

                opts = self._get_opts("search")
                opts['match_filter'] = yt_dlp.utils.match_filter_func("!is_live")
                
                final_results = []
                
                # 🆕 ОПТИМИЗИРОВАННЫЕ СТРАТЕГИИ ПОИСКА
                if search_mode == 'genre':
                    # Для жанров: меньше запросов, больше результатов
                    logger.info(f"[Search] Жанровый поиск, стратегия: тематические запросы.")
                    
                    # 🆕 Только 2 запроса вместо 6!
                    primary_query = f"{query} mix"
                    secondary_query = f"{query} playlist"
                    
                    for themed_query in [primary_query, secondary_query]:
                        if len(final_results) >= limit:
                            break
                            
                        search_query = f"ytsearch{limit * 2}:{themed_query}"  # Запрашиваем больше
                        
                        try:
                            info = await self._extract_info(search_query, opts)
                            entries = info.get("entries", []) or []
                            
                            processed = [TrackInfo.from_yt_info(e) for e in entries if filter_entry(e)]
                            final_results.extend(processed)
                            
                            if processed:
                                logger.info(f"[Search] Найдено {len(processed)} треков с '{themed_query}'")
                                break  # Достаточно одного успешного запроса
                        except Exception as e:
                            logger.warning(f"[Search] Ошибка запроса '{themed_query}': {e}")
                            continue
                
                elif search_mode == 'artist':
                    # Для артистов: точный поиск официальных треков
                    logger.info(f"[Search] Поиск по артисту: {query}")
                    
                    # 🆕 Упрощенная стратегия
                    for suffix in ["official audio", "topic", ""]:
                        themed_query = f"{query} {suffix}".strip()
                        search_query = f"ytsearch{limit}:{themed_query}"
                        
                        try:
                            info = await self._extract_info(search_query, opts)
                            entries = info.get("entries", []) or []
                            
                            processed = [TrackInfo.from_yt_info(e) for e in entries if filter_entry(e)]
                            
                            if processed:
                                final_results.extend(processed)
                                logger.info(f"[Search] Найдено {len(processed)} треков артиста с '{themed_query}'")
                                break  # Первый успешный = достаточно
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
        🆕 УЛУЧШЕННАЯ ЗАГРУЗКА с retry-логикой и graceful degradation
        """
        async with self.semaphore:
            try:
                # Проверка кеша
                cache_key = f"yt:{video_id}"
                cached = await self._cache.get(cache_key, Source.YOUTUBE)
                
                if cached and cached.file_path and Path(cached.file_path).exists():
                    logger.debug(f"[Download] Использование кеша для {video_id}")
                    return cached
                elif cached:
                    # Запись в кеше есть, но файл отсутствует
                    logger.warning(f"[Download] Файл из кеша отсутствует для {video_id}, удаляем запись")
                    # Не используем await для delete - это не критично
                    try:
                        asyncio.create_task(self._cache.blacklist_track_id(video_id))
                    except:
                        pass

                video_url = f"https://www.youtube.com/watch?v={video_id}"
                
                # 🆕 Быстрая проверка длительности БЕЗ полной загрузки
                try:
                    info_for_check = await asyncio.wait_for(
                        self._extract_info(video_url, self._get_opts("search")),
                        timeout=15.0  # 🆕 Строгий таймаут
                    )
                    track_info_from_download = TrackInfo.from_yt_info(info_for_check)
                    
                    # Проверка длительности
                    if track_info_from_download.duration and track_info_from_download.duration > self._settings.PLAY_MAX_GENRE_DURATION_S:
                        return DownloadResult(
                            success=False, 
                            error=f"Видео слишком длинное ({track_info_from_download.duration / 60:.1f} мин.)"
                        )
                except asyncio.TimeoutError:
                    logger.warning(f"[Download] Таймаут проверки длительности для {video_id}")
                    # Продолжаем загрузку, но с риском
                except Exception as e:
                    logger.warning(f"[Download] Не удалось проверить длительность {video_id}: {e}")
                    # Продолжаем

                # 🆕 RETRY-ЛОГИКА для загрузки
                max_retries = 2
                for attempt in range(max_retries + 1):
                    try:
                        loop = asyncio.get_running_loop()
                        download_opts = self._get_opts("download")
                        
                        # 🆕 Уменьшен таймаут: 60 секунд вместо 120
                        download_task = loop.run_in_executor(
                            None, 
                            lambda: yt_dlp.YoutubeDL(download_opts).download([video_url])
                        )
                        
                        await asyncio.wait_for(download_task, timeout=60.0)
                        
                        # Поиск файла
                        final_path = self._find_downloaded_file(video_id)
                        if not final_path:
                            raise FileNotFoundError("Файл не был создан после скачивания")
                        
                        # Проверка размера
                        file_size = Path(final_path).stat().st_size
                        max_size = self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024
                        
                        if file_size > max_size:
                            Path(final_path).unlink(missing_ok=True)
                            return DownloadResult(
                                success=False, 
                                error=f"Финальный файл превысил лимит размера ({file_size / 1024 / 1024:.1f}MB)"
                            )

                        # Успех!
                        result = DownloadResult(
                            success=True, 
                            file_path=str(final_path), 
                            track_info=track_info_from_download if 'track_info_from_download' in locals() else TrackInfo(
                                title="Unknown",
                                artist="Unknown",
                                duration=0,
                                source=Source.YOUTUBE.value,
                                identifier=video_id
                            )
                        )
                        
                        # Сохраняем в кеш
                        await self._cache.set(cache_key, Source.YOUTUBE, result)
                        logger.info(f"[Download] Успешно скачан {video_id} (попытка {attempt + 1})")
                        return result
                        
                    except asyncio.TimeoutError:
                        logger.warning(f"[Download] Таймаут загрузки {video_id} (попытка {attempt + 1}/{max_retries + 1})")
                        # Очистка partial files
                        self._cleanup_partial_files(video_id)
                        
                        if attempt < max_retries:
                            await asyncio.sleep(2)  # 🆕 Небольшая задержка перед retry
                            continue
                        else:
                            return DownloadResult(
                                success=False, 
                                error="Превышен таймаут скачивания после нескольких попыток"
                            )
                    
                    except Exception as e:
                        logger.error(f"[Download] Ошибка загрузки {video_id} (попытка {attempt + 1}): {e}")
                        self._cleanup_partial_files(video_id)
                        
                        if attempt < max_retries:
                            await asyncio.sleep(2)
                            continue
                        else:
                            return DownloadResult(success=False, error=str(e))

            except Exception as e:
                logger.error(f"[Download] Критическая ошибка для {video_id}: {e}", exc_info=True)
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