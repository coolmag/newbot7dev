from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.constants import ChatType
from config import get_settings

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру главного меню."""
    keyboard = [
        [
            InlineKeyboardButton("🎵 Радио по жанру", callback_data="radio_genre"),
            InlineKeyboardButton("⭐️ Избранное", callback_data="favorites"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_genre_keyboard() -> InlineKeyboardMarkup:
    """Динамически создает клавиатуру для выбора жанра радио."""
    settings = get_settings()
    buttons = [
        InlineKeyboardButton(
            text=genre.capitalize(),
            callback_data=f"genre_{genre}"
        )
        for genre in settings.RADIO_GENRES
    ]
    # Группируем кнопки по 3 в ряд для лучшего вида
    keyboard = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_status_keyboard(base_url: str, chat_type: str, chat_id: int) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру для сообщения о статусе."""
    webapp_url = f"{base_url}/webapp/?chat_id={chat_id}"
    if chat_type == ChatType.PRIVATE:
        player_button = InlineKeyboardButton("🎧 Открыть плеер", web_app=WebAppInfo(url=webapp_url))
    else:
        player_button = InlineKeyboardButton("🎧 Открыть плеер", url=webapp_url)
        
    keyboard = [
        [
            InlineKeyboardButton("⏭️", callback_data="skip_track"),
            InlineKeyboardButton("⏹️", callback_data="stop_radio"),
        ],
        [
            player_button
        ]
    ]
    return InlineKeyboardMarkup(keyboard)