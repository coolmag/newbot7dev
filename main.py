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

def audio_mime_for(path: Path) -> str:
    """Guess the MIME type for a given audio file path."""
    ext = path.suffix.lower()
    if ext == ".mp3": return "audio/mpeg"
    if ext in (".m4a", ".mp4"): return "audio/mp4"
    if ext in (".webm", ".opus", ".ogg"): return "audio/webm"
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


async def download_playlist_in_background(
    downloader: YouTubeDownloader, 
    tracks: list[TrackInfo]
):
    """
    🆕 УЛУЧШЕННАЯ фоновая загрузка с контролем конкурентности
    """
    logger.info(f"[Background] Начало фоновой загрузки {len(tracks)} треков.")
    
    # 🆕 Ограничиваем количество одновременных загрузок
    semaphore = asyncio.Semaphore(3)  # Максимум 3 параллельно
    
    async def download_with_limit(track: TrackInfo):
        async with semaphore:
            try:
                result = await asyncio.wait_for(
                    downloader.download(track.identifier),
                    timeout=60.0
                )
                if result.success:
                    logger.debug(f"[Background] Загружен: {track.title}")
                    health_monitor.record_download(True) # 🆕 Запись успешной загрузки
                else:
                    logger.warning(f"[Background] Ошибка загрузки {track.title}: {result.error}")
                    health_monitor.record_download(False) # 🆕 Запись неуспешной загрузки
            except asyncio.TimeoutError:
                logger.warning(f"[Background] Таймаут для {track.title}")
                health_monitor.record_download(False) # 🆕 Запись неуспешной загрузки
            except Exception as e:
                logger.error(f"[Background] Ошибка для {track.title}: {e}")
                health_monitor.record_download(False) # 🆕 Запись неуспешной загрузки
    
    # Запускаем все задачи параллельно (но с ограничением через semaphore)
    await asyncio.gather(
        *[download_with_limit(track) for track in tracks],
        return_exceptions=True  # 🆕 Не останавливаемся на ошибках
    )
    
    logger.info(f"[Background] Фоновая загрузка завершена.")


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
    🆕 Улучшенный lifespan с graceful shutdown
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

    # Создаем директории
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
    
    # 🆕 Graceful остановка keep-alive
    if not keep_alive_task.done():
        keep_alive_task.cancel()
        try:
            await asyncio.wait_for(keep_alive_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        logger.info("✅ Keep-alive task stopped")

    # Остановка радио
    try: 
        await asyncio.wait_for(radio.stop_all(), timeout=10.0)
        logger.info("✅ All radio sessions stopped")
    except asyncio.TimeoutError:
        logger.warning("⚠️ Radio stop timeout")
    except Exception as e: 
        logger.warning(f"Error during radio stop: {e}")
    
    # Остановка бота
    await tg_app.stop()
    await tg_app.shutdown()
    
    # Закрытие кеша
    await db_service.close()
    
    logger.info("✅ Application shutdown complete.")


app = FastAPI(lifespan=lifespan)

# 🆕 Добавление CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Для продакшена лучше указать конкретные домены
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

# --- API Routes for Web Player ---

# 🆕 Moved health checks under /api
@app.get("/api/health")
async def health():
    return {"ok": True}

@app.get("/api/health/detailed")
async def detailed_health():
    return health_monitor.get_stats()

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
    # 🆕 Для запуска из WebApp используем режим 'genre' по умолчанию
    await radio.start(chat_id=req.chat_id, query=req.query, chat_type="WebApp", search_mode="genre")
    return {"ok": True}


@app.get("/api/player/playlist")
async def get_player_playlist(
    query: str, 
    background_tasks: BackgroundTasks,
    downloader: YouTubeDownloader = Depends(get_downloader_dep)
):
    """
    🆕 УЛУЧШЕННАЯ генерация плейлиста с прогрессивной загрузкой
    """
    if not query or len(query.strip()) == 0:
        raise HTTPException(status_code=400, detail="Query parameter is required and cannot be empty.")

    try:
        # 💡 Use 'genre' mode for broad web app queries to find mixes and compilations
        tracks = await asyncio.wait_for(
            downloader.search(query, search_mode='genre', limit=15),
            timeout=20.0
        )
        
        if not tracks:
            logger.warning(f"[Playlist] Не найдено треков для '{query}'")
            return {"playlist": [], "message": "No tracks found for this query"}

        # Блокирующая загрузка ПЕРВОГО трека
        first_track = tracks[0]
        try:
            logger.info(f"[Playlist] Блокирующая загрузка первого трека: {first_track.identifier}")
            
            result = await asyncio.wait_for(
                downloader.download(first_track.identifier),
                timeout=45.0
            )
            
            if not result.success:
                logger.error(f"[Playlist] Не удалось загрузить первый трек: {result.error}")
                # 🆕 Пробуем второй трек, если первый провалился
                if len(tracks) > 1:
                    logger.info(f"[Playlist] Пробуем второй трек как первый...")
                    second_track = tracks[1]
                    result = await asyncio.wait_for(
                        downloader.download(second_track.identifier),
                        timeout=45.0
                    )
                    if result.success:
                        # Меняем местами треки
                        tracks[0], tracks[1] = tracks[1], tracks[0]
                    else:
                        raise HTTPException(
                            status_code=500, 
                            detail="Failed to download any tracks for playback"
                        )
                else:
                    raise HTTPException(
                        status_code=500, 
                        detail=f"Failed to process first track: {result.error}"
                    )
            
            logger.info(f"[Playlist] Первый трек загружен успешно: {first_track.identifier}")
            
        except asyncio.TimeoutError:
            logger.error(f"[Playlist] Таймаут загрузки первого трека {first_track.identifier}")
            raise HTTPException(
                status_code=504,
                detail="Timeout while downloading first track. Please try again."
            )

        # Фоновая загрузка остальных треков
        remaining_tracks = tracks[1:]
        if remaining_tracks:
            logger.info(f"[Playlist] Запуск фоновой загрузки {len(remaining_tracks)} треков")
            background_tasks.add_task(
                download_playlist_in_background, 
                downloader, 
                remaining_tracks
            )

        # Формирование ответа
        playlist = [
            {
                "title": track.title, 
                "artist": track.artist, 
                "duration": track.duration,
                "identifier": track.identifier, 
                "url": f"/audio/{track.identifier}",
                "view_count": track.view_count, 
                "like_count": track.like_count,
            } for track in tracks
        ]
        
        return {
            "playlist": playlist,
            "total": len(playlist),
            "first_ready": True
        }
        
    except asyncio.TimeoutError:
        logger.error(f"[Playlist] Общий таймаут для запроса '{query}'")
        raise HTTPException(
            status_code=504,
            detail="Search timeout. Please try a more specific query."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Playlist] Критическая ошибка: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal error while generating playlist: {str(e)}"
        )


@app.get("/audio/{track_id}")
async def get_audio(
    track_id: str,
    db_service: DatabaseService = Depends(get_database_service_dep)
):
    """
    Redirects to the S3 URL for a given track_id if it's cached.
    This is used by the web player.
    """
    try:
        if not track_id or len(track_id) != 11:
            raise HTTPException(status_code=400, detail="Invalid track ID format")
        
        # Attempt to get the cached result from the database
        cached_result = await db_service.get(track_id, Source.YOUTUBE)
        
        # If we have a cached result with a URL, redirect to it
        if cached_result and cached_result.url:
            logger.info(f"[Audio] Redirecting to S3 URL for track {track_id}")
            return RedirectResponse(url=cached_result.url, status_code=307)
        
        # If the track is not cached yet, inform the client
        logger.info(f"[Audio] Track {track_id} not found in cache for streaming.")
        raise HTTPException(
            status_code=404, 
            detail={
                "error": "track_not_ready",
                "message": "Track is not cached yet or is still being processed.",
                "track_id": track_id
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Audio] Unexpected error for {track_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error while fetching audio"
        )

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
        health_monitor.record_error() # 🆕 Запись ошибки
    return {"ok": True}
