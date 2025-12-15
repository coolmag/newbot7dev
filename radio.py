from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from pathlib import Path
from typing import Optional, Set, Dict, Deque
from dataclasses import dataclass, field

from telegram import Bot, Message
from telegram.constants import ParseMode
from telegram.error import BadRequest

from config import Settings
from models import TrackInfo
from youtube import YouTubeDownloader
from keyboards import get_dashboard_keyboard, get_track_keyboard

logger = logging.getLogger("radio")

@dataclass
class RadioSession:
    chat_id: int
    query: str
    chat_type: str
    started_at: float = field(default_factory=time.time)
    current: Optional[TrackInfo] = None
    playlist: Deque[TrackInfo] = field(default_factory=deque)
    played_ids: Set[str] = field(default_factory=set)
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    skip_event: asyncio.Event = field(default_factory=asyncio.Event)
    fails_in_row: int = 0
    audio_file_path: Optional[Path] = None
    dashboard_msg_id: Optional[int] = None

class RadioManager:
    def __init__(self, bot: Bot, settings: Settings, downloader: YouTubeDownloader):
        self._bot = bot
        self._settings = settings
        self._downloader = downloader
        self._sessions: Dict[int, RadioSession] = {}
        self._tasks: Dict[int, asyncio.Task] = {}

    async def start(self, chat_id: int, query: str, chat_type: str = "private"):
        await self.stop(chat_id)
        session = RadioSession(chat_id=chat_id, query=query.strip(), chat_type=chat_type)
        self._sessions[chat_id] = session
        msg = await self._send_dashboard(session, status="🔍 Поиск треков...")
        if msg:
            session.dashboard_msg_id = msg.message_id
        self._tasks[chat_id] = asyncio.create_task(self._radio_loop(session))

    async def stop(self, chat_id: int):
        if task := self._tasks.pop(chat_id, None):
            task.cancel()
        if session := self._sessions.pop(chat_id, None):
            session.stop_event.set()
            await self._update_dashboard(session, status="🛑 Эфир завершен")

    async def skip(self, chat_id: int):
        if session := self._sessions.get(chat_id):
            session.skip_event.set()

    async def _radio_loop(self, s: RadioSession):
        """Профессиональный цикл: новый трек каждые 90 секунд."""
        try:
            while not s.stop_event.is_set():
                s.skip_event.clear()

                if len(s.playlist) < 2:
                    await self._fetch_playlist(s)

                if not s.playlist:
                    await asyncio.sleep(5)
                    continue

                track = s.playlist.popleft()
                s.current = track
                s.played_ids.add(track.identifier)
                
                await self._update_dashboard(s, status=f"⬇️ Загрузка...")

                # Скачивание с таймаутом
                try:
                    result = await asyncio.wait_for(
                        self._downloader.download_with_retry(track.identifier),
                        timeout=45.0
                    )
                except asyncio.TimeoutError:
                    continue

                if not result or not result.success:
                    continue

                s.audio_file_path = Path(result.file_path)

                # Отправка аудио
                try:
                    with open(s.audio_file_path, 'rb') as f:
                        await self._bot.send_audio(
                            chat_id=s.chat_id,
                            audio=f,
                            caption=f"🎧 *{track.title}*\n👤 {track.artist}",
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=get_track_keyboard(track.identifier)
                        )
                    await self._update_dashboard(s, status="▶️ В эфире")
                except Exception as e:
                    logger.error(f"Send error: {e}")

                # ОЖИДАНИЕ 90 СЕКУНД ДО СЛЕДУЮЩЕГО ТРЕКА
                try:
                    await asyncio.wait_for(s.skip_event.wait(), timeout=90.0)
                except asyncio.TimeoutError:
                    pass # Время вышло, идем дальше

                if s.audio_file_path and s.audio_file_path.exists():
                    try: s.audio_file_path.unlink()
                    except: pass

        except asyncio.CancelledError:
            pass
        finally:
            await self.stop(s.chat_id)

    async def _fetch_playlist(self, s: RadioSession) -> bool:
        tracks = await self._downloader.search(s.query, limit=10)
        if tracks:
            new_tracks = [t for t in tracks if t.identifier not in s.played_ids]
            s.playlist.extend(new_tracks)
            return True
        return False

    async def _send_dashboard(self, s: RadioSession, status: str) -> Optional[Message]:
        text = self._build_dashboard_text(s, status)
        try:
            return await self._bot.send_message(
                chat_id=s.chat_id, text=text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_dashboard_keyboard(self._settings.BASE_URL, s.chat_type, s.chat_id)
            )
        except: return None

    async def _update_dashboard(self, s: RadioSession, status: str = None):
        if not s.dashboard_msg_id: return
        text = self._build_dashboard_text(s, status)
        try:
            await self._bot.edit_message_text(
                chat_id=s.chat_id, message_id=s.dashboard_msg_id,
                text=text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_dashboard_keyboard(self._settings.BASE_URL, s.chat_type, s.chat_id)
            )
        except: pass

    def _build_dashboard_text(self, s: RadioSession, status_override: str = None) -> str:
        status = status_override or (f"▶️ Играет: {s.current.artist}" if s.current else "⏳ Ожидание...")
        track_name = (s.current.title if s.current else "...").replace("*", "")
        return f"📻 *CYBER RADIO V7*\n━━━━━━━━━━━━━━━━━━\n💿 *Трек:* `{track_name}`\n🏷 *Волна:* _{s.query}_\n\nℹ️ _Статус:_ {status}"
