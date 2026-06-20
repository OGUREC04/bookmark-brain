"""Dedup-alert + first-task-list-tip helpers (worker split — 0dj).

No arq entrypoint. Used by ``processing.py``.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.config import get_settings

from .telegram import _send_message

logger = logging.getLogger(__name__)
settings = get_settings()


async def _maybe_send_first_task_list_tip(session, user_id, chat_id: int) -> None:
    """Phase 2: показать подсказку про reply-команды один раз на юзера.

    Канонический текст подсказки — `bot/onboarding.py: TIP_FIRST_TASK_LIST`.
    Здесь дубль из-за того, что worker и bot — разные процессы без общего
    модуля. При правке текста — синхронизировать оба места.

    Флаг хранится в `users.settings.onboarding_first_task_list` (плоский ключ
    выбран потому что PATCH /users/me/settings делает shallow merge).
    """
    from app.models import User
    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return

    current_settings = dict(user.settings or {})
    if current_settings.get("onboarding_first_task_list"):
        return

    tip_text = (
        "💡 Это список задач — я распознал его автоматически.\n\n"
        "Чтобы редактировать — отвечай (reply) на это сообщение:\n"
        "• «закрой 1, 3» — отметить пункты выполненными\n"
        "• «добавь купить хлеб» — новый пункт\n"
        "• «удали 2» — убрать пункт\n"
        "• «удали список» — убрать всё"
    )

    # Сначала фиксируем флаг — если flush упадёт, подсказка не уйдёт
    # (иначе при ошибке БД пользователь получил бы её снова на следующий task_list)
    current_settings["onboarding_first_task_list"] = True
    user.settings = current_settings
    await session.flush()

    # flush прошёл — отправляем подсказку (постоянная, не ephemeral)
    asyncio.create_task(_send_message(chat_id, tip_text))


async def _store_general_dedup(
    chat_id: int, alert_msg_id: int,
    new_bid: str, old_bid: str, src_msg_id: int | None = None,
) -> None:
    """Сохраняет состояние general dedup в Redis.

    Ключ: general_dedup:{chat_id}:{alert_msg_id}.
    Bot reply handler использует этот ключ для обработки ответа юзера.

    src_msg_id — исходное сообщение юзера. В silent-режиме near-dup
    снимает с него 👀; по нему bot вернёт 👍 после save_new/update,
    иначе фидбэка нет вообще (#10).
    """
    import json
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await r.set(
                f"general_dedup:{chat_id}:{alert_msg_id}",
                json.dumps({
                    "new_bid": new_bid,
                    "old_bid": old_bid,
                    "src_msg_id": src_msg_id,
                }),
                ex=24 * 3600,
            )
            # pending_dedup НЕ ставим: дедуп резолвится только через reply на
            # алерт (правило «ответ — только reply»). Раньше next-message
            # перехват зацикливал любой текст в «Не понял …».
        finally:
            await r.aclose()
    except Exception as e:
        logger.debug(f"store_general_dedup failed: {e}")


async def _store_dedup_alert(
    chat_id: int, new_bid: str, old_bid: str, new_msg_id: int,
) -> None:
    """Сохраняет состояние dedup-alert в Redis.

    Ключ: dedup_alert:{chat_id}:{new_bid} — совпадает с bot/state_store.py.
    Callback data в кнопках содержит new_bid, бот ищет по нему.
    """
    import json
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await r.set(
                f"dedup_alert:{chat_id}:{new_bid}",
                json.dumps({
                    "new_bid": new_bid,
                    "old_bid": old_bid,
                    "new_msg_id": new_msg_id,
                }),
                ex=24 * 3600,
            )
        finally:
            await r.aclose()
    except Exception as e:
        logger.debug(f"store_dedup_alert failed: {e}")


def _build_dedup_alert(similar: dict, new_bookmark_id: str) -> tuple[str, dict]:
    """Текст и кнопки для dedup-alert.

    similar — dict из find_similar_unclosed_task_list().
    Возвращает (text, reply_markup).
    """
    title = similar.get("title") or "Список задач"
    done = similar.get("done_count", 0)
    total = similar.get("total_count", 0)
    created = similar.get("created_at")

    date_str = ""
    if created:
        try:
            from datetime import datetime
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
            date_str = f" от {created.strftime('%d.%m')}"
        except Exception:
            pass

    text = (
        f"🔄 Похожий список <b>{title}</b>{date_str}\n"
        f"({done}/{total} выполнено)\n\n"
        f"Объединить новые задачи в него?"
    )

    # Callback key = new_bookmark_id (UUID, 36 chars + prefix 3 = 39 bytes < 64 limit).
    # Это позволяет отправить кнопки сразу без PLACEHOLDER + re-edit.
    buttons = {
        "inline_keyboard": [
            [
                {"text": "🔗 Объединить", "callback_data": f"dm:{new_bookmark_id}"},
                {"text": "📋 Отдельно", "callback_data": f"dk:{new_bookmark_id}"},
            ]
        ]
    }
    return text, buttons
