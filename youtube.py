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
            # Обычный User-Agent
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
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }],
                # Лимит 30 МБ (хватит на любой трек, но не на микс)
                "max_filesize": 30 * 1024 * 1024,
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
        pattern = str(self._settings.DOWNLOADS_DIR / f"{video_id}.*")
        files = glob.glob(pattern)
        valid_files = [f for f in files if not f.endswith((".part", ".ytdl", ".json", ".webp", ".jpg", ".png"))]
        if not valid_files: return None
        valid_files.sort(key=lambda x: 0 if x.endswith(".mp3") else 1)
        return valid_files[0]

    async def search(
        self,
        query: str,
        limit: int = 30,
        **kwargs,
    ) -> List[TrackInfo]:
        """
        Умный поиск.
        """
        # Минус-слова для YouTube
        clean_query = f'{query} -live -stream -"10 hours" -"full album"'
        search_query = f"ytsearch{limit * 2}:{clean_query}"
        opts = self._get_opts(mode="search")

        try:
            info = await self._extract_info(search_query, opts)
            entries = info.get("entries", []) or []

            out: List[TrackInfo] = []
            
            BANNED = [
                '10 hours', '1 hour', 'mix 20', 'full album', 'playlist', 
                'compilation', 'live radio', '24/7', 'stream', 'top 10', 'best of'
            ]

            for e in entries:
                if not e: continue
                vid_id = e.get("id")
                title = e.get("title", "").lower()
                
                if not vid_id: continue

                # Фильтр по названию
                if any(b in title for b in BANNED):
                    if "mix" not in query.lower(): continue

                duration = e.get("duration")
                
                # Если длительность известна, проверяем
                if duration:
                    duration = int(duration)
                    if duration > 900: continue # > 15 мин
                    if duration < 120: continue # < 2 мин
                
                # Если длительность 0 или None - пропускаем (обычно это стримы)
                # НО: иногда это норм треки. Давай рисковать только если это не "Radio"
                elif "radio" in title or "live" in title:
                    continue

                out.append(
                    TrackInfo(
                        title=e.get("title", "Unknown"),
                        artist=e.get("uploader") or "Unknown",
                        duration=duration or 0,
                        source=Source.YOUTUBE.value,
                        identifier=vid_id,
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

                # Фатальные ошибки
                err = str(result.error).lower()
                if "too long" in err or "large" in err:
                    return result

                if "503" in err:
                    await asyncio.sleep(5 * (attempt + 1))

            except Exception as e:
                logger.error(f"DL Attempt {attempt+1} error: {e}")

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
                    return DownloadResult(success=False, error="Ничего не найдено.")
                video_id = found[0].identifier

            # 1. Проверка кэша
            cache_key = f"yt:{video_id}"
            cached = await self._cache.get(cache_key, Source.YOUTUBE)
            if cached and Path(cached.file_path).exists():
                return cached
            elif cached:
                await self._cache.delete(cache_key)

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            opts = self._get_opts(mode="download")
            loop = asyncio.get_running_loop()
            
            # 2. Скачивание (yt-dlp сам проверит max_filesize)
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(
                        None, 
                        lambda: yt_dlp.YoutubeDL(opts).download([video_url])
                    ),
                    timeout=self._settings.DOWNLOAD_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                 return DownloadResult(success=False, error="Таймаут скачивания.")
            except Exception as e:
                if "File is larger" in str(e):
                    return DownloadResult(success=False, error="Файл слишком большой.")
                # Идем дальше, проверяем файл

            # 3. Поиск файла
            final_path = self._find_downloaded_file(video_id)
            if not final_path:
                return DownloadResult(success=False, error="Файл не скачался (возможно, стрим).")

            # 4. Чтение метаданных из .json файла
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
                    # Чистим json после использования
                    try:
                        json_path.unlink()
                    except OSError as e:
                        logger.warning(f"Could not remove info.json file: {e}")

                except Exception as e:
                    logger.warning(f"Could not read metadata JSON for {video_id}: {e}")

            if not track_info:
                track_info = TrackInfo("Unknown", "Unknown", 0, Source.YOUTUBE.value, video_id)

            result = DownloadResult(True, final_path, track_info)
            await self._cache.set(cache_key, Source.YOUTUBE, result)
            return result

        except Exception as e:
            logger.error(f"Critical DL error: {e}", exc_info=True)
            return DownloadResult(success=False, error=str(e))