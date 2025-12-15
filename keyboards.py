from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.constants import ChatType
from config import get_settings

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню."""
    keyboard = [
        [
            InlineKeyboardButton("🎸 Выбрать жанр", callback_data="radio_genre"),
            InlineKeyboardButton("🎲 Случайный поток", callback_data="genre_random"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_genre_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура жанров (сетка 2xN)."""
    settings = get_settings()
    # Делаем первую букву заглавной
    buttons = [
        InlineKeyboardButton(
            text=f"📻 {genre.title()}",
            callback_data=f"genre_{genre}"
        )
        for genre in settings.RADIO_GENRES
    ]
    # Сетка 2 кнопки в ряд
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_dashboard_keyboard(base_url: str, chat_type: str, chat_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для Dashboard (активного радио).
    """
    webapp_url = f"{base_url}/webapp/?chat_id={chat_id}"
    
    if chat_type == ChatType.PRIVATE:
        webapp_btn = InlineKeyboardButton("✨ ОТКРЫТЬ CYBER PLAYER ✨", web_app=WebAppInfo(url=webapp_url))
    else:
        webapp_btn = InlineKeyboardButton("✨ ОТКРЫТЬ CYBER PLAYER ✨", url=webapp_url)

    keyboard = [
        [webapp_btn],
        [
            InlineKeyboardButton("⏮️", callback_data="noop"), 
            InlineKeyboardButton("⏹️ Стоп", callback_data="stop_radio"),
            InlineKeyboardButton("⏭️ Скип", callback_data="skip_track"),
        ],
        [
            InlineKeyboardButton("📂 Меню", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_track_keyboard(base_url: str, chat_id: int) -> InlineKeyboardMarkup:
    """
    Маленькая кнопка, которая крепится под каждым аудио-файлом.
    """
    webapp_url = f"{base_url}/webapp/?chat_id={chat_id}"
    btn = InlineKeyboardButton("🎧 Открыть плеер", url=webapp_url)
    return InlineKeyboardMarkup([[btn]])