from __future__ import annotations

import asyncio
import logging
import random
import os
from datetime import datetime, timedelta
from typing import Optional, Set, Dict, Deque, List, Callable
from collections import deque
from pathlib import Path
from dataclasses import dataclass, field

from telegram import Bot, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config import Settings
from models import DownloadResult, TrackInfo
from youtube import YouTubeDownloader

logger = logging.getLogger("radio")

@dataclass
class RadioSession:
    chat_id: int
    query: str
    started_at: float = field(default_factory=lambda: time.time())
    current: Optional[TrackInfo] = None
    playlist: Deque[TrackInfo] = field(default_factory=deque)
    played_ids: Set[str] = field(default_factory=set)
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    skip_event: asyncio.Event = field(default_factory=asyncio.Event)
    fails_in_row: int = 0
    last_error: Optional[str] = None
    audio_file_path: Optional[Path] = None

class RadioManager:
    """
    Управляет радио-сессиями для разных чатов.
    """
    def __init__(self, bot: Bot, settings: Settings, downloader: YouTubeDownloader):
        self._bot = bot
        self._settings = settings
        self._downloader = downloader
        self._sessions: Dict[int, RadioSession] = {}
        self._tasks: Dict[int, asyncio.Task] = {}

    def _parse_error(self, error: Exception) -> str:
        msg = str(error).lower()
        if "private" in msg: return "Видео приватное"
        if "unavailable" in msg: return "Видео недоступно"
        if "age" in msg: return "Требуется возраст 18+"
        if "copyright" in msg: return "Заблокировано по авторским правам"
        if "read operation timed out" in msg: return "Таймаут скачивания"
        return str(error)[:100]

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
                }
                if s.audio_file_path and s.audio_file_path.exists() and s.current.identifier:
                    audio_url = f"{self._settings.BASE_URL}/audio/{s.current.identifier}"
                    current_track_info["audio_url"] = audio_url

            data[str(chat_id)] = {
                "chat_id": chat_id,
                "query": s.query,
                "started_at": s.started_at,
                "current": current_track_info,
                "playlist_len": len(s.playlist),
                "fails_in_row": s.fails_in_row,
                "last_error": s.last_error,
            }
        return {"sessions": data}

    async def start(self, chat_id: int, query: str):
        await self.stop(chat_id)
        session = RadioSession(chat_id=chat_id, query=query.strip() or random.choice(self._settings.RADIO_GENRES))
        self._sessions[chat_id] = session
        self._tasks[chat_id] = asyncio.create_task(self._radio_loop(session))
        logger.info(f"[{chat_id}] Radio task created for query: '{query}'")

    async def stop(self, chat_id: int):
        if task := self._tasks.pop(chat_id, None):
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        
        if session := self._sessions.pop(chat_id, None):
            if session.audio_file_path and session.audio_file_path.exists():
                try: session.audio_file_path.unlink()
                except OSError as e: logger.warning(f"[{chat_id}] Error deleting audio file on stop: {e}")
        logger.info(f"[{chat_id}] Radio stopped.")

    async def stop_all(self):
        await asyncio.gather(*(self.stop(chat_id) for chat_id in list(self._sessions.keys())))

    async def skip(self, chat_id: int):
        if session := self._sessions.get(chat_id):
            session.skip_event.set()

    async def _fetch_playlist(self, session: RadioSession) -> bool:
        query = random.choice([session.query, f"{session.query} music", f"best {session.query} mix"])
        logger.info(f"[{session.chat_id}] Fetching new tracks for query: '{query}'")
        
        new_tracks = await self._downloader.search(
            query,
            limit=50,
            min_duration=self._settings.RADIO_MIN_DURATION_S,
            max_duration=self._settings.RADIO_MAX_DURATION_S,
        )

        if new_tracks:
            unique_tracks = [t for t in new_tracks if t.identifier not in session.played_ids]
            random.shuffle(unique_tracks)
            session.playlist.extend(unique_tracks)
            logger.info(f"[{session.chat_id}] Added {len(unique_tracks)} new unique tracks. Total: {len(session.playlist)}")
            return True
        return False

    async def _radio_loop(self, s: RadioSession):
        while not s.stop_event.is_set():
            try:
                if len(s.playlist) < 5:
                    if not await self._fetch_playlist(s):
                        s.fails_in_row += 1
                        if s.fails_in_row >= 3:
                            s.query = random.choice(self._settings.RADIO_GENRES)
                            s.fails_in_row = 0
                            logger.warning(f"[{s.chat_id}] Failed to find tracks 3 times. Switching to: {s.query}")
                            await self._bot.send_message(s.chat_id, f"😕 Не могу найти музыку по запросу. Переключаю на: **{s.query}**", parse_mode=ParseMode.MARKDOWN)
                        await asyncio.sleep(5)
                        continue
                    s.fails_in_row = 0
                
                if not s.playlist:
                    await asyncio.sleep(self._settings.RETRY_DELAY_S)
                    continue

                track_to_play = s.playlist.popleft()
                s.current = track_to_play
                s.skip_event.clear()

                if s.audio_file_path and s.audio_file_path.exists(): s.audio_file_path.unlink()

                download_msg = await self._bot.send_message(s.chat_id, f"⏳ Скачиваю: `{track_to_play.title}`", parse_mode=ParseMode.MARKDOWN)
                
                result = await self._downloader.download_with_retry(track_to_play.identifier)

                if not result.success:
                    s.last_error = self._parse_error(Exception(result.error))
                    logger.warning(f"[{s.chat_id}] Skipping failed track: {track_to_play.identifier} - {s.last_error}")
                    await download_msg.edit_text(f"⚠️ Ошибка: {s.last_error}. Пропускаю...")
                    continue
                
                s.audio_file_path = Path(result.file_path)
                s.played_ids.add(track_to_play.identifier)
                if len(s.played_ids) > 500: s.played_ids.discard(next(iter(s.played_ids), None))

                try:
                    with s.audio_file_path.open("rb") as f:
                        await self._bot.send_audio(
                            chat_id=s.chat_id, audio=f, title=result.track_info.title,
                            performer=result.track_info.artist, duration=result.track_info.duration,
                            caption=f"📻 {s.query}"
                        )
                    await download_msg.delete()
                except TelegramError as e:
                    logger.error(f"[{s.chat_id}] Telegram error sending audio: {e}")
                    s.last_error = "Ошибка отправки"
                    continue

                try:
                    await asyncio.wait_for(s.skip_event.wait(), timeout=float(s.current.duration + 10))
                except asyncio.TimeoutError:
                    pass
                finally:
                    s.skip_event.clear()

            except asyncio.CancelledError:
                logger.info(f"[{s.chat_id}] Radio loop cancelled.")
                break
            except Exception:
                logger.exception(f"[{s.chat_id}] Unhandled error in radio loop.")
                s.fails_in_row += 1
                await asyncio.sleep(5)
        
        logger.info(f"[{s.chat_id}] Radio loop finished.")