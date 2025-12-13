from __future__ import annotations

import os
from dataclasses import dataclass


def _require(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


@dataclass(frozen=True)
class Config:
    bot_token: str
    webhook_url: str  # Полный URL до /telegram
    base_url: str     # https://your-domain (для WebApp ссылки)
    admin_id: int

    # Радио
    play_window_sec: int = 90
    max_results: int = 12
    download_timeout_sec: int = 120
    search_timeout_sec: int = 20
    max_filesize_mb: int = 45
    max_concurrent_downloads: int = 1  # Railway обычно не любит параллельные yt-dlp

    # Cookies для yt-dlp (опционально)
    cookies_txt_env: str = "COOKIES_TXT"  # содержимое cookies.txt строкой
    cookies_path: str = "cookies.txt"

    @staticmethod
    def from_env() -> "Config":
        return Config(
            bot_token=_require("BOT_TOKEN"),
            webhook_url=_require("WEBHOOK_URL"),
            base_url=_require("BASE_URL").rstrip("/"),
            admin_id=int(_require("ADMIN_ID")),
        )