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


def split_remind_text_and_time(
    args: str, user_tz: str = DEFAULT_TZ,
) -> tuple[str, str | None]:
    """Split /remind args into (reminder text, time part).

    Strategy: try parsing the WHOLE thing as time — if ParseStatus.OK then
    there is no separate time. Otherwise search a time phrase from the end:
    the last 2-5 tokens go to the parser; if OK that is the time and the
    rest is text. If nothing parses, the whole input is text without time.

    Returns ``(text, time_part_or_None)``.
    """
    from bot.services.nl_date import ParseStatus, parse

    args = args.strip()
    if not args:
        return "", None

    tokens = args.split()
    n = len(tokens)

    # Heuristic: try a LARGER window from the end (5..1 tokens).
    # Count OK AND IN_PAST as a "time match" — otherwise «вчера в 9»
    # (3 tokens) is skipped because «в 9» (2 tokens) parses OK first.
    # IN_PAST is later caught in cmd_remind with a meaningful message.
    valid_statuses = (ParseStatus.OK, ParseStatus.IN_PAST)
    for window in range(min(5, n), 0, -1):
        time_part = " ".join(tokens[n - window:])
        text_part = " ".join(tokens[: n - window])
        result = parse(time_part, user_tz=user_tz)
        if result.status in valid_statuses and text_part:
            return text_part.strip(), time_part.strip()

    # No time found — whole input is text.
    return args, None
