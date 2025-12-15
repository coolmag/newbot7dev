from pathlib import Path
from typing import List, Dict, Any
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

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
    MAX_RESULTS: int = 30 # Увеличил выборку для разнообразия

    # ==========================================
    # 🎵 МУЗЫКАЛЬНАЯ ИЕРАРХИЯ (КАТАЛОГ)
    # ==========================================
    # Формат: "Название кнопки": "Поисковый запрос для YouTube"
    # Если значение - словарь, это подкатегория.
    
    MUSIC_CATALOG: Dict[str, Any] = {
        "🎸 Рок и Метал": {
            "🤘 Classic Rock": "best classic rock hits 70s 80s",
            "🎸 Alt Rock": "alternative rock hits",
            "⚫ Metal": "heavy metal best songs",
            "😡 Punk": "punk rock classic",
            "🌫 Grunge": "best grunge songs",
            "🌑 Indie Rock": "indie rock hits",
            "🇷🇺 Русский Рок": "лучший русский рок хиты",
            "☠️ Metalcore": "metalcore best songs"
        },
        "🎹 Электроника": {
            "🏠 House": "best house music 2024",
            "💊 Techno": "techno music playlist",
            "🔊 Drum & Bass": {
                "🚀 Mainstream DnB": "drum and bass hits",
                "🌴 Liquid DnB": "liquid drum and bass",
                "🦁 Jungle": "old school jungle music",
                "🧠 Neurofunk": "neurofunk mix"
            },
            "🌀 Trance": "vocal trance classic",
            "👾 Dubstep": "dubstep hits classic",
            "🌌 Synthwave": "synthwave retrowave mix"
        },
        "🎤 Хип-Хоп": {
            "🇺🇸 Old School": "90s hip hop hits",
            "🔫 Trap": "best trap music",
            "🏎 Phonk": "phonk drift music",
            "🇷🇺 Русский Рэп": "лучший русский рэп",
            "🚬 Кальянный": "кальянный рэп хиты"
        },
        "🕰 По Эпохам": {
            "🕺 50s Rock'n'Roll": "50s rock n roll hits",
            "☮️ 60s Hippie": "60s music hits",
            "🕺 70s Disco/Rock": "70s hits best songs",
            "💾 80s Hits": "80s greatest hits",
            "📼 90s Eurodance": "90s eurodance hits",
            "🧢 2000s Pop/Rock": "2000s hits"
        },
        "✨ Вайб / Настроение": {
            "☕️ Lo-Fi / Study": "lofi hip hop radio",
            "🛌 Sleep / Ambient": "ambient music for sleep",
            "💪 Gym / Workout": "gym workout music",
            "🚗 Night Drive": "night drive music",
            "🎷 Jazz Bar": "smooth jazz instrumental"
        }
    }

def get_settings() -> Settings:
    return Settings()