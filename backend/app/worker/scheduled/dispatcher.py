"""Reminders dispatcher cron + helpers (worker split — djtn).

``scheduled_dispatcher`` / ``auto_done_reminders`` plus reminder constants and
text/keyboard helpers. ``async_session`` / ``_send_message`` /
``aioredis_from_url`` are looked up in THIS module — dispatcher-flow test
patches target ``app.worker.scheduled.dispatcher.*``.
"""

from __future__ import annotations

import asyncio
import html
import logging

from app.config import get_settings
from app.database import async_session
from app.worker.telegram import _send_message, aioredis_from_url

logger = logging.getLogger(__name__)
settings = get_settings()


# ──────────────────────────────────────────────────
# Reminders constants (Phase 2.5)
# ──────────────────────────────────────────────────

# Сколько раз retry'нуть Telegram-отправку перед status='failed'
MAX_REMINDER_RETRIES = 2
# Задержка между retry-попытками
REMINDER_RETRY_DELAY_MIN = 5
# Окно auto-done: если юзер не нажал «Выполнено» в течение N часов после
# отправки — считаем, что задача выполнена молча.
AUTO_DONE_HOURS = 24
# TTL Redis-ключа reminder:{chat_id}:{message_id} (немного больше окна auto-done)
REMINDER_REDIS_TTL_SEC = 25 * 3600
# Сколько reminder'ов подбираем за один тик cron
DISPATCH_BATCH_SIZE = 50
# Окно «застрявшего» status='sending' — больше job_timeout (120s).
# Если row висит дольше — worker умер между CAS-lock и mark-sent, возвращаем
# в 'pending' для retry.
STUCK_SENDING_THRESHOLD_MIN = 5


def _reminder_buttons(scheduled_message_id: str) -> dict:
    """Inline-клавиатура для отправленного reminder.

    Только две кнопки по UX-спеке: Выполнено / Продлить.
    Callback префиксы:
      rdone:<sm_id> — отметить выполненным
      rsnz:<sm_id>  — продлить (бот спросит «на сколько» через reply)
    """
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Выполнено", "callback_data": f"rdone:{scheduled_message_id}"},
                {"text": "💤 Продлить", "callback_data": f"rsnz:{scheduled_message_id}"},
            ]
        ]
    }


def _format_reminder_text(payload: dict) -> str:
    """Текст напоминания. Берём payload.text (то, что юзер написал в reply),
    fallback — общая строка."""
    text = (payload or {}).get("text") or ""
    text = text.strip()
    if not text:
        return "🔔 Напоминание"
    return f"🔔 Напомню: {html.escape(text)}"


def _recurring_reminder_buttons(recurring_id: str) -> dict:
    """Inline-клавиатура регулярного срабатывания (/repeat).

    Без «продлить» — следующее уже завтра. Callback префиксы:
      rrok:<recurring_id>   — принять это срабатывание (серия продолжается)
      rrstop:<recurring_id> — остановить серию
    """
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Ок", "callback_data": f"rrok:{recurring_id}"},
                {
                    "text": "🛑 Больше не напоминать",
                    "callback_data": f"rrstop:{recurring_id}",
                },
            ]
        ]
    }


def _format_recurring_text(payload: dict) -> str:
    """Текст регулярного срабатывания — значок 🔁 отличает его от разового 🔔."""
    text = (payload or {}).get("text") or ""
    text = text.strip()
    if not text:
        return "🔁 Напоминание"
    return f"🔁 {html.escape(text)}"


async def _save_reminder_redis_state(
    chat_id: int, message_id: int, scheduled_message_id: str,
) -> None:
    """Сохраняем reminder:{chat_id}:{message_id} → sm_id для callback-handler'ов
    бота. TTL чуть больше auto-done окна — после 25h ключ уже не нужен."""
    r = aioredis_from_url(settings.REDIS_URL)
    try:
        await r.set(
            f"reminder:{chat_id}:{message_id}",
            scheduled_message_id,
            ex=REMINDER_REDIS_TTL_SEC,
        )
    finally:
        await r.aclose()


async def scheduled_dispatcher(ctx: dict) -> None:
    """Cron (каждую минуту): шлём reminder'ы у которых fire_at наступил.

    Шаги:
      1. SELECT due (status='pending' AND fire_at <= now()) JOIN users
      2. Для каждого — CAS UPDATE status='sending' RETURNING (защита от
         двойной отправки если запущено несколько worker-инстансов).
      3. Отправляем в Telegram, на success → status='sent', message_id.
      4. На failure — retry_count++, либо reschedule (+5min), либо 'failed'.
    """
    from sqlalchemy import text as sa_text

    async with async_session() as session:
        # Recovery: возвращаем застрявшие в 'sending' (worker упал между
        # CAS-lock и mark-sent). fire_at не меняется при CAS, так что rows
        # с fire_at < NOW() - threshold действительно «зависли». Threshold
        # больше job_timeout (120s), чтобы не перехватывать активные jobs.
        stuck_result = await session.execute(sa_text(
            """
            UPDATE scheduled_messages
            SET status = 'pending'
            WHERE status = 'sending'
              AND kind = 'reminder'
              AND fire_at < NOW() - (:threshold || ' minutes')::interval
            """
        ).bindparams(threshold=str(STUCK_SENDING_THRESHOLD_MIN)))
        stuck_count = getattr(stuck_result, "rowcount", 0) or 0
        if stuck_count:
            logger.warning(
                f"scheduled_dispatcher: recovered {stuck_count} stuck 'sending' row(s)"
            )
            await session.commit()

        # JOIN с users — нужен telegram_id для отправки
        due_result = await session.execute(sa_text(
            """
            SELECT sm.id, sm.user_id, u.telegram_id, sm.bookmark_id,
                   sm.fire_at, sm.retry_count, sm.payload
            FROM scheduled_messages sm
            JOIN users u ON u.id = sm.user_id
            WHERE sm.status = 'pending'
              AND sm.kind = 'reminder'
              AND sm.fire_at <= NOW()
            ORDER BY sm.fire_at
            LIMIT :limit
            """
        ).bindparams(limit=DISPATCH_BATCH_SIZE))
        rows = due_result.all()

        if not rows:
            return

        logger.info(f"scheduled_dispatcher: {len(rows)} due reminder(s)")

        for row in rows:
            sm_id = row[0]
            telegram_id = row[2]

            # CAS lock — только один worker берёт reminder.
            # Возвращаем актуальные поля (retry_count и payload могут
            # отличаться от snapshot в SELECT выше — например, snooze
            # обновил payload между SELECT и CAS).
            cas_result = await session.execute(sa_text(
                """
                UPDATE scheduled_messages
                SET status = 'sending'
                WHERE id = :id AND status = 'pending'
                RETURNING id, user_id, bookmark_id, payload, retry_count
                """
            ).bindparams(id=sm_id))
            # CAS RETURNING — берём по имени колонки через .mappings().
            # scalar_one_or_none() вернул бы только первый столбец (id) —
            # никаких payload/retry_count не достать.
            locked = cas_result.mappings().one_or_none()
            if locked is None:
                # Другой worker уже захватил — пропускаем
                continue

            # Берём свежий payload из CAS-результата, не из SELECT-snapshot
            actual_payload = locked["payload"] or (row[6] or {})
            # Регулярное срабатывание (/repeat) — другой значок + другие кнопки
            # (✅ Ок / 🛑 Стоп) с recurring_id, не sm_id.
            _recurring_id = actual_payload.get("recurring_id")
            if _recurring_id:
                text_msg = _format_recurring_text(actual_payload)
                buttons = _recurring_reminder_buttons(str(_recurring_id))
            else:
                text_msg = _format_reminder_text(actual_payload)
                buttons = _reminder_buttons(str(sm_id))

            send_result = await _send_message(telegram_id, text_msg, buttons)

            if send_result and send_result.get("message_id"):
                msg_id = send_result["message_id"]
                # Mark sent
                await session.execute(sa_text(
                    """
                    UPDATE scheduled_messages
                    SET status = 'sent',
                        sent_at = NOW(),
                        message_id = :msg_id
                    WHERE id = :id
                    """
                ).bindparams(id=sm_id, msg_id=msg_id))
                await session.commit()

                # Redis state — для callback-handler'ов бота
                try:
                    await _save_reminder_redis_state(telegram_id, msg_id, str(sm_id))
                except Exception as e:
                    logger.warning(f"Failed to save reminder Redis state for {sm_id}: {e}")
            else:
                # Send failed — retry или failed
                # Текущий retry_count — из CAS-lock результата (актуальный).
                current_retry = locked["retry_count"] or 0
                if current_retry >= MAX_REMINDER_RETRIES:
                    await session.execute(sa_text(
                        """
                        UPDATE scheduled_messages
                        SET status = 'failed',
                            retry_count = retry_count + 1
                        WHERE id = :id
                        """
                    ).bindparams(id=sm_id))
                    logger.error(
                        f"Reminder {sm_id} failed permanently "
                        f"after {current_retry} retries"
                    )
                    # F1: уведомляем юзера. Best-effort — это уже notify-канал
                    # тоже может упасть, но если оно упало 1 раз транзиентно
                    # из retry, сейчас (минуту спустя) может уже работать.
                    short_text = (actual_payload.get("text") or "")[:60]
                    fail_msg = (
                        "⚠️ Не удалось отправить напоминание"
                        + (f" «{short_text}»" if short_text else "")
                        + ". Попробуй создать заново через /remind."
                    )
                    asyncio.create_task(_send_message(telegram_id, fail_msg))
                else:
                    # Reschedule — пока без exponential backoff, фиксированный лаг
                    await session.execute(sa_text(
                        """
                        UPDATE scheduled_messages
                        SET status = 'pending',
                            retry_count = retry_count + 1,
                            fire_at = NOW() + (:delay || ' minutes')::interval
                        WHERE id = :id
                        """
                    ).bindparams(id=sm_id, delay=str(REMINDER_RETRY_DELAY_MIN)))
                    logger.warning(
                        f"Reminder {sm_id} send failed "
                        f"(retry {current_retry + 1}/{MAX_REMINDER_RETRIES})"
                    )
                await session.commit()


async def auto_done_reminders(ctx: dict) -> None:
    """Cron (раз в час): помечаем sent reminder'ы старше 24h как done.

    Если юзер не нажал «Выполнено» / «Продлить» в течение суток — значит
    задача либо сделана и забыта, либо неактуальна. Reminder уходит из
    активных. В payload пишем `auto_done=true` для аудита (отличить от
    юзер-нажал-«Выполнено»: тот пишет в payload `done_by_user=true`).

    Status='done' — единственное завершённое состояние в ENUM
    `scheduled_status`. Различаем юзер vs auto через payload-флаг, не
    через статус (иначе пришлось бы расширять ENUM миграцией).
    """
    from sqlalchemy import text as sa_text

    async with async_session() as session:
        # F5: добавлен guard `fire_at <= NOW()` — защита от race с snooze.
        # update_reminder сбрасывает sent_at=NULL при snooze, но если race
        # оставил status='sent' с fire_at в будущем — не трогаем.
        result = await session.execute(sa_text(
            """
            UPDATE scheduled_messages
            SET status = 'done',
                payload = COALESCE(payload, '{}'::jsonb)
                          || jsonb_build_object('auto_done', true)
            WHERE kind = 'reminder'
              AND status = 'sent'
              AND sent_at < NOW() - (:hours || ' hours')::interval
              AND fire_at <= NOW()
            """
        ).bindparams(hours=str(AUTO_DONE_HOURS)))
        await session.commit()
        rowcount = getattr(result, "rowcount", 0) or 0
        if rowcount:
            logger.info(f"auto_done_reminders: marked {rowcount} reminder(s) as done (auto)")
        else:
            logger.debug("auto_done_reminders: nothing to mark")
