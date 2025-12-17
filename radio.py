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
    current_file_path: Optional[Path] = None
    playlist: Deque[TrackInfo] = field(default_factory=deque)
    played_ids: Set[str] = field(default_factory=set)
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    skip_event: asyncio.Event = field(default_factory=asyncio.Event)
    preload_task: Optional[asyncio.Task] = None
    next_file_path: Optional[str] = None
    next_track_info: Optional[TrackInfo] = None
    fails_in_row: int = 0
    dashboard_msg_id: Optional[int] = None

class RadioManager:
    def __init__(self, bot: Bot, settings: Settings, downloader: YouTubeDownloader):
        self._bot = bot
        self._settings = settings
        self._downloader = downloader
        self._sessions: Dict[int, RadioSession] = {}

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
            data[str(chat_id)] = {
                "chat_id": chat_id, "query": s.query, "current": current_info,
                "playlist_len": len(s.playlist), "is_active": not s.stop_event.is_set()
            }
        return {"sessions": data}

    async def start(self, chat_id: int, query: str, chat_type: str, message_id: Optional[int] = None):
        await self.stop(chat_id)
        session = RadioSession(chat_id=chat_id, query=query.strip(), chat_type=chat_type)
        self._sessions[chat_id] = session
        
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
            
            paths_to_delete = [session.next_file_path, session.current_file_path]
            for p_str in paths_to_delete:
                if p_str and Path(p_str).exists():
                    try: Path(p_str).unlink()
                    except OSError as e: logger.error(f"Не удалось удалить файл {p_str}: {e}")
            
            await self._update_dashboard(session, status="🛑 Эфир завершен")

    async def stop_all(self):
        for chat_id in list(self._sessions.keys()): await self.stop(chat_id)

    async def skip(self, chat_id: int):
        if session := self._sessions.get(chat_id):
            session.skip_event.set()
            await self._update_dashboard(session, status="⏭️ Переключение...")

    async def _preload_next_track(self, s: RadioSession):
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

    async def _radio_loop(self, s: RadioSession):
        try:
            logger.info(f"[{s.chat_id}] Запущен главный цикл радио.")
            while not s.stop_event.is_set():
                s.skip_event.clear()

                if len(s.playlist) < 5:
                    if not await self._fetch_playlist(s):
                        s.fails_in_row += 1
                        if s.fails_in_row >= 2:
                            s.query = random.choice(self._settings.RADIO_GENRES)
                            s.fails_in_row = 0
                            await self._update_dashboard(s, status=f"🔀 Смена волны на: {s.query}")
                        await asyncio.sleep(5)
                        continue
                    s.fails_in_row = 0
                
                if not s.playlist:
                    await self._send_error_message(s.chat_id, "Не удалось найти треки. Попробуйте другой жанр.")
                    break

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
                            duration=track_info.duration, caption=f"#{s.query.replace(' ', '_')}",
                            reply_markup=get_track_keyboard(self._settings.BASE_URL, s.chat_id)
                        )
                    
                    wait_time = 90.0
                    
                    await asyncio.wait_for(s.skip_event.wait(), timeout=wait_time)
                except asyncio.TimeoutError:
                    logger.info(f"[{s.chat_id}] Трек завершился по таймауту, переключаюсь на следующий.")
                except asyncio.CancelledError:
                    logger.warning(f"[{s.chat_id}] Задача отправки или ожидания была отменена.")
                    raise  # Re-raise to allow the outer loop to handle cancellation
                except TelegramError as e:
                    logger.error(f"[{s.chat_id}] Ошибка Telegram при отправке/ожидании: {e}")
                    if "forbidden" in str(e).lower(): s.stop_event.set()
                except Exception as e:
                    logger.error(f"[{s.chat_id}] НЕИЗВЕСТНАЯ ошибка в цикле отправки: {e}", exc_info=True)
            
        except asyncio.CancelledError:
            logger.info(f"[{s.chat_id}] Цикл радио отменен.")
        except Exception as e:
            logger.exception(f"[{s.chat_id}] Критическая ошибка в цикле радио. Завершаю сессию.")
        finally:
            logger.info(f"[{s.chat_id}] Завершение сессии.")
            await self.stop(s.chat_id)
    
    async def _fetch_playlist(self, s: RadioSession) -> bool:
        q = random.choice([s.query, f"{s.query} music", f"best {s.query}"])
        tracks = await self._downloader.search(q, limit=self._settings.MAX_RESULTS)
        if tracks:
            new = [t for t in tracks if t.identifier not in s.played_ids]
            s.playlist.extend(new)
            logger.info(f"[{s.chat_id}] Плейлист пополнен на {len(new)} треков.")
            return bool(new)
        return False

    async def _send_error_message(self, chat_id: int, text: str):
        try: await self._bot.send_message(chat_id, text)
        except: pass

    def _build_dashboard_text(self, s: RadioSession, status_override: str = None) -> str:
        if status_override: status = status_override
        elif s.current: status = f"▶️ В эфире: {s.current.title[:35]}..."
        else: status = "⏳ Ожидание..."
        track = s.current.title if s.current else "..."
        artist = s.current.artist if s.current else "..."
        query = s.query
        return f"""
📻 *CYBER RADIO V7*
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