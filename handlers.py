from __future__ import annotations

import logging
import random
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
from telegram.error import BadRequest

from radio import RadioManager
from config import Settings
from keyboards import get_dashboard_keyboard, get_track_keyboard, get_genre_voting_keyboard
from models import VoteCallback # Import the new callback model

logger = logging.getLogger("handlers")

# --- Helper Functions for Genre Keyboards ---
# (These remain the same)
def _generate_main_genres_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    buttons = []
    genres = settings.GENRE_DATA
    for genre_key, genre_data in genres.items():
        if "name" in genre_data and "icon" in genre_data:
            button_text = f"{genre_data['icon']} {genre_data['name']}"
            callback_data = f"genre_main:{genre_key}"
            buttons.append(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_menu")])
    return InlineKeyboardMarkup(keyboard)

def _generate_subgenres_keyboard(settings: Settings, main_genre_key: str) -> Optional[InlineKeyboardMarkup]:
    main_genre = settings.GENRE_DATA.get(main_genre_key)
    if not main_genre or not main_genre.get("subgenres"):
        return None

    buttons = []
    subgenres = main_genre["subgenres"]
    for subgenre_key, subgenre_data in subgenres.items():
        if "name" in subgenre_data:
            button_text = subgenre_data['name']
            callback_data = f"genre_sub:{main_genre_key}:{subgenre_key}"
            buttons.append(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    keyboard = [[button] for button in buttons]
    keyboard.append([
        InlineKeyboardButton("↩️ Назад", callback_data="show_main_genres"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_menu")
    ])
    return InlineKeyboardMarkup(keyboard)

def _get_style_search_query(settings: Settings, main_genre_key: str, subgenre_key: str) -> str:
    main_genre = settings.GENRE_DATA.get(main_genre_key, {})
    subgenre = main_genre.get("subgenres", {}).get(subgenre_key, {})
    return subgenre.get("search", subgenre.get("name", "lofi beats"))

def setup_handlers(app: Application, radio: RadioManager, settings: Settings) -> None:
    
    # --- Command Handlers ---
    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user.first_name
        text = f"""👋 *Привет, {user}!*
        
Я — *Cyber Radio v7*. Я кручу музыку 24/7.

👇 *Выбери категорию или открой плеер:*"""
        
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_generate_main_genres_keyboard(settings)
        )

    async def radio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        query = " ".join(context.args) if context.args else "random"
        if query == "random": query = radio._get_random_style_query(radio._sessions.get(chat.id))
        try: await update.message.delete()
        except: pass
        await radio.start(chat.id, query, chat.type)

    async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.stop(update.effective_chat.id)
        await update.effective_message.reply_text("🛑 *Радио остановлено.*", parse_mode=ParseMode.MARKDOWN)

    async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.skip(update.effective_chat.id)

    async def vote_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles the /vote command to show the current voting poll."""
        chat_id = update.effective_chat.id
        session = radio._sessions.get(chat_id)
        if session and session.is_vote_in_progress:
            await update.message.reply_text(
                "📢 **Идет голосование за жанр!**",
                reply_markup=get_genre_voting_keyboard(session.current_vote_genres, session.votes),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("⛔ В данный момент голосование неактивно.")
    
    # --- Callback Query Handler ---
    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        try: await query.answer()
        except BadRequest: pass

        data = query.data
        chat_id = query.message.chat.id
        chat_type = query.message.chat.type

        if data == "show_main_genres":
            await query.edit_message_text("💿 *Каталог жанров:*", parse_mode=ParseMode.MARKDOWN, reply_markup=_generate_main_genres_keyboard(settings))
        elif data.startswith("genre_main:"):
            main_genre_key = data.removeprefix("genre_main:")
            main_genre_name = settings.GENRE_DATA.get(main_genre_key, {}).get("name", "Жанр")
            keyboard = _generate_subgenres_keyboard(settings, main_genre_key)
            if keyboard: await query.edit_message_text(f"🎶 *{main_genre_name}:*", parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        elif data.startswith("genre_sub:"):
            _, main_genre_key, subgenre_key = data.split(":")
            subgenre_name = settings.GENRE_DATA.get(main_genre_key, {}).get("subgenres", {}).get(subgenre_key, {}).get("name", "Unknown")
            search_query = _get_style_search_query(settings, main_genre_key, subgenre_key)
            await radio.start(chat_id, search_query, chat_type, message_id=query.message.message_id, display_name=subgenre_name)
        elif data.startswith(VoteCallback.PREFIX):
            genre_key = data.removeprefix(VoteCallback.PREFIX)
            user_id = query.from_user.id
            if await radio.register_vote(chat_id, genre_key, user_id):
                await query.answer("✅ Ваш голос принят!")
            else:
                await query.answer("⛔ Голосование уже завершено.", show_alert=True)
        elif data == "stop_radio": await radio.stop(chat_id)
        elif data == "skip_track": await radio.skip(chat_id)
        elif data == "cancel_menu": await query.edit_message_text("Меню закрыто.", reply_markup=None)
        elif data == "noop": pass

    # --- Register Handlers ---
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", start_cmd))
    app.add_handler(CommandHandler("vote", vote_cmd))
    app.add_handler(CommandHandler("radio", radio_cmd, filters.User(settings.ADMIN_ID_LIST)))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("skip", skip_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))