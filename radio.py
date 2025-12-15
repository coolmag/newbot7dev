from __future__ import annotations

import asyncio
import logging
import random
import time
import mimetypes
from collections import deque
from pathlib import Path
from typing import Optional, Set, Dict, Deque
from dataclasses import dataclass, field

from telegram import Bot, Message
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest

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
    last_error: Optional[str] = None
    audio_file_path: Optional[Path] = None
    
    dashboard_msg_id: Optional[int] = None

class RadioManager:
    def __init__(self, bot: Bot, settings: Settings, downloader: YouTubeDownloader):
        self._bot = bot
        self._settings = settings
        self._downloader = downloader
        self._sessions: Dict[int, RadioSession] = {}
        self._tasks: Dict[int, asyncio.Task] = {}

    def status(self) -> dict:
        data = {}
        for chat_id, s in self._sessions.items():
            current_info = None
            if s.current:
                mime = "audio/mpeg"
                if s.audio_file_path:
                    ext = s.audio_file_path.suffix.lower()
                    if ext in (".m4a", ".mp4"): mime = "audio/mp4"
                    elif ext in (".webm"): mime = "audio/webm"

                current_info = {
                    "title": s.current.title,
                    "artist": s.current.artist,
                    "duration": s.current.duration,
                    "identifier": s.current.identifier,
                    "audio_url": f"{self._settings.BASE_URL}/audio/{s.current.identifier}",
                    "audio_mime": mime
                }
            
            data[str(chat_id)] = {
                "chat_id": chat_id,
                "query": s.query,
                "current": current_info,
                "playlist_len": len(s.playlist),
                "is_active": not s.stop_event.is_set()
            }
        return {"sessions": data}

    async def start(self, chat_id: int, query: str, chat_type: str = "private"):
        await self.stop(chat_id)
        
        session = RadioSession(chat_id=chat_id, query=query.strip(), chat_type=chat_type)
        self._sessions[chat_id] = session
        
        msg = await self._send_dashboard(session, status="🔍 Поиск треков...")
        if msg:
            session.dashboard_msg_id = msg.message_id
        
        self._tasks[chat_id] = asyncio.create_task(self._radio_loop(session))
        logger.info(f"[{chat_id}] Started radio: {query}")

    async def stop(self, chat_id: int):
        if task := self._tasks.pop(chat_id, None):
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        
        if session := self._sessions.pop(chat_id, None):
            session.stop_event.set()
            if session.audio_file_path and session.audio_file_path.exists():
                try: session.audio_file_path.unlink()
                except: pass
            
            await self._update_dashboard(session, status="🛑 Эфир завершен")
            
    async def stop_all(self):
        for chat_id in list(self._sessions.keys()):
            await self.stop(chat_id)

    async def skip(self, chat_id: int):
        if session := self._sessions.get(chat_id):
            session.skip_event.set()
            await self._update_dashboard(session, status="⏭️ Переключение...")

    async def _send_dashboard(self, s: RadioSession, status: str) -> Optional[Message]:
        text = self._build_dashboard_text(s, status)
        try:
            return await self._bot.send_message(
                chat_id=s.chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_dashboard_keyboard(self._settings.BASE_URL, s.chat_type, s.chat_id)
            )
        except Exception as e:
            logger.error(f"[{s.chat_id}] Failed to send dashboard: {e}")
            return None

    async def _update_dashboard(self, s: RadioSession, status: str = None):
        if not s.dashboard_msg_id:
            return
        
        text = self._build_dashboard_text(s, status)
        try:
            await self._bot.edit_message_text(
                chat_id=s.chat_id,
                message_id=s.dashboard_msg_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_dashboard_keyboard(self._settings.BASE_URL, s.chat_type, s.chat_id)
            )
        except BadRequest as e:
            if "message is not modified" not in str(e):
                logger.warning(f"Dashboard update failed: {e}")
                if "message to edit not found" in str(e) and not s.stop_event.is_set():
                    msg = await self._send_dashboard(s, status or "Восстановление...")
                    if msg:
                        s.dashboard_msg_id = msg.message_id
        except Exception as e:
            logger.warning(f"Dashboard error: {e}")

    def _build_dashboard_text(self, s: RadioSession, status_override: str = None) -> str:
        if status_override:
            status = status_override
        elif s.current:
            status = f"▶️ Играет: {s.current.artist}"
        else:
            status = "⏳ Ожидание..."

        track_name = s.current.title if s.current else "..."
        artist_name = s.current.artist if s.current else "Загрузка"
        progress = "▓▓▓▓▓░░░░░" 

        track_name = track_name.replace("*", "").replace("_", "").replace("`", "")
        artist_name = artist_name.replace("*", "").replace("_", "").replace("`", "")
        query_safe = s.query.replace("*", "").replace("_", "").replace("`", "")

        return f"""📻 *CYBER RADIO V7*
━━━━━━━━━━━━━━━━━━
💿 *Трек:* `{track_name}`
👤 *Артист:* `{artist_name}`
🏷 *Волна:* _{query_safe}_

{progress}

ℹ️ _Статус:_ {status}
"""

    async def _fetch_playlist(self, s: RadioSession) -> bool:
        q_variants = [s.query, f"{s.query} music", f"best {s.query}"]
        actual_query = random.choice(q_variants)
        
        logger.info(f"[{s.chat_id}] Searching tracks: {actual_query}")
        tracks = await self._downloader.search(
            actual_query, 
            limit=self._settings.MAX_RESULTS
        )
        
        if tracks:
            new_tracks = [t for t in tracks if t.identifier not in s.played_ids]
            random.shuffle(new_tracks)
            s.playlist.extend(new_tracks)
            logger.info(f"[{s.chat_id}] Found {len(new_tracks)} new tracks")
            return True
        return False

    async def _radio_loop(self, s: RadioSession):
        try:
            while not s.stop_event.is_set():
                s.skip_event.clear()

                if len(s.playlist) < 3:
                    await self._update_dashboard(s, status="📡 Поиск частот...")
                    if not await self._fetch_playlist(s):
                        s.fails_in_row += 1
                        if s.fails_in_row >= 3:
                            s.query = random.choice(self._settings.RADIO_GENRES)
                            s.fails_in_row = 0
                            logger.warning(f"[{s.chat_id}] Search failed, switching to {s.query}")
                        await asyncio.sleep(5)
                        continue
                    s.fails_in_row = 0

                if not s.playlist:
                    await asyncio.sleep(5)
                    continue

                track = s.playlist.popleft()
                s.current = track
                
                await self._update_dashboard(s, status=f"⬇️ Загрузка: {track.title}...")
                
                if s.audio_file_path and s.audio_file_path.exists():
                    try: s.audio_file_path.unlink()
                    except: pass
                
                result = await self._downloader.download_with_retry(track.identifier)
                
                if not result.success:
                    logger.warning(f"Download failed: {result.error}")
                    if result.error and ("большой" in str(result.error) or "too large" in str(result.error)):
                         await self._update_dashboard(s, status="⚠️ Слишком большой файл, пропуск...")
                    else:
                         await self._update_dashboard(s, status=f"⚠️ Ошибка: {result.error}")
                    await asyncio.sleep(1)
                    continue 
                
                s.audio_file_path = Path(result.file_path)
                s.played_ids.add(track.identifier)
                
                if len(s.played_ids) > 300:
                    s.played_ids = set(list(s.played_ids)[-100:])

                await self._update_dashboard(s, status="▶️ Pre-buffering...")
                
                try:
                    with open(s.audio_file_path, "rb") as f:
                        await self._bot.send_audio(
                            chat_id=s.chat_id,
                            audio=f,
                            title=track.title,
                            performer=track.artist,
                            duration=track.duration,
                            caption=f"#{s.query.replace(' ', '_')}",
                            reply_markup=get_track_keyboard(self._settings.BASE_URL, s.chat_id)
                        )
                    
                    await self._update_dashboard(s)
                    
                    wait_time = float(track.duration) if track.duration > 0 else 180.0
                    try:
                        await asyncio.wait_for(s.skip_event.wait(), timeout=wait_time)
                    except asyncio.TimeoutError:
                        pass
                        
                except Exception as e:
                    logger.error(f"Playback error: {e}")
                    await asyncio.sleep(5)

        except asyncio.CancelledError:
            logger.info(f"[{s.chat_id}] Loop cancelled")
        except Exception as e:
            logger.exception("Critical radio loop error")
        finally:
            logger.info(f"[{s.chat_id}] Loop finished")