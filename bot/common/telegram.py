"""Telegram messaging helpers shared across feature packages."""
from __future__ import annotations

from aiogram.types import Message


async def send_ephemeral(
    message: Message, text: str, delay: float | None = None,
) -> None:
    """Send a plain (non-HTML) reply.

    Historically auto-deleted after ``delay`` seconds; that was removed —
    users need to see the bot answered even when it's a "didn't understand"
    reply (the old ephemerality made the bot look silent). ``delay`` is
    accepted but ignored, kept so the historic call sites stay untouched;
    behaviour is a single ``message.answer``.
    """
    await message.answer(text, parse_mode=None)
