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
        if getattr(self._settings, "COOKIES_FILE", None) and self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
            opts["cookiefile"] = str(self._settings.COOKIES_FILE)
        return opts

    def _search_opts(self, min_duration: int | None = None, max_duration: int | None = None) -> Dict[str, Any]:
        opts = self._base_opts()
        # Для поиска можно оставить плоский режим, но duration иногда бывает 0 — это ок
        opts["extract_flat"] = True
        return opts

    def _info_opts(self) -> Dict[str, Any]:
        # ВАЖНО: не задаём format, чтобы extract_info не падал на выборе формата
        return self._base_opts()

    def _download_opts(self, fmt: str) -> Dict[str, Any]:
        opts = self._base_opts()
        opts.update(
            {
                "format": fmt,
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "% (id)s.%(ext)s"),
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
        **kwargs,
    ) -> List[TrackInfo]:
        # min/max duration здесь можно фильтровать уже “вручную”, т.к. extract_flat не всегда даёт duration
        info = await self._extract_info(f"ytsearch{limit}:{query}", self._search_opts(), process=True)
        entries = (info or {}).get("entries") or []

        out: List[TrackInfo] = []
        for e in entries:
            if not e or not e.get("id") or not isinstance(e["id"], str) or len(e["id"]) != 11:
                continue
            if e.get("is_live"):
                continue

            duration = int(e.get("duration") or 0)
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

    def _pick_downloaded_file(self, video_id: str) -> Optional[str]:
        files = glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.*"))
        files = [f for f in files if not f.endswith((".part", ".ytdl", ".json", ".webp", ".jpg", ".png"))]
        if not files:
            return None

        pref = [".m4a", ".mp3", ".mp4", ".webm", ".opus", ".ogg"]
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
        """
        Конвертация в mp3 для максимальной совместимости WebApp.
        Требует ffmpeg в контейнере.
        """
        out_path = str(self._settings.DOWNLOADS_DIR / f"{video_id}.mp3")

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    input_path,
                    "-vn",
                    "-ac",
                    "2",
                    "-b:a",
                    "192k",
                    out_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
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

                # Не ретраим “формат не найден” (бесполезно)
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
                # берём первый валидный id из поиска
                found = await self.search(query_or_id, limit=5)
                video_id = found[0].identifier if found else None

            if not video_id:
                return DownloadResult(success=False, error="Ничего не найдено.")

            cache_key = f"yt:{video_id}"
            cached = await self._cache.get(cache_key, Source.YOUTUBE)
            if cached:
                return cached

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

            # Опционально: принудительно делать mp3 (максимальная совместимость WebApp)
            if getattr(self._settings, "FORCE_MP3_FOR_WEBAPP", False):
                if self._ffmpeg_available():
                    mp3 = self._convert_to_mp3(path, video_id)
                    if mp3:
                        # Удаляем исходный файл после конвертации
                        try:
                            Path(path).unlink()
                        except OSError as e:
                            logger.warning(f"Error deleting original file after MP3 conversion: {e}")
                        path = mp3
                    else:
                        logger.warning(f"Failed to convert {path} to MP3. Serving original.")
                else:
                    logger.warning("FORCE_MP3_FOR_WEBAPP включен, но ffmpeg не найден в контейнере. Пропуск конвертации.")


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

    async def search(self, query: str, **kwargs) -> List[TrackInfo]:
        limit = int(kwargs.get("limit", 30))
        opts = self._search_opts()
        # Добавляем фильтры по длительности для поиска, если они переданы
        min_duration = kwargs.get("min_duration")
        max_duration = kwargs.get("max_duration")
        if min_duration is not None or max_duration is not None:
            expr = []
            if min_duration is not None:
                expr.append(f"duration >= {min_duration}")
            if max_duration is not None:
                expr.append(f"duration <= {max_duration}")
            opts["match_filter"] = yt_dlp.utils.match_filter_func(" & ".join(expr))


        try:
            info = await self._extract_info(f"ytsearch{limit}:{query}", opts, download=False, process=True)
            entries = (info or {}).get("entries") or []
            out: List[TrackInfo] = []
            for e in entries:
                if e and e.get("id"):
                    # Применяем фильтры по длительности после получения инфо
                    duration = int(e.get("duration") or 0)
                    if (min_duration is not None and duration < min_duration) or \
                       (max_duration is not None and duration > max_duration):
                        continue
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
