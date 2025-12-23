import logging
import asyncio
import httpx
from contextlib import asynccontextmanager
from pathlib import Path
import os # Added os import

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.requests import ClientDisconnect
from fastapi.middleware.cors import CORSMiddleware # 🆕 Добавлен CORS

from telegram import Update
from telegram.ext import Application

# Local imports
from auth import get_validated_user, WebAppUser
from config import Settings
from logging_setup import setup_logging
from database import DatabaseService
from youtube import YouTubeDownloader
from models import Source, TrackInfo
from radio import RadioManager
from handlers import setup_handlers
from dependencies import (
    get_settings_dep,
    get_database_service_dep,
    get_downloader_dep,
    get_telegram_app_dep,
    get_radio_manager_dep,
    get_genre_voting_service_dep,
)
from health_check import HealthMonitor # 🆕 Добавлен HealthMonitor

logger = logging.getLogger(__name__)

# 🆕 Инициализация HealthMonitor
health_monitor = HealthMonitor()

# Obsolete functions from file-based architecture are removed.

async def keep_alive_task_func():
    """A task to ping the health check endpoint to keep the service alive on some platforms."""
    # Pinging the internal 127.0.0.1 address is more reliable than localhost.
    health_url = "http://127.0.0.1:8080/api/health"
    consecutive_failures = 0
    
    while True:
        # Wait 30 seconds on first run before starting the loop
        if consecutive_failures == 0:
            await asyncio.sleep(30)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(health_url)
                if response.status_code == 200:
                    consecutive_failures = 0
                    logger.debug("[Keep-Alive] Ping OK")
                else:
                    consecutive_failures += 1
                    logger.warning(f"[Keep-Alive] Status {response.status_code} for {health_url}")
                    health_monitor.record_error()
        except httpx.RequestError as e:
            consecutive_failures += 1
            logger.warning(f"[Keep-Alive] Ping failed for {health_url} ({consecutive_failures}): {e}")
            health_monitor.record_error()
        except Exception as e:
            consecutive_failures += 1
            logger.error(f"[Keep-Alive] Unexpected error for {health_url}: {e}", exc_info=True)
            health_monitor.record_error()
        
        # If there are many consecutive failures, increase the sleep interval.
        if consecutive_failures > 5:
            await asyncio.sleep(600)  # 10 minutes
        else:
            await asyncio.sleep(240)  # 4 minutes


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Улучшенный lifespan с graceful shutdown
    """
    # --- Startup ---
    setup_logging()
    logger.info("⚡ Application starting up...")

    settings = get_settings_dep()
    db_service = get_database_service_dep()
    tg_app = get_telegram_app_dep()
    radio = get_radio_manager_dep()
    downloader = get_downloader_dep()
    voting_service = get_genre_voting_service_dep()

    # Create the keep-alive task without passing the base_url
    keep_alive_task = asyncio.create_task(keep_alive_task_func())

    # Создаем директории (оставляем на случай, если yt-dlp что-то временно кэширует)
    settings.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if settings.COOKIES_CONTENT:
        settings.COOKIES_FILE.write_text(settings.COOKIES_CONTENT, encoding="utf-8")

    # Инициализация сервисов
    await db_service.initialize()
    
    setup_handlers(tg_app, radio, settings, downloader, voting_service)
    await tg_app.initialize()
    await tg_app.start()
    
    try:
        await tg_app.bot.set_my_commands([
            ("start", "🚀 Start/Menu"),
            ("play", "🎵 Найти трек"),
            ("artist", "🎤 Радио по артисту"),
            ("radio", "📻 Start Radio"),
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
    logger.info(f"✅ Bot started. Webhook: {webhook_url}")

    yield

    # --- Shutdown ---
    logger.info("🛑 Application shutting down...")
    
    if not keep_alive_task.done():
        keep_alive_task.cancel()
        try:
            await asyncio.wait_for(keep_alive_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        logger.info("✅ Keep-alive task stopped")

    try: 
        await asyncio.wait_for(radio.stop_all(), timeout=10.0)
        logger.info("✅ All radio sessions stopped")
    except asyncio.TimeoutError:
        logger.warning("⚠️ Radio stop timeout")
    except Exception as e: 
        logger.warning(f"Error during radio stop: {e}")
    
    await tg_app.stop()
    await tg_app.shutdown()
    await db_service.close()
    
    logger.info("✅ Application shutdown complete.")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Core Web App Routes ---

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/webapp")

app.mount("/webapp", StaticFiles(directory="webapp", html=True), name="webapp")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("webapp/favicon.svg", media_type="image/svg+xml")

# --- API Routes ---

@app.get("/api/health")
async def health():
    return {"ok": True}

@app.get("/api/health/detailed")
async def detailed_health():
    return health_monitor.get_stats()

class RadioStartRequest(BaseModel):
    chat_id: int
    query: str

@app.get("/debug/file/{video_id}")
async def debug_file(
    video_id: str,
    downloader: YouTubeDownloader = Depends(get_downloader_dep),
    settings: Settings = Depends(get_settings_dep) # Added settings to get TEMP_DIR
):
    """Debug endpoint to check downloaded file."""
    # Create a dummy TrackInfo for download_track_audio
    dummy_track_info = TrackInfo(
        identifier=video_id,
        title="Debug Track",
        artist="Debug Artist",
        duration=60, # Dummy duration
        source=Source.YOUTUBE.value
    )
    
    file_path = await downloader.download_track_audio(dummy_track_info)
    
    file_info = {
        "path": str(file_path) if file_path else None,
        "exists": file_path.is_file() if file_path else False,
        "size": file_path.stat().st_size if file_path and file_path.is_file() else 0,
        "extension": file_path.suffix if file_path else None,
        "track_info": {
            "title": dummy_track_info.title,
            "artist": dummy_track_info.artist,
            "duration": dummy_track_info.duration
        }
    }
    
    # Read first 100 bytes for format check
    if file_path and file_path.is_file():
        try:
            with open(file_path, 'rb') as f:
                file_info["first_100_bytes"] = f.read(100).hex()
        except Exception as e:
            file_info["read_error"] = str(e)
        finally:
            # Clean up the downloaded temporary file immediately after inspection
            try:
                os.unlink(file_path)
                logger.info(f"[Debug] Cleaned up temporary file: {file_path}")
            except OSError as e:
                logger.error(f"[Debug] Error cleaning up temporary file {file_path}: {e}", exc_info=True)
    
    if file_info["exists"] and file_info["size"] > 0:
        return JSONResponse(file_info)
    else:
        return JSONResponse({"error": "Failed to download or file is empty.", "details": file_info}, status_code=500)


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
    await radio.start(chat_id=req.chat_id, query=req.query, chat_type="WebApp", search_mode="genre")
    return {"ok": True}


@app.get("/api/player/playlist")
async def get_player_playlist(
    query: str,
    downloader: YouTubeDownloader = Depends(get_downloader_dep)
):
    """
    Searches for tracks and returns metadata for the web player.
    Does not download or cache anything.
    """
    if not query or len(query.strip()) == 0:
        raise HTTPException(status_code=400, detail="Query parameter is required.")

    try:
        tracks = await downloader.search(query, search_mode='genre', limit=20)
        
        if not tracks:
            return {"playlist": []}

        playlist = [
            {
                "title": track.title, 
                "artist": track.artist, 
                "duration": track.duration,
                "identifier": track.identifier, 
                "url": f"/stream/{track.identifier}", # URL points to our own stream endpoint
            } for track in tracks
        ]
        return {"playlist": playlist}
        
    except Exception as e:
        logger.error(f"[Playlist] Critical error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@app.get("/stream/{video_id}")
async def stream_audio(
    video_id: str,
    downloader: YouTubeDownloader = Depends(get_downloader_dep)
):
    """
    Gets a direct stream URL from yt-dlp and proxies the audio stream.
    This avoids storing any files on disk.
    """
    stream_result = await downloader.get_stream_info(video_id)
    if not stream_result.success:
        raise HTTPException(status_code=404, detail=stream_result.error)

    stream_url = stream_result.stream_info.stream_url

    async def stream_generator():
        """Yields chunks of the audio stream."""
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", stream_url) as response:
                if response.status_code != 200:
                    logger.error(f"Upstream audio source returned status {response.status_code}")
                    raise HTTPException(status_code=502, detail="Upstream audio source failed.")
                
                async for chunk in response.aiter_bytes():
                    yield chunk

    # yt-dlp usually provides 'audio/mp4' for bestaudio
    return StreamingResponse(stream_generator(), media_type="audio/mp4")


# --- Telegram Webhook ---

@app.post("/telegram")
async def webhook(
    req: Request,
    tg_app: Application = Depends(get_telegram_app_dep)
):
    # ... (rest of the file is the same)
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
        health_monitor.record_error()
    return {"ok": True}
