from enum import Enum
from typing import Optional
from pathlib import Path # Added Path import

from pydantic import BaseModel, ConfigDict, Field # Added ConfigDict, Field

class Source(str, Enum):
    """Перечисление доступных источников музыки."""
    YOUTUBE = "YouTube"
    YOUTUBE_MUSIC = "YouTube Music"
    INTERNET_ARCHIVE = "Internet Archive"

class StreamInfo(BaseModel):
    """Содержит прямую ссылку на аудиопоток и метаданные трека."""
    stream_url: str
    track_info: "TrackInfo"

class StreamInfoResult(BaseModel):
    """
    Результат операции по получению информации о потоке.
    """
    success: bool
    stream_info: Optional[StreamInfo] = None
    error: Optional[str] = None

class TrackInfo(BaseModel): # Changed from @dataclass(frozen=True)
    """
    Структура для хранения информации о треке.
    """
    model_config = ConfigDict(frozen=True) # Equivalent to frozen=True for dataclass

    title: str
    artist: str
    duration: int
    source: str
    identifier: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None

    @property
    def display_name(self) -> str:
        """Возвращает форматированное имя для отображения."""
        return f"{self.artist} - {self.title}"

    def format_duration(self) -> str:
        """Форматирует длительность из секунд в строку MM:SS."""
        if not self.duration or self.duration < 0:
            return "00:00"
        minutes, seconds = divmod(self.duration, 60)
        return f"{minutes:02d}:{seconds:02d}"

    @classmethod # Changed from staticmethod to classmethod
    def from_yt_info(cls, info: dict) -> "TrackInfo": # Use cls instead of hardcoded TrackInfo
        """Создает TrackInfo из словаря информации yt-dlp."""
        return cls( # Use cls() for instantiation
            title=info.get("title", "Unknown"),
            artist=info.get("channel", info.get("uploader", "Unknown")),
            duration=int(info.get("duration") or 0),
            source=Source.YOUTUBE.value,
            identifier=info["id"],
            view_count=info.get("view_count"),
            like_count=info.get("like_count"),
        )

# === Callback Data Prefixes ===
# Using classes for namespacing callback data to avoid magic strings

class MenuCallback:
    """Callbacks related to the main menu."""
    VOTE_FOR_GENRE = "menu:vote_genre"
    # Add other menu callbacks if needed

class VoteCallback:
    """Callbacks related to voting."""
    PREFIX = "vote:"

class GenreCallback:
    """Callbacks related to admin genre selection."""
    PREFIX = "genre:"

class DownloadResult(BaseModel):
    success: bool
    file_path: Optional[Path] = None
    track_info: Optional[TrackInfo] = None
    error: Optional[str] = None
