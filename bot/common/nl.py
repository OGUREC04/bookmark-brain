"""Natural-language reminder parsing helpers shared across feature packages.

``extract_explicit_remind_body`` and ``split_remind_text_and_time`` are used
by both the reminders package and the tasks package (T7 "напомни on task
list"). Keeping them here removes the reminders↔tasks lateral dependency
that previously leaked through private re-exports.
"""
from __future__ import annotations

import re

from .datetime import DEFAULT_TZ

# Phase 2.6 T8: explicit-command prefix «сделай напоминание <body>» / «напомни <body>».
# Used by start.handle_text (inline trigger) and tasks T7 reply flow.
#
# Principles:
# - Start of string only (^) — a word mid-sentence is NOT a trigger
# - Require whitespace/end after the trigger — «напомни-ка» does NOT match
#   (guards against the «-ка» particle leaking into the body)
# - «напомнить/напоминаешь/напоминалось» (other verb forms) do not match
#   because a word-char follows «напомни», so the \b boundary fails
EXPLICIT_REMIND_PREFIX_RE = re.compile(
    r"^(?:сделай\s+напомин\w+|поставь\s+(?:напомин\w+|reminder)|"
    r"напомни(?:\s+мне)?|создай\s+напомин\w+)"
    r"(?=\s|$|[:,.])"   # next: space/end/allowed punctuation — NOT hyphen/letter
    r"[\s:,.]*",        # consume the separator (no hyphen)
    re.IGNORECASE,
)


def extract_explicit_remind_body(text: str) -> str | None:
    """If ``text`` starts with «сделай напоминание …» return the «...» body.

    Returns ``None`` if the prefix does not match.
    Returns an empty string if the prefix is present but the body is empty
    («напомни») — the caller then asks the user what to remind.
    """
    if not text:
        return None
    m = EXPLICIT_REMIND_PREFIX_RE.match(text.strip())
    if m is None:
        return None
    return text.strip()[m.end():].strip()


# Структурная граница «дата ↔ текст» в идиоме
# «напомни <дата>[,] [что|чтобы|про] <текст>».
# Запятая / «что» / «чтобы» / «про» — разделитель: часть ДО = кандидат на
# дату-триггер, часть ПОСЛЕ = текст напоминания. Покрывает ведущую дату
# («Напомни 25 мая, что 1 июня экзамен»), которую tail-search не видит.
_IDIOM_BOUNDARY_RE = re.compile(
    r",|\bчто\b|\bчтобы\b|\bчтоб\b|\bпро\b",
    re.IGNORECASE,
)
# Связки в начале текста-остатка — срезаем («что 1 июня…» → «1 июня…»).
_TAIL_LEAD_RE = re.compile(r"^(?:что|чтобы|чтоб|про)\b\s*", re.IGNORECASE)


def _try_leading_date_idiom(
    args: str, user_tz: str,
) -> tuple[str, str] | None:
    """«напомни <дата>[,] [что|про] <текст>» → ``(text, date)`` или None.

    Дата стоит ПЕРЕД структурной границей (запятая/«что»/«про»). При двух
    датах ПЕРВАЯ (до границы) = триггер, вторая остаётся в тексте события.
    Принимаем head как дату при OK/IN_PAST/NEEDS_HOUR (голая дата без часа —
    тоже дата, час спросят downstream).
    """
    from bot.services.nl_date import ParseStatus, parse

    m = _IDIOM_BOUNDARY_RE.search(args)
    if m is None:
        return None
    head = args[: m.start()].strip().strip(",.;:").strip()
    tail = _TAIL_LEAD_RE.sub("", args[m.end():].strip()).strip()
    if not head or not tail:
        return None
    result = parse(head, user_tz=user_tz)
    if result.status in (
        ParseStatus.OK, ParseStatus.IN_PAST, ParseStatus.NEEDS_HOUR,
    ):
        return tail, head
    return None


def split_remind_text_and_time(
    args: str, user_tz: str = DEFAULT_TZ,
) -> tuple[str, str | None]:
    """Split /remind args into (reminder text, time part).

    Strategy (по убыванию приоритета):
    1. Front-date idiom «<дата>[,] [что|про] <текст>» — дата в НАЧАЛЕ
       со структурной границей (см. ``_try_leading_date_idiom``).
    2. Весь ввод — дата без текста («25 мая», «завтра») → ("", args).
    3. Tail-search: последние 1-7 токенов как время; если OK — это время,
       остальное текст. Дата в КОНЦЕ.
    4. Leading-search: первые 7..1 токенов как время БЕЗ разделителя
       («сегодня вечером доделать ивенторус»). Жадно к большему окну.
    5. Ничего не распознано → весь ввод это текст, time=None.

    Returns ``(text, time_part_or_None)``.
    """
    from bot.services.nl_date import ParseStatus, parse

    args = args.strip()
    if not args:
        return "", None

    # 1. Ведущая дата по структурной границе (запятая/«что»/«про»).
    idiom = _try_leading_date_idiom(args, user_tz)
    if idiom is not None:
        return idiom

    # 2. Весь args — это дата БЕЗ текста («25 мая», «завтра»)? Тогда
    # ("", args) — пустой текст сигналит «дата-only» (caller спросит «про
    # что?»). Без этого tail-search фрагментирует «25 мая» → («25»,«мая»).
    whole = parse(args, user_tz=user_tz)
    if whole.status in (
        ParseStatus.OK, ParseStatus.IN_PAST, ParseStatus.NEEDS_HOUR,
    ):
        return "", args

    tokens = args.split()
    n = len(tokens)

    # Heuristic: try a LARGER window from the end (5..1 tokens).
    # OK / IN_PAST / NEEDS_HOUR считаем «совпадением времени»: «вчера в 9»
    # (3 токена) иначе скипается т.к. «в 9» парсится OK первым. NEEDS_HOUR —
    # голая дата в хвосте («купить хлеб завтра»): время-часть = «завтра»,
    # downstream спросит час. IN_PAST ловится в cmd_remind с понятным текстом.
    valid_statuses = (
        ParseStatus.OK, ParseStatus.IN_PAST, ParseStatus.NEEDS_HOUR,
    )
    for window in range(min(7, n), 0, -1):
        time_part = " ".join(tokens[n - window:])
        text_part = " ".join(tokens[: n - window])
        result = parse(time_part, user_tz=user_tz)
        if result.status in valid_statuses and text_part:
            return text_part.strip(), time_part.strip()

    # 4. Leading-search БЕЗ структурной границы: время в НАЧАЛЕ, действие в
    # конце («сегодня вечером доделать ивенторус», «через час купить хлеб»).
    # Покрывает кейс, когда idiom не сработал (нет «,/что/про») и tail-search
    # не нашёл (последние токены — слова действия). Жадно: больше окно вперёд,
    # чтобы «завтра в 9 утра позвонить маме» взяло всё время-выражение.
    for window in range(min(7, n), 0, -1):
        time_part = " ".join(tokens[:window])
        text_part = " ".join(tokens[window:])
        result = parse(time_part, user_tz=user_tz)
        if result.status in valid_statuses and text_part:
            return text_part.strip(), time_part.strip()

    # 5. Middle-search: время в СЕРЕДИНЕ фразы («Нужно завтра в 9 пойти на
    #    футбол» — по краям текст, время посередине). Срабатывает ТОЛЬКО когда
    #    idiom/whole/tail/leading не нашли: время не в начале (i>0) и не в
    #    конце (j<n). Это ОБЩЕЕ решение вместо череды частных случаев: берём
    #    самый длинный contiguous-спан, парсящийся как время; текст = всё до и
    #    после спана. O(n·7) parse-вызовов — окно времени ограничено 7 токенами.
    best: tuple[int, int, int] | None = None  # (window, i, j)
    max_win = min(7, n)
    for i in range(1, n):  # i==0 — это leading (уже пробовали)
        for window in range(min(max_win, n - i), 0, -1):
            j = i + window
            if j >= n:
                continue  # j==n — это tail (уже пробовали)
            result = parse(" ".join(tokens[i:j]), user_tz=user_tz)
            if result.status in valid_statuses:
                text_part = " ".join(tokens[:i] + tokens[j:]).strip()
                if text_part and (best is None or window > best[0]):
                    best = (window, i, j)
                break  # для данного i нашли самое длинное валидное окно
    if best is not None:
        _, bi, bj = best
        return (
            " ".join(tokens[:bi] + tokens[bj:]).strip(),
            " ".join(tokens[bi:bj]).strip(),
        )

    # No time found — whole input is text.
    return args, None
