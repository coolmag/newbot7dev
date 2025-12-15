from __future__ import annotations

import asyncio
import glob
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache import CacheService

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    # Регулярка для проверки ID
    YT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        # Ограничиваем одновременные загрузки
        self.semaphore = asyncio.Semaphore(3)

    def _get_opts(self, is_search: bool = False, query: str = "") -> Dict[str, Any]:
        """
        Оптимизированные настройки: скорость и защита от больших файлов.
        """
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,  # Быстрый таймаут
            "source_address": "0.0.0.0",
            "no_check_certificate": True,
            "prefer_insecure": True,
            "geo_bypass": True,
            "retries": 5,
            "fragment_retries": 5,
            "skip_unavailable_fragments": True,
            # ВАЖНО: Фильтр. Игнорируем видео длиннее 15 минут (900 сек) и стримы
            "match_filter": yt_dlp.utils.match_filter_func("duration < 900 & !is_live"),
        }

        if getattr(self._settings, "COOKIES_FILE", None) and self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
            opts["cookiefile"] = str(self._settings.COOKIES_FILE)

        if is_search:
            opts["extract_flat"] = True
        else:
            # Настройки для скачивания файла: только аудио, малый размер
            opts.update({
                # Приоритет: m4a (самый легкий) -> webm -> любой аудио
                "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128", # Качество 128kbps (идеально для радио)
                }],
                # Жесткий лимит размера файла (50 МБ)
                "max_filesize": 50 * 1024 * 1024,
            })
        
        return opts

    async def _extract_info(self, query: str, opts: Dict[str, Any], download: bool = False) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: yt_dlp.YoutubeDL(opts).extract_info(query, download=download)
        )

    async def search(
        self,
        query: str,
        limit: int = 30,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
        **kwargs,
    ) -> List[TrackInfo]:
        """
        Поиск с фильтрацией мусора.
        """
        search_query = f"ytsearch{limit}:{query}"
        opts = self._get_opts(is_search=True, query=query)

        try:
            info = await self._extract_info(search_query, opts, download=False)
            entries = info.get("entries", []) or []

            out: List[TrackInfo] = []
            
            # Список стоп-слов
            BANNED_WORDS = [
                'ai cover', 'suno', 'udio', 'ai version', 
                'ии кавер', 'сгенерировано ии', 'ai generated',
                '10 hours', '1 hour', 'mix 2025'
            ]

            for e in entries:
                if not e or not e.get("id") or not e.get("title"):
                    continue
                
                if e.get("is_live"):
                    continue

                title_lower = e.get("title", "").lower()

                if any(banned in title_lower for banned in BANNED_WORDS):
                    continue

                duration = int(e.get("duration") or 0)

                # Игнорируем слишком длинные (больше 15 мин)
                if duration > 900: 
                    continue

                out.append(
                    TrackInfo(
                        title=e.get("title", "Unknown"),
                        artist=e.get("channel") or e.get("uploader") or "Unknown",
                        duration=duration,
                        source=Source.YOUTUBE.value,
                        identifier=e["id"],
                    )
                )
            return out

        except Exception as e:
            logger.error(f"Ошибка поиска: {e}")
            return []

    async def download_with_retry(self, query: str) -> DownloadResult:
        """
        Попытка скачать с ретраями.
        """
        for attempt in range(self._settings.MAX_RETRIES):
            try:
                async with self.semaphore:
                    result = await self.download(query)

                if result and result.success:
                    return result

                # Ошибки, при которых нет смысла пробовать снова
                error_msg = str(result.error) if result.error else ""
                if "File is larger" in error_msg or "video is too long" in error_msg:
                    return result # Возвращаем ошибку сразу, не ретраим

                if "503" in error_msg or "Sign in" in error_msg:
                    logger.warning(f"[YouTube] Поймали блок. Ждем {10 * (attempt + 1)} сек...")
                    await asyncio.sleep(10 * (attempt + 1))

            except Exception as e:
                logger.error(f"[YouTube] Попытка {attempt+1} провалилась: {e}")

            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S)

        return DownloadResult(success=False, error="Не удалось скачать трек.")

    async def download(self, query_or_id: str) -> DownloadResult:
        is_id = self.YT_ID_RE.match(query_or_id) is not None
        video_id: str

        try:
            if is_id:
                video_id = query_or_id
            else:
                found = await self.search(query_or_id, limit=3)
                if not found:
                    return DownloadResult(success=False, error="Ничего не найдено.")
                video_id = found[0].identifier

            # Кэш
            cache_key = f"yt:{video_id}"
            cached = await self._cache.get(cache_key, Source.YOUTUBE)
            if cached:
                if Path(cached.file_path).exists():
                    return cached
                else:
                    await self._cache.delete(cache_key)

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            opts = self._get_opts(is_search=False)

            loop = asyncio.get_running_loop()
            
            try:
                info = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, 
                        lambda: yt_dlp.YoutubeDL(opts).extract_info(video_url, download=True)
                    ),
                    timeout=self._settings.DOWNLOAD_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                 return DownloadResult(success=False, error="Таймаут скачивания.")

            if not info:
                 return DownloadResult(success=False, error="Ошибка получения информации.")

            track_info = TrackInfo(
                title=info.get("title", "Unknown"),
                artist=info.get("channel") or info.get("uploader") or "Unknown",
                duration=int(info.get("duration") or 0),
                source=Source.YOUTUBE.value,
                identifier=video_id,
            )

            final_path = str(self._settings.DOWNLOADS_DIR / f"{video_id}.mp3")
            
            if not Path(final_path).exists():
                logger.info(f"MP3 не найден, ищу альтернативы для {video_id}...")
                files = glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*"))
                files = [f for f in files if not f.endswith((".part", ".ytdl", ".json", ".webp"))]
                if not files:
                    return DownloadResult(success=False, error="Файл не найден на диске.")
                final_path = files[0]

            result = DownloadResult(True, final_path, track_info)
            await self._cache.set(cache_key, Source.YOUTUBE, result)
            return result

        except (DownloadError, ExtractorError) as e:
            msg = str(e)
            if "File is larger" in msg:
                 return DownloadResult(success=False, error="Файл слишком большой (> 50MB).")
            logger.error(f"Ошибка yt-dlp: {msg}")
            return DownloadResult(success=False, error=f"Ошибка загрузки: {msg[:50]}")
            
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}", exc_info=True)
            return DownloadResult(success=False, error=str(e))