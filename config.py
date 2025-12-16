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
        "🎸 Рок и Метал": {
            "🤘 Classic Rock": "classic rock hits 70s 80s songs",
            "🎸 Alt Rock": "alternative rock hits songs",
            "⚫ Metal": {
                "🤘 Heavy Metal": "heavy metal hits",
                "🔥 Thrash Metal": "thrash metal songs",
                "☠️ Death Metal": "death metal songs",
                "🛠 Industrial": "industrial metal songs rammstein"
            },
            "😡 Punk": {
                "🇬🇧 Classic Punk": "sex pistols songs",
                "🛹 Pop Punk": "pop punk hits blink-182 songs",
                "🇷🇺 Русский Панк": "король и шут песни"
            }
        },
        "🎹 Электроника": {
            "🏠 House": {
                "☀️ Deep House": "deep house vocal songs",
                "🎹 Tech House": "tech house tracks",
                "🕺 Funky House": "funky house songs"
            },
            "🌀 Trance": {
                "🎤 Vocal Trance": "vocal trance hits",
                "🕉 Psy-Trance": "psytrance hits",
                "⏫ Uplifting": "uplifting trance songs"
            },
            "💊 Techno": {
                "🏭 Industrial": "hard industrial techno tracks",
                "🎹 Melodic": "melodic techno songs"
            },
            "🔊 Drum & Bass": {
                "🌴 Liquid": "liquid drum and bass songs",
                "🧠 Neurofunk": "neurofunk dnb tracks",
                "🏃 Jump Up": "jump up dnb songs"
            },
            "🌌 Synthwave": "synthwave songs"
        },
        "🎤 Хип-Хоп": {
            "🇺🇸 Old School": "90s hip hop songs",
            "🔫 Trap": "trap music hits",
            "🏎 Phonk": "drift phonk songs",
            "🇷🇺 Наш Рэп": "русский рэп хиты"
        },
        "✨ Чилл / Вайб": {
            "☕️ Lo-Fi": "lofi hip hop songs",
            "🛌 Ambient": "ambient music tracks",
            "🎷 Jazz": "smooth jazz songs"
        }
    }

def get_settings() -> Settings:
    return Settings()