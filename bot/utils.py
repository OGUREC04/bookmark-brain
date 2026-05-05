"""Утилиты для Telegram бота — реакции, ephemeral-сообщения."""

import asyncio
import logging

from aiogram.types import Message, ReactionTypeEmoji

logger = logging.getLogger(__name__)


async def safe_react(message: Message, emoji: str) -> bool:
    """Best-effort реакция на сообщение. Не ломает основной flow при ошибке.

    Returns True если реакция поставлена, False если нет (старый клиент, группа и т.д.).
    """
    try:
        await message.react([ReactionTypeEmoji(emoji=emoji)])
        return True
    except Exception as e:
        logger.debug(
            "Reaction failed (chat=%s, msg=%s): %s",
            message.chat.id, message.message_id, e,
        )
        return False


async def safe_remove_reaction(message: Message) -> None:
    """Убирает все реакции бота с сообщения."""
    try:
        await message.react([])
    except Exception as e:
        logger.debug(
            "Remove reaction failed (chat=%s, msg=%s): %s",
            message.chat.id, message.message_id, e,
        )


async def _delete_after(msg: Message, delay: float = 10) -> None:
    """Удаляет сообщение после задержки (best-effort)."""
    try:
        await asyncio.sleep(delay)
        await msg.delete()
    except Exception as e:
        logger.debug("Auto-delete failed (msg=%s): %s", msg.message_id, e)


async def ephemeral_error(
    message: Message, text: str, delay: float = 10,
) -> None:
    """Отправляет сообщение об ошибке, которое автоудалится через delay секунд."""
    try:
        error_msg = await message.reply(text, parse_mode=None)
        asyncio.create_task(_delete_after(error_msg, delay))
    except Exception as e:
        logger.debug("ephemeral_error failed: %s", e)
