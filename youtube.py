import asyncio
import glob
import logging
import random
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pathlib import Path

import yt_dlp

from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache import CacheService

logger = logging.getLogger(__name__)


class BaseDownloader(ABC):
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self.name = self.__class__.__name__
        self.semaphore = asyncio.Semaphore(3)

    @abstractmethod
    async def search(self, query: str, limit: int = 20, **kwargs) -> List[TrackInfo]:
        raise NotImplementedError

    @abstractmethod
    async def download(self, query: str) -> DownloadResult:
        raise NotImplementedError

    async def download_with_retry(self, query: str) -> DownloadResult:
        for attempt in range(self._settings.MAX_RETRIES):
            try:
                async with self.semaphore:
                    result = await self.download(query)
                if result and result.success:
                    return result
                
                # Если ошибка "format not available" - не повторять
                if result and result.error and "format" in result.error.lower():
                    logger.warning(f"[Downloader] Формат недоступен, пропускаю: {query}")
                    return result

            except Exception as e:
                logger.error(f"[Downloader] Исключение при загрузке: {e}")
            
            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S * (attempt + 1))

        return DownloadResult(success=False, error=f"Не удалось скачать после {self._settings.MAX_RETRIES} попыток.")


class YouTubeDownloader(BaseDownloader):
    def __init__(self, settings: Settings, cache_service: CacheService):
        super().__init__(settings, cache_service)
        # Создаём папку для загрузок
        self._settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    def _get_ydl_options(self, is_search: bool = False) -> Dict[str, Any]:
        base = {
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "noplaylist": False,  # ← ВКЛЮЧАЕМ! Именно из-за этого всё падало
            "extract_flat": is_search,
            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 15,
            "extractor_retries": 5,
            "sleep_interval": 1,
            "max_sleep_interval": 5,
        }

        if not is_search:
            base.update({
                # Самое главное в декабре 2025:
                "format": "ba[ext=m4a]/ba[ext=webm]/ba/b",  # ← ба — bestaudio, без подписи
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                
                # ЭТОТ БЛОК — ЕДИНСТВЕННОЕ, ЧТО РЕАЛЬНО РАБОТАЕТ СЕЙЧАС:
                "extractor_args": {
                    "youtube": {
                        "skip": ["dash", "hls"],           # отключаем подписанные манифесты
                        "player_client": ["android"],      # ← только android сейчас живой
                        "player_skip": ["webpage", "configs"],
                    }
                },
                "http_headers": {
                    "User-Agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 14) gzip",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                # Критически важно — принудительно используем android клиент
                "player_client": "android",
            })

            if self._settings.COOKIES_FILE.exists():
                base["cookiefile"] = str(self._settings.COOKIES_FILE)

        return base

    async def _extract_info(self, query: str, ydl_opts: Dict) -> Optional[Dict]:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(query, download=False)
            )
        except Exception as e:
            logger.error(f"Extract info error: {e}")
            return None

    async def download(self, query_or_id: str) -> DownloadResult:
        cache_key = f"yt:{query_or_id.lower().strip()}"
        if cached := await self._cache.get(cache_key, Source.YOUTUBE):
            return cached

        ydl_opts = self._get_ydl_options(is_search=False)
        
        try:
            # ← Вот эта строчка — ключ к жизни в декабре 2025
            info = await asyncio.wait_for(
                self._extract_info(query_or_id, ydl_opts),
                timeout=45.0
            )
            if not info:
                return DownloadResult(success=False, error="Видео/плейлист недоступен")

            # Если это плейлист — берём первый трек
            if info.get("_type") == "playlist" and info.get("entries"):
                info = info["entries"][0]
                if not info:
                    return DownloadResult(success=False, error="Плейлист пустой")

            video_id = info["id"]
            duration = int(info.get("duration") or 0)

            if duration > self._settings.PLAY_MAX_DURATION_S:
                return DownloadResult(success=False, error="Слишком длинный трек")

            await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, lambda: yt_dlp.YoutubeDL(ydl_opts).download(query_or_id)
                ),
                timeout=self._settings.DOWNLOAD_TIMEOUT_S
            )

            # ищем файл
            for ext in ["mp3", "m4a", "webm"]:
                path = self._settings.DOWNLOADS_DIR / f"{video_id}.{ext}"
                if path.exists():
                    result = DownloadResult(True, str(path), TrackInfo.from_yt_info(info))
                    await self._cache.set(cache_key, Source.YOUTUBE, result)
                    return result

            return DownloadResult(success=False, error="Файл не найден после скачивания")

        except asyncio.TimeoutError:
            await self._cache.blacklist_track_id(video_id) # Blacklist on timeout
            return DownloadResult(success=False, error="Таймаут")
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            await self._cache.blacklist_track_id(video_id) # Blacklist on any download error
            if "Requested format is not available" in error_msg:
                return DownloadResult(success=False, error="Формат больше не поддерживается YouTube")
            return DownloadResult(success=False, error=error_msg[:200])
        except yt_dlp.utils.ExtractorError as e: # Catch all ExtractorError
            error_msg = str(e)
            await self._cache.blacklist_track_id(video_id) # Blacklist on any extractor error
            if "Requested format is not available" in error_msg:
                return DownloadResult(success=False, error="Формат больше не поддерживается YouTube")
            return DownloadResult(success=False, error=error_msg[:200])
        except Exception as e:
            logger.error(f"YouTube fatal: {e}", exc_info=True)
            return DownloadResult(success=False, error="Ошибка скачивания")

    async def search(
        self,
        query: str,
        limit: int = 20,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
        min_views: Optional[int] = None,
        min_likes: Optional[int] = None,
        min_like_ratio: Optional[float] = None,
        match_filter: Optional[str] = None
    ) -> List[TrackInfo]:
        """Поиск треков"""
        
        search_query = f"ytsearch{limit}:{query}"
        ydl_opts = self._get_ydl_options(is_search=True)
        
        try:
            info = await self._extract_info(search_query, ydl_opts)
            if not info:
                return []
            
            entries = info.get("entries", []) or []
            
            # Фильтруем
            BANNED_WORDS = ['karaoke', 'караоке', '24/7', 'live radio', 'ai cover']
            
            results = []
            for e in entries:
                if not e or not e.get("id") or not e.get("title"):
                    continue
                
                # Проверяем ID (11 символов)
                if len(e.get("id", "")) != 11:
                    continue
                
                # Пропускаем, если трек в черном списке
                if await self._cache.is_blacklisted(e.get("id")):
                    logger.debug(f"[YouTube Search Debug] Пропущен трек '{e.get('title')}' (ID: {e.get('id')}) - находится в черном списке.")
                    continue
                
                # Пропускаем live
                if e.get('is_live'):
                    continue
                
                # Пропускаем по стоп-словам
                title_lower = e.get("title", "").lower()
                if any(banned in title_lower for banned in BANNED_WORDS):
                    continue
                
                duration = int(e.get("duration") or 0)
                
                # Фильтр по длительности
                if min_duration and duration < min_duration:
                    continue
                if max_duration and duration > max_duration:
                    continue
                
                results.append(TrackInfo(
                    title=e["title"],
                    artist=e.get("uploader", "Unknown"),
                    duration=duration,
                    source=Source.YOUTUBE.value,
                    identifier=e["id"],
                    view_count=e.get("view_count"),
                    like_count=e.get("like_count"),
                ))
            
            logger.info(f"[Search] '{query}' -> {len(results)} tracks")
            return results
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []