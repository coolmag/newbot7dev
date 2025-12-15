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
    
    # --- Helper: Рекурсивный поиск запроса ---
    def get_query_from_catalog(path_str: str) -> str:
        """Ищет реальный запрос по пути 'Рок|Метал|Хэви'."""
        path = path_str.split('|')
        current = settings.MUSIC_CATALOG
        
        # Идем вглубь словаря
        for p in path[:-1]:
            current = current.get(p, {})
            if not isinstance(current, dict):
                return "best music mix" # Защита от сбоев
        
        # Последний элемент - ключ конечного значения
        genre_name = path[-1]
        query = current.get(genre_name)
        
        if isinstance(query, dict):
            return "best music mix" # Если вдруг указали на папку, а не трек
        return str(query)

    # --- Commands ---

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user.first_name
        text = f"""👋 *Привет, {user}!*
        
Я — *Cyber Radio v7*.

🎧 *Возможности:*
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
        if query == "random": query = "best music mix"
        
        # Удаляем команду пользователя для чистоты (если есть права)
        try: await update.message.delete()
        except: pass
        
        await radio.start(chat.id, query, chat.type)

    async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.stop(update.effective_chat.id)
        # Отправляем сообщение, которое само исчезнет через 5 сек (чтобы не спамить)
        msg = await update.effective_message.reply_text("🛑 *Радио остановлено.*", parse_mode=ParseMode.MARKDOWN)
        # Можно добавить удаление через job_queue, но это усложнит код. Оставим так.

    async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.skip(update.effective_chat.id)

    # --- Callbacks (Меню) ---

    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        # Обязательно отвечаем на callback, чтобы часики исчезли
        try: await query.answer()
        except: pass
        
        data = query.data
        chat_id = query.message.chat_id
        chat_type = query.message.chat.type

        # 1. Главное меню
        if data == "main_menu":
            await query.edit_message_text(
                "💿 *Каталог жанров:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_main_menu_keyboard()
            )
        
        # 2. Навигация по папкам (cat|HASH)
        elif data.startswith("cat|"):
            path_hash = data.removeprefix("cat|")
            path_str = resolve_path(path_hash)
            
            if not path_str:
                await query.edit_message_text("⚠️ Меню устарело. Нажмите /start.", reply_markup=None)
                return

            folder_name = path_str.split('|')[-1]
            await query.edit_message_text(
                f"📂 *{folder_name}*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_subcategory_keyboard(path_str)
            )

        # 3. Запуск жанра (play|HASH)
        elif data.startswith("play|"):
            path_hash = data.removeprefix("play|")
            path_str = resolve_path(path_hash)
            
            if not path_str:
                await query.edit_message_text("⚠️ Меню устарело.", reply_markup=None)
                return

            search_query = get_query_from_catalog(path_str)
            
            # Удаляем меню и запускаем радио
            await query.message.delete()
            await radio.start(chat_id, search_query, chat_type)

        # 4. Управление плеером
        elif data == "stop_radio":
            await radio.stop(chat_id)
            await query.edit_message_text("🛑 *Эфир завершен.*", parse_mode=ParseMode.MARKDOWN)

        elif data == "skip_track":
            # Не меняем текст сообщения, просто шлем уведомление
            await query.answer("⏭️ Переключаю...", show_alert=False)
            await radio.skip(chat_id)
            
        elif data == "play_random":
            await query.message.delete()
            await radio.start(chat_id, "best music hits 2024 mix", chat_type)

        elif data == "noop":
            await query.answer("Это просто кнопка :)")

    # --- Inline Mode ---
    
    async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.inline_query.query.strip()
        suggestions = ["Rock", "Lo-Fi", "Phonk", "Jazz"] if not query else [query]
        results = []
        
        for term in suggestions:
            results.append(InlineQueryResultArticle(
                id=str(uuid4()),
                title=f"📻 Play: {term.capitalize()}",
                description="Нажмите для запуска радио",
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