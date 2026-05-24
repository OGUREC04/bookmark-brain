"""Просмотр закладок: /list, пагинация, удаление."""
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


@router.message(Command("list"))
async def cmd_list(message: types.Message, api):
    """Просмотр закладок с inline-кнопками."""
    token = await ensure_user(message, api)
    if not token:
        return

    parts = message.text.split()
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    await _send_list(message, api, token, page)


async def _send_list(target, api, token: str, page: int = 1):
    """Отправляет список закладок. target — Message или CallbackQuery."""
    per_page = 5

    try:
        data = await api.get_bookmarks(token, page=page, per_page=per_page)
    except Exception as e:
        logger.error(f"List failed: {e}")
        if isinstance(target, CallbackQuery):
            await target.answer("Ошибка загрузки", show_alert=True)
        else:
            await target.answer("Ошибка. Попробуй позже.", parse_mode=None)
        return

    items = data.get("items", [])
    total = data.get("total", 0)

    if not items:
        text = "У тебя пока нет сохранённых закладок."
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text)
        else:
            await target.answer(text, parse_mode=None)
        return

    total_pages = (total + per_page - 1) // per_page
    lines = [f"<b>Закладки</b> (стр. {page}/{total_pages}, всего {total}):\n"]

    for i, b in enumerate(items, start=(page - 1) * per_page + 1):
        title = b.get("title") or "Без названия"
        summary = b.get("summary") or b["raw_text"][:80]
        tags = b.get("tags", [])
        created = b.get("created_at", "")

        # Форматируем дату
        date_str = ""
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                date_str = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                date_str = ""

        entry = f"{i}. <b>{title}</b>"
        if date_str:
            entry += f"  <i>({date_str})</i>"
        entry += f"\n{summary}"
        if tags:
            tag_str = " ".join(f"#{t['name']}" for t in tags[:4])
            entry += f"\n{tag_str}"

        lines.append(entry)

    text = "\n\n".join(lines)

    # Inline-кнопки для каждой закладки
    buttons = []
    for b in items:
        bid = b["id"]
        title_short = (b.get("title") or "Без названия")[:25]
        buttons.append([
            InlineKeyboardButton(text=f"📖 {title_short}", callback_data=f"view:{bid}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del:{bid}"),
        ])

    # Навигация
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page:{page - 1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)


# ── #6: /lists вынесён в bot/handlers/tasks/lists.py (router-split,
#       code review H1). cmd_lists + _send_task_lists + cb_lists_page
#       живут там, подключены через `tasks.router`.
# cb_view вынесен в bot/handlers/bookmark_view.py (router-split, H1).


@router.callback_query(F.data.startswith("page:"))
async def cb_page(callback: CallbackQuery, api):
    """Пагинация списка."""
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
    await _send_list(callback, api, token, page)
    await callback.answer()


@router.callback_query(F.data.startswith("del:"))
async def cb_delete_confirm(callback: CallbackQuery, api):
    """Запрос подтверждения удаления."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    bid = callback.data.split(":")[1]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_del:{bid}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="page:1"),
        ]
    ])

    await callback.message.edit_text("Удалить эту закладку?", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_del:"))
async def cb_delete_execute(callback: CallbackQuery, api):
    """Удаление закладки после подтверждения."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    token = await ensure_user(callback, api)
    if not token:
        return

    bid = callback.data.split(":")[1]

    try:
        await api.delete_bookmark(token, bid)
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        await callback.answer("Ошибка удаления", show_alert=True)
        return

    await callback.answer("Удалено!")
    # Возвращаемся к списку
    await _send_list(callback, api, token, page=1)
