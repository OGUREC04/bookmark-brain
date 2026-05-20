"""Препроцесс голосового транскрипта для task_list AI-ветки.

Yandex STT отдаёт chunks (после strip_timestamps превращаются в строки),
но границы chunks не совпадают с пунктами:
  - «1 Дочистить макеты.» + «По главной странице поиска.» — один пункт.
  - «3» одинокой строкой + «Сделать 3 задание по бизнесу.» — один пункт.
  - «Сегодня нужно.» — преамбула, не пункт.

Группируем строки в пункты по нумерации, добавляем точки после цифр,
сбрасываем явные преамбулы. После этого task_list_detector видит
чистый «1. … 2. … 3. …» и не плодит огрызки.
"""
from __future__ import annotations

import re

# Цифра в начале строки (с опциональной пунктуацией после) — маркер пункта.
_DIGIT_LEAD_RE = re.compile(r"^(\d{1,2})[.):]?\s*(.*)$")
# Голая цифра-строка («3», «4.») — STT-разрыв середины пункта.
_BARE_DIGIT_RE = re.compile(r"^\d{1,2}[.):]?$")

# Короткие фразы-преамбулы, которые не должны становиться пунктами.
_PREAMBLE_WORDS = (
    "нужно", "надо", "сделать", "сегодня", "завтра",
    "запиши", "запомни", "вот", "так",
)


def _is_preamble(line: str) -> bool:
    """True если строка похожа на «Сегодня нужно.» / «Мне надо.» /
    «Вот что» — короткая преамбула без конкретики, ≤6 слов."""
    norm = line.strip().lower().rstrip(".:!,;")
    if len(norm) > 40 or not norm:
        return False
    words = norm.split()
    if len(words) > 6:
        return False
    # Хоть одно преамбульное слово И нет конкретного действия-существительного
    return any(w in _PREAMBLE_WORDS for w in words)


def preprocess_voice_list(text: str) -> str:
    """Группирует строки голосового транскрипта в пункты по нумерации.

    Правила:
      - Строка начинается с «\\d+ ...» → новый пункт.
      - «\\d+» (голая цифра) → следующая строка приклеивается к ней.
      - Не-цифровая строка после пункта → континуация (склеиваем).
      - Не-цифровая строка ДО первого пункта → преамбула, дропаем
        если короткая и из преамбульных слов.
      - На выходе каждый пункт идёт «N. <текст>» одной строкой.
    """
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not raw_lines:
        return ""

    items: list[str] = []
    current: str | None = None
    seen_first_digit = False

    for ln in raw_lines:
        m = _DIGIT_LEAD_RE.match(ln)
        if m and m.group(1):
            # Новый нумерованный пункт. Сохраняем предыдущий.
            if current is not None:
                items.append(current.strip())
            digit, rest = m.group(1), (m.group(2) or "").strip()
            current = f"{digit}. {rest}" if rest else f"{digit}."
            seen_first_digit = True
        else:
            # Не цифровая строка
            if not seen_first_digit:
                # Преамбула до первого пункта — дропаем если выглядит как
                # «сегодня нужно»/«мне надо», иначе пока копим в current.
                if _is_preamble(ln):
                    continue
                if current is None:
                    current = ln
                else:
                    current = f"{current} {ln}".strip()
            else:
                # Континуация текущего пункта.
                if current is None:
                    current = ln
                else:
                    current = f"{current} {ln}".strip()

    if current:
        items.append(current.strip())

    # Если bare digit оказался хвостом (current = «5.») — он будет
    # одним пунктом без текста; убираем такие огрызки.
    items = [it for it in items if not _BARE_DIGIT_RE.fullmatch(it.strip())]

    return "\n".join(items)
