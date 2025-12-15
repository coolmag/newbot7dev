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

    def _get_opts(self, is_search: bool = False) -> Dict[str, Any]:
        """
        Настройки с жестким ограничением размера.
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
            "retries": 3,
            "fragment_retries": 3,
            "skip_unavailable_fragments": True,
            "match_filter": yt_dlp.utils.match_filter_func("duration < 900 & !is_live"),
        }

        if getattr(self._settings, "COOKIES_FILE", None) and self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
            opts["cookiefile"] = str(self._settings.COOKIES_FILE)

        if is_search:
            opts["extract_flat"] = True
        else:
            opts.update({
                "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }],
                # === ЖЕСТКИЙ ЛИМИТ 20 МБ ===
                "max_filesize": 20 * 1024 * 1024,
            })
        
        return opts

    async def _extract_info(self, query: str, opts: Dict[str, Any], download: bool = False) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: yt_dlp.YoutubeDL(opts).extract_info(query, download=download)
        )

    def _find_downloaded_file(self, video_id: str) -> Optional[str]:
        pattern = str(self._settings.DOWNLOADS_DIR / f"{video_id}.*")
        files = glob.glob(pattern)
        valid_files = [f for f in files if not f.endswith((".part", ".ytdl", ".json", ".webp"))]
        
        if not valid_files:
            return None
        valid_files.sort(key=lambda x: 0 if x.endswith(".mp3") else 1)
        return valid_files[0]

    async def search(
        self,
        query: str,
        limit: int = 30,
        **kwargs,
    ) -> List[TrackInfo]:
        """
        Поиск с фильтрацией.
        """
        # Добавляем минус-слова для YouTube
        clean_query = f'{query} -live -radio -stream -24/7 -"10 hours" -"1 hour" -"mix 20"'
        search_query = f"ytsearch{limit * 2}:{clean_query}"
        opts = self._get_opts(is_search=True)

        try:
            info = await self._extract_info(search_query, opts, download=False)
            entries = info.get("entries", []) or []

            out: List[TrackInfo] = []
            
            BANNED = ['10 hours', '1 hour', 'mix 20', 'full album', 'playlist']

            for e in entries:
                if not e or not e.get("id"): continue
                
                # Строгие проверки
                if e.get("is_live"): continue
                
                title = e.get("title", "").lower()
                if any(b in title for b in BANNED) and "mix" not in query.lower():
                    continue

                duration = int(e.get("duration") or 0)
                if duration == 0: continue # Скорее всего стрим
                if duration > 900: continue # > 15 мин
                if duration < 30: continue 

                out.append(
                    TrackInfo(
                        title=e.get("title", "Unknown"),
                        artist=e.get("channel") or e.get("uploader") or "Unknown",
                        duration=duration,
                        source=Source.YOUTUBE.value,
                        identifier=e["id"],
                    )
                )
                if len(out) >= limit: break
            return out

        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def download_with_retry(self, query: str) -> DownloadResult:
        for attempt in range(self._settings.MAX_RETRIES):
            try:
                async with self.semaphore:
                    result = await self.download(query)

                if result and result.success:
                    return result

                if result.error and ("too long" in str(result.error) or "large" in str(result.error)):
                    return result 

            except Exception as e:
                logger.error(f"Attempt {attempt+1} error: {e}")

            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S)

        return DownloadResult(success=False, error="Download failed.")

    async def download(self, query_or_id: str) -> DownloadResult:
        is_id = self.YT_ID_RE.match(query_or_id) is not None
        video_id = query_or_id if is_id else None

        try:
            if not video_id:
                found = await self.search(query_or_id, limit=1)
                if not found:
                    return DownloadResult(success=False, error="Ничего не найдено (фильтр скрыл стримы).")
                video_id = found[0].identifier

            cache_key = f"yt:{video_id}"
            cached = await self._cache.get(cache_key, Source.YOUTUBE)
            if cached and Path(cached.file_path).exists():
                return cached
            elif cached:
                await self._cache.delete(cache_key)

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            opts = self._get_opts(is_search=False)
            loop = asyncio.get_running_loop()
            
            # Предварительная проверка метаданных
            try:
                info_check = await self._extract_info(video_url, self._get_opts(is_search=True), download=False)
                if info_check:
                    dur = int(info_check.get("duration") or 0)
                    if dur > 900: return DownloadResult(success=False, error="Трек слишком длинный.")
                    if dur == 0: return DownloadResult(success=False, error="Вероятно стрим.")
            except: pass

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
                if "large" in str(e) or "long" in str(e):
                    return DownloadResult(success=False, error="Файл слишком большой.")
                logger.warning(f"DL Warning: {e}")

            final_path = self._find_downloaded_file(video_id)
            if not final_path:
                return DownloadResult(success=False, error="Файл не найден на диске.")

            try:
                info = await self._extract_info(video_url, self._get_opts(is_search=True), download=False)
            except: info = {}

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

        except Exception as e:
            logger.error(f"DL error: {e}", exc_info=True)
            return DownloadResult(success=False, error=str(e))