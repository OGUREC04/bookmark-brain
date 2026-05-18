"""`/todo` command handler (3po split). Owns its own Router."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("unpin"))
async def cmd_unpin_all(message: Message, api, store=None):
    """#5: открепить все списки задач в чате. Сами списки остаются —
    снимается только закрепление."""
    from bot.common.auth import ensure_user
    token = await ensure_user(message, api)
    if not token:
        return
    if store is None:
        await message.answer(
            "Сейчас недоступно (нет состояния). Попробуй позже.",
            parse_mode=None,
        )
        return

    chat_id = message.chat.id
    try:
        msg_ids = await store.list_task_list_message_ids(chat_id)
    except Exception as e:
        logger.warning(f"/unpin: list ids failed: {e}")
        msg_ids = []

    if not msg_ids:
        await message.answer("Списков в этом чате не нашёл.", parse_mode=None)
        return

    # unpinChatMessage идемпотентен (на незакреплённом — no-op), поэтому
    # точный счётчик «сколько было закреплено» недостоверен — не врём.
    for mid in msg_ids:
        try:
            await message.bot.unpin_chat_message(chat_id, mid)
        except TelegramBadRequest:
            pass  # не был закреплён / устарел — ок
        except Exception as e:
            logger.debug(f"/unpin: unpin {mid} failed: {e}")

    await message.answer(
        "📌 Открепил все списки. Сами списки на месте — /lists.",
        parse_mode=None,
    )


@router.message(Command("todo"))
async def cmd_todo(message: Message, api):
    """`/todo пункт1, пункт2` — принудительно создать список."""
    from bot.common.auth import ensure_user
    token = await ensure_user(message, api)
    if not token:
        return

    text = (message.text or "").split(maxsplit=1)
    if len(text) < 2 or not text[1].strip():
        await message.answer(
            "Напиши так: /todo купить молоко, позвонить маме, записаться к зубному",
            parse_mode=None,
        )
        return

    content = text[1].strip()
    raw_text = f"сделай список: {content}"

    from bot.handlers.settings import is_silent
    from bot.utils import ephemeral_error, safe_react
    silent = await is_silent(api, token, message.from_user.id)

    if silent:
        await safe_react(message, "\U0001f440")
        try:
            await api.create_bookmark(
                token=token,
                raw_text=raw_text,
                url=None,
                source="bot_command",
                source_message_id=message.message_id,
                notify_chat_id=message.chat.id,
                notify_message_id=message.message_id,
                silent=True,
            )
        except Exception as e:
            logger.error(f"/todo create failed: {e}")
            await safe_react(message, "\U0001f44e")
            await ephemeral_error(message, "Ошибка. Попробуй ещё раз.")
    else:
        status_msg = await message.answer("⏳ Обрабатываю...", parse_mode=None)
        try:
            await api.create_bookmark(
                token=token,
                raw_text=raw_text,
                url=None,
                source="bot_command",
                source_message_id=message.message_id,
                notify_chat_id=status_msg.chat.id,
                notify_message_id=status_msg.message_id,
            )
        except Exception as e:
            logger.error(f"/todo create failed: {e}")
            try:
                await status_msg.edit_text("Ошибка. Попробуй ещё раз.")
            except TelegramBadRequest:
                pass
