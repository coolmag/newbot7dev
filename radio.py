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
                mime = "audio/mpeg" 
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

    async def start(self, chat_id: int, query: str, chat_type: str = "private", message_id: Optional[int] = None):
        await self.stop(chat_id)
        
        session = RadioSession(chat_id=chat_id, query=query.strip(), chat_type=chat_type)
        self._sessions[chat_id] = session
        
        # Если есть ID сообщения, редактируем его. Иначе - отправляем новое.
        if message_id:
            session.dashboard_msg_id = message_id
            await self._update_dashboard(session, status="🔍 Поиск треков...")
        else:
            msg = await self._send_dashboard(session, status="🔍 Поиск треков...")
            if msg:
                session.dashboard_msg_id = msg.message_id
        
        asyncio.create_task(self._radio_loop(session))
        logger.info(f"[{chat_id}] Радио запущено: {query}")

    async def stop(self, chat_id: int):
        if session := self._sessions.pop(chat_id, None):
            session.stop_event.set()
            if session.preload_task:
                session.preload_task.cancel()
            
            if session.next_file_path and Path(session.next_file_path).exists():
                try: Path(session.next_file_path).unlink()
                except: pass
            if session.current_file_path and session.current_file_path.exists():
                try: session.current_file_path.unlink()
                except: pass
            await self._update_dashboard(session, status="🛑 Эфир завершен")

    async def stop_all(self):
        for chat_id in list(self._sessions.keys()): await self.stop(chat_id)

    async def skip(self, chat_id: int):
        if session := self._sessions.get(chat_id):
            session.skip_event.set()
            await self._update_dashboard(session, status="⏭️ Переключение...")

    async def _preload_next_track(self, s: RadioSession):
        try:
            if not s.playlist:
                logger.debug(f"[{s.chat_id}] Предзагрузка: плейлист пуст.")
                return
            track = s.playlist[0]
            logger.info(f"[{s.chat_id}] Предзагрузка следующего трека: {track.title}")
            result = await self._downloader.download_with_retry(track.identifier)
            if result.success:
                s.next_file_path = result.file_path
                s.next_track_info = result.track_info
                logger.info(f"[{s.chat_id}] Предзагрузка завершена: {track.title}")
            else:
                logger.warning(f"[{s.chat_id}] Ошибка предзагрузки: {result.error}")
                if s.playlist and s.playlist[0].identifier == track.identifier:
                    s.playlist.popleft()
        except Exception as e:
            logger.error(f"[{s.chat_id}] Критическая ошибка в предзагрузке: {e}", exc_info=True)

    async def _radio_loop(self, s: RadioSession):
        loop_count = 0
        try:
            logger.info(f"[{s.chat_id}] Запущен главный цикл радио.")
            while not s.stop_event.is_set():
                loop_count += 1
                logger.info(f"[{s.chat_id}] Итерация цикла #{loop_count}. Плейлист: {len(s.playlist)} треков.")
                s.skip_event.clear()

                if len(s.playlist) < 5:
                    logger.info(f"[{s.chat_id}] В плейлисте мало треков ({len(s.playlist)}), пополняю...")
                    if not await self._fetch_playlist(s):
                        s.fails_in_row += 1
                        logger.warning(f"[{s.chat_id}] Не удалось пополнить плейлист. Ошибок подряд: {s.fails_in_row}")
                        if s.fails_in_row >= 2:
                            s.query = random.choice(self._settings.RADIO_GENRES)
                            s.fails_in_row = 0
                            logger.error(f"[{s.chat_id}] 2 ошибки подряд. Меняю волну на случайную: {s.query}")
                            await self._update_dashboard(s, status=f"🔀 Смена волны на: {s.query}")
                        await asyncio.sleep(5)
                        continue
                    s.fails_in_row = 0
                
                if not s.playlist:
                    logger.error(f"[{s.chat_id}] Плейлист пуст после попытки пополнения. Радио остановлено.")
                    await self._send_error_message(s.chat_id, "Не удалось найти треки по данному запросу. Попробуйте другой жанр.")
                    break

                file_path, track_info = None, None
                if s.next_file_path and Path(s.next_file_path).exists() and s.playlist:
                    logger.info(f"[{s.chat_id}] Использую предзагруженный трек.")
                    file_path, track_info, s.next_file_path, s.next_track_info = s.next_file_path, s.next_track_info, None, None
                    s.playlist.popleft()
                else:
                    track = s.playlist.popleft()
                    logger.info(f"[{s.chat_id}] Предзагруженного трека нет. Качаю сейчас: {track.title}")
                    await self._update_dashboard(s, status=f"⬇️ Загрузка: {track.title[:30]}...")
                    result = await self._downloader.download_with_retry(track.identifier)
                    if not result.success:
                        logger.warning(f"[{s.chat_id}] Ошибка скачивания: {result.error}")
                        await asyncio.sleep(1)
                        continue
                    file_path, track_info = result.file_path, result.track_info

                s.current, s.current_file_path = track_info, Path(file_path)
                s.played_ids.add(track_info.identifier)
                if len(s.played_ids) > 200: s.played_ids = set(list(s.played_ids)[-50:])

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
                    
                    interval = 90.0
                    duration = float(track_info.duration)
                    wait_time = max(duration, interval) if duration > 0 else interval
                    logger.info(f"[{s.chat_id}] Трек '{track_info.title}' отправлен. Ожидание {wait_time} секунд.")
                    
                    await asyncio.wait_for(s.skip_event.wait(), timeout=wait_time)
                    logger.info(f"[{s.chat_id}] Ожидание завершено (или был скип). Перехожу к следующему треку.")
                except TelegramError as e:
                    logger.error(f"[{s.chat_id}] Ошибка Telegram API: {e}")
                    if "forbidden" in str(e).lower() or "chat not found" in str(e).lower():
                        logger.critical(f"[{s.chat_id}] Бот заблокирован, сессия остановлена.")
                        s.stop_event.set()
                    else: await asyncio.sleep(5)
                except Exception as e:
                    logger.error(f"[{s.chat_id}] Ошибка отправки: {e}", exc_info=True)
                    await asyncio.sleep(5)
            
            logger.info(f"[{s.chat_id}] Цикл радио завершился.")
        except asyncio.CancelledError:
            logger.info(f"[{s.chat_id}] Цикл радио отменен.")
        except Exception as e:
            logger.exception(f"[{s.chat_id}] Критическая ошибка в цикле радио.")
        finally:
            logger.info(f"[{s.chat_id}] Блок finally: останавливаю сессию.")
            await self.stop(s.chat_id)
    
    async def _fetch_playlist(self, s: RadioSession) -> bool:
        q = random.choice([s.query, f"{s.query} music", f"best {s.query}"])
        tracks = await self._downloader.search(q, limit=self._settings.MAX_RESULTS)
        if tracks:
            new = [t for t in tracks if t.identifier not in s.played_ids]
            random.shuffle(new)
            s.playlist.extend(new)
            logger.info(f"[{s.chat_id}] Плейлист пополнен на {len(new)} треков.")
            return True
        logger.warning(f"[{s.chat_id}] Поиск по запросу '{q}' не дал новых треков.")
        return False

    async def _send_error_message(self, chat_id: int, text: str):
        try:
            await self._bot.send_message(chat_id, text)
        except Exception:
            pass

    async def _send_dashboard(self, s: RadioSession, status: str) -> Optional[Message]:
        # ...
        pass
    async def _update_dashboard(self, s: RadioSession, status: str = None):
        # ...
        pass
    def _build_dashboard_text(self, s: RadioSession, status_override: str = None) -> str:
        # ...
        pass

