from __future__ import annotations

import asyncio
import glob
import logging
import re
import subprocess
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
        # Ограничиваем количество одновременных загрузок
        self.semaphore = asyncio.Semaphore(3)

    def _base_opts(self) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "source_address": "0.0.0.0",
            # Используем обобщенный User-Agent во избежание блокировок
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "no_check_certificate": True,
            "prefer_insecure": True,
            "noprogress": True,
            "retries": 10,
            "fragment_retries": 10,
            "skip_unavailable_fragments": True,
            "continuedl": True,
            "overwrites": True,
            # Важно для VEVO видео (как AC/DC)
            "geo_bypass": True, 
        }
        if getattr(self._settings, "COOKIES_FILE", None) and self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
            opts["cookiefile"] = str(self._settings.COOKIES_FILE)
        return opts

    def _search_opts(self) -> Dict[str, Any]:
        opts = self._base_opts()
        opts["extract_flat"] = True
        return opts

    def _info_opts(self) -> Dict[str, Any]:
        # ВАЖНО: не задаём format, чтобы extract_info не падал на выборе формата
        return self._base_opts()

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
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}
            ]
            options["outtmpl"] = str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s")
            if self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
                options["cookiefile"] = str(self._settings.COOKIES_FILE)
        return options

    def _download_opts(self, fmt: str) -> Dict[str, Any]:
        opts = self._base_opts()
        opts.update(
            {
                "format": fmt,
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "max_filesize": self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024,
            }
        )
        return opts

    async def _extract_info(
        self,
        query: str,
        ydl_opts: Dict[str, Any],
        *,
        download: bool = False,
        process: bool = True,
    ) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(query, download=download, process=process),
        )

    async def search(
        self,
        query: str,
        limit: int = 30,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
        match_filter: Optional[str] = None, # Добавлен параметр match_filter
        **kwargs,
    ) -> List[TrackInfo]:
        # Объединенная и исправленная функция поиска
        ydl_opts = self._get_ydl_options(
            is_search=True, 
            match_filter=match_filter,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        info = await self._extract_info(f"ytsearch{limit}:{query}", ydl_opts, process=True)
        entries = (info or {}).get("entries") or []

        # --- Усиленная и строгая фильтрация в Python ---
        BANNED_WORDS = [
            'ai cover', 'suno', 'udio', 'ai version', 'karaoke', 'караоке',
            'ии кавер', 'сгенерировано ии', 'ai generated', '24/7', 'live radio',
            'podcast', 'подкаст', 'interview', 'интервью', 'vlog', 'влог',
            'full album', 'полный альбом', 'playlist', 'плейлист', 'compilation',
            'сборник', 'mix', 'микс', 'tribute', 'пародия', 'reaction', 'реакция',
            'tutorial', 'обучение', 'lesson', 'урок', 'cover by', 'кавер от',
            'remix by', 'ремикс от', 'mashup', 'мэшап', 'live performance',
            'концерт', 'выступление', 'official video', 'music video'
        ]
        
        final_entries = []
        for e in entries:
            if not (e and e.get("title")):
                continue
            
            # Явная проверка на флаг is_live
            if e.get('is_live') is True:
                logger.warning(f"Пропущен LIVE трек (по флагу is_live): {e.get('title')}")
                continue

            # Проверка по стоп-словам в названии
            title_lower = e.get("title", "").lower()
            if any(banned in title_lower for banned in BANNED_WORDS):
                logger.warning(f"Пропущен трек по стоп-слову '{[b for b in BANNED_WORDS if b in title_lower][0]}': {e.get('title')}")
                continue
            
            final_entries.append(e)

        entries = final_entries
        # --- КОНЕЦ НОВОЙ ЛОГИКИ ---

        # Сначала отфильтровываем по категории "Music"
        music_entries = [
            e for e in entries 
            if e and isinstance(e.get("categories"), list) and "Music" in e.get("categories", [])
        ]
        
        # Если после фильтрации ничего не осталось, используем оригинальный список
        if not music_entries:
            logger.warning(f"[YouTube Search] Не найдено треков с категорией 'Music' для запроса '{query}'. Использую все результаты.")
            music_entries = entries

        out: List[TrackInfo] = []
        for e in music_entries:
            if not e or not e.get("id") or not isinstance(e["id"], str) or len(e["id"]) != 11:
                continue
            if e.get("is_live"):
                continue

            duration = int(e.get("duration") or 0)
            
            # Фильтрация
            if min_duration is not None and duration and duration < min_duration:
                continue
            if max_duration is not None and duration and duration > max_duration:
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

        # --- Python-based Quality Filter ---
        def is_high_quality(e: Dict[str, Any]) -> bool:
            title = e.get('title', '').lower()
            channel = e.get('channel', '').lower()
            
            is_good_title = any(kw in title for kw in ['audio', 'lyric', 'альбом', 'album'])
            is_topic_channel = channel.endswith(' - topic')
            is_bad_title = any(kw in title for kw in [
                'live', 'short', 'концерт', 'выступление', 'official video', 
                'music video', 'full show', 'interview', 'parody', 'влог', 
                'vlog', 'топ 10', 'mix', 'сборник', 'playlist'
            ])
            
            return (is_good_title or is_topic_channel) and not is_bad_title

        def is_valid_video_entry(e: Dict[str, Any]) -> bool:
            """Проверяет, что ID похож на ID видео, а не канала."""
            entry_id = e.get('id')
            return entry_id and len(entry_id) == 11

        # --- Попытка 1: строгий поиск ---
        logger.debug(f"[SmartSearch] Попытка 1: строгий поиск с запросом '{smart_query}'")
        ydl_opts_strict = self._get_ydl_options(
            is_search=True,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        
        try:
            info = await self._extract_info(f"ytsearch5:{smart_query}", ydl_opts_strict)
            if info and info.get("entries"):
                entries = info["entries"]
                
                # Применяем фильтры в Python
                valid_entries = [e for e in entries if is_valid_video_entry(e)]
                high_quality_entries = [e for e in valid_entries if is_high_quality(e)]

                # Сначала ищем в музыкальной категории качественных треков
                music_entries = [e for e in high_quality_entries if isinstance(e.get("categories"), list) and "Music" in e.get("categories", [])]
                if music_entries:
                    entry = music_entries[0]
                    logger.info(f"[SmartSearch] Успех (строгий поиск, high quality, music)! Найден: {entry['title']}")
                    return TrackInfo(
                        title=entry["title"], artist=entry.get("channel", entry.get("uploader", "Unknown")),
                        duration=int(entry.get("duration", 0)), source=Source.YOUTUBE.value, identifier=entry["id"])

                # Если не нашли, ищем любой качественный
                if high_quality_entries:
                    entry = high_quality_entries[0]
                    logger.info(f"[SmartSearch] Успех (строгий поиск, high quality)! Найден: {entry['title']}")
                    return TrackInfo(
                        title=entry["title"], artist=entry.get("channel", entry.get("uploader", "Unknown")),
                        duration=int(entry.get("duration", 0)), source=Source.YOUTUBE.value, identifier=entry["id"])

        except Exception as e:
            logger.warning(f"[SmartSearch] Ошибка на этапе строгого поиска: {e}")

        # --- Попытка 2: обычный поиск ---
        logger.info("[SmartSearch] Строгий поиск не дал результатов, перехожу к обычному поиску.")
        ydl_opts_fallback = self._get_ydl_options(
            is_search=True,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        try:
            info = await self._extract_info(f"ytsearch1:{query}", ydl_opts_fallback)
            if info and info.get("entries"):
                # Применяем только фильтр на валидность видео
                valid_entries = [e for e in info["entries"] if is_valid_video_entry(e)]
                
                if not valid_entries:
                    logger.warning(f"[SmartSearch] Обычный поиск по запросу '{query}' не дал валидных видео.")
                    return None

                # Ищем музыкальные треки
                music_entries = [e for e in valid_entries if isinstance(e.get("categories"), list) and "Music" in e.get("categories", [])]
                if music_entries:
                    entry = music_entries[0]
                    logger.info(f"[SmartSearch] Успех (обычный поиск, music)! Найден: {entry['title']}")
                    return TrackInfo(
                        title=entry["title"], artist=entry.get("channel", entry.get("uploader", "Unknown")),
                        duration=int(entry.get("duration", 0)), source=Source.YOUTUBE.value, identifier=entry["id"])

                # Берем просто первое валидное видео
                entry = valid_entries[0]
                logger.info(f"[SmartSearch] Музыкальных треков не найдено (обычный поиск), беру первый результат: {entry['title']}")
                return TrackInfo(
                    title=entry["title"], artist=entry.get("channel", entry.get("uploader", "Unknown")),
                    duration=int(entry.get("duration", 0)), source=Source.YOUTUBE.value, identifier=entry["id"])
        
        except Exception as e:
            logger.error(f"[SmartSearch] Ошибка на этапе обычного поиска: {e}")
            return None
        
        logger.warning(f"[SmartSearch] Поиск по запросу '{query}' не дал никаких результатов.")
        return None

    def _pick_downloaded_file(self, video_id: str) -> Optional[str]:
        files = glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*"))
        # Исключаем временные файлы yt-dlp
        files = [f for f in files if not f.endswith((".part", ".ytdl", ".json", ".webp", ".jpg", ".png"))]
        if not files:
            return None

        # Приоритет форматов
        pref = [".m4a", ".mp3", ".opus", ".ogg", ".mp4", ".webm"]
        files_sorted = sorted(
            files,
            key=lambda p: pref.index(Path(p).suffix.lower()) if Path(p).suffix.lower() in pref else 999,
        )
        return files_sorted[0]

    def _ffmpeg_available(self) -> bool:
        try:
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return True
        except Exception:
            return False

    def _convert_to_mp3(self, input_path: str, video_id: str) -> Optional[str]:
        out_path = str(self._settings.DOWNLOADS_DIR / f"{video_id}.mp3")
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", input_path,
                    "-vn", "-ac", "2", "-b:a", "192k",
                    out_path,
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
            )
            return out_path
        except Exception:
            logger.warning("ffmpeg convert failed", exc_info=True)
            return None

    async def download_with_retry(self, query: str) -> DownloadResult:
        for attempt in range(self._settings.MAX_RETRIES):
            try:
                async with self.semaphore:
                    result = await self.download(query)

                if result and result.success:
                    return result

                if result and result.error and "503" in result.error:
                    logger.warning("[YouTubeDownloader] Получен код 503 от сервера. Большая пауза...")
                    await asyncio.sleep(60 * (attempt + 1))

                # Не ретраим заведомо бесполезное
                if result and result.error and "Requested format is not available" in (result.error or ""):
                    return result

            except Exception:
                logger.exception("[YouTubeDownloader] download_with_retry exception")

            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S * (attempt + 1))

        return DownloadResult(success=False, error="Не удалось скачать после нескольких попыток.")

    async def download(self, query_or_id: str) -> DownloadResult:
        is_id = self.YT_ID_RE.match(query_or_id) is not None
        video_id: Optional[str]

        try:
            if is_id:
                video_id = query_or_id
            else:
                track_info_for_dl = await self._find_best_match(
                    query_or_id,
                    min_duration=self._settings.PLAY_MIN_DURATION_S,
                    max_duration=self._settings.PLAY_MAX_DURATION_S
                )
                if not track_info_for_dl:
                    return DownloadResult(success=False, error="Ничего не найдено.")
                video_id = track_info_for_dl.identifier

            if not video_id:
                return DownloadResult(success=False, error="Ничего не найдено.")

            cache_key = f"yt:{video_id}"
            cached = await self._cache.get(cache_key, Source.YOUTUBE)
            if cached:
                # Проверяем, существует ли файл физически
                if Path(cached.file_path).exists():
                    return cached
                else:
                    await self._cache.delete(cache_key)

            video_url = f"https://www.youtube.com/watch?v={video_id}"

            # Метаданные без выбора формата
            info = await self._extract_info(video_url, self._info_opts(), process=False)
            if not info:
                return DownloadResult(success=False, error="Не удалось получить информацию о видео.")

            track_info = TrackInfo(
                title=info.get("title", "Unknown"),
                artist=info.get("channel") or info.get("uploader") or "Unknown",
                duration=int(info.get("duration") or 0),
                source=Source.YOUTUBE.value,
                identifier=video_id,
            )

            if track_info.duration and track_info.duration > self._settings.PLAY_MAX_DURATION_S:
                return DownloadResult(
                    success=False, error=f"Трек слишком длинный ({track_info.format_duration()})."
                )

            # 3 ступени fallback:
            # 1) AAC/mp4a audio-only (идеально для WebView)
            # 2) любой audio-only
            # 3) muxed (видео+аудио) — иначе старые ролики будут постоянно “format not available”
            format_candidates = [
                "bestaudio[vcodec=none][acodec^=mp4a][ext=m4a]/bestaudio[vcodec=none][acodec^=mp4a]",
                "bestaudio[vcodec=none]/best[acodec!=none][vcodec=none]",
                "best[acodec!=none]/best",
            ]

            last_err: Exception | None = None
            download_successful = False

            for fmt in format_candidates:
                try:
                    ydl_opts = self._download_opts(fmt)
                    await asyncio.wait_for(
                        asyncio.get_running_loop().run_in_executor(
                            None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([video_url])
                        ),
                        timeout=self._settings.DOWNLOAD_TIMEOUT_S,
                    )
                    download_successful = True
                    break # Успех, выходим из цикла перебора форматов
                except (DownloadError, ExtractorError) as e:
                    last_err = e
                    if "Requested format is not available" in str(e):
                        continue
                    raise

            if not download_successful:
                return DownloadResult(success=False, error=f"Requested format is not available: {last_err}")
            
            # 3) Находим реальный файл
            path = self._pick_downloaded_file(video_id)
            if not path:
                return DownloadResult(success=False, error="Файл скачан, но не найден на диске.")

            # Опционально: принудительно делать mp3 (максимальная совместимость WebApp)
            if getattr(self._settings, "FORCE_MP3_FOR_WEBAPP", False):
                if self._ffmpeg_available():
                    mp3 = self._convert_to_mp3(path, video_id)
                    if mp3:
                        try:
                            if path != mp3: Path(path).unlink()
                        except OSError:
                            pass
                        path = mp3
                    else:
                        logger.warning(f"Failed to convert {path} to MP3. Serving original.")
                else:
                    logger.warning("FORCE_MP3_FOR_WEBAPP включен, но ffmpeg не найден в контейнере. Пропуск.")


            result = DownloadResult(True, path, track_info)
            await self._cache.set(cache_key, Source.YOUTUBE, result)
            return result

        except (DownloadError, ExtractorError) as e:
            msg = str(e)
            if "Requested format is not available" in msg:
                return DownloadResult(success=False, error=f"Requested format is not available: {msg}")
            if "File is larger than max-filesize" in msg:
                return DownloadResult(
                    success=False,
                    error=f"Файл слишком большой ( > {self._settings.PLAY_MAX_FILE_SIZE_MB}MB).",
                )
            logger.error("YouTube error: %s", msg, exc_info=True)
            return DownloadResult(success=False, error=msg)
        except Exception as e:
            logger.error("Unknown YouTube error: %s", e, exc_info=True)
            return DownloadResult(success=False, error=str(e))