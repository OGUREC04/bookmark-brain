"""Shared, domain-agnostic utilities for bot feature packages.

`bot.common` is the lowest bot layer: feature packages (handlers/*) and the
orchestration layer (start.py, main.py) may import from it, but it imports
from nothing inside `bot` except other `bot.common` submodules. This is the
seam that lets reminders / tasks / start share helpers WITHOUT importing
each other (no lateral feature coupling). Enforced by import-linter.

Public API only — no underscore-prefixed names are exported here.
"""
from __future__ import annotations

from .auth import ensure_user
from .datetime import (
    DEFAULT_TZ,
    HOUR_EXAMPLES,
    TIME_EXAMPLES,
    format_fire_at,
    get_user_tz_name,
)
from .nl import (
    EXPLICIT_REMIND_PREFIX_RE,
    extract_explicit_remind_body,
    split_remind_text_and_time,
)
from .telegram import send_ephemeral
from .text import safe

__all__ = [
    "DEFAULT_TZ",
    "EXPLICIT_REMIND_PREFIX_RE",
    "HOUR_EXAMPLES",
    "TIME_EXAMPLES",
    "ensure_user",
    "extract_explicit_remind_body",
    "format_fire_at",
    "get_user_tz_name",
    "safe",
    "send_ephemeral",
    "split_remind_text_and_time",
]
