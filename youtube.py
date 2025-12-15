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

    def _get_opts(self, is_search: bool = False, query: str = "") -> Dict[str, Any]:
        """
        Настройки с жесткой защитой от длинных видео.
        """
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,
            "source_address": "0.0.0.0",
            "no_check_certificate": True,
            "prefer_insecure": True,
            "geo_bypass": True,
            "retries": 5,
            "fragment_retries": 5,
            "skip_unavailable_fragments": True,
            # Фильтр для самого процесса загрузки (дублирующая защита)
            "match_filter": yt_dlp.utils.match_filter_func("duration < 900 & !is_live"),
        }

        if getattr(self._settings, "COOKIES_FILE", None) and self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
            opts["cookiefile"] = str(self._settings.COOKIES_FILE)

        if is_search:
            opts["extract_flat"] = True
        else:
            opts.update({
                # Приоритет форматов: m4a (самый легкий) -> webm -> любой аудио
                "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }],
                "max_filesize": 50 * 1024 * 1024, # 50 MB
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
        Умный поиск с агрессивной фильтрацией стримов и миксов.
        """
        # Ищем больше, чтобы было из чего выбрать после фильтрации
        search_query = f"ytsearch{limit * 2}:{query}"
        opts = self._get_opts(is_search=True, query=query)

        try:
            info = await self._extract_info(search_query, opts, download=False)
            entries = info.get("entries", []) or []

            out: List[TrackInfo] = []
            
            # Слова, указывающие на длинный контент или мусор
            BANNED_WORDS = [
                # Технические стоп-слова
                'ai cover', 'suno', 'udio', 'ai version', 'generated',
                # Длительность и тип контента
                '10 hours', '1 hour', '2 hours', '3 hours', '10 часов', '1 час',
                'full album', 'full concert', 'compilation', 'mix 20', 'best of',
                'playlist', 'collection', 'vol.', 'vol 1', 'vol 2',
                'study music', 'relaxing music', 'sleep music', 'meditation'
            ]

            for e in entries:
                if not e or not e.get("id") or not e.get("title"):
                    continue
                
                # 1. Проверка флагов (если YouTube их отдал)
                if e.get("is_live"):
                    continue

                title = e.get("title", "")
                title_lower = title.lower()

                # 2. Фильтр по названию (самый важный для flat-extraction)
                if any(banned in title_lower for banned in BANNED_WORDS):
                    # Если запрос пользователя САМ содержит эти слова, то не фильтруем так строго
                    if not any(bw in query.lower() for bw in ['mix', 'album', 'hour']):
                        continue

                duration = int(e.get("duration") or 0)

                # 3. Фильтр по длительности (если она известна)
                if duration > 0:
                    if max_duration is not None and duration > max_duration:
                        continue
                    # Если длительность > 15 мин (900 сек), скипаем
                    if duration > 900:
                        continue
                    # Слишком короткие (интро)
                    if duration < 30:
                        continue
                
                # 4. Если длительность неизвестна (0), но в названии есть подозрительные слова - скип
                elif duration == 0:
                    # Если в названии нет явных признаков трека, лучше пропустить
                    suspicious = ['mix', 'radio', 'live', 'stream', 'non-stop']
                    if any(s in title_lower for s in suspicious):
                        continue

                out.append(
                    TrackInfo(
                        title=title,
                        artist=e.get("channel") or e.get("uploader") or "Unknown",
                        duration=duration,
                        source=Source.YOUTUBE.value,
                        identifier=e["id"],
                    )
                )
                
                if len(out) >= limit:
                    break
                    
            return out

        except Exception as e:
            logger.error(f"Ошибка поиска: {e}")
            return []

    async def download_with_retry(self, query: str) -> DownloadResult:
        for attempt in range(self._settings.MAX_RETRIES):
            try:
                async with self.semaphore:
                    result = await self.download(query)

                if result and result.success:
                    return result

                # Критические ошибки - не ретраим
                err = str(result.error).lower() if result.error else ""
                if "too long" in err or "large" in err or "found" in err:
                    return result

                if "503" in err or "sign in" in err:
                    logger.warning(f"[YouTube] Throttling. Sleep {10 * (attempt + 1)}s...")
                    await asyncio.sleep(10 * (attempt + 1))

            except Exception as e:
                logger.error(f"[YouTube] Attempt {attempt+1} error: {e}")

            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S)

        return DownloadResult(success=False, error="Download failed after retries.")

    async def download(self, query_or_id: str) -> DownloadResult:
        is_id = self.YT_ID_RE.match(query_or_id) is not None
        video_id = query_or_id if is_id else None

        try:
            if not video_id:
                found = await self.search(query_or_id, limit=1)
                if not found:
                    return DownloadResult(success=False, error="Ничего не найдено.")
                video_id = found[0].identifier

            # Кэш
            cache_key = f"yt:{video_id}"
            cached = await self._cache.get(cache_key, Source.YOUTUBE)
            if cached and Path(cached.file_path).exists():
                return cached
            elif cached:
                await self._cache.delete(cache_key) # Битая ссылка в кэше

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            opts = self._get_opts(is_search=False)

            loop = asyncio.get_running_loop()
            
            # Скачивание
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(
                        None, 
                        lambda: yt_dlp.YoutubeDL(opts).extract_info(video_url, download=True)
                    ),
                    timeout=self._settings.DOWNLOAD_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                 return DownloadResult(success=False, error="Таймаут скачивания.")
            except Exception as e:
                # Если yt-dlp выкинул ошибку (например фильтр длительности), ловим её здесь
                if "video is too long" in str(e) or "File is larger" in str(e):
                    return DownloadResult(success=False, error="Файл слишком большой/длинный.")
                raise e

            # Поиск скачанного файла (любое расширение)
            download_pattern = str(self._settings.DOWNLOADS_DIR / f"{video_id}.*")
            found_files = glob.glob(download_pattern)
            valid_files = [f for f in found_files if not f.endswith((".part", ".ytdl", ".json", ".webp", ".jpg"))]
            
            if not valid_files:
                return DownloadResult(success=False, error="Файл не сохранен на диск (возможно, отфильтрован).")
            
            # Выбираем лучший (mp3 > m4a > др)
            final_path = valid_files[0]
            for f in valid_files:
                if f.endswith(".mp3"):
                    final_path = f
                    break
                elif f.endswith(".m4a"):
                    final_path = f

            # Получаем метаданные (быстро)
            try:
                info = await self._extract_info(video_url, self._get_opts(is_search=False), download=False)
            except:
                info = {}

            track_info = TrackInfo(
                title=info.get("title", "Unknown"),
                artist=info.get("channel") or info.get("uploader") or "Unknown",
                duration=int(info.get("duration") or 0),
                source=Source.YOUTUBE.value,
                identifier=video_id,
            )

            result = DownloadResult(True, final_path, track_info)
            await self._cache.set(cache_key, Source.YOUTUBE, result)
            return result

        except (DownloadError, ExtractorError) as e:
            return DownloadResult(success=False, error=f"YT Error: {str(e)[:50]}")
        except Exception as e:
            logger.error(f"Critical DL error: {e}", exc_info=True)
            return DownloadResult(success=False, error=str(e))