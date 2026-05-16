"""Main arq job — AI-обработка одной закладки (worker split — 0dj).

``process_bookmark_task`` is wired into ``WorkerSettings.functions``.
Imports helpers from telegram / dedup / reminder_offer / reminder_decision.
"""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session

from .dedup import (
    _build_dedup_alert,
    _maybe_send_first_task_list_tip,
    _store_dedup_alert,
    _store_general_dedup,
)
from .reminder_decision import _dispatch_reminder_decision
from .reminder_offer import _maybe_offer_reminder
from .telegram import (
    _bind_task_list_message,
    _delete_message,
    _edit_message,
    _pin_message,
    _send_message,
    _set_reaction,
)

logger = logging.getLogger(__name__)
settings = get_settings()


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
        #
        # Phase 2.6: сначала пробуем dispatch по router-decision (auto-create
        # / 3-button / Reply-ask). Если decision пуст или form=NONE/strong —
        # fallback на legacy Phase 2.5 _maybe_offer_reminder.
        if (
            bookmark
            and bookmark.ai_status in ("completed", "partial")
            and not near_dup_handled
        ):
            try:
                handled = await _dispatch_reminder_decision(
                    bookmark=bookmark, chat_id=chat_id,
                )
                if not handled:
                    await _maybe_offer_reminder(
                        bookmark=bookmark, chat_id=chat_id, silent=silent,
                    )
            except Exception as e:
                logger.debug(f"reminder dispatch/offer failed: {e}")

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
