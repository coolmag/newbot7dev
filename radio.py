from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

import logging
from telegram import Bot

from youtube import Track, yt_search, download_audio_mp3
from config import Config # Добавлено: импортируем Config

logger = logging.getLogger("radio")


GENRES = [
    "rock hits",
    "orchestral",
    "ambient",
    "tropical house",
    "synthwave",
    "hip hop",
    "jazz",
]


@dataclass
class RadioSession:
    chat_id: int
    query: str
    started_at: float = field(default_factory=lambda: time.time())
    current: Optional[Track] = None
    playlist: Deque[Track] = field(default_factory=deque)
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    skip_event: asyncio.Event = field(default_factory=asyncio.Event)
    fails_in_row: int = 0
    last_error: Optional[str] = None
    audio_file_path: Optional[Path] = None # Добавлено


class RadioManager:
    def __init__(
        self,
        bot: Bot,
        cfg: Config, # Изменено: теперь принимаем Config
    ) -> None:
        self.bot = bot
        self.cookies_path = cfg.cookies_path
        self.play_window_sec = cfg.play_window_sec
        self.max_results = cfg.max_results
        self.search_timeout_sec = cfg.search_timeout_sec
        self.download_timeout_sec = cfg.download_timeout_sec
        self.max_filesize_mb = cfg.max_filesize_mb

        self._sessions: Dict[int, RadioSession] = {}
        self._tasks: Dict[int, asyncio.Task[None]] = {}
        self._dl_sem = asyncio.Semaphore(cfg.max_concurrent_downloads) # Используем cfg.max_concurrent_downloads

    def status(self) -> dict:
        data = {}
        for chat_id, s in self._sessions.items():
            current_track_info = None
            if s.current:
                audio_url = None
                if s.audio_file_path and s.audio_file_path.exists():
                    audio_url = f"/audio/{s.current.id}" # Будет обработан FastAPI

                current_track_info = {
                    "id": s.current.id,
                    "title": s.current.title,
                    "artist": s.current.artist,
                    "cover_url": s.current.cover_url,
                    "audio_url": audio_url,
                    "duration": s.current.duration,
                    "webpage_url": s.current.webpage_url,
                }

            data[str(chat_id)] = {
                "chat_id": chat_id,
                "query": s.query,
                "started_at": s.started_at,
                "current": current_track_info, # Теперь объект с полной информацией
                "playlist_len": len(s.playlist),
                "fails_in_row": s.fails_in_row,
                "last_error": s.last_error,
            }
        logger.debug("Radio status for chat %s: %s", chat_id, data[str(chat_id)])
        return {"sessions": data}

    async def start(self, chat_id: int, query: str) -> None:
        await self.stop(chat_id)

        s = RadioSession(chat_id=chat_id, query=query.strip() or random.choice(GENRES))
        self._sessions[chat_id] = s
        self._tasks[chat_id] = asyncio.create_task(self._loop(s))
        logger.info("Radio started chat=%s query=%r", chat_id, s.query)

    async def stop(self, chat_id: int) -> None:
        s = self._sessions.get(chat_id)
        t = self._tasks.get(chat_id)
        if s:
            s.stop_event.set()
            s.skip_event.set()
        if t:
            t.cancel()
            try:
                await t
            except Exception:
                pass
        self._sessions.pop(chat_id, None)
        self._tasks.pop(chat_id, None)

    async def stop_all(self) -> None: # Добавлено: метод stop_all
        for chat_id in list(self._sessions.keys()):
            await self.stop(chat_id)

    async def skip(self, chat_id: int) -> None:
        s = self._sessions.get(chat_id)
        if s:
            s.skip_event.set()

    async def _refill_playlist(self, s: RadioSession) -> None:
        """
        Рефилл с мягким backoff и сменой запросов.
        """
        queries = [
            s.query,
            f"{s.query} music",
            f"best {s.query} mix",
            random.choice(GENRES),
        ]

        for attempt, q in enumerate(queries, start=1):
            try:
                logger.info("[Radio] search chat=%s q=%r attempt=%s", s.chat_id, q, attempt)
                tracks = await yt_search(
                    q,
                    max_results=self.max_results,
                    timeout_sec=self.search_timeout_sec,
                    cookies_path=self.cookies_path,
                )
                if tracks:
                    random.shuffle(tracks)
                    for t in tracks:
                        s.playlist.append(t)
                    s.fails_in_row = 0
                    s.last_error = None
                    logger.info("[Radio] added=%s total=%s chat=%s", len(tracks), len(s.playlist), s.chat_id)
                    return
            except asyncio.TimeoutError:
                s.last_error = "search timeout"
            except Exception as e:
                s.last_error = f"search error: {e}"

            # backoff чтобы не крутиться вхолостую
            await asyncio.sleep(2 + attempt)

        s.fails_in_row += 1
        logger.warning("[Radio] playlist empty after attempts chat=%s fails=%s", s.chat_id, s.fails_in_row)

        if s.fails_in_row >= 3:
            s.query = random.choice(GENRES)
            s.fails_in_row = 0
            logger.warning("[Radio] auto-change genre chat=%s new_query=%r", s.chat_id, s.query)

    async def _loop(self, s: RadioSession) -> None:
        """
        Главный цикл радио:
        - если плейлист пуст, пытаемся наполнить (с backoff)
        - скачиваем трек с таймаутом, при зависании — kill и skip
        - после отправки ждём play_window_sec или skip/stop
        """
        while not s.stop_event.is_set():
            if not s.playlist:
                await self._refill_playlist(s)
                if not s.playlist:
                    await asyncio.sleep(3)
                    continue

            track = s.playlist.popleft()
            s.current = track
            s.skip_event.clear()

            try:
                await self.bot.send_message(s.chat_id, f"⏳ Скачиваю: `{track.title}`", parse_mode="Markdown")

                async with self._dl_sem:
                    file_path = await download_audio_mp3(
                        track,
                        timeout_sec=self.download_timeout_sec,
                        max_filesize_mb=self.max_filesize_mb,
                        cookies_path=self.cookies_path,
                    )

                # отправка файла
                with file_path.open("rb") as f:
                    await self.bot.send_audio(
                        chat_id=s.chat_id,
                        audio=f,
                        title=track.title[:64],
                        caption=track.webpage_url,
                    )

                # Сохраняем путь к файлу для веб-плеера
                s.audio_file_path = file_path

                # Временно не чистим файл для тестирования веб-плеера
                # TODO: реализовать механизм очистки файлов по истечении срока жизни или по запросу
                # try:
                #     file_path.unlink()
                #     file_path.parent.rmdir()
                # except Exception:
                #     pass

            except asyncio.TimeoutError:
                s.last_error = "download timeout"
                logger.warning("[Radio] download timeout chat=%s track=%s", s.chat_id, track.id)
                continue
            except Exception as e:
                s.last_error = f"download/send error: {e}"
                logger.exception("[Radio] error chat=%s", s.chat_id)
                continue

            # Ждём окно проигрывания или skip/stop
            try:
                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(asyncio.sleep(self.play_window_sec)),
                        asyncio.create_task(s.skip_event.wait()),
                        asyncio.create_task(s.stop_event.wait()),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for p in pending:
                    p.cancel()
            except Exception:
                pass

        logger.info("Radio stopped chat=%s", s.chat_id)
