import json
from pathlib import Path
from typing import List, Dict, Any
from functools import lru_cache

from pydantic import BaseSettings, validator, root_validator

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
    
    # --- Cache Settings ---
    CACHE_TTL_DAYS: int = 7
    
    # --- Media Constraints ---
    RADIO_MAX_DURATION_S: int = 900 # Currently unused, consider removing or adapting
    RADIO_MIN_DURATION_S: int = 30 # Currently unused, consider removing or adapting

    PLAY_MAX_SONG_DURATION_S: int = 900 # Max duration for individual songs (e.g., /play command)
    PLAY_MIN_SONG_DURATION_S: int = 120 # Min duration for individual songs

    PLAY_MAX_GENRE_DURATION_S: int = 3600 # Max duration for genre mixes/compilations
    PLAY_MIN_GENRE_DURATION_S: int = 60 # Min duration for genre mixes/compilations
    
    PLAY_MAX_FILE_SIZE_MB: int = 50

    @validator("ADMIN_ID_LIST", pre=True, always=True)
    def _assemble_admin_ids(cls, v, values) -> List[int]:
        """Parses the ADMIN_IDS string from environment into a list of integers."""
        admin_ids_str = values.get("ADMIN_IDS", "")
        if not admin_ids_str:
            return []
        try:
            return [int(i.strip()) for i in admin_ids_str.split(",") if i.strip()]
        except ValueError as e:
            raise ValueError(f"Invalid ADMIN_IDS format. Could not parse '{admin_ids_str}'. Must be a comma-separated list of numbers.") from e

    @root_validator(pre=False, skip_on_failure=True)
    def _load_genre_data(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Loads genre data from genres.json, failing fast if the file is missing or invalid."""
        base_dir = values.get("BASE_DIR")
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
                values["GENRE_DATA"] = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from {genres_path}: {e}") from e
        
        return values

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

@lru_cache()
def get_settings() -> Settings:
    """
    Provides a cached, validated Settings object.
    The lru_cache ensures the Settings class is instantiated only once.
    """
    return Settings()
