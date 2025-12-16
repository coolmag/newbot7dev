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

        # --- Фильтры качества на основе предоставленного кода ---
        def is_high_quality(e: Dict[str, Any]) -> bool:
            title = e.get('title', '').lower()
            # Убираем проверку канала, т.к. она ненадежна
            
            is_good_title = any(kw in title for kw in ['audio', 'lyric', 'альбом', 'album', 'официальный'])
            is_bad_title = any(kw in title for kw in [
                'live', 'концерт', 'выступление', 'official video', 'music video', 
                'full show', 'interview', 'parody', 'влог', 'vlog', 'топ', 'mix', 
                'сборник', 'playlist', 'чарт', 'billboard', 'hot 100', 'песен', 'песни'
            ])
            
            return is_good_title and not is_bad_title

        # --- Этап 1: Строгий поиск качественного контента ---
        try:
            # Ищем чуть больше, чтобы было из чего выбрать
            strict_query = f"ytsearch10:{query} official audio"
            opts = self._get_opts("search")
            opts['match_filter'] = yt_dlp.utils.match_filter_func(
                f"duration >= 120 & duration <= 900 & view_count > 1000 & !is_live"
            )
            
            info = await self._extract_info(strict_query, opts)
            entries = info.get("entries", []) or []
            
            high_quality_entries = [e for e in entries if is_high_quality(e)]
            
            if high_quality_entries:
                logger.info(f"[Search] Строгий поиск успешен. Найдено {len(high_quality_entries)} качественных треков.")
                results = []
                for e in high_quality_entries[:limit]:
                    results.append(TrackInfo(
                        title=e.get("title", "Unknown"),
                        artist=e.get("uploader") or "Unknown",
                        duration=int(e.get("duration", 0)),
                        source=Source.YOUTUBE.value,
                        identifier=e["id"],
                    ))
                return results

        except Exception as e:
            logger.warning(f"[Search] Ошибка на этапе строгого поиска: {e}")

        # --- Этап 2: Запасной вариант (Fallback) ---
        logger.info("[Search] Строгий поиск не дал результатов, перехожу к общему поиску.")
        try:
            fallback_query = f"ytsearch{limit}:{query}"
            opts = self._get_opts("search")
            opts['match_filter'] = yt_dlp.utils.match_filter_func(
                 f"duration >= 120 & duration <= 900 & !is_live"
            )
            info = await self._extract_info(fallback_query, opts)
            entries = info.get("entries", []) or []

            # Здесь фильтрация уже не такая строгая
            results = []
            for e in entries:
                title = e.get('title', '').lower()
                if any(kw in title for kw in ['сборник', 'playlist', 'mix', 'топ 100']):
                    continue
                results.append(TrackInfo(
                    title=e.get("title", "Unknown"),
                    artist=e.get("uploader") or "Unknown",
                    duration=int(e.get("duration", 0)),
                    source=Source.YOUTUBE.value,
                    identifier=e["id"],
                ))
            
            logger.info(f"[Search] Общий поиск вернул {len(results)} треков.")
            return results

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
            
            loop = asyncio.get_running_loop()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).download([video_url])),
                    timeout=self._settings.DOWNLOAD_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                 return DownloadResult(success=False, error="Таймаут скачивания.")
            except Exception as e:
                if "File is larger" in str(e):
                    return DownloadResult(success=False, error="Файл слишком большой.")
                raise e

            final_path = self._find_downloaded_file(video_id)
            if not final_path:
                return DownloadResult(success=False, error="Файл не скачался (возможно, стрим).")

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
