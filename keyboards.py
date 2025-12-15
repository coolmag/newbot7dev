from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.constants import ChatType
from config import get_settings

settings = get_settings()

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню категорий."""
    # Берем ключи верхнего уровня из каталога
    categories = list(settings.MUSIC_CATALOG.keys())
    
    keyboard = []
    # Строим сетку по 2 кнопки
    for i in range(0, len(categories), 2):
        row = []
        cat1 = categories[i]
        row.append(InlineKeyboardButton(cat1, callback_data=f"cat|{cat1}"))
        if i + 1 < len(categories):
            cat2 = categories[i + 1]
            row.append(InlineKeyboardButton(cat2, callback_data=f"cat|{cat2}"))
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
    
    # Спускаемся по дереву каталога
    for p in path:
        current_level = current_level.get(p, {})

    keyboard = []
    items = list(current_level.items())
    
    for i in range(0, len(items), 2):
        row = []
        name1, val1 = items[i]
        
        # Если значение - словарь, значит это еще одна папка
        if isinstance(val1, dict):
            callback1 = f"cat|{path_str}|{name1}"
            label1 = f"📂 {name1}"
        else:
            # Иначе это конечный жанр для воспроизведения
            # Используем хэш или само название, если оно короткое. 
            # Но лучше передать путь, а хендлер найдет запрос.
            callback1 = f"play_cat|{path_str}|{name1}"
            label1 = f"▶️ {name1}"
            
        row.append(InlineKeyboardButton(label1, callback_data=callback1))

        if i + 1 < len(items):
            name2, val2 = items[i+1]
            if isinstance(val2, dict):
                callback2 = f"cat|{path_str}|{name2}"
                label2 = f"📂 {name2}"
            else:
                callback2 = f"play_cat|{path_str}|{name2}"
                label2 = f"▶️ {name2}"
            row.append(InlineKeyboardButton(label2, callback_data=callback2))
            
        keyboard.append(row)

    # Кнопка "Назад"
    if '|' in path_str:
        # Если мы глубоко, возвращаемся на уровень выше
        parent_path = "|".join(path[:-1])
        back_callback = f"cat|{parent_path}"
    else:
        # Если мы на первом уровне, возвращаемся в главное меню
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