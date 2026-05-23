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

# Маркеры пунктов в начале строки. Включаем ✅/☐/✓/✗ — наш собственный
# рендер использует их, и юзер может переслать своё же сообщение боту обратно.
# Без этих маркеров отрендеренный список не распознаётся при copy-paste.
BULLET_RE = re.compile(
    r"^\s*(?:✅|☐|✔|✗|☑|☒|[-•*—−]|\d+[.)])\s+",
    re.MULTILINE,
)

# Служебные строки нашего рендера — игнорируем при подсчёте preamble и tasks.
BOT_RENDERED_NOISE_RE = re.compile(
    r"^\s*(?:📋|↩️|💬|⏰|"
    r"Выполнено:|Reply:|Примеры:|Ответь reply|Ответь на это сообщение|"
    r"\[\d{2}:\d{2}\])",
    re.IGNORECASE,
)

# Разделители для inline-списков ("молоко, хлеб, сыр")
INLINE_SPLIT_RE = re.compile(r"[,;]|\s+и\s+")

# Anti-task-list signals: ad/social/contact patterns в пункте.
# Если такой паттерн встречается в 2+ пунктах — это рекламный/информационный
# пост, а не список задач.
AD_PATTERNS = (
    re.compile(r"#\w+", re.IGNORECASE),                  # хэштеги
    re.compile(r"https?://|www\.|\.ru\b|\.com\b", re.IGNORECASE),  # ссылки
    re.compile(r"\+?\d[\d\s\-()]{8,}"),                  # телефоны
    re.compile(r"\bподпис(?:ат|ыв)|\bканал[ея]|\bзаявк|чат\b|телеграм", re.IGNORECASE),
    re.compile(r"@[a-z0-9_]{4,}", re.IGNORECASE),        # @mentions
)

# Длинный пункт = абзац, не задача. Жёсткий лимит на отдельный элемент.
MAX_TASK_LENGTH = 100

# Прелюдия перед первым маркером: если описательного текста > N слов,
# это статья с нумерацией, не список задач.
MAX_PREAMBLE_WORDS = 25

# Слова-преамбулы голосовой диктовки. «Сегодня нужно», «Мне надо»,
# «Так, короче» — вводные перед самим списком, не пункты. Зеркало
# bot/services/voice_list._PREAMBLE_WORDS, но backend — источник правды
# для structured_data, поэтому фильтруем здесь независимо от того,
# препроцессил ли бот (текст / форвард / другой клиент могут не).
PREAMBLE_WORDS = (
    "нужно", "надо", "сделать", "сегодня", "завтра",
    "запиши", "запомни", "вот", "так", "короче", "значит",
)
# Филлеры-связки: сами по себе не преамбула, но допустимы внутри неё
# («Мне надо», «Так короче»). Реального пункта-существительного не несут.
PREAMBLE_FILLER = (
    "мне", "нам", "я", "это", "что", "ну", "и", "а", "тут", "там",
)
# Преамбула — короткая (≤6 слов, ≤40 симв) строка.
MAX_PREAMBLE_LINE_WORDS = 6
MAX_PREAMBLE_LINE_CHARS = 40


def _is_preamble_line(line: str) -> bool:
    """True если строка — чистая вводная преамбула («Сегодня нужно.»).

    Требуем: короткая (≤6 слов, ≤40 симв), есть хоть одно преамбульное
    слово, И ВСЕ слова — преамбульные/филлеры. Если есть хоть одно
    «контентное» слово («сделать отчёт» → «отчёт») — это реальный пункт,
    не дропаем.
    """
    norm = line.strip().lower()
    if not norm or len(norm) > MAX_PREAMBLE_LINE_CHARS:
        return False
    # Чистим пунктуацию у каждого слова («так,» → «так»), чтобы запятые
    # в середине не ломали матч.
    words = [w.strip(".:!,;-—") for w in norm.split()]
    words = [w for w in words if w]
    if not words or len(words) > MAX_PREAMBLE_LINE_WORDS:
        return False
    allowed = set(PREAMBLE_WORDS) | set(PREAMBLE_FILLER)
    has_preamble_word = any(w in PREAMBLE_WORDS for w in words)
    all_allowed = all(w in allowed for w in words)
    return has_preamble_word and all_allowed


def _drop_leading_preamble(lines: list[str]) -> list[str]:
    """Снимает ведущие строки-преамбулы до первого реального пункта.

    Дропаем только В НАЧАЛЕ — преамбульное слово в середине списка
    («2. надо позвонить») это валидный пункт, не трогаем.
    """
    i = 0
    while i < len(lines) and _is_preamble_line(lines[i]):
        i += 1
    return lines[i:]


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
    """Парсит текст с маркерами в начале строк.

    Также удаляет нумерацию ВНУТРИ пункта после bullet-маркера (например
    «✅ 1. хуй» → «хуй»), потому что наш рендер использует ✅ + номер.
    Пропускает служебные строки бот-рендера (📋, Выполнено:, Reply: и т.д.).
    """
    lines = text.split("\n")
    tasks = []
    for line in lines:
        # Пропускаем шапку/футер нашего же рендера
        if BOT_RENDERED_NOISE_RE.match(line):
            continue
        stripped = BULLET_RE.sub("", line).strip()
        # После снятия bullet может остаться "1. хуй" — снимаем нумерацию
        stripped = re.sub(r"^\d+[.):\-]\s*", "", stripped)
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


def _count_ad_signal_items(tasks: list[str]) -> int:
    """Сколько пунктов содержат ad/social/contact маркеры.

    2+ таких пункта = информационный пост, не список задач.
    """
    count = 0
    for t in tasks:
        if any(p.search(t) for p in AD_PATTERNS):
            count += 1
    return count


def _preamble_word_count(text: str) -> int:
    """Возвращает число слов до первого маркера (если он есть).

    Пустая строка / нет маркеров → 0 (не штрафуем).
    """
    match = BULLET_RE.search(text)
    if not match:
        return 0
    preamble = text[:match.start()].strip()
    if not preamble:
        return 0
    return len(preamble.split())


def _looks_like_article_with_numbering(text: str, tasks: list[str]) -> bool:
    """True, если структура текста явно говорит «это пост/статья,
    а не список задач»:

    - Длинная описательная прелюдия перед первым пунктом
    - Хотя бы один пункт длиннее MAX_TASK_LENGTH
    - В нескольких пунктах есть ad/social/contact маркеры
    """
    if not tasks:
        return False

    # 1a. Длинный пункт в распарсенных tasks = это абзац статьи
    if any(len(t) > MAX_TASK_LENGTH for t in tasks):
        return True

    # 1b. Длинная строка между маркерами в исходном тексте — могла быть
    # отфильтрована в _parse_bulleted (>300 chars), но это всё равно статья.
    # Без этой проверки очень длинный нумерованный абзац + короткий пункт
    # обходили article-filter.
    for line in text.split("\n"):
        # снимаем bullet-маркер в начале строки
        stripped = BULLET_RE.sub("", line).strip()
        if len(stripped) > MAX_TASK_LENGTH:
            return True

    # 2. 2+ пункта с рекламными/контактными маркерами
    if _count_ad_signal_items(tasks) >= 2:
        return True

    # 3. Описательная прелюдия перед маркерами
    if _preamble_word_count(text) > MAX_PREAMBLE_WORDS:
        return True

    return False


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
        # Снимаем ведущую преамбулу («Сегодня нужно.») — не пункт.
        lines = _drop_leading_preamble(lines)
        if len(lines) >= 2:
            tasks = lines
        else:
            # Одна строка без запятых — один пункт
            tasks = [lines[0]] if lines else []

    if not tasks:
        return TaskListDetection(False, forced, [], stripped_text)

    # Решение: список или нет
    # 1. Юзер форсировал → да (если есть хоть что-то парсить).
    #    Здесь намеренно не отфильтровываем по article-сигналам — юзер сам сказал.
    if forced and len(tasks) >= 1:
        return TaskListDetection(True, True, tasks, stripped_text)

    # Anti-false-positive фильтр: если структура говорит «это статья/пост»
    # — не делаем список, даже если AI или маркер-эвристика сказали бы да.
    if _looks_like_article_with_numbering(content, tasks):
        return TaskListDetection(False, False, [], stripped_text)

    # 2. AI сказал action + ≥2 пункта → да
    if ai_item_type == "action" and len(tasks) >= 2:
        return TaskListDetection(True, False, tasks, stripped_text)

    # 3. Сильная эвристика: ≥2 маркированных строк → да независимо от AI
    #    НО: если средняя длина пунктов > 80 символов — это не задачи, а длинный
    #    нумерованный текст (страховка поверх article-фильтра выше).
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
