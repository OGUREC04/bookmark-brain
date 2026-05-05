"""/clean — удалить все сообщения бота из чата.

Хранилище (Redis bot_msgs:{chat_id}) ведётся через state_store.
По умолчанию пропускаем «защищённый» контент — task_list (по ключам
task_list_msg:*) и закреплённые сообщения. В silent mode списки могут
быть не закреплены, но всё равно tracked как task_list — их тоже не трогаем.

/clean all — удалить в том числе task_list и закреплённые.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("clean"))
async def cmd_clean(message: Message, store=None, command: CommandObject = None):
    include_pinned = False
    if command and command.args and command.args.strip().lower() in {"all", "всё", "все"}:
        include_pinned = True

    # Само /clean — удаляем немедленно, чтобы не мусорил
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    if store is None:
        sent = await message.answer("Хранилище недоступно.", parse_mode=None)
        asyncio.create_task(_delete_after(sent, 6))
        return

    chat_id = message.chat.id
    ids = await store.list_bot_messages(chat_id, exclude_protected=not include_pinned)

    if not ids:
        sent = await message.answer("Нечего удалять 🙂", parse_mode=None)
        asyncio.create_task(_delete_after(sent, 4))
        return

    deleted = 0
    for mid in ids:
        try:
            await message.bot.delete_message(chat_id, mid)
            await store.forget_bot_message(chat_id, mid)
            if include_pinned:
                await store.unbind_list_message(chat_id, mid)
            deleted += 1
        except TelegramBadRequest:
            # Сообщение старше 48ч или уже удалено — просто забываем
            await store.forget_bot_message(chat_id, mid)
            if include_pinned:
                await store.unbind_list_message(chat_id, mid)
        except Exception as e:
            logger.debug(f"clean: failed to delete {mid}: {e}")

    sent = await message.answer(
        f"Удалил {deleted} сообщ." + (" (включая закреплённые)" if include_pinned else ""),
        parse_mode=None,
    )
    asyncio.create_task(_delete_after(sent, 5))


async def _delete_after(msg: Message, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass
