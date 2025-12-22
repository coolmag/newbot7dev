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
from models import TrackInfo, StreamInfo, StreamInfoResult
from youtube import YouTubeDownloader, SearchMode # Import SearchMode
from keyboards import get_dashboard_keyboard, get_track_keyboard
from radio_voting import GenreVotingService

logger = logging.getLogger("radio")

class PlayerAnimator:
    """Creates a textual animation for the player."""
    def __init__(self):
        self._frames = [
            "☀️ 💿",
            "☀️ . 💿",
            "☀️ . . 💿",
            "☀️ . . . 💿",
            "💿 . . . ☀️",
            "💿 . . ☀️",
            "💿 . ☀️",
            "💿 ☀️"
        ]
        self._current_frame = 0

    def get_next_frame(self) -> str:
        frame = self._frames[self._current_frame]
        self._current_frame = (self._current_frame + 1) % len(self._frames)
        return frame

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
    playlist: Deque[TrackInfo] = field(default_factory=deque)
    played_ids: Set[str] = field(default_factory=set)
    current_stream_info: Optional[StreamInfo] = None # Replaces current_url and current
    
    # Async control
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    skip_event: asyncio.Event = field(default_factory=asyncio.Event)
    preload_task: Optional[asyncio.Task] = None
    
    # Preloading state
    preloaded_stream_info: Optional[StreamInfo] = None # Replaces next_url and next_track_info
    
    # Status & UI
    fails_in_row: int = 0
    dashboard_msg_id: Optional[int] = None
    animator: PlayerAnimator = field(default_factory=PlayerAnimator)
    animation_task: Optional[asyncio.Task] = None
    
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
        self._session_tasks: Dict[int, asyncio.Task] = {}
        self._locks: Dict[int, asyncio.Lock] = {}

    def _get_lock(self, chat_id: int) -> asyncio.Lock:
        """Returns a lock for a given chat_id, creating one if it doesn't exist."""
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

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
            if s.current_stream_info and s.current_stream_info.track_info:
                track = s.current_stream_info.track_info
                current_info = {
                    "title": track.title,
                    "artist": track.artist,
                    "duration": track.duration,
                    "identifier": track.identifier,
                    "audio_url": f"{self._settings.BASE_URL}/stream/{track.identifier}",
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
        lock = self._get_lock(chat_id)
        async with lock:
            # Stop any existing session for this chat before starting a new one.
            await self._stop_internal(chat_id)
            
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

            if search_mode == 'artist':
                session.mode_end_time = datetime.now() + timedelta(hours=24)
            else: # For 'genre' mode
                session.mode_end_time = datetime.now() + timedelta(minutes=60)
                
            self._sessions[chat_id] = session

            task = asyncio.create_task(self._radio_loop(session))
            self._session_tasks[chat_id] = task
            logger.info(f"[{chat_id}] Радио запущено: '{session.query}' (режим: {session.search_mode})")

    async def _stop_internal(self, chat_id: int):
        """Internal stop method that doesn't acquire a lock, assuming it's already held."""
        if task := self._session_tasks.pop(chat_id, None):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass # This is expected.
        
        if session := self._sessions.pop(chat_id, None):
            # The loop's finally block will call this method again, but the session will be gone.
            # We perform cleanup here to be sure.
            session.stop_event.set() # Ensure event is set for any checks.
            if session.preload_task and not session.preload_task.done(): session.preload_task.cancel()
            if session.animation_task and not session.animation_task.done(): session.animation_task.cancel()
            await self._voting_service.end_voting_session(chat_id)
            
            # Local file cleanup is no longer needed in S3 architecture
            
            await self._update_player_message(session, status_override="🛑 Эфир завершен")
            logger.info(f"[{chat_id}] Сессия радио принудительно остановлена.")

    async def stop(self, chat_id: int):
        """Public stop method that acquires a lock."""
        lock = self._get_lock(chat_id)
        async with lock:
            await self._stop_internal(chat_id)

    async def stop_all(self):
        # Create a list of chat_ids to avoid issues with changing dict size during iteration
        all_chat_ids = list(self._sessions.keys())
        for chat_id in all_chat_ids:
            await self.stop(chat_id)
        await self._voting_service.stop_all_votings()

    async def skip(self, chat_id: int):
        if session := self._sessions.get(chat_id):
            session.skip_event.set()
            await self._update_player_message(session, status_override="⏭️ Переключение...")

    # --- Main Radio Loop (Refactored) ---
    async def _radio_loop(self, s: RadioSession):
        try:
            if s.dashboard_msg_id:
                try:
                    await self._bot.delete_message(s.chat_id, s.dashboard_msg_id)
                    s.dashboard_msg_id = None
                except (TelegramError, BadRequest):
                    pass

            while not s.stop_event.is_set():
                s.skip_event.clear()

                if s.search_mode == 'genre' and datetime.now() >= s.mode_end_time:
                    winning_genre_key = await self._voting_service.end_voting(s.chat_id)
                    if winning_genre_key:
                        s.winning_genre = winning_genre_key
                        s.mode_end_time = datetime.now() + timedelta(minutes=60)
                        genre_info = self._settings.GENRE_DATA.get(s.winning_genre, {})
                        s.query = genre_info.get("name", s.winning_genre)
                        s.display_name = s.query
                        s.playlist.clear()
                        s.played_ids.clear()
                        s.fails_in_row = 0
                        s.skip_event.set()
                    await self._voting_service.start_new_voting_cycle(s.chat_id)
                
                if len(s.playlist) < 5:
                    if not await self._fetch_playlist(s):
                        s.fails_in_row += 1
                        if s.fails_in_row >= 5:
                            logger.warning(f"[{s.chat_id}] Failed to find tracks for '{s.query}'. Switching source.")
                            await self._send_error_message(s.chat_id, f"🎧 No tracks found for «{s.display_name}». Finding something else...")
                            new_query, new_display_name = self._get_random_style_query()
                            s.query, s.display_name, s.search_mode = new_query, new_display_name, 'genre'
                            s.fails_in_row = 0
                            s.playlist.clear()
                            s.played_ids.clear()
                        await asyncio.sleep(5)
                        continue
                    s.fails_in_row = 0
                
                if not s.playlist:
                    logger.warning(f"[{s.chat_id}] Playlist is empty after fetch attempt.")
                    await asyncio.sleep(10)
                    continue
                
                # --- Get Stream Info Logic ---
                stream_info = None
                if s.preloaded_stream_info:
                    stream_info, s.preloaded_stream_info = s.preloaded_stream_info, None
                    s.playlist.popleft()
                else:
                    track = s.playlist.popleft()
                    result = await self._downloader.get_stream_info(track.identifier)
                    if not result.success:
                        logger.warning(f"[{s.chat_id}] Could not get stream info: {result.error}")
                        s.fails_in_row += 1
                        if s.fails_in_row >= 3:
                            logger.error(f"[{s.chat_id}] Failed to get stream info 3 times. Stopping radio.")
                            await self._send_error_message(s.chat_id, "❌ Could not retrieve audio streams. Radio stopped.")
                            break
                        continue
                    else:
                        s.fails_in_row = 0
                    stream_info = result.stream_info

                s.current_stream_info = stream_info
                s.played_ids.add(stream_info.track_info.identifier)

                if s.preload_task: s.preload_task.cancel()
                s.preload_task = asyncio.create_task(self._preload_next_track(s))

                if s.animation_task: s.animation_task.cancel()
                if s.dashboard_msg_id:
                    try:
                        await self._bot.delete_message(s.chat_id, s.dashboard_msg_id)
                    except (TelegramError, BadRequest):
                        pass
                
                try:
                    caption = self._build_dashboard_text(s)
                    # This is the URL to our own app's streaming endpoint
                    proxy_stream_url = f"{self._settings.BASE_URL}/stream/{stream_info.track_info.identifier}"

                    audio_msg = await self._bot.send_audio(
                        chat_id=s.chat_id,
                        audio=proxy_stream_url,
                        title=stream_info.track_info.title,
                        performer=stream_info.track_info.artist,
                        duration=stream_info.track_info.duration,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=get_dashboard_keyboard(self._settings.BASE_URL, s.chat_type, s.chat_id)
                    )
                    s.dashboard_msg_id = audio_msg.message_id
                    
                    s.animation_task = asyncio.create_task(self._animation_loop(s))

                    track_timeout = stream_info.track_info.duration + 2.0 if stream_info.track_info.duration > 0 else 90.0
                    await asyncio.wait_for(s.skip_event.wait(), timeout=track_timeout)
                except asyncio.TimeoutError:
                    pass
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"[{s.chat_id}] Error in send/play loop: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info(f"[{s.chat_id}] Radio loop cancelled.")
        finally:
            logger.info(f"[{s.chat_id}] Finalizing session.")
            await self.stop(s.chat_id)

    async def _animation_loop(self, s: RadioSession):
        """Periodically updates the player message to create an animation."""
        while not s.stop_event.is_set():
            try:
                await asyncio.sleep(4)
                await self._update_player_message(s)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[{s.chat_id}] Error in animation loop: {e}")
                await asyncio.sleep(10)

    async def _preload_next_track(self, s: RadioSession):
        try:
            if not s.playlist: return
            track = s.playlist[0]
            result = await self._downloader.get_stream_info(track.identifier)
            if result.success:
                s.preloaded_stream_info = result.stream_info
            else:
                logger.warning(f"[{s.chat_id}] Preload failed: {result.error}")
                if s.playlist and s.playlist[0].identifier == track.identifier: s.playlist.popleft()
        except Exception as e:
            logger.error(f"[{s.chat_id}] Critical preload error: {e}", exc_info=True)

    async def _fetch_playlist(self, s: RadioSession) -> bool:
        tracks = await self._downloader.search(s.query, search_mode=s.search_mode, limit=self._settings.MAX_RESULTS)
        if tracks:
            new = [t for t in tracks if t.identifier not in s.played_ids]
            s.playlist.extend(new)
            logger.info(f"[{s.chat_id}] Playlist supplemented with {len(new)} tracks.")
            if len(s.played_ids) > 200:
                s.played_ids.clear()
            return bool(new)
        return False

    async def _send_error_message(self, chat_id: int, text: str):
        try: await self._bot.send_message(chat_id, text)
        except: pass

    def _build_dashboard_text(self, s: RadioSession, status_override: str = None) -> str:
        status = status_override or "▶️ В эфире"
        track_info = s.current_stream_info.track_info if s.current_stream_info else None
        track = track_info.title if track_info else "..."
        artist = track_info.artist if track_info else "..."
        query = s.display_name or s.query
        animation_frame = s.animator.get_next_frame()

        return f"""{animation_frame}
*Трек:* `{track}`
*Артист:* `{artist}`
*Волна:* _{query}_
*Статус:* {status}"""

    async def _update_player_message(self, s: RadioSession, status_override: str = None):
        """Updates the caption of the current audio message."""
        if not s.dashboard_msg_id:
            return

        text = self._build_dashboard_text(s, status_override)
        try:
            await self._bot.edit_message_caption(
                chat_id=s.chat_id,
                message_id=s.dashboard_msg_id,
                caption=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_dashboard_keyboard(self._settings.BASE_URL, s.chat_type, s.chat_id)
            )
        except BadRequest as e:
            # If the message text is not modified, it's not an error we need to log verbosely.
            if "Message is not modified" not in str(e):
                logger.warning(f"Не удалось обновить подпись: {e}")
        except Exception as e:
            logger.warning(f"Не удалось обновить подпись: {e}")