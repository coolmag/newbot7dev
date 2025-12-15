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
    MAX_RESULTS: int = 30 
    
    # --- Кэш ---
    CACHE_TTL_DAYS: int = 7
    
    # --- Совместимость ---
    RADIO_MAX_DURATION_S: int = 900
    RADIO_MIN_DURATION_S: int = 30
    PLAY_MAX_DURATION_S: int = 900
    PLAY_MAX_FILE_SIZE_MB: int = 50

    # Fallback
    RADIO_GENRES: List[str] = ["rock", "pop", "jazz"] 

    # ==========================================
    # 🎵 ПОЛНЫЙ МУЗЫКАЛЬНЫЙ КАТАЛОГ
    # ==========================================
    
    MUSIC_CATALOG: Dict[str, Any] = {
        "🎸 Рок и Метал": {
            "🤘 Classic Rock": "best classic rock hits 70s 80s",
            "🎸 Alt Rock": "alternative rock hits",
            "🌫 Grunge": "best grunge songs nirvana pearl jam",
            "🌑 Indie Rock": "indie rock hits",
            "🇷🇺 Русский Рок": "лучший русский рок хиты",
            "⚫ Metal": {
                "🤘 Heavy Metal": "heavy metal classic hits",
                "🔥 Thrash Metal": "thrash metal metallica megadeth",
                "☠️ Death Metal": "death metal mix",
                "🖤 Black Metal": "old school black metal",
                "🎼 Symphonic Metal": "symphonic metal hits",
                "🛠 Industrial": "industrial metal rammstein",
                "💥 Nu Metal": "nu metal hits linkin park korn"
            },
            "😡 Punk": {
                "🇬🇧 Classic Punk": "sex pistols the clash",
                "🛹 Pop Punk": "pop punk hits blink-182",
                "🇷🇺 Русский Панк": "король и шут гражданская оборона",
                "🏴 Post-Punk": "soviet post punk doomer"
            }
        },
        "🎹 Электроника": {
            "🏠 House": {
                "☀️ Deep House": "deep house vocal chill",
                "🎹 Tech House": "tech house mix 2024",
                "🕺 Funky House": "funky house disco",
                "🌇 Progressive": "progressive house classic",
                "🔊 Bass House": "bass house mix"
            },
            "🌀 Trance": {
                "🎤 Vocal Trance": "vocal trance classics asot",
                "🌅 Progressive": "progressive trance mix",
                "🕉 Psy-Trance": "psytrance goa mix",
                "🍄 Goa Trance": "old school goa trance",
                "⏫ Uplifting": "uplifting trance 138 bpm"
            },
            "💊 Techno": {
                "🏭 Industrial": "hard industrial techno",
                "⛏ Hard Techno": "hard techno schranz",
                "🧠 Minimal": "minimal techno trippy",
                "🧪 Acid": "acid techno 303",
                "🎹 Melodic": "melodic techno afterlife"
            },
            "🔊 Drum & Bass": {
                "🌴 Liquid": "liquid drum and bass vocal",
                "🧠 Neurofunk": "neurofunk dnb mix",
                "🦁 Jungle": "ragga jungle old school",
                "🌑 Darkstep": "darkstep dnb techstep",
                "🏃 Jump Up": "jump up dnb mix"
            },
            "🌌 Synth & Wave": {
                "🚗 Synthwave": "synthwave retrowave mix",
                "📼 Vaporwave": "vaporwave chill",
                "🌆 Cyberpunk": "cyberpunk midtempo darksynth"
            },
            "👾 Dubstep": "dubstep classic skrillex"
        },
        "🎤 Хип-Хоп": {
            "🇺🇸 Old School": "90s hip hop east coast west coast",
            "🔫 Trap": "best trap music 2024",
            "🏎 Phonk": "drift phonk house",
            "☁️ Cloud Rap": "cloud rap yung lean",
            "🎹 Lo-Fi Hip Hop": "lofi hip hop beats",
            "🇷🇺 Наш Рэп": {
                "🏙 Олдскул": "русский рэп олдскул",
                "🚬 Кальянный": "кальянный рэп хиты",
                "🆕 Новая Школа": "русский трэп новинки"
            }
        },
        "🕰 По Эпохам": {
            "🕺 50s Rock'n'Roll": "50s rock n roll hits",
            "☮️ 60s Hippie": "60s music hits",
            "🕺 70s Disco/Rock": "70s hits best songs",
            "💾 80s Hits": "80s greatest hits",
            "📼 90s Eurodance": "90s eurodance hits",
            "🧢 2000s Hits": "2000s pop hits"
        },
        "✨ Чилл / Вайб": {
            "☕️ Lo-Fi / Study": "lofi hip hop radio",
            "🛌 Ambient": "ambient music for sleep",
            "🎷 Smooth Jazz": "smooth jazz instrumental",
            "🍹 Lounge": "ibiza lounge chillout",
            "🧘 Meditation": "meditation music 432hz"
        }
    }

def get_settings() -> Settings:
    return Settings()