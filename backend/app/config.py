from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings

# .env лежит в корне проекта (на уровень выше backend/)
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/bookmarkbrain"
    REDIS_URL: str = "redis://localhost:6379"

    # Telegram
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    MINI_APP_URL: str = ""
    BOT_SECRET: str  # Required — must match bot's BOT_SECRET

    # AI
    AI_PROVIDER: str = "gigachat"  # "gigachat" | "deepseek" | "claude"
    EMBEDDING_PROVIDER: str = "gigachat"  # "gigachat" or "voyage"
    GIGACHAT_AUTH_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    VOYAGE_API_KEY: str = ""

    # STT (Speech-to-Text)
    WHISPER_API_KEY: str = ""
    STT_PROVIDER: str = "openai"  # "openai" | "groq" | "yandex"
    YANDEX_CLOUD_API_KEY: str = ""
    YANDEX_CLOUD_FOLDER_ID: str = ""

    # App
    SECRET_KEY: str  # Required — no default, must be set in .env
    ENVIRONMENT: str = "development"

    # Stale list nudge — hour (UTC) when nudge cron runs
    NUDGE_HOUR_UTC: int = 6  # ~9:00 MSK

    # GigaChat TLS — path to CA bundle for Sber certificates
    GIGACHAT_CA_BUNDLE: str = ""

    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Startup guards — fail fast if critical secrets are missing
    if not s.SECRET_KEY or s.SECRET_KEY == "change-me-in-production":
        raise RuntimeError(
            "SECRET_KEY is not set or uses the unsafe default. "
            "Set a strong random value in .env"
        )
    if not s.BOT_SECRET:
        raise RuntimeError(
            "BOT_SECRET is empty. Set a shared secret between bot and backend in .env"
        )
    return s
