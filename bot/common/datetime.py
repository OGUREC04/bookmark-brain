"""Timezone / fire-at formatting helpers shared across feature packages.

Domain-agnostic. ``get_user_tz_name`` takes the API client by parameter
rather than importing it, so this module has no upward dependency.
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Default timezone — used when users.timezone is empty or unparseable.
DEFAULT_TZ = "Europe/Moscow"

# Reply examples shown when asking the user for a full time (дата+час).
TIME_EXAMPLES = (
    "Примеры:\n"
    "• <code>через час</code>\n"
    "• <code>завтра в 9</code>\n"
    "• <code>в субботу в 18</code>\n"
    "• <code>15 мая</code>"
)

# Reply examples когда дата УЖЕ известна и нужен только ЧАС («во сколько?»).
# Примеры с датой («15 мая», «завтра») тут невалидны — спрашиваем время суток.
HOUR_EXAMPLES = (
    "Примеры:\n"
    "• <code>в 9</code>\n"
    "• <code>в 18:30</code>\n"
    "• <code>утром</code>\n"
    "• <code>вечером</code>"
)


async def get_user_tz_name(api, token: str) -> str:
    """IANA timezone name for the user. Falls back to ``DEFAULT_TZ`` when
    the field is empty or invalid. Returns a string — ``nl_date.parse()``
    validates via ZoneInfo internally."""
    try:
        user = await api.get_me(token)
        tz_name = (user or {}).get("timezone") or DEFAULT_TZ
    except Exception as e:
        logger.warning(f"get_user_tz_name: get_me failed, using {DEFAULT_TZ}: {e}")
        return DEFAULT_TZ
    try:
        ZoneInfo(tz_name)  # validate
        return tz_name
    except Exception:
        logger.warning(f"get_user_tz_name: invalid tz {tz_name!r}, fallback {DEFAULT_TZ}")
        return DEFAULT_TZ


def format_fire_at(fire_at: datetime, tz_name: str) -> str:
    """Localized «11.05 09:00» for user-facing confirmations."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_TZ)
    local = fire_at.astimezone(tz)
    return local.strftime("%d.%m %H:%M")
