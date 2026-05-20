"""Voice intent detection — determines what to do with a transcribed voice message.

Intents:
  - "reminder" — user dictated «напомни …» (deterministic → reminder flow)
  - "todo"     — user dictated a task list (triggers task_list creation)
  - "search"   — user asked a search query (short, question-like)
  - "note"     — regular voice note (default, saved as bookmark)

Detection is purely heuristic (no LLM call) for speed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class VoiceIntent(str, Enum):
    REMINDER = "reminder"
    TODO = "todo"
    SEARCH = "search"
    NOTE = "note"


@dataclass
class IntentResult:
    intent: VoiceIntent
    cleaned_text: str  # text after stripping intent prefix


# ── Todo triggers ──────────────────────────────────────────────

_TODO_PREFIXES = (
    "сделай список",
    "список задач",
    "задачи на",
    "задачи:",
    "todo",
    "to do",
    "план на",
    "план:",
    "купить:",
    "купить",
    "закупка:",
    "чеклист",
    "чек-лист",
    "надо сделать",
    "нужно сделать",
)

# ── Reminder triggers (skf/kjo) ────────────────────────────────
# «напомни …» — детерминированно в reminder-флоу (как /remind), НЕ в
# task_list. Исключение: «напомни что/какие/где …» — это поисковый
# вопрос («напомни что я покупал»), уходит в search ниже.

_REMINDER_PREFIXES = (
    "напомни",
    "напоминание",
    "поставь напоминание",
    "сделай напоминание",
    "поставь напоминалку",
)

_REMINDER_SEARCH_GUARD = (
    "напомни что",
    "напомни о ",
    "напомни про",
    "напомни какие",
    "напомни какая",
    "напомни какой",
    "напомни где",
    "напомни сколько",
)

# Голосовая диктовка списка без буллетов: STT отдаёт сплошной поток.
# Эти два паттерна (порог ≥2) — компенсация: ловим перечисление и
# повтор-императив, отправляем в TODO. Подтверждение «Сделать список?»
# дальше всё равно спросит — даже ложный позитив гасится отказом.

# «1 ... 2 ... 3 ...» — нумерованный диктат без точек после цифр.
_NUMBERED_LIST_RE = re.compile(r"(?:^|\s)[1-9]\b")
# «нужно/надо сделать ... нужно/надо купить ...» — повтор-императив.
_REPEAT_IMPERATIVE_RE = re.compile(
    r"\b(?:нужно|надо|должен|должна|должны)\s+\w+",
    re.IGNORECASE,
)

_TODO_ANYWHERE = (
    "запиши задач",
    "сделай задач",
    "оформи список",
    "создай список",
)

# ── Search triggers ────────────────────────────────────────────

_SEARCH_PREFIXES = (
    "найди",
    "поищи",
    "покажи",
    "где у меня",
    "что у меня",
    "search",
    "напомни что",
    "какая закладка",
    "какие закладки",
)

_QUESTION_WORDS = ("где", "что", "какой", "какая", "какие", "какое", "когда", "сколько")


def detect_intent(text: str, duration: float | None = None) -> IntentResult:
    """Detect voice intent from transcription text.

    Args:
        text: Transcribed text from STT
        duration: Voice message duration in seconds (short = more likely search)

    Returns:
        IntentResult with detected intent and cleaned text
    """
    if not text or not text.strip():
        return IntentResult(intent=VoiceIntent.NOTE, cleaned_text=text or "")

    normalized = text.strip().lower()

    # ── Check reminder intent (skf/kjo) ──
    # «напомни …» → детерминированно reminder, кроме поисковых
    # «напомни что/какие/где …».
    if not normalized.startswith(_REMINDER_SEARCH_GUARD):
        for prefix in _REMINDER_PREFIXES:
            if normalized.startswith(prefix):
                cleaned = text.strip()[len(prefix):].lstrip(" :-—,.\n")
                # «напомни мне …» → срезаем и «мне»
                if cleaned.lower().startswith("мне "):
                    cleaned = cleaned[4:].lstrip(" :-—,.\n")
                return IntentResult(
                    intent=VoiceIntent.REMINDER,
                    cleaned_text=cleaned or text.strip(),
                )

    # ── Voice list dictation without bullets (kjo-followup) ──
    # ≥2 «1 ... 2 ...» цифр-маркеров ИЛИ ≥2 «нужно/надо <глагол>»
    # → диктовка списка. Подтверждение спросит дальше — ложный
    # позитив (например «у меня 2 идеи 3 варианта») безопасен.
    if (
        len(_NUMBERED_LIST_RE.findall(normalized)) >= 2
        or len(_REPEAT_IMPERATIVE_RE.findall(normalized)) >= 2
    ):
        return IntentResult(intent=VoiceIntent.TODO, cleaned_text=text.strip())

    # ── Check todo intent ──
    for prefix in _TODO_PREFIXES:
        if normalized.startswith(prefix):
            cleaned = text.strip()[len(prefix):].lstrip(" :-—,.\n")
            return IntentResult(intent=VoiceIntent.TODO, cleaned_text=cleaned or text.strip())

    for phrase in _TODO_ANYWHERE:
        if phrase in normalized:
            return IntentResult(intent=VoiceIntent.TODO, cleaned_text=text.strip())

    # ── Check search intent ──
    # Only consider search for short messages (< 10s or < 60 chars)
    is_short = (duration is not None and duration < 10) or len(text.strip()) < 60

    if is_short:
        for prefix in _SEARCH_PREFIXES:
            if normalized.startswith(prefix):
                cleaned = text.strip()[len(prefix):].lstrip(" :-—,.\n")
                return IntentResult(intent=VoiceIntent.SEARCH, cleaned_text=cleaned or text.strip())

        # Question-like short message
        first_word = normalized.split()[0] if normalized.split() else ""
        if first_word in _QUESTION_WORDS and len(text.strip()) < 80:
            return IntentResult(intent=VoiceIntent.SEARCH, cleaned_text=text.strip())

    # ── Default: note ──
    return IntentResult(intent=VoiceIntent.NOTE, cleaned_text=text.strip())
