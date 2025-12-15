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
        # Ограничиваем одновременные загрузки (как в v5)
        self.semaphore = asyncio.Semaphore(3)

    def _get_opts(self, is_search: bool = False, query: str = "") -> Dict[str, Any]:
        """
        Генерация настроек на основе стабильной логики v5.
        """
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "source_address": "0.0.0.0",
            # ВАЖНО: Убрали жесткий User-Agent, yt-dlp сам подберет актуальный
            "no_check_certificate": True,
            "prefer_insecure": True,
            "geo_bypass": True,
            # Настройки повторных попыток на уровне сети
            "retries": 10,
            "fragment_retries": 10,
            "skip_unavailable_fragments": True,
        }

        # Подключаем куки, если есть (важно для премиум контента или 18+)
        if getattr(self._settings, "COOKIES_FILE", None) and self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
            opts["cookiefile"] = str(self._settings.COOKIES_FILE)

        if is_search:
            opts["extract_flat"] = True  # Быстрый поиск без получения ссылок на скачивание
        else:
            # ЛОГИКА ИЗ v5: Используем postprocessors для конвертации в MP3
            # Это намного надежнее, чем ручной subprocess ffmpeg
            opts.update({
                "format": "bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                # Ограничение размера файла
                "max_filesize": self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024,
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
        Поиск с использованием фильтров из v5 (SmartSearch).
        """
        # Формируем запрос
        search_query = f"ytsearch{limit}:{query}"
        opts = self._get_opts(is_search=True, query=query)

        try:
            info = await self._extract_info(search_query, opts, download=False)
            entries = info.get("entries", []) or []

            out: List[TrackInfo] = []
            
            # Список стоп-слов из v5
            BANNED_WORDS = [
                'ai cover', 'suno', 'udio', 'ai version', 
                'ии кавер', 'сгенерировано ии', 'ai generated'
            ]

            for e in entries:
                if not e or not e.get("id") or not e.get("title"):
                    continue
                
                # Фильтр 1: Live-трансляции
                if e.get("is_live"):
                    continue

                title_lower = e.get("title", "").lower()

                # Фильтр 2: Стоп-слова (AI каверы и мусор)
                if any(banned in title_lower for banned in BANNED_WORDS):
                    continue

                duration = int(e.get("duration") or 0)

                # Фильтр 3: Длительность
                if min_duration is not None and duration < min_duration:
                    continue
                if max_duration is not None and duration > max_duration:
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
        Логика ретраев, взятая полностью из v5.
        """
        for attempt in range(self._settings.MAX_RETRIES):
            try:
                async with self.semaphore:
                    result = await self.download(query)

                if result and result.success:
                    return result

                # Специфическая обработка 503 (YouTube Throttling)
                error_msg = str(result.error) if result and result.error else ""
                if "503" in error_msg or "Sign in" in error_msg:
                    logger.warning(f"[YouTube] Поймали блок (503/Sign in). Ждем {60 * (attempt + 1)} сек...")
                    await asyncio.sleep(60 * (attempt + 1))

            except Exception as e:
                logger.error(f"[YouTube] Попытка {attempt+1} провалилась: {e}")

            # Пауза перед следующей попыткой
            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S * (attempt + 1))

        return DownloadResult(success=False, error="Не удалось скачать трек после всех попыток.")

    async def download(self, query_or_id: str) -> DownloadResult:
        """
        Оптимизированный процесс загрузки (v5 style).
        """
        is_id = self.YT_ID_RE.match(query_or_id) is not None
        video_id: str

        try:
            # 1. Определяем ID видео
            if is_id:
                video_id = query_or_id
            else:
                found = await self.search(query_or_id, limit=3)
                if not found:
                    return DownloadResult(success=False, error="Ничего не найдено.")
                video_id = found[0].identifier

            # 2. Проверяем кэш
            cache_key = f"yt:{video_id}"
            cached = await self._cache.get(cache_key, Source.YOUTUBE)
            if cached:
                if Path(cached.file_path).exists():
                    return cached
                else:
                    await self._cache.delete(cache_key)

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            opts = self._get_opts(is_search=False)

            # 3. Скачиваем и конвертируем (одним действием через yt-dlp)
            # В v7 было разделение на extract_info и download, что вызывало ошибки.
            # Здесь мы делаем как в v5.
            loop = asyncio.get_running_loop()
            
            try:
                # Получаем инфо + скачиваем сразу
                info = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, 
                        lambda: yt_dlp.YoutubeDL(opts).extract_info(video_url, download=True)
                    ),
                    timeout=self._settings.DOWNLOAD_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                 return DownloadResult(success=False, error="Таймаут скачивания (YouTube долго отвечает).")

            if not info:
                 return DownloadResult(success=False, error="Не удалось получить информацию.")

            # 4. Собираем метаданные
            track_info = TrackInfo(
                title=info.get("title", "Unknown"),
                artist=info.get("channel") or info.get("uploader") or "Unknown",
                duration=int(info.get("duration") or 0),
                source=Source.YOUTUBE.value,
                identifier=video_id,
            )

            # 5. Находим скачанный файл
            # Так как мы использовали postprocessor 'mp3', ищем mp3
            final_path = str(self._settings.DOWNLOADS_DIR / f"{video_id}.mp3")
            
            # Если вдруг yt-dlp решил не конвертировать (редко), ищем другие расширения
            if not Path(final_path).exists():
                logger.info(f"MP3 не найден по пути {final_path}, ищу альтернативы...")
                files = glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*"))
                # Фильтруем временные файлы
                files = [f for f in files if not f.endswith((".part", ".ytdl", ".json", ".webp"))]
                if not files:
                    return DownloadResult(success=False, error="Файл скачался, но не найден на диске.")
                final_path = files[0]

            # Успех
            result = DownloadResult(True, final_path, track_info)
            await self._cache.set(cache_key, Source.YOUTUBE, result)
            return result

        except (DownloadError, ExtractorError) as e:
            msg = str(e)
            if "File is larger than max-filesize" in msg:
                 return DownloadResult(success=False, error=f"Файл слишком большой (> {self._settings.PLAY_MAX_FILE_SIZE_MB}MB).")
            if "Sign in" in msg:
                return DownloadResult(success=False, error="YouTube требует вход (Sign in required).")
            
            logger.error(f"Ошибка yt-dlp: {msg}")
            return DownloadResult(success=False, error="Ошибка загрузки с YouTube.")
            
        except Exception as e:
            logger.error(f"Критическая ошибка загрузчика: {e}", exc_info=True)
            return DownloadResult(success=False, error=str(e))