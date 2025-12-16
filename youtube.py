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
    YT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self.semaphore = asyncio.Semaphore(3)

    def _get_opts(self, mode: str = "download") -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,
            "source_address": "0.0.0.0",
            "no_check_certificate": True,
            "geo_bypass": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        }

        if getattr(self._settings, "COOKIES_FILE", None) and self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
            opts["cookiefile"] = str(self._settings.COOKIES_FILE)

        if mode == "search":
            opts.update({
                "extract_flat": True,
                "skip_download": True,
            })
        elif mode == "download":
            opts.update({
                "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}],
                "max_filesize": self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024 if hasattr(self._settings, 'PLAY_MAX_FILE_SIZE_MB') else 50 * 1024 * 1024,
                "match_filter": yt_dlp.utils.match_filter_func("!is_live"),
                "writeinfojson": True,
            })
        return opts

    async def _extract_info(self, query: str, opts: Dict[str, Any]) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: yt_dlp.YoutubeDL(opts).extract_info(query, download=False)
        )

    def _find_downloaded_file(self, video_id: str) -> Optional[str]:
        pattern = str(self._settings.DOWNLOADS_DIR / f"{video_id}.mp3")
        files = glob.glob(pattern)
        return files[0] if files else None

    async def search(self, query: str, limit: int = 30, **kwargs) -> List[TrackInfo]:
        """
        Воспроизводит двухэтапную логику поиска из предоставленного файла.
        Сначала ищет "качественный" контент, затем делает более общий запрос.
        """
        logger.info(f"[Search] Запуск поиска для: '{query}'")

        # --- Вспомогательная функция для фильтрации на Python ---
        def filter_entry(e: Dict[str, Any], strict_mode: bool = True) -> bool:
            title = e.get('title', '').lower()
            uploader = e.get('uploader', '').lower()
            raw_duration = e.get('duration')
            duration = int(raw_duration or 0)

            # Базовые проверки длительности
            if not (120 <= duration <= 900): # От 2 до 15 минут
                return False

            # Стоп-слова (черный список)
            BANNED_WORDS = [
                'cover', 'remix', 'mashup', 'live', 'concert', 'концерт', 
                'acoustic', 'karaoke', 'караоке', 'instrumental', 'минус', 
                'минусовка', 'vlog', 'влог', 'interview', 'пародия', 'parody', 
                '10 hours', '24/7', 'top 10', 'top 50', 'top 100', 'playlist', 
                'сборник', 'mix', 'чарт', 'billboard', 'hot 100', 'песен', 'песни',
                'reaction', 'реакция', 'tutorial', 'how to'
            ]
            if any(banned_word in title for banned_word in BANNED_WORDS):
                return False

            # Если несколько исполнителей в названии (обычно сборники)
            if title.count(',') > 2 and "official" not in title and "audio" not in title: # Смягченный вариант
                return False

            # Дополнительные строгие проверки для режима "строгого поиска"
            if strict_mode:
                is_good_title_keywords = any(kw in title for kw in ['official audio', 'topic', 'album', 'официальный'])
                is_good_uploader_keywords = any(kw in uploader for kw in ['vevo', 'official', 'topic'])
                is_music_category = isinstance(e.get("categories"), list) and "Music" in e.get("categories", [])
                
                # Должно быть что-то из хороших признаков
                if not (is_good_title_keywords or is_good_uploader_keywords or is_music_category):
                    return False

            return True

        # --- Общие параметры yt-dlp для поиска ---
        common_search_opts = self._get_opts("search")
        common_match_filter = yt_dlp.utils.match_filter_func(
            f"duration >= 120 & duration <= 900 & !is_live" # Только базовая фильтрация на стороне yt-dlp
        )
        common_search_opts['match_filter'] = common_match_filter


        # --- Этап 1: Строгий поиск качественного контента ---
        try:
            # Ищем чуть больше, чтобы было из чего выбрать
            strict_yt_query = f"ytsearch20:{query} official audio" # Добавил "official audio"
            info = await self._extract_info(strict_yt_query, common_search_opts)
            entries = info.get("entries", []) or []
            
            # Применяем Python-фильтр
            filtered_entries = [e for e in entries if e and e.get("id") and e.get("title") and filter_entry(e, strict_mode=True)]
            
            if filtered_entries:
                logger.info(f"[Search] Строгий поиск успешен. Найдено {len(filtered_entries)} качественных треков.")
                results = []
                for e in filtered_entries[:limit]:
                    results.append(TrackInfo(
                        title=e["title"],
                        artist=e.get("uploader") or "Unknown",
                        duration=int(e.get("duration", 0)),
                        source=Source.YOUTUBE.value,
                        identifier=e["id"],
                    ))
                return results

        except Exception as e:
            logger.warning(f"[Search] Ошибка на этапе строгого поиска: {e}. Перехожу к общему поиску.")

        # --- Этап 2: Запасной вариант (Fallback) ---
        logger.info("[Search] Строгий поиск не дал результатов, перехожу к общему поиску.")
        try:
            fallback_yt_query = f"ytsearch{limit * 2}:{query}" # Ищем больше, чтобы было из чего выбрать
            info = await self._extract_info(fallback_yt_query, common_search_opts) # Используем тот же базовый фильтр
            entries = info.get("entries", []) or []

            # Применяем Python-фильтр в менее строгом режиме
            filtered_entries = [e for e in entries if e and e.get("id") and e.get("title") and filter_entry(e, strict_mode=False)]

            if filtered_entries:
                logger.info(f"[Search] Общий поиск успешен. Найдено {len(filtered_entries)} треков.")
                results = []
                for e in filtered_entries[:limit]:
                    results.append(TrackInfo(
                        title=e["title"],
                        artist=e.get("uploader") or "Unknown",
                        duration=int(e.get("duration", 0)),
                        source=Source.YOUTUBE.value,
                        identifier=e["id"],
                    ))
                return results
            
            logger.warning(f"[Search] Поиск по запросу '{query}' не дал никаких результатов после фильтрации.")
            return []

        except Exception as e:
            logger.error(f"[Search] Критическая ошибка на этапе общего поиска: {e}", exc_info=True)
            return []

    async def download(self, query_or_id: str) -> DownloadResult:
        # ... (остальной код download остается без изменений, т.к. он уже использует .json и кэш) ...
        is_id = self.YT_ID_RE.match(query_or_id) is not None
        video_id = query_or_id if is_id else None

        try:
            if not video_id:
                # В режиме радио мы всегда передаем ID, этот блок для /play
                found_tracks = await self.search(query_or_id, limit=1)
                if not found_tracks:
                    return DownloadResult(success=False, error="Ничего не найдено.")
                video_id = found_tracks[0].identifier

            cache_key = f"yt:{video_id}"
            cached = await self._cache.get(cache_key, Source.YOUTUBE)
            if cached and Path(cached.file_path).exists():
                return cached
            elif cached:
                await self._cache.delete(cache_key)

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            opts = self._get_opts(mode="download")

            # --- Step 1: Get info without downloading to check size ---
            loop = asyncio.get_running_loop()
            info_opts = self._get_opts(mode="search") # Use search mode opts to avoid download side effects
            try:
                # Use a short timeout for info extraction
                info = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(info_opts).extract_info(video_url, download=False)),
                    timeout=10.0 # Short timeout for info
                )
            except asyncio.TimeoutError:
                logger.warning(f"Таймаут получения информации о видео {video_id}. Пропускаю.")
                return DownloadResult(success=False, error="Таймаут получения информации о видео.")
            except Exception as e:
                logger.warning(f"Ошибка получения информации о видео {video_id}: {e}. Продолжаю попытку скачивания.")
                info = None # Clear info to proceed with download
            
            if info:
                filesize = info.get('filesize') or info.get('filesize_approx')
                if filesize and filesize > self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024:
                    err_msg = f"Видео слишком большое ({filesize / (1024*1024):.1f} MB), превышает лимит в {self._settings.PLAY_MAX_FILE_SIZE_MB} MB."
                    logger.warning(err_msg)
                    return DownloadResult(success=False, error=err_msg)

            # --- Step 2: Proceed with download if size is acceptable or unknown ---
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).download([video_url])),
                    timeout=self._settings.DOWNLOAD_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                 return DownloadResult(success=False, error="Таймаут скачивания.")
            except Exception as e:
                # This exception might still be caught by the outer try-except, if yt-dlp raises
                # an error for filesize.
                if "File is larger" in str(e) or "exceeds max-filesize" in str(e):
                    return DownloadResult(success=False, error=f"Файл слишком большой ( > {self._settings.PLAY_MAX_FILE_SIZE_MB}MB).")
                raise e # Re-raise other exceptions to be caught by outer block.

            # ... rest of download logic (find file, extract metadata, cache) ...
            final_path = self._find_downloaded_file(video_id)
            if not final_path:
                return DownloadResult(success=False, error="Файл не скачался (возможно, стрим).")
            
            # --- Step 3: Post-download size check (redundant but safe) ---
            actual_size = Path(final_path).stat().st_size
            if actual_size > self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024:
                err_msg = f"Файл {final_path} скачался слишком большим ({actual_size / (1024*1024):.1f} MB)."
                logger.error(err_msg)
                Path(final_path).unlink() # Delete the oversized file
                return DownloadResult(success=False, error=err_msg)

            track_info = None
            json_path = self._settings.DOWNLOADS_DIR / f"{video_id}.info.json"
            if json_path.exists():
                try:
                    import json
                    info = json.loads(json_path.read_text(encoding="utf-8"))
                    track_info = TrackInfo(
                        title=info.get("title", "Unknown"),
                        artist=info.get("uploader", "Unknown"),
                        duration=int(info.get("duration") or 0),
                        source=Source.YOUTUBE.value,
                        identifier=video_id,
                    )
                    try:
                        json_path.unlink()
                    except OSError: pass
                except Exception: pass

            if not track_info:
                track_info = TrackInfo("Unknown", "Unknown", 0, Source.YOUTUBE.value, video_id)

            result = DownloadResult(True, final_path, track_info)
            await self._cache.set(cache_key, Source.YOUTUBE, result)
            return result

        except Exception as e:
            logger.error(f"Critical DL error: {e}", exc_info=True)
            return DownloadResult(success=False, error=str(e))

    async def download_with_retry(self, query: str) -> DownloadResult:
        """
        Выполняет загрузку с несколькими попытками в случае сбоя.
        """
        for attempt in range(self._settings.MAX_RETRIES):
            try:
                async with self.semaphore:
                    result = await self.download(query)
                if result and result.success:
                    return result
                
                # Специальная обработка для 503 ошибки, чтобы подождать подольше
                if result and result.error and "503" in result.error:
                    logger.warning("[Downloader] Получен код 503 от сервера. Большая пауза...")
                    await asyncio.sleep(60 * (attempt + 1))

            except (asyncio.TimeoutError, Exception) as e:
                logger.error(f"[Downloader] Исключение при загрузке (попытка {attempt + 1}): {e}", exc_info=True)
            
            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S * (attempt + 1))

        return DownloadResult(
            success=False,
            error=f"Не удалось скачать после {self._settings.MAX_RETRIES} попыток.",
        )
