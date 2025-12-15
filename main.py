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
from utils import preload_paths, PATH_STORE  # <--- Импорт утилиты

logger = logging.getLogger("main")

def audio_mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".mp3":
        return "audio/mpeg"
    if ext in (".m4a", ".mp4"):
        return "audio/mp4"
    if ext in (".webm", ".opus", ".ogg"):
        return "audio/webm"
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = Settings()

    # === Инициализация меню ===
    # Это чинит проблему "Меню устарело" после перезагрузки
    preload_paths(settings.MUSIC_CATALOG)
    logger.info(f"✅ Menu paths preloaded. Total items: {len(PATH_STORE)}")

    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    if settings.COOKIES_CONTENT:
        settings.COOKIES_FILE.write_text(settings.COOKIES_CONTENT, encoding="utf-8")
        logger.info("✅ cookies.txt создан из переменной окружения.")

    cache = CacheService(settings)
    await cache.initialize()
    logger.info("Cache initialized")

    youtube_downloader = YouTubeDownloader(settings, cache)

    # Увеличиваем таймауты для Telegram API, чтобы не было httpx.ReadError
    tg_app = (
        Application.builder()
        .token(settings.BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .build()
    )

    async def on_error(update, context):
        logger.exception("PTB error: %s", context.error)

    tg_app.add_error_handler(on_error)

    radio = RadioManager(
        bot=tg_app.bot,
        settings=settings,
        downloader=youtube_downloader,
    )

    setup_handlers(tg_app, radio, settings)

    await tg_app.initialize()
    await tg_app.start()
    
    await tg_app.bot.set_my_commands([
        ("start", "🚀 Запуск/Перезапуск"),
        ("menu", "📖 Главное меню"),
        ("player", "🎧 Открыть плеер"),
        ("radio", "📻 Включить радио"),
        ("skip", "⏭️ След. трек"),
        ("stop", "⏹️ Стоп"),
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

app.mount("/webapp", StaticFiles(directory="webapp", html=True), name="webapp")

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/api/radio/status")
async def radio_status(chat_id: str | None = None):
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
async def radio_skip(req: Request):
    data = await req.json()
    chat_id = data.get("chat_id")
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id is required")
        
    logger.info(f"API: Received skip request for chat_id: {chat_id}")
    radio: RadioManager = app.state.radio
    await radio.skip(int(chat_id))
    return {"ok": True}

@app.post("/api/radio/stop")
async def radio_stop(req: Request):
    data = await req.json()
    chat_id = data.get("chat_id")
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id is required")

    logger.info(f"API: Received stop request for chat_id: {chat_id}")
    radio: RadioManager = app.state.radio
    await radio.stop(int(chat_id))
    return {"ok": True, "message": f"Radio stopped for chat_id {chat_id}"}

@app.post("/telegram")
async def telegram_webhook(req: Request):
    data = await req.json()
    tg_app: Application = app.state.tg_app
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

@app.get("/audio/{track_id}")
async def get_audio_file(track_id: str):
    # logger.info(f"Request for audio: {track_id}") # Можно отключить для чистоты логов
    radio: RadioManager = app.state.radio
    
    # Ищем трек в активных сессиях
    for session in radio._sessions.values():
        if session.current and session.current.identifier == track_id:
            if session.audio_file_path and session.audio_file_path.exists():
                file_path = session.audio_file_path
                media_type = audio_mime_for(file_path)
                return FileResponse(
                    file_path,
                    media_type=media_type,
                    headers={
                        "Cache-Control": "public, max-age=3600",
                        "Access-Control-Allow-Origin": "*"
                    }
                )
    
    raise HTTPException(status_code=404, detail="Track not found")