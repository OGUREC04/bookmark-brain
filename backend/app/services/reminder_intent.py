"""Pattern-based детектор намерений «нужно сделать что-то к сроку» (Phase 2.5).

Не использует LLM — простые regex для скорости и предсказуемости.
ML-классификатор намерений — Phase 4 (Learning Mechanisms) с feedback loop.

Семантика:
- has_intent=True → бот предлагает inline-кнопку «🔔 Создать напоминание?»
- has_intent=False → ничего не показываем (обычный save flow)

Допускаем false positive (показали кнопку зря) — юзер может проигнорить / нажать «Отказ».
False negative (не показали хотя надо было) — хуже: юзер не узнает что фича существует.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ReminderIntent:
    has_intent: bool


# Сильные глаголы намерения — одного хватит для intent (без даты).
# «Надо купить молоко» — реальный todo, лучше показать кнопку лишний раз.
_STRONG_VERB_RE = re.compile(
    r"\b(надо|нужно|нужен|нужна|нужны|не\s+забыть|должен|должна|должны)\b",
    re.IGNORECASE,
)

# Слабые глаголы — нужно подтверждение датой / предлогом
_WEAK_VERB_RE = re.compile(
    r"\b("
    r"сделать|сделай|"
    r"позвонить|позвони|"
    r"написать|напиши|"
    r"купить|купи|"
    r"подать|подай|"
    r"проверить|проверь|"
    r"оплатить|оплати|"
    r"закрыть|закрой|"
    r"отправить|отправь|"
    r"встретиться|встретимся|встреча|"
    r"созвон|созвониться|созвонимся|"
    r"съездить|съездим"
    r")\b",
    re.IGNORECASE,
)

# Временные предлоги — «до X», «к X», «на X»
_PREPOSITION_RE = re.compile(
    r"\b(?:до|к|на)\s+(?=\S)",  # должно быть что-то после
    re.IGNORECASE,
)

# Явные даты / относительные интервалы — самодостаточные (без глагола ОК)
_DATE_RE = re.compile(
    r"\b("
    # Относительные
    r"завтра|послезавтра|сегодня|"
    r"через\s+\d+\s+(?:час|часа|часов|минут|минуту|минуты|день|дня|дней|неделю|недели|недель|месяц|месяца|месяцев)|"
    r"через\s+(?:час|день|неделю|месяц)|"
    # Дни недели — со всеми падежами
    r"(?:в\s+)?(?:понедельник\w*|вторник\w*|сред\w+|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*)|"
    # «N мая» / «N июня» и т.д.
    r"\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)|"
    # Праздники / выходные
    r"на\s+праздник(?:ах|и)?|на\s+выходн(?:ых|ые)"
    r")\b",
    re.IGNORECASE,
)

# Время суток — слабый сигнал, требует глагола.
# Без этого «я читал утром» → has_intent=True (ложное срабатывание).
_TIME_OF_DAY_RE = re.compile(
    r"\b(?:утром|вечером|ночью|днём|днем)\b",
    re.IGNORECASE,
)

# Числовые даты DD.MM — отдельно с проверкой диапазонов (не «версия 2.5»)
_NUMERIC_DATE_RE = re.compile(
    r"\b("
    # DD.MM или DD.MM.YYYY — день 01-31, месяц 01-12
    r"(?:0?[1-9]|[12]\d|3[01])[.\-/](?:0?[1-9]|1[012])(?:[.\-/]\d{2,4})?"
    r")\b"
)


def detect_reminder_intent(text: str) -> ReminderIntent:
    """Пытается понять есть ли в тексте намерение «нужно сделать к сроку».

    Не пытается достать конкретное время — это зона `nl_date.parse()`.
    Здесь только бинарный сигнал «показывать кнопку или нет».

    Логика:
    - Сильный глагол («надо», «нужно», «не забыть») — достаточно сам по себе.
    - Слабый глагол («купить», «позвонить») + дата/предлог — достаточно.
    - Просто явная дата без глагола («встреча 15 мая») — достаточно.
    """
    if not text or not text.strip():
        return ReminderIntent(has_intent=False)

    has_strong_verb = bool(_STRONG_VERB_RE.search(text))
    has_weak_verb = bool(_WEAK_VERB_RE.search(text))
    has_word_date = bool(_DATE_RE.search(text))
    has_numeric_date = bool(_NUMERIC_DATE_RE.search(text))
    has_time_of_day = bool(_TIME_OF_DAY_RE.search(text))
    has_preposition = bool(_PREPOSITION_RE.search(text))

    if has_strong_verb:
        return ReminderIntent(has_intent=True)
    if has_weak_verb and (has_word_date or has_numeric_date or has_time_of_day or has_preposition):
        return ReminderIntent(has_intent=True)
    # Word-формы дат («15 мая», «завтра», «в пятницу») — однозначно дата.
    if has_word_date:
        return ReminderIntent(has_intent=True)
    # Numeric date «15.05» — дата только в контексте предлога/глагола,
    # иначе не отличить от версии «2.5» / номера «3.14».
    if has_numeric_date and (has_weak_verb or has_preposition):
        return ReminderIntent(has_intent=True)

    return ReminderIntent(has_intent=False)
