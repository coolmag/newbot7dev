import asyncio
import glob
import logging
import random
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import aiohttp
import yt_dlp

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
    async def search(
        self,
        query: str,
        limit: int = 30,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
        min_views: Optional[int] = None,
        min_likes: Optional[int] = None,
        min_like_ratio: Optional[float] = None,
    ) -> List[TrackInfo]:
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
                
                if result and result.error and "503" in result.error:
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

    def _get_ydl_options(
        self, 
        is_search: bool, 
        match_filter: Optional[str] = None,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
    ) -> Dict[str, Any]:
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
            options["extract_flat"] = True
            
            filters = []
            if match_filter:
                filters.append(match_filter)
            if min_duration is not None:
                filters.append(f"duration >= {min_duration}")
            if max_duration is not None:
                filters.append(f"duration <= {max_duration}")
            
            if filters:
                combined_filter = " & ".join(filters)
                options["match_filter"] = yt_dlp.utils.match_filter_func(combined_filter)
        else:
            options.update({
                'format': 'bestaudio[ext=m4a]/bestaudio/best[filesize<20M]/bestaudio/best[height<=480]/best[ext=mp4]/best',
                'format_sort': ['ext:mp3>m4a>webm>opus>mp4', 'br:192', 'size+'],
                'outtmpl': str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                    'keepvideo': False,
                }],
                'retries': 10,
                'fragment_retries': 10,
            })
            if self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
                options["cookiefile"] = str(self._settings.COOKIES_FILE)
        return options

    async def _extract_info(self, query: str, ydl_opts: Dict) -> Dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(query, download=False)
        )

    async def _find_best_match(
        self, 
        query: str, 
        min_duration: Optional[int] = None, 
        max_duration: Optional[int] = None
    ) -> Optional[TrackInfo]:
        """
        Интеллектуальный поиск лучшего трека с фильтрацией в Python.
        """
        logger.info(f"[SmartSearch] Начинаю интеллектуальный поиск для: '{query}'")
        
        search_query_parts = [query]
        if "советск" in query.lower() or "ссср" in query.lower():
            search_query_parts.extend(["гостелерадиофонд", "эстрада", "песня года"])
        else:
            search_query_parts.extend(["official audio", "topic", "lyrics", "альбом"])
        smart_query = " ".join(search_query_parts)

        def is_high_quality(e: Dict[str, Any]) -> bool:
            title = e.get('title', '').lower()
            channel = e.get('channel', '').lower()
            is_good_title = any(kw in title for kw in ['audio', 'lyric', 'альбом', 'album'])
            is_topic_channel = channel.endswith(' - topic')
            is_bad_title = any(kw in title for kw in ['live', 'short', 'концерт', 'выступление', 'official video', 'music video', 'full show', 'interview', 'parody', 'влог', 'vlog', 'топ 10', 'mix', 'сборник', 'playlist'])
            return (is_good_title or is_topic_channel) and not is_bad_title

        def is_valid_video_entry(e: Dict[str, Any]) -> bool:
            entry_id = e.get('id')
            return entry_id and len(entry_id) == 11

        logger.debug(f"[SmartSearch] Попытка 1: строгий поиск с запросом '{smart_query}'")
        ydl_opts_strict = self._get_ydl_options(is_search=True, min_duration=min_duration, max_duration=max_duration)
        
        try:
            info = await self._extract_info(f"ytsearch5:{smart_query}", ydl_opts_strict)
            if info and info.get("entries"):
                entries = [e for e in info["entries"] if is_valid_video_entry(e) and is_high_quality(e)]
                if entries:
                    entry = entries[0]
                    logger.info(f"[SmartSearch] Успех (строгий поиск)! Найден: {entry['title']}")
                    return TrackInfo(title=entry["title"], artist=entry.get("channel", entry.get("uploader", "Unknown")), duration=int(entry.get("duration", 0)), source=Source.YOUTUBE.value, identifier=entry["id"])
        except Exception as e:
            logger.warning(f"[SmartSearch] Ошибка на этапе строгого поиска: {e}")

        logger.info("[SmartSearch] Строгий поиск не дал результатов, перехожу к обычному поиску.")
        ydl_opts_fallback = self._get_ydl_options(is_search=True, min_duration=min_duration, max_duration=max_duration)
        try:
            info = await self._extract_info(f"ytsearch1:{query}", ydl_opts_fallback)
            if info and info.get("entries"):
                valid_entries = [e for e in info["entries"] if is_valid_video_entry(e)]
                if valid_entries:
                    entry = valid_entries[0]
                    logger.info(f"[SmartSearch] Успех (обычный поиск)! Найден: {entry['title']}")
                    return TrackInfo(title=entry["title"], artist=entry.get("channel", entry.get("uploader", "Unknown")), duration=int(entry.get("duration", 0)), source=Source.YOUTUBE.value, identifier=entry["id"])
        except Exception as e:
            logger.error(f"[SmartSearch] Ошибка на этапе обычного поиска: {e}")
        
        logger.warning(f"[SmartSearch] Поиск по запросу '{query}' не дал никаких результатов.")
        return None

    async def download(self, query_or_id: str) -> DownloadResult:
        is_id = re.match(r"^[a-zA-Z0-9_-]{11}$", query_or_id) is not None
        cache_key = f"yt:{query_or_id}"
        
        cached = await self._cache.get(cache_key, Source.YOUTUBE)
        if cached: return cached

        try:
            track_identifier = query_or_id if is_id else (await self._find_best_match(query_or_id, self._settings.PLAY_MIN_DURATION_S, self._settings.PLAY_MAX_DURATION_S) or {}).get("identifier")
            if not track_identifier:
                return DownloadResult(success=False, error="Ничего не найдено.")

            ydl_opts = self._get_ydl_options(is_search=False)
            ydl_opts["max_filesize"] = self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024

            info = await self._extract_info(track_identifier, ydl_opts)
            if not info: return DownloadResult(success=False, error="Не удалось получить информацию о видео.")

            track_info = TrackInfo.from_yt_info(info)

            if track_info.duration > self._settings.PLAY_MAX_DURATION_S:
                return DownloadResult(success=False, error=f"Трек слишком длинный ({track_info.format_duration()}).")

            await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([track_identifier])), timeout=self._settings.DOWNLOAD_TIMEOUT_S)
            
            # Ищем скачанный файл с любым из ожидаемых расширений
            for ext in ["m4a", "webm", "mp3"]:
                f = next(iter(glob.glob(str(self._settings.DOWNLOADS_DIR / f"{track_identifier}.{ext}"))), None)
                if f:
                    result = DownloadResult(True, f, track_info)
                    await self._cache.set(cache_key, Source.YOUTUBE, result)
                    return result
            
            return DownloadResult(success=False, error="Файл не найден после скачивания.")

        except Exception as e:
            logger.error(f"Ошибка скачивания с YouTube: {e}", exc_info=True)
            if "File is larger than max-filesize" in str(e):
                return DownloadResult(success=False, error=f"Файл слишком большой ( > {self._settings.PLAY_MAX_FILE_SIZE_MB}MB).")
            return DownloadResult(success=False, error=str(e))

    async def search(
        self,
        query: str,
        limit: int = 30,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
        min_views: Optional[int] = None,
        min_likes: Optional[int] = None,
        min_like_ratio: Optional[float] = None,
        match_filter: Optional[str] = None,
    ) -> List[TrackInfo]:
        search_query = f"ytsearch{limit}:{query}"
        ydl_opts = self._get_ydl_options(is_search=True, match_filter=match_filter, min_duration=min_duration, max_duration=max_duration)
        
        try:
            info = await self._extract_info(search_query, ydl_opts)
            if not info or not info.get("entries"):
                return []
            
            results = []
            for e in info["entries"]:
                if not e or not e.get("id") or not e.get("title") or len(e.get("id", "")) != 11 or e.get('is_live'):
                    continue
                
                title_lower = e.get("title", "").lower()
                if any(banned in title_lower for banned in ['ai cover', 'karaoke', 'караоке', '24/7', 'live radio']):
                    continue
                
                duration = int(e.get("duration") or 0)
                if (min_duration and duration < min_duration) or \
                   (max_duration and duration > max_duration) or \
                   (min_views and (e.get("view_count") is None or e.get("view_count") < min_views)) or \
                   (min_likes and (e.get("like_count") is None or e.get("like_count") < min_likes)):
                    continue
                
                results.append(TrackInfo.from_yt_info(e))
            return results
        except Exception as e:
            logger.error(f"[YouTube] Ошибка поиска для '{query}': {e}", exc_info=True)
            return []


class InternetArchiveDownloader(BaseDownloader):
    """
    Загрузчик для Internet Archive.
    """

    API_URL = "https://archive.org/advancedsearch.php"

    def __init__(self, settings: Settings, cache_service: CacheService):
        super().__init__(settings, cache_service)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def search(
        self,
        query: str,
        limit: int = 30,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
        min_views: Optional[int] = None,
        min_likes: Optional[int] = None,
        min_like_ratio: Optional[float] = None,
    ) -> List[TrackInfo]:
        params = {
            "q": f'mediatype:audio AND (subject:("{query}") OR title:("{query}"))',
            "fl[]": "identifier,title,creator,length",
            "rows": limit,
            "page": random.randint(1, 5),
            "output": "json",
        }
        try:
            session = await self._get_session()
            async with session.get(self.API_URL, params=params) as response:
                data = await response.json()
            
            results = []
            for doc in data.get("response", {}).get("docs", []):
                duration = int(float(doc.get("length", 0)))
                if duration <= 0 or \
                   (min_duration and duration < min_duration) or \
                   (max_duration and duration > max_duration):
                    continue
                
                results.append(TrackInfo(
                    title=doc.get("title", "Unknown"),
                    artist=doc.get("creator", "Unknown"),
                    duration=duration,
                    source=Source.INTERNET_ARCHIVE.value,
                    identifier=doc.get("identifier"),
                ))
            return results
        except Exception:
            return []

    async def download(self, query: str) -> DownloadResult:
        cached = await self._cache.get(query, Source.INTERNET_ARCHIVE)
        if cached:
            return cached
        
        search_results = await self.search(query, limit=1)
        if not search_results:
            return DownloadResult(success=False, error="Ничего не найдено.")

        track = search_results[0]
        identifier = track.identifier
        try:
            session = await self._get_session()
            metadata_url = f"https://archive.org/metadata/{identifier}"
            async with session.get(metadata_url) as response:
                metadata = await response.json()

            mp3_file = next(
                (f for f in metadata.get("files", []) if f.get("format", "").startswith("VBR MP3")),
                None
            )
            if not mp3_file:
                return DownloadResult(success=False, error="MP3 файл не найден.")

            file_path = self._settings.DOWNLOADS_DIR / f"{identifier}.mp3"
            download_url = f"https://archive.org/download/{identifier}/{mp3_file['name']}"
            
            async with session.get(download_url) as response:
                with open(file_path, "wb") as f:
                    while chunk := await response.content.read(1024):
                        f.write(chunk)
            
            result = DownloadResult(True, str(file_path), track)
            await self._cache.set(query, Source.INTERNET_ARCHIVE, result)
            return result
        except Exception as e:
            return DownloadResult(success=False, error=str(e))

    async def close(self):
        if self._session:
            await self._session.close()
