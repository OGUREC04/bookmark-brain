"""Форматирование транскриптов голосовых сообщений для отправки в Telegram.

Длинные транскрипты оборачиваются в expandable blockquote (Bot API 7.x),
чтобы не засорять чат стеной текста. Короткие — отправляются как plain-текст.
"""
from __future__ import annotations

import re

from bot.common.text import safe

# Порог длины: транскрипт считается «длинным» если превышает этот лимит
LONG_TRANSCRIPT_CHARS = 600

# Минимальное количество таймкодов [MM:SS], при котором текст считается
# «навигационным» и оборачивается даже если короче порога по символам
_MIN_TIMECODES_FOR_WRAP = 2

_TIMECODE_RE = re.compile(r"\[\d{2}:\d{2}\]")


def _is_long(text: str) -> bool:
    """Проверяет, нужно ли оборачивать текст в expandable blockquote.

    Условия (любое из них):
    1. Длина превышает LONG_TRANSCRIPT_CHARS символов.
    2. Текст содержит несколько таймкодов [MM:SS] — признак навигационного
       транскрипта длинного голосового сообщения.
    """
    if len(text) > LONG_TRANSCRIPT_CHARS:
        return True
    if len(_TIMECODE_RE.findall(text)) >= _MIN_TIMECODES_FOR_WRAP:
        return True
    return False


def wrap_expandable(text: str) -> tuple[str, str | None]:
    """Обернуть транскрипт в expandable blockquote если он длинный.

    Args:
        text: Текст транскрипта (с таймкодами или без).

    Returns:
        Кортеж (готовый_текст, parse_mode):
        - Длинный: ("<blockquote expandable>...escaped...</blockquote>", "HTML")
        - Короткий: (text, None) — без изменений, отправляется plain.
    """
    if not _is_long(text):
        return (text, None)

    escaped = safe(text)
    html = f"<blockquote expandable>{escaped}</blockquote>"
    return (html, "HTML")
