from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from telegram import Update
from telegram.ext import Application

from config import Config
from logging_setup import setup_logging
from cache import Cache
from radio import RadioManager
from handlers import setup_handlers

logger = logging.getLogger("main")


def _write_cookies_if_present(cfg: Config) -> None:
    raw = os.getenv(cfg.cookies_txt_env)
    if not raw:
        return
    Path(cfg.cookies_path).write_text(raw, encoding="utf-8")
    logger.info("✅ cookies.txt создан из переменной окружения (%s).", cfg.cookies_txt_env)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    cfg = Config.from_env()

    _write_cookies_if_present(cfg)

    cache = Cache("cache.sqlite3")
    await cache.initialize()
    logger.info("Cache initialized")

    tg_app = Application.builder().token(cfg.bot_token).build()

    # error handler чтобы видеть реальные причины
    async def on_error(update, context):
        logger.exception("PTB error: %s", context.error)

    tg_app.add_error_handler(on_error)

    radio = RadioManager(
        bot=tg_app.bot,
        cfg=cfg, # Изменено: передаем cfg
    )

    setup_handlers(tg_app, radio, cfg) # Изменено: передаем cfg

    await tg_app.initialize()
    await tg_app.start()

    # Установка вебхука
    await tg_app.bot.set_webhook(url=cfg.webhook_url)
    logger.info("✅ Webhook set to: %s", cfg.webhook_url)

    # сохраняем в app.state
    app.state.cfg = cfg
    app.state.cache = cache
    app.state.tg_app = tg_app
    app.state.radio = radio

    yield

    # shutdown
    try:
        await app.state.radio.stop_all()  # если вдруг добавишь (см. ниже)
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