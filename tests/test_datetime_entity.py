"""T19 (bookmark-brain-4nc): Bot API 9.5 date_time MessageEntity reading.

Tests verify что бот корректно вытаскивает unix_time из entity и пропускает
текстовый парсер в этом случае.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest


def _make_entity(unix_time: int, offset: int = 0, length: int = 5):
    ent = MagicMock()
    ent.type = "date_time"
    ent.offset = offset
    ent.length = length
    ent.unix_time = unix_time
    ent.date_time_format = "yMMMd"
    return ent


def _make_text_link_entity():
    ent = MagicMock()
    ent.type = "text_link"
    ent.offset = 0
    ent.length = 4
    ent.url = "https://example.com"
    ent.unix_time = None
    return ent


def _make_msg(text: str, entities=None, caption_entities=None):
    msg = MagicMock()
    msg.text = text
    msg.entities = entities
    msg.caption_entities = caption_entities
    return msg


# ──────────────────────────────────────────────────
# extract_first_datetime_entity
# ──────────────────────────────────────────────────


class TestExtractDatetimeEntity:
    def test_extracts_unix_time_from_entity(self):
        from bot.handlers.reminders import extract_first_datetime_entity
        ts = int(datetime(2026, 5, 12, 9, 0, 0, tzinfo=timezone.utc).timestamp())
        msg = _make_msg("завтра в 9", entities=[_make_entity(ts)])
        dt = extract_first_datetime_entity(msg)
        assert dt is not None
        assert dt.tzinfo is timezone.utc
        assert int(dt.timestamp()) == ts

    def test_returns_none_when_no_entities(self):
        from bot.handlers.reminders import extract_first_datetime_entity
        msg = _make_msg("через час", entities=None)
        assert extract_first_datetime_entity(msg) is None

    def test_returns_none_when_no_datetime_type(self):
        from bot.handlers.reminders import extract_first_datetime_entity
        msg = _make_msg("через час", entities=[_make_text_link_entity()])
        assert extract_first_datetime_entity(msg) is None

    def test_picks_first_datetime_among_multiple(self):
        """Если несколько date_time entities — берём первый (по порядку появления в тексте)."""
        from bot.handlers.reminders import extract_first_datetime_entity
        ts1 = int(datetime(2026, 5, 12, 9, 0, 0, tzinfo=timezone.utc).timestamp())
        ts2 = int(datetime(2026, 5, 13, 9, 0, 0, tzinfo=timezone.utc).timestamp())
        msg = _make_msg(
            "завтра в 9 или послезавтра",
            entities=[_make_entity(ts1, offset=0), _make_entity(ts2, offset=20)],
        )
        dt = extract_first_datetime_entity(msg)
        assert int(dt.timestamp()) == ts1

    def test_handles_caption_entities_too(self):
        from bot.handlers.reminders import extract_first_datetime_entity
        ts = int(datetime(2026, 5, 12, 9, 0, 0, tzinfo=timezone.utc).timestamp())
        msg = _make_msg("photo caption", entities=None, caption_entities=[_make_entity(ts)])
        dt = extract_first_datetime_entity(msg)
        assert dt is not None
        assert int(dt.timestamp()) == ts

    def test_invalid_unix_time_skipped(self):
        from bot.handlers.reminders import extract_first_datetime_entity
        ent = MagicMock()
        ent.type = "date_time"
        ent.unix_time = "not a number"
        msg = _make_msg("test", entities=[ent])
        # Должно скипнуться без exception
        assert extract_first_datetime_entity(msg) is None

    def test_supports_aiogram_enum_type(self):
        """aiogram может отдавать тип как Enum с .value, не строкой."""
        from bot.handlers.reminders import extract_first_datetime_entity
        ts = int(datetime(2026, 5, 12, 9, 0, 0, tzinfo=timezone.utc).timestamp())
        ent = MagicMock()
        # Мимикрируем Enum: type — объект с .value="date_time"
        type_enum = MagicMock()
        type_enum.value = "date_time"
        ent.type = type_enum
        ent.unix_time = ts
        msg = _make_msg("test", entities=[ent])
        dt = extract_first_datetime_entity(msg)
        assert dt is not None
        assert int(dt.timestamp()) == ts


# ──────────────────────────────────────────────────
# Reply-handler integration: entity bypasses parser
# ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    async def _fake(*_a, **_k):
        return "fake-token"
    import bot.handlers.start
    monkeypatch.setattr(bot.handlers.start, "_ensure_user", _fake)


@pytest.fixture
def api():
    a = AsyncMock()
    a.get_me = AsyncMock(return_value={
        "id": "u1", "telegram_id": 999, "timezone": "Europe/Moscow",
    })
    a.create_reminder = AsyncMock(return_value={"id": "rem-1"})
    a.update_reminder = AsyncMock(return_value={"id": "rem-1"})
    return a


@pytest.fixture
def store():
    s = AsyncMock()
    s.get_reminder_pending = AsyncMock(return_value=None)
    s.get_reminder_snooze = AsyncMock(return_value=None)
    s.get_reminder_fallback = AsyncMock(return_value=None)
    s.delete_reminder_pending = AsyncMock()
    s.delete_reminder_snooze = AsyncMock()
    s.pop_reminder_fallback = AsyncMock(return_value=None)
    s.store_reminder_fallback = AsyncMock()
    return s


def _make_reply(text: str, entity_unix: int | None = None, reply_to_msg_id: int = 42):
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock(id=100)
    msg.message_id = reply_to_msg_id + 1
    msg.from_user = MagicMock(id=999, username="t", first_name="T")
    rt = MagicMock(message_id=reply_to_msg_id)
    msg.reply_to_message = rt

    if entity_unix is not None:
        msg.entities = [_make_entity(entity_unix, offset=0, length=len(text))]
    else:
        msg.entities = None
    msg.caption_entities = None

    msg.answer = AsyncMock()
    return msg


class TestEntityBypassesParser:
    async def test_entity_used_in_pending_create(self, api, store):
        """Reply на pending offer с entity → reminder создан с entity timestamp,
        парсер не вызывается."""
        from bot.handlers.reminders import handle_reminder_reply

        bid = str(uuid4())
        store.pop_reminder_pending = AsyncMock(return_value={"kind": "bookmark", "bookmark_id": bid})
        store.pop_reminder_snooze = AsyncMock(return_value=None)

        future_ts = int((datetime.now(timezone.utc) + timedelta(hours=2)).timestamp())
        msg = _make_reply("через 2 часа", entity_unix=future_ts)

        handled = await handle_reminder_reply(msg, api, store)
        assert handled is True
        api.create_reminder.assert_called_once()
        args = api.create_reminder.call_args.args
        # second positional arg = fire_at_iso
        fire_at_iso = args[1]
        # Должен быть в пределах 1 секунды от future_ts
        sent_dt = datetime.fromisoformat(fire_at_iso)
        assert abs(int(sent_dt.timestamp()) - future_ts) < 5

    async def test_entity_in_past_rejected(self, api, store):
        """Entity с unix_time в прошлом → отказ, reminder не создан."""
        from bot.handlers.reminders import handle_reminder_reply

        bid = str(uuid4())
        store.pop_reminder_pending = AsyncMock(return_value={"kind": "bookmark", "bookmark_id": bid})
        store.pop_reminder_snooze = AsyncMock(return_value=None)

        past_ts = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
        msg = _make_reply("вчера", entity_unix=past_ts)

        handled = await handle_reminder_reply(msg, api, store)
        assert handled is True
        api.create_reminder.assert_not_called()
        sent = msg.answer.call_args.args[0]
        assert "прошлом" in sent.lower() or "будущ" in sent.lower()

    async def test_no_entity_falls_back_to_parser(self, api, store):
        """Без entity — текущий поведение (через парсер)."""
        from bot.handlers.reminders import handle_reminder_reply

        bid = str(uuid4())
        store.pop_reminder_pending = AsyncMock(return_value={"kind": "bookmark", "bookmark_id": bid})
        store.pop_reminder_snooze = AsyncMock(return_value=None)

        msg = _make_reply("через час", entity_unix=None)

        handled = await handle_reminder_reply(msg, api, store)
        assert handled is True
        api.create_reminder.assert_called_once()  # парсер сработал
