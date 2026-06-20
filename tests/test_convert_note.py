"""Tests для конвертации дубля-заметки в список/напоминание (c6ti).

Кнопки 📋/🔔 на подтверждении «сохрани как новую»: structured → materialize;
single_phrase → спросить пункты (reply); напоминание → reminder_pending
kind=bookmark (текст из закладки, ловит существующий reminder-reply флоу).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest

BID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    async def _fake(*_a, **_k):
        return "fake-token"
    import bot.common.auth
    monkeypatch.setattr(bot.common.auth, "ensure_user", _fake)


@pytest.fixture(autouse=True)
def patch_is_silent(monkeypatch):
    import bot.handlers.settings
    async def _fake(*_a, **_k):
        return False
    monkeypatch.setattr(bot.handlers.settings, "is_silent", _fake)


def _make_callback(data: str):
    from aiogram.types import Message
    cb = AsyncMock()
    cb.data = data
    cb.message = MagicMock(spec=Message)
    cb.message.chat = MagicMock(id=100)
    cb.message.message_id = 555
    cb.message.bot = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock(return_value=MagicMock(message_id=777))
    cb.from_user = MagicMock(id=999)
    cb.answer = AsyncMock()
    return cb


def _make_reply_message(text: str, prompt_msg_id: int = 555):
    from aiogram.types import Message
    msg = MagicMock(spec=Message)
    msg.reply_to_message = MagicMock(message_id=prompt_msg_id)
    msg.message_id = 600
    msg.chat = MagicMock(id=100)
    msg.text = text
    msg.from_user = MagicMock(id=999)
    msg.bot = AsyncMock()
    msg.answer = AsyncMock()
    return msg


# ── saved_new_keyboard ──


def test_saved_new_keyboard_has_both_actions():
    from bot.handlers.tasks.convert import saved_new_keyboard
    kb = saved_new_keyboard(BID)
    datas = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    assert f"d2l:{BID}" in datas
    assert f"d2r:{BID}" in datas


# ── d2l: сделать списком ──


async def test_convert_to_list_structured_materializes(monkeypatch):
    from bot.handlers.tasks import convert
    cb = _make_callback(f"d2l:{BID}")
    api = AsyncMock()
    api.structure_as_list = AsyncMock(return_value={"structured": True, "tasks_count": 3})
    store = AsyncMock()
    mat = AsyncMock()
    monkeypatch.setattr(convert, "_materialize_list", mat)

    await convert.cb_convert_to_list(cb, api, store)

    api.structure_as_list.assert_awaited_once()
    mat.assert_awaited_once()
    cb.message.edit_text.assert_awaited()  # «📋 Готово»
    store.store_convert_list_pending.assert_not_called()


async def test_convert_to_list_single_phrase_asks_items(monkeypatch):
    from bot.handlers.tasks import convert
    cb = _make_callback(f"d2l:{BID}")
    api = AsyncMock()
    api.structure_as_list = AsyncMock(
        return_value={"structured": False, "reason": "single_phrase"}
    )
    store = AsyncMock()
    mat = AsyncMock()
    monkeypatch.setattr(convert, "_materialize_list", mat)

    await convert.cb_convert_to_list(cb, api, store)

    mat.assert_not_called()
    cb.message.edit_text.assert_awaited()  # промпт «пришли пункты»
    store.store_convert_list_pending.assert_awaited_once_with(100, 555, BID)


async def test_convert_to_list_rejects_bad_uuid():
    from bot.handlers.tasks import convert
    cb = _make_callback("d2l:not-a-uuid")
    api = AsyncMock()
    store = AsyncMock()

    await convert.cb_convert_to_list(cb, api, store)

    api.structure_as_list.assert_not_called()


# ── d2r: напоминание ──


async def test_convert_to_reminder_stores_bookmark_pending():
    from bot.handlers.tasks import convert
    cb = _make_callback(f"d2r:{BID}")
    api = AsyncMock()
    store = AsyncMock()

    await convert.cb_convert_to_reminder(cb, api, store)

    cb.message.answer.assert_awaited()  # промпт «Когда напомнить?»
    store.restore_reminder_pending.assert_awaited_once()
    args, _ = store.restore_reminder_pending.call_args
    assert args[0] == 100              # chat_id
    assert args[1] == 777              # prompt message_id
    assert args[2] == {"kind": "bookmark", "bookmark_id": BID}


# ── reply с пунктами ──


async def test_convert_list_reply_no_pending_returns_false():
    from bot.handlers.tasks.convert import handle_convert_list_reply
    msg = _make_reply_message("молоко, хлеб")
    store = AsyncMock()
    store.pop_convert_list_pending = AsyncMock(return_value=None)
    api = AsyncMock()

    result = await handle_convert_list_reply(msg, api, store)

    assert result is False
    api.structure_as_list.assert_not_called()


async def test_convert_list_reply_builds_list_allow_single(monkeypatch):
    from bot.handlers.tasks import convert
    msg = _make_reply_message("молоко, хлеб")
    store = AsyncMock()
    store.pop_convert_list_pending = AsyncMock(return_value=BID)
    api = AsyncMock()
    api.structure_as_list = AsyncMock(return_value={"structured": True, "tasks_count": 2})
    mat = AsyncMock()
    monkeypatch.setattr(convert, "_materialize_list", mat)

    result = await convert.handle_convert_list_reply(msg, api, store)

    assert result is True
    _, kwargs = api.structure_as_list.call_args
    assert kwargs.get("allow_single") is True
    mat.assert_awaited_once()


async def test_convert_list_reply_empty_text_reasks(monkeypatch):
    from bot.handlers.tasks import convert
    msg = _make_reply_message("")  # пустой reply
    store = AsyncMock()
    store.pop_convert_list_pending = AsyncMock(return_value=BID)
    api = AsyncMock()
    mat = AsyncMock()
    monkeypatch.setattr(convert, "_materialize_list", mat)

    result = await convert.handle_convert_list_reply(msg, api, store)

    assert result is True
    api.structure_as_list.assert_not_called()
    mat.assert_not_called()
    msg.answer.assert_awaited()  # переспросили
    store.store_convert_list_pending.assert_awaited()  # pending вернули
