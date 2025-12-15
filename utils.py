import hashlib
from typing import Dict, Any

# Глобальное хранилище путей (Хэш -> Путь)
PATH_STORE = {}

def shorten_path(path: str) -> str:
    """
    Генерирует стабильный хэш для пути (например 'Rock|Metal').
    Хэш всегда одинаковый для одной и той же строки.
    """
    return hashlib.md5(path.encode()).hexdigest()[:10]

def resolve_path(key: str) -> str:
    """
    Восстанавливает полный путь по хэшу.
    Если бота перезагрузили, preload_paths восстановит этот словарь.
    """
    return PATH_STORE.get(key, "")

def preload_paths(catalog: Dict[str, Any], parent_path: str = ""):
    """
    Рекурсивно проходит по каталогу и сохраняет все возможные пути в память.
    Вызывается при старте бота.
    """
    for key, value in catalog.items():
        # Текущий путь (например "Рок" или "Рок|Метал")
        current_path = f"{parent_path}|{key}" if parent_path else key
        
        # Генерируем хэш и сохраняем в память
        path_hash = shorten_path(current_path)
        PATH_STORE[path_hash] = current_path
        
        # Если это папка (словарь), идем глубже
        if isinstance(value, dict):
            preload_paths(value, current_path)