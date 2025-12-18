from functools import lru_cache

from telegram.ext import Application

from config import get_settings, Settings
from cache import CacheService
from youtube import YouTubeDownloader
from radio import RadioManager

# By using lru_cache, we ensure that each of these functions is executed only once,
# creating a single instance of each service (singleton pattern).

@lru_cache()
def get_settings_dep() -> Settings:
    """Dependency to get the application settings."""
    return get_settings()

@lru_cache()
def get_cache_service_dep() -> CacheService:
    """Dependency to get the CacheService."""
    return CacheService(settings=get_settings_dep())

@lru_cache()
def get_downloader_dep() -> YouTubeDownloader:
    """Dependency to get the YouTubeDownloader."""
    return YouTubeDownloader(
        settings=get_settings_dep(), 
        cache=get_cache_service_dep()
    )

@lru_cache()
def get_telegram_app_dep() -> Application:
    """Dependency to get the Telegram Application instance."""
    return (
        Application.builder()
        .token(get_settings_dep().BOT_TOKEN)
        .updater(None)
        .build()
    )

@lru_cache()
def get_radio_manager_dep() -> RadioManager:
    """Dependency to get the RadioManager."""
    return RadioManager(
        bot=get_telegram_app_dep().bot,
        settings=get_settings_dep(),
        downloader=get_downloader_dep()
    )
