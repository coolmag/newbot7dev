from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.constants import ChatType
from config import get_settings
from typing import List, Dict
from models import VoteCallback, TrackInfo


settings = get_settings()

def get_track_search_keyboard(tracks: List[TrackInfo]) -> InlineKeyboardMarkup:
    """
    🆕 Creates a keyboard with a list of tracks for the user to choose from.
    Improved with better layout and validation.
    """
    if not tracks:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_search")
        ]])
    
    buttons = []
    # 🆕 Ограничиваем до 10 треков максимум
    for i, track in enumerate(tracks[:10], 1):
        callback_data = f"track_choice:{track.identifier}"
        # 🆕 Проверяем длину callback_data (макс 64 байта)
        if len(callback_data.encode('utf-8')) <= 64:
            buttons.append(InlineKeyboardButton(text=str(i), callback_data=callback_data))
        else:
            logger.warning(f"Пропущен трек с длинным ID: {track.identifier}")
    
    if not buttons:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Ошибка", callback_data="cancel_search")
        ]])
    
    # 🆕 Улучшенная раскладка: 5 кнопок в ряд
    keyboard = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_search")])
    
    return InlineKeyboardMarkup(keyboard)

def get_dashboard_keyboard(base_url: str, chat_type: str, chat_id: int) -> InlineKeyboardMarkup:
    webapp_url = f"{base_url}/webapp/?chat_id={chat_id}"
    
    if chat_type == ChatType.PRIVATE:
        webapp_btn = InlineKeyboardButton("✨ ОТКРЫТЬ WINAMP ✨", web_app=WebAppInfo(url=webapp_url))
    else:
        webapp_btn = InlineKeyboardButton("✨ ОТКРЫТЬ WINAMP ✨", url=webapp_url)

    keyboard = [
        [webapp_btn],
        [
            InlineKeyboardButton("⏮️", callback_data="noop"), 
            InlineKeyboardButton("⏹️ Стоп", callback_data="stop_radio"),
            InlineKeyboardButton("⏭️ Скип", callback_data="skip_track"),
        ],
        [
            InlineKeyboardButton("📂 Каталог жанров", callback_data="show_main_genres"),
            InlineKeyboardButton("🗳️ Голосование", callback_data="show_vote")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_track_keyboard(base_url: str, chat_id: int) -> InlineKeyboardMarkup:
    webapp_url = f"{base_url}/webapp/?chat_id={chat_id}"
    btn = InlineKeyboardButton("🎧 Открыть плеер", url=webapp_url)
    return InlineKeyboardMarkup([[btn]])

def get_genre_voting_keyboard(genres_for_voting: List[str], votes: Dict[str, set] = None) -> InlineKeyboardMarkup:
    """
    Creates the keyboard for genre voting.
    Shows the vote count for each genre.
    """
    if votes is None:
        votes = {}

    buttons = []
    for genre in genres_for_voting:
        vote_count = len(votes.get(genre, []))
        text = f"{genre.capitalize()}"
        if vote_count > 0:
            text += f" [{vote_count}]"
        
        buttons.append(
            InlineKeyboardButton(text=text, callback_data=f"{VoteCallback.PREFIX}{genre}")
        )

    # Group buttons by 2 in a row
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(keyboard)