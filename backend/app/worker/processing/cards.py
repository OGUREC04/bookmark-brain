"""Result-card & inline-keyboard builders (processing split — djtn).

Pure presentation helpers for the bookmark-processing job: result/dedup
keyboards and the rich-card markdown. No Telegram I/O, no DB — safe leaf module.
"""

from __future__ import annotations


def _result_buttons(bookmark_id: str) -> dict:
    """Inline-кнопки для результата обработки."""
    return {
        "inline_keyboard": [
            [
                {"text": "📖 Открыть", "callback_data": f"view:{bookmark_id}"},
                {"text": "🗑 Удалить", "callback_data": f"del:{bookmark_id}"},
            ],
            [
                {"text": "📋 Все закладки", "callback_data": "page:1"},
            ],
        ]
    }


def _open_old_button(old_bid: str) -> dict:
    """Inline-кнопка «📖 Открыть старую» для dedup-алерта.

    Переиспользует тот же ``view:`` callback, что и кнопки «Открыть» по
    всему боту (handler — bot.handlers.bookmark_view). Даёт открыть
    закладку-дубль в один тап, не угадывая её через /list или /search.
    """
    return {
        "inline_keyboard": [[
            {"text": "📖 Открыть старую", "callback_data": f"view:{old_bid}"},
        ]]
    }


# Длина title, после которой #-heading в rich-карточке смотрится гигантским
# (title — это предложение, а не короткое имя). Тогда — обычная жирная строка.
_RICH_TITLE_HEADING_MAX = 50


def _build_result_card_markdown(title: str, summary: str, category: str) -> str:
    """Markdown rich-карточки результата.

    Короткий title → крупный заголовок-heading «# ✅ …». Длинный (предложение
    длиннее ~50 симв) → обычная жирная строка с галкой, без гигантского H1.
    Дальше summary одной строкой и категория. Без дубля title/summary.
    """
    title = (title or "").strip()
    if len(title) > _RICH_TITLE_HEADING_MAX:
        parts = [f"✅ **{title}**"]
    else:
        parts = [f"# ✅ {title}"]
    if summary:
        parts.append(summary[:200])
    if category:
        parts.append(f"Категория: {category}")
    return "\n\n".join(parts)
