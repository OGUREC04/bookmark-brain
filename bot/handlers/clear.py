"""Массовые «опасные» команды с подтверждением:

  • /clearlists      — архивировать ВСЕ списки задач (обратимо)
  • /clearreminders  — отменить ВСЕ активные напоминания

Обе показывают inline-подтверждение перед выполнением (необратимое/массовое
действие — случайный вызов не должен ничего снести).
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.common.auth import ensure_user

logger = logging.getLogger(__name__)

router = Router()


def _confirm_kb(yes_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=yes_data),
        InlineKeyboardButton(text="❌ Отмена", callback_data="clr:no"),
    ]])


# ─── /clearlists ───


@router.message(Command("clearlists"))
async def cmd_clear_lists(message: Message, api):
    """Архивировать все списки задач (с подтверждением)."""
    token = await ensure_user(message, api)
    if not token:
        return

    try:
        data = await api.get_bookmarks(
            token, per_page=1, structured_type="task_list", is_archived=False,
        )
        total = data.get("total", 0)
    except Exception as e:
        logger.error(f"/clearlists count failed: {e}")
        await message.answer("Не получилось проверить списки. Попробуй позже.", parse_mode=None)
        return

    if total == 0:
        await message.answer("Активных списков нет — нечего архивировать.", parse_mode=None)
        return

    await message.answer(
        f"Архивировать все списки задач ({total})?\n"
        f"Они исчезнут из /lists, но сохранятся в базе (обратимо).",
        reply_markup=_confirm_kb("clrlists:yes"),
        parse_mode=None,
    )


@router.callback_query(F.data == "clrlists:yes")
async def cb_clear_lists_confirm(callback: CallbackQuery, api):
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return
    token = await ensure_user(callback, api)
    if not token:
        return
    try:
        result = await api.archive_all_task_lists(token)
        n = result.get("archived", 0)
    except Exception as e:
        logger.error(f"/clearlists archive failed: {e}")
        await callback.message.edit_text("Ошибка при архивировании. Попробуй ещё раз.")
        await callback.answer()
        return
    await callback.message.edit_text(f"📦 Архивировал списков: {n}.")
    await callback.answer()


# ─── /clearreminders ───


@router.message(Command("clearreminders"))
async def cmd_clear_reminders(message: Message, api):
    """Отменить все активные напоминания (с подтверждением)."""
    token = await ensure_user(message, api)
    if not token:
        return

    try:
        data = await api.list_upcoming_reminders(token)
        total = data.get("total", 0)
    except Exception as e:
        logger.error(f"/clearreminders count failed: {e}")
        await message.answer("Не получилось проверить напоминания. Попробуй позже.", parse_mode=None)
        return

    if total == 0:
        await message.answer("Активных напоминаний нет.", parse_mode=None)
        return

    await message.answer(
        f"Отменить все активные напоминания ({total})?\n"
        f"История выполненных/отменённых не тронется.",
        reply_markup=_confirm_kb("clrrem:yes"),
        parse_mode=None,
    )


@router.callback_query(F.data == "clrrem:yes")
async def cb_clear_reminders_confirm(callback: CallbackQuery, api):
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return
    token = await ensure_user(callback, api)
    if not token:
        return
    try:
        result = await api.cancel_all_reminders(token)
        n = result.get("cancelled", 0)
    except Exception as e:
        logger.error(f"/clearreminders cancel failed: {e}")
        await callback.message.edit_text("Ошибка при отмене. Попробуй ещё раз.")
        await callback.answer()
        return
    await callback.message.edit_text(f"🔕 Отменил напоминаний: {n}.")
    await callback.answer()


# ─── общая отмена ───


@router.callback_query(F.data == "clr:no")
async def cb_clear_cancel(callback: CallbackQuery):
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Отменил, ничего не трогаю.")
    await callback.answer()
