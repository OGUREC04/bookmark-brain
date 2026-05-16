"""Тесты для scheduled_dispatcher и auto_done_reminders cron'ов.

Без реальной Postgres — мокаем session.execute и Telegram API.
Полные интеграционные тесты — отдельная задача.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ──────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────


def _make_due_row(
    *,
    sm_id=None,
    user_id=None,
    bookmark_id=None,
    telegram_id: int = 999,
    fire_at: datetime | None = None,
    retry_count: int = 0,
    payload: dict | None = None,
):
    """Tuple (id, user_id, telegram_id, bookmark_id, fire_at, retry_count, payload)."""
    return (
        sm_id or uuid4(),
        user_id or uuid4(),
        telegram_id,
        bookmark_id,
        fire_at or (datetime.now(timezone.utc) - timedelta(seconds=5)),
        retry_count,
        payload or {},
    )


class _MappingsResult:
    """`result.mappings()` возвращает объект с `.one_or_none()`."""

    def __init__(self, value):
        self._value = value

    def one_or_none(self):
        return self._value


class _ExecResult:
    """Mock SQLAlchemy execution result with `.all()`, `.scalar_one_or_none()`,
    `.mappings().one_or_none()`, `.rowcount`."""

    def __init__(self, *, all_rows=None, scalar=None, mapping=None, rowcount: int = 0):
        self._all = all_rows or []
        self._scalar = scalar
        # mapping для .mappings().one_or_none() — dict с column-name доступом.
        # Если не задан, используем scalar (back-compat).
        self._mapping = mapping if mapping is not None else scalar
        self.rowcount = rowcount

    def all(self):
        return self._all

    def scalar_one_or_none(self):
        return self._scalar

    def mappings(self):
        return _MappingsResult(self._mapping)


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.aclose = AsyncMock()
    return r


@pytest.fixture
def mock_session():
    s = AsyncMock()
    s.commit = AsyncMock()
    s.flush = AsyncMock()
    return s


# ──────────────────────────────────────────────────
# scheduled_dispatcher
# ──────────────────────────────────────────────────


class TestScheduledDispatcher:
    async def test_no_due_messages_noop(self, mock_session):
        """Пустая выборка — выходим без send."""
        from app.worker import scheduled_dispatcher

        # 1й execute — recovery stuck (rowcount=0), 2й — SELECT due (empty)
        mock_session.execute = AsyncMock(side_effect=[
            _ExecResult(rowcount=0),
            _ExecResult(all_rows=[]),
        ])

        with patch("app.worker.scheduled.async_session") as mk_sess, \
             patch("app.worker.scheduled._send_message", AsyncMock()) as send:
            mk_sess.return_value.__aenter__.return_value = mock_session
            await scheduled_dispatcher({})
            send.assert_not_called()

    async def test_recovery_resets_stuck_sending(self, mock_session):
        """Если есть stuck sending → reset в pending (rowcount > 0), warning лог."""
        from app.worker import scheduled_dispatcher

        mock_session.execute = AsyncMock(side_effect=[
            _ExecResult(rowcount=2),     # recovery — нашли 2 stuck
            _ExecResult(all_rows=[]),    # SELECT due после recovery
        ])

        with patch("app.worker.scheduled.async_session") as mk_sess, \
             patch("app.worker.scheduled._send_message", AsyncMock()):
            mk_sess.return_value.__aenter__.return_value = mock_session
            await scheduled_dispatcher({})  # не должен бросить

        # Recovery + SELECT — два execute
        assert mock_session.execute.call_count == 2
        # Recovery commit вызван
        assert mock_session.commit.called

    async def test_sends_due_reminder_and_marks_sent(self, mock_session, mock_redis):
        """Reminder due → CAS-lock → send → status=sent, message_id сохранён."""
        from app.worker import scheduled_dispatcher

        row = _make_due_row(payload={"text": "купить хлеб"})
        sm_id = row[0]

        # 1й execute — recovery (no stuck), 2й — SELECT due,
        # далее на каждый id: CAS UPDATE → 'sending' → returns row, UPDATE → 'sent'.
        cas_locked = {"id": sm_id, "user_id": row[1], "bookmark_id": None, "payload": row[6], "retry_count": 0}
        mock_session.execute = AsyncMock(side_effect=[
            _ExecResult(rowcount=0),                     # recovery
            _ExecResult(all_rows=[row]),                 # SELECT due
            _ExecResult(scalar=cas_locked),              # CAS UPDATE → sending
            _ExecResult(rowcount=1),                     # UPDATE → sent
        ])

        send_mock = AsyncMock(return_value={"message_id": 12345})

        with patch("app.worker.scheduled.async_session") as mk_sess, \
             patch("app.worker.scheduled._send_message", send_mock), \
             patch("app.worker.scheduled.aioredis_from_url", return_value=mock_redis):
            mk_sess.return_value.__aenter__.return_value = mock_session
            await scheduled_dispatcher({})

        send_mock.assert_called_once()
        # Telegram chat_id == users.telegram_id
        assert send_mock.call_args.args[0] == 999
        # Текст содержит payload text
        sent_text = send_mock.call_args.args[1]
        assert "купить хлеб" in sent_text
        # Inline buttons присутствуют
        markup = send_mock.call_args.args[2] if len(send_mock.call_args.args) > 2 else send_mock.call_args.kwargs.get("reply_markup")
        assert markup is not None
        # Redis key reminder:{chat_id}:{message_id} → {sm_id}
        mock_redis.set.assert_called()
        keys_set = [c.args[0] for c in mock_redis.set.call_args_list]
        assert any(f"reminder:999:12345" == k for k in keys_set)

    async def test_cas_lock_lost_skips(self, mock_session):
        """CAS UPDATE не вернул строку (другой воркер захватил) → skip, не падаем."""
        from app.worker import scheduled_dispatcher

        row = _make_due_row()
        mock_session.execute = AsyncMock(side_effect=[
            _ExecResult(rowcount=0),               # recovery
            _ExecResult(all_rows=[row]),
            _ExecResult(scalar=None),  # CAS промазал — другой воркер захватил
        ])

        with patch("app.worker.scheduled.async_session") as mk_sess, \
             patch("app.worker.scheduled._send_message", AsyncMock()) as send:
            mk_sess.return_value.__aenter__.return_value = mock_session
            await scheduled_dispatcher({})
            send.assert_not_called()

    async def test_send_failure_first_try_reschedules(self, mock_session, mock_redis):
        """Telegram вернул None → retry_count++, status='pending', fire_at=+5min."""
        from app.worker import scheduled_dispatcher

        row = _make_due_row(retry_count=0)
        cas_locked = {"id": row[0], "user_id": row[1], "bookmark_id": None, "payload": {}, "retry_count": 0}
        mock_session.execute = AsyncMock(side_effect=[
            _ExecResult(rowcount=0),  # recovery
            _ExecResult(all_rows=[row]),
            _ExecResult(scalar=cas_locked),
            _ExecResult(rowcount=1),  # reschedule UPDATE
        ])

        send_mock = AsyncMock(return_value=None)  # send failed

        with patch("app.worker.scheduled.async_session") as mk_sess, \
             patch("app.worker.scheduled._send_message", send_mock), \
             patch("app.worker.scheduled.aioredis_from_url", return_value=mock_redis):
            mk_sess.return_value.__aenter__.return_value = mock_session
            await scheduled_dispatcher({})

        # Recovery + SELECT + CAS + reschedule = 4 execute
        assert mock_session.execute.call_count == 4

    async def test_send_failure_max_retries_marks_failed(self, mock_session, mock_redis):
        """retry_count >= MAX_RETRIES → status='failed', не reschedule."""
        from app.worker import MAX_REMINDER_RETRIES, scheduled_dispatcher

        row = _make_due_row(retry_count=MAX_REMINDER_RETRIES)  # уже на пределе
        cas_locked = {
            "id": row[0], "user_id": row[1], "bookmark_id": None,
            "payload": {}, "retry_count": MAX_REMINDER_RETRIES,
        }
        mock_session.execute = AsyncMock(side_effect=[
            _ExecResult(rowcount=0),  # recovery
            _ExecResult(all_rows=[row]),
            _ExecResult(scalar=cas_locked),
            _ExecResult(rowcount=1),  # status='failed' UPDATE
        ])

        send_mock = AsyncMock(return_value=None)

        with patch("app.worker.scheduled.async_session") as mk_sess, \
             patch("app.worker.scheduled._send_message", send_mock), \
             patch("app.worker.scheduled.aioredis_from_url", return_value=mock_redis):
            mk_sess.return_value.__aenter__.return_value = mock_session
            await scheduled_dispatcher({})

        # Recovery + SELECT + CAS + failed-UPDATE = 4
        assert mock_session.execute.call_count == 4

    async def test_multiple_due_processed_in_order(self, mock_session, mock_redis):
        """Несколько due reminder'ов — все обрабатываются."""
        from app.worker import scheduled_dispatcher

        row1 = _make_due_row(payload={"text": "first"})
        row2 = _make_due_row(payload={"text": "second"})
        cas1 = {"id": row1[0], "user_id": row1[1], "bookmark_id": None, "payload": row1[6], "retry_count": 0}
        cas2 = {"id": row2[0], "user_id": row2[1], "bookmark_id": None, "payload": row2[6], "retry_count": 0}

        mock_session.execute = AsyncMock(side_effect=[
            _ExecResult(rowcount=0),                  # recovery
            _ExecResult(all_rows=[row1, row2]),
            _ExecResult(scalar=cas1),  # CAS row1
            _ExecResult(rowcount=1),    # mark sent row1
            _ExecResult(scalar=cas2),  # CAS row2
            _ExecResult(rowcount=1),    # mark sent row2
        ])

        send_mock = AsyncMock(return_value={"message_id": 100})

        with patch("app.worker.scheduled.async_session") as mk_sess, \
             patch("app.worker.scheduled._send_message", send_mock), \
             patch("app.worker.scheduled.aioredis_from_url", return_value=mock_redis):
            mk_sess.return_value.__aenter__.return_value = mock_session
            await scheduled_dispatcher({})

        assert send_mock.call_count == 2

    async def test_payload_text_fallback_when_empty(self, mock_session, mock_redis):
        """payload без text — отправляем дефолтный «Напоминание»."""
        from app.worker import scheduled_dispatcher

        row = _make_due_row(payload={})  # пустой payload
        cas = {"id": row[0], "user_id": row[1], "bookmark_id": None, "payload": {}, "retry_count": 0}
        mock_session.execute = AsyncMock(side_effect=[
            _ExecResult(rowcount=0),   # recovery
            _ExecResult(all_rows=[row]),
            _ExecResult(scalar=cas),
            _ExecResult(rowcount=1),
        ])
        send_mock = AsyncMock(return_value={"message_id": 1})

        with patch("app.worker.scheduled.async_session") as mk_sess, \
             patch("app.worker.scheduled._send_message", send_mock), \
             patch("app.worker.scheduled.aioredis_from_url", return_value=mock_redis):
            mk_sess.return_value.__aenter__.return_value = mock_session
            await scheduled_dispatcher({})

        sent_text = send_mock.call_args.args[1]
        # Не падаем, пишем что-то осмысленное
        assert sent_text  # не пустая строка


# ──────────────────────────────────────────────────
# auto_done_reminders
# ──────────────────────────────────────────────────


class TestAutoDoneReminders:
    async def test_marks_old_sent_reminders_as_auto_done(self, mock_session):
        """sent_at < now()-24h → status='auto_done'."""
        from app.worker import auto_done_reminders

        mock_session.execute = AsyncMock(return_value=_ExecResult(rowcount=3))

        with patch("app.worker.scheduled.async_session") as mk_sess:
            mk_sess.return_value.__aenter__.return_value = mock_session
            await auto_done_reminders({})

        # UPDATE выполнен ровно один раз
        assert mock_session.execute.call_count == 1
        assert mock_session.commit.called

    async def test_no_old_reminders_noop(self, mock_session):
        """rowcount=0 — лог, без падения."""
        from app.worker import auto_done_reminders

        mock_session.execute = AsyncMock(return_value=_ExecResult(rowcount=0))

        with patch("app.worker.scheduled.async_session") as mk_sess:
            mk_sess.return_value.__aenter__.return_value = mock_session
            await auto_done_reminders({})  # не должен бросить

        assert mock_session.commit.called


# ──────────────────────────────────────────────────
# Reminder buttons builder
# ──────────────────────────────────────────────────


class TestReminderButtons:
    def test_builds_done_and_snooze_buttons(self):
        from app.worker import _reminder_buttons

        sm_id = uuid4()
        markup = _reminder_buttons(str(sm_id))
        assert "inline_keyboard" in markup
        kb = markup["inline_keyboard"]
        # Хотя бы одна строка с двумя кнопками
        assert len(kb) >= 1
        flat = [btn for row in kb for btn in row]
        labels = [b["text"] for b in flat]
        callbacks = [b["callback_data"] for b in flat]
        # Выполнено + Продлить (или Snooze)
        assert any("Выполнено" in l or "✅" in l for l in labels)
        assert any("Продлить" in l or "💤" in l for l in labels)
        # Callback data содержит sm_id
        assert any(str(sm_id) in cb for cb in callbacks)


# ──────────────────────────────────────────────────
# Cron registration
# ──────────────────────────────────────────────────


class TestCronRegistration:
    def test_scheduled_dispatcher_registered_every_minute(self):
        """WorkerSettings.cron_jobs содержит scheduled_dispatcher."""
        from app.worker import WorkerSettings

        names = [getattr(c, "name", None) or str(c) for c in WorkerSettings.cron_jobs]
        joined = " ".join(names)
        assert "scheduled_dispatcher" in joined

    def test_auto_done_reminders_registered(self):
        from app.worker import WorkerSettings

        names = [getattr(c, "name", None) or str(c) for c in WorkerSettings.cron_jobs]
        joined = " ".join(names)
        assert "auto_done_reminders" in joined
