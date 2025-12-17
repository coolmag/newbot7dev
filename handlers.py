from __future__ import annotations

import logging
import random
from typing import Optional
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
    filters, # New import
)
from telegram.error import BadRequest

from radio import RadioManager
from config import Settings, get_settings
from keyboards import get_dashboard_keyboard, get_track_keyboard

logger = logging.getLogger("handlers")

# --- Helper Functions for Genre Keyboards ---
def _generate_main_genres_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    buttons = []
    genres = settings.GENRE_DATA.get("genres", {})
    for genre_key, genre_data in genres.items():
        if "name" in genre_data and "icon" in genre_data:
            button_text = f"{genre_data['icon']} {genre_data['name']}"
            callback_data = f"genre_main:{genre_key}"
            buttons.append(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    keyboard = []
    row = []
    for button in buttons:
        row.append(button)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_menu")])

    return InlineKeyboardMarkup(keyboard)

def _generate_subgenres_keyboard(settings: Settings, main_genre_key: str) -> Optional[InlineKeyboardMarkup]:
    genres_data = settings.GENRE_DATA.get("genres", {})
    main_genre = genres_data.get(main_genre_key)

    if not main_genre or not main_genre.get("subgenres"):
        return None

    buttons = []
    subgenres = main_genre["subgenres"]
    for subgenre_key, subgenre_data in subgenres.items():
        if "name" in subgenre_data:
            button_text = subgenre_data['name']
            callback_data = f"genre_sub:{main_genre_key}:{subgenre_key}"
            buttons.append(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    keyboard = []
    for button in buttons:
        keyboard.append([button])
    
    keyboard.append([
        InlineKeyboardButton("↩️ Назад", callback_data="show_main_genres"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_menu")
    ])

    return InlineKeyboardMarkup(keyboard)

def _get_style_search_query(settings: Settings, main_genre_key: str, subgenre_key: str) -> str:
    genres_data = settings.GENRE_DATA.get("genres", {})
    main_genre = genres_data.get(main_genre_key)
    if not main_genre: return "lofi beats" # Fallback

    subgenres_data = main_genre.get("subgenres", {})
    subgenre = subgenres_data.get(subgenre_key)
    if not subgenre: return main_genre.get("search_term", main_genre["name"]) # Fallback to main genre

    styles = subgenre.get("styles", [])
    if styles:
        return random.choice(styles)
    else:
        return subgenre.get("search", subgenre["name"]) # Fallback to subgenre name


def setup_handlers(app: Application, radio: RadioManager, settings: Settings) -> None:
    
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
            reply_markup=_generate_main_genres_keyboard(settings)
        )

    async def radio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        query = " ".join(context.args) if context.args else "random"
        
        # БЕЗОПАСНЫЙ ЗАПРОС (чтобы не качать миксы на 10 часов)
        if query == "random": query = radio._get_random_style_query()
        
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
        try:
            await query.answer()
        except BadRequest as e:
            logger.warning(f"Failed to answer callback query: {e}")
        except Exception as e:
            logger.error(f"Unexpected error answering callback query: {e}")

        data = query.data
        chat_id = query.message.chat_id
        chat_type = query.message.chat.type

        data = query.data
        chat_id = query.message.chat_id
        chat_type = query.message.chat.type

        # --- New Navigation ---
        if data == "show_main_genres":
            try:
                await query.edit_message_text(
                    "💿 *Каталог жанров:*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=_generate_main_genres_keyboard(settings)
                )
            except BadRequest: pass

        elif data.startswith("genre_main:"):
            main_genre_key = data.removeprefix("genre_main:")
            main_genre_name = settings.GENRE_DATA.get("genres", {}).get(main_genre_key, {}).get("name", "Жанр")
            keyboard = _generate_subgenres_keyboard(settings, main_genre_key)
            if keyboard:
                try:
                    await query.edit_message_text(
                        f"🎶 *{main_genre_name} поджанры:*",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=keyboard
                    )
                except BadRequest: pass
            else:
                await query.edit_message_text("Поджанры не найдены.", reply_markup=None)

        elif data.startswith("genre_sub:"):
            _, main_genre_key, subgenre_key = data.split(":")
            subgenre_name = settings.GENRE_DATA.get("genres", {}).get(main_genre_key, {}).get("subgenres", {}).get(subgenre_key, {}).get("name", "Unknown")
            search_query = _get_style_search_query(settings, main_genre_key, subgenre_key)
            await radio.start(
                chat_id, 
                search_query, 
                chat_type, 
                message_id=query.message.message_id, 
                display_name=subgenre_name
            )

        # --- Radio Controls ---
        elif data == "stop_radio":
            await radio.stop(chat_id)

        elif data == "skip_track":
            await radio.skip(chat_id)
        
        elif data == "cancel_menu":
            try:
                await query.edit_message_text("Меню закрыто.", reply_markup=None)
            except BadRequest: pass
        
        elif data == "noop":
            pass # No operation, just answer the callback

    # --- Inline ---
    async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # TODO: Реализовать инлайн поиск, если нужно
        pass

    # --- Регистрация ---
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", start_cmd))
    app.add_handler(CommandHandler("radio", radio_cmd, filters.User(settings.ADMIN_ID_LIST)))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("skip", skip_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(InlineQueryHandler(inline_query_handler))