"""Redis-based хранилище состояния, разделяемое между ботом и worker'ом.

Ключи:
- task_list_msg:{chat_id}:{message_id} -> bookmark_id (TTL 14 дней)
  Запоминаем какое сообщение в каком чате отображает какой task_list.
  Worker пишет при первичном edit, бот — при перерисовках.
  Reply-handler читает, чтобы понять на какой список юзер ответил.

- bot_msgs:{chat_id} -> SET<message_id> (TTL 48ч)
  Все сообщения, которые бот прислал в этот чат. Для /clean.
  Авто-pinned списки исключаем через дополнительное поле pinned:{chat_id}.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_LIST_TTL = 14 * 24 * 3600  # 14 дней
_CLEAN_TTL = 48 * 3600  # 48ч — Telegram разрешает удалять только до этого возраста
_CLEANUP_TTL = 5 * 60  # 5 мин — список «временных» сообщений после неудачного reply


class StateStore:
    def __init__(self, redis_url: str):
        self._url = redis_url
        self._r: Optional[aioredis.Redis] = None
        self._init_lock = asyncio.Lock()

    async def _get(self) -> aioredis.Redis:
        if self._r is None:
            async with self._init_lock:
                if self._r is None:
                    self._r = aioredis.from_url(self._url, decode_responses=True)
        return self._r

    async def close(self) -> None:
        if self._r is not None:
            await self._r.aclose()

    # ── task_list message registry ─────────────────────────

    async def bind_list_message(
        self, chat_id: int, message_id: int, bookmark_id: str
    ) -> None:
        r = await self._get()
        await r.set(
            f"task_list_msg:{chat_id}:{message_id}",
            bookmark_id,
            ex=_LIST_TTL,
        )

    async def get_list_bookmark(
        self, chat_id: int, message_id: int
    ) -> str | None:
        r = await self._get()
        return await r.get(f"task_list_msg:{chat_id}:{message_id}")

    async def unbind_list_message(self, chat_id: int, message_id: int) -> None:
        r = await self._get()
        await r.delete(f"task_list_msg:{chat_id}:{message_id}")

    # ── bot message tracker (for /clean) ───────────────────

    async def track_bot_message(
        self, chat_id: int, message_id: int, pinned: bool = False
    ) -> None:
        r = await self._get()
        key = f"bot_msgs:{chat_id}"
        score = float(message_id)  # хранить как sorted set чтобы было упорядочено
        await r.zadd(key, {str(message_id): score})
        await r.expire(key, _CLEAN_TTL)
        if pinned:
            await r.sadd(f"bot_msgs_pinned:{chat_id}", str(message_id))
            await r.expire(f"bot_msgs_pinned:{chat_id}", _LIST_TTL)

    async def list_bot_messages(
        self, chat_id: int, exclude_protected: bool = True
    ) -> list[int]:
        """Все tracked сообщения бота в чате.

        exclude_protected=True (default) исключает «защищённый» контент:
        - закреплённые (set bot_msgs_pinned:{chat_id})
        - активные task_list (ключи task_list_msg:{chat_id}:{message_id})

        Это нужно чтобы /clean без аргумента не сносил полезные списки —
        в silent mode они могут быть не закреплены, но всё равно tracked
        в task_list_msg.
        """
        r = await self._get()
        ids = await r.zrange(f"bot_msgs:{chat_id}", 0, -1)
        if exclude_protected:
            protected: set[str] = set()
            pinned = await r.smembers(f"bot_msgs_pinned:{chat_id}")
            protected.update(pinned)
            task_list_ids = await self.list_task_list_message_ids(chat_id)
            protected.update(str(i) for i in task_list_ids)
            ids = [i for i in ids if i not in protected]
        return [int(i) for i in ids]

    async def list_task_list_message_ids(self, chat_id: int) -> list[int]:
        """Все message_id, зарегистрированные как task_list для этого чата.

        Сканирует task_list_msg:{chat_id}:* (TTL 14 дней). Используется
        /clean чтобы не удалить активные списки даже если они не закреплены
        (silent mode / pin failed).
        """
        r = await self._get()
        prefix = f"task_list_msg:{chat_id}:"
        match = f"{prefix}*"
        ids: list[int] = []
        async for key in r.scan_iter(match=match, count=200):
            try:
                ids.append(int(key[len(prefix):]))
            except ValueError:
                continue
        return ids

    async def forget_bot_message(self, chat_id: int, message_id: int) -> None:
        r = await self._get()
        await r.zrem(f"bot_msgs:{chat_id}", str(message_id))
        await r.srem(f"bot_msgs_pinned:{chat_id}", str(message_id))

    async def clear_tracked(self, chat_id: int) -> None:
        r = await self._get()
        await r.delete(f"bot_msgs:{chat_id}")
        # pinned оставляем — закреплённые остаются закреплёнными

    # ── last-seen message id (для «не переносить если и так последний») ─

    # Lua script for atomic max-and-set
    _BUMP_SCRIPT = """
    local cur = redis.call('GET', KEYS[1])
    if cur == false or tonumber(cur) < tonumber(ARGV[1]) then
        redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
        return 1
    end
    return 0
    """

    async def bump_last_seen(self, chat_id: int, message_id: int) -> None:
        """Atomically update max(last_seen, message_id) via Lua script."""
        r = await self._get()
        key = f"last_msg:{chat_id}"
        await r.eval(self._BUMP_SCRIPT, 1, key, message_id, _CLEAN_TTL)

    async def get_last_seen(self, chat_id: int) -> int | None:
        r = await self._get()
        v = await r.get(f"last_msg:{chat_id}")
        return int(v) if v else None

    async def force_last_seen(self, chat_id: int, message_id: int) -> None:
        """Принудительно выставить last_seen (без max). Используется когда
        мы знаем, что удалили сообщения позже и реальное "последнее"
        откатилось назад — например после delete reply юзера.
        """
        r = await self._get()
        await r.set(f"last_msg:{chat_id}", message_id, ex=_CLEAN_TTL)

    # ── dedup alert state (для Phase 1.5A — объединение похожих списков) ──

    _DEDUP_TTL = 24 * 3600  # 24 часа

    async def store_dedup_alert(
        self,
        chat_id: int,
        new_bid: str,
        old_bid: str,
        new_msg_id: int,
    ) -> None:
        """Сохраняем состояние dedup-alert для обработки callback.

        Ключ: dedup_alert:{chat_id}:{new_bid}.
        """
        import json
        r = await self._get()
        await r.set(
            f"dedup_alert:{chat_id}:{new_bid}",
            json.dumps({
                "new_bid": new_bid,
                "old_bid": old_bid,
                "new_msg_id": new_msg_id,
            }),
            ex=self._DEDUP_TTL,
        )

    async def pop_dedup_alert(
        self, chat_id: int, new_bid: str,
    ) -> dict | None:
        """Атомарно читаем И удаляем состояние dedup-alert (GETDEL).

        Защита от double-tap: второй вызов вернёт None.
        """
        import json
        r = await self._get()
        raw = await r.getdel(f"dedup_alert:{chat_id}:{new_bid}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def delete_dedup_alert(
        self, chat_id: int, new_bid: str,
    ) -> None:
        """Удаляем состояние dedup-alert после обработки."""
        r = await self._get()
        await r.delete(f"dedup_alert:{chat_id}:{new_bid}")

    # ── general dedup (Phase 5D-lite) ──────────────────────────

    async def get_general_dedup(
        self, chat_id: int, message_id: int,
    ) -> dict | None:
        """Проверяем, является ли сообщение dedup-alert'ом.

        Ключ: general_dedup:{chat_id}:{message_id}.
        Возвращает {"new_bid": "...", "old_bid": "..."} или None.
        """
        import json
        r = await self._get()
        raw = await r.get(f"general_dedup:{chat_id}:{message_id}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def pop_general_dedup(
        self, chat_id: int, message_id: int,
    ) -> dict | None:
        """Атомарно читаем И удаляем (GETDEL)."""
        import json
        r = await self._get()
        raw = await r.getdel(f"general_dedup:{chat_id}:{message_id}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    # ── pending dedup (следующее сообщение без reply) ─────────

    _PENDING_DEDUP_TTL = 5 * 60  # 5 минут — потом забываем

    async def set_pending_dedup(
        self, chat_id: int, alert_msg_id: int,
    ) -> None:
        """Запоминаем что в чате ожидается ответ на dedup-alert.

        Ключ: pending_dedup:{chat_id} → alert_msg_id.
        Следующее сообщение с dedup-ключевым словом обработается как ответ.
        """
        r = await self._get()
        await r.set(
            f"pending_dedup:{chat_id}",
            str(alert_msg_id),
            ex=self._PENDING_DEDUP_TTL,
        )

    async def get_pending_dedup(self, chat_id: int) -> int | None:
        """Проверяем ожидается ли ответ на dedup. Возвращает alert_msg_id."""
        r = await self._get()
        v = await r.get(f"pending_dedup:{chat_id}")
        return int(v) if v else None

    async def clear_pending_dedup(self, chat_id: int) -> None:
        r = await self._get()
        await r.delete(f"pending_dedup:{chat_id}")

    # ── stale list nudge (Phase 1.5B) ─────────────────────────

    _NUDGE_TTL = 2 * 3600  # 2ч — потом nudge-сообщение авто-удалится
    _NUDGED_TTL = 7 * 24 * 3600  # 7 дней — не напоминаем повторно

    async def store_nudge(
        self, chat_id: int, msg_id: int, bookmark_id: str,
    ) -> None:
        """Сохраняем nudge state для обработки reply."""
        import json
        r = await self._get()
        await r.set(
            f"nudge:{chat_id}:{msg_id}",
            json.dumps({"bookmark_id": bookmark_id}),
            ex=self._NUDGE_TTL,
        )

    async def get_nudge(
        self, chat_id: int, msg_id: int,
    ) -> dict | None:
        """Проверяем nudge state по message_id."""
        import json
        r = await self._get()
        raw = await r.get(f"nudge:{chat_id}:{msg_id}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def pop_nudge(
        self, chat_id: int, msg_id: int,
    ) -> dict | None:
        """Атомарно читаем И удаляем nudge (GETDEL)."""
        import json
        r = await self._get()
        raw = await r.getdel(f"nudge:{chat_id}:{msg_id}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def mark_nudged(self, bookmark_id: str) -> None:
        """Помечаем что по этому списку nudge уже отправлен."""
        r = await self._get()
        await r.set(f"nudged:{bookmark_id}", "1", ex=self._NUDGED_TTL)

    async def was_nudged(self, bookmark_id: str) -> bool:
        """Проверяем был ли nudge для этого списка."""
        r = await self._get()
        return await r.exists(f"nudged:{bookmark_id}") > 0

    # ── cleanup-хвостов: failed replies + bot help messages ─
    # Когда юзер шлёт reply в формате который мы не поняли, мы реагируем 👎
    # и шлём подсказку. Если следующий reply сработал — все эти «хвосты»
    # должны исчезнуть, чтобы чат остался чистым.

    async def track_cleanup_msg(
        self, chat_id: int, list_msg_id: int, msg_id: int,
    ) -> None:
        """Запомнить временное сообщение, привязанное к task_list."""
        r = await self._get()
        key = f"tasklist_cleanup:{chat_id}:{list_msg_id}"
        await r.rpush(key, str(msg_id))
        await r.expire(key, _CLEANUP_TTL)

    async def pop_cleanup_msgs(
        self, chat_id: int, list_msg_id: int,
    ) -> list[int]:
        """Забрать и очистить все временные сообщения этого task_list."""
        r = await self._get()
        key = f"tasklist_cleanup:{chat_id}:{list_msg_id}"
        raw = await r.lrange(key, 0, -1)
        await r.delete(key)
        return [int(x) for x in raw if x.isdigit()]

    # ── reminders (Phase 2.5) ──────────────────────────────
    # Три ключа:
    #   reminder_pending:{chat_id}:{msg_id} → bookmark_id  (TTL 1ч)
    #     Ставит worker._maybe_offer_reminder при показе кнопки «Создать?».
    #     Читает reply-handler когда юзер отвечает временем.
    #   reminder:{chat_id}:{msg_id}         → scheduled_message_id (TTL 25ч)
    #     Ставит worker.scheduled_dispatcher при отправке reminder'а.
    #     Читают callbacks rdone:/rsnz: для маппинга msg_id → reminder_id.
    #   reminder_snooze:{chat_id}:{msg_id}  → scheduled_message_id (TTL 1ч)
    #     Ставит callback rsnz: когда юзер нажал «Продлить».
    #     Читает reply-handler когда юзер отвечает новым временем.

    _REMINDER_PENDING_TTL = 3600
    _REMINDER_SNOOZE_TTL = 3600

    async def get_reminder_pending(
        self, chat_id: int, msg_id: int,
    ) -> str | None:
        """bookmark_id для msg_id с offer-кнопкой, или None."""
        r = await self._get()
        return await r.get(f"reminder_pending:{chat_id}:{msg_id}")

    async def pop_reminder_pending(
        self, chat_id: int, msg_id: int,
    ) -> str | None:
        """Атомарно читаем + удаляем — защита от double-reply."""
        r = await self._get()
        return await r.getdel(f"reminder_pending:{chat_id}:{msg_id}")

    async def delete_reminder_pending(
        self, chat_id: int, msg_id: int,
    ) -> None:
        r = await self._get()
        await r.delete(f"reminder_pending:{chat_id}:{msg_id}")

    async def get_reminder_id(
        self, chat_id: int, msg_id: int,
    ) -> str | None:
        """scheduled_message_id для отправленного reminder, или None."""
        r = await self._get()
        return await r.get(f"reminder:{chat_id}:{msg_id}")

    async def delete_reminder_id(
        self, chat_id: int, msg_id: int,
    ) -> None:
        r = await self._get()
        await r.delete(f"reminder:{chat_id}:{msg_id}")

    async def store_reminder_snooze(
        self, chat_id: int, msg_id: int, reminder_id: str,
    ) -> None:
        """Юзер нажал «Продлить» — ждём новое время через reply."""
        r = await self._get()
        await r.set(
            f"reminder_snooze:{chat_id}:{msg_id}",
            reminder_id,
            ex=self._REMINDER_SNOOZE_TTL,
        )

    async def pop_reminder_snooze(
        self, chat_id: int, msg_id: int,
    ) -> str | None:
        r = await self._get()
        return await r.getdel(f"reminder_snooze:{chat_id}:{msg_id}")

    # F2: FALLBACK_DEFAULT confirm flow.
    # Когда юзер написал «потом / не знаю / ладно» в reply на «когда напомнить?»,
    # мы ставим reminder на now+24h, но НЕ создаём сразу — спрашиваем confirm.
    # До «да» — храним предложенное время + контекст (bid или snooze rid).
    _REMINDER_FALLBACK_TTL = 5 * 60   # 5 минут на ответ «да/уточни»

    async def store_reminder_fallback(
        self, chat_id: int, msg_id: int,
        kind: str,                        # "create" | "snooze"
        target_id: str,                   # bookmark_id или reminder_id
        proposed_dt_iso: str,             # ISO-строка предложенного времени
    ) -> None:
        import json
        r = await self._get()
        await r.set(
            f"reminder_fallback:{chat_id}:{msg_id}",
            json.dumps({
                "kind": kind,
                "target_id": target_id,
                "dt_iso": proposed_dt_iso,
            }),
            ex=self._REMINDER_FALLBACK_TTL,
        )

    async def pop_reminder_fallback(
        self, chat_id: int, msg_id: int,
    ) -> dict | None:
        import json
        r = await self._get()
        raw = await r.getdel(f"reminder_fallback:{chat_id}:{msg_id}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def get_reminder_fallback(
        self, chat_id: int, msg_id: int,
    ) -> dict | None:
        import json
        r = await self._get()
        raw = await r.get(f"reminder_fallback:{chat_id}:{msg_id}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def get_reminder_snooze(
        self, chat_id: int, msg_id: int,
    ) -> str | None:
        r = await self._get()
        return await r.get(f"reminder_snooze:{chat_id}:{msg_id}")

    async def delete_reminder_snooze(
        self, chat_id: int, msg_id: int,
    ) -> None:
        r = await self._get()
        await r.delete(f"reminder_snooze:{chat_id}:{msg_id}")
