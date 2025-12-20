import logging
import mimetypes
import asyncio
import httpx
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.requests import ClientDisconnect # Added this line

from telegram import Update
from telegram.ext import Application

# Local imports
from auth import get_validated_user, WebAppUser
from config import Settings
from logging_setup import setup_logging
from cache import CacheService
from youtube import YouTubeDownloader
from models import Source, TrackInfo
from radio import RadioManager
from handlers import setup_handlers
from dependencies import (
    get_settings_dep,
    get_cache_service_dep,
    get_downloader_dep,
    get_telegram_app_dep,
    get_radio_manager_dep,
)

logger = logging.getLogger(__name__)

def audio_mime_for(path: Path) -> str:
    """Guess the MIME type for a given audio file path."""
    ext = path.suffix.lower()
    if ext == ".mp3": return "audio/mpeg"
    if ext in (".m4a", ".mp4"): return "audio/mp4"
    if ext in (".webm", ".opus", ".ogg"): return "audio/webm"
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"

async def download_playlist_in_background(
    downloader: YouTubeDownloader, tracks: list[TrackInfo]
):
    """Download a list of tracks in the background without blocking."""
    logger.info(f"Starting background download for {len(tracks)} tracks.")
    for track in tracks:
        try:
            asyncio.create_task(downloader.download(track.identifier))
        except Exception as e:
            logger.error(f"Error starting background download task for {track.identifier}: {e}")

async def keep_alive_task(base_url: str):
    """A background task to prevent the service from sleeping."""
    health_url = f"{base_url.rstrip('/')}/health"
    while True:
        try:
            async with httpx.AsyncClient() as client:
                await client.get(health_url, timeout=10)
            logger.info("[Keep-Alive] Ping successful.")
        except httpx.RequestError as e:
            logger.warning(f"[Keep-Alive] Ping failed: {e}")
        except Exception as e:
            logger.error(f"[Keep-Alive] An unexpected error occurred: {e}", exc_info=True)
        
        await asyncio.sleep(240) # Sleep for 4 minutes

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context. Handles startup and shutdown events,
    initializing and cleaning up resources.
    """
    # --- Startup ---
    setup_logging()
    logger.info("Application starting up...")

    # Get singleton instances via dependency functions to "prime the pump"
    settings = get_settings_dep()
    cache = get_cache_service_dep()
    tg_app = get_telegram_app_dep()
    radio = get_radio_manager_dep()
    downloader = get_downloader_dep()

    # Start the keep-alive task
    keep_alive = asyncio.create_task(keep_alive_task(settings.BASE_URL))

    # Create necessary directories and files from settings
    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if settings.COOKIES_CONTENT:
        settings.COOKIES_FILE.write_text(settings.COOKIES_CONTENT, encoding="utf-8")

    # Initialize services that require async setup
    await cache.initialize()
    
    # Set up Telegram handlers and start the bot
    setup_handlers(tg_app, radio, settings, downloader)
    await tg_app.initialize()
    await tg_app.start()
    
    try:
        await tg_app.bot.set_my_commands([
            ("start", "🚀 Start/Menu"),
            ("play", "🎵 Найти трек"),
            ("artist", "🎤 Радио по артисту"),
            ("radio", "📻 Start Radio (Admin)"),
            ("stop", "⏹️ Стоп"),
            ("skip", "⏭️ Пропустить"),
            ("vote", "🗳️ Показать голосование"),
        ])
    except Exception as e: 
        logger.warning(f"Could not set bot commands: {e}")

    webhook_url = settings.WEBHOOK_URL.rstrip('/')
    if not webhook_url.endswith('/telegram'):
        webhook_url += '/telegram'

    await tg_app.bot.set_webhook(url=webhook_url)
    logger.info(f"✅ Bot started. Webhook set to {webhook_url}")

    yield

    # --- Shutdown ---
    logger.info("Application shutting down...")
    
    # Gracefully stop the keep-alive task
    logger.info("[Keep-Alive] Stopping keep-alive task...")
    keep_alive.cancel()
    try:
        await keep_alive
    except asyncio.CancelledError:
        logger.info("[Keep-Alive] Task successfully cancelled.")

    try: 
        await get_radio_manager_dep().stop_all()
    except Exception as e: 
        logger.warning(f"Error during radio stop: {e}")
    
    await get_telegram_app_dep().stop()
    await get_telegram_app_dep().shutdown()
    await get_cache_service_dep().close()
    logger.info("Application shutdown complete.")


app = FastAPI(lifespan=lifespan)

# --- Core Web App Routes ---

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

# --- API Routes for Web Player ---

class RadioStartRequest(BaseModel):
    chat_id: int
    query: str

@app.get("/api/radio/status")
async def radio_status(
    chat_id: str | None = None,
    radio: RadioManager = Depends(get_radio_manager_dep)
):
    full_status = radio.status()
    if chat_id and str(chat_id) in full_status.get("sessions", {}):
         return JSONResponse({"sessions": {str(chat_id): full_status["sessions"][str(chat_id)]}})
    return JSONResponse(full_status)

@app.post("/api/radio/skip")
async def skip(
    req: Request, 
    user: WebAppUser = Depends(get_validated_user),
    radio: RadioManager = Depends(get_radio_manager_dep)
):
    data = await req.json()
    if chat_id := data.get("chat_id"):
        await radio.skip(int(chat_id))
    return {"ok": True}

@app.post("/api/radio/stop")
async def stop(
    req: Request, 
    user: WebAppUser = Depends(get_validated_user),
    radio: RadioManager = Depends(get_radio_manager_dep)
):
    data = await req.json()
    if chat_id := data.get("chat_id"):
        await radio.stop(int(chat_id))
    return {"ok": True}

@app.post("/api/radio/start")
async def start_radio_from_webapp(
    req: RadioStartRequest, 
    user: WebAppUser = Depends(get_validated_user),
    radio: RadioManager = Depends(get_radio_manager_dep)
):
    await radio.start(chat_id=req.chat_id, query=req.query, chat_type="WebApp")
    return {"ok": True}

@app.get("/api/player/playlist")
async def get_player_playlist(
    query: str, 
    background_tasks: BackgroundTasks,
    downloader: YouTubeDownloader = Depends(get_downloader_dep)
):
    if not query:
        raise HTTPException(status_code=400, detail="Query parameter is required.")

    tracks = await downloader.search(query, limit=15)
    if not tracks:
        return {"playlist": []}

    # Block and wait for the FIRST track to ensure playback starts immediately
    first_track = tracks[0]
    try:
        logger.info(f"Starting blocking download for the first track: {first_track.identifier}")
        result = await downloader.download(first_track.identifier)
        if not result.success:
            logger.error(f"Failed to download the first track {first_track.identifier}: {result.error}")
            raise HTTPException(status_code=500, detail=f"Failed to process first track: {result.error}")

        logger.info(f"First track {first_track.identifier} downloaded successfully.")
    except Exception as e:
        logger.error(
            f"Failed to download the first track {first_track.identifier}: {e}. Playlist might fail.",
            exc_info=True
        )
        # Re-raise as HTTPException to inform the client
        raise HTTPException(status_code=500, detail=str(e))

    # Download the rest of the tracks in the background
    remaining_tracks = tracks[1:]
    if remaining_tracks:
        background_tasks.add_task(download_playlist_in_background, downloader, remaining_tracks)

    # Format and return the full playlist
    playlist = [
        {
            "title": track.title, "artist": track.artist, "duration": track.duration,
            "identifier": track.identifier, "url": f"/audio/{track.identifier}",
            "view_count": track.view_count, "like_count": track.like_count,
        } for track in tracks
    ]
    return {"playlist": playlist}

@app.get("/audio/{track_id}")
async def get_audio(
    track_id: str,
    cache: CacheService = Depends(get_cache_service_dep)
):
    cached_result = await cache.get(f"yt:{track_id}", Source.YOUTUBE)
    
    if cached_result and cached_result.file_path and Path(cached_result.file_path).exists():
        return FileResponse(
            cached_result.file_path,
            media_type=audio_mime_for(Path(cached_result.file_path)),
            headers={"Access-Control-Allow-Origin": "*"}
        )

    logger.warning(f"Audio file for track_id '{track_id}' not found in cache. Skipping.")
    raise HTTPException(status_code=404, detail="Track not cached or ready yet. Please try again.")

# --- Telegram Webhook ---

@app.post("/telegram")
async def webhook(
    req: Request,
    tg_app: Application = Depends(get_telegram_app_dep)
):
    """Single entry point for Telegram updates."""
    try:
        data = await req.json()
        update = Update.de_json(data, tg_app.bot)
        await tg_app.process_update(update)
    except ClientDisconnect:
        logger.warning("Client disconnected prematurely during webhook processing.")
        return {"ok": True}
    except Exception as e:
        body = await req.body()
        logger.error(
            "Error processing webhook. Body: %s, Error: %s",
            body.decode(errors="ignore"),
            e,
            exc_info=True,
        )
    return {"ok": True}
