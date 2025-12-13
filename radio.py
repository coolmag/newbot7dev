from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional
from pathlib import Path

import logging
from telegram import Bot

from youtube import YouTubeDownloader, BaseDownloader # Предполагаем, что youtube.py теперь содержит YouTubeDownloader
from config import Settings # Используем Settings из нового config
from models import TrackInfo, DownloadResult, Source # Импортируем из нового models

logger = logging.getLogger("radio")





@dataclass
class RadioSession:
    chat_id: int
    query: str
    started_at: float = field(default_factory=lambda: time.time())
    current: Optional[TrackInfo] = None # Изменено на TrackInfo
    playlist: Deque[TrackInfo] = field(default_factory=deque) # Изменено на TrackInfo
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    skip_event: asyncio.Event = field(default_factory=asyncio.Event)
    fails_in_row: int = 0
    last_error: Optional[str] = None
    audio_file_path: Optional[Path] = None


class RadioManager:
    def __init__(
        self,
        bot: Bot,
        settings: Settings, # Изменено: теперь принимаем Settings
        youtube_downloader: YouTubeDownloader, # Добавлено: принимаем YouTubeDownloader
    ) -> None:
        self.bot = bot
        self._settings = settings # Сохраняем настройки
        self.youtube_downloader = youtube_downloader # Сохраняем загрузчик

        self._sessions: Dict[int, RadioSession] = {}
        self._tasks: Dict[int, asyncio.Task[None]] = {}


    def status(self) -> dict:
        data = {}
        for chat_id, s in self._sessions.items():
            current_track_info = None
            if s.current:
                current_track_info = {
                    "title": s.current.title,
                    "artist": s.current.artist,
                    "duration": s.current.duration,
                    "source": s.current.source,
                    "identifier": s.current.identifier,
                    # web_page_url и cover_url отсутствуют в TrackInfo, но можно их добавить, если нужно.
                    # Пока оставляем только то, что есть в TrackInfo
                }

            data[str(chat_id)] = {
                "chat_id": chat_id,
                "query": s.query,
                "started_at": s.started_at,
                "current": current_track_info,
                "playlist_len": len(s.playlist),
                "fails_in_row": s.fails_in_row,
                "last_error": s.last_error,
            }
        logger.debug("Radio status for chat %s: %s", chat_id, data[str(chat_id)])
        return {"sessions": data}

    async def start(self, chat_id: int, query: str) -> None:
        await self.stop(chat_id)

        s = RadioSession(chat_id=chat_id, query=query.strip() or random.choice(self._settings.RADIO_GENRES))
        self._sessions[chat_id] = s
        self._tasks[chat_id] = asyncio.create_task(self._loop(s))
        logger.info("Radio started chat=%s query=%r", chat_id, s.query)

    async def stop(self, chat_id: int) -> None:
        s = self._sessions.get(chat_id)
        t = self._tasks.get(chat_id)
        if s:
            s.stop_event.set()
            s.skip_event.set()
        if t:
            t.cancel()
            try:
                await t
            except Exception:
                pass
        self._sessions.pop(chat_id, None)
        self._tasks.pop(chat_id, None)

    async def stop_all(self) -> None:
        for chat_id in list(self._sessions.keys()):
            await self.stop(chat_id)

    async def skip(self, chat_id: int) -> None:
        s = self._sessions.get(chat_id)
        if s:
            s.skip_event.set()

    async def _refill_playlist(self, s: RadioSession) -> None:
        queries = [
            s.query,
            f"{s.query} music",
            f"best {s.query} mix",
            random.choice(self._settings.RADIO_GENRES),
        ]

        for attempt, q in enumerate(queries, start=1):
            try:
                logger.info("[Radio] search chat=%s q=%r attempt=%s", s.chat_id, q, attempt)
                
                # Используем новый YouTubeDownloader.search
                tracks = await self.youtube_downloader.search(
                    q,
                    limit=self._settings.MAX_RESULTS, # Предполагается, что MAX_RESULTS теперь в Settings
                    min_duration=self._settings.RADIO_MIN_DURATION_S,
                    max_duration=self._settings.RADIO_MAX_DURATION_S,
                    min_views=self._settings.RADIO_MIN_VIEWS,
                    min_likes=self._settings.RADIO_MIN_LIKES,
                    min_like_ratio=self._settings.RADIO_MIN_LIKE_RATIO
                )
                
                if tracks:
                    random.shuffle(tracks)
                    for t in tracks:
                        s.playlist.append(t)
                    s.fails_in_row = 0
                    s.last_error = None
                    logger.info("[Radio] added=%s total=%s chat=%s", len(tracks), len(s.playlist), s.chat_id)
                    return
            except asyncio.TimeoutError:
                s.last_error = "search timeout"
            except Exception as e:
                s.last_error = f"search error: {e}"

            await asyncio.sleep(2 + attempt)

        s.fails_in_row += 1
        logger.warning("[Radio] playlist empty after attempts chat=%s fails=%s", s.chat_id, s.fails_in_row)

        if s.fails_in_row >= self._settings.MAX_RETRIES: # Используем MAX_RETRIES из Settings
            s.query = random.choice(self._settings.RADIO_GENRES)
            s.fails_in_row = 0
            logger.warning("[Radio] auto-change genre chat=%s new_query=%r", s.chat_id, s.query)

    async def _loop(self, s: RadioSession) -> None:
        while not s.stop_event.is_set():
            if not s.playlist:
                await self._refill_playlist(s)
                if not s.playlist:
                    await asyncio.sleep(3)
                    continue

            track_info = s.playlist.popleft() # Теперь это TrackInfo
            s.current = track_info
            s.skip_event.clear()

            try:
                await self.bot.send_message(s.chat_id, f"⏳ Скачиваю: `{track_info.title}`", parse_mode="Markdown")

                # Используем новый YouTubeDownloader.download_with_retry
                download_result = await self.youtube_downloader.download_with_retry(track_info.identifier)

                if not download_result.success:
                    s.last_error = download_result.error
                    logger.warning(f"[Radio] Skip failed track: {track_info.identifier} - {download_result.error}")
                    # Не ждём, сразу берём следующий трек
                    continue

                if not download_result.file_path or not download_result.track_info:
                    s.last_error = download_result.error or "Unknown download error: file_path or track_info missing"
                    logger.warning("[Radio] Download result missing file_path or track_info chat=%s track=%s error=%s", s.chat_id, track_info.identifier, s.last_error)
                    continue


                # отправка файла
                with Path(download_result.file_path).open("rb") as f:
                    await self.bot.send_audio(
                        chat_id=s.chat_id,
                        audio=f,
                        title=download_result.track_info.title[:64],
                        caption=download_result.track_info.display_name, # Используем display_name
                        performer=download_result.track_info.artist,
                        duration=download_result.track_info.duration,
                    )
                
                # После отправки, удаляем файл
                try:
                    file_path = Path(download_result.file_path)
                    file_path.unlink()
                    if file_path.parent != self._settings.DOWNLOADS_DIR: # Если временная папка, удаляем ее
                        file_path.parent.rmdir()
                except Exception as e:
                    logger.warning(f"Ошибка при удалении загруженного файла {download_result.file_path}: {e}")


            except asyncio.TimeoutError:
                s.last_error = "download timeout"
                logger.warning("[Radio] download timeout chat=%s track=%s", s.chat_id, track_info.identifier)
                continue
            except Exception as e:
                s.last_error = f"download/send error: {e}"
                logger.exception("[Radio] error chat=%s", s.chat_id)
                continue

            try:
                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(asyncio.sleep(self._settings.RADIO_COOLDOWN_S)), # Используем RADIO_COOLDOWN_S из Settings
                        asyncio.create_task(s.skip_event.wait()),
                        asyncio.create_task(s.stop_event.wait()),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for p in pending:
                    p.cancel()
            except Exception:
                pass

        logger.info("Radio stopped chat=%s", s.chat_id)
