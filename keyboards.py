from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру главного меню."""
    keyboard = [
        [
            InlineKeyboardButton("🎵 Радио по жанру", callback_data="radio_genre"),
            InlineKeyboardButton("📻 Моё радио", callback_data="radio_my"),
        ],
        [
            InlineKeyboardButton("⭐️ Избранное", callback_data="favorites"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_genre_keyboard() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру выбора жанра."""
    keyboard = [
        [
            InlineKeyboardButton("🤘 Rock", callback_data="genre_rock"),
            InlineKeyboardButton("🕺 Pop", callback_data="genre_pop"),
            InlineKeyboardButton("🎹 Electronic", callback_data="genre_electronic"),
        ],
        [
            InlineKeyboardButton("🎧 Hip-Hop", callback_data="genre_hip-hop"),
            InlineKeyboardButton("🎷 Jazz", callback_data="genre_jazz"),
            InlineKeyboardButton("🧘 Lo-Fi", callback_data="genre_lofi"),
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_status_keyboard(base_url: str, chat_type: str, chat_id: int) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру для сообщения о статусе."""
    webapp_url = f"{base_url}/webapp/?chat_id={chat_id}"
    keyboard = [
        [
            InlineKeyboardButton("⏭️", callback_data="skip_track"),
            InlineKeyboardButton("⏹️", callback_data="stop_radio"),
            InlineKeyboardButton("🎧 Открыть плеер", web_app=WebAppInfo(url=webapp_url)),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

