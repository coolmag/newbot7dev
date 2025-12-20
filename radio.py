from __future__ import annotations
import asyncio
import logging
import random
import time
import os
from collections import deque
from pathlib import Path
from typing import Optional, Set, Dict, Deque, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from telegram import Bot, Message
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest

from config import Settings
from models import TrackInfo
from youtube import YouTubeDownloader
from keyboards import get_dashboard_keyboard, get_track_keyboard
from radio_voting import GenreVotingService # Import the new service

logger = logging.getLogger("radio")

@dataclass
class RadioSession:
    # Core session attributes
    chat_id: int
    query: str
    chat_type: str
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

    def _get_random_style_query(self, s: RadioSession) -> str:
        # Use winning genre if available
        if s.winning_genre:
            base_genre_key = s.winning_genre
        else:
            # Fallback to random if no vote winner
            genres_data = self._settings.GENRE_DATA
            if not genres_data:
                return random.choice(["lofi beats", "pop hits", "rock music"])
            base_genre_key = random.choice(list(genres_data.keys()))

        main_genre = self._settings.GENRE_DATA.get(base_genre_key, {})
        subgenres_data = main_genre.get("subgenres", {})

        if subgenres_data:
            subgenre_key = random.choice(list(subgenres_data.keys()))
            return subgenres_data[subgenre_key].get("search")
        
        return base_genre_key # Fallback to the main key as a search term

    def status(self) -> dict:
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

    async def start(self, chat_id: int, query: str, chat_type: str, message_id: Optional[int] = None, display_name: Optional[str] = None):
        await self.stop(chat_id)
        session = RadioSession(
            chat_id=chat_id, 
            query=query.strip(), 
            chat_type=chat_type,
            display_name=display_name or query.strip()
        )
        self._sessions[chat_id] = session
        
        # Initial mode_end_time will be set by _radio_loop after the first vote.

        if message_id:
            session.dashboard_msg_id = message_id
            await self._update_dashboard(session, status="🔍 Поиск треков...")
        else:
            msg = await self._send_dashboard(session, status="🔍 Поиск треков...")
            if msg: session.dashboard_msg_id = msg.message_id
        
        asyncio.create_task(self._radio_loop(session))
        logger.info(f"[{chat_id}] Радио запущено: {query}")

    async def stop(self, chat_id: int):
        if session := self._sessions.pop(chat_id, None):
            session.stop_event.set()
            if session.preload_task: session.preload_task.cancel()
            
            # End any active voting session for this chat
            await self._voting_service.end_voting_session(chat_id)
            
            paths_to_delete = [session.next_file_path, session.current_file_path]
            for p_str in paths_to_delete:
                if p_str and Path(p_str).exists():
                    try: Path(p_str).unlink()
                    except OSError as e: logger.error(f"Не удалось удалить файл {p_str}: {e}")
            
            await self._update_dashboard(session, status="🛑 Эфир завершен")

    async def stop_all(self):
        for chat_id in list(self._sessions.keys()): await self.stop(chat_id)
        await self._voting_service.stop_all_votings()

    async def skip(self, chat_id: int):
        if session := self._sessions.get(chat_id):
            session.skip_event.set()
            await self._update_dashboard(session, status="⏭️ Переключение...")

    # --- Main Radio Loop ---
    async def _radio_loop(self, s: RadioSession):
        try:
            while not s.stop_event.is_set():
                s.skip_event.clear()

                # Check if it's time for a vote or current genre block has ended
                if s.mode_end_time is None or datetime.now() >= s.mode_end_time:
                    # End any pending vote for this chat, retrieve winner
                    winning_genre_from_vote = await self._voting_service.end_voting(s.chat_id)
                    if winning_genre_from_vote:
                        s.winning_genre = winning_genre_from_vote
                        s.mode_end_time = datetime.now() + timedelta(minutes=60) # Set new 60-minute block
                        s.playlist.clear() # Clear playlist for new genre
                        s.fails_in_row = 0
                        # Update query and display name based on new winning genre
                        s.query = self._settings.GENRE_DATA.get(s.winning_genre, {}).get("name", s.winning_genre)
                        s.display_name = s.query
                        s.skip_event.set() # Skip current track to start the new genre immediately

                    # Start a new vote cycle for the *next* genre (it will replace existing vote message if exists)
                    await self._voting_service.start_new_voting_cycle(s.chat_id, message_id=s.dashboard_msg_id)
                
                if len(s.playlist) < 5:
                    current_query = s.query
                    # If the session is for a random query, get a specific genre query now
                    if current_query == "random":
                        current_query = self._get_random_style_query(s)
                    
                    if not await self._fetch_playlist(s, current_query):
                        s.fails_in_row += 1
                        if s.fails_in_row >= 2:
                            await self._send_error_message(s.chat_id, f"Не могу найти треки по запросу '{current_query}'. Попробую что-нибудь другое...")
                            s.winning_genre = None # Reset winning genre to try something random
                            s.query = "random" # Set back to random to re-trigger random selection
                            s.fails_in_row = 0
                        await asyncio.sleep(5)
                        continue
                    s.fails_in_row = 0
                
                if not s.playlist:
                    await self._send_error_message(s.chat_id, "Плейлист пуст, не могу продолжить.")
                    await asyncio.sleep(10)
                    continue
                
                file_path, track_info = None, None
                if s.next_file_path and Path(s.next_file_path).exists():
                    file_path, track_info, s.next_file_path, s.next_track_info = s.next_file_path, s.next_track_info, None, None
                    s.playlist.popleft()
                else:
                    track = s.playlist.popleft()
                    await self._update_dashboard(s, status=f"⬇️ Загрузка: {track.title[:35]}...")
                    result = await self._downloader.download_with_retry(track.identifier)
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
                    with open(file_path, "rb") as f:
                        await self._bot.send_audio(
                            s.chat_id, f, title=track_info.title, performer=track_info.artist,
                            duration=track_info.duration, caption=f"#{s.display_name.replace(' ', '_')}",
                            reply_markup=get_track_keyboard(self._settings.BASE_URL, s.chat_id)
                        )
                    
                    await asyncio.wait_for(s.skip_event.wait(), timeout=track_info.duration)
                except asyncio.TimeoutError:
                    logger.info(f"[{s.chat_id}] Трек завершился по таймауту.")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"[{s.chat_id}] Ошибка в цикле отправки: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info(f"[{s.chat_id}] Цикл радио отменен.")
        finally:
            logger.info(f"[{s.chat_id}] Завершение сессии.")
            await self.stop(s.chat_id)

    async def _preload_next_track(self, s: RadioSession):
        # ... (no changes needed here) ...
        try:
            if not s.playlist: return
            track = s.playlist[0]
            logger.info(f"[{s.chat_id}] Предзагрузка: {track.title}")
            result = await self._downloader.download_with_retry(track.identifier)
            if result.success:
                s.next_file_path, s.next_track_info = result.file_path, result.track_info
                logger.info(f"[{s.chat_id}] Предзагрузка завершена: {track.title}")
            else:
                logger.warning(f"[{s.chat_id}] Ошибка предзагрузки: {result.error}")
                if s.playlist and s.playlist[0].identifier == track.identifier: s.playlist.popleft()
        except Exception as e:
            logger.error(f"[{s.chat_id}] Критическая ошибка в предзагрузке: {e}", exc_info=True)

    async def _fetch_playlist(self, s: RadioSession, query: str) -> bool:
        # ... (no changes needed here) ...
        tracks = await self._downloader.search(query, limit=self._settings.MAX_RESULTS)
        if tracks:
            new = [t for t in tracks if t.identifier not in s.played_ids]
            s.playlist.extend(new)
            logger.info(f"[{s.chat_id}] Плейлист пополнен на {len(new)} треков.")
            return bool(new)
        return False

    async def _send_error_message(self, chat_id: int, text: str):
        # ... (no changes needed here) ...
        try: await self._bot.send_message(chat_id, text)
        except: pass

    def _build_dashboard_text(self, s: RadioSession, status_override: str = None) -> str:
        # ... (no changes needed here) ...
        if status_override: status = status_override
        elif s.current: status = f"▶️ В эфире: {s.current.title[:35]}..."
        else: status = "⏳ Ожидание..."
        track = s.current.title if s.current else "..."
        artist = s.current.artist if s.current else "..."
        query = s.display_name or s.query
        return f"""
📻 *CYBER RADIO V7*
━━━━━━━━━━━━━━━━━━
💿 *Трек:* `{track}`
👤 *Артист:* `{artist}`
🏷 *Волна:* _{query}_

▓▓▓▓▓░░░░░

ℹ️ _Статус:_ {status}"""

    async def _send_dashboard(self, s: RadioSession, status: str) -> Optional[Message]:
        # ... (no changes needed here) ...
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
        # ... (no changes needed here) ...
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
