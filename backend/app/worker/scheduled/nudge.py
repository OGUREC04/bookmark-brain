"""Stale task-list morning nudge cron (worker split — djtn).

``stale_list_nudge`` pings users about task lists older than 24h with unfinished
items. ``_send_message`` / ``_delete_message`` are looked up in THIS module —
nudge test patches target ``app.worker.scheduled.nudge.*``.
"""

from __future__ import annotations

import html
import logging

from sqlalchemy import select

from app.config import get_settings
from app.worker.telegram import _delete_message, _send_message

logger = logging.getLogger(__name__)
settings = get_settings()


# Анти-спам: максимум nudge'ей на одного юзера за один прогон крона.
# Без лимита прогон шлёт по сообщению на КАЖДЫЙ незакрытый список — у юзера
# с накопленными списками это 20+ сообщений за раз. Пингуем только самый
# залежавшийся список; остальные — в следующие прогоны (по мере закрытия).
_MAX_NUDGES_PER_USER_PER_RUN = 1


async def stale_list_nudge(ctx: dict) -> None:
    """Cron: утреннее напоминание о незакрытых списках задач.

    Ищет task_list'ы старше 24ч с done < total, отправляет nudge в Telegram.
    Не напоминает повторно (Redis nudged:{bookmark_id} TTL 7 дней).
    Не больше ``_MAX_NUDGES_PER_USER_PER_RUN`` на юзера за прогон (анти-спам).
    """
    from sqlalchemy import and_, text

    from app.database import async_session
    from app.models import Bookmark, User

    logger.info("Stale list nudge: starting check")

    async with async_session() as session:
        # Ищем task_list'ы: ai_status completed/partial, не archived,
        # structured_data.type = 'task_list', старше 24ч.
        # Сортировка по created_at ASC — самые залежавшиеся первыми, чтобы
        # под per-user лимит попадал самый старый незакрытый список.
        result = await session.execute(
            select(Bookmark, User.telegram_id).join(
                User, Bookmark.user_id == User.id,
            ).where(
                and_(
                    Bookmark.ai_status.in_(["completed", "partial"]),
                    Bookmark.is_archived == False,  # noqa: E712 — SQL boolean comparison
                    Bookmark.structured_data.isnot(None),
                    text("bookmarks.structured_data->>'type' = 'task_list'"),
                    Bookmark.created_at < text(
                        "NOW() - INTERVAL '24 hours'"
                    ),
                )
            ).order_by(Bookmark.created_at.asc())
        )
        rows = result.all()

    if not rows:
        logger.info("Stale list nudge: no stale lists found")
        return

    # Фильтруем: done < total И не nudged (atomic SET NX)
    import json

    import redis.asyncio as aioredis
    r: aioredis.Redis | None = None
    nudge_count = 0
    # Сколько nudge'ей уже отправлено каждому юзеру в ЭТОМ прогоне (анти-спам).
    sent_per_user: dict[int, int] = {}

    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

        for bookmark, telegram_id in rows:
            sd = bookmark.structured_data or {}
            tasks = sd.get("tasks", [])
            if not tasks:
                continue
            total = len(tasks)
            done = sum(1 for t in tasks if t.get("done"))
            if done >= total:
                continue  # Все выполнены

            # Анти-спам: лимит на юзера за прогон. rows отсортированы по
            # created_at ASC → под лимит попадает самый залежавшийся список.
            if sent_per_user.get(telegram_id, 0) >= _MAX_NUDGES_PER_USER_PER_RUN:
                continue

            bid = str(bookmark.id)

            # Проверяем не nudged ли уже (без записи — запишем после успешной отправки)
            if await r.exists(f"nudged:{bid}"):
                continue

            # Формируем nudge (title/тексты пунктов — user-controlled → escape,
            # т.к. _send_message шлёт parse_mode=HTML)
            title = html.escape(bookmark.title or "Список задач")
            created = bookmark.created_at
            date_str = ""
            if created:
                try:
                    date_str = f" от {created.strftime('%d.%m')}"
                except Exception:
                    pass

            undone = [t.get("text", "?") for t in tasks if not t.get("done")]
            undone_preview = html.escape(", ".join(undone[:3]))
            if len(undone) > 3:
                undone_preview += f" (+{len(undone) - 3})"

            nudge_text = (
                f"📋 <b>{title}</b>{date_str}\n"
                f"Выполнено: {done}/{total}\n"
                f"Осталось: {undone_preview}\n\n"
                f"⚡ <i>Ответь reply: перенести / закрыть / оставить</i>"
            )

            resp = await _send_message(telegram_id, nudge_text)
            if resp and resp.get("message_id"):
                nudge_msg_id = resp["message_id"]
                # Atomic SET NX ПОСЛЕ успешной отправки — race-safe
                was_set = await r.set(
                    f"nudged:{bid}", "1", ex=7 * 24 * 3600, nx=True,
                )
                if not was_set:
                    # Другой worker уже отправил — удаляем дубль
                    await _delete_message(telegram_id, nudge_msg_id)
                    continue
                # Сохраняем nudge state в Redis (bot reply handler читает)
                await r.set(
                    f"nudge:{telegram_id}:{nudge_msg_id}",
                    json.dumps({"bookmark_id": bid}),
                    ex=2 * 3600,  # 2ч TTL
                )
                nudge_count += 1
                sent_per_user[telegram_id] = sent_per_user.get(telegram_id, 0) + 1
                logger.info(f"Nudge sent for {bid} to {telegram_id}")
    finally:
        if r is not None:
            await r.aclose()

    logger.info(f"Stale list nudge: sent {nudge_count} nudges")
