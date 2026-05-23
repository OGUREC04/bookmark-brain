"""NL parser для времени напоминаний.

⚠️ COPY of backend/app/services/nl_date.py (см. bookmark-brain-4dr).
Bot Docker-контейнер не имеет доступа к backend/ — мы шипим bot/ отдельно.
Поддерживать синхронность с backend-версией вручную при правках.

Тонкая обёртка над `dateparser` + edge-case handling по PRD Phase 2.5.

API:
    result = parse("завтра в 9", user_tz="Europe/Moscow", now=...)
    if result.status == ParseStatus.OK:
        save_reminder(result.dt)
    elif result.status == ParseStatus.NEEDS_HOUR:
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
from zoneinfo import ZoneInfo

import dateparser


class ParseStatus(str, Enum):
    OK = "ok"
    UNPARSEABLE = "unparseable"
    IN_PAST = "in_past"
    # NEEDS_HOUR — есть дата, но не указан час и часть суток.
    # Хендлер должен спросить юзера через Reply («во сколько напомнить?»).
    # Phase 2.6: ранее называлось NEEDS_TIME — переименовано для ясности.
    NEEDS_HOUR = "needs_hour"
    NEEDS_TIME = "needs_hour"  # backward-compat alias (same value → enum alias)
    FALLBACK_DEFAULT = "fallback_default"


@dataclass(frozen=True)
class ParseResult:
    dt: datetime | None
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

# Маркеры интервала («через N часов / дней / недель») — там время суток не нужно
_INTERVAL_HINT_RE = re.compile(
    r"\bчерез\s+\d*\s*(?:часов|часа|час|минут|минуту|мин|секунд|"
    r"дней|дня|день|сутки|недель|недели|неделю|месяцев|месяца|месяц)\b",
    re.IGNORECASE,
)

# Точное совпадение всей фразы (с опц. пунктуацией) с fallback-маркером.
# Чтобы «в 9 ок» не классифицировалось как fallback.
_FALLBACK_PATTERNS_FULL_RE: re.Pattern | None = None  # лениво строится

# rby: явный маркер дня в тексте. Если есть — НЕ перекатываем «в прошлом»
# на завтра (юзер сам указал день: «15 мая» в прошлом = реально прошлое).
_DAY_MARKER_RE = re.compile(
    r"\b(?:сегодня|завтра|послезавтра|вчера"
    r"|понедельник\w*|вторник\w*|сред[ауы]\w*|четверг\w*|пятниц\w*"
    r"|суббот\w*|воскресень\w*"
    r"|\d{1,2}[.\/]\d{1,2}"
    r"|\d+\s*(?:дн|недел|месяц)"
    r"|январ|феврал|март|апрел|\bма[йя]\b|июн|июл|август|сентябр"
    r"|октябр|ноябр|декабр)",
    re.IGNORECASE,
)
# Только часть суток / голое время без дня («вечером», «18:00»,
# «час ночи», «5 вечера»).
_BARE_TIME_RE = re.compile(
    r"\b(?:утром|утра|дн[её]м|днем|вечером|вечера|ночью|ночи|дня)\b",
    re.IGNORECASE,
)

# #7b: словесные часы с уточнением суток — «час ночи»=01:00,
# «два часа дня»=14:00, «в 5 вечера»=17:00, «9 утра»=09:00.
_HOUR_WORDS = {
    "час": 1, "одна": 1, "один": 1, "два": 2, "две": 2, "три": 3,
    "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
    "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12,
}
_CLOCK_WORD_RE = re.compile(
    r"(?:\bв\s+)?\b("
    r"\d{1,2}|час|одна|один|два|две|три|четыре|пять|шесть|семь|"
    r"восемь|девять|десять|одиннадцать|двенадцать"
    r")\s*(?:час(?:а|ов)?)?\s+(ночи|утра|дня|вечера)\b",
    re.IGNORECASE,
)


def _clock_word_to_24(num_token: str, qual: str) -> int | None:
    """(«два», «дня») → 14. None если час вне 0..12."""
    nt = num_token.lower()
    h = int(nt) if nt.isdigit() else _HOUR_WORDS.get(nt)
    if h is None or h < 0 or h > 12:
        return None
    q = qual.lower()
    if q == "ночи":
        return 0 if h == 12 else h          # «час ночи»=1, «12 ночи»=0
    if q == "утра":
        return 0 if h == 12 else h          # «12 утра»=0, «9 утра»=9
    if q == "дня":
        return 12 if h == 12 else (h + 12 if h < 12 else h)  # «час дня»=13
    # вечера
    return h + 12 if h < 12 else h          # «6 вечера»=18, «12 вечера»=12


def _normalize_clock_words(text: str) -> str:
    """«в час ночи» → «01:00», «два часа дня» → «14:00». Делается ДО
    остального препроцессинга, чтобы дальше шла чистая «HH:00»-строка.
    """
    def _repl(m: re.Match) -> str:
        hh = _clock_word_to_24(m.group(1), m.group(2))
        return m.group(0) if hh is None else f"{hh:02d}:00"
    return _CLOCK_WORD_RE.sub(_repl, text)


def _is_bare_time_of_day(text_normalized: str) -> bool:
    """True если в тексте только время/часть суток и НЕТ явного дня.

    Тогда «в прошлом» = юзер имел в виду ближайшее будущее (rby):
    «вечером» в 20:00 → завтра 18:00, «в 9» в 10:00 → завтра 9:00.
    """
    t = text_normalized.strip()
    if _DAY_MARKER_RE.search(t):
        return False
    return bool(
        _BARE_TIME_RE.search(t)
        or re.fullmatch(r"(?:в\s+)?\d{1,2}[:.]\d{2}", t)
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

    # Размытое — fallback default. Точное совпадение всей фразы (с опц. пунктуацией),
    # чтобы «в 9 ок» НЕ классифицировалось как fallback.
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

    # Есть ли в тексте указание времени / интервала. Считаем ДО парсинга —
    # нужно чтобы решить, обнулять ли время базы (см. ниже).
    has_time_in_text = bool(_TIME_HINT_RE.search(text_normalized))
    has_interval = bool(_INTERVAL_HINT_RE.search(text_normalized))

    # «Голая дата» без времени/интервала («завтра», «в субботу», «15 мая»):
    # обнуляем время базы. Иначе dateparser для ОТНОСИТЕЛЬНЫХ слов («завтра»)
    # наследует текущий час (завтра в это же время) → NEEDS_HOUR не срабатывает
    # и бот молча ставит напоминание на «сейчас завтра». «сегодня» не трогаем
    # (midnight → ушло бы в IN_PAST вместо вопроса о часе).
    base = now_in_user_tz
    if not has_today_marker and not has_time_in_text and not has_interval:
        base = now_in_user_tz.replace(hour=0, minute=0, second=0, microsecond=0)

    # БАГ-фикс: ранее RELATIVE_BASE передавался naive (через .replace(tzinfo=None)).
    # Dateparser трактует naive base как UTC → «завтра» в локальном 01:08 даёт
    # неверный день (UTC 22:08 → «завтра» = тот же local day).
    # Передаём tz-aware RELATIVE_BASE + явный TIMEZONE чтобы parsing шёл в user_tz.
    settings: dict = {
        "RELATIVE_BASE": base,  # tz-aware в user_tz (время обнулено для голой даты)
        "TIMEZONE": user_tz,
        "RETURN_AS_TIMEZONE_AWARE": True,
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
        # rby: голое время / часть суток без явного дня. _preprocess
        # синтетически привязал к «сегодня», has_today_marker=False.
        # Раз время уже прошло — юзер имел в виду ближайшее будущее →
        # перекатываем на следующий день.
        if not has_today_marker and _is_bare_time_of_day(text_normalized):
            rolled = parsed + timedelta(days=1)
            if rolled >= now - timedelta(seconds=30):
                parsed = rolled
            else:
                return ParseResult(dt=None, status=ParseStatus.IN_PAST)
        else:
            return ParseResult(dt=None, status=ParseStatus.IN_PAST)

    # Если нет указания времени и нет интервала, и время вышло «00:00» в user_tz —
    # это дата без времени → NEEDS_TIME (has_time_in_text/has_interval уже посчитаны выше)
    if not has_time_in_text and not has_interval:
        parsed_in_user_tz = parsed.astimezone(user_zone)
        # «завтра» / «в субботу» / «15 мая» dateparser обычно возвращает с time=00:00
        if parsed_in_user_tz.hour == 0 and parsed_in_user_tz.minute == 0:
            return ParseResult(dt=None, status=ParseStatus.NEEDS_HOUR)

    return ParseResult(dt=parsed, status=ParseStatus.OK)


def _preprocess_short_time(text: str) -> str:
    """«в 9» → «в 9:00», «в 18» → «в 18:00», «at 9» → «at 9:00».

    Также маппит словесные части суток (T15):
      «утром» → «9:00», «днём/днем» → «14:00»,
      «вечером» → «18:00», «ночью» → «22:00»

    Без этого dateparser игнорирует короткое указание часа без минут
    и не понимает части суток («завтра утром», «в субботу вечером»).

    Не трогает «в 9:00», «в 18-30», «через 9 часов», числа > 23.
    """
    # 0. Словесные часы с уточнением суток («час ночи», «5 вечера»,
    #    «9 утра») → «HH:00». ДО time_of_day_map — иначе «9 утра»
    #    ломалось в «9 9:00» (см. старый коммент ниже).
    text = _normalize_clock_words(text)

    # 1. Часть суток → конкретное время. Делаем ДО обработки «в N»:
    #    после маппинга «утром» → «9:00» в строке нет «в N», обработка идёт чисто.
    time_of_day_map = {
        r"\bутром\b": "9:00",
        r"\bутра\b": "9:00",            # «9 утра» → «9 9:00»? нет, только без числа
        r"\bднём\b": "14:00",
        r"\bднем\b": "14:00",
        r"\bвечером\b": "18:00",
        r"\bночью\b": "22:00",
    }
    # «9 утра» / «3 ночи» — не подменяем (там число уже задаёт час).
    # Простая эвристика: подменяем только если перед маркером нет цифры.
    for pat, replacement in time_of_day_map.items():
        # Lookbehind: «не цифра и не цифра-пробел»
        full_pat = re.compile(r"(?<!\d)(?<!\d\s)" + pat, re.IGNORECASE)
        text = full_pat.sub(replacement, text)

    # Bare time без контекста («22:00», «9:00») dateparser теперь не парсит
    # (после tz-фикса). Если в строке нет дня (сегодня/завтра/в субботу/число.число)
    # и есть только время → подставляем «сегодня».
    text_stripped = text.strip()
    has_day_marker = bool(re.search(
        r"\b(сегодня|завтра|послезавтра|вчера|в\s+(?:понедельник|вторник|сред[уы]|четверг|пятниц[уы]|суббот[уы]|воскресень)\w*|\d{1,2}\.\d{1,2}|\d+\s*(?:дн|недел|месяц))",
        text_stripped, re.IGNORECASE,
    ))
    has_only_time = bool(re.fullmatch(r"\d{1,2}[:.]\d{2}", text_stripped))
    if has_only_time and not has_day_marker:
        text = "сегодня " + text_stripped

    # 2. «в N» / «at N» → «в N:00» (числа 0..23, не followed by :, ., -, час/h)
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
    """Полная фраза совпадает с fallback-маркером (с опц. пунктуацией вокруг).

    Match: «не знаю», «  потом ?», «как-нибудь.», «ок».
    No match: «в 9 ок», «приди не знаю когда», «потом увидимся».

    `text` ожидается lowercase + stripped.
    """
    global _FALLBACK_PATTERNS_FULL_RE
    if _FALLBACK_PATTERNS_FULL_RE is None:
        # Сортируем по длине убыванием чтобы «как-нибудь» матчилось перед «как»
        sorted_patterns = sorted(_FALLBACK_PATTERNS, key=len, reverse=True)
        joined = "|".join(re.escape(p) for p in sorted_patterns)
        _FALLBACK_PATTERNS_FULL_RE = re.compile(
            rf"^\s*(?:{joined})\s*[!?.,]*\s*$", re.IGNORECASE
        )
    return bool(_FALLBACK_PATTERNS_FULL_RE.match(text))
