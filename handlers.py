from __future__ import annotations

import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    CallbackQuery,
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


async def safe_answer_callback(query: CallbackQuery, text: str | None = None) -> None:
    """Безопасно отвечает на callback query, игнорируя устаревшие запросы."""
    try:
        await query.answer(text)
    except BadRequest as e:
        msg = str(e).lower()
        if any(x in msg for x in ["too old", "timeout expired", "invalid"]):
            logger.debug(f"Ignored stale callback query: {e}")
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
    """Регистрирует все обработчики команд и callback'ов."""
    
    # ─────────────────────────────────────────────────────────────
    # Вспомогательные функции
    # ─────────────────────────────────────────────────────────────
    
    def get_player_markup(chat_type: str, chat_id: int) -> InlineKeyboardMarkup:
        """Shortcut для создания player_markup с текущими настройками."""
        return player_markup(settings.BASE_URL, chat_type, chat_id)

    async def send_status(chat_id: int, chat_type: str, reply_func) -> None:
        """Общая логика отправки статуса радио."""
        st = radio.status()
        session = st["sessions"].get(str(chat_id))
        
        if not session:
            await reply_func(
                "Радио не запущено.",
                reply_markup=get_player_markup(chat_type, chat_id)
            )
            return

        current = session.get("current")
        if current:
            text = f"""🎶 *Сейчас в эфире:*
*{current.get('title', 'N/A')}*
_{current.get('artist', 'N/A')}_

🎧 *Запрос:* `{session['query']}`
⌛ *В очереди:* `{session['playlist_len']}` треков"""
            await reply_func(
                text,
                parse_mode="Markdown",
                reply_markup=get_status_keyboard(settings.BASE_URL, chat_type, chat_id)
            )
        else:
            await reply_func(
                "⏳ Подбираю следующий трек...",
                reply_markup=get_player_markup(chat_type, chat_id)
            )

    # ─────────────────────────────────────────────────────────────
    # Command Handlers
    # ─────────────────────────────────────────────────────────────

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        await update.effective_message.reply_text(
            f"""Привет! Я твой музыкальный бот.

Используй /menu, чтобы открыть главное меню, или /radio <запрос>, чтобы сразу запустить радио.""",
            reply_markup=get_player_markup(chat.type, chat.id)
        )

    async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "Главное меню:",
            reply_markup=get_main_menu_keyboard(),
        )

    async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id if update.effective_user else 0
        if uid not in settings.ADMIN_ID_LIST:
            await update.effective_message.reply_text("⛔ Нет доступа.")
            return
        await update.effective_message.reply_text(
            "👑 **Админ-панель**", 
            parse_mode="Markdown"
        )

    async def player_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        await update.effective_message.reply_text(
            "Нажмите кнопку ниже, чтобы открыть веб-плеер:",
            reply_markup=get_player_markup(chat.type, chat.id),
        )

    async def radio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        query = " ".join(context.args).strip() if context.args else "rock hits"
        
        await radio.start(chat.id, query, chat.type)
        await update.effective_message.reply_text(
            f"✅ Радио запущено: {query}",
            reply_markup=get_player_markup(chat.type, chat.id)
        )

    async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.stop(update.effective_chat.id)
        await update.effective_message.reply_text("⏹ Радио остановлено.")

    async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.skip(update.effective_chat.id)
        await update.effective_message.reply_text("⏭ Ок, пропускаю…")

    async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        await send_status(chat.id, chat.type, update.effective_message.reply_text)

    # ─────────────────────────────────────────────────────────────
    # Callback Query Handler
    # ─────────────────────────────────────────────────────────────

    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await safe_answer_callback(query)
        
        data = query.data
        chat = query.message.chat
        chat_id = chat.id
        chat_type = chat.type

        match data:
            case "main_menu":
                await query.edit_message_text(
                    text="Главное меню:",
                    reply_markup=get_main_menu_keyboard()
                )
            
            case "radio_genre":
                await query.edit_message_text(
                    text="Выберите жанр:",
                    reply_markup=get_genre_keyboard()
                )
            
            case "skip_track":
                await radio.skip(chat_id)
                await query.edit_message_text(text="⏭️ Пропускаю...")
            
            case "stop_radio":
                await radio.stop(chat_id)
                await query.edit_message_text(text="⏹️ Радио остановлено.")
            
            case "status":
                try:
                    await query.message.delete()
                except BadRequest:
                    pass
                await send_status(chat_id, chat_type, chat.send_message)
            
            case _ if data.startswith("genre_"):
                genre = data.removeprefix("genre_")
                await radio.start(chat_id, genre, chat_type)
                await query.edit_message_text(
                    text=f"✅ Радио запущено: {genre}",
                    reply_markup=get_player_markup(chat_type, chat_id)
                )
            
            case _:
                logger.warning(f"Unknown callback data: {data}")

    # ─────────────────────────────────────────────────────────────
    # Регистрация обработчиков
    # ─────────────────────────────────────────────────────────────
    
    commands = [
        ("start", start_cmd),
        ("menu", menu_cmd),
        ("admin", admin_cmd),
        ("player", player_cmd),
        ("radio", radio_cmd),
        ("stop", stop_cmd),
        ("skip", skip_cmd),
        ("status", status_cmd),
    ]
    
    for name, handler in commands:
        app.add_handler(CommandHandler(name, handler))
    
    app.add_handler(CallbackQueryHandler(button_callback))