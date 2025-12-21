from __future__ import annotations
import asyncio
import logging
import random
import time
import os
from collections import deque
from pathlib import Path
from typing import Optional, Set, Dict, Deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from telegram import Bot, Message
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest

from config import Settings
from models import TrackInfo
from youtube import YouTubeDownloader, SearchMode # Import SearchMode
from keyboards import get_dashboard_keyboard
from radio_voting import GenreVotingService

logger = logging.getLogger("radio")

@dataclass
class RadioSession:
    # Core session attributes
    chat_id: int
    query: str
    chat_type: str
    search_mode: SearchMode # Explicitly define the search mode
    display_name: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    
    # Playlist management
    current: Optional[TrackInfo] = None
    current_file_path: Optional[Path] = None
    playlist: Deque[TrackInfo] = field(default_factory=deque)
    played_ids: Set[str] = field(default_factory=set)
    
    # Async control
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    skip_event: asyncio.Event = field(default_factory=asyncio.Event)
    preload_task: Optional[asyncio.Task] = None
    
    # Preloading state
    next_file_path: Optional[str] = None
    next_track_info: Optional[TrackInfo] = None
    
    # Status & UI
    fails_in_row: int = 0
    dashboard_msg_id: Optional[int] = None
    
    # --- Mode attributes ---
    mode_end_time: Optional[datetime] = None
    winning_genre: Optional[str] = None


class RadioManager:
    def __init__(self, bot: Bot, settings: Settings, downloader: YouTubeDownloader, voting_service: GenreVotingService):
        self._bot = bot
        self._settings = settings
        self._downloader = downloader
        self._voting_service = voting_service
        self._sessions: Dict[int, RadioSession] = {}

    def _get_random_style_query(self) -> tuple[str, str]:
        """Returns a random genre search query and its display name."""
        genres_data = self._settings.GENRE_DATA
        if not genres_data:
            return "lofi beats", "Lo-Fi"
            
        base_genre_key = random.choice(list(genres_data.keys()))
        main_genre = genres_data.get(base_genre_key, {})
        display_name = main_genre.get("name", base_genre_key)
        
        subgenres_data = main_genre.get("subgenres", {})
        if subgenres_data:
            subgenre_key = random.choice(list(subgenres_data.keys()))
            search_query = subgenres_data[subgenre_key].get("search", subgenre_key)
            display_name = subgenres_data[subgenre_key].get("name", display_name)
            return search_query, display_name
        
        return base_genre_key, display_name

    def status(self) -> dict:
        # (No changes needed in this method)
        data = {}
        for chat_id, s in self._sessions.items():
            current_info = None
            if s.current:
                current_info = {
                    "title": s.current.title,
                    "artist": s.current.artist,
                    "duration": s.current.duration,
                    "identifier": s.current.identifier,
                    "audio_url": f"{self._settings.BASE_URL}/audio/{s.current.identifier}",
                }
            
            voting_session = self._voting_service.get_session(chat_id)
            is_vote_in_progress = voting_session.is_vote_in_progress if voting_session else False

            data[str(chat_id)] = {
                "chat_id": chat_id, "query": s.query, "current": current_info,
                "playlist_len": len(s.playlist), "is_active": not s.stop_event.is_set(),
                "winning_genre": s.winning_genre,
                "is_vote_in_progress": is_vote_in_progress
            }
        return {"sessions": data}

    async def start(self, chat_id: int, query: str, chat_type: str, search_mode: SearchMode, message_id: Optional[int] = None, display_name: Optional[str] = None):
        await self.stop(chat_id)
        
        # If starting in random genre mode, get an initial query right away.
        if query == "random" and search_mode == "genre":
            actual_query, actual_display_name = self._get_random_style_query()
        else:
            actual_query, actual_display_name = query.strip(), display_name or query.strip()
            
        session = RadioSession(
            chat_id=chat_id, 
            query=actual_query,
            chat_type=chat_type,
            search_mode=search_mode,
            display_name=actual_display_name
        )
        self._sessions[chat_id] = session

        if message_id:
            session.dashboard_msg_id = message_id
            await self._update_dashboard(session, status="🔍 Поиск треков...")
        else:
            msg = await self._send_dashboard(session, status="🔍 Поиск треков...")
            if msg: session.dashboard_msg_id = msg.message_id
        
        asyncio.create_task(self._radio_loop(session))
        logger.info(f"[{chat_id}] Радио запущено: '{session.query}' (режим: {session.search_mode})")

    async def stop(self, chat_id: int):
        if session := self._sessions.pop(chat_id, None):
            session.stop_event.set()
            if session.preload_task: session.preload_task.cancel()
            await self._voting_service.end_voting_session(chat_id)
            
            paths_to_delete = [session.next_file_path, session.current_file_path]
            for p_str in paths_to_delete:
                if p_str and Path(p_str).exists():
                    try: Path(p_str).unlink(missing_ok=True)
                    except OSError as e: logger.error(f"Не удалось удалить файл {p_str}: {e}")
            
            await self._update_dashboard(session, status="🛑 Эфир завершен")

    async def stop_all(self):
        for chat_id in list(self._sessions.keys()): await self.stop(chat_id)
        await self._voting_service.stop_all_votings()

    async def skip(self, chat_id: int):
        if session := self._sessions.get(chat_id):
            session.skip_event.set()
            await self._update_dashboard(session, status="⏭️ Переключение...")

    # --- Main Radio Loop (Refactored) ---
    async def _radio_loop(self, s: RadioSession):
        try:
            while not s.stop_event.is_set():
                s.skip_event.clear()

                # --- Voting and Genre Change Logic ---
                if s.mode_end_time is None or datetime.now() >= s.mode_end_time:
                    winning_genre_key = await self._voting_service.end_voting(s.chat_id)
                    if winning_genre_key:
                        s.winning_genre = winning_genre_key
                        s.mode_end_time = datetime.now() + timedelta(minutes=60)
                        
                        # Set the session to the new winning genre
                        genre_info = self._settings.GENRE_DATA.get(s.winning_genre, {})
                        s.query = genre_info.get("name", s.winning_genre)
                        s.display_name = s.query
                        s.search_mode = 'genre' # Ensure mode is genre
                        
                        # Clear state for the new genre
                        s.playlist.clear()
                        s.played_ids.clear()
                        s.fails_in_row = 0
                        s.skip_event.set() # Immediately skip to start the new genre

                    await self._voting_service.start_new_voting_cycle(s.chat_id, message_id=s.dashboard_msg_id)
                
                # --- Playlist Fetching Logic ---
                if len(s.playlist) < 5:
                    if not await self._fetch_playlist(s):
                        s.fails_in_row += 1
                        # If fetching fails consistently for a specific query, stop the radio.
                        if s.fails_in_row >= 3:
                            logger.warning(f"[{s.chat_id}] Не удалось найти треки для '{s.query}' 3 раза подряд. Остановка радио.")
                            await self._send_error_message(s.chat_id, f"❌ Не могу найти треки по запросу «{s.display_name}». Эфир остановлен.")
                            # The loop will terminate as we call stop() in the finally block.
                            break
                        
                        await asyncio.sleep(5) # Wait before retrying
                        continue 
                    s.fails_in_row = 0 # Reset counter on success
                
                if not s.playlist:
                    logger.warning(f"[{s.chat_id}] Плейлист пуст после попытки пополнения.")
                    await asyncio.sleep(10)
                    continue
                
                # --- Download and Play Logic ---
                file_path, track_info = None, None
                if s.next_file_path and Path(s.next_file_path).exists():
                    file_path, track_info, s.next_file_path, s.next_track_info = s.next_file_path, s.next_track_info, None, None
                    s.playlist.popleft()
                else:
                    track = s.playlist.popleft()
                    await self._update_dashboard(s, status=f"⬇️ Загрузка: {track.title[:35]}...")
                    result = await self._downloader.download(track.identifier)
                    if not result.success:
                        logger.warning(f"[{s.chat_id}] Ошибка скачивания: {result.error}")
                        continue
                    file_path, track_info = result.file_path, result.track_info

                s.current, s.current_file_path = track_info, Path(file_path)
                s.played_ids.add(track_info.identifier)

                if s.preload_task: s.preload_task.cancel()
                s.preload_task = asyncio.create_task(self._preload_next_track(s))

                await self._update_dashboard(s, status="▶️ В эфире")
                try:
                    caption = f"#{s.display_name.replace(' ', '_').replace(':', '')}"
                    with open(file_path, "rb") as f:
                        await self._bot.send_audio(
                            s.chat_id, f, title=track_info.title, performer=track_info.artist,
                            duration=track_info.duration, caption=caption,
                        )
                    await asyncio.wait_for(s.skip_event.wait(), timeout=track_info.duration)
                except asyncio.TimeoutError:
                    pass # Normal track end
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"[{s.chat_id}] Ошибка в цикле отправки: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info(f"[{s.chat_id}] Цикл радио отменен.")
        finally:
            logger.info(f"[{s.chat_id}] Завершение сессии.")
            await self.stop(s.chat_id) # Ensure session is always cleaned up

    async def _preload_next_track(self, s: RadioSession):
        try:
            if not s.playlist: return
            track = s.playlist[0]
            result = await self._downloader.download(track.identifier)
            if result.success:
                s.next_file_path, s.next_track_info = result.file_path, result.track_info
            else:
                logger.warning(f"[{s.chat_id}] Ошибка предзагрузки: {result.error}")
                if s.playlist and s.playlist[0].identifier == track.identifier: s.playlist.popleft()
        except Exception as e:
            logger.error(f"[{s.chat_id}] Критическая ошибка в предзагрузке: {e}", exc_info=True)

    async def _fetch_playlist(self, s: RadioSession) -> bool:
        tracks = await self._downloader.search(s.query, search_mode=s.search_mode, limit=self._settings.MAX_RESULTS)
        if tracks:
            new = [t for t in tracks if t.identifier not in s.played_ids]
            s.playlist.extend(new)
            logger.info(f"[{s.chat_id}] Плейлист пополнен на {len(new)} треков.")
            # Reset played IDs if the playlist gets too repetitive, allowing old tracks to be re-added
            if len(s.played_ids) > 200:
                s.played_ids.clear()
            return bool(new)
        return False

    async def _send_error_message(self, chat_id: int, text: str):
        try: await self._bot.send_message(chat_id, text)
        except: pass

    def _build_dashboard_text(self, s: RadioSession, status_override: str = None) -> str:
        # (No changes needed)
        status = status_override or f"▶️ В эфире"
        track = s.current.title if s.current else "..."
        artist = s.current.artist if s.current else "..."
        query = s.display_name or s.query
        return f"""📻 *CYBER RADIO V7*
━━━━━━━━━━━━━━━━━━
💿 *Трек:* `{track}`
👤 *Артист:* `{artist}`
🏷 *Волна:* _{query}_

▓▓▓▓▓░░░░░

ℹ️ _Статус:_ {status}"""

    async def _send_dashboard(self, s: RadioSession, status: str) -> Optional[Message]:
        text = self._build_dashboard_text(s, status)
        try:
            return await self._bot.send_message(
                chat_id=s.chat_id, text=text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_dashboard_keyboard(self._settings.BASE_URL, s.chat_type, s.chat_id)
            )
        except Exception as e:
            logger.error(f"Не удалось отправить панель: {e}")
            return None

    async def _update_dashboard(self, s: RadioSession, status: str = None):
        if not s.dashboard_msg_id: return
        text = self._build_dashboard_text(s, status)
        try:
            await self._bot.edit_message_text(
                chat_id=s.chat_id, message_id=s.dashboard_msg_id, text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_dashboard_keyboard(self._settings.BASE_URL, s.chat_type, s.chat_id)
            )
        except BadRequest:
            s.dashboard_msg_id = None
        except Exception as e:
            logger.warning(f"Не удалось обновить панель: {e}")