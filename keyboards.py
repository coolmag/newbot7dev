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
            InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_genre_keyboard() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру выбора жанра."""
    # В будущем здесь будет динамическая генерация из настроек
    keyboard = [
        [
            InlineKeyboardButton("🤘 Rock", callback_data="genre_rock"),
            InlineKeyboardButton("🕺 Pop", callback_data="genre_pop"),
            InlineKeyboardButton("🎹 Electronic", callback_data="genre_electronic"),
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
