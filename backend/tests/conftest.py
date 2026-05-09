"""Backend test fixtures.

Минимальная инфра — фокус на pure-Python тестах сервисов без БД.
Интеграционные тесты с реальной Postgres — отдельная задача (см. beads).
"""
import os
import sys
from pathlib import Path

# Добавляем backend/ в sys.path, чтобы импорты `app.*` работали
_BACKEND_DIR = Path(__file__).parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Дефолтные env для импорта app.config — тесты должны идти без реальных credentials
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("SECRET_KEY", "x" * 32)
os.environ.setdefault("BOT_SECRET", "test-secret")
os.environ.setdefault("GIGACHAT_AUTH_KEY", "fake")
os.environ.setdefault("VOYAGE_API_KEY", "fake")
