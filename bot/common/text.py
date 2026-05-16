"""Text-safety helpers shared across bot feature packages.

Public, dependency-free utilities. Anything here must stay domain-agnostic
(no aiogram handlers, no API calls) so every feature package can depend on
``bot.common`` without creating lateral feature-to-feature coupling.
"""
from __future__ import annotations

import html


def safe(s: str | None) -> str:
    """HTML-escape user text for embedding into ``parse_mode="HTML"``.

    Telegram HTML mode allows ``<a> <b> <i> <code> <pre>`` — without
    escaping a user could inject ``<a href="tg://...">`` (security).
    """
    return html.escape(s or "", quote=False)
