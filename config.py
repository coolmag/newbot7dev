import json
from pathlib import Path
from typing import List, Dict, Any
from functools import lru_cache

from pydantic import Field, model_validator, field_validator # Updated Pydantic imports
from pydantic_settings import BaseSettings, SettingsConfigDict # New import for BaseSettings

class Settings(BaseSettings):
    # --- Basic Settings from .env ---
    BOT_TOKEN: str
    WEBHOOK_URL: str
    BASE_URL: str
    ADMIN_IDS: str = ""
    COOKIES_CONTENT: str = ""

    # --- Fields Populated by Validators ---
    ADMIN_ID_LIST: List[int] = []
    GENRE_DATA: Dict[str, Any] = {}

    # --- Path Definitions ---
    BASE_DIR: Path = Path(__file__).resolve().parent
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    CACHE_DB_PATH: Path = BASE_DIR / "cache.db"
    LOG_FILE_PATH: Path = BASE_DIR / "bot.log"
    COOKIES_FILE: Path = BASE_DIR / "cookies.txt"

    # --- App Logic Settings ---
    LOG_LEVEL: str = "INFO"
    MAX_QUERY_LENGTH: int = 150
    DOWNLOAD_TIMEOUT_S: int = 120
    MAX_RETRIES: int = 5
    RETRY_DELAY_S: float = 5.0
    MAX_RESULTS: int = 30
    
    # 🆕 Новые настройки для улучшенной стабильности
    MAX_CONCURRENT_DOWNLOADS: int = 10  # Увеличен с 3
    MAX_CONCURRENT_SEARCHES: int = 5    # Новая настройка
    SEARCH_TIMEOUT_S: int = 20          # Таймаут для поиска
    DOWNLOAD_RETRY_ATTEMPTS: int = 2    # Количество повторов
    KEEP_ALIVE_INTERVAL_S: int = 240    # Интервал keep-alive
    
    # --- Cache Settings ---
    CACHE_TTL_DAYS: int = 7
    
    # --- Media Constraints ---
    # Unified settings for track duration and file size limits
    
    # For 'track' and 'artist' search modes
    TRACK_MIN_DURATION_S: int = 60
    TRACK_MAX_DURATION_S: int = 900  # 15 minutes

    # For 'genre' search mode (can be longer, like mixes)
    GENRE_MIN_DURATION_S: int = 60
    GENRE_MAX_DURATION_S: int = 1800 # 30 minutes

    # General file size limit
    PLAY_MAX_FILE_SIZE_MB: int = 30

    @field_validator("ADMIN_ID_LIST", mode="before") # Updated to field_validator
    @classmethod
    def _assemble_admin_ids(cls, v, info) -> List[int]: # Signature changed for Pydantic v2
        """Parses the ADMIN_IDS string from environment into a list of integers."""
        admin_ids_str = info.data.get("ADMIN_IDS", "") # Access via info.data
        if not admin_ids_str:
            return []
        try:
            return [int(i.strip()) for i in admin_ids_str.split(",") if i.strip()]
        except ValueError as e:
            raise ValueError(f"Invalid ADMIN_IDS format. Could not parse '{admin_ids_str}'. Must be a comma-separated list of numbers.") from e

    @model_validator(mode='after') # Updated to model_validator
    def _load_genre_data(self) -> "Settings": # Signature changed for Pydantic v2
        """Loads genre data from genres.json, failing fast if the file is missing or invalid."""
        base_dir = self.BASE_DIR # Access via self
        if not base_dir:
            # This should not happen if BASE_DIR has its default value
            raise ValueError("BASE_DIR is not set, cannot locate genres.json")

        genres_path = base_dir / "genres.json"
        if not genres_path.is_file():
            raise FileNotFoundError(
                f"Critical file not found: {genres_path}. "
                "The application cannot start without genre definitions."
            )
        
        try:
            with open(genres_path, "r", encoding="utf-8") as f:
                self.GENRE_DATA = json.load(f) # Update self.GENRE_DATA
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from {genres_path}: {e}") from e
        
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore") # New way to define Config

@lru_cache()
def get_settings() -> Settings:
    """
    Provides a cached, validated Settings object.
    The lru_cache ensures the Settings class is instantiated only once.
    """
    return Settings()
