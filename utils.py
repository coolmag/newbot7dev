import hashlib

# Хранилище в памяти
PATH_STORE = {}

def shorten_path(path: str) -> str:
    """Сохраняет путь и возвращает короткий ключ."""
    key = hashlib.md5(path.encode()).hexdigest()[:10]
    PATH_STORE[key] = path
    return key

def resolve_path(key: str) -> str:
    """Восстанавливает путь по ключу."""
    return PATH_STORE.get(key, "")