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

    # --- Cloud Settings (for S3) ---
    S3_ENDPOINT_URL: str | None = None
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None
    S3_BUCKET_NAME: str | None = None

    # --- Path Definitions ---
    BASE_DIR: Path = Path(__file__).resolve().parent
