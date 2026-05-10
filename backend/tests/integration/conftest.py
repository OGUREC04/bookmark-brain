"""Conftest для integration-tier тестов.

Грузит реальный DATABASE_URL из .env (root проекта) — перебивает дефолт
из backend/tests/conftest.py.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest


def _load_env_file(path: Path) -> dict[str, str]:
    """Минимальный .env parser без зависимостей."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if val and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        out[key] = val
    return out


# Грузим .env из корня проекта (override defaults уже выставленных в backend/tests/conftest.py)
_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
_env = _load_env_file(_ROOT_ENV)
for key in ("DATABASE_URL", "REDIS_URL", "SECRET_KEY", "BOT_SECRET", "GIGACHAT_AUTH_KEY", "VOYAGE_API_KEY"):
    if key in _env and _env[key]:
        os.environ[key] = _env[key]


# Общий event-loop для модуля чтобы async engine из app.database переиспользовался.
# Иначе pytest-asyncio создаёт новый loop на каждый тест, asyncpg-pool становится
# attached to dead loop → "operating on a different event loop" между тестами.
@pytest.fixture(scope="session", autouse=True)
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    """После каждого теста disposed engine — чтобы новый тест получил
    fresh pool без stale connections."""
    yield
    try:
        from app.database import engine
        await engine.dispose()
    except Exception:
        pass
