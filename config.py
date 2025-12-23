import json
from pathlib import Path
from typing import List, Dict, Any
from functools import lru_cache

from pydantic import Field, model_validator, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    TEMP_DIR: Path = BASE_DIR / "temp_audio"

    # --- App Logic Settings ---
    LOG_LEVEL: str = "INFO"
    CACHE_TTL_DAYS: int = 7
    MAX_RESULTS: int = 30
    DOWNLOAD_RETRY_ATTEMPTS: int = 2

    # --- Media Constraints ---
    TRACK_MIN_DURATION_S: int = 60
    TRACK_MAX_DURATION_S: int = 900  # 15 minutes
    GENRE_MIN_DURATION_S: int = 600 # 10 minutes
    GENRE_MAX_DURATION_S: int = 18000 # 5 hours
    PLAY_MAX_FILE_SIZE_MB: int = 50

    @field_validator("ADMIN_ID_LIST", mode="before")
    @classmethod
    def _assemble_admin_ids(cls, v, info) -> List[int]:
        admin_ids_str = info.data.get("ADMIN_IDS", "")
        if not admin_ids_str:
            return []
        try:
            return [int(i.strip()) for i in admin_ids_str.split(",") if i.strip()]
        except ValueError as e:
            raise ValueError(f"Invalid ADMIN_IDS format. Could not parse '{admin_ids_str}'.") from e

    @model_validator(mode='after')
    def _load_genre_data(self) -> "Settings":
        base_dir = self.BASE_DIR
        if not base_dir:
            raise ValueError("BASE_DIR is not set, cannot locate genres.json")

        genres_path = base_dir / "genres.json"
        if not genres_path.is_file():
            raise FileNotFoundError(f"Critical file not found: {genres_path}.")
        
        try:
            with open(genres_path, "r", encoding="utf-8") as f:
                self.GENRE_DATA = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from {genres_path}: {e}") from e
        
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

@lru_cache()
def get_settings() -> Settings:
    return Settings()