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

logger = logging.getLogger("handlers")

def setup_handlers(app: Application, radio: RadioManager, settings: Settings) -> None:
    
    # --- Helpers ---
    def get_query_from_catalog(path_str: str, genre_name: str) -> str:
        """Ищет реальный поисковый запрос в словаре по пути."""
        path = path_str.split('|')
        current = settings.MUSIC_CATALOG
        for p in path:
            current = current.get(p, {})
        
        # Получаем конечный запрос
        query = current.get(genre_name)
        if not query or isinstance(query, dict):
            return "best music 2024" # Fallback
        return query

    # --- Commands ---

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user.first_name
        text = f"""👋 *Привет, {user}!*
        
Я — *Cyber Radio v7*. 

🎧 *Фичи:*
• Бесконечный поток музыки
• Умный поиск без мусора
• WebApp плеер в стиле Winamp

Выбери категорию ниже 👇"""
        
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu_keyboard()
        )

    async def radio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        query = " ".join(context.args) if context.args else "random"
        if query == "random": query = "best music mix"
        await radio.start(chat.id, query, chat.type)

    async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.stop(update.effective_chat.id)

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

        # 1. Главное меню
        if data == "main_menu":
            await query.edit_message_text(
                "💿 *Музыкальный каталог:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_main_menu_keyboard()
            )
        
        # 2. Навигация по папкам (cat|Рок|Метал)
        elif data.startswith("cat|"):
            path_str = data.removeprefix("cat|")
            # Название текущей папки - последнее в пути
            folder_name = path_str.split('|')[-1]
            
            await query.edit_message_text(
                f"📂 *Категория:* {folder_name}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_subcategory_keyboard(path_str)
            )

        # 3. Запуск жанра (play_cat|Рок|Метал|Хэви)
        elif data.startswith("play_cat|"):
            # Формат: play_cat|ПУТЬ_К_ПАПКЕ|ИМЯ_ЖАНРА
            parts = data.split('|')
            genre_name = parts[-1]       # Последний элемент - имя жанра
            path_str = "|".join(parts[1:-1]) # Всё, что посередине - путь к папке
            
            # Достаем реальный запрос из конфига
            search_query = get_query_from_catalog(path_str, genre_name)
            
            await query.message.delete()
            await radio.start(chat_id, search_query, chat_type)

        # 4. Управление
        elif data == "stop_radio":
            await radio.stop(chat_id)
            await query.edit_message_text("🛑 *Эфир завершен.*", parse_mode=ParseMode.MARKDOWN)

        elif data == "skip_track":
            await query.message.edit_text("⏭️ *Ищем следующий трек...*", parse_mode=ParseMode.MARKDOWN)
            await radio.skip(chat_id)
            
        elif data == "play_random":
            await query.message.delete()
            await radio.start(chat_id, "best music hits mix", chat_type)

    # --- Inline ---
    async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.inline_query.query.strip()
        suggestions = ["Rock", "Lo-Fi", "Phonk", "Jazz"] if not query else [query]
        results = []
        for term in suggestions:
            results.append(InlineQueryResultArticle(
                id=str(uuid4()),
                title=f"📻 Play: {term.capitalize()}",
                description="Click to start radio",
                input_message_content=InputTextMessageContent(f"/radio {term}"),
                thumbnail_url="https://cdn-icons-png.flaticon.com/512/3075/3075977.png"
            ))
        await update.inline_query.answer(results, cache_time=0)

    # --- Register ---
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", start_cmd))
    app.add_handler(CommandHandler("radio", radio_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("skip", skip_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(InlineQueryHandler(inline_query))