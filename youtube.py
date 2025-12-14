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
    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self.semaphore = asyncio.Semaphore(3)

    def _base_opts(self) -> Dict[str, Any]:
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "source_address": "0.0.0.0",
            "user_agent": "Mozilla/5.0",
            "no_check_certificate": True,
            "prefer_insecure": True,
            "noprogress": True,
            "retries": 10,
            "fragment_retries": 10,
            "skip_unavailable_fragments": True,
            "continuedl": True,
            "overwrites": True,
        }
        if getattr(self._settings, "COOKIES_FILE", None) and self._settings.COOKIES_FILE.exists():
            opts["cookiefile"] = str(self._settings.COOKIES_FILE)
        return opts

    def _search_opts(self, min_duration: int | None = None, max_duration: int | None = None) -> Dict[str, Any]:
        opts = self._base_opts()
        opts["extract_flat"] = True

        expr: list[str] = []
        if min_duration is not None:
            expr.append(f"duration >= {min_duration}")
        if max_duration is not None:
            expr.append(f"duration <= {max_duration}")

        if expr:
            opts["match_filter"] = yt_dlp.utils.match_filter_func(" & ".join(expr))

        return opts

    def _info_opts(self) -> Dict[str, Any]:
        # ВАЖНО: никаких format/format_sort тут не нужно
        return self._base_opts()

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

    async def _find_best_match(self, query: str) -> Optional[str]:
        # Можно увеличить ytsearch5 -> ytsearch10
        opts = self._search_opts(
            min_duration=self._settings.PLAY_MIN_DURATION_S,
            max_duration=self._settings.PLAY_MAX_DURATION_S,
        )

        try:
            info = await self._extract_info(f"ytsearch5:{query}", opts, download=False, process=True)
            entries = (info or {}).get("entries") or []
            for e in entries:
                if not e or not e.get("id"):
                    continue
                vid = e["id"]
                if isinstance(vid, str) and len(vid) == 11:
                    return vid
        except Exception:
            logger.warning("[SmartSearch] search failed", exc_info=True)

        return None

    def _pick_downloaded_file(self, video_id: str) -> Optional[str]:
        # берём любой файл с этим id, кроме служебных
        files = glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*"))
        files = [
            f for f in files
            if not f.endswith((".part", ".ytdl", ".json", ".webp", ".jpg", ".png"))
        ]
        if not files:
            return None

        # приоритет для WebView: m4a/mp4(aac) > mp3 > остальное
        pref = [".m4a", ".mp4", ".mp3", ".webm", ".opus", ".ogg"]
        files_sorted = sorted(
            files,
            key=lambda p: pref.index(Path(p).suffix.lower()) if Path(p).suffix.lower() in pref else 999,
        )
        return files_sorted[0]

    async def download_with_retry(self, query: str) -> DownloadResult:
        for attempt in range(self._settings.MAX_RETRIES):
            try:
                async with self.semaphore:
                    result = await self.download(query)

                if result and result.success:
                    return result

                # Не ретраим заведомо бесполезное
                if result and result.error and "Requested format is not available" in (result.error or ""):
                    return result

            except Exception:
                logger.error("[YouTubeDownloader] download_with_retry exception", exc_info=True)

            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S * (attempt + 1))

        return DownloadResult(success=False, error="Не удалось скачать после нескольких попыток.")

    async def download(self, query_or_id: str) -> DownloadResult:
        is_id = re.match(r"^[a-zA-Z0-9_-]{11}$", query_or_id) is not None
        cache_key = f"yt:{query_or_id}"

        cached = await self._cache.get(cache_key, Source.YOUTUBE)
        if cached:
            return cached

        try:
            if is_id:
                video_id = query_or_id
            else:
                video_id = await self._find_best_match(query_or_id)

            if not video_id:
                return DownloadResult(success=False, error="Ничего не найдено.")

            video_url = f"https://www.youtube.com/watch?v={video_id}"

            # 1) Метаданные: process=False, чтобы НЕ выбирать форматы
            info = await self._extract_info(video_url, self._info_opts(), download=False, process=False)
            if not info:
                return DownloadResult(success=False, error="Не удалось получить информацию о видео.")

            track_info = TrackInfo(
                title=info.get("title", "Unknown"),
                artist=info.get("channel") or info.get("uploader") or "Unknown",
                duration=int(info.get("duration") or 0),
                source=Source.YOUTUBE.value,
                identifier=video_id,
            )

            if track_info.duration > self._settings.PLAY_MAX_DURATION_S:
                return DownloadResult(
                    success=False, error=f"Трек слишком длинный ({track_info.format_duration()})."
                )

            # 2) Скачивание с fallback форматами
            format_candidates = [
                # 1) Идеально для Telegram WebView/iOS: AAC (mp4a) audio-only
                "bestaudio[vcodec=none][acodec^=mp4a][ext=m4a]/bestaudio[vcodec=none][acodec^=mp4a]",
                # 2) Любой audio-only (может быть webm/opus — на iOS может не играть)
                "bestaudio[vcodec=none]/best[acodec!=none][vcodec=none]",
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
                    break
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
                return DownloadResult(success=False, error="Файл не найден после скачивания.")

            result = DownloadResult(True, path, track_info)
            await self._cache.set(cache_key, Source.YOUTUBE, result)
            return result

        except (DownloadError, ExtractorError) as e:
            msg = str(e)
            if "Requested format is not available" in msg:
                return DownloadResult(success=False, error="Requested format is not available")
            if "File is larger than max-filesize" in msg:
                return DownloadResult(
                    success=False,
                    error=f"Файл слишком большой ( > {self._settings.PLAY_MAX_FILE_SIZE_MB}MB).",
                )
            logger.error("YouTube download error: %s", msg, exc_info=True)
            return DownloadResult(success=False, error=msg)
        except Exception as e:
            logger.error("Unknown YouTube error: %s", e, exc_info=True)
            return DownloadResult(success=False, error=str(e))

    async def search(self, query: str, **kwargs) -> List[TrackInfo]:
        limit = int(kwargs.get("limit", 30))
        opts = self._search_opts(kwargs.get("min_duration"), kwargs.get("max_duration"))
        try:
            info = await self._extract_info(f"ytsearch{limit}:{query}", opts, download=False, process=True)
            entries = (info or {}).get("entries") or []
            out: List[TrackInfo] = []
            for e in entries:
                if e and e.get("id"):
                    out.append(TrackInfo(
                        title=e.get("title", "Unknown"),
                        artist=e.get("channel") or e.get("uploader") or "Unknown",
                        duration=int(e.get("duration") or 0),
                        source=Source.YOUTUBE.value,
                        identifier=e["id"],
                    ))
            return out
        except Exception:
            logger.error("[YouTube] search failed", exc_info=True)
            return []
