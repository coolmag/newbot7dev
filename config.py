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
        "📂 Электроника": {
            "House": {
                "Deep House": "deep house classics",
                "Tech House": "tech house top 100",
                "Progressive House": "progressive house anthems",
            },
            "Techno": {
                "Melodic Techno": "melodic techno playlist tale of us",
                "Industrial Techno": "industrial techno mix",
                "Minimal Techno": "minimal techno boris brejcha",
            },
            "Trance": {
                "Vocal Trance": "vocal trance hits armin van buuren",
                "Psytrance": "psytrance festival mix astrix vini vici",
                "Uplifting Trance": "uplifting trance emotional",
            },
            "Breaks / DnB": {
                "Drum & Bass": "liquid dnb classics",
                "Dubstep": "classic dubstep skrillex burial",
                "Breakbeat": "90s breakbeat prodigy chemical brothers",
            },
            "Ambient / Chill": {
                "Ambient": "ambient music brian eno",
                "Chillwave": "chillwave playlist washed out",
                "Downtempo": "downtempo chill trip-hop massive attack",
            },
            "80s Influence": {
                "Synthwave": "synthwave retrowave playlist The Midnight",
                "Italo Disco": "italo disco 80s",
            },
        },
        "📂 Рок / Альтернатива": {
            "Classic Rock": {
                "Psychedelic Rock 60-70s": "psychedelic rock 60s 70s Jimi Hendrix",
                "Progressive Rock 70s": "progressive rock 70s Pink Floyd Yes",
                "Arena Rock 80s": "arena rock 80s bon jovi journey",
            },
            "Hard Rock & Metal": {
                "Hard Rock": "hard rock 70s 80s led zeppelin ac/dc",
                "Heavy Metal": "heavy metal iron maiden judas priest",
                "Thrash Metal": "thrash metal metallica slayer",
            },
            "Alternative": {
                "Grunge 90s": "grunge rock 90s nirvana soundgarden",
                "Britpop 90s": "britpop 90s oasis blur pulp",
                "Indie Rock 00-10s": "indie rock 2000s the strokes arctic monkeys",
            },
            "Punk": {
                "Punk Rock 70s": "punk rock 70s ramones sex pistols",
                "Pop-Punk 90-00s": "pop punk 2000s blink-182 sum 41",
                "Post-Punk": "post-punk joy division the cure",
            },
        },
        "📂 Хип-хоп / R&B": {
            "Roots": {
                "Funk": "funk 70s james brown parliament",
                "Soul": "soul music 60s 70s marvin gaye aretha franklin",
                "Disco": "disco classics 70s earth wind and fire",
            },
            "Golden Age": {
                "Old-School 80s": "80s old school hip hop run dmc",
                "East Coast 90s": "90s east coast hip hop nas wu-tang clan",
                "West Coast 90s": "90s west coast hip hop dr dre snoop dogg",
            },
            "R&B": {
                "Contemporary R&B 90-00s": "90s 2000s r&b hits usher beyonce",
                "Neo-Soul": "neo-soul d'angelo erykah badu",
            },
            "Modern": {
                "Trap": "trap music top hits Travis Scott Migos",
                "Drill": "drill music pop smoke chief keef",
                "Phonk": "phonk drift music",
            },
        },
        "📂 Поп": {
            "80s Pop": {
                "Synth-Pop": "synth-pop 80s depeche mode human league",
                "New Wave": "new wave 80s the police tears for fears",
            },
            "90s Pop": {
                "Teen Pop": "90s teen pop britney spears backstreet boys",
                "Europop": "90s europop ace of base aqua",
            },
            "00s Pop": {
                "Pop/R&B": "2000s pop r&b beyonce justin timberlake",
                "Dance-Pop": "2000s dance pop lady gaga rihanna",
            },
            "Global Pop": {
                "K-Pop": "k-pop hits bts blackpink",
                "Latin Pop": "latin pop hits shakira ricky martin",
            },
        },
        "📂 Джаз / Блюз": {
            "Jazz": {
                "Cool Jazz": "cool jazz miles davis chet baker",
                "Jazz Fusion": "jazz fusion weather report mahavishnu orchestra",
                "Big Band / Swing": "big band swing duke ellington",
            },
            "Blues": {
                "Delta Blues": "delta blues robert johnson",
                "Chicago Blues": "chicago blues muddy waters howlin wolf",
                "Electric Blues": "electric blues b b king",
            },
        },
    }

def get_settings() -> Settings:
    return Settings()