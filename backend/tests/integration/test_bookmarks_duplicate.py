"""Integration test: Bug 2026-05-11 — дубликат source_message_id.

Симптом: юзер отправил список, бот merge'ил, через 18 секунд юзер
отправил тот же список снова → INSERT падал с IntegrityError на
`idx_bookmarks_source_dedup` → 500 «Ошибка при сохранении».

Фикс: POST /bookmarks ловит IntegrityError на этом индексе и
возвращает СУЩЕСТВУЮЩИЙ bookmark (idempotent semantics) — бот
дальше показывает его как «уже есть».

Тесты на ЖИВОМ Postgres — IntegrityError не репродуцируется на моках.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pytestmark = pytest.mark.integration


_TG_ID_COUNTER = 7800000


@pytest.fixture
async def db_user_id():
    global _TG_ID_COUNTER
    _TG_ID_COUNTER += 1
    tg_id = _TG_ID_COUNTER

    from app.database import async_session
    from app.models import User
    from sqlalchemy import delete

    async with async_session() as session:
        u = User(
            telegram_id=tg_id,
            telegram_username=f"dup_{tg_id}",
            telegram_first_name="Dup",
            timezone="Europe/Moscow",
        )
        session.add(u)
        await session.flush()
        await session.refresh(u)
        user_id = u.id
        await session.commit()

    yield user_id

    try:
        async with async_session() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
    except Exception:
        pass


async def _create_bookmark(user_id, source_message_id: int, text: str = "task"):
    """Прямой INSERT в Bookmark — обходим API, тестируем именно constraint."""
    from app.database import async_session
    from app.models import Bookmark
    async with async_session() as session:
        bm = Bookmark(
            user_id=user_id,
            source="bot_message",
            source_message_id=source_message_id,
            raw_text=text,
            content_type="other",
        )
        session.add(bm)
        await session.flush()
        await session.refresh(bm)
        bid = bm.id
        await session.commit()
        return bid


class TestDuplicateSourceMessageIdIndex:
    """Подтверждаем что unique-индекс действительно срабатывает —
    это входной контракт для фикса в API."""

    async def test_duplicate_raises_integrity(self, db_user_id):
        from app.database import async_session
        from app.models import Bookmark
        from sqlalchemy.exc import IntegrityError

        await _create_bookmark(db_user_id, source_message_id=999_001)

        async with async_session() as session:
            bm2 = Bookmark(
                user_id=db_user_id,
                source="bot_message",
                source_message_id=999_001,
                raw_text="другой текст",
                content_type="other",
            )
            session.add(bm2)
            with pytest.raises(IntegrityError):
                await session.flush()

    async def test_different_message_ids_ok(self, db_user_id):
        bid1 = await _create_bookmark(db_user_id, 999_010, "first")
        bid2 = await _create_bookmark(db_user_id, 999_011, "second")
        assert bid1 != bid2

    async def test_null_source_message_id_ok_multiple(self, db_user_id):
        """idx_bookmarks_source_dedup имеет WHERE source_message_id IS NOT NULL —
        NULL'ы не конфликтуют."""
        from app.database import async_session
        from app.models import Bookmark
        async with async_session() as session:
            for _ in range(3):
                session.add(Bookmark(
                    user_id=db_user_id, source="bot_message",
                    source_message_id=None, raw_text="x", content_type="other",
                ))
            await session.commit()  # не должно упасть


class TestAPIIdempotentOnDuplicate:
    """API POST /bookmarks должен быть идемпотентным на дубликате
    (user_id, source, source_message_id) — возвращать существующий."""

    async def test_post_duplicate_returns_existing(self, db_user_id):
        """Bug 2026-05-11: повторный POST с тем же source_message_id
        не должен возвращать 500 — должен вернуть существующий bookmark."""
        from app.api.bookmarks import create_bookmark
        from app.database import async_session
        from app.models import User
        from app.schemas import BookmarkCreate
        from sqlalchemy import select

        # Создаём «существующий» bookmark
        existing_id = await _create_bookmark(
            db_user_id, source_message_id=888_001, text="первый текст",
        )

        # Получаем User объект для зависимости
        async with async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == db_user_id))
            ).scalar_one()

        data = BookmarkCreate(
            raw_text="второй текст",
            source="bot_message",
            source_message_id=888_001,
            content_type="other",
            silent=True,
        )

        async with async_session() as session:
            # Передаём ту же user → дубликат должен быть пойман
            result = await create_bookmark(data, current_user=user, session=session)

        # Должен вернуть СУЩЕСТВУЮЩИЙ id (не создать новый)
        assert result.id == existing_id, (
            f"ожидал existing_id={existing_id}, получил {result.id} "
            "(значит создан дубликат вместо возврата существующего)"
        )
        # raw_text — оригинальный (не обновлён)
        assert result.raw_text == "первый текст"
