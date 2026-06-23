"""Парсер регулярных напоминаний (/repeat). MVP — только ежедневно.

Вход — сырой хвост команды: «полить цветы каждый день в 10:00».
Выход — RecurrenceParse: при успехе (text, rule='daily', hour, minute),
иначе ok=False + код ошибки (NO_SCHEDULE / NO_TIME / NO_TEXT / BAD_TIME),
по которому API/бот выберут понятное сообщение пользователю.

ЭТО НЕ NL-детект регулярности: парсер вызывается ТОЛЬКО из явной команды
/repeat. Свободный текст («поливаю цветы каждый день») сюда не попадает.

Расписание ожидается в конце фразы; берём ПОСЛЕДНИЙ time-токен (если в тексте
есть свой «в 7» — расписание «в 8» в хвосте важнее). Время без префикса «в»
ловим только в форме HH:MM (двоеточие), чтобы случайное число в тексте
(«купить 2 билета») не приняли за время.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# «каждый день» / «ежедневно» (с любыми окончаниями).
_DAILY_RE = re.compile(r"(?:кажд\w+\s+день|ежедневн\w+)", re.IGNORECASE)

# «в 10», «в 10:00», «в 9.30», «в 6 вечера» — время с предлогом «в».
_TIME_PREP_RE = re.compile(
    r"\bв\s+(\d{1,2})(?:[:.](\d{2}))?\s*(утр\w*|вечер\w*|дн\w*|ноч\w*)?",
    re.IGNORECASE,
)
# «10:00» / «9.30» без предлога — требуем разделитель, чтобы не ловить голое число.
_TIME_COLON_RE = re.compile(r"\b(\d{1,2})[:.](\d{2})\b")


@dataclass(frozen=True)
class RecurrenceParse:
    ok: bool
    error: str | None = None  # NO_SCHEDULE | NO_TIME | NO_TEXT | BAD_TIME
    text: str = ""
    rule: str = "daily"
    hour: int = 0
    minute: int = 0


def _apply_meridiem(hour: int, meridiem: str | None) -> int:
    """Нормализуем час по части суток. MVP-упрощения задокументированы в PRD:
    «ночи» (кроме 12→0) и «утра» оставляем как есть, «дня»/«вечера» +12 для <12.
    """
    if not meridiem:
        return hour
    m = meridiem.lower()
    if m.startswith("утр"):
        return 0 if hour == 12 else hour
    if m.startswith("дн"):
        return hour + 12 if hour < 12 else hour
    if m.startswith("вечер"):
        return hour + 12 if hour < 12 else hour
    if m.startswith("ноч"):
        return 0 if hour == 12 else hour
    return hour


def parse_recurrence(raw: str) -> RecurrenceParse:
    s = (raw or "").strip()
    if not s:
        return RecurrenceParse(ok=False, error="NO_TEXT")

    daily = _DAILY_RE.search(s)
    if not daily:
        return RecurrenceParse(ok=False, error="NO_SCHEDULE")

    meridiem: str | None = None
    preps = list(_TIME_PREP_RE.finditer(s))
    if preps:
        tmatch = preps[-1]  # расписание обычно в конце
        hour = int(tmatch.group(1))
        minute = int(tmatch.group(2) or 0)
        meridiem = tmatch.group(3)
    else:
        colons = list(_TIME_COLON_RE.finditer(s))
        if not colons:
            return RecurrenceParse(ok=False, error="NO_TIME")
        tmatch = colons[-1]
        hour = int(tmatch.group(1))
        minute = int(tmatch.group(2))

    hour = _apply_meridiem(hour, meridiem)
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        return RecurrenceParse(ok=False, error="BAD_TIME")

    # text = строка без фразы расписания и без time-токена.
    # Вырезаем span'ы с конца, чтобы индексы не съезжали.
    spans = sorted([daily.span(), tmatch.span()], key=lambda sp: sp[0], reverse=True)
    text = s
    for a, b in spans:
        text = text[:a] + " " + text[b:]
    text = re.sub(r"\s+", " ", text).strip(" ,.;:—-")
    # Висячий одиночный предлог «в» в конце/начале — убрать.
    text = re.sub(r"(?:^|\s)в\s*$", "", text, flags=re.IGNORECASE).strip(" ,.;:—-")
    if not text:
        return RecurrenceParse(ok=False, error="NO_TEXT")

    return RecurrenceParse(ok=True, text=text, rule="daily", hour=hour, minute=minute)
