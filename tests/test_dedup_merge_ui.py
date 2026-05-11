"""Tests for cb_dedup_merge UI flow.

Bug 2026-05-11: после успешного API merge (PATCH+DELETE 200/204) бот:
- не удалил сообщение нового списка
- не отрендерил обновлённый старый список
- юзер остался без визуальной обратной связи

Root cause:
1. delete_message в Telegram падал с TelegramBadRequest и был silent-swallow
2. Re-render отрабатывал ПОСЛЕ delete — если delete упал, re-render не давал
   видимой обратной связи (без логов вообще)

Fix:
- Re-render СНАЧАЛА (always-visible feedback)
- delete_message с explicit WARNING на failure
- unpin_chat_message ПЕРЕД delete (для pinned task-list сообщений)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    async def _fake(*_a, **_k):
        return "fake-token"
    import bot.handlers.start
    monkeypatch.setattr(bot.handlers.start, "_ensure_user", _fake)


@pytest.fixture(autouse=True)
def patch_is_silent(monkeypatch):
    """is_silent = False (verbose mode) для предсказуемости."""
    import bot.handlers.settings
    async def _fake(*_a, **_k):
        return False
    monkeypatch.setattr(bot.handlers.settings, "is_silent", _fake)


def _make_callback(new_bid: str):
    from aiogram.types import Message
    cb = AsyncMock()
    cb.data = f"dm:{new_bid}"
    # spec=Message — чтобы isinstance(cb.message, Message) проходил
    cb.message = MagicMock(spec=Message)
    cb.message.chat = MagicMock(id=100)
    cb.message.message_id = 555  # alert message id
    cb.message.bot = AsyncMock()
    cb.message.bot.delete_message = AsyncMock()
    cb.message.bot.send_message = AsyncMock(
        return_value=MagicMock(message_id=999)
    )
    cb.message.delete = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.from_user = MagicMock(id=999)
    cb.answer = AsyncMock()
    return cb


def _make_api(updated_old: dict | None = None):
    api = AsyncMock()
    api.merge_task_list = AsyncMock(return_value=updated_old or {
        "id": "old-bid",
        "title": "Список",
        "structured_data": {
            "type": "task_list",
            "tasks": [
                {"text": "молоко", "done": False, "deadline": None, "note": None},
                {"text": "хлеб", "done": False, "deadline": None, "note": None},
            ],
        },
    })
    return api


def _make_store(dedup_state: dict | None = None, old_msg_id: int | None = None):
    store = AsyncMock()
    if dedup_state is not None:
        store.pop_dedup_alert = AsyncMock(return_value=dedup_state)
    else:
        store.pop_dedup_alert = AsyncMock(return_value={
            "new_bid": "new-bid", "old_bid": "old-bid", "new_msg_id": 700,
        })
    store.unbind_list_message = AsyncMock()
    store.bind_list_message = AsyncMock()
    store.list_task_list_message_ids = AsyncMock(
        return_value=[old_msg_id] if old_msg_id else []
    )
    store.get_list_bookmark = AsyncMock(return_value="old-bid")
    store.force_last_seen = AsyncMock()
    return store


# ──────────────────────────────────────────────────
# Happy path: API succeeded + UI updated
# ──────────────────────────────────────────────────


class TestMergeHappyPath:
    async def test_renders_updated_list_visible_to_user(self):
        """Главное требование: после merge юзер ДОЛЖЕН увидеть обновлённый список —
        либо через send_message (если old_msg_id не найден), либо через
        _rerender_at_bottom.
        """
        from bot.handlers.tasks import cb_dedup_merge

        cb = _make_callback("new-bid")
        api = _make_api()
        store = _make_store(old_msg_id=None)  # старого msg в Redis нет — fallback на send

        with patch("bot.handlers.tasks._rerender_at_bottom") as rerender_mock:
            rerender_mock.return_value = None
            await cb_dedup_merge(cb, api, store)

        # API дёрнут
        api.merge_task_list.assert_called_once()
        # Юзер УВИДЕЛ обновлённый список — либо send_message либо rerender
        sent_via_new = cb.message.bot.send_message.called
        sent_via_rerender = rerender_mock.called
        assert sent_via_new or sent_via_rerender, (
            "Юзер не получил визуальной обратной связи после merge"
        )

    async def test_renders_via_rerender_when_old_msg_known(self):
        from bot.handlers.tasks import cb_dedup_merge

        cb = _make_callback("new-bid")
        api = _make_api()
        store = _make_store(old_msg_id=400)  # знаем старое сообщение

        with patch("bot.handlers.tasks._rerender_at_bottom") as rerender_mock:
            rerender_mock.return_value = None
            await cb_dedup_merge(cb, api, store)

        rerender_mock.assert_called_once()


# ──────────────────────────────────────────────────
# Telegram delete fails — UI всё равно должен обновиться
# ──────────────────────────────────────────────────


class TestDeleteFailFallback:
    async def test_render_happens_even_if_delete_new_msg_fails(self):
        """Bug 2026-05-11: delete_message новой выдал TelegramBadRequest →
        ранее silent swallow и re-render выполнялся успешно. Регрессия-тест:
        re-render выполняется НЕЗАВИСИМО от delete-результата."""
        from aiogram.exceptions import TelegramBadRequest
        from bot.handlers.tasks import cb_dedup_merge

        cb = _make_callback("new-bid")
        api = _make_api()
        store = _make_store(old_msg_id=None)

        # delete_message нового списка падает
        cb.message.bot.delete_message = AsyncMock(
            side_effect=TelegramBadRequest(
                method=MagicMock(),
                message="Bad Request: message can't be deleted",
            )
        )

        with patch("bot.handlers.tasks._rerender_at_bottom") as rerender_mock:
            rerender_mock.return_value = None
            await cb_dedup_merge(cb, api, store)

        # send_message всё равно вызван (юзер увидел список)
        assert cb.message.bot.send_message.called or rerender_mock.called

    async def test_warning_logged_on_delete_failure(self, caplog):
        """Silent failure hunter: delete_message failure ДОЛЖЕН логироваться
        как WARNING (не debug, не swallow без логов)."""
        import logging
        from aiogram.exceptions import TelegramBadRequest
        from bot.handlers.tasks import cb_dedup_merge

        cb = _make_callback("new-bid")
        api = _make_api()
        store = _make_store(old_msg_id=None)

        cb.message.bot.delete_message = AsyncMock(
            side_effect=TelegramBadRequest(
                method=MagicMock(),
                message="Bad Request: message can't be deleted",
            )
        )

        caplog.set_level(logging.WARNING, logger="bot.handlers.tasks")
        with patch("bot.handlers.tasks._rerender_at_bottom"):
            await cb_dedup_merge(cb, api, store)

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("delete" in r.message.lower() for r in warnings), (
            f"WARNING с упоминанием 'delete' не найден: {[r.message for r in warnings]}"
        )


# ──────────────────────────────────────────────────
# API merge fails — graceful error, не silent
# ──────────────────────────────────────────────────


class TestApiMergeFail:
    async def test_api_failure_shows_user_message(self):
        from bot.handlers.tasks import cb_dedup_merge

        cb = _make_callback("new-bid")
        api = _make_api()
        api.merge_task_list = AsyncMock(side_effect=Exception("backend 500"))
        store = _make_store()

        await cb_dedup_merge(cb, api, store)

        # callback.answer был с информативным сообщением
        cb.answer.assert_called()
        # И не было краша наружу

    async def test_state_already_consumed_returns_gracefully(self):
        """Bug 2026-05-11 родственный: second-click race — state уже pop'нут,
        бот не должен крашиться."""
        from bot.handlers.tasks import cb_dedup_merge

        cb = _make_callback("new-bid")
        api = _make_api()
        store = _make_store()
        store.pop_dedup_alert = AsyncMock(return_value=None)  # state нет

        await cb_dedup_merge(cb, api, store)

        # API не вызван
        api.merge_task_list.assert_not_called()
        # Юзер получил информативный ответ
        cb.answer.assert_called()
