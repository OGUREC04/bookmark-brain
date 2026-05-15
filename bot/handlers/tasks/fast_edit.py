"""Fast-path NL edits for task lists (3po split).

Regex-based command parsing WITHOUT LLM: done/undone/all-done, add, remove,
deadline. Plus delete-list meta-command detection and the reply-based
delete-list flow. Pure helpers — no router (called by nl_edit).
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

logger = logging.getLogger(__name__)


# ───────────────────── Reply meta-commands ─────────────────────

_DELETE_PHRASES = frozenset({
    "удали", "удалить", "удали список", "удалить список",
    "убери", "убери список", "убрать список", "снеси", "снеси список",
})


def _is_delete_command(text: str) -> bool:
    return text in _DELETE_PHRASES


# ───────────────────── Fast-path NL edits (без LLM) ─────────────

# Паттерны: "9 до завтра", "3 до пятницы", "9 пункт до завтра", "9: до 08.05"
_DEADLINE_PATTERN = re.compile(
    r"^(\d+)\s*(?:пункт|п|:|-|—)?\s*(?:до|к|дедлайн|срок|deadline)?\s*(.+)$",
    re.IGNORECASE,
)
# Mark done — широкий список синонимов + один или несколько индексов через "," или "и".
# Ловит: "закрой 1", "закрой 1, 3", "выполни 2 и 4", "1 готово", "3 пункт сделано",
#        "✅ 1, 2", "сделал 5", "гтв 7", "done 10".
# ВАЖНО: идемпотентный SET (done=True), НЕ toggle. Снять галку — через _UNDONE_PATTERN.
_INDEX_GROUP = r"(\d+(?:\s*(?:[,;]|\bи\b)\s*\d+)*)"
_DONE_VERBS = (
    r"готово|сделано?|сделал[аи]?|закончил[аи]?|завершил[аи]?|"
    r"гтв|done|✓|✅|закрой|закрыть|закрыт[аоы]?|"
    r"отметь|отметить|выполни|выполнить|сделай"
)
_DONE_PATTERN = re.compile(
    rf"^(?:{_DONE_VERBS})\s*{_INDEX_GROUP}\s*(?:пункт[аы]?|п)?$"
    rf"|"
    rf"^{_INDEX_GROUP}\s*(?:пункт[аы]?|п)?\s*(?:{_DONE_VERBS})$",
    re.IGNORECASE,
)
# Unmark done — снять галку. ВАЖНО: «не готово» проверяем ДО _DONE_PATTERN
# чтобы «готово» не сматчилось раньше.
_UNDONE_VERBS = (
    r"не\s+готов[оы]?|не\s+сделано?|"
    r"отмени|отменить|"
    r"вернуть|верни|"
    r"снять|сними|открой|открыть"
)
_UNDONE_PATTERN = re.compile(
    rf"^(?:{_UNDONE_VERBS})\s*{_INDEX_GROUP}\s*(?:пункт[аы]?|п)?$"
    rf"|"
    rf"^{_INDEX_GROUP}\s*(?:пункт[аы]?|п)?\s*(?:{_UNDONE_VERBS})$",
    re.IGNORECASE,
)
# Bulk: «всё/все готово», «закрой всё/все», «готово всё». done=True для всех.
_ALL_DONE_PATTERN = re.compile(
    r"^(?:"
    r"(?:всё|все)\s+(?:готово|сделано|закрыт[оы]?)"
    r"|закрой\s+(?:всё|все)"
    r"|закрыть\s+(?:всё|все)"
    r"|готово\s+(?:всё|все)"
    r")$",
    re.IGNORECASE,
)
# "добавь X", "+ X", "запиши X"
_ADD_PATTERN = re.compile(
    r"^(?:добавь|добавить|запиши|записать|внеси|внести|\+)\s+(.+)$",
    re.IGNORECASE,
)
# "удали 3", "удали 1, 3", "убери 2 и 4", "- 5"
_REMOVE_PATTERN = re.compile(
    rf"^(?:удали|удалить|убери|убрать|-)\s*{_INDEX_GROUP}\s*(?:пункт[аы]?|п)?$",
    re.IGNORECASE,
)


def _parse_indices(group_text: str) -> list[int]:
    """'1, 3', '1 и 4', '2;5' → [0, 2] / [0, 3] / [1, 4] (0-based, отсортировано, без дублей)."""
    raw = re.split(r"[,;]|\sи\s", group_text)
    out: set[int] = set()
    for chunk in raw:
        chunk = chunk.strip()
        if chunk.isdigit():
            out.add(int(chunk) - 1)
    return sorted(out)

_DAY_NAMES = {
    "понедельник": 0, "пн": 0,
    "вторник": 1, "вт": 1,
    "среда": 2, "ср": 2, "среду": 2,
    "четверг": 3, "чт": 3,
    "пятница": 4, "пт": 4, "пятницу": 4,
    "суббота": 5, "сб": 5, "субботу": 5,
    "воскресенье": 6, "вс": 6,
}


def _parse_date(text: str) -> str | None:
    """Парсит дату из текста. Возвращает ISO YYYY-MM-DD или None."""
    text = text.strip().lower().rstrip(".")

    today = date.today()

    if text in ("сегодня", "today"):
        return today.isoformat()
    if text in ("завтра", "tomorrow"):
        return (today + timedelta(days=1)).isoformat()
    if text in ("послезавтра",):
        return (today + timedelta(days=2)).isoformat()

    # "через N дней"
    m = re.match(r"через\s+(\d+)\s+(?:день|дня|дней)", text)
    if m:
        return (today + timedelta(days=int(m.group(1)))).isoformat()

    # "через неделю"
    if text in ("через неделю",):
        return (today + timedelta(weeks=1)).isoformat()

    # День недели
    if text in _DAY_NAMES:
        target_wd = _DAY_NAMES[text]
        current_wd = today.weekday()
        days_ahead = (target_wd - current_wd) % 7
        if days_ahead == 0:
            days_ahead = 7  # следующий такой день
        return (today + timedelta(days=days_ahead)).isoformat()

    # DD.MM или DD.MM.YYYY
    m = re.match(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?$", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass

    return None


def _try_fast_edit(user_text: str, structured: dict) -> dict | None:
    """Пробует применить простую команду без LLM.

    Возвращает обновлённый structured_data или None если не распознал.
    """
    text = user_text.strip()
    tasks = list(structured.get("tasks", []))
    if not tasks:
        return None

    # All done: «всё готово», «закрой все» → done=True для всех
    if _ALL_DONE_PATTERN.match(text):
        new_tasks = [{**t, "done": True} for t in tasks]
        return {**structured, "tasks": new_tasks}

    # Undone — проверяем ДО done чтобы «не готово» не сматчилось как «готово»
    m = _UNDONE_PATTERN.match(text)
    if m:
        group = m.group(1) or m.group(2)
        indices = _parse_indices(group)
        if not indices:
            return None
        if any(i < 0 or i >= len(tasks) for i in indices):
            return None
        for idx in indices:
            tasks[idx] = {**tasks[idx], "done": False}
        return {**structured, "tasks": tasks}

    # Done: «закрой 1», «закрой 1, 3», «выполни 2 и 4», «3 готово», «сделал 5».
    # ИДЕМПОТЕНТНО (set done=True, не toggle).
    m = _DONE_PATTERN.match(text)
    if m:
        group = m.group(1) or m.group(2)
        indices = _parse_indices(group)
        if not indices:
            return None
        if any(i < 0 or i >= len(tasks) for i in indices):
            return None
        for idx in indices:
            tasks[idx] = {**tasks[idx], "done": True}
        return {**structured, "tasks": tasks}

    # Remove: "удали 3", "удали 1, 3", "убери 2 и 4"
    m = _REMOVE_PATTERN.match(text)
    if m:
        indices = _parse_indices(m.group(1))
        if not indices:
            return None
        if any(i < 0 or i >= len(tasks) for i in indices):
            return None
        # Удаляем с конца, чтобы индексы не сдвигались
        for idx in sorted(indices, reverse=True):
            tasks.pop(idx)
        return {**structured, "tasks": tasks}

    # Add: "добавь X", "+ X"
    m = _ADD_PATTERN.match(text)
    if m:
        new_text = m.group(1).strip()
        if new_text:
            tasks.append({"text": new_text, "done": False, "deadline": None, "note": None})
            return {**structured, "tasks": tasks}
        return None

    # Deadline: "9 до завтра", "3 пятница", "9: до 08.05"
    m = _DEADLINE_PATTERN.match(text)
    if m:
        idx = int(m.group(1)) - 1
        date_text = m.group(2).strip()
        parsed = _parse_date(date_text)
        if parsed and 0 <= idx < len(tasks):
            tasks[idx] = {**tasks[idx], "deadline": parsed}
            return {**structured, "tasks": tasks}
        # Не смогли распарсить дату — пусть LLM попробует
        return None

    return None


async def _handle_delete_via_reply(
    message: Message, api, token: str, bid: str, store=None,
) -> None:
    """Удалить task_list целиком через reply-команду (silent mode аналог кнопки 🗑)."""
    replied = message.reply_to_message

    # Unpin
    if replied:
        try:
            await replied.unpin()
        except TelegramBadRequest:
            pass

    # Удалить bookmark в БД
    try:
        await api.delete_bookmark(token, bid)
    except Exception as e:
        logger.error(f"delete_bookmark via reply failed: {e}")

    # Удалить сообщение бота
    if replied:
        try:
            await replied.delete()
        except TelegramBadRequest:
            try:
                await replied.edit_text("🗑 Удалён", parse_mode=None, reply_markup=None)
            except TelegramBadRequest:
                pass

    # Удалить reply юзера
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # Чистим Redis
    if store is not None and replied:
        try:
            await store.unbind_list_message(message.chat.id, replied.message_id)
        except Exception:
            pass
