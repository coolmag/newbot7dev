import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from telegram import Update
from telegram.ext import Application

from auth import get_validated_user, WebAppUser
from config import get_settings, Settings
from logging_setup import setup_logging
from cache import CacheService
from youtube import YouTubeDownloader
from models import Source
from radio import RadioManager
from handlers import setup_handlers

logger = logging.getLogger("main")

class RadioStartRequest(BaseModel): # New Pydantic model
    chat_id: int
    query: str

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
    settings = get_settings()

    # 1. Меню
    # preload_paths(settings.MUSIC_CATALOG) # Removed as MUSIC_CATALOG is now dynamic
 # Note: MUSIC_CATALOG is removed from config.py

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
            ("start", "🚀 Старт"),
            ("menu", "💿 Каталог жанров"),
            ("radio", "📻 Включить радио (только админ)"),
            ("stop", "⏹️ Стоп"),
            ("skip", "⏭️ Скип"),
        ])
    except Exception as e: 
        logger.warning(f"Could not set bot commands: {e}")

    webhook_url = settings.WEBHOOK_URL.rstrip('/')
    if not webhook_url.endswith('/telegram'):
        webhook_url += '/telegram'

    await tg_app.bot.set_webhook(url=webhook_url)
    logger.info(f"✅ Bot started on {webhook_url}")

    # State
    app.state.tg_app = tg_app
    app.state.radio = radio
    app.state.settings = settings
    app.state.cache = cache
    app.state.downloader = youtube

    yield

    try: 
        await radio.stop_all()
    except Exception as e: 
        logger.warning(f"Error during radio stop: {e}")
    
    await tg_app.stop()
    await tg_app.shutdown()
    await cache.close()


app = FastAPI(lifespan=lifespan)

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/webapp")

app.mount("/webapp", StaticFiles(directory="webapp", html=True), name="webapp")

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("webapp/favicon.svg", media_type="image/svg+xml")


@app.get("/api/radio/status")
async def radio_status(chat_id: str | None = None):
    radio = app.state.radio
    full = radio.status()
    if chat_id and str(chat_id) in full.get("sessions", {}):
         return JSONResponse({"sessions": {str(chat_id): full["sessions"][str(chat_id)]}})
    return JSONResponse(full)

@app.post("/api/radio/skip")
async def skip(req: Request, user: WebAppUser = Depends(get_validated_user)):
    data = await req.json()
    if chat_id := data.get("chat_id"):
        await app.state.radio.skip(int(chat_id))
    return {"ok": True}

@app.post("/api/radio/stop")
async def stop(req: Request, user: WebAppUser = Depends(get_validated_user)):
    data = await req.json()
    if chat_id := data.get("chat_id"):
        await app.state.radio.stop(int(chat_id))
    return {"ok": True}

@app.post("/api/radio/start")
async def start_radio_from_webapp(req: RadioStartRequest, user: WebAppUser = Depends(get_validated_user)):
    radio = app.state.radio
    await radio.start(chat_id=req.chat_id, query=req.query, chat_type="WebApp")
    return {"ok": True}

async def download_playlist_in_background(downloader: YouTubeDownloader, tracks: list[TrackInfo]):
    logger.info(f"Запуск фоновой загрузки для {len(tracks)} треков.")
    for track in tracks:
        try:
            # Мы не ждем окончания каждой загрузки, а просто запускаем их
            asyncio.create_task(downloader.download(track.identifier))
        except Exception as e:
            logger.error(f"Ошибка при запуске задачи фоновой загрузки для {track.identifier}: {e}")

@app.get("/api/player/playlist")
async def get_player_playlist(query: str, background_tasks: BackgroundTasks):
    downloader: YouTubeDownloader = app.state.downloader
    if not query:
        raise HTTPException(status_code=400, detail="Query parameter is required.")
    
    tracks = await downloader.search(query, limit=15) # Уменьшим лимит для ускорения
    
    # Запускаем загрузку в фоне
    background_tasks.add_task(download_playlist_in_background, downloader, tracks)
    
    # Преобразуем TrackInfo объекты в словари для JSON
    playlist = []
    for track in tracks:
        playlist.append({
            "title": track.title,
            "artist": track.artist,
            "duration": track.duration,
            "identifier": track.identifier,
            "url": f"/audio/{track.identifier}",
            "view_count": track.view_count,
            "like_count": track.like_count
        })
    
    return {"playlist": playlist}

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
    cache: CacheService = app.state.cache
    
    # 1. Проверяем кэш на наличие пути к файлу
    cached_result = await cache.get(f"yt:{track_id}", Source.YOUTUBE)
    
    # 2. Проверяем, существует ли сам файл по этому пути
    if cached_result and cached_result.file_path and Path(cached_result.file_path).exists():
        return FileResponse(
            cached_result.file_path,
            media_type=audio_mime_for(Path(cached_result.file_path)),
            headers={"Access-Control-Allow-Origin": "*"}
        )

    # 3. Если в кэше нет или файл был удален, возвращаем 404
    # Это заставит фронтенд пропустить трек и попробовать следующий
    logger.warning(f"Аудиофайл для track_id '{track_id}' не найден в кэше. Пропускаем.")
    raise HTTPException(status_code=404, detail="Track not cached or ready yet. Please try again.")