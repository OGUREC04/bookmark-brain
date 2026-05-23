"""Save-flow router для Phase 2.6 — определяет финальный reminder_form.

Pure function: на вход берёт текст + AIClassification + user_tz,
на выход — RouterDecision с формой и resolved items (UTC datetimes).

Worker (bookmark_processor) персистит decision в `bookmark.structured_data
.reminder_decision` чтобы T4-T8 хендлеры могли прочитать его и среагировать
соответствующим образом (3-button UI / per-item create / composite create /
strong-flow / nothing).

Контракт см. docs/prd/PHASE-2.6-REMINDERS-X-TASKS.md, секция "Solution Detail".

Правила приоритета (применяются сверху вниз):

  1. Strong-intent + single-statement + есть час/часть суток → SINGLE_REMINDER (молча)
  2. Strong-intent + single-statement + нет даты → STRONG_INTENT_3BUTTON (Phase 2.5 flow)
  3. Strong-intent + single-statement + дата без часа → NEEDS_HOUR (ask Reply)
  4. 2+ дат → TASK_LIST_WITH_REMINDERS (молча, per-item)
  5. 1 дата + multi-item → NEEDS_BUTTON_CHOICE (3 кнопки 📋/🔔/✕)
  6. 1 дата + single-item → SINGLE_REMINDER
  7. 0 дат + needs_hour_items → NEEDS_HOUR
  8. 0 дат + multi-item → TASK_LIST_NO_REMINDERS
  9. Иначе → NONE (обычная закладка)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.schemas import AIClassification, ReminderItem
from app.services.nl_date import ParseResult, ParseStatus
from app.services.nl_date import parse as nl_date_parse

logger = logging.getLogger(__name__)


class ReminderForm(str, Enum):
    """Финальное решение роутера. Бот/воркер маршрутизируют UI и побочки по этому."""

    NONE = "none"
    TASK_LIST_NO_REMINDERS = "task_list_no_reminders"
    TASK_LIST_WITH_REMINDERS = "task_list_with_reminders"
    SINGLE_REMINDER = "single_reminder"
    COMPOSITE_REMINDER = "composite_reminder"
    # Спросить юзера через 3 кнопки 📋/🔔/✕ (1 дата + multi-item)
    NEEDS_BUTTON_CHOICE = "needs_button_choice"
    # Спросить юзера через Reply «во сколько?»
    NEEDS_HOUR = "needs_hour"
    # Strong-intent Phase 2.5 — кнопки 🔔/📝/✕
    STRONG_INTENT_3BUTTON = "strong_intent_3button"


@dataclass(frozen=True)
class ResolvedItem:
    """Один распознанный пункт с резолвом даты в UTC datetime."""

    text: str
    raw_date_phrase: str | None
    fire_at: datetime | None  # UTC-aware или None
    status: ParseStatus | None  # None если нет raw_date_phrase

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "raw_date_phrase": self.raw_date_phrase,
            "fire_at_utc": self.fire_at.isoformat() if self.fire_at else None,
            "status": self.status.value if self.status else None,
        }


@dataclass(frozen=True)
class RouterDecision:
    form: ReminderForm
    items: list[ResolvedItem] = field(default_factory=list)
    strong_intent: bool = False
    explicit_trigger: bool = False  # «сделай напоминание …»

    @property
    def dated_items(self) -> list[ResolvedItem]:
        return [i for i in self.items if i.fire_at is not None]

    @property
    def needs_hour_items(self) -> list[ResolvedItem]:
        return [i for i in self.items if i.status == ParseStatus.NEEDS_HOUR]

    def to_dict(self) -> dict:
        """Сериализация для bookmark.structured_data.reminder_decision."""
        return {
            "form": self.form.value,
            "items": [i.to_dict() for i in self.items],
            "strong_intent": self.strong_intent,
            "explicit_trigger": self.explicit_trigger,
        }


# Strong-intent глаголы по Phase 2.5 — на старте предложения / самостоятельно.
# «надо/нужно/не забыть/срочно/обязательно/обязан/должен/должна».
_STRONG_INTENT_RE = re.compile(
    r"\b(?:надо|нужно|нужен|нужна|нужны|не\s+забыть|"
    r"срочно|обязательно|обязан|обязана|должен|должна|должны)\b",
    re.IGNORECASE,
)

# Explicit-команда «сделай напоминание / напомни / поставь reminder».
_EXPLICIT_TRIGGER_RE = re.compile(
    # Не используем закрывающий \b — стемы «напоминан/reminder» могут иметь
    # окончания («напоминание/напоминанию/reminders»), word boundary на стыке
    # word-char + word-char не сработает.
    r"\b(?:сделай\s+напоминан|поставь\s+(?:напоминан|reminder)|"
    r"напомни(?:\b|\s+мне|\s+что)|создай\s+(?:напоминан|reminder)|"
    r"\breminder\b)",
    re.IGNORECASE,
)

# Час или часть суток в тексте — если есть, при strong-intent НЕ показываем
# 3-button, а сразу создаём reminder. Берём из nl_date._TIME_HINT_RE для
# консистентности: «в 9», «18:30», «утром», «вечером», «через час».
_TIME_OR_PART_OF_DAY_RE = re.compile(
    r"(?:"
    r"\b\d{1,2}[:.]\d{2}"
    r"|\bв\s+\d{1,2}\b"
    r"|\bчерез\s+\d*\s*(?:час|часа|часов|минут|минуту|минуты|мин)"
    r"|\bутр(?:а|ом)?\b|\bвечер(?:а|ом)?\b|\bдн(?:я|ём|ем)\b|\bноч(?:и|ью)\b"
    r"|\bв\s+полдень\b|\bполдень\b"
    r")",
    re.IGNORECASE,
)


def _resolve_item(item: ReminderItem, user_tz: str, now: datetime | None) -> ResolvedItem:
    """Прогоняет raw_date_phrase через nl_date.parse() → ResolvedItem."""
    if not item.raw_date_phrase:
        return ResolvedItem(
            text=item.text,
            raw_date_phrase=None,
            fire_at=None,
            status=None,
        )
    result: ParseResult = nl_date_parse(item.raw_date_phrase, user_tz=user_tz, now=now)
    return ResolvedItem(
        text=item.text,
        raw_date_phrase=item.raw_date_phrase,
        fire_at=result.dt,  # None если NEEDS_HOUR / IN_PAST / UNPARSEABLE
        status=result.status,
    )


def route(
    *,
    text: str,
    classification: AIClassification,
    user_tz: str = "Europe/Moscow",
    now: datetime | None = None,
) -> RouterDecision:
    """Главный роутер. См. docstring модуля для правил.

    Args:
        text: оригинальный текст сообщения (для strong-intent / explicit detection)
        classification: AIClassification с reminder_items, single_statement, hint
        user_tz: IANA timezone юзера
        now: текущее время (UTC-aware) для тестов

    Returns:
        RouterDecision с финальной формой и items.
    """
    text_norm = (text or "").strip()

    strong_intent = bool(_STRONG_INTENT_RE.search(text_norm))
    explicit = bool(_EXPLICIT_TRIGGER_RE.search(text_norm))
    has_time_marker = bool(_TIME_OR_PART_OF_DAY_RE.search(text_norm))
    single = classification.single_statement

    # Резолвим каждый item через nl_date
    items = [
        _resolve_item(it, user_tz=user_tz, now=now)
        for it in (classification.reminder_items or [])
    ]
    dated = [i for i in items if i.fire_at is not None]
    needs_hour = [i for i in items if i.status == ParseStatus.NEEDS_HOUR]

    # Терминальные формы-классификации (сравнимы с AI form_hint).
    # ask-состояния (needs_hour / needs_button_choice / strong_3button) —
    # это «спросить юзера», не классификация, в аудит не идут.
    _COMPARABLE_FORMS = frozenset({
        "none", "single_reminder", "composite_reminder",
        "task_list_with_reminders", "task_list_no_reminders",
    })

    def _decision(form: ReminderForm) -> RouterDecision:
        # B2 measurement: логируем расхождение router-решения и
        # холистической категории AI (reminder_form_hint). По этим данным
        # выберем архитектуру (router-primary / AI-primary / disagreement).
        # Чистое измерение — на поведение НЕ влияет.
        if form.value in _COMPARABLE_FORMS:
            hint = (classification.reminder_form_hint or "none").strip().lower()
            logger.info(
                "reminder_route_audit: router=%s ai_hint=%s agree=%s "
                "dated=%d single=%s strong=%s explicit=%s",
                form.value, hint, form.value == hint, len(dated),
                single, strong_intent, explicit,
            )
        return RouterDecision(
            form=form,
            items=items,
            strong_intent=strong_intent,
            explicit_trigger=explicit,
        )

    # ── Правило 1-3: strong-intent + single-statement ─────────────────────
    # Применяется только если AI согласился что это одно утверждение.
    # Multi-statement сразу падает в правила 4-8 (даже со strong словом).
    if strong_intent and single:
        # 1: есть дата с часом → создаём reminder молча
        if len(dated) >= 1:
            return _decision(ReminderForm.SINGLE_REMINDER)
        # 2: дата без часа → спросим Reply
        if needs_hour:
            return _decision(ReminderForm.NEEDS_HOUR)
        # 3: нет извлечённой даты — отдаём в Phase 2.5 strong-flow
        # (3 кнопки 🔔/📝/✕). Юзер уточнит через reply.
        # Даже если в тексте мелькает «утром»/«в 9», AI не извлёк item с
        # raw_date_phrase — создавать reminder без fire_at нечем.
        if has_time_marker:
            logger.debug(
                "router: strong+single без dated_items, но в тексте есть "
                "time-marker — AI не извлёк raw_date_phrase. Fallback в 3-button."
            )
        return _decision(ReminderForm.STRONG_INTENT_3BUTTON)

    # ── Правило 4: 2+ дат → task_list_with_reminders молча ────────────────
    if len(dated) >= 2:
        return _decision(ReminderForm.TASK_LIST_WITH_REMINDERS)

    # ── Правило 5: 1 дата + multi-item → 3 кнопки 📋/🔔/✕ ─────────────────
    if len(dated) == 1 and not single:
        return _decision(ReminderForm.NEEDS_BUTTON_CHOICE)

    # ── Правило 6: 1 дата + single-item → single_reminder ─────────────────
    if len(dated) == 1 and single:
        return _decision(ReminderForm.SINGLE_REMINDER)

    # ── Правило 7: 0 дат, но есть needs_hour → ask Reply ──────────────────
    if not dated and needs_hour:
        return _decision(ReminderForm.NEEDS_HOUR)

    # ── Правило 8: 0 дат + multi-item → task_list без reminders ───────────
    if not dated and not single and len(items) >= 2:
        return _decision(ReminderForm.TASK_LIST_NO_REMINDERS)

    # ── Правило 9: ничего из вышеперечисленного → обычная закладка ────────
    # Explicit-trigger («сделай напоминание») без даты в AI items —
    # отдаём как NEEDS_HOUR если AI вернул хоть один item, иначе NONE.
    # Bot хендлер T8 поймает inline-команду «сделай напоминание <текст> <когда>»
    # отдельно через start.handle_text, до save-flow.
    return _decision(ReminderForm.NONE)
