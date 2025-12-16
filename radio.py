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
    
    # Предзагруженный файл
    next_file_path: Optional[str] = None
    next_track_info: Optional[TrackInfo] = None
    preload_task: Optional[asyncio.Task] = None
    
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
                # Пытаемся угадать mime, но для веба это не критично
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

    async def start(self, chat_id: int, query: str, chat_type: str = "private"):
        await self.stop(chat_id)
        
        session = RadioSession(chat_id=chat_id, query=query.strip(), chat_type=chat_type)
        self._sessions[chat_id] = session
        
        msg = await self._send_dashboard(session, status="🔍 Разогрев ламп...")
        if msg:
            session.dashboard_msg_id = msg.message_id
        
        # Запускаем основной цикл
        asyncio.create_task(self._radio_loop(session))
        logger.info(f"[{chat_id}] Radio started: {query}")

    async def stop(self, chat_id: int):
        if session := self._sessions.pop(chat_id, None):
            session.stop_event.set()
            if session.preload_task:
                session.preload_task.cancel()
            
            # Чистим файлы
            if session.next_file_path and Path(session.next_file_path).exists():
                try: Path(session.next_file_path).unlink()
                except: pass
                
            await self._update_dashboard(session, status="🛑 Эфир завершен")

    async def stop_all(self):
        for chat_id in list(self._sessions.keys()):
            await self.stop(chat_id)

    async def skip(self, chat_id: int):
        if session := self._sessions.get(chat_id):
            session.skip_event.set()
            await self._update_dashboard(session, status="⏭️ Переключение...")

    # --- Preload Logic ---

    async def _preload_next_track(self, s: RadioSession):
        """Фоновая задача: скачивает следующий трек, пока играет текущий."""
        try:
            if not s.playlist:
                return

            track = s.playlist[0] # Смотрим следующий, но не удаляем пока
            logger.info(f"[{s.chat_id}] Preloading next: {track.title}")
            
            result = await self._downloader.download_with_retry(track.identifier)
            
            if result.success:
                s.next_file_path = result.file_path
                s.next_track_info = result.track_info
                logger.info(f"[{s.chat_id}] Preload complete: {track.title}")
            else:
                logger.warning(f"[{s.chat_id}] Preload failed: {result.error}")
                # Удаляем битый трек из очереди, чтобы не застрять
                if s.playlist and s.playlist[0].identifier == track.identifier:
                    s.playlist.popleft()
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Preload error: {e}")

    # --- Main Loop ---

    async def _radio_loop(self, s: RadioSession):
        try:
            while not s.stop_event.is_set():
                s.skip_event.clear()

                # 1. Пополнение плейлиста
                if len(s.playlist) < 3:
                    if not await self._fetch_playlist(s):
                        s.fails_in_row += 1
                        if s.fails_in_row >= 2:
                            s.query = random.choice(self._settings.RADIO_GENRES)
                            s.fails_in_row = 0
                            await self._update_dashboard(s, status=f"🔀 Смена волны: {s.query}")
                        await asyncio.sleep(2)
                        continue
                    s.fails_in_row = 0

                # 2. Получение трека (из предзагрузки или скачивание сейчас)
                file_path = None
                track_info = None

                # Если уже скачано в фоне
                if s.next_file_path and Path(s.next_file_path).exists() and s.playlist:
                    file_path = s.next_file_path
                    track_info = s.next_track_info
                    s.playlist.popleft() # Удаляем из очереди, так как берем его
                    s.next_file_path = None
                    s.next_track_info = None
                
                # Если не скачано - качаем сейчас (первый запуск или ошибка прелоада)
                else:
                    if not s.playlist: continue
                    track = s.playlist.popleft()
                    await self._update_dashboard(s, status=f"⬇️ Загрузка: {track.title}...")
                    
                    result = await self._downloader.download_with_retry(track.identifier)
                    if not result.success:
                        logger.warning(f"DL Failed: {result.error}")
                        await asyncio.sleep(1)
                        continue
                    file_path = result.file_path
                    track_info = result.track_info

                # 3. Обновляем сессию
                s.current = track_info
                s.played_ids.add(track_info.identifier)
                if len(s.played_ids) > 200: s.played_ids = set(list(s.played_ids)[-50:])

                # 4. ЗАПУСК ПРЕДЗАГРУЗКИ СЛЕДУЮЩЕГО (Многопоточность!)
                if s.preload_task: s.preload_task.cancel()
                s.preload_task = asyncio.create_task(self._preload_next_track(s))

                # 5. Эфир
                await self._update_dashboard(s, status="▶️ В эфире")
                
                try:
                    with open(file_path, "rb") as f:
                        await self._bot.send_audio(
                            chat_id=s.chat_id,
                            audio=f,
                            title=track_info.title,
                            performer=track_info.artist,
                            duration=track_info.duration,
                            caption=f"#{s.query.replace(' ', '_')}",
                            reply_markup=get_track_keyboard(self._settings.BASE_URL, s.chat_id)
                        )
                    
                    # 6. Таймер (90 сек или длительность)
                    # Если трек длиннее 90 сек, играем 90 сек. Если короче - играем полностью.
                    limit = 90.0
                    duration = float(track_info.duration)
                    wait_time = duration if (duration > 0 and duration < limit) else limit
                    
                    try:
                        await asyncio.wait_for(s.skip_event.wait(), timeout=wait_time)
                    except asyncio.TimeoutError:
                        pass # Время вышло, идем дальше
                    
                except Exception as e:
                    logger.error(f"Send error: {e}")
                    await asyncio.sleep(5)
                
                # Удаляем сыгранный файл (чтобы не забивать диск)
                # Но не удаляем сразу, даем телеграму секунду на обработку, если нужно
                # (Хотя мы уже отправили файл, так что можно удалять)
                # Для надежности можно хранить последние 2 файла, но пока удаляем текущий
                # перед следующим циклом (или оставим его в download_dir, он перезапишется или очистится)
                # Лучшая практика: удалять старый файл в начале следующего цикла, если нужно место.
                # В данном коде мы полагаемся на то, что downloader перезаписывает файлы или уникальные имена.
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Loop error")
        finally:
            if s.preload_task: s.preload_task.cancel()
            if s.next_file_path and Path(s.next_file_path).exists():
                try: Path(s.next_file_path).unlink()
                except: pass

    # --- Helpers ---

    async def _send_dashboard(self, s: RadioSession, status: str) -> Optional[Message]:
        text = self._build_dashboard_text(s, status)
        try:
            return await self._bot.send_message(
                chat_id=s.chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_dashboard_keyboard(self._settings.BASE_URL, s.chat_type, s.chat_id)
            )
        except: return None

    async def _update_dashboard(self, s: RadioSession, status: str = None):
        if not s.dashboard_msg_id: return
        text = self._build_dashboard_text(s, status)
        try:
            await self._bot.edit_message_text(
                chat_id=s.chat_id,
                message_id=s.dashboard_msg_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_dashboard_keyboard(self._settings.BASE_URL, s.chat_type, s.chat_id)
            )
        except BadRequest:
            logger.warning(f"Dashboard message not found in chat {s.chat_id}. Disabling updates.")
            s.dashboard_msg_id = None
        except Exception as e:
            logger.error(f"Failed to update dashboard for {s.chat_id}: {e}")

    def _build_dashboard_text(self, s: RadioSession, status_override: str = None) -> str:
        if status_override: status = status_override
        elif s.current: status = f"▶️ Играет: {s.current.artist}"
        else: status = "⏳ Ожидание..."

        track = s.current.title if s.current else "..."
        artist = s.current.artist if s.current else "..."
        
        # Экранирование
        track = track.replace("*", "").replace("_", "").replace("`", "")
        artist = artist.replace("*", "").replace("_", "").replace("`", "")
        query = s.query.replace("*", "").replace("_", "").replace("`", "")

        return f"""📻 *CYBER RADIO V7*
━━━━━━━━━━━━━━━━━━
💿 *Трек:* `{track}`
👤 *Артист:* `{artist}`
🏷 *Волна:* _{query}_

▓▓▓▓▓░░░░░

ℹ️ _Статус:_ {status}
"""

    async def _fetch_playlist(self, s: RadioSession) -> bool:
        q = random.choice([s.query, f"{s.query} music", f"best {s.query}"])
        tracks = await self._downloader.search(q, limit=self._settings.MAX_RESULTS)
        if tracks:
            new = [t for t in tracks if t.identifier not in s.played_ids]
            random.shuffle(new)
            s.playlist.extend(new)
            return True
        return False