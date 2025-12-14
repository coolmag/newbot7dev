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
    CallbackQueryHandler,
)
from telegram.error import BadRequest

from radio import RadioManager
from config import Settings # Изменено на Settings
from keyboards import get_main_menu_keyboard, get_genre_keyboard

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


def player_markup(base_url: str, chat_type: str, chat_id: int) -> InlineKeyboardMarkup:
    webapp_url = f"{base_url}/webapp/?chat_id={chat_id}"
    if chat_type == ChatType.PRIVATE:
        btn = InlineKeyboardButton("🎧 Открыть плеер", web_app=WebAppInfo(url=webapp_url))
    else:
        # web_app в группах нельзя -> url
        btn = InlineKeyboardButton("🎧 Открыть плеер", url=webapp_url)
    return InlineKeyboardMarkup([[btn]])


def setup_handlers(app: Application, radio: RadioManager, settings: Settings) -> None: # Изменено: теперь принимаем Settings
    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "Привет! Команды:\n"
            "/player — открыть веб-плеер\n"
            "/radio <запрос> — запустить радио\n"
            "/skip — следующий трек\n"
            "/stop — остановить радио\n"
            "/status — статус\n"
            "/menu — открыть меню\n"
        )

    async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "Главное меню:",
            reply_markup=get_main_menu_keyboard(),
        )

    async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id if update.effective_user else 0
        if uid not in settings.ADMIN_ID_LIST: # Используем settings.ADMIN_ID_LIST
            await update.effective_message.reply_text("Нет доступа.")
            return
        await update.effective_message.reply_text("👑 **Админ-панель**", parse_mode="Markdown")

    async def player_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_type = update.effective_chat.type
        chat_id = update.effective_chat.id
        await update.effective_message.reply_text(
            "Нажмите кнопку ниже, чтобы открыть веб-плеер:",
            reply_markup=player_markup(settings.BASE_URL, chat_type, chat_id), # Используем settings.BASE_URL
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
        current_track_info = "нет"
        if s.get("current"):
            current = s["current"]
            current_track_info = f"{current.get('title', 'N/A')} - {current.get('artist', 'N/A')}"

        await update.effective_message.reply_text(
            "📻 Статус:\n"
            f"- query: {s['query']}\n"
            f"- current: {current_track_info}\n"
            f"- playlist: {s['playlist_len']}\n"
            f"- last_error: {s['last_error']}\n"
        )
    
    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await safe_answer_callback(query)
        data = query.data

        if data == "main_menu":
            await query.edit_message_text(text="Главное меню:", reply_markup=get_main_menu_keyboard())
        elif data == "radio_genre":
            await query.edit_message_text(text="Выберите жанр:", reply_markup=get_genre_keyboard())
        elif data.startswith("genre_"):
            genre = data.split("_")[1]
            await radio.start(update.effective_chat.id, genre)
            await query.edit_message_text(text=f"✅ Радио запущено: {genre}")


    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("player", player_cmd))
    app.add_handler(CommandHandler("radio", radio_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("skip", skip_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
