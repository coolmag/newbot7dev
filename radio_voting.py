from __future__ import annotations
import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Optional, Set, Dict, List, TYPE_CHECKING

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config import Settings
from keyboards import get_genre_voting_keyboard

if TYPE_CHECKING:
    from radio import RadioManager # For type hinting without circular import

logger = logging.getLogger("radio_voting")

class GenreVotingService:
    def __init__(self, bot: Bot, settings: Settings):
        self._bot = bot
        self._settings = settings
        self._sessions: Dict[int, GenreVotingSession] = {} # Key: chat_id

    def get_session(self, chat_id: int) -> Optional["GenreVotingSession"]:
        return self._sessions.get(chat_id)

    async def start_new_voting_cycle(self, chat_id: int, message_id: Optional[int] = None):
        """Starts a new voting cycle for a given chat."""
        # Ensure only one vote is active per chat
        if chat_id in self._sessions and self._sessions[chat_id].is_vote_in_progress:
            logger.warning(f"[{chat_id}] Попытка запустить голосование, когда оно уже идет.")
            return

        session = GenreVotingSession(chat_id=chat_id)
        self._sessions[chat_id] = session
        
        session.vote_task = asyncio.create_task(self._run_vote_lifecycle(session, message_id))

    async def _run_vote_lifecycle(self, s: "GenreVotingSession", message_id: Optional[int]):
        s.is_vote_in_progress = True
        s.votes = {}
        
        all_genres = list(self._settings.GENRE_DATA.keys())
        sample_size = min(len(all_genres), 6) # 6 genres to vote for
        s.current_vote_genres = sorted(random.sample(all_genres, sample_size))

        logger.info(f"[{s.chat_id}] Начинается голосование за жанр: {s.current_vote_genres}")

        try:
            vote_msg_text = f"📢 **Началось голосование за жанр!**\n\nВыберите, что будет играть следующий час. Голосование продлится 3 минуты."
            if message_id: # Edit existing message if provided (e.g., from /vote command)
                await self._bot.edit_message_text(
                    chat_id=s.chat_id,
                    message_id=message_id,
                    text=vote_msg_text,
                    reply_markup=get_genre_voting_keyboard(s.current_vote_genres, s.votes),
                    parse_mode=ParseMode.MARKDOWN,
                )
                s.vote_message_id = message_id
            else: # Send new message
                vote_msg = await self._bot.send_message(
                    chat_id=s.chat_id,
                    text=vote_msg_text,
                    reply_markup=get_genre_voting_keyboard(s.current_vote_genres, s.votes),
                    parse_mode=ParseMode.MARKDOWN,
                )
                s.vote_message_id = vote_msg.message_id
        except Exception as e:
            logger.error(f"[{s.chat_id}] Не удалось отправить/отредактировать сообщение для голосования: {e}")
            s.is_vote_in_progress = False
            return

        await asyncio.sleep(180)  # 3 minutes for voting
        if s.is_vote_in_progress: # Check if it wasn't already ended (e.g., by manual admin action)
            await self.end_voting(s.chat_id)

    async def register_vote(self, chat_id: int, genre_key: str, user_id: int) -> bool:
        session = self.get_session(chat_id)
        if not session or not session.is_vote_in_progress:
            return False
        
        # Allow user to change their vote
        for g in session.votes:
            session.votes[g].discard(user_id)
            
        if genre_key not in session.votes:
            session.votes[genre_key] = set()
        session.votes[genre_key].add(user_id)
        
        logger.debug(f"[{chat_id}] Пользователь {user_id} проголосовал за {genre_key}.")
        await self._update_vote_keyboard(session)
        return True

    async def _update_vote_keyboard(self, s: "GenreVotingSession"):
        if not s.is_vote_in_progress or not s.vote_message_id: return
        try:
            await self._bot.edit_message_reply_markup(
                chat_id=s.chat_id, message_id=s.vote_message_id,
                reply_markup=get_genre_voting_keyboard(s.current_vote_genres, s.votes)
            )
        except TelegramError: pass # Ignore "not modified" errors

    async def end_voting(self, chat_id: int) -> Optional[str]:
        """Ends the voting process and returns the winning genre."""
        session = self._sessions.pop(chat_id, None)
        if not session or not session.is_vote_in_progress:
            return None # Voting already ended or never started

        logger.info(f"[{session.chat_id}] Голосование завершено. Подвожу итоги.")
        
        if session.votes:
            winner = max(session.votes, key=lambda g: len(session.votes[g]))
        else:
            winner = random.choice(session.current_vote_genres) if session.current_vote_genres else "random" # Fallback
        
        winner_name = self._settings.GENRE_DATA.get(winner, {}).get("name", winner.capitalize())
        announcement = f"🎉 **Голосование завершено!**\n\nСледующий час играет: **{winner_name}**"
        
        try:
            if session.vote_message_id:
                await self._bot.edit_message_text(
                    chat_id=session.chat_id, message_id=session.vote_message_id,
                    text=announcement, parse_mode=ParseMode.MARKDOWN, reply_markup=None
                )
        except TelegramError as e:
            logger.warning(f"[{session.chat_id}] Не удалось обновить сообщение о голосовании: {e}")

        session.is_vote_in_progress = False
        if session.vote_task:
            session.vote_task.cancel()
        
        return winner

    async def stop_all_votings(self):
        for chat_id in list(self._sessions.keys()):
            if session := self._sessions.get(chat_id):
                session.is_vote_in_progress = False
                if session.vote_task:
                    session.vote_task.cancel()
                self._sessions.pop(chat_id, None)

    async def end_voting_session(self, chat_id: int):
        """Gracefully ends a voting session for a specific chat, cancelling its task."""
        session = self._sessions.pop(chat_id, None)
        if session and session.vote_task:
            session.vote_task.cancel()
            try:
                await session.vote_task
            except asyncio.CancelledError:
                pass
            logger.info(f"[{chat_id}] Сессия голосования завершена и задача отменена.")
        elif session:
            logger.info(f"[{chat_id}] Сессия голосования удалена.")

@dataclass
class GenreVotingSession:
    chat_id: int
    is_vote_in_progress: bool = False
    votes: Dict[str, Set[int]] = field(default_factory=dict)
    current_vote_genres: List[str] = field(default_factory=list)
    vote_message_id: Optional[int] = None
    vote_task: Optional[asyncio.Task] = None
