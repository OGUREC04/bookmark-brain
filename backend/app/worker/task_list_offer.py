"""Task-list confirmation offer — «Сделать список?» до создания+пина.

No arq entrypoint. Used by ``processing.py``: вместо немедленного
создания+пина task_list бот спрашивает подтверждение (как reminder-offer).
Только после «Да» список рендерится, биндится и пинится (bot-side
``bot/handlers/tasks/confirm.py``).

Зеркалит probe-before-send из ``reminder_offer.py``: ключ ставится в
Redis ДО показа кнопок, иначе кнопка-без-стейта = silent UX fail.
"""

from __future__ import annotations

import html
import json
import logging

from app.config import get_settings
from shared.messages import compose, reply_hint_compact

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


_MAX_OFFER_ITEMS = 8
_MAX_OFFER_ITEM_LEN = 80


def _offer_items_block(tasks: list) -> str:
    """Превью пунктов для оффера: HTML-escaped, обрезка по длине, кап по числу."""
    texts = [
        (t.get("text") or "").strip()
        for t in tasks
        if isinstance(t, dict) and (t.get("text") or "").strip()
    ]
    if not texts:
        return ""
    lines = []
    for tx in texts[:_MAX_OFFER_ITEMS]:
        if len(tx) > _MAX_OFFER_ITEM_LEN:
            # h3j2: показываем ровно _MAX_OFFER_ITEM_LEN значимых символов + «…».
            # Раньше «- 1» → 79: пункт ровно 80 символов выводился целиком, а 81 —
            # обрезался до 79 (скачок назад). Канон: len > лимита → лимит + «…».
            tx = tx[:_MAX_OFFER_ITEM_LEN].rstrip() + "…"
        lines.append(f"• {html.escape(tx)}")
    if len(texts) > _MAX_OFFER_ITEMS:
        lines.append(f"…и ещё {len(texts) - _MAX_OFFER_ITEMS}")
    return "\n".join(lines)


def _task_list_offer_text(structured_data: dict) -> str:
    """Текст оффера в КАНОН-порядке: reply-подсказка → заголовок → пункты → вопрос."""
    tasks = structured_data.get("tasks", []) if isinstance(structured_data, dict) else []
    n = len(tasks)
    word = "пункт" if n == 1 else "пункта" if 2 <= n <= 4 else "пунктов"
    items_block = _offer_items_block(tasks)
    heading = f"📋 <b>Похоже на список — {n} {word}</b>"
    body = items_block + "\n\nСделать закреплённый список?" if items_block else "Сделать закреплённый список?"
    return compose(
        reply_hint_compact("отмечать и редактировать список"),
        heading,
        body,
    )


async def _maybe_offer_task_list(
    *, bookmark, chat_id: int | None, message_id: int | None, silent: bool,
    similar: dict | None = None, general_dup: dict | None = None,
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

    # similar — для post-confirm dedup-alert (bot tlc отправит alert
    # после создания списка). Serializable форма для Redis JSON.
    sim_pl: dict | None = None
    if similar:
        created = similar.get("created_at")
        sim_pl = {
            "id": str(similar.get("id", "")),
            "title": similar.get("title"),
            "done_count": int(similar.get("done_count", 0) or 0),
            "total_count": int(similar.get("total_count", 0) or 0),
            "structured_data": similar.get("structured_data"),  # состав старого списка для merge-диффа
            "created_at": (
                created.isoformat() if hasattr(created, "isoformat") else created
            ),
        }

    # general_dup — для отложенного near-dup при «Нет» (bot tlx).
    gen_pl: dict | None = None
    if general_dup:
        gc = general_dup.get("created_at")
        gen_pl = {
            "id": str(general_dup.get("id", "")),
            "title": general_dup.get("title") or "Без названия",
            "is_task_list": bool(general_dup.get("is_task_list")),
            "similarity": float(general_dup.get("similarity") or 0.0),
            "summary": general_dup.get("summary"),  # состав заметки в алерте
            "structured_data": general_dup.get("structured_data"),  # состав списка
            "created_at": (
                gc.isoformat() if hasattr(gc, "isoformat") else gc
            ),
        }

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
                    "similar": sim_pl,
                    "general_dup": gen_pl,
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
