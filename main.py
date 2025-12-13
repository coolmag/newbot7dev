from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from telegram import Update
from telegram.ext import Application

from config import Settings # Изменено на Settings
from logging_setup import setup_logging
from cache import CacheService # Изменено на CacheService
from youtube import YouTubeDownloader # Добавлено
from radio import RadioManager
from handlers import setup_handlers

logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = Settings() # Используем новый класс Settings

    # Создаем директорию для загрузок, если её нет
    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # Записываем cookies, если они есть в переменных окружения
    if settings.COOKIES_CONTENT:
        settings.COOKIES_FILE.write_text(settings.COOKIES_CONTENT, encoding="utf-8")
        logger.info("✅ cookies.txt создан из переменной окружения.")

    cache = CacheService(settings) # Используем новый CacheService
    await cache.initialize()
    logger.info("Cache initialized")

    youtube_downloader = YouTubeDownloader(settings, cache) # Инициализируем YouTubeDownloader

    tg_app = Application.builder().token(settings.BOT_TOKEN).build() # Используем settings.BOT_TOKEN

    # error handler чтобы видеть реальные причины
    async def on_error(update, context):
        logger.exception("PTB error: %s", context.error)

    tg_app.add_error_handler(on_error)

    radio = RadioManager(
        bot=tg_app.bot,
        settings=settings, # Передаем settings
        youtube_downloader=youtube_downloader, # Передаем youtube_downloader
    )

    setup_handlers(tg_app, radio, settings) # Передаем settings

    await tg_app.initialize()
    await tg_app.start()

    # Установка вебхука
    await tg_app.bot.set_webhook(url=settings.WEBHOOK_URL) # Используем settings.WEBHOOK_URL
    logger.info("✅ Webhook set to: %s", settings.WEBHOOK_URL)

    # сохраняем в app.state
    app.state.settings = settings # Изменено на app.state.settings
    app.state.cache = cache
    app.state.tg_app = tg_app
    app.state.radio = radio
    app.state.youtube_downloader = youtube_downloader # Сохраняем youtube_downloader

    yield

    # shutdown
    try:
        await app.state.radio.stop_all()
    except Exception:
        pass
    await tg_app.stop()
    await tg_app.shutdown()
    await cache.close()


app = FastAPI(lifespan=lifespan)

# статика webapp
app.mount("/webapp", StaticFiles(directory="webapp", html=True), name="webapp")


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/api/radio/status")
async def radio_status():
    radio = app.state.radio
    return JSONResponse(radio.status())


@app.post("/telegram")
async def telegram_webhook(req: Request):
    data = await req.json()
    tg_app: Application = app.state.tg_app
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.get("/audio/{track_id}")
async def get_audio_file(track_id: str):
    logger.debug("Request for audio file with track_id: %s", track_id)
    radio = app.state.radio
    for chat_id, session in radio._sessions.items():
        if session.current and session.current.id == track_id:
            logger.debug("Found session for track_id %s in chat %s. Current track_id: %s, audio_file_path: %s, exists: %s",
                         track_id, chat_id, session.current.id, session.audio_file_path, session.audio_file_path.exists() if session.audio_file_path else "N/A")
            if session.audio_file_path and session.audio_file_path.exists():
                return FileResponse(session.audio_file_path, media_type="audio/mpeg")
            else:
                logger.warning("Audio file not found for track_id: %s at path: %s", track_id, session.audio_file_path)
                return JSONResponse({"error": "Audio file not found"}, status_code=404)
    logger.warning("Track_id %s not found in any active session.", track_id)
    return JSONResponse({"error": "Track not found or not currently playing"}, status_code=404)