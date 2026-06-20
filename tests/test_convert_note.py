"""Tests для конвертации дубля-заметки в список/напоминание (c6ti).

Кнопки 📋/🔔 на подтверждении «сохрани как новую»:
- 📋 → структурирует текст заметки в список СРАЗУ (allow_single: фраза → 1 пункт),
  без переспроса «пришли пункты» (текст уже отправлен);
- 🔔 → reminder_pending kind=bookmark (текст из закладки, ловит reminder-reply).
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


# ── saved_new_keyboard ──


def test_saved_new_keyboard_has_both_actions():
    from bot.handlers.tasks.convert import saved_new_keyboard
    kb = saved_new_keyboard(BID)
    datas = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    assert f"d2l:{BID}" in datas
    assert f"d2r:{BID}" in datas


# ── d2l: сделать списком (вариант б — сразу, без переспроса) ──


async def test_convert_to_list_makes_list_with_allow_single(monkeypatch):
    from bot.handlers.tasks import convert
    cb = _make_callback(f"d2l:{BID}")
    api = AsyncMock()
    api.structure_as_list = AsyncMock(return_value={"structured": True, "tasks_count": 1})
    store = AsyncMock()
    mat = AsyncMock()
    monkeypatch.setattr(convert, "_materialize_list", mat)

    await convert.cb_convert_to_list(cb, api, store)

    # allow_single=True — фраза-заголовок тоже становится списком, без переспроса
    _, kwargs = api.structure_as_list.call_args
    assert kwargs.get("allow_single") is True
    mat.assert_awaited_once()
    cb.message.edit_text.assert_awaited()  # «📋 Готово»


async def test_convert_to_list_empty_note_answers(monkeypatch):
    from bot.handlers.tasks import convert
    cb = _make_callback(f"d2l:{BID}")
    api = AsyncMock()
    api.structure_as_list = AsyncMock(return_value={"structured": False, "reason": "empty"})
    store = AsyncMock()
    mat = AsyncMock()
    monkeypatch.setattr(convert, "_materialize_list", mat)

    await convert.cb_convert_to_list(cb, api, store)

    mat.assert_not_called()
    cb.answer.assert_awaited()  # «Пустая заметка — нечего в список»


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
