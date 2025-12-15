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
from config import Settings
from keyboards import get_main_menu_keyboard, get_genre_keyboard, get_dashboard_keyboard

logger = logging.getLogger("handlers")

def setup_handlers(app: Application, radio: RadioManager, settings: Settings) -> None:
    
    # --- Commands ---

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Приветствие + Меню."""
        user = update.effective_user.first_name
        text = f"""👋 *Привет, {user}!*
        
Я — *Cyber Radio v7*. Я превращу этот чат в бесконечную радиостанцию.

🎧 *Возможности:*
• Бесконечный поток музыки без рекламы
• WebApp плеер с визуализацией
• Поддержка фонового режима

Нажми кнопку ниже, чтобы начать 👇"""
        
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu_keyboard()
        )

    async def radio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Быстрый запуск: /radio rock."""
        chat = update.effective_chat
        query = " ".join(context.args) if context.args else "random"
        
        if query == "random":
            query = "best music mix"
            
        await radio.start(chat.id, query, chat.type)
        # Dashboard отправится внутри radio.start, здесь ничего слать не надо

    async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.stop(update.effective_chat.id)

    async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.skip(update.effective_chat.id)

    # --- Callbacks (Кнопки) ---

    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        try: await query.answer()
        except: pass
        
        data = query.data
        chat_id = query.message.chat_id
        chat_type = query.message.chat.type

        if data == "main_menu":
            await query.edit_message_text(
                "💿 *Выбери волну:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_main_menu_keyboard()
            )
        
        elif data == "radio_genre":
            await query.edit_message_text(
                "🎹 *Доступные жанры:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_genre_keyboard()
            )

        elif data.startswith("genre_"):
            genre = data.replace("genre_", "")
            if genre == "random": 
                genre = "best music 2024"
            
            # Удаляем меню, чтобы не мешало дашборду
            await query.message.delete()
            await radio.start(chat_id, genre, chat_type)

        elif data == "stop_radio":
            await radio.stop(chat_id)
            await query.edit_message_text("🛑 *Эфир завершен.*", parse_mode=ParseMode.MARKDOWN)

        elif data == "skip_track":
            await query.message.edit_text("⏭️ *Ищем следующий трек...*", parse_mode=ParseMode.MARKDOWN)
            await radio.skip(chat_id)

    # --- Inline Mode (Поиск в любом чате) ---

    async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка @BotName text"""
        query = update.inline_query.query.strip()
        
        if not query:
            # Если пусто, предлагаем популярные
            suggestions = ["Rock", "Lo-Fi", "Pop", "Jazz"]
        else:
            suggestions = [query]

        results = []
        for term in suggestions:
            results.append(
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"📻 Запустить радио: {term.capitalize()}",
                    description="Нажмите, чтобы включить бесконечный поток этой музыки",
                    input_message_content=InputTextMessageContent(
                        f"/radio {term}" # Это отправится в чат и триггернет команду
                    ),
                    thumbnail_url="https://cdn-icons-png.flaticon.com/512/3075/3075977.png"
                )
            )

        await update.inline_query.answer(results, cache_time=0)

    # --- Registration ---

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", start_cmd)) # Алиас
    app.add_handler(CommandHandler("radio", radio_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("skip", skip_cmd))
    
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(InlineQueryHandler(inline_query))