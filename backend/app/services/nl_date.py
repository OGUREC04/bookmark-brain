"""NL parser для времени напоминаний.

Тонкая обёртка над `dateparser` + edge-case handling по PRD Phase 2.5.

API:
    result = parse("завтра в 9", user_tz="Europe/Moscow", now=...)
    if result.status == ParseStatus.OK:
        save_reminder(result.dt)
    elif result.status == ParseStatus.NEEDS_TIME:
        ask_user("укажи время — например, в субботу в 9")
    elif result.status == ParseStatus.IN_PAST:
        ask_user("время в прошлом, ты про будущее?")
    elif result.status == ParseStatus.FALLBACK_DEFAULT:
        # юзер написал «не знаю / потом» — поставили +24ч
        save_reminder(result.dt)
    elif result.status == ParseStatus.UNPARSEABLE:
        ask_user("не разобрал, попробуй: завтра в 9, через час, 15 мая в 18:00")

Возвращает:
    ParseResult(dt: datetime | None, status: ParseStatus)
    dt — всегда UTC-aware datetime (или None если не получилось)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

import dateparser


class ParseStatus(str, Enum):
    OK = "ok"
    UNPARSEABLE = "unparseable"
    IN_PAST = "in_past"
    NEEDS_TIME = "needs_time"
    FALLBACK_DEFAULT = "fallback_default"


@dataclass(frozen=True)
class ParseResult:
    dt: Optional[datetime]
    status: ParseStatus


# Размытые ответы — ставим дефолт +24ч
_FALLBACK_PATTERNS: tuple[str, ...] = (
    "не знаю",
    "хз",
    "потом",
    "позже",
    "как-нибудь",
    "когда-нибудь",
    "ок",
    "окей",
    "ладно",
    "давай",
)
_FALLBACK_DEFAULT_HOURS = 24

# Маркеры что в тексте есть указание времени (часов/минут).
# Если их нет, а парсер вернул datetime с time=00:00 — это «дата без времени» → NEEDS_TIME.
_TIME_HINT_RE = re.compile(
    r"(?:"
    r"\b\d{1,2}[:.]\d{2}"            # 18:00, 9.30
    r"|\bв\s+\d{1,2}\s*(?:часов|часа|час|ч)?\b"   # «в 9», «в 18 часов»
    r"|\b\d{1,2}\s*(?:часов|часа|час)\b"          # «9 часов»
    r"|\bв\s+\d{1,2}-?\d{0,2}\b"     # «в 18-30»
    r"|\bпол(?:овина|овины)?\s+\w+\b"            # «полвторого» — редко
    r"|\bутр(?:а|ом)?\b|\bвечер(?:а|ом)?\b|\bдн(?:я|ём)\b|\bноч(?:и|ью)\b"
    r")",
    re.IGNORECASE,
)

# Маркеры интервала («через N часов/минут») — там время суток не нужно
_INTERVAL_HINT_RE = re.compile(
    r"\bчерез\s+\d*\s*(?:часов|часа|час|минут|минуту|мин|секунд)\b",
    re.IGNORECASE,
)


def parse(
    text: str,
    user_tz: str = "Europe/Moscow",
    now: datetime | None = None,
) -> ParseResult:
    """Парсит NL-описание времени в UTC datetime.

    Args:
        text: пользовательский ввод («завтра в 9», «через час», «не знаю»)
        user_tz: IANA timezone юзера (валидируется через ZoneInfo)
        now: текущее время для тестов. Если None — `datetime.now(UTC)`.

    Returns:
        ParseResult с status и опциональным dt (UTC-aware).

    Raises:
        ZoneInfoNotFoundError / ValueError: при невалидном timezone.
    """
    # Валидация timezone (бросит исключение если невалидный)
    user_zone = ZoneInfo(user_tz)

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    text_normalized = text.strip().lower()

    # Пустота / совсем не текст
    if not text_normalized or len(text_normalized) < 2:
        return ParseResult(dt=None, status=ParseStatus.UNPARSEABLE)

    # Размытое — fallback default
    if any(phrase == text_normalized or phrase in text_normalized for phrase in _FALLBACK_PATTERNS):
        # «через час» содержит «час» — но не fallback. Проверим что нет dateparser-парсимого.
        # Простой тест: «не знаю» / «потом» — это fallback, «через час» — нет.
        # Делаем строже: точное совпадение или короткое включение.
        if _is_fallback_phrase(text_normalized):
            return ParseResult(
                dt=now + timedelta(hours=_FALLBACK_DEFAULT_HOURS),
                status=ParseStatus.FALLBACK_DEFAULT,
            )

    # Базовое время для dateparser — в timezone юзера
    now_in_user_tz = now.astimezone(user_zone)

    # «сегодня» в тексте → не использовать PREFER_DATES_FROM=future
    # (иначе «сегодня в 8» когда сейчас 12 переносится на завтра, а должно быть IN_PAST)
    has_today_marker = bool(re.search(r"\bсегодня\b", text_normalized))

    # Препроцессинг: «в 9» → «в 9:00» (dateparser не парсит часы без минут)
    text_for_parser = _preprocess_short_time(text_normalized)

    settings: dict = {
        "RELATIVE_BASE": now_in_user_tz.replace(tzinfo=None),  # naive в user_tz
    }
    if not has_today_marker:
        settings["PREFER_DATES_FROM"] = "future"

    parsed = dateparser.parse(
        text_for_parser,
        languages=["ru", "en"],
        settings=settings,
    )

    if parsed is None:
        return ParseResult(dt=None, status=ParseStatus.UNPARSEABLE)

    # dateparser вернул naive — это время в user_tz. Конвертируем в UTC.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=user_zone).astimezone(timezone.utc)
    else:
        # Если уже tz-aware, просто нормализуем в UTC
        parsed = parsed.astimezone(timezone.utc)

    # Защита от прошлого: если получилось < now (с допуском 30 сек на парсинг)
    if parsed < now - timedelta(seconds=30):
        return ParseResult(dt=None, status=ParseStatus.IN_PAST)

    # Проверка «есть ли в тексте указание времени»
    has_time_in_text = bool(_TIME_HINT_RE.search(text_normalized))
    has_interval = bool(_INTERVAL_HINT_RE.search(text_normalized))

    # Если нет указания времени и нет интервала, и время вышло «00:00» в user_tz —
    # это дата без времени → NEEDS_TIME
    if not has_time_in_text and not has_interval:
        parsed_in_user_tz = parsed.astimezone(user_zone)
        # «завтра» / «в субботу» / «15 мая» dateparser обычно возвращает с time=00:00
        if parsed_in_user_tz.hour == 0 and parsed_in_user_tz.minute == 0:
            return ParseResult(dt=None, status=ParseStatus.NEEDS_TIME)

    return ParseResult(dt=parsed, status=ParseStatus.OK)


def _preprocess_short_time(text: str) -> str:
    """«в 9» → «в 9:00», «в 18» → «в 18:00», «at 9» → «at 9:00».

    Без этого dateparser игнорирует короткое указание часа без минут.
    Не трогает «в 9:00», «в 18-30», «через 9 часов», числа > 23.
    """
    # «в N» / «at N» где N=0..23 и НЕ followed by :, ., -, час/часов
    def repl(m: re.Match) -> str:
        prefix, hour_str = m.group(1), m.group(2)
        try:
            hour = int(hour_str)
        except ValueError:
            return m.group(0)
        if 0 <= hour <= 23:
            return f"{prefix} {hour}:00"
        return m.group(0)

    pattern = re.compile(
        r"(\bв|\bat)\s+(\d{1,2})\b(?![:.\-]|\s*(?:час|hour|hr|h\b))",
        re.IGNORECASE,
    )
    return pattern.sub(repl, text)


def _is_fallback_phrase(text: str) -> bool:
    """Точная проверка — это fallback фраза или нет.

    `text` уже lowercase + stripped.
    """
    # Точное совпадение
    if text in _FALLBACK_PATTERNS:
        return True
    # Короткие фразы (≤ 15 символов) и содержат fallback-маркер
    if len(text) <= 15:
        return any(phrase in text for phrase in _FALLBACK_PATTERNS)
    return False
