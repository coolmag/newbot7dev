from __future__ import annotations

import logging
from uuid import uuid4

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultArticle,
    InputTextMessageContent,
    WebAppInfo
)
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    InlineQueryHandler,
)
from telegram.error import BadRequest

from radio import RadioManager
from config import Settings, get_settings
from keyboards import get_main_menu_keyboard, get_subcategory_keyboard, get_dashboard_keyboard
from utils import resolve_path

logger = logging.getLogger("handlers")

def setup_handlers(app: Application, radio: RadioManager, settings: Settings) -> None:
    
    def get_query_from_catalog(path_str: str) -> str:
        """Ищет реальный запрос по пути."""
        path = path_str.split('|')
        current = settings.MUSIC_CATALOG
        for p in path[:-1]:
            current = current.get(p, {})
            if not isinstance(current, dict): return "top 50 hits"
        
        genre_name = path[-1]
        query = current.get(genre_name)
        if isinstance(query, dict): return "top 50 hits"
        return str(query)

    # --- Commands ---

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user.first_name
        text = f"""👋 *Привет, {user}!*
        
Я — *Cyber Radio v7*.

🎧 *Фичи:*
• Бесконечное радио без рекламы
• Умный поиск (без мусора)
• Стильный плеер (Winamp Style)

👇 *Выбери категорию:*"""
        
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu_keyboard()
        )

    async def radio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        query = " ".join(context.args) if context.args else "random"
        
        # БЕЗОПАСНЫЙ ЗАПРОС (чтобы не качать миксы на 10 часов)
        if query == "random": query = "top 50 global hits"
        
        try: await update.message.delete()
        except: pass
        
        await radio.start(chat.id, query, chat.type)

    async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.stop(update.effective_chat.id)
        msg = await update.effective_message.reply_text("🛑 *Радио остановлено.*", parse_mode=ParseMode.MARKDOWN)

    async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.skip(update.effective_chat.id)

    # --- Callbacks ---

    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        try: await query.answer()
        except: pass
        
        data = query.data
        chat_id = query.message.chat_id
        chat_type = query.message.chat.type

        if data == "main_menu":
            await query.edit_message_text(
                "💿 *Каталог жанров:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_main_menu_keyboard()
            )
        
        elif data.startswith("cat|"):
            path_hash = data.removeprefix("cat|")
            path_str = resolve_path(path_hash)
            
            # АВТО-ВОССТАНОВЛЕНИЕ: Если хэш протух, возвращаем в главное 