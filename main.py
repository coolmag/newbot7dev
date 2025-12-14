from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import BaseModel
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from telegram import Update
from telegram.ext import Application

from config import Settings
from logging_setup import setup_logging
from cache import CacheService
from youtube import YouTubeDownloader
from radio import RadioManager
from handlers import setup_handlers

logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = Settings()

    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    if settings.COOKIES_CONTENT:
        settings.COOKIES_FILE.write_text(settings.COOKIES_CONTENT, encoding="utf-8")
        logger.info("✅ cookies.txt создан из переменной окружения.")

    cache = CacheService(settings)
    await cache.initialize()
    logger.info("Cache initialized")

    youtube_downloader = YouTubeDownloader(settings, cache)

    tg_app = Application.builder().token(settings.BOT_TOKEN).build()

    async def on_error(update, context):
        logger.exception("PTB error: %s", context.error)

    tg_app.add_error_handler(on_error)

    radio = RadioManager(
        bot=tg_app.bot,
        settings=settings,
        youtube_downloader=youtube_downloader,
    )

    setup_handlers(tg_app, radio, settings)

    await tg_app.initialize()
    await tg_app.start()
    
    await tg_app.bot.set_my_commands([
        ("start", "🚀 Запуск/Перезапуск"),
        ("menu", "📖 Главное меню"),
        ("player", "🎧 Открыть веб-плеер"),
        ("radio", "📻 Включить радио с запросом"),
        ("skip", "⏭️ Следующий трек"),
        ("stop", "⏹️ Остановить радио"),
        ("status", "📊 Статус радио"),
    ])

    await tg_app.bot.set_webhook(url=settings.WEBHOOK_URL)
    logger.info("✅ Webhook set to: %s", settings.WEBHOOK_URL)

    app.state.settings = settings
    app.state.cache = cache
    app.state.tg_app = tg_app
    app.state.radio = radio
    app.state.youtube_downloader = youtube_downloader

    yield

    try:
        await app.state.radio.stop_all()
    except Exception:
        pass
    await tg_app.stop()
    await tg_app.shutdown()
    await cache.close()


app = FastAPI(lifespan=lifespan)

class ChatIdPayload(BaseModel):
    chat_id: str # Изменено с int на str

app.mount("/webapp", StaticFiles(directory="webapp", html=True), name="webapp")

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/api/radio/status")
async def radio_status(chat_id: str | None = None): # Изменено с int на str
    radio: RadioManager = app.state.radio
    full_status = radio.status()
    if chat_id:
        chat_id_str = str(chat_id)
        if chat_id_str in full_status.get("sessions", {}):
             return JSONResponse({"sessions": {chat_id_str: full_status["sessions"][chat_id_str]}})
        else:
             return JSONResponse({"sessions": {}})
    return JSONResponse(full_status)

@app.post("/api/radio/skip")
async def radio_skip(payload: ChatIdPayload):
    logger.info(f"API: Received skip request for chat_id: {payload.chat_id}")
    radio: RadioManager = app.state.radio
    await radio.skip(int(payload.chat_id)) # Преобразуем обратно в int
    return {"ok": True}

@app.post("/api/radio/stop")
async def radio_stop(payload: ChatIdPayload):
    logger.info(f"API: Received stop request for chat_id: {payload.chat_id}")
    radio: RadioManager = app.state.radio
    await radio.stop(int(payload.chat_id)) # Преобразуем обратно в int
    return {"ok": True, "message": f"Radio stopped for chat_id {payload.chat_id}"}

@app.post("/telegram")
async def telegram_webhook(req: Request):
    data = await req.json()
    tg_app: Application = app.state.tg_app
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.get("/audio/{track_id}")
async def get_audio_file(track_id: str):
    logger.info(f"Request for audio file with track_id: {track_id}")
    radio: RadioManager = app.state.radio
    for session in radio._sessions.values():
        if session.current and session.current.identifier == track_id:
            logger.info(f"Found session for track_id {track_id}. Path: {session.audio_file_path}")
            if session.audio_file_path and session.audio_file_path.exists():
                logger.info(f"Serving file: {session.audio_file_path}")
                return FileResponse(session.audio_file_path, media_type="audio/mpeg")
            else:
                logger.error(f"Audio file link exists, but file not found on disk for track_id: {track_id} at path: {session.audio_file_path}")
                raise HTTPException(status_code=404, detail="Audio file not found on disk, it might have been cleaned up.")
    
    logger.error(f"Track_id {track_id} not found in any active session.")
    raise HTTPException(status_code=404, detail="Track not found or not currently playing")