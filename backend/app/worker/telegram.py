"""Low-level Telegram Bot API + Redis helpers (worker split — 0dj).

No arq entrypoint here — pure helpers used by processing/dedup/scheduled/
reminder_* sub-modules. Re-exported from ``app.worker`` for backward
compatibility (tests patch ``app.worker._send_message`` etc.).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx
import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BOT_API = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


def aioredis_from_url(url: str):
    """Тонкий wrapper — оставляет точку для monkeypatch в тестах."""
    return aioredis.from_url(url, decode_responses=True)


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


async def _send_chat_action(chat_id: int, action: str = "typing") -> None:
    """Шлёт chat action («печатает…» сверху чата). Best-effort.

    Telegram гасит индикатор через ~5с — для длинной обработки нужен повтор
    (см. typing_action). bookmark-brain-5lt продолжение: фидбэк на текст/ссылки,
    где AI идёт в воркере после выхода из бот-хендлера.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{BOT_API}/sendChatAction",
                json={"chat_id": chat_id, "action": action},
            )
    except Exception as e:
        logger.debug(f"Failed to send chat action: {e}")


@contextlib.asynccontextmanager
async def typing_action(
    chat_id: int | None, action: str = "typing", interval: float = 4.0,
):
    """Держит индикатор «печатает…» сверху чата на всё время блока.

    Шлёт chat action сразу и затем каждые ``interval`` секунд (TG гасит его
    через ~5с). Гасится автоматически на выходе (когда появляется результат —
    👍/👎). Best-effort: ошибки пульса не роняют обработку. ``chat_id=None`` —
    no-op (silent / нет чата).
    """
    if chat_id is None:
        yield
        return

    async def _pulse() -> None:
        try:
            while True:
                await _send_chat_action(chat_id, action)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — пульс не должен ронять обработку
            logger.debug(f"typing pulse failed: {e}")

    task = asyncio.create_task(_pulse())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.debug(f"typing pulse cleanup: {e}")


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
