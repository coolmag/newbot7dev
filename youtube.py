from __future__ import annotations
import asyncio
import glob
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yt_dlp
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
        if mode == "search":
            opts.update({"extract_flat": "in_playlist", "skip_download": True})
        elif mode == "download":
            opts.update({
                "format": "bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}],
                "writeinfojson": True,
            })
        return opts

    async def _extract_info(self, query: str, opts: Dict[str, Any]) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: yt_dlp.YoutubeDL(opts).extract_info(query, download=False)
        )

    def _find_downloaded_file(self, video_id: str) -> Optional[str]:
        pattern = str(self._settings.DOWNLOADS_DIR / f"{video_id}.mp3")
        files = glob.glob(pattern)
        return files[0] if files else None

    async def search(self, query: str, limit: int = 30, **kwargs) -> List[TrackInfo]:
        logger.info(f"[Search] Запуск поиска для: '{query}'")

        def filter_entry(e: Dict[str, Any], strict_mode: bool) -> bool:
            if not e or not e.get("id") or not e.get("title"): return False
            title = e.get('title', '').lower()
            duration = int(e.get('duration') or 0)

            if not (120 <= duration <= 900): return False

            BANNED_WORDS = [
                'cover', 'live', 'concert', 'концерт', 'acoustic', 'karaoke', 'караоке', 
                'instrumental', 'минус', 'vlog', 'влог', 'interview', 'пародия', 'reaction',
                'playlist', 'сборник', 'mix', 'микс', 'чарт', 'chart', 'billboard', 
                'hot 100', 'top', 'топ', 'hits', 'хиты'
            ]
            if any(banned in title for banned in BANNED_WORDS): return False
            if title.count(',') > 3 and "official" not in title: return False

            if strict_mode:
                is_good_title = any(kw in title for kw in ['audio', 'lyric', 'альбом', 'официальный'])
                is_music_category = "Music" in e.get("categories", [])
                if not (is_good_title or is_music_category): return False
            
            return True

        opts = self._get_opts("search")
        opts['match_filter'] = yt_dlp.utils.match_filter_func("!is_live")

        try:
            # Этап 1: Строгий поиск
            strict_query = f"ytsearch{limit}:{query} official audio"
            info = await self._extract_info(strict_query, opts)
            entries = [e for e in info.get("entries", []) or [] if filter_entry(e, strict_mode=True)]
            
            # Этап 2: Если результатов мало, делаем общий поиск
            if len(entries) < limit:
                logger.info(f"[Search] Строгий поиск дал мало результатов ({len(entries)}). Перехожу к общему.")
                fallback_query = f"ytsearch{limit}:{query}"
                info = await self._extract_info(fallback_query, opts)
                
                # Добавляем новые результаты и фильтруем в мягком режиме
                all_entries = entries + (info.get("entries", []) or [])
                entries = [e for e in all_entries if filter_entry(e, strict_mode=False)]

            unique_entries = {e['id']: e for e in entries}.values()
            
            results = [TrackInfo.from_yt_info(e) for e in unique_entries]
            logger.info(f"[Search] Финальный результат: {len(results)} треков для запроса '{query}'")
            return results[:limit]

        except Exception as e:
            logger.error(f"[Search] Критическая ошибка поиска: {e}", exc_info=True)
            return []

    async def download(self, query_or_id: str) -> DownloadResult:
        is_id = self.YT_ID_RE.match(query_or_id) is not None
        video_id = query_or_id if is_id else None

        try:
            if not video_id:
                found_tracks = await self.search(query_or_id, limit=1)
                if not found_tracks:
                    return DownloadResult(success=False, error="Ничего не найдено.")
                video_id = found_tracks[0].identifier

            cache_key = f"yt:{video_id}"
            cached = await self._cache.get(cache_key, Source.YOUTUBE)
            if cached and Path(cached.file_path).exists():
                return cached
            elif cached: await self._cache.delete(cache_key)

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Этап 1: Предварительная проверка метаданных
            info = await self._extract_info(video_url, self._get_opts("search"))
            
            duration = info.get('duration', 0)
            if not (120 <= duration <= 900):
                return DownloadResult(success=False, error=f"Трек имеет недопустимую длительность ({duration}с).")

            max_size_bytes = self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024
            filesize = info.get('filesize_approx') or info.get('filesize')
            if filesize and filesize > max_size_bytes:
                return DownloadResult(success=False, error=f"Файл слишком большой ({filesize / (1024*1024):.1f} MB).")

            # Этап 2: Скачивание
            download_opts = self._get_opts("download")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(download_opts).download([video_url]))

            final_path = self._find_downloaded_file(video_id)
            if not final_path:
                return DownloadResult(success=False, error="Файл не найден после скачивания.")
            
            # Этап 3: Финальная проверка размера
            if Path(final_path).stat().st_size > max_size_bytes:
                Path(final_path).unlink()
                return DownloadResult(success=False, error="Финальный файл превысил лимит размера.")

            track_info = TrackInfo.from_yt_info(info)
            result = DownloadResult(True, str(final_path), track_info)
            await self._cache.set(cache_key, Source.YOUTUBE, result)
            return result

        except Exception as e:
            logger.error(f"Критическая ошибка скачивания: {e}", exc_info=True)
            return DownloadResult(success=False, error=str(e))

    async def download_with_retry(self, query: str) -> DownloadResult:
        for attempt in range(self._settings.MAX_RETRIES):
            try:
                async with self.semaphore:
                    result = await self.download(query)
                if result.success: return result
                if result.error and "503" in result.error:
                    await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"[Downloader] Попытка {attempt + 1}: {e}", exc_info=True)
            
            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S)
        return DownloadResult(success=False, error="Не удалось скачать.")