"""Tests: голосовой список — не удалять запись + срезать таймкоды.

Yandex Async STT (>30s) встраивает [MM:SS] в текст. Раньше это
попадало в каждый пункт списка. Голос-источник раньше удалялся как
«дубль» — теперь оставляем (это контент, не дубль текста).
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

# ───────────────────── preprocess_voice_list ─────────────────────


class TestVoiceListPreprocessing:
    def test_full_voice_transcript_cleaned(self):
        from bot.services.timestamps import strip_timestamps
        from bot.services.voice_list import preprocess_voice_list
        stt = (
            "[00:00] Сегодня нужно. [00:02] 1 Дочистить макеты. "
            "[00:05] По главной странице поиска. [00:08] 2 Сделай 3 Вьюга 100. "
            "[00:12] 3 [00:15] Сделать 3 задание по бизнесу. "
            "[00:19] 4 [00:21] Внести правки на сайт Тильда. "
            "[00:25] 5 Заказать справку студента. [00:30] Вроде все."
        )
        out = preprocess_voice_list(strip_timestamps(stt))
        lines = out.splitlines()
        # Преамбула «Сегодня нужно» удалена, 5 нумерованных пунктов.
        assert len(lines) == 5
        assert lines[0].startswith("1. Дочистить макеты")
        # Континуация склеена с пунктом 1
        assert "По главной странице поиска" in lines[0]
        # Bare digit «3» склеен со следующей строкой
        assert lines[2].startswith("3. Сделать 3 задание")
        # «Вроде все» приклеено к последнему пункту
        assert "Вроде все" in lines[4]

    def test_preamble_dropped(self):
        from bot.services.voice_list import preprocess_voice_list
        out = preprocess_voice_list("Мне нужно.\n1 Купить молоко.\n2 Позвонить маме.")
        assert "Мне нужно" not in out
        assert out.splitlines() == ["1. Купить молоко.", "2. Позвонить маме."]

    def test_bare_digit_merges_with_next(self):
        from bot.services.voice_list import preprocess_voice_list
        out = preprocess_voice_list("1 a\n2\nb\n3 c")
        assert out.splitlines() == ["1. a", "2. b", "3. c"]

    def test_no_digits_keeps_single_item(self):
        from bot.services.voice_list import preprocess_voice_list
        out = preprocess_voice_list("просто заметка без структуры")
        assert out == "просто заметка без структуры"

    def test_empty_passthrough(self):
        from bot.services.voice_list import preprocess_voice_list
        assert preprocess_voice_list("") == ""
        assert preprocess_voice_list("   \n  ") == ""

    def test_only_bare_digits_returns_empty(self):
        """M4 (code review): входной транскрипт только из голых цифр
        (STT-разрывы посреди молчания) → пустой результат. Caller
        должен фолбэчиться на full_text."""
        from bot.services.voice_list import preprocess_voice_list
        assert preprocess_voice_list("1\n2\n3") == ""

    def test_trailing_bare_digit_dropped(self):
        """Последняя голая цифра (STT добил «4.» без продолжения) —
        дропается как огрызок."""
        from bot.services.voice_list import preprocess_voice_list
        out = preprocess_voice_list("1 хлеб\n2 молоко\n3.")
        assert out.splitlines() == ["1. хлеб", "2. молоко"]

    def test_only_preamble_returns_empty(self):
        """Только преамбула без пунктов → пусто (caller фолбэчится)."""
        from bot.services.voice_list import preprocess_voice_list
        assert preprocess_voice_list("Сегодня нужно.\nЗапиши.") == ""


# ───────────────────── strip_timestamps ─────────────────────


class TestStripTimestamps:
    def test_strips_all_markers(self):
        from bot.services.timestamps import strip_timestamps
        out = strip_timestamps(
            "[00:00] Сегодня нужно. [00:02] 1 Дочистить макеты. "
            "[00:30] Вроде все."
        )
        assert "[00:" not in out
        assert "Сегодня нужно" in out
        assert "Дочистить макеты" in out

    def test_preserves_chunk_structure_as_lines(self):
        """[MM:SS] = границы chunks STT = разрезы. Заменяем на \\n,
        иначе AI получает одну строку → один пункт."""
        from bot.services.timestamps import strip_timestamps
        out = strip_timestamps(
            "[00:00] раз [00:02] два [00:05] три"
        )
        lines = out.splitlines()
        assert lines == ["раз", "два", "три"]

    def test_no_markers_passthrough(self):
        from bot.services.timestamps import strip_timestamps
        assert strip_timestamps("просто текст") == "просто текст"


# ───────────────────── _handle_voice_todo ─────────────────────


class TestVoiceTodoRawText:
    async def test_raw_text_has_no_timestamps(self, monkeypatch):
        """В создании bookmark идёт раw_text БЕЗ [MM:SS], иначе AI
        потащит таймкоды в каждый пункт списка."""
        import bot.handlers.media as md
        msg = MagicMock()
        msg.reply = AsyncMock()
        msg.chat = MagicMock(id=100)
        msg.message_id = 555
        api = AsyncMock()
        api.create_bookmark = AsyncMock()
        # onboarding tip — патчим чтобы не лезть в API
        monkeypatch.setattr(
            md.onboarding, "maybe_show_tip", AsyncMock(),
        )

        full_with_ts = (
            "[00:00] Сегодня нужно. [00:02] 1 Дочистить макеты. "
            "[00:08] 2 Сделать отчёт."
        )
        cleaned_with_ts = full_with_ts  # intent prefix не срезал
        await md._handle_voice_todo(
            msg, api, "tok", full_with_ts, cleaned_with_ts,
            file_id="f1", duration_float=35.0, silent=True,
        )

        api.create_bookmark.assert_awaited()
        kwargs = api.create_bookmark.await_args.kwargs
        assert "[00:" not in kwargs["raw_text"]
        assert kwargs["raw_text"].startswith("список задач:")
        assert "Дочистить макеты" in kwargs["raw_text"]
        # Reply с таймкодами — для навигации, оставляем
        msg.reply.assert_awaited()
        assert "[00:00]" in msg.reply.await_args.args[0]


# ───────────────── worker offer: is_media_src ─────────────────


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
    async def set(self, k, v, ex=None):
        self.store[k] = v
    async def delete(self, *ks):
        for k in ks:
            self.store.pop(k, None)
    async def aclose(self):
        pass


def _bookmark_obj(content_type=None, bid="bid-X"):
    bm = MagicMock()
    bm.id = bid
    bm.structured_data = {
        "type": "task_list",
        "tasks": [{"text": "a", "done": False}, {"text": "b", "done": False}],
    }
    bm.content_type = content_type
    return bm


class TestWorkerOfferMediaFlag:
    async def test_voice_source_sets_is_media_src_true(self):
        import json

        from app.worker import task_list_offer as mod
        fake = _FakeRedis()
        with patch.object(mod, "aioredis_from_url", return_value=fake), \
             patch.object(mod, "_send_message",
                          AsyncMock(return_value={"message_id": 777})):
            ok = await mod._maybe_offer_task_list(
                bookmark=_bookmark_obj(content_type="voice"),
                chat_id=42, message_id=9, silent=True,
            )
        assert ok is True
        payload = json.loads(fake.store["task_list_pending:42:777"])
        assert payload["is_media_src"] is True

    async def test_text_source_sets_is_media_src_false(self):
        import json

        from app.worker import task_list_offer as mod
        fake = _FakeRedis()
        with patch.object(mod, "aioredis_from_url", return_value=fake), \
             patch.object(mod, "_send_message",
                          AsyncMock(return_value={"message_id": 777})):
            await mod._maybe_offer_task_list(
                bookmark=_bookmark_obj(content_type=None),
                chat_id=42, message_id=9, silent=True,
            )
        payload = json.loads(fake.store["task_list_pending:42:777"])
        assert payload["is_media_src"] is False


# ───────────── bot tlc: do not delete media source ─────────────


def _make_cb(data: str = "tlc:bid-1", msg_id: int = 555):
    from aiogram.types import Message
    cb = AsyncMock()
    cb.data = data
    cb.message = MagicMock(spec=Message)
    cb.message.chat = MagicMock(id=100)
    cb.message.message_id = msg_id
    cb.message.bot = AsyncMock()
    cb.message.bot.send_message = AsyncMock(
        return_value=MagicMock(message_id=999)
    )
    cb.message.bot.pin_chat_message = AsyncMock()
    cb.message.bot.delete_message = AsyncMock()
    cb.message.delete = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.from_user = MagicMock(id=999)
    cb.answer = AsyncMock()
    return cb


@pytest.fixture(autouse=True)
def patch_ensure_user(monkeypatch):
    async def _fake(*_a, **_k):
        return "tok"
    import bot.common.auth
    monkeypatch.setattr(bot.common.auth, "ensure_user", _fake)


class TestConfirmDoesNotDeleteMedia:
    async def test_voice_source_kept(self):
        from bot.handlers.tasks import cb_tasklist_confirm
        cb = _make_cb()
        store = AsyncMock()
        store.pop_task_list_pending = AsyncMock(return_value={
            "bookmark_id": "bid-1", "src_msg_id": 42,
            "silent": True, "is_media_src": True,
        })
        api = AsyncMock()
        api.get_bookmark = AsyncMock(return_value={
            "title": "x",
            "structured_data": {"type": "task_list",
                                "tasks": [{"text": "a", "done": False}]},
        })
        api.update_bookmark = AsyncMock()

        await cb_tasklist_confirm(cb, api, store)

        # Offer-сообщение удаляется (это служебная кнопка)
        cb.message.delete.assert_awaited()
        # А исходное голосовое (src_msg_id=42) — НЕ трогаем
        for call in cb.message.bot.delete_message.await_args_list:
            assert call.args != (100, 42)

    async def test_post_confirm_dedup_alert_when_similar(self):
        """Worker нашёл similar и прокинул в pending → bot tlc после пина шлёт
        merge-дифф «Объединить списки?» (текущие пункты + что добавится)."""
        from bot.handlers.tasks import cb_tasklist_confirm
        cb = _make_cb()
        store = AsyncMock()
        store.pop_task_list_pending = AsyncMock(return_value={
            "bookmark_id": "bid-1", "src_msg_id": 9,
            "silent": False, "is_media_src": False,
            "similar": {
                "id": "old-bid", "title": "Старый",
                "done_count": 1, "total_count": 1,
                "created_at": "2026-05-19T10:00:00",
                "structured_data": {"type": "task_list", "tasks": [
                    {"text": "старый пункт", "done": True},
                ]},
            },
        })
        api = AsyncMock()
        api.get_bookmark = AsyncMock(return_value={
            "title": "x",
            "structured_data": {"type": "task_list",
                                "tasks": [{"text": "a", "done": False}]},
        })
        api.update_bookmark = AsyncMock()

        await cb_tasklist_confirm(cb, api, store)

        # Два send_message: первый — сам список (999), второй — dedup alert
        assert cb.message.bot.send_message.await_count >= 2
        alert_call = cb.message.bot.send_message.await_args_list[-1]
        alert_text = alert_call.args[1]
        assert "Объединить списки?" in alert_text   # merge-дифф headline
        assert "старый пункт" in alert_text          # текущий пункт старого списка
        assert "➕ a" in alert_text                   # добавится из нового
        # store_dedup_alert вызван
        store.store_dedup_alert.assert_awaited()
        args = store.store_dedup_alert.await_args.args
        assert args[:3] == (100, "bid-1", "old-bid")

    async def test_no_similar_no_alert(self):
        from bot.handlers.tasks import cb_tasklist_confirm
        cb = _make_cb()
        store = AsyncMock()
        store.pop_task_list_pending = AsyncMock(return_value={
            "bookmark_id": "bid-1", "src_msg_id": 9,
            "silent": False, "is_media_src": False, "similar": None,
        })
        api = AsyncMock()
        api.get_bookmark = AsyncMock(return_value={
            "title": "x",
            "structured_data": {"type": "task_list",
                                "tasks": [{"text": "a", "done": False}]},
        })
        api.update_bookmark = AsyncMock()

        await cb_tasklist_confirm(cb, api, store)

        # Только один send_message — сам список, без alert
        assert cb.message.bot.send_message.await_count == 1
        store.store_dedup_alert.assert_not_awaited()

    async def test_materialize_calls_create_when_task_list(self, monkeypatch):
        """save_new на near-dup → если new — task_list, материализуем
        (без повторного offer)."""
        from bot.handlers.tasks.dedup import _materialize_if_task_list
        api = AsyncMock()
        api.get_bookmark = AsyncMock(return_value={
            "structured_data": {"type": "task_list", "tasks": [{"text": "a"}]},
            "content_type": "voice",
        })
        store = AsyncMock()
        bot = AsyncMock()
        import bot.handlers.settings as settings_mod
        async def _silent(*_a, **_k): return True
        monkeypatch.setattr(settings_mod, "is_silent", _silent)
        # patch the helper we delegate to
        import bot.handlers.tasks.confirm as cf
        created = AsyncMock(return_value=999)
        monkeypatch.setattr(cf, "_create_and_pin_task_list", created)
        await _materialize_if_task_list(
            bot, 100, "tok", api, store, "new-bid", 42, user_id=7,
        )
        created.assert_awaited_once()
        # is_media_src=True (voice), silent=True переданы
        kwargs = created.await_args.kwargs
        assert kwargs["silent"] is True
        assert kwargs["is_media_src"] is True
        assert kwargs["src_msg_id"] == 42

    async def test_materialize_skips_when_not_task_list(self, monkeypatch):
        from bot.handlers.tasks.dedup import _materialize_if_task_list
        api = AsyncMock()
        api.get_bookmark = AsyncMock(return_value={
            "structured_data": None,  # обычная заметка
            "content_type": "text",
        })
        import bot.handlers.tasks.confirm as cf
        created = AsyncMock()
        monkeypatch.setattr(cf, "_create_and_pin_task_list", created)
        await _materialize_if_task_list(
            AsyncMock(), 100, "tok", api, AsyncMock(),
            "new-bid", 42, user_id=7,
        )
        created.assert_not_awaited()

    async def test_decline_with_general_dup_sends_alert(self):
        """tlx «Нет» + есть general_dup → отложенный near-dup alert
        отправляется, store_general_dedup пишется (reply-флоу подхватит)."""
        from bot.handlers.tasks import cb_tasklist_decline
        cb = _make_cb("tlx:bid-1")
        store = AsyncMock()
        store.pop_task_list_pending = AsyncMock(return_value={
            "bookmark_id": "bid-1", "src_msg_id": 42,
            "silent": False, "is_media_src": True,
            "similar": None,
            "general_dup": {
                "id": "old-bid", "title": "Старая закладка",
                "is_task_list": False, "similarity": 0.97,
                "created_at": "2026-05-18T10:00:00",
            },
        })
        api = AsyncMock()
        api.update_bookmark = AsyncMock(return_value={"title": "x"})

        # capture sent alert message_id для assert
        sent_msg = MagicMock(message_id=777)
        cb.message.bot.send_message = AsyncMock(return_value=sent_msg)

        await cb_tasklist_decline(cb, api, store)

        # 1) structured_data сброшен
        api.update_bookmark.assert_awaited_with("tok", "bid-1", {"structured_data": None})
        # 2) Alert отправлен с «почти такая же» (similarity >= 0.95)
        cb.message.bot.send_message.assert_awaited()
        alert_text = cb.message.bot.send_message.await_args.args[1]
        assert "почти такая же" in alert_text
        assert "Старая закладка" in alert_text
        # 3) general_dedup state сохранён в Redis (для reply-флоу)
        store.store_general_dedup.assert_awaited()
        args = store.store_general_dedup.await_args.args
        assert args[:4] == (100, 777, "bid-1", "old-bid")

    async def test_decline_without_general_dup_old_behavior(self):
        """tlx без general_dup → стандартная карточка/реакция, без alert."""
        from bot.handlers.tasks import cb_tasklist_decline
        cb = _make_cb("tlx:bid-1")
        store = AsyncMock()
        store.pop_task_list_pending = AsyncMock(return_value={
            "bookmark_id": "bid-1", "src_msg_id": 42,
            "silent": False, "is_media_src": False,
            "similar": None, "general_dup": None,
        })
        api = AsyncMock()
        api.update_bookmark = AsyncMock(return_value={"title": "x"})

        await cb_tasklist_decline(cb, api, store)

        store.store_general_dedup.assert_not_awaited()
        # Verbose: edit_text карточкой
        cb.message.edit_text.assert_awaited()

    async def test_text_source_still_deleted(self):
        from bot.handlers.tasks import cb_tasklist_confirm
        cb = _make_cb()
        store = AsyncMock()
        store.pop_task_list_pending = AsyncMock(return_value={
            "bookmark_id": "bid-1", "src_msg_id": 42,
            "silent": True, "is_media_src": False,
        })
        api = AsyncMock()
        api.get_bookmark = AsyncMock(return_value={
            "title": "x",
            "structured_data": {"type": "task_list",
                                "tasks": [{"text": "a", "done": False}]},
        })
        api.update_bookmark = AsyncMock()

        await cb_tasklist_confirm(cb, api, store)

        cb.message.bot.delete_message.assert_awaited_with(100, 42)
