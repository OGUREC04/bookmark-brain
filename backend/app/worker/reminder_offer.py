"""T8 reminder offer — кнопка «Создать напоминание?» после save (0dj).

No arq entrypoint. Used by ``processing.py`` as Phase 2.5 legacy fallback.

Tests patch ``app.worker._send_message`` / ``app.worker.aioredis_from_url``;
after the split those names are looked up in THIS module, so the worker-test
patches target ``app.worker.reminder_offer.*``.
"""

from __future__ import annotations

import html
import logging

from app.config import get_settings
from shared.messages import compose, reply_hint_full

from .telegram import _delete_message, _send_message, aioredis_from_url

logger = logging.getLogger(__name__)
settings = get_settings()


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


def _reminder_offer_text(label: str = "") -> str:
    """Текст оффера в КАНОН-порядке: reply-подсказка → заголовок → примеры.

    ``label`` — текст закладки (про что напоминание), УЖЕ html-экранированный
    вызывающим (slice→escape). Пустой → общий заголовок.
    """
    heading = (
        f"🔔 Напомнить про «<b>{label}</b>»?"
        if label else
        "🔔 Что-то напомнить?"
    )
    examples = (
        "Примеры времени:\n"
        "• <code>завтра в 9</code>\n"
        "• <code>через час</code>\n"
        "• <code>в субботу</code>\n"
        "• <code>в субботу в 18</code>\n"
        "• <code>15 мая</code>\n"
        "• <code>на праздниках</code>"
    )
    return compose(
        reply_hint_full(action="указать время после кнопки «Создать»"),
        heading,
        examples,
    )


async def _maybe_offer_reminder(
    *, bookmark, chat_id: int | None, silent: bool,
) -> None:
    """Если bookmark.structured_data.reminder_intent=True — шлём offer
    с одной кнопкой и подсказкой про reply.

    Silent mode НЕ блокирует offer: silent_mode по дефолту True у
    каждого юзера, иначе фича reminders становится невидимой. Offer —
    это одно сообщение с одной кнопкой, минимум шума.

    Best-effort: любые ошибки проглатываем, основной flow не ломаем.
    """
    if chat_id is None:
        return

    structured = getattr(bookmark, "structured_data", None) or {}
    if not isinstance(structured, dict):
        return
    if not structured.get("reminder_intent"):
        return

    # T13 anti-double-offer: если юзер уже выбрал «📝 Заметка» в strong-flow,
    # не показываем второй offer на ту же исходную message_id.
    # Bot ставит strong_handled:{chat_id}:{source_msg_id} TTL 5 мин.
    src_msg_id = (
        getattr(bookmark, "source_message_id", None)
        or (structured.get("source_message_id") if isinstance(structured, dict) else None)
    )
    if src_msg_id is not None:
        try:
            r_check = aioredis_from_url(settings.REDIS_URL)
            try:
                handled = await r_check.get(f"strong_handled:{chat_id}:{src_msg_id}")
                if handled:
                    logger.info(
                        f"_maybe_offer_reminder: skip — strong_handled flag for "
                        f"{chat_id}:{src_msg_id}"
                    )
                    return
            finally:
                await r_check.aclose()
        except Exception as e:
            logger.debug(f"_maybe_offer_reminder: anti-double check failed: {e}")

    bookmark_id = str(bookmark.id)
    # bug 2026-06-09: показываем, ПРО ЧТО напоминание. SLICE до 60, ПОТОМ escape
    # (иначе можно разрезать &amp; → Telegram 400). _send_message всегда HTML,
    # поэтому экранирование обязательно — иначе title с <>& уронит весь offer.
    raw_label = (
        getattr(bookmark, "title", None)
        or getattr(bookmark, "raw_text", None)
        or ""
    ).strip()[:60]
    label = html.escape(raw_label) if raw_label else ""
    text = _reminder_offer_text(label)
    buttons = _reminder_offer_buttons(bookmark_id)

    # F3: probe Redis ДО отправки сообщения. Иначе если Redis упал между
    # send и SET — в чате висит кнопка которая не работает (silent UX fail).
    # Probe-ключ заодно содержит bookmark_id — на случай если final SET
    # не дойдёт, мы хотя бы знаем что offer был.
    r = None
    sent = None
    msg_id = None
    probe_key = f"reminder_pending_probe:{chat_id}:{bookmark_id}"
    try:
        r = aioredis_from_url(settings.REDIS_URL)
        try:
            await r.set(probe_key, bookmark_id, ex=60)
        except Exception as e:
            logger.warning(
                f"_maybe_offer_reminder: Redis probe failed, skipping offer for "
                f"{bookmark.id}: {e}"
            )
            return

        # Redis жив — теперь безопасно отправлять
        sent = await _send_message(chat_id, text, buttons)
        if not sent or not sent.get("message_id"):
            # Send упал — чистим probe чтобы не висел orphan
            try:
                await r.delete(probe_key)
            except Exception:
                pass
            return
        msg_id = sent["message_id"]

        # Финальный SET с реальным msg_id.
        # 12y: JSON envelope вместо голой UUID-строки.
        # Bot reader умеет читать оба формата (legacy + envelope).
        import json as _json
        try:
            await r.set(
                f"reminder_pending:{chat_id}:{msg_id}",
                _json.dumps({"kind": "bookmark", "bookmark_id": bookmark_id}),
                ex=REMINDER_PENDING_TTL_SEC,
            )
            await r.delete(probe_key)
        except Exception as e:
            # Probe прошёл, но финальная запись упала (race?). Удаляем
            # сообщение в чате чтобы не было broken-button.
            logger.warning(
                f"_maybe_offer_reminder: probe ok but final SET failed for "
                f"{bookmark.id}, deleting offer message: {e}"
            )
            try:
                await _delete_message(chat_id, msg_id)
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"_maybe_offer_reminder failed for {bookmark.id}: {e}")
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass
