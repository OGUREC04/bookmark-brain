"""Task-list confirmation offer — «Сделать список?» до создания+пина.

No arq entrypoint. Used by ``processing.py``: вместо немедленного
создания+пина task_list бот спрашивает подтверждение (как reminder-offer).
Только после «Да» список рендерится, биндится и пинится (bot-side
``bot/handlers/tasks/confirm.py``).

Зеркалит probe-before-send из ``reminder_offer.py``: ключ ставится в
Redis ДО показа кнопок, иначе кнопка-без-стейта = silent UX fail.
"""

from __future__ import annotations

import json
import logging

from app.config import get_settings

from .telegram import _delete_message, _send_message, aioredis_from_url

logger = logging.getLogger(__name__)
settings = get_settings()

# Час хватает, чтобы юзер успел нажать Да/Нет.
TASK_LIST_PENDING_TTL_SEC = 3600


def _task_list_offer_buttons(bookmark_id: str) -> dict:
    """Префиксы callback'ов (≤64 байта):
      tlc:<bid> — да, создать+закрепить список
      tlx:<bid> — нет, оставить обычной закладкой
    """
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Да", "callback_data": f"tlc:{bookmark_id}"},
                {"text": "✕ Нет", "callback_data": f"tlx:{bookmark_id}"},
            ]
        ]
    }


def _task_list_offer_text(structured_data: dict) -> str:
    tasks = structured_data.get("tasks", []) if isinstance(structured_data, dict) else []
    n = len(tasks)
    return (
        f"📋 Похоже на список задач — {n} "
        f"{'пункт' if n == 1 else 'пункта' if 2 <= n <= 4 else 'пунктов'}. "
        f"Сделать закреплённый список?\n\n"
        f"<i>Его можно отмечать галочками и редактировать ответом на сообщение.</i>"
    )


async def _maybe_offer_task_list(
    *, bookmark, chat_id: int | None, message_id: int | None, silent: bool,
) -> bool:
    """Шлём offer «Сделать список?». Возвращает True если offer показан
    (вызывающий тогда НЕ создаёт/пинит список — это сделает bot по «Да»).

    False — offer не отправлен (нет chat_id или Redis недоступен): caller
    идёт по старому пути немедленного создания (fallback, не теряем список).

    Best-effort: ошибки проглатываем, основной flow не ломаем.
    """
    if chat_id is None:
        return False

    structured = getattr(bookmark, "structured_data", None) or {}
    if not isinstance(structured, dict):
        return False

    bookmark_id = str(bookmark.id)
    text = _task_list_offer_text(structured)
    buttons = _task_list_offer_buttons(bookmark_id)

    # Источник — медиа (voice/audio/video_note)? Тогда исходное
    # сообщение бот НЕ должен удалять при подтверждении — это запись,
    # а не дубль текста списка.
    _ct = getattr(bookmark, "content_type", None)
    content_type = _ct if isinstance(_ct, str) and _ct else "text"
    is_media_src = content_type != "text"

    # Probe Redis ДО отправки — иначе кнопка без стейта.
    probe_key = f"task_list_pending_probe:{chat_id}:{bookmark_id}"
    r = None
    msg_id = None
    try:
        r = aioredis_from_url(settings.REDIS_URL)
        try:
            await r.set(probe_key, bookmark_id, ex=60)
        except Exception as e:
            logger.warning(
                f"_maybe_offer_task_list: Redis probe failed, fallback to "
                f"direct create for {bookmark.id}: {e}"
            )
            return False

        sent = await _send_message(chat_id, text, buttons)
        if not sent or not sent.get("message_id"):
            try:
                await r.delete(probe_key)
            except Exception:
                pass
            return False
        msg_id = sent["message_id"]

        try:
            await r.set(
                f"task_list_pending:{chat_id}:{msg_id}",
                json.dumps({
                    "bookmark_id": bookmark_id,
                    "src_msg_id": message_id,
                    "silent": bool(silent),
                    "is_media_src": is_media_src,
                }),
                ex=TASK_LIST_PENDING_TTL_SEC,
            )
            await r.delete(probe_key)
        except Exception as e:
            logger.warning(
                f"_maybe_offer_task_list: probe ok but final SET failed for "
                f"{bookmark.id}, deleting offer message: {e}"
            )
            try:
                await _delete_message(chat_id, msg_id)
            except Exception:
                pass
            return False
    except Exception as e:
        logger.debug(f"_maybe_offer_task_list failed for {bookmark.id}: {e}")
        return False
    finally:
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass

    logger.info(f"Task-list offer sent for {bookmark_id} (msg {msg_id})")
    return True
