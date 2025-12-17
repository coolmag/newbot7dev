import json
from pathlib import Path
from typing import List, Dict, Any
from pydantic import BaseSettings

class Settings(BaseSettings):
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    # --- Основные настройки ---
    BOT_TOKEN: str
    WEBHOOK_URL: str
    BASE_URL: str
    ADMIN_IDS: str = ""
    COOKIES_CONTENT: str = ""
    
    GENRE_DATA: Dict[str, Any] = {}

    @property
    def ADMIN_ID_LIST(self) -> List[int]:
        if not self.ADMIN_IDS: return []
        return [int(i.strip()) for i in self.ADMIN_IDS.split(",") if i.strip()]

    # --- Пути ---
    BASE_DIR: Path = Path(__file__).resolve().parent
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    CACHE_DB_PATH: Path = BASE_DIR / "cache.db"
    LOG_FILE_PATH: Path = BASE_DIR / "bot.log"
    COOKIES_FILE: Path = BASE_DIR / "cookies.txt"

    # --- Настройки ---
    LOG_LEVEL: str = "INFO"
    MAX_QUERY_LENGTH: int = 150
    DOWNLOAD_TIMEOUT_S: int = 120
    MAX_RETRIES: int = 5
    RETRY_DELAY_S: float = 5.0
    MAX_RESULTS: int = 30 
    
    # --- Кэш ---
    CACHE_TTL_DAYS: int = 7
    
    # --- Совместимость ---
    RADIO_MAX_DURATION_S: int = 900
    RADIO_MIN_DURATION_S: int = 30
    PLAY_MAX_DURATION_S: int = 900
    PLAY_MAX_FILE_SIZE_MB: int = 50

def get_settings() -> Settings:
    settings = Settings()
    genres_path = settings.BASE_DIR / "genres.json"
    if genres_path.exists():
        with open(genres_path, "r", encoding="utf-8") as f:
            settings.GENRE_DATA = json.load(f)
    else:
        # Fallback in case genres.json is missing
        settings.GENRE_DATA = {
            "genres": {
                "pop": {"name": "Pop", "search_term": "pop hits"},
                "rock": {"name": "Rock", "search_term": "rock music"},
                "hip_hop": {"name": "Hip-Hop", "search_term": "hip hop"},
            },
            "trending": {
                "searches": ["tiktok viral hits"]
            }
        }
    return settings