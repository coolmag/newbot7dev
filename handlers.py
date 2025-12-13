from __future__ import annotations

import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram.error import BadRequest

from radio import RadioManager
from config import Config # Добавлено: импортируем Config

logger = logging.getLogger("handlers")


async def safe_answer_callback(query, text: str | None = None) -> None:
    """
    answer_callback_query может упасть, если кнопка "старая" или бот долго думал.
    Это НЕ критично — просто игнорируем именно этот кейс.
    """
    try:
        await query.answer(text)
    except BadRequest as e:
        msg = str(e)
        if (
            "Query is too old" in msg
            or "response timeout expired" in msg
            or "query id is invalid" in msg
        ):
            return
        raise


def player_markup(base_url: str, chat_type: str) -> InlineKeyboardMarkup:
    webapp_url = f"{base_url}/webapp/"
    if chat_type == ChatType.PRIVATE:
        btn = InlineKeyboardButton("🎧 Открыть плеер", web_app=WebAppInfo(url=webapp_url))
    else:
        # web_app в группах нельзя -> url
        btn = InlineKeyboardButton("🎧 Открыть плеер", url=webapp_url)
    return InlineKeyboardMarkup([[btn]])


def setup_handlers(app: Application, radio: RadioManager, cfg: Config) -> None: # Изменено: теперь принимаем Config
    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "Привет! Команды:\n"
            "/player — открыть веб-плеер\n"
            "/radio <запрос> — запустить радио\n"
            "/skip — следующий трек\n"
            "/stop — остановить радио\n"
            "/status — статус\n"
        )

    async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id if update.effective_user else 0
        if uid != cfg.admin_id: # Используем cfg.admin_id
            await update.effective_message.reply_text("Нет доступа.")
            return
        await update.effective_message.reply_text("👑 **Админ-панель**", parse_mode="Markdown")

    async def player_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_type = update.effective_chat.type
        await update.effective_message.reply_text(
            "Нажмите кнопку ниже, чтобы открыть веб-плеер:",
            reply_markup=player_markup(cfg.base_url, chat_type), # Используем cfg.base_url
        )

    async def radio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        q = " ".join(context.args).strip()
        if not q:
            q = "rock hits"
        await radio.start(update.effective_chat.id, q)
        await update.effective_message.reply_text(f"✅ Радио запущено: {q}")

    async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.stop(update.effective_chat.id)
        await update.effective_message.reply_text("⏹ Радио остановлено.")

    async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.skip(update.effective_chat.id)
        await update.effective_message.reply_text("⏭ Ок, пропускаю…")

    async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        st = radio.status()
        s = st["sessions"].get(str(update.effective_chat.id))
        if not s:
            await update.effective_message.reply_text("Радио не запущено.")
            return
        await update.effective_message.reply_text(
            "📻 Статус:\n"
            f"- query: {s['query']}\n"
            f"- current: {s['current']}\n"
            f"- playlist: {s['playlist_len']}\n"
            f"- last_error: {s['last_error']}\n"
        )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("player", player_cmd))
    app.add_handler(CommandHandler("radio", radio_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("skip", skip_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
