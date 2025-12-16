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
        "🔥 Топ-чарты": {
            "Global Top 50": "top 50 global official playlist",
            "Viral Hits": "tiktok viral hits playlist",
        },
        "🎶 По настроению": {
            "🏃‍♂️ Тренировка": "gym workout music motivational",
            "☕️ Чилаут": "chill lofi hip hop beats to relax",
            "🎉 Вечеринка": "party hits playlist pop dance",
            "❤️ Романтика": "romantic love songs playlist",
            "😢 Грусть": "sad songs for broken hearts playlist",
        },
        "📅 По десятилетиям": {
            "🕺 80-е": "80s greatest hits",
            "🎸 90-е": "90s greatest hits",
            "✨ 00-е": "2000s greatest hits",
            "📱 10-е": "2010s greatest hits",
        },
        "🎸 Рок": {
            "Classic Rock": "classic rock anthems 70s 80s",
            "Hard Rock & Metal": "hard rock heavy metal playlist",
            "Alternative & Indie": "90s 2000s alternative rock indie",
            "Punk Rock": "punk rock classics ramones misfits",
        },
        "🎤 Хип-хоп": {
            "Old-School 80s & 90s": "old school hip hop 80s 90s",
            "Golden Age": "90s boom bap hip hop wu-tang nas",
            "Modern Trap": "trap music playlist migos drake",
            "R&B Classics": "90s 2000s r&b classics",
        },
        "🎧 Электроника": {
            "House": "deep house playlist",
            "Techno": "techno club mix playlist",
            "Trance": "vocal trance anthems",
            "Drum & Bass": "liquid drum & bass mix",
        },
        "✨ Поп": {
            "80s Synth-Pop": "synth-pop 80s hits depeche mode",
            "90s & 00s Pop": "90s 2000s pop hits playlist",
            "Modern Pop": "today's top pop hits",
        },
    }

def get_settings() -> Settings:
    return Settings()