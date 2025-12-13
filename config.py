from pathlib import Path
from typing import List, Optional, Dict

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Обязательные переменные ---
    BOT_TOKEN: str
    WEBHOOK_URL: str  # Полный URL до /telegram
    BASE_URL: str     # https://your-domain (для WebApp ссылки)

    # --- Необязательные переменные ---
    ADMIN_IDS: str = ""
    COOKIES_CONTENT: str = ""

    @property
    def ADMIN_ID_LIST(self) -> List[int]:
        if not self.ADMIN_IDS:
            return []
        return [int(i.strip()) for i in self.ADMIN_IDS.split(",") if i.strip()]

    # --- Пути ---
    BASE_DIR: Path = Path(__file__).resolve().parent
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    CACHE_DB_PATH: Path = BASE_DIR / "cache.db"
    LOG_FILE_PATH: Path = BASE_DIR / "bot.log"
    COOKIES_FILE: Path = BASE_DIR / "cookies.txt"

    # --- Настройки логгера ---
    LOG_LEVEL: str = "INFO"

    # --- Настройки загрузчика ---
    MAX_QUERY_LENGTH: int = 150
    DOWNLOAD_TIMEOUT_S: int = 120
    MAX_CONCURRENT_DOWNLOADS: int = 2
    
    # --- Настройки для команды /play ---
    PLAY_MAX_DURATION_S: int = 720    # 12 минут
    PLAY_MIN_DURATION_S: int = 15     # 15 секунд
    PLAY_MAX_FILE_SIZE_MB: int = 45

    # --- Настройки повторных попыток ---
    MAX_RETRIES: int = 5
    RETRY_DELAY_S: float = 5.0

    # --- Настройки радио ---
    RADIO_SOURCE: str = "youtube"
    RADIO_COOLDOWN_S: int = 120
    RADIO_MAX_DURATION_S: int = 600
    RADIO_MIN_DURATION_S: int = 60
    RADIO_MIN_VIEWS: Optional[int] = None      # ← Убрал строгий фильтр
    RADIO_MIN_LIKES: Optional[int] = None      # ← Убрал строгий фильтр  
    RADIO_MIN_LIKE_RATIO: Optional[float] = None  # ← Убрал строгий фильтр
    MAX_RESULTS: int = 20  # ✅ ДОБАВЛЕНО
    
    RADIO_GENRES: List[str] = [
        "rock", "classic rock", "indie rock", "alternative rock",
        "pop", "disco", "r&b", "synth-pop",
        "soul", "funk", "jazz", "blues",
        "electronic", "house", "techno", "ambient",
        "hip-hop", "rap",
        "classical", "soundtrack",
    ]

    RADIO_MOODS: Dict[str, List[str]] = {
        "чилл": ["lofi hip-hop", "chillwave", "downtempo", "ambient"],
        "энергия": ["pop", "house", "edm", "rock"],
        "грусть": ["blues", "indie rock", "alternative rock"],
        "драйв": ["hard rock", "metal", "techno", "trance"],
    }

    # --- Настройки кэша ---
    CACHE_TTL_DAYS: int = 7


def get_settings() -> Settings:
    return Settings()