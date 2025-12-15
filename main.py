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

    # 1. Инициализация путей меню
    preload_paths(settings.MUSIC_CATALOG)
    logger.info(f"✅ Menu paths preloaded. Total items: {len(PATH_STORE)}")

    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    if settings.COOKIES_CONTENT:
        settings.COOKIES_FILE.write_text(settings.COOKIES_CONTENT, encoding="utf-8")
        logger.info("✅ cookies.txt created.")

    # 2. Сервисы
    cache = CacheService(settings)
    await cache.initialize()
    
    youtube_downloader = YouTubeDownloader(settings, cache)

    # 3. Telegram Bot
    tg_app = (
        Application.builder()
        .token(settings.BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .build()
    )

    # Радио менеджер
    radio = RadioManager(tg_app.bot, settings, youtube_downloader)

    # 4. РЕГИСТРАЦИЯ ХЕНДЛЕРОВ (Самое важное!)
    setup_handlers(tg_app, radio, settings)
    logger.info("✅ Handlers registered.")

    # 5. Запуск бота
    await tg_app.initialize()
    await tg_app.start()
    
    try:
        await tg_app.bot.set_my_commands([
            ("start", "🚀 Главное меню"),
            ("stop", "⏹️ Остановить радио"),
            ("skip", "⏭️ След. трек"),
        ])
    except: pass

    await tg_app.bot.set_webhook(url=settings.WEBHOOK_URL)
    logger.info(f"✅ Webhook set: {settings.WEBHOOK_URL}")

    # Сохраняем в state
    app.state.settings = settings
    app.state.cache = cache
    app.state.tg_app = tg_app
    app.state.radio = radio

    yield

    # Shutdown
    try: await app.state.radio.stop_all()
    except: pass
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
    radio: RadioManager = app.state.radio
    full = radio.status()
    if chat_id and str(chat_id) in full.get("sessions", {}):
         return JSONResponse({"sessions": {str(chat_id): full["sessions"][str(chat_id)]}})
    return JSONResponse(full)

@app.post("/api/radio/skip")
async def radio_skip(req: Request):
    data = await req.json()
    chat_id = data.get("chat_id")
    if chat_id:
        await app.state.radio.skip(int(chat_id))
    return {"ok": True}

@app.post("/api/radio/stop")
async def radio_stop(req: Request):
    data = await req.json()
    chat_id = data.get("chat_id")
    if chat_id:
        await app.state.radio.stop(int(chat_id))
    return {"ok": True}

@app.post("/telegram")
async def telegram_webhook(req: Request):
    data = await req.json()
    tg_app: Application = app.state.tg_app
    # Важно: обрабатываем апдейт в контексте приложения
    await tg_app.update_queue.put(
        Update.de_json(data, tg_app.bot)
    )
    return {"ok": True}

@app.get("/audio/{track_id}")
async def get_audio_file(track_id: str):
    radio: RadioManager = app.state.radio
    for session in radio._sessions.values():
        if session.current and session.current.identifier == track_id:
            if session.audio_file_path and session.audio_file_path.exists():
                return FileResponse(
                    session.audio_file_path,
                    media_type=audio_mime_for(session.audio_file_path),
                    headers={"Access-Control-Allow-Origin": "*"}
                )
    raise HTTPException(status_code=404)