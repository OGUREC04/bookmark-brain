"""Reminders dispatcher + cron jobs (Phase 2.5) (worker split — 0dj).

Holds the cron coroutines wired into ``WorkerSettings.cron_jobs``:
``scheduled_dispatcher``, ``auto_done_reminders``, ``retry_failed_task``,
``retry_partial_embeddings``, ``stale_list_nudge``.

``async_session`` / ``_send_message`` / ``aioredis_from_url`` are looked up
in THIS module — worker-test patches for the dispatcher / auto-done flows
target ``app.worker.scheduled.*``.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session

from .telegram import _delete_message, _send_message, aioredis_from_url

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
    return f"🔔 Напомню: {text}"


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


async def retry_failed_task(ctx: dict) -> None:
    """Cron: ночной retry для failed закладок."""
    from app.database import async_session
    from app.models import Bookmark

    async with async_session() as session:
        result = await session.execute(
            select(Bookmark.id).where(
                Bookmark.ai_status == "failed",
                Bookmark.retry_count < 3,
            )
        )
        bookmark_ids = [str(row[0]) for row in result.fetchall()]

    if not bookmark_ids:
        logger.info("No failed bookmarks to retry")
        return

    logger.info(f"Retrying {len(bookmark_ids)} failed bookmarks")
    for bid in bookmark_ids:
        await ctx["redis"].enqueue_job("process_bookmark_task", bid)


async def backfill_bookmark_links(ctx: dict | None = None, *, batch_size: int = 200) -> int:
    """One-shot джоба: строит смысловые связи для всех заметок с эмбеддингом (Phase 5A).

    Идёт по СУЩЕСТВУЮЩИМ эмбеддингам — 0 вызовов LLM и 0 запросов к Voyage,
    батчами (keyset по id), идемпотентно (ON CONFLICT DO NOTHING в
    build_links_for_bookmark). Возвращает число обработанных заметок.

    Запуск (один раз, пользователем): enqueue_job("backfill_bookmark_links").

    ВАЖНО (консистентность пространства): если существующие заметки
    пересчитывались под новый рецепт эмбеддинга (AD-7 — реальный текст + ИИ),
    запускать ПОСЛЕ пересчёта, иначе связи строятся в смешанном пространстве
    (старый рецепт ↔ новый). Пересчёт существующих — отдельный шаг (E1,
    требует бюджета Voyage); новые/переобработанные заметки уже на новом рецепте.
    """
    from app.database import async_session
    from app.models import Bookmark
    from app.services.connections import build_links_for_bookmark

    processed = 0
    last_id = None
    async with async_session() as session:
        while True:
            stmt = (
                select(Bookmark.id, Bookmark.user_id, Bookmark.embedding)
                .where(
                    Bookmark.ai_status.in_(("completed", "partial")),
                    Bookmark.embedding.isnot(None),
                )
                .order_by(Bookmark.id)
                .limit(batch_size)
            )
            if last_id is not None:
                stmt = stmt.where(Bookmark.id > last_id)

            rows = (await session.execute(stmt)).fetchall()
            if not rows:
                break

            for row in rows:
                emb = row.embedding
                emb_list = emb.tolist() if hasattr(emb, "tolist") else list(emb)
                try:
                    await build_links_for_bookmark(
                        session, row.id, row.user_id, emb_list,
                    )
                except Exception as e:  # noqa: BLE001 — не валим весь бэкфилл
                    logger.debug(f"backfill: link build failed for {row.id}: {e}")
                processed += 1
                last_id = row.id

            await session.commit()

    logger.info(f"backfill_bookmark_links: processed {processed} bookmark(s)")
    return processed


async def reembed_all_bookmarks(ctx: dict | None = None, *, batch_size: int = 100) -> int:
    """One-shot джоба: пере-эмбеддит ВСЕ заметки новым рецептом (AD-7).

    Нужна после смены рецепта эмбеддинга (реальный текст + ИИ-поля). Старые
    заметки эмбеддились по старому рецепту (только ИИ-выжимка) — связи/дедуп для
    них считались бы в СТАРОМ пространстве, ровно от которого мы уходили. Прогон
    делает пространство единым. 0 вызовов LLM (только Voyage-эмбеддинги).

    Запуск вручную на деплое: enqueue_job("reembed_all_bookmarks"), ПЕРЕД
    backfill_bookmark_links (сначала единый рецепт, потом по нему строим связи).

    Идёт батчами (keyset по id), best-effort на элемент. Возвращает число
    успешно переэмбедженных заметок.
    """
    from types import SimpleNamespace

    from app.database import async_session
    from app.models import Bookmark
    from app.services.bookmark_processor import _build_embedding_text
    from app.services.embeddings import (
        EmbeddingError,
        RetryableEmbeddingError,
        create_embedding_service,
    )

    embedding_service = create_embedding_service(
        provider=settings.EMBEDDING_PROVIDER,
        auth_key=settings.GIGACHAT_AUTH_KEY,
        api_key=settings.VOYAGE_API_KEY,
        ca_bundle=settings.GIGACHAT_CA_BUNDLE,
    )
    processed = 0
    last_id = None
    try:
        while True:
            async with async_session() as session:
                stmt = (
                    select(Bookmark)
                    .where(Bookmark.ai_status.in_(("completed", "partial")))
                    .order_by(Bookmark.id)
                    .limit(batch_size)
                )
                if last_id is not None:
                    stmt = stmt.where(Bookmark.id > last_id)

                bookmarks = (await session.execute(stmt)).scalars().all()
                if not bookmarks:
                    break

                for bm in bookmarks:
                    last_id = bm.id
                    # Теги lazy-не-загружены → None; основной сигнал в реальном тексте.
                    clf = SimpleNamespace(
                        takeaway=bm.takeaway,
                        summary=bm.summary,
                        key_ideas=bm.key_ideas,
                        tags=None,
                    )
                    try:
                        emb = await embedding_service.get_embedding(
                            _build_embedding_text(bm, clf)
                        )
                        bm.embedding = emb
                        processed += 1
                    except (EmbeddingError, RetryableEmbeddingError) as e:
                        logger.warning(f"reembed: failed for {bm.id}: {e}")

                await session.commit()
    finally:
        await embedding_service.close()

    logger.info(f"reembed_all_bookmarks: re-embedded {processed} bookmark(s)")
    return processed


async def retry_partial_embeddings(ctx: dict) -> None:
    """Cron: retry embedding for partial bookmarks (classification OK, embedding failed).

    Runs daily at 5:00 AM (after retry_failed at 3:00 AM).
    Max 5 retries per bookmark, circuit breaker after 5 consecutive failures.
    """
    from datetime import datetime, timezone

    from app.database import async_session
    from app.models import Bookmark
    from app.services.embeddings import (
        EmbeddingError,
        RetryableEmbeddingError,
        create_embedding_service,
    )

    MAX_EMBEDDING_RETRIES = 5
    CIRCUIT_BREAKER_THRESHOLD = 5

    embedding_service = create_embedding_service(
        provider=settings.EMBEDDING_PROVIDER,
        auth_key=settings.GIGACHAT_AUTH_KEY,
        api_key=settings.VOYAGE_API_KEY,
        ca_bundle=settings.GIGACHAT_CA_BUNDLE,
    )

    async with async_session() as session:
        result = await session.execute(
            select(Bookmark).where(
                Bookmark.ai_status == "partial",
                Bookmark.embedding_retry_count < MAX_EMBEDDING_RETRIES,
            )
        )
        bookmarks = result.scalars().all()

    if not bookmarks:
        logger.info("No partial bookmarks to retry embeddings")
        await embedding_service.close()
        return

    logger.info(f"Retrying embeddings for {len(bookmarks)} partial bookmarks")
    consecutive_failures = 0

    for bookmark in bookmarks:
        if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            logger.warning("Circuit breaker tripped — stopping embedding retries")
            break

        try:

            # Единый рецепт эмбеддинга (AD-7): реальный текст заметки + ИИ-поля.
            # Иначе ретрай создавал бы эмбеддинги в СТАРОМ пространстве (только
            # ИИ-поля), несовместимом с новыми/переобработанными заметками →
            # смешанное пространство и кривые связи/дедуп. Теги lazy-не-загружены.
            from types import SimpleNamespace

            from app.services.bookmark_processor import _build_embedding_text

            _clf = SimpleNamespace(
                takeaway=bookmark.takeaway,
                summary=bookmark.summary,
                key_ideas=bookmark.key_ideas,
                tags=None,
            )
            embedding_text = _build_embedding_text(bookmark, _clf)
            embedding = await embedding_service.get_embedding(embedding_text)

            async with async_session() as session:
                result = await session.execute(
                    select(Bookmark).where(Bookmark.id == bookmark.id)
                )
                bm = result.scalar_one()
                bm.embedding = embedding
                bm.ai_status = "completed"
                bm.ai_error = None
                bm.embedding_last_attempt = datetime.now(timezone.utc)
                await session.commit()

            consecutive_failures = 0
            logger.info(f"Embedding retry succeeded for {bookmark.id}")

        except (EmbeddingError, RetryableEmbeddingError) as e:
            consecutive_failures += 1
            async with async_session() as session:
                result = await session.execute(
                    select(Bookmark).where(Bookmark.id == bookmark.id)
                )
                bm = result.scalar_one()
                bm.embedding_retry_count += 1
                bm.embedding_last_attempt = datetime.now(timezone.utc)
                if bm.embedding_retry_count >= MAX_EMBEDDING_RETRIES:
                    bm.ai_status = "completed_no_embedding"
                    bm.ai_error = f"Permanent: embedding failed after {MAX_EMBEDDING_RETRIES} retries"
                    logger.warning(f"Bookmark {bookmark.id} marked completed_no_embedding")
                await session.commit()

            logger.warning(f"Embedding retry failed for {bookmark.id}: {e}")

        except Exception as e:
            consecutive_failures += 1
            logger.error(f"Unexpected error retrying embedding for {bookmark.id}: {e}")

    await embedding_service.close()


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

            # Формируем nudge
            title = bookmark.title or "Список задач"
            created = bookmark.created_at
            date_str = ""
            if created:
                try:
                    date_str = f" от {created.strftime('%d.%m')}"
                except Exception:
                    pass

            undone = [t.get("text", "?") for t in tasks if not t.get("done")]
            undone_preview = ", ".join(undone[:3])
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


# ──────────────────────────────────────────────────
# analytics_events partition maintenance (Phase M1, ADR 0010)
# ──────────────────────────────────────────────────

# Сколько месяцев храним аналитические события. Старше — DROP PARTITION.
ANALYTICS_RETENTION_MONTHS = 6


def _month_partition(year: int, month: int) -> tuple[str, str, str]:
    """(имя_партиции, начало, конец) для месяца. Границы RANGE [from, to)."""
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    return (
        f"analytics_events_{year:04d}_{month:02d}",
        f"{year:04d}-{month:02d}-01",
        f"{ny:04d}-{nm:02d}-01",
    )


async def analytics_partition_maintenance(ctx: dict) -> None:
    """Cron (раз в сутки + на старте): катит месячные партиции
    analytics_events вперёд и дропает старше retention.

    DROP PARTITION = чистый retention без bloat/VACUUM-боли. Партиции на
    текущий+следующий месяц всегда есть → данные не попадают в DEFAULT,
    retention работает по-месячно.
    """
    from datetime import datetime, timezone

    from sqlalchemy import text as sa_text

    now = datetime.now(timezone.utc)
    # 1. Создаём партиции на текущий + следующий месяц (idempotent).
    months = [(now.year, now.month)]
    months.append((now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1))

    created = 0
    async with async_session() as session:
        for year, month in months:
            name, start, end = _month_partition(year, month)
            await session.execute(sa_text(
                f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF analytics_events "
                f"FOR VALUES FROM ('{start}') TO ('{end}')"
            ))
            created += 1
        await session.commit()

        # 2. Дропаем партиции старше retention.
        cutoff_idx = now.year * 12 + (now.month - 1) - ANALYTICS_RETENTION_MONTHS
        rows = (await session.execute(sa_text(
            "SELECT child.relname FROM pg_inherits "
            "JOIN pg_class parent ON pg_inherits.inhparent = parent.oid "
            "JOIN pg_class child ON pg_inherits.inhrelid = child.oid "
            "WHERE parent.relname = 'analytics_events'"
        ))).scalars().all()

        dropped = 0
        for relname in rows:
            # ждём формат analytics_events_YYYY_MM (default-партицию пропускаем)
            parts = relname.rsplit("_", 2)
            if len(parts) != 3 or not (parts[1].isdigit() and parts[2].isdigit()):
                continue
            p_idx = int(parts[1]) * 12 + (int(parts[2]) - 1)
            if p_idx < cutoff_idx:
                await session.execute(sa_text(f"DROP TABLE IF EXISTS {relname}"))
                dropped += 1
        await session.commit()

    logger.info(
        f"analytics partition maintenance: ensured {created} month(s), "
        f"dropped {dropped} old (retention={ANALYTICS_RETENTION_MONTHS}mo)"
    )
