from functools import lru_cache
import aioboto3

from telegram.ext import Application
from telegram import Bot

from config import get_settings, Settings
from database import DatabaseService
from youtube import YouTubeDownloader
from radio import RadioManager
from radio_voting import GenreVotingService # Import the new service
from s3_client import get_s3_session # Import the S3 session getter

# By using lru_cache, we ensure that each of these functions is executed only once,
# creating a single instance of each service (singleton pattern).

@lru_cache()
def get_settings_dep() -> Settings:
    """Dependency to get the application settings."""
    return get_settings()

@lru_cache()
def get_s3_session_dep() -> aioboto3.Session | None:
    """Dependency to get the S3 session."""
    return get_s3_session(settings=get_settings_dep())

@lru_cache()
def get_database_service_dep() -> DatabaseService:
    """Dependency to get the DatabaseService."""
    return DatabaseService(settings=get_settings_dep())

@lru_cache()
def get_downloader_dep() -> YouTubeDownloader:
    """Dependency to get the YouTubeDownloader."""
    return YouTubeDownloader(
        settings=get_settings_dep(), 
        db_service=get_database_service_dep(),
        s3_session=get_s3_session_dep(), # Pass the S3 session
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
def get_genre_voting_service_dep() -> GenreVotingService:
    """Dependency to get the GenreVotingService."""
    return GenreVotingService(
        bot=get_telegram_app_dep().bot,
        settings=get_settings_dep()
    )

@lru_cache()
def get_radio_manager_dep() -> RadioManager:
    """Dependency to get the RadioManager."""
    return RadioManager(
        bot=get_telegram_app_dep().bot,
        settings=get_settings_dep(),
        downloader=get_downloader_dep(),
        voting_service=get_genre_voting_service_dep()
    )
