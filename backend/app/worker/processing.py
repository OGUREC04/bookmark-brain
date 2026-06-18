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
from shared.messages import DEDUP_COMMANDS, compose, reply_hint_full

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
    send_rich_message,
    typing_action,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Единый источник правды для max_tries: WorkerSettings.max_tries импортирует
# эту константу. На последней попытке (job_try >= _PROCESS_MAX_TRIES) safety-net
# в process_bookmark_task ставит 👎 вместо застрявшего 👀.
_PROCESS_MAX_TRIES = 5


# Phase 2.7: формы reminder_decision, при которых сообщение — напоминание,
# а не закладка. Такие НЕ гоняем через general dedup: реминдер «купить хлеб
# завтра в 9» — действие во времени, а не дубль старой заметки про хлеб.
# Точные дубли реминдеров (тот же текст + минута) ловит E15 в create_reminder.
# Зеркалит исключение для task_list (_is_task_list_early). См. dedup×reminder bug.
_REMINDER_INTENT_FORMS = frozenset({
    "single_reminder",
    "composite_reminder",
    "needs_button_choice",
    "needs_hour",
    "strong_intent_3button",
})


def _has_reminder_intent(structured) -> bool:
    """True если у закладки есть reminder-intent (см. _REMINDER_INTENT_FORMS).

    Такие сообщения пропускают general dedup — иначе напоминание матчится
    как дубль старой заметки, реминдер не создаётся, а юзеру показывается
    бессмысленный алерт без даты/времени (bug 2026-05-24).
    """
    if not isinstance(structured, dict):
        return False
    decision = structured.get("reminder_decision")
    if not isinstance(decision, dict):
        return False
    return decision.get("form") in _REMINDER_INTENT_FORMS


def _spawn_bg(coro) -> None:
    """Fire-and-forget таск с логированием ошибок.

    Голый asyncio.create_task теряет исключение ("Task exception was never
    retrieved" в stderr, без записи в лог). Done-callback логирует фейл.
    """
    task = asyncio.create_task(coro)

    def _log_if_failed(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.warning("background task failed: %s", exc)

    task.add_done_callback(_log_if_failed)


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


def _build_result_card_markdown(title: str, summary: str, category: str) -> str:
    """Markdown rich-карточки результата: заголовок → summary → строка категории."""
    parts = [f"# ✅ {title}"]
    if summary:
        parts.append(summary[:200])
    if category:
        parts.append(f"Категория: {category}")
    return "\n\n".join(parts)


async def _send_result_card(
    chat_id: int,
    message_id: int,
    *,
    title: str,
    summary: str,
    category: str,
    text: str,
    buttons: dict,
) -> None:
    """Показывает карточку результата обработки обычной закладки.

    По умолчанию (RICH_MESSAGES off) — ``_edit_message`` поверх статус-сообщения,
    ровно как раньше (поведение 1:1). При RICH_MESSAGES on пробуем rich-карточку
    через ``sendRichMessage``: её нельзя редактировать, поэтому удаляем
    статус-сообщение и шлём новую. ЛЮБОЙ сбой (ok=false / исключение / выключенный
    флаг) → тот же ``_edit_message`` без изменений.
    """
    if settings.RICH_MESSAGES:
        try:
            markdown = _build_result_card_markdown(title, summary, category)
            resp = await send_rich_message(chat_id, markdown, buttons)
            if resp and resp.get("ok"):
                # Rich нельзя редактировать → убираем статус-сообщение,
                # карточка уже отправлена новой.
                await _delete_message(chat_id, message_id)
                return
            logger.debug(
                "rich card not sent (ok=false), fallback to edit: %s",
                (resp or {}).get("description"),
            )
        except Exception as e:  # noqa: BLE001 — fallback ниже
            logger.debug(f"rich card failed, fallback to edit: {e}")

    # Fallback / default: правим статус-сообщение, как раньше.
    await _edit_message(chat_id, message_id, text, buttons)


async def process_bookmark_task(
    ctx: dict,
    bookmark_id: str,
    chat_id: int | None = None,
    message_id: int | None = None,
    silent: bool = False,
) -> None:
    """arq-entrypoint AI-обработки закладки.

    Обёртка держит индикатор «печатает…» сверху чата на ВСЁ время обработки
    (bookmark-brain-5lt продолжение: фидбэк для текста/ссылок, где AI идёт в
    воркере после выхода из бот-хендлера — там был только 👀, без «живого»
    статуса до 👍). Пульс гаснет на выходе, ровно когда появляется результат.
    """
    async with typing_action(chat_id):
        await _process_bookmark_task_impl(
            ctx, bookmark_id,
            chat_id=chat_id, message_id=message_id, silent=silent,
        )


async def _maybe_build_connections(session, bookmark) -> int:
    """Phase 5A: строит смысловые связи для заметки на сохранении (best-effort).

    0 вызовов LLM — чистый pgvector kNN (NFR-1). Эмбеддинг уже персистнут
    выше. Ошибка связывания НЕ должна влиять на обработку закладки. Возвращает
    число созданных рёбер (для логов/тестов).
    """
    if (
        bookmark is None
        or bookmark.embedding is None
        or bookmark.ai_status not in ("completed", "partial")
    ):
        return 0
    try:
        from app.services.connections import build_links_for_bookmark
        emb = (
            bookmark.embedding.tolist()
            if hasattr(bookmark.embedding, "tolist")
            else list(bookmark.embedding)
        )
        n = await build_links_for_bookmark(
            session, bookmark.id, bookmark.user_id, emb,
        )
        if n:
            await session.commit()
            logger.info(f"Connections: built {n} link(s) for {bookmark.id}")
        return n
    except Exception as e:  # noqa: BLE001 — best-effort, не валим обработку
        logger.debug(f"Connections link build failed: {e}")
        try:
            await session.rollback()
        except Exception:
            pass
        return 0


async def _process_bookmark_task_impl(
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

        try:
            await processor.process_bookmark(UUID(bookmark_id), progress_callback=on_progress)
            await session.commit()
        except Exception as exc:
            # process_bookmark бросил (RetryableError перевыброшен для ретрая arq,
            # либо непойманное исключение). Сессия откатится — финальная реакция
            # (👍/👎) ниже не достигается → 👀 застрял бы навсегда. Safety-net:
            # на последней попытке ставим 👎, иначе отдаём arq на ретрай (👀 ждёт).
            job_try = ctx.get("job_try", 1)
            is_final = job_try >= _PROCESS_MAX_TRIES
            logger.warning(
                f"process_bookmark raised for {bookmark_id} "
                f"(try {job_try}/{_PROCESS_MAX_TRIES}, final={is_final}): {exc}"
            )
            if not is_final:
                # Закрываем embedding_service до re-raise — иначе на каждой из
                # промежуточных попыток создаётся новый клиент без закрытия
                # предыдущего (утечка соединений через ретраи).
                await embedding_service.close()
                raise  # arq перепоставит; 👀 остаётся как «ещё обрабатываю»
            if can_notify:
                if silent:
                    await _set_reaction(chat_id, message_id, "\U0001f44e")  # 👎
                    # ai_error юзеру не показываем (может содержать фрагменты
                    # промпта/имена моделей) — полное в server-side логах.
                    _spawn_bg(_send_message(
                        chat_id,
                        "⚠️ Не удалось обработать. Попробуй ещё раз или /help",
                    ))
                else:
                    await _edit_message(
                        chat_id, message_id,
                        "❌ Не удалось обработать. Попробуй ещё раз или /help",
                    )
            await embedding_service.close()
            return

        duration = time.monotonic() - start_time

        # Финальное уведомление
        from app.models import Bookmark, User
        result = await session.execute(
            select(Bookmark).where(Bookmark.id == UUID(bookmark_id))
        )
        bookmark = result.scalar_one_or_none()

        # Phase 5A (Connections): смысловые связи на сохранении (best-effort, 0 LLM).
        await _maybe_build_connections(session, bookmark)

        # Phase 5D-lite: general dedup detection (cosine > 0.95)
        # Если юзер прислал почти то же самое — спрашиваем через reply.
        # Запускаем даже при отсутствии embedding (Pass 2 — text overlap),
        # иначе partial-bookmarks после GigaChat-fail никогда не ловятся.
        #
        # ИСКЛЮЧЕНИЕ для task_list: сначала спрашиваем «Сохранить как
        # список?» (offer), и только если юзер скажет «Нет» — показываем
        # «уже есть похожая, что делать?» (general dedup отложен в bot tlx).
        _is_task_list_early = bool(
            bookmark and bookmark.structured_data
            and isinstance(bookmark.structured_data, dict)
            and bookmark.structured_data.get("type") == "task_list"
        )
        # Phase 2.7: напоминания пропускают general dedup (как и task_list).
        # Иначе «купить хлеб завтра в 9» матчится со старой заметкой про хлеб,
        # реминдер не создаётся, а алерт показывается без даты/времени.
        _reminder_intent_early = bool(
            bookmark and _has_reminder_intent(bookmark.structured_data)
        )
        near_dup_handled = False
        if (
            not _is_task_list_early
            and not _reminder_intent_early
            and bookmark
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
                    new_structured=bookmark.structured_data,
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

                    # Канон: reply-подсказка ПЕРВОЙ → заголовок → команды.
                    # DEDUP_COMMANDS из shared.messages — один в один с
                    # bot confirm.py (_send_general_dedup_alert).
                    alert_text = compose(
                        reply_hint_full(action="выбрать что делать с дублем"),
                        f"{prefix} {dup_type}: <b>{dup_title}</b>{date_str}",
                        DEDUP_COMMANDS,
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
                            src_msg_id=message_id,
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
                # #5/bd-86g: подтверждение-флоу делает ранний выход и
                # пропускает Phase 1.5A dedup-alert. Поэтому СНАЧАЛА ищем
                # похожий незакрытый список. Если он есть — НЕ спрашиваем
                # «Сделать список?», а идём прямым путём (создаём+пин+
                # dedup-alert как раньше), чтобы фича «похожий список» не
                # отваливалась при включённом подтверждении. Результат
                # переиспользуется ниже (без повторного vector-запроса).
                similar: dict | None = None
                general_dup: dict | None = None
                if bookmark.embedding is not None:
                    _emb_list = (
                        bookmark.embedding.tolist()
                        if hasattr(bookmark.embedding, 'tolist')
                        else list(bookmark.embedding)
                    )
                    try:
                        from app.services.dedup_checker import (
                            find_similar_unclosed_task_list,
                        )
                        similar = await find_similar_unclosed_task_list(
                            session, bookmark.id, bookmark.user_id, _emb_list,
                        )
                    except Exception as e:
                        logger.debug(f"pre-offer similar check failed: {e}")
                    # General near-dup (любой тип) — для «Нет» tlx.
                    # Показываем «уже есть похожая, что делать?» ТОЛЬКО
                    # если юзер откажется создавать список.
                    try:
                        from app.services.dedup_checker import find_near_duplicate
                        general_dup = await find_near_duplicate(
                            session, bookmark.id, bookmark.user_id,
                            _emb_list, raw_text=bookmark.raw_text or "",
                            new_structured=bookmark.structured_data,
                        )
                    except Exception as e:
                        logger.debug(f"pre-offer general dedup failed: {e}")

                # Подтверждение перед созданием+пином ВСЕГДА (offer и
                # dedup-alert — разные слои UX). similar → post-confirm
                # merge-alert (bot tlc). general_dup → отложенный
                # near-dup при «Нет» (bot tlx).
                if can_notify:
                    from .task_list_offer import _maybe_offer_task_list
                    if await _maybe_offer_task_list(
                        bookmark=bookmark, chat_id=chat_id,
                        message_id=message_id, silent=silent,
                        similar=similar, general_dup=general_dup,
                    ):
                        await session.commit()
                        await embedding_service.close()
                        logger.info(
                            f"Task-list {bookmark_id}: awaiting user confirmation"
                        )
                        return

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
                        # Удаляем оригинал юзера (дубль списка) + снимаем 👀.
                        # Голос/аудио/видео — это запись, не дубль текста,
                        # её НЕ удаляем (юзер хочет видеть источник).
                        _src_ct = getattr(bookmark, "content_type", None) or "text"
                        if _src_ct == "text":
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

                    # Phase 1.5A: Dedup-alert. similar уже посчитан выше
                    # (pre-offer) — переиспользуем, без повторного запроса.
                    if similar is not None and task_list_msg_id is not None:
                        try:
                            sim_id = similar.get("id") if similar else None
                            if similar and sim_id is not None:
                                alert_text, alert_buttons = _build_dedup_alert(similar, bookmark_id)
                                alert_resp = await _send_message(chat_id, alert_text, alert_buttons)
                                if alert_resp:
                                    # Redis key по new_bid (а не msg_id) — кнопки уже содержат bid
                                    await _store_dedup_alert(
                                        chat_id, bookmark_id,
                                        sim_id, task_list_msg_id,
                                    )
                                    sim_score = float(similar.get("similarity") or 0.0)
                                    logger.info(
                                        f"Dedup alert sent for {bookmark_id}: "
                                        f"similar to {sim_id} (sim={sim_score:.2f})"
                                    )
                            elif similar:
                                logger.warning(
                                    f"Dedup alert skipped for {bookmark_id}: "
                                    f"similar payload missing 'id': {list(similar.keys())}"
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

                elif bookmark.source != "miniapp":
                    # Fallback: новое сообщение (нет chat_id/message_id). НЕ для Mini App —
                    # чат-дубль не нужен (список создан и виден в приложении, ti0).
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
                        category = bookmark.category or ""
                        lines = [f"✅ <b>{title}</b>"]
                        if category:
                            lines.append(f"Категория: {category}")
                        if summary:
                            lines.append(summary[:200])
                        lines.append(f"\n⏱ Обработано за {duration:.1f} сек")
                        text = "\n".join(lines)
                        buttons = _result_buttons(bookmark_id)
                        # RICH_MESSAGES off (default) → _edit_message 1:1 как раньше.
                        # on → rich-карточка с fallback на тот же _edit_message.
                        await _send_result_card(
                            chat_id, message_id,
                            title=title, summary=summary, category=category,
                            text=text, buttons=buttons,
                        )
                elif bookmark.source != "miniapp":
                    # Fallback: новое сообщение по telegram_id. НЕ для Mini App — заметка
                    # создана в приложении, чат-дубль не нужен (результат виден в app, ti0).
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


async def redispatch_reminder_task(
    ctx: dict,
    bookmark_id: str,
    chat_id: int | None = None,
) -> bool:
    """Re-dispatch persisted `reminder_decision` для одной закладки (ied).

    Контекст: при near-duplicate `process_bookmark_task` пропускает
    `_dispatch_reminder_decision` (см. `near_dup_handled`). Если юзер потом
    выбирает «сохрани как новую», reminder'ы из уже сохранённого decision
    иначе теряются. Эта джоба переигрывает dispatch по persisted decision.

    Идемпотентна: `_dispatch_reminder_decision` защищён CAS-флагом
    `reminder_decision_applied`, так что повторный вызов (или гонка с
    auto-create) не плодит дубли.

    Returns True если decision был обработан.
    """
    from app.database import async_session
    from app.models import Bookmark

    try:
        async with async_session() as session:
            res = await session.execute(
                select(Bookmark).where(Bookmark.id == UUID(bookmark_id))
            )
            bookmark = res.scalar_one_or_none()
            if bookmark is None:
                logger.warning("redispatch_reminder_task: bookmark %s not found", bookmark_id)
                return False
            return await _dispatch_reminder_decision(bookmark=bookmark, chat_id=chat_id)
    except Exception as e:
        logger.warning("redispatch_reminder_task failed for %s: %s", bookmark_id, e)
        return False
