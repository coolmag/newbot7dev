import asyncio
import glob
import logging
import random
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import aiohttp
import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache import CacheService

logger = logging.getLogger(__name__)


class BaseDownloader(ABC):
    """
    Абстрактный базовый класс для всех загрузчиков.
    Предоставляет общий интерфейс и логику повторных попыток.
    """

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self.name = self.__class__.__name__
        self.semaphore = asyncio.Semaphore(3)

    @abstractmethod
    async def search(self, query: str, **kwargs) -> List[TrackInfo]:
        raise NotImplementedError

    @abstractmethod
    async def download(self, query: str) -> DownloadResult:
        raise NotImplementedError

    async def download_with_retry(self, query: str) -> DownloadResult:
        for attempt in range(self._settings.MAX_RETRIES):
            try:
                async with self.semaphore:
                    result = await self.download(query)
                
                if result.success:
                    return result
                
                # Не ретраить ошибку "format not available"
                if "Requested format is not available" in (result.error or ""):
                    return result

                if "503" in (result.error or ""):
                    logger.warning("[Downloader] Получен код 503 от сервера. Большая пауза...")
                    await asyncio.sleep(60 * (attempt + 1))

            except (asyncio.TimeoutError, Exception) as e:
                logger.error(f"[Downloader] Исключение при загрузке: {e}", exc_info=True)
            
            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S * (attempt + 1))

        return DownloadResult(
            success=False,
            error=f"Не удалось скачать после {self._settings.MAX_RETRIES} попыток.",
        )


class YouTubeDownloader(BaseDownloader):
    """
    Улучшенный загрузчик для YouTube с интеллектуальным поиском.
    """

    def __init__(self, settings: Settings, cache_service: CacheService):
        super().__init__(settings, cache_service)

    def _get_ydl_options(self, is_search: bool = False, **kwargs) -> Dict[str, Any]:
        options = {
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "source_address": "0.0.0.0",
            "user_agent": "Mozilla/5.0",
            "no_check_certificate": True,
            "prefer_insecure": True,
            "noplaylist": True,
        }
        if is_search:
            options.update({
                "extract_flat": True,
                "match_filter": yt_dlp.utils.match_filter_func(
                    f"duration >= {kwargs.get('min_duration', 0)} & duration <= {kwargs.get('max_duration', 99999)}"
                ) if kwargs.get('min_duration') or kwargs.get('max_duration') else None
            })
        else:
            options.update({
                "format": "bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "noprogress": True,
                "retries": 10,
                "fragment_retries": 10,
                "skip_unavailable_fragments": True,
            })
            if self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
                options["cookiefile"] = str(self._settings.COOKIES_FILE)
        return options

    async def _extract_info(self, query: str, ydl_opts: Dict, *, download: bool = False, process: bool = True) -> Dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(query, download=download, process=process)
        )

    async def _find_best_match(self, query: str, **kwargs) -> Optional[TrackInfo]:
        logger.info(f"[SmartSearch] Начинаю интеллектуальный поиск для: '{query}'")
        ydl_opts = self._get_ydl_options(is_search=True, **kwargs)
        try:
            info = await self._extract_info(f"ytsearch1:{query}", ydl_opts)
            if info and info.get("entries"):
                entry = info["entries"][0]
                return TrackInfo.from_yt_info(entry)
        except Exception as e:
            logger.error(f"[SmartSearch] Ошибка на этапе поиска: {e}")
        return None

    async def download(self, query_or_id: str) -> DownloadResult:
        is_id = re.match(r"^[a-zA-Z0-9_-]{11}$", query_or_id) is not None
        cache_key = f"yt:{query_or_id}"
        
        cached = await self._cache.get(cache_key, Source.YOUTUBE)
        if cached: return cached

        try:
            track_identifier = query_or_id if is_id else (await self._find_best_match(query_or_id) or {}).get("identifier")
            if not track_identifier:
                return DownloadResult(success=False, error="Ничего не найдено.")
            
            video_url = f"https://www.youtube.com/watch?v={track_identifier}"

            info_opts = self._get_ydl_options()
            info_opts.pop("format", None)
            info = await self._extract_info(video_url, info_opts, process=False)
            if not info: return DownloadResult(success=False, error="Не удалось получить информацию о видео.")
            
            track_info = TrackInfo.from_yt_info(info)

            ydl_opts_download = self._get_ydl_options()
            ydl_opts_download["max_filesize"] = self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024

            await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts_download).download([video_url])), timeout=self._settings.DOWNLOAD_TIMEOUT_S)
            
            for ext in ["m4a", "webm", "mp3", "opus"]:
                f = next(iter(glob.glob(str(self._settings.DOWNLOADS_DIR / f"{track_identifier}.{ext}"))), None)
                if f:
                    result = DownloadResult(True, f, track_info)
                    await self._cache.set(cache_key, Source.YOUTUBE, result)
                    return result
            
            return DownloadResult(success=False, error="Файл не найден после скачивания.")
        
        except (DownloadError, ExtractorError) as e:
            if "Requested format is not available" in str(e):
                return DownloadResult(success=False, error="Формат недоступен для этого видео")
            logger.error(f"Ошибка скачивания с YouTube: {e}", exc_info=True)
            return DownloadResult(success=False, error=str(e))
        except Exception as e:
            logger.error(f"Неизвестная ошибка скачивания: {e}", exc_info=True)
            return DownloadResult(success=False, error=str(e))

    async def search(self, query: str, **kwargs) -> List[TrackInfo]:
        ydl_opts = self._get_ydl_options(is_search=True, **kwargs)
        try:
            info = await self._extract_info(f"ytsearch{kwargs.get('limit', 30)}:{query}", ydl_opts)
            if not info or not info.get("entries"):
                return []
            
            return [TrackInfo.from_yt_info(e) for e in info["entries"] if e and e.get("id")]
        except Exception as e:
            logger.error(f"[YouTube] Ошибка поиска для '{query}': {e}", exc_info=True)
            return []


class InternetArchiveDownloader(BaseDownloader):
    pass # Реализация не требуется для этого шага