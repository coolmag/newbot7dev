from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.constants import ChatType
from config import get_settings
from utils import shorten_path

settings = get_settings()

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню категорий."""
    categories = list(settings.MUSIC_CATALOG.keys())
    
    keyboard = []
    for i in range(0, len(categories), 2):
        row = []
        cat1 = categories[i]
        row.append(InlineKeyboardButton(cat1, callback_data=f"cat|{shorten_path(cat1)}"))
        if i + 1 < len(categories):
            cat2 = categories[i + 1]
            row.append(InlineKeyboardButton(cat2, callback_data=f"cat|{shorten_path(cat2)}"))
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton("🎲 Случайный микс", callback_data="play_random")])
    return InlineKeyboardMarkup(keyboard)

def get_subcategory_keyboard(path_str: str) -> InlineKeyboardMarkup:
    """
    Строит меню для подкатегории.
    path_str: путь к категории, разделенный '|', например "Электроника|Drum & Bass"
    """
    path = path_str.split('|')
    current_level = settings.MUSIC_CATALOG
    
    for p in path:
        current_level = current_level.get(p, {})

    keyboard = []
    items = list(current_level.items())
    
    for i in range(0, len(items), 2):
        row = []
        name1, val1 = items[i]
        
        full_path1 = f"{path_str}|{name1}"
        if isinstance(val1, dict):
            callback1 = f"cat|{shorten_path(full_path1)}"
            label1 = f"📂 {name1}"
        else:
            callback1 = f"play_cat|{shorten_path(full_path1)}"
            label1 = f"▶️ {name1}"
            
        row.append(InlineKeyboardButton(label1, callback_data=callback1))

        if i + 1 < len(items):
            name2, val2 = items[i+1]
            full_path2 = f"{path_str}|{name2}"
            if isinstance(val2, dict):
                callback2 = f"cat|{shorten_path(full_path2)}"
                label2 = f"📂 {name2}"
            else:
                callback2 = f"play_cat|{shorten_path(full_path2)}"
                label2 = f"▶️ {name2}"
            row.append(InlineKeyboardButton(label2, callback_data=callback2))
            
        keyboard.append(row)

    if '|' in path_str:
        parent_path = "|".join(path[:-1])
        back_callback = f"cat|{shorten_path(parent_path)}"
    else:
        back_callback = "main_menu"
        
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=back_callback)])
    
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
        [InlineKeyboardButton("📂 Каталог жанров", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_track_keyboard(base_url: str, chat_id: int) -> InlineKeyboardMarkup:
    webapp_url = f"{base_url}/webapp/?chat_id={chat_id}"
    btn = InlineKeyboardButton("🎧 Открыть плеер", url=webapp_url)
    return InlineKeyboardMarkup([[btn]])