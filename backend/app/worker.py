import asyncio
import logging
import time
from uuid import UUID

import httpx
import redis.asyncio as aioredis
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session


def aioredis_from_url(url: str):
    """Тонкий wrapper — оставляет точку для monkeypatch в тестах."""
    return aioredis.from_url(url, decode_responses=True)


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

logger = logging.getLogger(__name__)
settings = get_settings()

BOT_API = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


async def _edit_message(chat_id: int, message_id: int, text: str, reply_markup: dict | None = None) -> None:
    """Редактирует сообщение в Telegram."""
    try:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{BOT_API}/editMessageText", json=payload)
    except Exception as e:
        logger.debug(f"Failed to edit message: {e}")


async def _send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> dict | None:
    """Отправляет новое сообщение в Telegram. Возвращает result dict (с message_id) или None."""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{BOT_API}/sendMessage", json=payload)
            data = resp.json()
            if data.get("ok"):
                return data.get("result")
            return None
    except Exception as e:
        logger.debug(f"Failed to send message: {e}")
        return None


async def _bind_task_list_message(chat_id: int, message_id: int, bookmark_id: str) -> None:
    """Регистрируем (chat_id, message_id) → bookmark_id в Redis,
    чтобы bot reply-handler мог применить NL-edit к этому списку.

    Ключ и TTL совпадают с bot/state_store.py StateStore.bind_list_message.
    """
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await r.set(
                f"task_list_msg:{chat_id}:{message_id}",
                bookmark_id,
                ex=14 * 24 * 3600,
            )
        finally:
            await r.aclose()
    except Exception as e:
        logger.debug(f"bind_task_list_message failed: {e}")


async def _pin_message(chat_id: int, message_id: int) -> None:
    """Закрепляет сообщение в чате (без уведомления, чтобы не шуметь)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{BOT_API}/pinChatMessage",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "disable_notification": True,
                },
            )
    except Exception as e:
        logger.debug(f"Failed to pin: {e}")


async def _delete_message(chat_id: int, message_id: int) -> None:
    """Удаляет сообщение в Telegram (best-effort)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{BOT_API}/deleteMessage",
                json={"chat_id": chat_id, "message_id": message_id},
            )
    except Exception as e:
        logger.debug(f"Failed to delete message: {e}")


async def _set_reaction(chat_id: int, message_id: int, emoji: str | None) -> None:
    """Ставит/убирает реакцию на сообщение в Telegram (best-effort)."""
    try:
        reaction = [{"type": "emoji", "emoji": emoji}] if emoji else []
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": reaction,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{BOT_API}/setMessageReaction", json=payload)
    except Exception as e:
        logger.debug(f"Failed to set reaction: {e}")


async def _send_ephemeral(chat_id: int, text: str, delay: float = 10) -> None:
    """Отправляет сообщение и удаляет его через delay секунд (best-effort)."""
    try:
        # Отправляем — отдельный клиент, закрывается сразу
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BOT_API}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        data = resp.json()
        if data.get("ok") and data.get("result", {}).get("message_id"):
            sent_msg_id = data["result"]["message_id"]
            # Sleep вне httpx client — не держим TCP-соединение
            await asyncio.sleep(delay)
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{BOT_API}/deleteMessage",
                    json={"chat_id": chat_id, "message_id": sent_msg_id},
                )
    except Exception as e:
        logger.debug(f"Failed to send ephemeral: {e}")


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
    new_bid: str, old_bid: str,
) -> None:
    """Сохраняет состояние general dedup в Redis.

    Ключ: general_dedup:{chat_id}:{alert_msg_id}.
    Bot reply handler использует этот ключ для обработки ответа юзера.
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
                }),
                ex=24 * 3600,
            )
            # pending_dedup — чтобы следующее сообщение без reply тоже работало
            await r.set(
                f"pending_dedup:{chat_id}",
                str(alert_msg_id),
                ex=5 * 60,  # 5 минут
            )
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


def _result_buttons(bookmark_id: str) -> dict:
    """Inline-кнопки для результата обработки."""
    return {
        "inline_keyboard": [
            [
                {"text": "📖 Открыть", "callback_data": f"view:{bookmark_id}"},
                {"text": "🗑 Удалить", "callback_data": f"del:{bookmark_id}"},
            ],
            [
                {"text": "📋 Все закладки", "callback_data": "page:1"},
            ],
        ]
    }


async def process_bookmark_task(
    ctx: dict,
    bookmark_id: str,
    chat_id: int | None = None,
    message_id: int | None = None,
    silent: bool = False,
) -> None:
    """Задача: AI-обработка одной закладки.

    silent=False (verbose): текстовые сообщения с прогрессом (legacy).
    silent=True: реакции 👀→👍/👎, без промежуточных сообщений.
    """
    from app.database import async_session
    from app.services.ai_classifier import create_classifier
    from app.services.bookmark_processor import BookmarkProcessor
    from app.services.embeddings import create_embedding_service

    can_notify = chat_id is not None and message_id is not None
    start_time = time.monotonic()

    # Этап 1: Подготовка
    if can_notify and not silent:
        await _edit_message(chat_id, message_id, "⏳ Загружаю закладку...")
    # В silent mode 👀 уже стоит — ставил бот при получении сообщения

    _api_key = {
        "gigachat": settings.GIGACHAT_AUTH_KEY,
        "deepseek": settings.DEEPSEEK_API_KEY,
        "claude": settings.ANTHROPIC_API_KEY,
    }.get(settings.AI_PROVIDER, "")
    classifier = create_classifier(
        provider=settings.AI_PROVIDER,
        auth_key=_api_key,
        api_key=_api_key,
        ca_bundle=settings.GIGACHAT_CA_BUNDLE,
    )
    embedding_service = create_embedding_service(
        provider=settings.EMBEDDING_PROVIDER,
        auth_key=settings.GIGACHAT_AUTH_KEY,
        api_key=settings.VOYAGE_API_KEY,
        ca_bundle=settings.GIGACHAT_CA_BUNDLE,
    )

    async with async_session() as session:
        processor = BookmarkProcessor(session, classifier, embedding_service)

        # Подписываемся на прогресс через callback (только verbose)
        async def on_progress(stage: str):
            if can_notify and not silent:
                elapsed = time.monotonic() - start_time
                await _edit_message(
                    chat_id, message_id,
                    f"{stage}\n⏱ {elapsed:.0f} сек..."
                )

        await processor.process_bookmark(UUID(bookmark_id), progress_callback=on_progress)
        await session.commit()

        duration = time.monotonic() - start_time

        # Финальное уведомление
        from app.models import Bookmark, User
        result = await session.execute(
            select(Bookmark).where(Bookmark.id == UUID(bookmark_id))
        )
        bookmark = result.scalar_one_or_none()

        # Phase 5D-lite: general dedup detection (cosine > 0.95)
        # Если юзер прислал почти то же самое — спрашиваем через reply.
        # Запускаем даже при отсутствии embedding (Pass 2 — text overlap),
        # иначе partial-bookmarks после GigaChat-fail никогда не ловятся.
        near_dup_handled = False
        if (
            bookmark
            and bookmark.ai_status in ("completed", "partial")
            and can_notify
        ):
            try:
                from app.services.dedup_checker import find_near_duplicate
                # embedding может быть None если AI упал (partial-rescue ветка).
                # find_near_duplicate в этом случае пропускает Pass 1 и идёт
                # в Pass 2 (text overlap) — он работает без embedding.
                emb = None
                if bookmark.embedding is not None:
                    emb = (
                        bookmark.embedding.tolist()
                        if hasattr(bookmark.embedding, 'tolist')
                        else list(bookmark.embedding)
                    )
                dup = await find_near_duplicate(
                    session, bookmark.id, bookmark.user_id,
                    emb,
                    raw_text=bookmark.raw_text or "",
                )
                if dup:
                    dup_title = dup.get("title") or "Без названия"
                    dup_type = "список" if dup.get("is_task_list") else "закладку"
                    date_str = ""
                    created = dup.get("created_at")
                    if created:
                        try:
                            from datetime import datetime as _dt
                            if isinstance(created, str):
                                created = _dt.fromisoformat(created)
                            date_str = f" от {created.strftime('%d.%m')}"
                        except Exception:
                            pass

                    # Чем выше похожесть, тем явнее текст:
                    # >0.95 = почти дубликат, 0.85-0.95 = похоже
                    similarity = dup.get("similarity") or 0.0
                    if similarity >= 0.95:
                        prefix = "⚠️ Уже есть почти такая же"
                    else:
                        prefix = "🔄 Похожая запись уже сохранялась"

                    alert_text = (
                        f"{prefix} {dup_type}: <b>{dup_title}</b>{date_str}\n\n"
                        f"Что делаем с новой? Ответь reply на это сообщение:\n"
                        f"• <b>открой</b> — покажу старую\n"
                        f"• <b>удали</b> — удалю новую (старая останется)\n"
                        f"• <b>обнови</b> — заменю старую новой\n"
                        f"• <b>сохрани как новую</b> — оставлю обе"
                    )

                    if silent:
                        # Снимаем 👀
                        await _set_reaction(chat_id, message_id, None)

                    alert_resp = await _send_message(chat_id, alert_text)
                    if alert_resp and alert_resp.get("message_id"):
                        alert_mid = alert_resp["message_id"]
                        await _store_general_dedup(
                            chat_id, alert_mid,
                            bookmark_id, dup["id"],
                        )
                        near_dup_handled = True
                        logger.info(
                            f"Near-duplicate detected for {bookmark_id}: "
                            f"matches {dup['id']} (sim={dup['similarity']:.3f})"
                        )
            except Exception as e:
                logger.debug(f"General dedup check failed: {e}")

        if not near_dup_handled and bookmark and bookmark.ai_status in ("completed", "partial"):
            # Task list — специальный рендер с чекбоксами
            if (
                bookmark.structured_data
                and isinstance(bookmark.structured_data, dict)
                and bookmark.structured_data.get("type") == "task_list"
            ):
                from app.services.task_list_renderer import (
                    build_task_list_keyboard,
                    render_task_list_text,
                )
                bookmark.is_favorite = True
                await session.flush()

                # msg_id списка (для dedup-alert ниже)
                task_list_msg_id: int | None = None

                if can_notify:
                    if silent:
                        # Silent: текст без кнопок, только reply-инструкция
                        text = render_task_list_text(
                            bookmark.title,
                            bookmark.structured_data,
                            silent=True,
                        )
                        # Удаляем оригинал юзера (дубль списка) + снимаем 👀
                        await _delete_message(chat_id, message_id)
                        resp = await _send_message(chat_id, text)
                        if resp and resp.get("message_id"):
                            new_msg_id = resp["message_id"]
                            task_list_msg_id = new_msg_id
                            # bind ПЕРЕД pin — иначе on_pin_service_message не найдёт
                            # list в Redis и не удалит сервисное «закрепил(а)»
                            await _bind_task_list_message(chat_id, new_msg_id, bookmark_id)
                            await _pin_message(chat_id, new_msg_id)
                    else:
                        # Verbose: текст + inline-кнопки (legacy)
                        text = render_task_list_text(
                            bookmark.title,
                            bookmark.structured_data,
                        )
                        buttons = build_task_list_keyboard(
                            bookmark_id, bookmark.structured_data
                        )
                        await _edit_message(chat_id, message_id, text, buttons)
                        task_list_msg_id = message_id
                        # bind ПЕРЕД pin — on_pin_service_message ищет в Redis
                        await _bind_task_list_message(chat_id, message_id, bookmark_id)
                        await _pin_message(chat_id, message_id)

                    # Phase 1.5A: Dedup-alert — ищем похожий незакрытый список
                    if bookmark.embedding is not None and task_list_msg_id is not None:
                        try:
                            from app.services.dedup_checker import find_similar_unclosed_task_list
                            similar = await find_similar_unclosed_task_list(
                                session, bookmark.id, bookmark.user_id,
                                bookmark.embedding.tolist() if hasattr(bookmark.embedding, 'tolist') else list(bookmark.embedding),
                            )
                            if similar:
                                alert_text, alert_buttons = _build_dedup_alert(similar, bookmark_id)
                                alert_resp = await _send_message(chat_id, alert_text, alert_buttons)
                                if alert_resp:
                                    # Redis key по new_bid (а не msg_id) — кнопки уже содержат bid
                                    await _store_dedup_alert(
                                        chat_id, bookmark_id,
                                        similar["id"], task_list_msg_id,
                                    )
                                    logger.info(
                                        f"Dedup alert sent for {bookmark_id}: "
                                        f"similar to {similar['id']} (sim={similar['similarity']:.2f})"
                                    )
                        except Exception as e:
                            # Dedup — best-effort, никогда не ломаем основной flow
                            logger.debug(f"Dedup check failed for {bookmark_id}: {e}")

                    # Phase 2 Onboarding: первая подсказка про reply-команды
                    if task_list_msg_id is not None:
                        try:
                            await _maybe_send_first_task_list_tip(
                                session, bookmark.user_id, chat_id,
                            )
                        except Exception as e:
                            logger.debug(f"First task_list tip failed: {e}")

                else:
                    # Fallback: новое сообщение (нет chat_id/message_id)
                    text = render_task_list_text(
                        bookmark.title,
                        bookmark.structured_data,
                    )
                    buttons = build_task_list_keyboard(
                        bookmark_id, bookmark.structured_data
                    )
                    user_result = await session.execute(
                        select(User).where(User.id == bookmark.user_id)
                    )
                    user = user_result.scalar_one_or_none()
                    if user:
                        await _send_message(user.telegram_id, text, buttons)

            else:
                # Обычная закладка
                if can_notify:
                    if silent:
                        # Silent: просто ставим 👍 на оригинальное сообщение
                        await _set_reaction(chat_id, message_id, "\U0001f44d")
                    else:
                        title = bookmark.title or "Закладка"
                        summary = bookmark.summary or ""
                        lines = [f"✅ <b>{title}</b>"]
                        if bookmark.category:
                            lines.append(f"Категория: {bookmark.category}")
                        if summary:
                            lines.append(summary[:200])
                        lines.append(f"\n⏱ Обработано за {duration:.1f} сек")
                        text = "\n".join(lines)
                        buttons = _result_buttons(bookmark_id)
                        await _edit_message(chat_id, message_id, text, buttons)
                else:
                    # Fallback: отправить новое сообщение (verbose текст)
                    user_result = await session.execute(
                        select(User).where(User.id == bookmark.user_id)
                    )
                    user = user_result.scalar_one_or_none()
                    if user:
                        title = bookmark.title or "Закладка"
                        summary = bookmark.summary or ""
                        lines = [f"✅ <b>{title}</b>"]
                        if bookmark.category:
                            lines.append(f"Категория: {bookmark.category}")
                        if summary:
                            lines.append(summary[:200])
                        text = "\n".join(lines)
                        buttons = _result_buttons(bookmark_id)
                        await _send_message(user.telegram_id, text, buttons)

        elif bookmark and can_notify and not near_dup_handled:
            # Ошибка обработки
            if silent:
                await _set_reaction(chat_id, message_id, "\U0001f44e")
                # Ошибка должна ОСТАВАТЬСЯ в чате — юзер сам решит когда убрать.
                # Отправляем обычным сообщением без авто-удаления.
                # Не показываем bookmark.ai_error юзеру — может содержать
                # сырые ответы AI / фрагменты промпта / имена моделей.
                # Полная ошибка — в server-side логах.
                asyncio.create_task(_send_message(
                    chat_id,
                    "⚠️ Не удалось обработать. Попробуй ещё раз или /help",
                ))
            else:
                elapsed = time.monotonic() - start_time
                await _edit_message(
                    chat_id, message_id,
                    f"❌ Не удалось обработать\n{bookmark.ai_error or ''}\n⏱ {elapsed:.1f} сек"
                )

        # Final commit to persist any post-processing changes (e.g. is_favorite for task lists)
        await session.commit()

        # T8 — Reminder offer: показать кнопку «Создать напоминание?»
        # если detector нашёл intent. Skip при near-duplicate (юзер уже
        # выбирает что делать с дублем — не загромождаем UI).
        if (
            bookmark
            and bookmark.ai_status in ("completed", "partial")
            and not near_dup_handled
        ):
            try:
                await _maybe_offer_reminder(
                    bookmark=bookmark, chat_id=chat_id, silent=silent,
                )
            except Exception as e:
                logger.debug(f"reminder offer failed: {e}")

        # Onboarding: подсказка при первом сохранении
        if (
            bookmark
            and bookmark.ai_status in ("completed", "partial")
            and can_notify
            and silent
            and not near_dup_handled
        ):
            # Phase 2 Onboarding: первая подсказка теперь идёт через bot/onboarding.py
            # после успешного create_bookmark — не дублируем здесь.
            pass

    await embedding_service.close()
    logger.info(f"Task completed for bookmark {bookmark_id} in {duration:.1f}s")


# ──────────────────────────────────────────────────
# Reminder offer (T8) — кнопка «Создать напоминание?» после save
# ──────────────────────────────────────────────────


# TTL для reminder_pending — час хватает, чтобы юзер успел нажать
# и потом ответить reply'ем со временем.
REMINDER_PENDING_TTL_SEC = 3600


def _reminder_offer_buttons(bookmark_id: str) -> dict:
    """Одна кнопка по UX-спеке: «🔔 Создать напоминание?».

    Префиксы callback'ов:
      rsk:<bid> — да, создать (бот попросит время через reply)
      rsn:<bid> — нет, отказаться (бот удалит сообщение)
    """
    return {
        "inline_keyboard": [
            [
                {"text": "🔔 Создать напоминание?", "callback_data": f"rsk:{bookmark_id}"},
                {"text": "✕", "callback_data": f"rsn:{bookmark_id}"},
            ]
        ]
    }


def _reminder_offer_text() -> str:
    """Тело сообщения: подсказка про reply с примерами времени."""
    return (
        "Похоже, тут что-то напомнить. Если да — нажми кнопку, "
        "потом ответь <i>reply'ем</i> на это сообщение, когда напомнить.\n\n"
        "Примеры:\n"
        "• <code>завтра в 9</code>\n"
        "• <code>через час</code>\n"
        "• <code>в субботу</code>\n"
        "• <code>в субботу в 18</code>\n"
        "• <code>15 мая</code>\n"
        "• <code>на праздниках</code>"
    )


async def _maybe_offer_reminder(
    *, bookmark, chat_id: int | None, silent: bool,
) -> None:
    """Если bookmark.structured_data.reminder_intent=True и НЕ silent —
    шлём offer message с одной кнопкой и подсказкой про reply.

    Best-effort: любые ошибки проглатываем, основной flow не ломаем.
    """
    if chat_id is None or silent:
        return

    structured = getattr(bookmark, "structured_data", None) or {}
    if not isinstance(structured, dict):
        return
    if not structured.get("reminder_intent"):
        return

    bookmark_id = str(bookmark.id)
    text = _reminder_offer_text()
    buttons = _reminder_offer_buttons(bookmark_id)

    try:
        sent = await _send_message(chat_id, text, buttons)
        if not sent or not sent.get("message_id"):
            return
        msg_id = sent["message_id"]
        # Redis state — bot reply-handler читает по этому ключу
        r = aioredis_from_url(settings.REDIS_URL)
        try:
            await r.set(
                f"reminder_pending:{chat_id}:{msg_id}",
                bookmark_id,
                ex=REMINDER_PENDING_TTL_SEC,
            )
        finally:
            await r.aclose()
    except Exception as e:
        logger.debug(f"_maybe_offer_reminder failed for {bookmark.id}: {e}")


# ──────────────────────────────────────────────────
# Reminders dispatcher (Phase 2.5)
# ──────────────────────────────────────────────────


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
            payload = row[6] or {}

            # CAS lock — только один worker берёт reminder.
            # Возвращаем актуальные поля (retry_count может отличаться от
            # snapshot в SELECT выше).
            cas_result = await session.execute(sa_text(
                """
                UPDATE scheduled_messages
                SET status = 'sending'
                WHERE id = :id AND status = 'pending'
                RETURNING id, user_id, bookmark_id, payload, retry_count
                """
            ).bindparams(id=sm_id))
            locked = cas_result.scalar_one_or_none()
            if locked is None:
                # Другой worker уже захватил — пропускаем
                continue

            text_msg = _format_reminder_text(payload)
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
                current_retry = getattr(locked, "retry_count", 0) or 0
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
    """Cron (раз в час): помечаем sent reminder'ы старше 24h как auto_done.

    Если юзер не нажал «Выполнено» / «Продлить» в течение суток — значит
    задача либо сделана и забыта, либо неактуальна. Дальше реминдер не
    висит в активных.
    """
    from sqlalchemy import text as sa_text

    async with async_session() as session:
        result = await session.execute(sa_text(
            """
            UPDATE scheduled_messages
            SET status = 'auto_done'
            WHERE kind = 'reminder'
              AND status = 'sent'
              AND sent_at < NOW() - (:hours || ' hours')::interval
            """
        ).bindparams(hours=str(AUTO_DONE_HOURS)))
        await session.commit()
        rowcount = getattr(result, "rowcount", 0) or 0
        if rowcount:
            logger.info(f"auto_done_reminders: marked {rowcount} reminder(s) as auto_done")
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


async def retry_partial_embeddings(ctx: dict) -> None:
    """Cron: retry embedding for partial bookmarks (classification OK, embedding failed).

    Runs daily at 5:00 AM (after retry_failed at 3:00 AM).
    Max 5 retries per bookmark, circuit breaker after 5 consecutive failures.
    """
    from datetime import datetime, timezone
    from app.database import async_session
    from app.models import Bookmark
    from app.services.embeddings import create_embedding_service, EmbeddingError, RetryableEmbeddingError

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

            # Rebuild embedding text from existing classification data
            text_parts = []
            if bookmark.title:
                text_parts.append(bookmark.title)
            if bookmark.takeaway:
                text_parts.append(bookmark.takeaway)
            if bookmark.summary:
                text_parts.append(bookmark.summary)
            if bookmark.key_ideas:
                text_parts.extend(bookmark.key_ideas)
            if not text_parts:
                text_parts.append(bookmark.raw_text[:2000])

            embedding_text = "\n".join(text_parts)
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


async def stale_list_nudge(ctx: dict) -> None:
    """Cron: утреннее напоминание о незакрытых списках задач.

    Ищет task_list'ы старше 24ч с done < total, отправляет nudge в Telegram.
    Не напоминает повторно (Redis nudged:{bookmark_id} TTL 7 дней).
    """
    from sqlalchemy import and_, text
    from app.database import async_session
    from app.models import Bookmark, User

    logger.info("Stale list nudge: starting check")

    async with async_session() as session:
        # Ищем task_list'ы: ai_status completed/partial, не archived,
        # structured_data.type = 'task_list', старше 24ч
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
            )
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
                f"↩️ <i>Ответь reply: перенести / закрыть / оставить</i>"
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
                logger.info(f"Nudge sent for {bid} to {telegram_id}")
    finally:
        if r is not None:
            await r.aclose()

    logger.info(f"Stale list nudge: sent {nudge_count} nudges")


class WorkerSettings:
    functions = [process_bookmark_task]
    cron_jobs = [
        cron(retry_failed_task, hour=3, minute=0),
        cron(retry_partial_embeddings, hour=5, minute=0),
        cron(stale_list_nudge, hour=settings.NUDGE_HOUR_UTC, minute=0),
        # Phase 2.5 Reminders MVP
        # Каждую минуту проверяем due reminder'ы. set() = «каждую минуту любого часа».
        cron(scheduled_dispatcher, minute=set(range(60)), run_at_startup=False),
        # Раз в час, в :15 (чтобы не совпадало с пиком dispatcher на :00)
        cron(auto_done_reminders, minute={15}, run_at_startup=False),
    ]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 5
    job_timeout = 120
