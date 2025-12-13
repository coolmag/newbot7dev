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

    def _get_ydl_options(self, is_search: bool) -> Dict[str, Any]:
        options = {
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "noplaylist": True,
        }
        
        if is_search:
            options["extract_flat"] = True
            options["ignoreerrors"] = True
        else:
            # Для скачивания - более гибкий формат
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }]
            options["outtmpl"] = str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s")
            
            # Cookies
            if self._settings.COOKIES_FILE.exists():
                options["cookiefile"] = str(self._settings.COOKIES_FILE)
            
            # Android клиент для обхода блокировок
            options["extractor_args"] = {
                "youtube": {
                    "player_client": ["android", "web"],
                }
            }
            
            options["http_headers"] = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36",
            }
        
        return options

    async def _extract_info(self, query: str, ydl_opts: Dict) -> Optional[Dict]:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(query, download=False)
            )
        except Exception as e:
            logger.error(f"Extract info error: {e}")
            return None

    async def download(self, video_id: str) -> DownloadResult:
        """Скачивает видео по ID"""
        
        # Проверяем кэш
        cached = await self._cache.get(video_id, Source.YOUTUBE)
        if cached:
            return cached

        ydl_opts = self._get_ydl_options(is_search=False)
        url = f"https://www.youtube.com/watch?v={video_id}"

        try:
            # Получаем информацию
            info = await asyncio.wait_for(
                self._extract_info(url, ydl_opts),
                timeout=30.0
            )
            
            if not info:
                return DownloadResult(success=False, error="Не удалось получить информацию о видео")
            
            track_info = TrackInfo(
                title=info.get("title", "Unknown"),
                artist=info.get("channel", info.get("uploader", "Unknown")),
                duration=int(info.get("duration", 0)),
                source=Source.YOUTUBE.value,
                identifier=info["id"],
            )

            # Скачиваем
            loop = asyncio.get_running_loop()
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]),
                ),
                timeout=self._settings.DOWNLOAD_TIMEOUT_S
            )

            # Ищем файл
            mp3_file = next(
                iter(glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"))),
                None,
            )
            
            if not mp3_file:
                # Пробуем найти другие форматы
                for ext in ["m4a", "webm", "opus"]:
                    found = next(iter(glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.{ext}"))), None)
                    if found:
                        mp3_file = found
                        break
            
            if not mp3_file:
                return DownloadResult(success=False, error="Файл не найден после скачивания")

            result = DownloadResult(True, mp3_file, track_info)
            await self._cache.set(video_id, Source.YOUTUBE, result)
            return result
            
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if "format" in error_msg.lower() or "not available" in error_msg.lower():
                return DownloadResult(success=False, error="Формат недоступен")
            return DownloadResult(success=False, error=error_msg[:200])
        except yt_dlp.utils.ExtractorError as e: # Добавлена обработка ExtractorError
            error_msg = str(e)
            if "format" in error_msg.lower() or "not available" in error_msg.lower():
                return DownloadResult(success=False, error="Формат недоступен")
            return DownloadResult(success=False, error=error_msg[:200])
        except asyncio.TimeoutError:
            return DownloadResult(success=False, error="Таймаут скачивания")
        except Exception as e:
            logger.error(f"Download error: {e}", exc_info=True)
            return DownloadResult(success=False, error=str(e)[:200])

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