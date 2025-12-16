import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

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
from utils import preload_paths, PATH_STORE

logger = logging.getLogger("main")

def audio_mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".mp3": return "audio/mpeg"
    if ext in (".m4a", ".mp4"): return "audio/mp4"
    if ext in (".webm", ".opus", ".ogg"): return "audio/webm"
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = Settings()

    # 1. Меню
    preload_paths(settings.MUSIC_CATALOG)
    
    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if settings.COOKIES_CONTENT:
        settings.COOKIES_FILE.write_text(settings.COOKIES_CONTENT, encoding="utf-8")

    # 2. Сервисы
    cache = CacheService(settings)
    await cache.initialize()
    
    youtube = YouTubeDownloader(settings, cache)

    # 3. Telegram Bot (v21.x)
    tg_app = (
        Application.builder()
        .token(settings.BOT_TOKEN)
        .updater(None) # ВАЖНО: Отключаем встроенный Updater, так как у нас FastAPI вебхук
        .build()
    )

    radio = RadioManager(tg_app.bot, settings, youtube)
    setup_handlers(tg_app, radio, settings)

    # 4. Запуск
    await tg_app.initialize()
    await tg_app.start()
    
    try:
        await tg_app.bot.set_my_commands([
            ("start", "🚀 Меню"),
            ("stop", "⏹️ Стоп"),
            ("skip", "⏭️ Скип"),
        ])
    except Exception as e: 
        logger.warning(f"Could not set bot commands: {e}")

    webhook_url_with_path = f"{settings.WEBHOOK_URL.rstrip('/')}/telegram"
    await tg_app.bot.set_webhook(url=webhook_url_with_path)
    logger.info(f"✅ Bot started on {webhook_url_with_path}")

    # State
    app.state.tg_app = tg_app
    app.state.radio = radio

    yield

    try: 
        await radio.stop_all()
    except Exception as e: 
        logger.warning(f"Error during radio stop: {e}")
    
    await tg_app.stop()
    await tg_app.shutdown()
    await cache.close()


app = FastAPI(lifespan=lifespan)

app.mount("/webapp", StaticFiles(directory="webapp", html=True), name="webapp")

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/api/radio/status")
async def radio_status(chat_id: str | None = None):
    radio = app.state.radio
    full = radio.status()
    if chat_id and str(chat_id) in full.get("sessions", {}):
         return JSONResponse({"sessions": {str(chat_id): full["sessions"][str(chat_id)]}})
    return JSONResponse(full)

@app.post("/api/radio/skip")
async def skip(req: Request):
    data = await req.json()
    if chat_id := data.get("chat_id"):
        await app.state.radio.skip(int(chat_id))
    return {"ok": True}

@app.post("/api/radio/stop")
async def stop(req: Request):
    data = await req.json()
    if chat_id := data.get("chat_id"):
        await app.state.radio.stop(int(chat_id))
    return {"ok": True}

@app.post("/telegram")
async def webhook(req: Request):
    """Единственная точка входа для Telegram."""
    data = await req.json()
    tg_app = app.state.tg_app
    
    # Обрабатываем обновление вручную
    try:
        update = Update.de_json(data, tg_app.bot)
        await tg_app.process_update(update)
    except Exception as e:
        logger.error(f"Update error: {e}")
        
    return {"ok": True}

@app.get("/audio/{track_id}")
async def get_audio(track_id: str):
    radio = app.state.radio
    for s in radio._sessions.values():
        if s.current and s.current.identifier == track_id:
            if s.audio_file_path and s.audio_file_path.exists():
                return FileResponse(
                    s.audio_file_path,
                    media_type=audio_mime_for(s.audio_file_path),
                    headers={"Access-Control-Allow-Origin": "*"}
                )
    raise HTTPException(status_code=404)