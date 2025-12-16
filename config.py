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

    # Fallback
    RADIO_GENRES: List[str] = ["rock", "pop", "jazz", "lofi"] 

    # ==========================================
    # 🎵 МУЗЫКАЛЬНЫЙ КАТАЛОГ (ОПТИМИЗИРОВАННЫЙ)
    # ==========================================
    
    MUSIC_CATALOG: Dict[str, Any] = {
        "🎸 Рок": {
            "Классик-рок 70-х": "classic rock 70s fleetwood mac led zeppelin",
            "Хард-рок 80-х": "hard rock 80s bon jovi ac/dc guns n roses",
            "Альтернатива 90-х": "90s alternative rock nirvana pearl jam soundgarden",
            "Поп-панк 00-х": "pop punk 2000s blink-182 good charlotte green day",
            "Прогрессив-метал": "progressive metal tool dream theater opeth",
            "Современный рок": "modern rock hits foo fighters royal blood",
        },
        "🎤 Хип-хоп / R&B": {
            "Олдскул хип-хоп 80-х": "80s old school hip hop run dmc public enemy",
            "Золотая эра хип-хопа 90-х": "90s golden age hip hop a tribe called quest nas",
            "R&B 90-х": "90s r&b mariah carey tlc boyz ii men",
            "Трэп": "modern trap music Travis Scott Migos Future",
            "Дрилл": "drill music pop smoke chief keef",
            "Фонк": "phonk music cowbell drift",
            "Соул / Фанк 70-х": "70s soul funk Marvin Gaye Stevie Wonder",
        },
        "✨ Поп-музыка": {
            "Диско 70-х": "disco hits 70s Bee Gees Donna Summer ABBA",
            "Синти-поп 80-х": "synth-pop 80s depeche mode human league a-ha",
            "Поп 90-х": "90s pop hits spice girls backstreet boys britney spears",
            "Поп 00-х": "2000s pop hits beyonce justin timberlake christina aguilera",
            "Современный поп": "modern pop hits ed sheeran taylor swift billie eilish",
            "K-Pop": "k-pop hits bts blackpink twice",
        },
        "💿 По десятилетиям": {
            "Хиты 70-х": "best songs 1970s",
            "Хиты 80-х": "best songs 1980s",
            "Хиты 90-х": "best songs 1990s",
            "Хиты 00-х": "best songs 2000s",
            "Хиты 10-х": "best songs 2010s",
        },
        "🎧 Для настроения": {
            "Джаз-кафе": "jazz cafe background music",
            "Лоу-фай": "lofi hip hop radio beats to relax",
            "Акустика": "acoustic covers popular songs",
            "Эмбиент": "ambient music for studying",
            "Регги": "reggae classics bob marley",
        },
    }

def get_settings() -> Settings:
    return Settings()