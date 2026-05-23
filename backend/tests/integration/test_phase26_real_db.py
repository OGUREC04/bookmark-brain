"""Phase 2.6 integration tests against REAL Postgres.

Покрывает критичные пути на которых нельзя положиться на моки:

  1. CAS-UPDATE синтаксис в apply-decision endpoint и worker._mark_decision_applied_cas
     (JSONB COALESCE + jsonb_build_object + RETURNING)
  2. reminder_cascade.apply_cascade — JSONB-фильтр `payload->>'task_list_id' = :bid`
  3. apply-decision endpoint roundtrip через httpx → FastAPI app
  4. Idempotency: вторая попытка apply-decision возвращает 409

Запуск:
    pytest backend/tests/integration/test_phase26_real_db.py -m integration
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pytestmark = pytest.mark.integration


_TG_ID_COUNTER = 7900000


@pytest.fixture
async def db_user_id():
    """Юзер с уникальным telegram_id, cleanup после теста."""
    global _TG_ID_COUNTER
    _TG_ID_COUNTER += 1
    tg_id = _TG_ID_COUNTER

    from app.database import async_session
    from app.models import User
    from sqlalchemy import delete

    async with async_session() as session:
        u = User(
            telegram_id=tg_id,
            telegram_username=f"p26_{tg_id}",
            telegram_first_name="Phase26",
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


@pytest.fixture
async def bookmark_with_decision(db_user_id):
    """Bookmark со structured_data.reminder_decision уже заложенным —
    готов к вызову apply-decision."""
    from app.database import async_session
    from app.models import Bookmark
    from sqlalchemy import delete

    fire_at_iso = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).isoformat()

    structured = {
        "type": "task_list",
        "tasks": [
            {"text": "контрольная", "done": False, "deadline": None},
            {"text": "зачёт", "done": False, "deadline": None},
        ],
        "reminder_decision": {
            "form": "task_list_with_reminders",
            "items": [
                {
                    "text": "контрольная",
                    "raw_date_phrase": "завтра в 9",
                    "fire_at_utc": fire_at_iso,
                    "status": "ok",
                },
                {
                    "text": "зачёт",
                    "raw_date_phrase": None,
                    "fire_at_utc": None,
                    "status": None,
                },
            ],
            "strong_intent": False,
            "explicit_trigger": False,
        },
    }

    async with async_session() as session:
        bm = Bookmark(
            user_id=db_user_id,
            raw_text="завтра контрольная в 9, ещё зачёт",
            structured_data=structured,
            ai_status="completed",
        )
        session.add(bm)
        await session.flush()
        await session.refresh(bm)
        bm_id = bm.id
        await session.commit()

    yield bm_id

    try:
        async with async_session() as session:
            await session.execute(delete(Bookmark).where(Bookmark.id == bm_id))
            await session.commit()
    except Exception:
        pass


# ──────────────────────────────────────────────────
# CAS-UPDATE syntax verification on real PG
# ──────────────────────────────────────────────────


class TestCASUpdate:
    """SQL для idempotency-CAS должен работать на реальной Postgres."""

    async def test_cas_succeeds_on_first_call(self, bookmark_with_decision, db_user_id):
        """Первый CAS возвращает id (бумарк ещё без applied-флага)."""
        from app.database import async_session
        from sqlalchemy import text as sa_text

        async with async_session() as session:
            result = await session.execute(sa_text(
                """
                UPDATE bookmarks
                SET structured_data = COALESCE(structured_data, '{}'::jsonb)
                                      || jsonb_build_object('reminder_decision_applied', true)
                WHERE id = CAST(:bid AS uuid)
                  AND user_id = CAST(:uid AS uuid)
                  AND COALESCE(structured_data->>'reminder_decision_applied', 'false') <> 'true'
                RETURNING id
                """
            ).bindparams(bid=str(bookmark_with_decision), uid=str(db_user_id)))
            assert result.scalar_one_or_none() is not None
            await session.commit()

    async def test_cas_returns_none_on_second_call(self, bookmark_with_decision, db_user_id):
        """Второй CAS возвращает None (флаг уже стоит)."""
        from app.database import async_session
        from sqlalchemy import text as sa_text

        # First call
        async with async_session() as session:
            await session.execute(sa_text(
                """
                UPDATE bookmarks
                SET structured_data = COALESCE(structured_data, '{}'::jsonb)
                                      || jsonb_build_object('reminder_decision_applied', true)
                WHERE id = CAST(:bid AS uuid)
                  AND user_id = CAST(:uid AS uuid)
                  AND COALESCE(structured_data->>'reminder_decision_applied', 'false') <> 'true'
                RETURNING id
                """
            ).bindparams(bid=str(bookmark_with_decision), uid=str(db_user_id)))
            await session.commit()

        # Second call — should return None
        async with async_session() as session:
            result = await session.execute(sa_text(
                """
                UPDATE bookmarks
                SET structured_data = COALESCE(structured_data, '{}'::jsonb)
                                      || jsonb_build_object('reminder_decision_applied', true)
                WHERE id = CAST(:bid AS uuid)
                  AND user_id = CAST(:uid AS uuid)
                  AND COALESCE(structured_data->>'reminder_decision_applied', 'false') <> 'true'
                RETURNING id
                """
            ).bindparams(bid=str(bookmark_with_decision), uid=str(db_user_id)))
            assert result.scalar_one_or_none() is None
            await session.commit()

    async def test_cas_idor_protected(self, bookmark_with_decision):
        """CAS с чужим user_id ничего не апдейтит — IDOR-защита на raw SQL."""
        from app.database import async_session
        from sqlalchemy import text as sa_text

        async with async_session() as session:
            result = await session.execute(sa_text(
                """
                UPDATE bookmarks
                SET structured_data = COALESCE(structured_data, '{}'::jsonb)
                                      || jsonb_build_object('reminder_decision_applied', true)
                WHERE id = CAST(:bid AS uuid)
                  AND user_id = CAST(:uid AS uuid)
                  AND COALESCE(structured_data->>'reminder_decision_applied', 'false') <> 'true'
                RETURNING id
                """
            ).bindparams(bid=str(bookmark_with_decision), uid=str(uuid4())))
            assert result.scalar_one_or_none() is None
            await session.commit()

    async def test_mark_decision_applied_cas_helper(self, bookmark_with_decision, db_user_id):
        """Worker helper `_mark_decision_applied_cas` — claim then no-claim."""
        from app.database import async_session
        from app.worker import _mark_decision_applied_cas

        async with async_session() as session:
            first = await _mark_decision_applied_cas(session, bookmark_with_decision, db_user_id)
            await session.commit()
        assert first is True

        async with async_session() as session:
            second = await _mark_decision_applied_cas(session, bookmark_with_decision, db_user_id)
            await session.commit()
        assert second is False


# ──────────────────────────────────────────────────
# Cascade against real DB
# ──────────────────────────────────────────────────


class TestCascadeRealDB:
    """`reminder_cascade.apply_cascade` против real Postgres — JSONB-фильтры и UPDATEs."""

    async def test_cancel_removed_item(self, db_user_id):
        """Удалили пункт где висел reminder → cancel в БД."""
        from app.database import async_session
        from app.models import Bookmark, ScheduledMessage
        from app.services.reminder_cascade import apply_cascade
        from sqlalchemy import delete, select

        async with async_session() as session:
            bm = Bookmark(
                user_id=db_user_id,
                raw_text="x",
                structured_data={"type": "task_list", "tasks": [{"text": "молоко"}]},
                ai_status="completed",
            )
            session.add(bm)
            await session.flush()
            await session.refresh(bm)
            bm_id = bm.id

            rem = ScheduledMessage(
                user_id=db_user_id,
                bookmark_id=bm_id,
                kind="reminder",
                fire_at=datetime.now(timezone.utc) + timedelta(days=1),
                status="pending",
                payload={
                    "text": "молоко",
                    "source": "test",
                    "task_list_id": str(bm_id),
                },
            )
            session.add(rem)
            await session.flush()
            await session.refresh(rem)
            rid = rem.id
            await session.commit()

        # Apply cascade — old has молоко, new is empty
        async with async_session() as session:
            result = await apply_cascade(
                session,
                bookmark_id=bm_id,
                user_id=db_user_id,
                old_structured={"tasks": [{"text": "молоко"}]},
                new_structured={"tasks": []},
            )
            await session.commit()

        assert rid in result.cancelled

        async with async_session() as session:
            row = await session.execute(
                select(ScheduledMessage.status).where(ScheduledMessage.id == rid)
            )
            assert row.scalar_one() == "cancelled"

            # Cleanup
            await session.execute(delete(ScheduledMessage).where(ScheduledMessage.id == rid))
            await session.execute(delete(Bookmark).where(Bookmark.id == bm_id))
            await session.commit()

    async def test_create_for_new_item_with_deadline(self, db_user_id):
        """Добавили пункт с deadline → создан reminder."""
        from app.database import async_session
        from app.models import Bookmark, ScheduledMessage
        from app.services.reminder_cascade import apply_cascade
        from sqlalchemy import delete, select

        async with async_session() as session:
            bm = Bookmark(
                user_id=db_user_id,
                raw_text="x",
                structured_data={"type": "task_list", "tasks": []},
                ai_status="completed",
            )
            session.add(bm)
            await session.flush()
            await session.refresh(bm)
            bm_id = bm.id
            await session.commit()

        # Use a far-future date so test isn't time-sensitive
        future_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        async with async_session() as session:
            result = await apply_cascade(
                session,
                bookmark_id=bm_id,
                user_id=db_user_id,
                old_structured={"tasks": []},
                new_structured={"tasks": [{"text": "врач", "deadline": future_date}]},
                user_tz="Europe/Moscow",
            )
            await session.commit()

        assert len(result.created) == 1

        async with async_session() as session:
            rows = await session.execute(
                select(ScheduledMessage).where(
                    ScheduledMessage.bookmark_id == bm_id,
                    ScheduledMessage.status == "pending",
                )
            )
            rems = list(rows.scalars().all())
            assert len(rems) == 1
            assert rems[0].payload["text"] == "врач"
            assert rems[0].payload["source"] == "cascade_added"
            assert rems[0].payload["task_list_id"] == str(bm_id)

            # Cleanup
            for r in rems:
                await session.execute(
                    delete(ScheduledMessage).where(ScheduledMessage.id == r.id)
                )
            await session.execute(delete(Bookmark).where(Bookmark.id == bm_id))
            await session.commit()


# ──────────────────────────────────────────────────
# apply-decision endpoint roundtrip via httpx + FastAPI app
# ──────────────────────────────────────────────────


class TestApplyDecisionEndpoint:
    """POST /api/v1/reminders/apply-decision/{id} — настоящий HTTP request."""

    async def test_apply_creates_reminders_and_marks_applied(
        self, bookmark_with_decision, db_user_id,
    ):
        """Первый apply создаёт reminder'ы + ставит флаг. Второй — 409."""
        from app.auth import create_access_token
        from app.database import async_session
        from app.models import User
        from httpx import ASGITransport, AsyncClient
        from main import app
        from sqlalchemy import select

        # Получаем telegram_id для токена
        async with async_session() as session:
            res = await session.execute(select(User.telegram_id).where(User.id == db_user_id))
            tg_id = res.scalar_one()
        token = create_access_token(db_user_id, tg_id)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First apply — должен создать reminders
            resp = await client.post(
                f"/api/v1/reminders/apply-decision/{bookmark_with_decision}",
                params={"form": "task_list_with_reminders"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["total"] == 1  # один dated item в decision
            assert len(body["items"]) == 1
            assert body["items"][0]["payload"]["text"] == "контрольная"

            # Second apply — 409 idempotency
            resp2 = await client.post(
                f"/api/v1/reminders/apply-decision/{bookmark_with_decision}",
                params={"form": "task_list_with_reminders"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp2.status_code == 409, resp2.text
            assert "already applied" in resp2.json()["detail"].lower()

        # Cleanup reminders создаются от bookmark CASCADE при удалении в fixture

    async def test_apply_idor_returns_404_for_other_user(
        self, bookmark_with_decision,
    ):
        """Token чужого юзера → 404 (не палим существование)."""
        from app.auth import create_access_token

        # Создаём второго юзера прямо в тесте
        from app.database import async_session
        from app.models import User
        from httpx import ASGITransport, AsyncClient
        from main import app
        from sqlalchemy import delete

        global _TG_ID_COUNTER
        _TG_ID_COUNTER += 1
        other_tg = _TG_ID_COUNTER
        async with async_session() as session:
            other = User(
                telegram_id=other_tg,
                telegram_username=f"other_{other_tg}",
                timezone="Europe/Moscow",
            )
            session.add(other)
            await session.flush()
            await session.refresh(other)
            other_id = other.id
            await session.commit()

        try:
            other_token = create_access_token(other_id, other_tg)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    f"/api/v1/reminders/apply-decision/{bookmark_with_decision}",
                    params={"form": "task_list_with_reminders"},
                    headers={"Authorization": f"Bearer {other_token}"},
                )
                assert resp.status_code == 404, resp.text
        finally:
            async with async_session() as session:
                await session.execute(delete(User).where(User.id == other_id))
                await session.commit()

    async def test_apply_returns_409_when_no_decision(self, db_user_id):
        """Bookmark без structured_data.reminder_decision → 409."""
        from app.auth import create_access_token
        from app.database import async_session
        from app.models import Bookmark, User
        from httpx import ASGITransport, AsyncClient
        from main import app
        from sqlalchemy import delete, select

        async with async_session() as session:
            bm = Bookmark(
                user_id=db_user_id,
                raw_text="just text",
                structured_data={},
                ai_status="completed",
            )
            session.add(bm)
            await session.flush()
            await session.refresh(bm)
            bm_id = bm.id
            res = await session.execute(select(User.telegram_id).where(User.id == db_user_id))
            tg_id = res.scalar_one()
            await session.commit()

        try:
            token = create_access_token(db_user_id, tg_id)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    f"/api/v1/reminders/apply-decision/{bm_id}",
                    params={"form": "single_reminder"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 409
                assert "no reminder_decision" in resp.json()["detail"].lower()
        finally:
            async with async_session() as session:
                await session.execute(delete(Bookmark).where(Bookmark.id == bm_id))
                await session.commit()
