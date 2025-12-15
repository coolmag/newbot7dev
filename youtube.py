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
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "source_address": "0.0.0.0",
            # Стандартный User-Agent, чтобы не палиться
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "no_check_certificate": True,
            "prefer_insecure": True,
            "geo_bypass": True,
            "retries": 10,
            "fragment_retries": 10,
            "skip_unavailable_fragments": True,
        }

        if getattr(self._settings, "COOKIES_FILE", None) and self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
            opts["cookiefile"] = str(self._settings.COOKIES_FILE)

        if is_search:
            opts["extract_flat"] = True
        else:
            opts.update({
                "format": "bestaudio/best",
                "outtmpl": str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "max_filesize": 50 * 1024 * 1024,
            })
        
        return opts

    async def _extract_info(self, query: str, opts: Dict[str, Any], download: bool = False) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: yt_dlp.YoutubeDL(opts).extract_info(query, download=download)
        )

    # === LOGIC FROM V5 START ===

    async def _find_best_match(self, query: str) -> Optional[TrackInfo]:
        """
        Интеллектуальный поиск (как в v5).
        """
        # 1. Формируем "умный" запрос
        smart_query_parts = [query]
        if "советск" in query.lower() or "ссср" in query.lower():
            smart_query_parts.extend(["гостелерадиофонд", "эстрада"])
        else:
            smart_query_parts.extend(["official audio", "topic", "lyrics"])
        
        smart_query = " ".join(smart_query_parts)
        
        logger.info(f"[SmartSearch] Попытка 1: строгий поиск '{smart_query}'")
        
        # Функция фильтрации (V5 Logic)
        def is_high_quality(e: Dict[str, Any]) -> bool:
            title = e.get('title', '').lower()
            channel = e.get('channel', '').lower()
            
            is_good_title = any(kw in title for kw in ['audio', 'lyric', 'альбом', 'album', 'topic'])
            is_topic_channel = 'topic' in channel
            
            is_bad_title = any(kw in title for kw in [
                'live', 'short', 'концерт', 'official video', 
                'full show', 'interview', 'parody', 'vlog', 
                '10 hours', '1 hour', 'mix', 'compilation'
            ])
            
            return (is_good_title or is_topic_channel) and not is_bad_title

        # Попытка 1: Строгий поиск
        opts = self._get_opts(is_search=True)
        try:
            info = await self._extract_info(f"ytsearch5:{smart_query}", opts, download=False)
            entries = info.get("entries", []) or []
            
            valid_entries = [e for e in entries if e.get("id") and len(e["id"]) == 11]
            high_quality_entries = [e for e in valid_entries if is_high_quality(e)]
            
            # Приоритет: Music category
            music_entries = [e for e in high_quality_entries if isinstance(e.get("categories"), list) and "Music" in e.get("categories", [])]
            
            best_entry = None
            if music_entries:
                best_entry = music_entries[0]
            elif high_quality_entries:
                best_entry = high_quality_entries[0]
            
            if best_entry:
                logger.info(f"[SmartSearch] Найдено (High Quality): {best_entry.get('title')}")
                return TrackInfo(
                    title=best_entry.get("title", "Unknown"),
                    artist=best_entry.get("channel") or best_entry.get("uploader") or "Unknown",
                    duration=int(best_entry.get("duration") or 0),
                    source=Source.YOUTUBE.value,
                    identifier=best_entry["id"]
                )

        except Exception as e:
            logger.warning(f"Smart search error: {e}")

        # Попытка 2: Обычный поиск (Fallback)
        logger.info(f"[SmartSearch] Попытка 2: обычный поиск '{query}'")
        try:
            info = await self._extract_info(f"ytsearch3:{query}", opts, download=False)
            entries = info.get("entries", []) or []
            
            for e in entries:
                if not e or not e.get("id"): continue
                
                # Базовый фильтр от мусора
                title = e.get("title", "").lower()
                if "10 hours" in title or "1 hour" in title or "full album" in title:
                    continue
                
                logger.info(f"[SmartSearch] Найдено (Fallback): {e.get('title')}")
                return TrackInfo(
                    title=e.get("title", "Unknown"),
                    artist=e.get("channel") or e.get("uploader") or "Unknown",
                    duration=int(e.get("duration") or 0),
                    source=Source.YOUTUBE.value,
                    identifier=e["id"]
                )
                
        except Exception as e:
            logger.error(f"Fallback search error: {e}")

        return None

    # === LOGIC FROM V5 END ===

    async def search(
        self,
        query: str,
        limit: int = 30,
        **kwargs,
    ) -> List[TrackInfo]:
        """
        Массовый поиск (для радио). Используем логику V5 для фильтрации.
        """
        # Используем "умный запрос" но без фанатизма, чтобы получить список
        clean_query = query # Можно добавить минус-слова
        
        search_query = f"ytsearch{limit * 2}:{clean_query}"
        opts = self._get_opts(is_search=True)

        try:
            info = await self._extract_info(search_query, opts, download=False)
            entries = info.get("entries", []) or []

            out: List[TrackInfo] = []
            
            # Логика фильтрации списка (V5 style)
            BANNED_WORDS = [
                'ai cover', 'suno', 'udio', 'ai version', 
                '10 hours', '1 hour', 'mix 20', 'full album', 'playlist'
            ]

            for e in entries:
                if not e or not e.get("id"): continue
                if e.get("is_live"): continue

                title = e.get("title", "").lower()
                
                # Фильтр стоп-слов
                if any(b in title for b in BANNED_WORDS):
                    if "mix" not in query.lower(): # Если юзер не просил микс
                        continue

                duration = int(e.get("duration") or 0)
                # Фильтр длительности
                if duration > 1200: continue # > 20 мин
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

                # Ошибки без ретрая
                err = str(result.error).lower() if result.error else ""
                if "too long" in err or "large" in err:
                    return result

                if "503" in err:
                    await asyncio.sleep(10 * (attempt + 1))

            except Exception as e:
                logger.error(f"[YouTube] Attempt {attempt+1} error: {e}")

            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S)

        return DownloadResult(success=False, error="Download failed.")

    async def download(self, query_or_id: str) -> DownloadResult:
        is_id = self.YT_ID_RE.match(query_or_id) is not None
        
        # 1. Поиск ID (V5 Smart Search)
        video_id: str
        if is_id:
            video_id = query_or_id
        else:
            found_track = await self._find_best_match(query_or_id)
            if not found_track:
                return DownloadResult(success=False, error="Ничего не найдено (SmartSearch).")
            video_id = found_track.identifier

        # 2. Кэш
        cache_key = f"yt:{video_id}"
        cached = await self._cache.get(cache_key, Source.YOUTUBE)
        if cached:
            if Path(cached.file_path).exists():
                return cached
            else:
                await self._cache.delete(cache_key)

        video_url = f"https://www.youtube.com/watch?v={video_id}"
        opts = self._get_opts(is_search=False)
        loop = asyncio.get_running_loop()
        
        try:
            # 3. Скачивание
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
            if "too long" in str(e) or "large" in str(e):
                return DownloadResult(success=False, error="Файл слишком большой.")
            # Игнорируем другие ошибки yt-dlp, если файл скачался

        # 4. Поиск файла на диске (V5 method)
        pattern = str(self._settings.DOWNLOADS_DIR / f"{video_id}.*")
        files = glob.glob(pattern)
        valid_files = [f for f in files if not f.endswith((".part", ".ytdl", ".json", ".webp"))]
        
        if not valid_files:
            return DownloadResult(success=False, error="Файл не найден на диске.")
        
        # Приоритет mp3
        final_path = valid_files[0]
        for f in valid_files:
            if f.endswith(".mp3"):
                final_path = f
                break

        # 5. Метаданные
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