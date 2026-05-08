from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    BACKEND_URL: str = "http://localhost:8000"
    BOT_SECRET: str  # Required — must match backend's BOT_SECRET
    MINI_APP_URL: str = ""
    REDIS_URL: str = "redis://localhost:6379"
    WHISPER_API_KEY: str = ""
    STT_PROVIDER: str = "openai"  # "openai" | "groq" | "yandex"
    YANDEX_CLOUD_API_KEY: str = ""
    YANDEX_CLOUD_FOLDER_ID: str = ""
    # Async STT (>30s voice messages) — Yandex Object Storage S3-compatible.
    # Заполняется только если STT_PROVIDER=yandex и нужно поддерживать длинные голосовые.
    # Если не заполнено — длинные голосовые отвергаются с понятным сообщением.
    YANDEX_S3_ENDPOINT: str = "https://storage.yandexcloud.net"
    YANDEX_S3_BUCKET: str = ""
    YANDEX_S3_ACCESS_KEY: str = ""
    YANDEX_S3_SECRET_KEY: str = ""
    ENVIRONMENT: str = "development"

    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.BOT_SECRET:
        raise RuntimeError(
            "BOT_SECRET is empty. Set a shared secret between bot and backend in .env"
        )
    return s
