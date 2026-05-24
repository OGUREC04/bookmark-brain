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
    import bot.common.auth
    monkeypatch.setattr(bot.common.auth, "ensure_user", _fake)


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

        with patch("bot.handlers.tasks.dedup._rerender_at_bottom") as rerender_mock:
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

        with patch("bot.handlers.tasks.dedup._rerender_at_bottom") as rerender_mock:
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

        with patch("bot.handlers.tasks.dedup._rerender_at_bottom") as rerender_mock:
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
        with patch("bot.handlers.tasks.dedup._rerender_at_bottom"):
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


# ──────────────────────────────────────────────────
# Bug 2026-05-11 corner case: dedup "update" intent на task_list
# должен показать обновлённый список (юзер забыл что список уже есть,
# отправил новый — ожидает увидеть результат).
# ──────────────────────────────────────────────────


def _make_reply_message(text: str = "обнови"):
    """Юзер-сообщение с reply на bot alert."""
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock(id=100)
    msg.message_id = 600
    msg.from_user = MagicMock(id=999)
    msg.bot = AsyncMock()
    msg.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
    msg.delete = AsyncMock()
    replied = AsyncMock()
    replied.message_id = 555
    replied.edit_text = AsyncMock()
    msg.reply_to_message = replied
    return msg, replied


def _make_pending_message(text: str = "обнови"):
    """Юзер-сообщение БЕЗ reply (pending dedup variant)."""
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock(id=100)
    msg.message_id = 600
    msg.from_user = MagicMock(id=999)
    msg.bot = AsyncMock()
    msg.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
    msg.bot.edit_message_text = AsyncMock()
    msg.delete = AsyncMock()
    msg.reply_to_message = None
    return msg


def _make_task_list_bm(bid: str = "old-bid", tasks: list | None = None):
    return {
        "id": bid,
        "title": "Покупки",
        "structured_data": {
            "type": "task_list",
            "tasks": tasks or [
                {"text": "молоко", "done": False, "deadline": None, "note": None},
                {"text": "хлеб", "done": False, "deadline": None, "note": None},
            ],
        },
    }


class TestDedupUpdateRerendersTaskList:
    async def test_general_dedup_update_shows_updated_list(self):
        """Bug 2026-05-11 follow-up:
        intent=update + old is task_list → должен ОТРЕНДЕРИТЬ обновлённый
        список (либо через _rerender_at_bottom либо send_message), иначе
        юзер не видит результата.
        """
        from bot.handlers.tasks import _handle_general_dedup_reply

        msg, _ = _make_reply_message("обнови")
        api = AsyncMock()
        new_bm = _make_task_list_bm("new-bid", [
            {"text": "молоко", "done": False, "deadline": None, "note": None},
            {"text": "хлеб", "done": False, "deadline": None, "note": None},
        ])
        old_bm = _make_task_list_bm("old-bid")
        api.get_bookmark = AsyncMock(side_effect=[new_bm, old_bm])
        api.update_bookmark = AsyncMock()
        api.delete_bookmark = AsyncMock()

        store = AsyncMock()
        store.pop_general_dedup = AsyncMock()
        store.clear_pending_dedup = AsyncMock()
        store.list_task_list_message_ids = AsyncMock(return_value=[])
        store.bind_list_message = AsyncMock()

        dedup = {"new_bid": "new-bid", "old_bid": "old-bid"}

        with patch("bot.handlers.tasks.dedup._rerender_at_bottom") as rerender_mock:
            rerender_mock.return_value = None
            await _handle_general_dedup_reply(msg, api, store, dedup)

        # Главное: юзер увидел обновлённый список
        rendered = rerender_mock.called or msg.bot.send_message.called
        assert rendered, (
            "intent=update на task_list НЕ показал обновлённый список юзеру"
        )

    async def test_general_dedup_update_non_task_list_no_rerender(self):
        """Anti-regression: для НЕ-task_list (статья, голос) — re-render не нужен,
        достаточно "Оригинал обновлён"."""
        from bot.handlers.tasks import _handle_general_dedup_reply

        msg, _ = _make_reply_message("обнови")
        api = AsyncMock()
        # Не task_list — статья
        new_bm = {"id": "new", "title": "Статья", "summary": "...",
                  "structured_data": None}
        old_bm = {"id": "old", "title": "Старая статья", "summary": "...",
                  "structured_data": None}
        api.get_bookmark = AsyncMock(side_effect=[new_bm, old_bm])
        api.update_bookmark = AsyncMock()
        api.delete_bookmark = AsyncMock()

        store = AsyncMock()
        store.pop_general_dedup = AsyncMock()
        store.clear_pending_dedup = AsyncMock()
        store.list_task_list_message_ids = AsyncMock(return_value=[])

        dedup = {"new_bid": "new-bid", "old_bid": "old-bid"}

        with patch("bot.handlers.tasks.dedup._rerender_at_bottom") as rerender_mock:
            await _handle_general_dedup_reply(msg, api, store, dedup)

        # НЕ task_list → не вызываем rerender и не шлём список
        assert not rerender_mock.called
        # send_message может быть вызван для других целей, главное rerender не активен
        # Confirm "Оригинал обновлён" редактирует replied
        # (поведение не регрессировано)

    async def test_pending_dedup_update_shows_updated_list(self):
        """Тот же кейс для handle_pending_dedup (без reply, по ключевому слову)."""
        from bot.handlers.tasks import handle_pending_dedup

        msg = _make_pending_message("обнови")
        api = AsyncMock()
        new_bm = _make_task_list_bm("new-bid")
        old_bm = _make_task_list_bm("old-bid")
        api.get_bookmark = AsyncMock(side_effect=[new_bm, old_bm])
        api.update_bookmark = AsyncMock()
        api.delete_bookmark = AsyncMock()

        store = AsyncMock()
        store.list_task_list_message_ids = AsyncMock(return_value=[])
        store.bind_list_message = AsyncMock()

        dedup = {"new_bid": "new-bid", "old_bid": "old-bid"}

        with patch("bot.handlers.tasks.dedup._rerender_at_bottom") as rerender_mock:
            rerender_mock.return_value = None
            await handle_pending_dedup(
                msg, api, store, dedup, intent="update", alert_msg_id=555,
            )

        rendered = rerender_mock.called or msg.bot.send_message.called
        assert rendered, (
            "handle_pending_dedup intent=update task_list не показал список"
        )

    async def test_general_dedup_save_new_redispatches_reminders(self):
        """ied: «сохрани как новую» при near-dup должен переиграть
        reminder_decision (worker пропустил dispatch). Иначе напоминание
        из near-dup'нутого сообщения тихо теряется."""
        from bot.handlers.tasks import _handle_general_dedup_reply

        msg, _ = _make_reply_message("сохрани как новую")
        api = AsyncMock()
        # Новая закладка — НЕ task_list (near-dup только на non-task-list),
        # materialize будет no-op, redispatch — основное действие.
        api.get_bookmark = AsyncMock(return_value={
            "id": "new-bid", "title": "Купить хлеб", "structured_data": None,
        })
        api.redispatch_reminders = AsyncMock(return_value={"enqueued": True})

        store = AsyncMock()
        store.pop_general_dedup = AsyncMock()
        store.clear_pending_dedup = AsyncMock()

        dedup = {"new_bid": "new-bid", "old_bid": "old-bid", "src_msg_id": 42}

        await _handle_general_dedup_reply(msg, api, store, dedup)

        api.redispatch_reminders.assert_awaited_once()
        # chat_id передан как keyword
        assert api.redispatch_reminders.await_args.kwargs.get("chat_id") == 100
        # bookmark_id = new_bid
        assert "new-bid" in api.redispatch_reminders.await_args.args

    async def test_pending_dedup_save_new_redispatches_reminders(self):
        """Тот же ied-кейс для handle_pending_dedup (без reply)."""
        from bot.handlers.tasks import handle_pending_dedup

        msg = _make_pending_message("сохрани как новую")
        api = AsyncMock()
        api.get_bookmark = AsyncMock(return_value={
            "id": "new-bid", "title": "Купить хлеб", "structured_data": None,
        })
        api.redispatch_reminders = AsyncMock(return_value={"enqueued": True})

        store = AsyncMock()
        store.pop_general_dedup = AsyncMock()
        store.clear_pending_dedup = AsyncMock()

        dedup = {"new_bid": "new-bid", "old_bid": "old-bid", "src_msg_id": 42}

        await handle_pending_dedup(
            msg, api, store, dedup, intent="save_new", alert_msg_id=555,
        )

        api.redispatch_reminders.assert_awaited_once()
        assert api.redispatch_reminders.await_args.kwargs.get("chat_id") == 100

    async def test_redispatch_failure_does_not_crash_save_new(self):
        """Best-effort: если redispatch упал (backend 500), save_new всё равно
        отрабатывает без исключения наружу."""
        from bot.handlers.tasks import _handle_general_dedup_reply

        msg, _ = _make_reply_message("оставь обе")
        api = AsyncMock()
        api.get_bookmark = AsyncMock(return_value={
            "id": "new-bid", "title": "X", "structured_data": None,
        })
        api.redispatch_reminders = AsyncMock(side_effect=Exception("backend 500"))

        store = AsyncMock()
        store.pop_general_dedup = AsyncMock()
        store.clear_pending_dedup = AsyncMock()

        dedup = {"new_bid": "new-bid", "old_bid": "old-bid", "src_msg_id": 42}

        # Не должно бросить
        await _handle_general_dedup_reply(msg, api, store, dedup)
        api.redispatch_reminders.assert_awaited_once()

    async def test_user_source_message_deleted_on_update(self):
        """Юзер-сообщение со списком (которое он отправил, забыв про старый)
        должно быть удалено — иначе остаётся дубликат текста в чате."""
        from bot.handlers.tasks import _handle_general_dedup_reply

        msg, _ = _make_reply_message("обнови")
        api = AsyncMock()
        new_bm = _make_task_list_bm("new-bid")
        old_bm = _make_task_list_bm("old-bid")
        api.get_bookmark = AsyncMock(side_effect=[new_bm, old_bm])
        api.update_bookmark = AsyncMock()
        api.delete_bookmark = AsyncMock()

        store = AsyncMock()
        store.pop_general_dedup = AsyncMock()
        store.clear_pending_dedup = AsyncMock()
        store.list_task_list_message_ids = AsyncMock(return_value=[])
        store.bind_list_message = AsyncMock()

        dedup = {"new_bid": "new-bid", "old_bid": "old-bid"}

        with patch("bot.handlers.tasks.dedup._rerender_at_bottom"):
            await _handle_general_dedup_reply(msg, api, store, dedup)

        msg.delete.assert_called()
