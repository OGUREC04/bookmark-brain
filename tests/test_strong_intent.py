"""Тесты для T13: pre-AI strong intent detector + 3-button flow."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest


# ──────────────────────────────────────────────────
# Detector: is_strong_intent
# ──────────────────────────────────────────────────


class TestIsStrongIntent:
    @pytest.mark.parametrize("text", [
        "надо купить хлеб",
        "Надо купить хлеб",
        "нужно позвонить маме",
        "Не забыть оплатить счёт",
        "не забыти позвонить",
        "срочно доделать отчёт",
        "обязательно сходить",
        "обязан выполнить",
    ])
    def test_strong_match(self, text):
        from bot.handlers.reminders import is_strong_intent
        assert is_strong_intent(text), f"Expected strong: {text!r}"

    @pytest.mark.parametrize("text", [
        "купить хлеб",
        "позвонить маме",
        "думаю надо как-то сделать",  # не в начале
        "нужное направление",         # полное слово другое
        "статья про React",
        "",
        "   ",
        "ладно",
        "9 утра",
    ])
    def test_not_strong(self, text):
        from bot.handlers.reminders import is_strong_intent
        assert not is_strong_intent(text), f"Expected NOT strong: {text!r}"


# ──────────────────────────────────────────────────
# 3-button prompt + state save
# ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    async def _fake(*_a, **_k):
        return "fake-token"
    import bot.common.auth
    monkeypatch.setattr(bot.common.auth, "ensure_user", _fake)


@pytest.fixture
def api():
    a = AsyncMock()
    a.get_me = AsyncMock(return_value={
        "id": "u1", "telegram_id": 999, "timezone": "Europe/Moscow",
    })
    a.create_reminder = AsyncMock(return_value={"id": "rem-1"})
    a.create_bookmark = AsyncMock(return_value={"id": "bid-1"})
    return a


@pytest.fixture
def store():
    s = AsyncMock()
    redis_mock = AsyncMock()
    redis_mock.set = AsyncMock()
    redis_mock.getdel = AsyncMock(return_value=None)
    redis_mock.get = AsyncMock(return_value=None)
    s._get = AsyncMock(return_value=redis_mock)
    return s


def _make_msg(text: str):
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock(id=100)
    msg.message_id = 42
    msg.from_user = MagicMock(id=999, username="testuser", first_name="Test")
    prompt = MagicMock()
    prompt.message_id = 43
    prompt.delete = AsyncMock()
    msg.answer = AsyncMock(return_value=prompt)
    return msg


def _make_callback(data: str, msg_id: int = 43):
    cb = AsyncMock()
    cb.data = data
    cb.message = AsyncMock()
    cb.message.chat = MagicMock(id=100)
    cb.message.message_id = msg_id
    cb.message.edit_text = AsyncMock()
    cb.message.delete = AsyncMock()
    cb.from_user = MagicMock(id=999, username="testuser", first_name="Test")
    cb.answer = AsyncMock()
    return cb


class TestStrongIntentPromptHandler:
    async def test_strong_message_shows_3_buttons(self, api, store):
        from bot.handlers.reminders import handle_strong_intent_message
        msg = _make_msg("надо купить хлеб")
        await handle_strong_intent_message(msg, api, store)

        msg.answer.assert_called_once()
        kwargs = msg.answer.call_args.kwargs
        markup = kwargs.get("reply_markup")
        assert markup is not None
        kb = markup["inline_keyboard"]
        flat = [b for row in kb for b in row]
        assert len(flat) == 3
        callbacks = [b["callback_data"] for b in flat]
        assert "rstrong_b" in callbacks  # Напомнить
        assert "rstrong_n" in callbacks  # Заметка
        assert "rstrong_x" in callbacks  # ✕

    async def test_non_strong_message_skips(self, api, store):
        from aiogram.dispatcher.event.bases import SkipHandler
        from bot.handlers.reminders import handle_strong_intent_message
        msg = _make_msg("статья про React")

        with pytest.raises(SkipHandler):
            await handle_strong_intent_message(msg, api, store)
        msg.answer.assert_not_called()

    async def test_state_saved_in_redis(self, api, store):
        from bot.handlers.reminders import handle_strong_intent_message
        msg = _make_msg("надо позвонить маме")
        await handle_strong_intent_message(msg, api, store)

        # d71: централизованный метод store_reminder_strong.
        store.store_reminder_strong.assert_called_once()
        args = store.store_reminder_strong.call_args.args
        # (chat_id, prompt_msg_id, state_dict)
        assert args[0] == 100
        assert args[1] == 43
        assert isinstance(args[2], dict)
        assert "text" in args[2]


class TestStrongChoiceCancel:
    async def test_x_deletes_prompt_no_db_write(self, api, store):
        from bot.handlers.reminders import cb_strong_choice
        # State есть в Redis
        import json
        state_json = json.dumps({"text": "надо купить хлеб", "source_msg_id": 42, "parsed_dt_iso": None})
        store.pop_reminder_strong = AsyncMock(return_value=json.loads(state_json))

        cb = _make_callback("rstrong_x")
        await cb_strong_choice(cb, api, store)

        # ✕ → prompt-сообщение удалено или очищено, БД не трогается
        api.create_reminder.assert_not_called()
        api.create_bookmark.assert_not_called()


class TestStrongChoiceNote:
    async def test_note_creates_bookmark_with_anti_double_flag(self, api, store):
        from bot.handlers.reminders import cb_strong_choice
        import json
        state_json = json.dumps({
            "text": "надо купить хлеб",
            "source_msg_id": 42,
            "parsed_dt_iso": None,
        })
        store.pop_reminder_strong = AsyncMock(return_value=json.loads(state_json))

        cb = _make_callback("rstrong_n")
        await cb_strong_choice(cb, api, store)

        # bookmark создан
        api.create_bookmark.assert_called_once()
        kwargs = api.create_bookmark.call_args.kwargs
        assert kwargs.get("raw_text") == "надо купить хлеб"
        assert kwargs.get("source_message_id") == 42
        # reminder НЕ создан
        api.create_reminder.assert_not_called()
        # Anti-double flag set
        r_inst = store._get.return_value
        keys_set = [c.args[0] for c in r_inst.set.call_args_list]
        assert any(k == "strong_handled:100:42" for k in keys_set)


class TestStrongChoiceRemind:
    async def test_remind_with_parsed_time_creates_immediately(self, api, store):
        from bot.handlers.reminders import cb_strong_choice
        import json
        state_json = json.dumps({
            "text": "купить хлеб",
            "source_msg_id": 42,
            "parsed_dt_iso": "2026-05-12T06:00:00+00:00",
        })
        store.pop_reminder_strong = AsyncMock(return_value=json.loads(state_json))

        cb = _make_callback("rstrong_b")
        await cb_strong_choice(cb, api, store)

        api.create_reminder.assert_called_once()
        kwargs = api.create_reminder.call_args.kwargs
        assert kwargs.get("bookmark_id") is None
        assert kwargs.get("payload", {}).get("source") == "strong_intent"
        assert kwargs.get("payload", {}).get("text") == "купить хлеб"
        api.create_bookmark.assert_not_called()

    async def test_remind_without_time_asks_reply(self, api, store):
        from bot.handlers.reminders import cb_strong_choice
        import json
        state_json = json.dumps({
            "text": "купить хлеб",
            "source_msg_id": 42,
            "parsed_dt_iso": None,
        })
        store.pop_reminder_strong = AsyncMock(return_value=json.loads(state_json))

        cb = _make_callback("rstrong_b")
        await cb_strong_choice(cb, api, store)

        api.create_reminder.assert_not_called()
        # 12y: explicit pending через typed envelope
        store.store_reminder_pending_explicit.assert_called_once()
        args = store.store_reminder_pending_explicit.call_args.args
        # (chat_id, msg_id, text)
        assert "купить хлеб" in args[2]

    async def test_state_expired_returns_friendly_error(self, api, store):
        from bot.handlers.reminders import cb_strong_choice
        # state нет → getdel returns None
        store.pop_reminder_strong = AsyncMock(return_value=None)

        cb = _make_callback("rstrong_b")
        await cb_strong_choice(cb, api, store)

        api.create_reminder.assert_not_called()
        api.create_bookmark.assert_not_called()
        cb.answer.assert_called()


# ──────────────────────────────────────────────────
# Anti-double-offer in worker
# ──────────────────────────────────────────────────


class TestAntiDoubleOfferFlag:
    async def test_offer_skipped_when_strong_handled_flag_set(self):
        """Если worker видит strong_handled flag — offer не отправляется."""
        from app.worker import _maybe_offer_reminder

        bm = MagicMock()
        bm.id = uuid4()
        bm.structured_data = {"reminder_intent": True}
        bm.source_message_id = 42

        send_mock = AsyncMock()
        mock_redis = AsyncMock()
        # GET strong_handled:100:42 returns "1" → flag установлен
        mock_redis.get = AsyncMock(return_value="1")
        mock_redis.set = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch("app.worker.reminder_offer._send_message", send_mock), \
             patch("app.worker.reminder_offer.aioredis_from_url", return_value=mock_redis):
            await _maybe_offer_reminder(
                bookmark=bm, chat_id=100, silent=False,
            )

        send_mock.assert_not_called()
        # GET вызван (проверка флага)
        mock_redis.get.assert_called()
        get_keys = [c.args[0] for c in mock_redis.get.call_args_list]
        assert any("strong_handled:100:42" == k for k in get_keys)
