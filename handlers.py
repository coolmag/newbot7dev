from __future__ import annotations

import logging
import asyncio
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
from telegram.error import BadRequest

from radio import RadioManager
from config import Settings
from keyboards import get_track_search_keyboard, get_genre_voting_keyboard
from youtube import YouTubeDownloader, SearchMode # Import SearchMode
from radio_voting import GenreVotingService
from models import TrackInfo

logger = logging.getLogger("handlers")

# --- Helper Functions for Genre Keyboards (No changes needed) ---
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

def setup_handlers(app: Application, radio: RadioManager, settings: Settings, downloader: YouTubeDownloader, voting_service: GenreVotingService) -> None: 
    
    # --- Command Handlers (Refactored) ---
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

    async def play_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles the /play command to search for a single track."""
        query = " ".join(context.args)
        if not query:
            await update.message.reply_text(
                "💬 Укажите название трека или имя исполнителя.\n\n"
                "Например: `/play Queen - Bohemian Rhapsody`", 
                parse_mode=ParseMode.MARKDOWN
            )
            return

        search_msg = await update.message.reply_text(
            f"🔎 Ищу: `{query}`...", 
            parse_mode=ParseMode.MARKDOWN
        )
        
        try:
            # 🆕 Добавлен таймаут
            tracks = await asyncio.wait_for(
                downloader.search(query, search_mode='track', limit=10),
                timeout=20.0
            )
        except asyncio.TimeoutError:
            await search_msg.edit_text("⏱️ Поиск занял слишком много времени. Попробуйте снова.")
            return
        except Exception as e:
            logger.error(f"Ошибка при поиске трека по команде /play: {e}", exc_info=True)
            await search_msg.edit_text("❌ Произошла ошибка во время поиска.")
            return

        if not tracks:
            await search_msg.edit_text(f"❌ Ничего не найдено по запросу: `{query}`", parse_mode=ParseMode.MARKDOWN)
            return

        # 🆕 Ограничиваем длину вывода
        text = "**Вот что я нашел. Выберите трек:**\n\n"
        for i, track in enumerate(tracks[:10], 1):  # Максимум 10
            # Обрезаем длинные названия
            title = track.title[:40] + "..." if len(track.title) > 40 else track.title
            artist = track.artist[:30] + "..." if len(track.artist) > 30 else track.artist
            text += f"{i}. `{title} - {artist}` ({track.format_duration()})\n"
        
        reply_markup = get_track_search_keyboard(tracks[:10])  # Только 10
        await search_msg.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        
    async def artist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Starts a radio session for a specific artist."""
        chat = update.effective_chat
        query = " ".join(context.args)
        
        if not query:
            await update.message.reply_text(
                "💬 Укажите имя исполнителя.\n\n"
                "Например: `/artist Rammstein`", 
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # 🆕 Валидация длины запроса
        if len(query) > 100:
            await update.message.reply_text("❌ Слишком длинное имя артиста (максимум 100 символов)")
            return
            
        display_name = f"Волна по артисту: {query}"
        
        try:
            # 🆕 Добавлено уведомление о старте
            status_msg = await update.message.reply_text(f"🎤 Запускаю радио по артисту {query}...")
            
            await radio.start(
                chat.id, 
                query, 
                chat.type, 
                search_mode='artist',  # Явно указываем режим
                display_name=display_name
            )
            
            # Удаляем статусное сообщение и команду
            try:
                await status_msg.delete()
                await update.message.delete()
            except:
                pass
                
        except Exception as e:
            logger.error(f"Ошибка запуска радио по артисту: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Не удалось запустить радио: {str(e)}")

    async def radio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Starts a radio session with a genre query."""
        chat = update.effective_chat
        query = " ".join(context.args) if context.args else "random"
        
        # 🆕 Валидация
        if len(query) > 100:
            await update.message.reply_text("❌ Слишком длинный запрос (максимум 100 символов)")
            return
        
        try:
            await update.message.delete()
        except:
            pass
        
        try:
            await radio.start(
                chat.id, 
                query, 
                chat.type, 
                search_mode='genre'  # Явно указываем режим
            )
        except Exception as e:
            logger.error(f"Ошибка запуска радио: {e}", exc_info=True)
            await update.effective_chat.send_message(f"❌ Не удалось запустить радио: {str(e)}")

    async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.stop(update.effective_chat.id)
        await update.effective_message.reply_text("🛑 *Радио остановлено.*", parse_mode=ParseMode.MARKDOWN)

    async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await radio.skip(update.effective_chat.id)

    async def vote_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        current_voting_session = voting_service.get_session(chat_id)
        if current_voting_session and current_voting_session.is_vote_in_progress:
            await update.message.reply_text(
                "📢 **Идет голосование за жанр!**",
                reply_markup=get_genre_voting_keyboard(current_voting_session.current_vote_genres, current_voting_session.votes),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("⛔ В данный момент голосование неактивно.")
    
    # --- Callback Query Handler (Refactored) ---
    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        try: await query.answer()
        except BadRequest: pass

        data = query.data
        chat_id = query.message.chat.id
        chat_type = query.message.chat.type

        if data.startswith("track_choice:"):
            track_id = data.removeprefix("track_choice:")
            await query.edit_message_text(f"⏳ Загружаю выбранный трек...", reply_markup=None)
            
            result = await downloader.download(track_id)
            if result.success:
                try:
                    with open(result.file_path, "rb") as audio_file:
                        await context.bot.send_audio(
                            chat_id=chat_id,
                            audio=audio_file,
                            title=result.track_info.title,
                            performer=result.track_info.artist,
                            duration=result.track_info.duration,
                            caption=f"Трек загружен по вашему запросу."
                        )
                    await query.message.delete()
                except Exception as e:
                    logger.error(f"Ошибка при отправке файла: {e}", exc_info=True)
                    await query.edit_message_text("❌ Ошибка при отправке файла.")
            else:
                await query.edit_message_text(f"❌ Не удалось скачать: {result.error}")
            return
            
        if data == "cancel_search":
            await query.edit_message_text("Поиск отменен.", reply_markup=None)
            return

        if data == "show_main_genres":
            try:
                # First, try to edit. If it's a text message, this is fast.
                await query.edit_message_text(
                    "💿 *Каталог жанров:*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=_generate_main_genres_keyboard(settings)
                )
            except BadRequest as e:
                # If it fails because it's a media message, delete and send new.
                if "There is no text in the message to edit" in str(e):
                    await query.message.delete()
                    await query.message.chat.send_message(
                        "💿 *Каталог жанров:*",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=_generate_main_genres_keyboard(settings)
                    )
                else:
                    # Re-raise other bad requests
                    raise e
            return

        elif data.startswith("genre_main:"):
            main_genre_key = data.removeprefix("genre_main:")
            main_genre_name = settings.GENRE_DATA.get(main_genre_key, {}).get("name", "Жанр")
            keyboard = _generate_subgenres_keyboard(settings, main_genre_key)
            if keyboard: await query.edit_message_text(f"🎶 *{main_genre_name}:*", parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        elif data.startswith("genre_sub:"):
            _, main_genre_key, subgenre_key = data.split(":")
            subgenre_name = settings.GENRE_DATA.get(main_genre_key, {}).get("subgenres", {}).get(subgenre_key, {}).get("name", "Unknown")
            search_query = _get_style_search_query(settings, main_genre_key, subgenre_key)
            # Explicitly set search_mode to 'genre'
            await radio.start(chat_id, search_query, chat_type, search_mode='genre', message_id=query.message.message_id, display_name=subgenre_name)
        elif data.startswith("vote_genre:"):
            genre_key = data.removeprefix("vote_genre:")
            user_id = query.from_user.id
            if await voting_service.register_vote(chat_id, genre_key, user_id):
                await query.answer("✅ Ваш голос принят!")
            else:
                await query.answer("⛔ Голосование уже завершено.", show_alert=True)
        
        elif data == "show_vote":
            current_voting_session = voting_service.get_session(chat_id)
            if current_voting_session and current_voting_session.is_vote_in_progress:
                try:
                    await query.message.reply_text(
                        "📢 **Идет голосование за жанр!**",
                        reply_markup=get_genre_voting_keyboard(current_voting_session.current_vote_genres, current_voting_session.votes),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except BadRequest: pass
            else:
                await query.answer("⛔ В данный момент голосование неактивно.", show_alert=True)

        elif data == "stop_radio": await radio.stop(chat_id)
        elif data == "skip_track": await radio.skip(chat_id)
        
        elif data == "cancel_menu":
            try:
                await query.message.delete()
            except BadRequest:
                # If deletion fails, edit to a closed state as a fallback
                try:
                    await query.edit_message_text("Меню закрыто.", reply_markup=None)
                except BadRequest: # If that also fails, just ignore.
                    pass
            return
            
        elif data == "noop": pass

    # --- Register Handlers (No changes needed) ---
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", start_cmd))
    app.add_handler(CommandHandler("play", play_cmd))
    app.add_handler(CommandHandler("artist", artist_cmd))
    app.add_handler(CommandHandler("vote", vote_cmd))
    app.add_handler(CommandHandler("radio", radio_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("skip", skip_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))