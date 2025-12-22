from __future__ import annotations
import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Optional, Set, Dict, List, TYPE_CHECKING
from dataclasses import dataclass, field

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest

from config import Settings
from keyboards import get_genre_voting_keyboard

if TYPE_CHECKING:
    from radio import RadioManager

logger = logging.getLogger("radio_voting")

@dataclass
class GenreVotingSession:
    chat_id: int
    is_vote_in_progress: bool = False
    votes: Dict[str, Set[int]] = field(default_factory=dict)
    current_vote_genres: List[str] = field(default_factory=list)
    vote_message_id: Optional[int] = None
    vote_task: Optional[asyncio.Task] = None

class GenreVotingService:
    def __init__(self, bot: Bot, settings: Settings):
        self._bot = bot
        self._settings = settings
        self._sessions: Dict[int, GenreVotingSession] = {}

    def get_session(self, chat_id: int) -> Optional[GenreVotingSession]:
        return self._sessions.get(chat_id)

    async def start_new_voting_cycle(self, chat_id: int):
        """Starts a new voting cycle, always creating a new message."""
        if chat_id in self._sessions and self._sessions[chat_id].is_vote_in_progress:
            logger.warning(f"[{chat_id}] Попытка запустить голосование, когда оно уже идет.")
            return

        session = GenreVotingSession(chat_id=chat_id)
        self._sessions[chat_id] = session
        
        session.vote_task = asyncio.create_task(self._run_vote_lifecycle(session))

    async def _run_vote_lifecycle(self, s: GenreVotingSession):
        """
        🆕 Manages the voting process with improved error handling.
        """
        s.is_vote_in_progress = True
        s.votes = {}
        
        all_genres = list(self._settings.GENRE_DATA.keys())
        sample_size = min(len(all_genres), 6)
        s.current_vote_genres = sorted(random.sample(all_genres, sample_size))

        logger.info(f"[{s.chat_id}] Начинается голосование за жанр: {s.current_vote_genres}")

        try:
            vote_msg_text = (
                "📢 **Началось голосование за жанр!**\n\n"
                "Выберите, что будет играть следующий час. "
                "Голосование продлится 3 минуты."
            )
            
            vote_msg = await self._bot.send_message(
                chat_id=s.chat_id,
                text=vote_msg_text,
                reply_markup=get_genre_voting_keyboard(s.current_vote_genres, s.votes),
                parse_mode=ParseMode.MARKDOWN,
            )
            s.vote_message_id = vote_msg.message_id
            
        except Exception as e:
            logger.error(f"[{s.chat_id}] Не удалось отправить сообщение для голосования: {e}")
            s.is_vote_in_progress = False
            return

        # 🆕 Ждем с периодическим обновлением клавиатуры
        try:
            for _ in range(6):  # 6 итераций по 30 секунд = 3 минуты
                await asyncio.sleep(30)
                if not s.is_vote_in_progress:
                    break
                # Обновляем счетчик голосов
                await self._update_vote_keyboard(s)
        except asyncio.CancelledError:
            logger.info(f"[{s.chat_id}] Голосование отменено")
            raise
        
        # Завершаем голосование
        if s.is_vote_in_progress:
            await self.end_voting(s.chat_id)

    async def register_vote(self, chat_id: int, genre_key: str, user_id: int) -> bool:
        session = self.get_session(chat_id)
        if not session or not session.is_vote_in_progress:
            return False
        
        for g in session.votes:
            session.votes[g].discard(user_id)
            
        if genre_key not in session.votes:
            session.votes[genre_key] = set()
        session.votes[genre_key].add(user_id)
        
        await self._update_vote_keyboard(session)
        return True

    async def _update_vote_keyboard(self, s: GenreVotingSession):
        if not s.is_vote_in_progress or not s.vote_message_id: return
        try:
            await self._bot.edit_message_reply_markup(
                chat_id=s.chat_id, message_id=s.vote_message_id,
                reply_markup=get_genre_voting_keyboard(s.current_vote_genres, s.votes)
            )
        except (TelegramError, BadRequest): pass # Ignore "not modified" or other board errors

    async def end_voting(self, chat_id: int) -> Optional[str]:
        """Ends the voting, announces the winner, and schedules message deletion."""
        session = self._sessions.pop(chat_id, None)
        if not session or not session.is_vote_in_progress:
            return None

        logger.info(f"[{session.chat_id}] Голосование завершено. Подвожу итоги.")
        
        if session.votes:
            winner = max(session.votes, key=lambda g: len(session.votes[g]))
        else:
            winner = random.choice(session.current_vote_genres) if session.current_vote_genres else None
        
        if winner:
            winner_name = self._settings.GENRE_DATA.get(winner, {}).get("name", winner.capitalize())
            announcement = f"🎉 **Голосование завершено!**\n\nСледующий час играет: **{winner_name}**"
        else:
            announcement = "Результаты голосования не определены."

        try:
            if session.vote_message_id:
                await self._bot.edit_message_text(
                    chat_id=session.chat_id, message_id=session.vote_message_id,
                    text=announcement, parse_mode=ParseMode.MARKDOWN, reply_markup=None
                )
                # Schedule deletion of the results message
                asyncio.create_task(self._delete_message_after_delay(session.chat_id, session.vote_message_id, 15))
        except (TelegramError, BadRequest) as e:
            logger.warning(f"[{session.chat_id}] Не удалось обновить или удалить сообщение о голосовании: {e}")

        session.is_vote_in_progress = False
        if session.vote_task:
            session.vote_task.cancel()
        
        return winner

    async def _delete_message_after_delay(self, chat_id: int, message_id: int, delay_s: int):
        """Waits for a delay and then deletes a message."""
        await asyncio.sleep(delay_s)
        try:
            await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
        except (TelegramError, BadRequest) as e:
            logger.info(f"Не удалось удалить сообщение {message_id} в чате {chat_id}: {e}")

    async def stop_all_votings(self):
        for chat_id in list(self._sessions.keys()):
            if session := self._sessions.get(chat_id):
                session.is_vote_in_progress = False
                if session.vote_task:
                    session.vote_task.cancel()
                self._sessions.pop(chat_id, None)

    async def end_voting_session(self, chat_id: int):
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