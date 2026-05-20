"""`/lists` command + lpage callback (router-split out of start.py).

Отдельная история списков задач — `structured_data.type=task_list`.
Был частью `bot/handlers/start.py`, вынесен в отдельный sub-router
после code review H1 (start.py перевалил 800 LOC).

Owns its own Router; aggregated в `bot/handlers/tasks/__init__.py`.
"""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router, types
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


@router.message(Command("lists"))
async def cmd_lists(message: types.Message, api):
    """Только списки задач — отдельно от обычных закладок (/list)."""
    token = await ensure_user(message, api)
    if not token:
        return
    parts = (message.text or "").split()
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    await _send_task_lists(message, api, token, page)


async def _send_task_lists(target, api, token: str, page: int = 1):
    """Список task_list'ов (structured_data.type=task_list) с прогрессом."""
    per_page = 5
    is_cb = isinstance(target, CallbackQuery)
    try:
        data = await api.get_bookmarks(
            token, page=page, per_page=per_page, structured_type="task_list",
        )
    except Exception as e:
        logger.error(f"/lists failed: {e}")
        if is_cb:
            await target.answer("Ошибка загрузки", show_alert=True)
        else:
            await target.answer("Ошибка. Попробуй позже.", parse_mode=None)
        return

    items = data.get("items", [])
    total = data.get("total", 0)

    if not items:
        text = "У тебя пока нет списков задач. Создай: /todo пункт1, пункт2"
        if is_cb:
            await target.message.edit_text(text)
        else:
            await target.answer(text, parse_mode=None)
        return

    total_pages = (total + per_page - 1) // per_page
    lines = [f"📋 <b>Списки задач</b> (стр. {page}/{total_pages}, всего {total}):\n"]
    buttons = []
    for i, b in enumerate(items, start=(page - 1) * per_page + 1):
        sd = b.get("structured_data") or {}
        tasks = sd.get("tasks", []) if isinstance(sd, dict) else []
        done = sum(1 for t in tasks if t.get("done"))
        title = b.get("title") or "Список задач"
        entry = f"{i}. <b>{title}</b> — {done}/{len(tasks)}"
        cd = sd.get("common_deadline") if isinstance(sd, dict) else None
        if cd:
            try:
                dt = datetime.fromisoformat(cd)
                entry += (
                    f"  <i>⏰ {dt.strftime('%d.%m')}</i>" if dt.hour == 0
                    else f"  <i>⏰ {dt.strftime('%d.%m %H:%M')}</i>"
                )
            except Exception:
                pass
        lines.append(entry)
        bid = b["id"]
        buttons.append([
            InlineKeyboardButton(
                text=f"📋 {title[:25]}", callback_data=f"view:{bid}",
            ),
            InlineKeyboardButton(text="🗑", callback_data=f"del:{bid}"),
        ])

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(
            text="⬅️ Назад", callback_data=f"lpage:{page - 1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(
            text="Вперёд ➡️", callback_data=f"lpage:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "\n".join(lines)
    if is_cb:
        await target.message.edit_text(
            text, reply_markup=kb, parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        await target.answer(
            text, reply_markup=kb, parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.callback_query(F.data.startswith("lpage:"))
async def cb_lists_page(callback: CallbackQuery, api):
    """Пагинация /lists."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return
    token = await ensure_user(callback, api)
    if not token:
        return
    try:
        page = int((callback.data or "").split(":")[1])
    except (IndexError, ValueError):
        page = 1
    await _send_task_lists(callback, api, token, page)
    await callback.answer()
