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
from config import Settings
from keyboards import get_main_menu_keyboard, get_genre_keyboard, get_status_keyboard

logger = logging.getLogger("handlers")


async def safe_answer_callback(query, text: str | None = None) -> None:
    try:
        await query.answer(text)
    except BadRequest as e:
        msg = str(e)
        if "Query is too old" in msg or "response timeout expired" in msg or "query id is invalid" in msg:
            return
        raise

def player_markup(base_url: str, chat_type: str, chat_id: int) -> InlineKeyboardMarkup:
    """Возвращает кнопку плеера, адаптированную под тип чата."""
    webapp_url = f"{base_url}/webapp/?chat_id={chat_id}"
    if chat_type == ChatType.PRIVATE:
        btn = InlineKeyboardButton("🎧 Открыть плеер", web_app=WebAppInfo(url=webapp_url))
    else:
        btn = InlineKeyboardButton("🎧 Открыть плеер", url=webapp_url)
    return InlineKeyboardMarkup([[btn]])


def setup_handlers(app: Application, radio: RadioManager, settings: Settings) -> None:
    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        await update.effective_message.reply_text(
            "Привет! Я твой музыкальный бот.\n\n"
            "Используй /menu, чтобы открыть главное меню, или /radio <запрос>, чтобы сразу запустить радио.",
            reply_markup=player_markup(settings.BASE_URL, chat_type, chat_id)
        )

    async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "Главное меню:",
            reply_markup=get_main_menu_keyboard(),
        )

    async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id if update.effective_user else 0
        if uid not in settings.ADMIN_ID_LIST:
            await update.effective_message.reply_text("Нет доступа.")
            return
        await update.effective_message.reply_text("👑 **Админ-панель**", parse_mode="Markdown")

    async def player_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        await update.effective_message.reply_text(
            "Нажмите кнопку ниже, чтобы открыть веб-плеер:",
            reply_markup=player_markup(settings.BASE_URL, chat_type, chat_id),
        )

    async def radio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        q = " ".join(context.args).strip()
        if not q:
            q = "rock hits"
        await radio.start(update.effective_chat.id, q)
        await update.effective_message.reply_text(f"✅ Радио запущено: {q}", reply_markup=player_markup(settings.BASE_URL, update.effective_chat.type, update.effective_chat.id))

    async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.stop(update.effective_chat.id)
        await update.effective_message.reply_text("⏹ Радио остановлено.")

    async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.skip(update.effective_chat.id)
        await update.effective_message.reply_text("⏭ Ок, пропускаю…")

    async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        st = radio.status()
        s = st["sessions"].get(str(chat.id))
        if not s:
            await update.effective_message.reply_text("Радио не запущено.", reply_markup=player_markup(settings.BASE_URL, chat.type, chat.id))
            return

        current = s.get("current")
        if current:
            text = (
                f"🎶 *Сейчас в эфире:*\n" +
                f"*{current.get('title', 'N/A')}*\n" +
                f"_{current.get('artist', 'N/A')}_\n\n" +
                f"🎧 *Запрос:* `{s['query']}`\n" +
                f"⌛ *В очереди:* `{s['playlist_len']}` треков"
            )
            await update.effective_message.reply_text(
                text,
                parse_mode="Markdown",
                reply_markup=get_status_keyboard(settings.BASE_URL, chat.type, chat.id)
            )
        else:
            await update.effective_message.reply_text(
                "⏳ Подбираю следующий трек...",
                reply_markup=player_markup(settings.BASE_URL, chat.type, chat.id)
            )

    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await safe_answer_callback(query)
        data = query.data
        chat = query.message.chat
        chat_id = chat.id
        chat_type = chat.type

        if data == "main_menu":
            await query.edit_message_text(text="Главное меню:", reply_markup=get_main_menu_keyboard())
        elif data == "radio_genre":
            await query.edit_message_text(text="Выберите жанр:", reply_markup=get_genre_keyboard())
        elif data.startswith("genre_"):
            genre = data.split("_")[1]
            await radio.start(chat_id, genre)
            await query.edit_message_text(text=f"✅ Радио запущено: {genre}")
        elif data == "skip_track":
            await radio.skip(chat_id)
            await query.edit_message_text(text="⏭️ Пропускаю...")
        elif data == "stop_radio":
            await radio.stop(chat_id)
            await query.edit_message_text(text="⏹️ Радио остановлено.")
        elif data == "status":
            await query.message.delete()
            effective_update = Update(update.update_id, message=query.message)
            await status_cmd(effective_update, context)


    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("player", player_cmd))
    app.add_handler(CommandHandler("radio", radio_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("skip", skip_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
