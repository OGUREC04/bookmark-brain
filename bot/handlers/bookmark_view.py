"""`view:` callback — просмотр полной закладки.

Вынесен из `bot/handlers/start.py` после code review H1 (start.py
> 800 LOC). Callback `view:` префикс отправляется кнопками из
`/list` и `/lists` (см. также bookmark_view → cb_view).

Owns its own Router; подключается в `bot/main.py`.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.common.auth import ensure_user

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data.startswith("view:"))
async def cb_view(callback: CallbackQuery, api):
    """Просмотр полной закладки."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    token = await ensure_user(callback, api)
    if not token:
        return

    try:
        bid = (callback.data or "").split(":")[1]
    except IndexError:
        await callback.answer("Неверная кнопка.", show_alert=True)
        return

    try:
        bookmark = await api.get_bookmark(token, bid)
    except Exception as e:
        logger.error(f"View failed: {e}")
        await callback.answer("Ошибка загрузки", show_alert=True)
        return

    title = bookmark.get("title") or "Без названия"
    raw_text = bookmark.get("raw_text", "")
    summary = bookmark.get("summary") or ""
    category = bookmark.get("category") or ""
    url = bookmark.get("url")
    tags = bookmark.get("tags", [])
    ai_status = bookmark.get("ai_status", "pending")

    lines = [f"<b>{title}</b>"]

    if category:
        lines.append(f"Категория: {category}")

    if tags:
        tag_str = " ".join(f"#{t['name']}" for t in tags)
        lines.append(f"Теги: {tag_str}")

    status_map = {
        "completed": "✅", "processing": "⏳", "pending": "🕐",
        "failed": "❌", "partial": "⚠️",
    }
    lines.append(f"Статус: {status_map.get(ai_status, '?')} {ai_status}")

    if summary:
        lines.append(f"\n<b>Саммари:</b>\n{summary}")

    if url:
        lines.append(
            f'\n<b>Ссылка:</b> <a href="{url}">{url[:60]}...</a>'
            if len(url) > 60
            else f'\n<b>Ссылка:</b> <a href="{url}">{url}</a>'
        )

    # Полный текст (обрезаем до 3000 символов для Telegram)
    if raw_text and raw_text != summary:
        display_text = raw_text[:3000]
        if len(raw_text) > 3000:
            display_text += "\n\n... (текст обрезан)"
        lines.append(f"\n<b>Полный текст:</b>\n{display_text}")

    text = "\n".join(lines)

    # Кнопки
    buttons = [
        [
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{bid}"),
            InlineKeyboardButton(text="◀️ К списку", callback_data="page:1"),
        ]
    ]
    if url:
        buttons.insert(0, [InlineKeyboardButton(text="🔗 Открыть ссылку", url=url)])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Telegram ограничивает edit_text до 4096 символов
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (обрезано)"

    await callback.message.edit_text(
        text, reply_markup=kb, parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()
