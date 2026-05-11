"""
Spike: progress UI variants for long-running bot operations.

Tests 4 ways of showing "bot is working" feedback:
  /progress_a  — multi-step status message with edits ("Расшифровываю..." → "Анализирую..." → "Готово")
  /progress_b  — chat action loop (typing/record_voice) + final message
  /progress_c  — sendMessageDraft streaming chunks (Bot API 10.0)
  /progress_d  — combo: chat action + status edits (recommended in most bots)

Each simulates an ~8-second pipeline: STT 4s → classify 2s → embed 1s → save 1s.

USAGE:
    1. STOP main dev bot (only one polling per token)
    2. python tools/spike_progress_ui.py
    3. In Telegram, send /progress_help → /progress_a etc.

Compare visually which feels best, then we integrate winner into bot/handlers.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN not in .env")
    sys.exit(1)

API = f"https://api.telegram.org/bot{TOKEN}"


async def call(method: str, **params: Any) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{API}/{method}", json=params)
            data = r.json()
            if not data.get("ok"):
                print(f"  API ERROR [{method}]: {data.get('description')!r} (code={data.get('error_code')})")
            return data
    except Exception as e:
        print(f"  HTTP ERROR [{method}]: {type(e).__name__}: {e}")
        return {"ok": False}


# ─── Variants ────────────────────────────────────────────────────


async def variant_a_status_edits(chat_id: int) -> None:
    """A: Send status message, edit it through pipeline phases."""
    # Initial status
    r = await call("sendMessage", chat_id=chat_id, text="🎙 Расшифровываю голосовое...")
    if not r.get("ok"):
        return
    msg_id = r["result"]["message_id"]

    await asyncio.sleep(4)  # STT phase
    await call("editMessageText", chat_id=chat_id, message_id=msg_id, text="🧠 Анализирую содержимое...")

    await asyncio.sleep(2)  # classify
    await call("editMessageText", chat_id=chat_id, message_id=msg_id, text="🏷 Подбираю теги...")

    await asyncio.sleep(1)  # embed
    await call("editMessageText", chat_id=chat_id, message_id=msg_id, text="💾 Сохраняю...")

    await asyncio.sleep(1)  # save
    await call(
        "editMessageText",
        chat_id=chat_id,
        message_id=msg_id,
        text="✅ Сохранено #идеи #проект (8 сек)",
    )


async def variant_b_chat_action(chat_id: int) -> None:
    """B: Loop sendChatAction every 4s (Telegram timeout), then final message."""
    stop = False

    async def keep_typing():
        while not stop:
            await call("sendChatAction", chat_id=chat_id, action="typing")
            await asyncio.sleep(4)  # action expires after 5s, refresh before

    typing_task = asyncio.create_task(keep_typing())
    try:
        await asyncio.sleep(8)  # simulate full pipeline
    finally:
        stop = True
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass

    await call("sendMessage", chat_id=chat_id, text="✅ Сохранено #идеи #проект (8 сек)")


async def variant_c_send_message_draft(chat_id: int) -> None:
    """C: sendMessageDraft streaming chunks (Bot API 10.0)."""
    chunks = [
        "✅ Сохранено\n\n",
        "📝 Содержание: ",
        "это голосовая заметка о новой идее ",
        "для продукта, связанной с механизмом рекомендаций ",
        "на основе контекста.\n\n",
        "🏷 Теги: #идеи #продукт #рекомендации\n",
        "📌 Тип: Идея (high confidence)\n",
        "⏱ Обработано за 8 сек",
    ]

    msg_id = None
    accumulated = ""
    for i, chunk in enumerate(chunks):
        accumulated += chunk
        is_final = i == len(chunks) - 1
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": accumulated,
        }
        if msg_id is not None:
            params["message_id"] = msg_id
        # Try sendMessageDraft (Bot API 10.0)
        r = await call("sendMessageDraft", **params)
        if not r.get("ok"):
            # Fallback: use sendMessage / editMessageText loop
            print(f"  sendMessageDraft failed, falling back to edit loop")
            if msg_id is None:
                r = await call("sendMessage", chat_id=chat_id, text=accumulated)
                if r.get("ok"):
                    msg_id = r["result"]["message_id"]
            else:
                await call("editMessageText", chat_id=chat_id, message_id=msg_id, text=accumulated)
        else:
            if msg_id is None:
                msg_id = r["result"]["message_id"]
        await asyncio.sleep(1.0)


async def variant_d_combo(chat_id: int) -> None:
    """D: chat action + status edits (recommended)."""
    # Start chat action loop
    stop = False

    async def keep_typing():
        while not stop:
            await call("sendChatAction", chat_id=chat_id, action="typing")
            await asyncio.sleep(4)

    typing_task = asyncio.create_task(keep_typing())

    try:
        # Status message
        r = await call("sendMessage", chat_id=chat_id, text="🎙 Расшифровываю голосовое...")
        if not r.get("ok"):
            return
        msg_id = r["result"]["message_id"]

        await asyncio.sleep(4)
        await call("editMessageText", chat_id=chat_id, message_id=msg_id, text="🧠 Анализирую содержимое...")
        await asyncio.sleep(2)
        await call("editMessageText", chat_id=chat_id, message_id=msg_id, text="🏷 Подбираю теги...")
        await asyncio.sleep(1)
        await call("editMessageText", chat_id=chat_id, message_id=msg_id, text="💾 Сохраняю...")
        await asyncio.sleep(1)
        await call(
            "editMessageText",
            chat_id=chat_id,
            message_id=msg_id,
            text="✅ Сохранено #идеи #проект (8 сек)",
        )
    finally:
        stop = True
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


# ─── Dispatcher ──────────────────────────────────────────────────


async def handle_message(msg: dict) -> None:
    text = msg.get("text", "") or ""
    chat_id = msg["chat"]["id"]
    user = msg.get("from", {})

    print(f"\n>>> {user.get('first_name', '?')} ({user.get('id')}) chat={chat_id}: {text!r}")

    if not text.startswith("/progress"):
        return

    cmd = text.split()[0]

    if cmd == "/progress_help":
        help_text = (
            "Variants of progress UI feedback:\n\n"
            "/progress_a — status message with edits\n"
            "    (clean, shows pipeline phases)\n\n"
            "/progress_b — chat action loop (typing)\n"
            "    (Telegram standard, minimal)\n\n"
            "/progress_c — sendMessageDraft streaming\n"
            "    (Bot API 10.0, real streaming)\n\n"
            "/progress_d — combo: typing + status edits\n"
            "    (recommended for most bots)\n\n"
            "Send each. Compare which feels best."
        )
        await call("sendMessage", chat_id=chat_id, text=help_text)

    elif cmd == "/progress_a":
        print("  Running variant A: status message with edits")
        await variant_a_status_edits(chat_id)
        print("  Done A")

    elif cmd == "/progress_b":
        print("  Running variant B: chat action loop")
        await variant_b_chat_action(chat_id)
        print("  Done B")

    elif cmd == "/progress_c":
        print("  Running variant C: sendMessageDraft streaming")
        await variant_c_send_message_draft(chat_id)
        print("  Done C")

    elif cmd == "/progress_d":
        print("  Running variant D: combo (typing + edits)")
        await variant_d_combo(chat_id)
        print("  Done D")


async def main() -> None:
    print("=" * 60)
    print("Spike: progress UI variants")
    print("=" * 60)

    me = await call("getMe")
    if not me.get("ok"):
        print(f"FAIL getMe: {me}")
        return
    bot_info = me["result"]
    print(f"Bot: @{bot_info.get('username')} ({bot_info.get('first_name')})")
    print()
    print(f"Send /progress_help in Telegram to start.")
    print("Ctrl+C to stop.")
    print("=" * 60)

    offset = 0
    while True:
        try:
            r = await call("getUpdates", offset=offset, timeout=25, allowed_updates=["message"])
            if r.get("ok"):
                for update in r["result"]:
                    offset = update["update_id"] + 1
                    msg = update.get("message")
                    if msg:
                        try:
                            await handle_message(msg)
                        except Exception as e:
                            print(f"  HANDLER ERROR: {type(e).__name__}: {e}")
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\nStopping...")
            break
        except Exception as e:
            print(f"  POLL ERROR: {type(e).__name__}: {e}")
            await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
