"""Детектор списков задач и парсер пунктов.

Принцип: юзер не должен ничего выбирать руками. Либо мы уверенно
определяем что это список — либо оставляем как обычную заметку.

Порядок проверок:
  1. Явный триггер в тексте ("сделай список", "todo:", ...) → force=True, strip prefix.
  2. AI сказал item_type=action И видим ≥2 пункта → detected=True.
  3. Сильная эвристика (≥2 строки с маркерами или ≥3 коротких элемента
     через запятую) → detected=True даже если AI промахнулся.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Явные триггеры — если начинается с этого, ГАРАНТИРОВАННО делаем список.
# Нижний регистр, без пунктуации в конце. Матчим по началу нормализованного текста.
EXPLICIT_TRIGGERS = (
    "сделай список",
    "оформи список",
    "в список",
    "списком",
    "список:",
    "список задач",
    "задачи:",
    "задачи на",
    "todo:",
    "to do:",
    "to-do:",
    "чеклист:",
    "чек-лист:",
    "чек лист:",
    "план:",
    "план на",
    "купить:",
    "закупка:",
    "шоппинг:",
    "shopping:",
)

# Маркеры пунктов в начале строки
BULLET_RE = re.compile(r"^\s*(?:[-•*—−]|\d+[.)])\s+", re.MULTILINE)

# Разделители для inline-списков ("молоко, хлеб, сыр")
INLINE_SPLIT_RE = re.compile(r"[,;]|\s+и\s+")


@dataclass
class TaskListDetection:
    is_list: bool
    forced_by_user: bool  # юзер явно попросил
    tasks: list[str]      # распарсенные пункты
    stripped_text: str    # текст после удаления триггер-префикса


def _strip_trigger(text: str) -> tuple[str, bool]:
    """Если текст начинается с явного триггера — снимаем префикс.

    Возвращает (stripped, matched).
    """
    normalized = text.strip().lower()
    for trig in EXPLICIT_TRIGGERS:
        if normalized.startswith(trig):
            # Находим длину триггера в оригинале (с учётом регистра)
            stripped = text.strip()[len(trig):].lstrip(" :-—\n")
            return stripped, True
    return text, False


def _parse_bulleted(text: str) -> list[str]:
    """Парсит текст с маркерами в начале строк."""
    lines = text.split("\n")
    tasks = []
    for line in lines:
        stripped = BULLET_RE.sub("", line).strip()
        # Пропускаем пустые и слишком длинные (вряд ли пункт)
        if stripped and len(stripped) < 300:
            tasks.append(stripped)
    return tasks


def _count_bullet_lines(text: str) -> int:
    return len(BULLET_RE.findall(text))


def _parse_inline(text: str) -> list[str]:
    """Парсит inline-список через запятые: 'молоко, хлеб, сыр'."""
    # Берём только первую строку если их несколько
    first_line = text.strip().split("\n")[0]
    parts = [p.strip() for p in INLINE_SPLIT_RE.split(first_line) if p.strip()]
    return parts


def _looks_like_inline_list(text: str) -> bool:
    """≥3 пункта через запятую, каждый короткий."""
    parts = _parse_inline(text)
    if len(parts) < 3:
        return False
    avg_len = sum(len(p) for p in parts) / len(parts)
    if avg_len > 40:
        return False
    # И нет точек в пунктах (не предложения)
    if any("." in p for p in parts):
        return False
    return True


def detect(text: str, ai_item_type: str | None = None) -> TaskListDetection:
    """Главный детектор. Никогда не бросает исключений."""
    if not text or not text.strip():
        return TaskListDetection(False, False, [], text)

    stripped_text, forced = _strip_trigger(text)

    # Анализируем содержимое после снятия триггера (если был)
    content = stripped_text if forced else text

    bullet_count = _count_bullet_lines(content)

    # Пытаемся распарсить оба способа
    bulleted_tasks = _parse_bulleted(content) if bullet_count >= 2 else []
    inline_ok = _looks_like_inline_list(content)
    inline_tasks = _parse_inline(content) if inline_ok else []

    # Выбор стратегии
    tasks: list[str] = []
    if bulleted_tasks:
        tasks = bulleted_tasks
    elif inline_tasks:
        tasks = inline_tasks
    elif forced:
        # Юзер попросил список, но маркеров нет — разбиваем по переносам
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        if len(lines) >= 2:
            tasks = lines
        else:
            # Одна строка без запятых — один пункт
            tasks = [content.strip()] if content.strip() else []

    if not tasks:
        return TaskListDetection(False, forced, [], stripped_text)

    # Решение: список или нет
    # 1. Юзер форсировал → да (если есть хоть что-то парсить)
    if forced and len(tasks) >= 1:
        return TaskListDetection(True, True, tasks, stripped_text)

    # 2. AI сказал action + ≥2 пункта → да
    if ai_item_type == "action" and len(tasks) >= 2:
        return TaskListDetection(True, False, tasks, stripped_text)

    # 3. Сильная эвристика: ≥2 маркированных строк → да независимо от AI
    #    НО: если средняя длина пунктов > 80 символов — это не задачи, а длинный
    #    нумерованный текст (статья, пост, тезисы). Пропускаем.
    if bullet_count >= 2:
        avg_task_len = sum(len(t) for t in tasks) / len(tasks) if tasks else 0
        if avg_task_len <= 80:
            return TaskListDetection(True, False, tasks, stripped_text)

    # 4. Сильный inline (3+ коротких пункта) → да
    if inline_ok and len(inline_tasks) >= 3:
        return TaskListDetection(True, False, tasks, stripped_text)

    return TaskListDetection(False, False, [], stripped_text)


def build_structured_data(detection: TaskListDetection) -> dict | None:
    """Превращает детекцию в JSONB shape для Bookmark.structured_data."""
    if not detection.is_list or not detection.tasks:
        return None
    return {
        "type": "task_list",
        "tasks": [
            {"text": t, "done": False, "deadline": None}
            for t in detection.tasks
        ],
    }
