"""
Spike: Bot API 10.0 — topics in private DM with bot.

Standalone polling script. Does NOT touch bot/ codebase.
Uses raw HTTPS calls to Telegram Bot API (no aiogram version dependency).

USAGE:
    1. STOP main dev bot (it holds polling lock — only one per token):
       (close BB Bot window or `taskkill /f /im python.exe` carefully)
    2. python tools/spike_dm_topics.py
    3. Open Telegram, find @bookmarkbrain_dev_bot
    4. Send /spike_help — see commands

Commands available in Telegram:
    /spike_status                  — bot info + chat info (is_forum?)
    /spike_create <name>           — createForumTopic
    /spike_send <topic_id> <text>  — sendMessage with message_thread_id
    /spike_list                    — list topics created this session
    /spike_delete <topic_id>       — deleteForumTopic
    /spike_cleanup                 — delete all topics this session

After spike — Ctrl+C to stop, restart main bot via start.bat or run/bot.bat.
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
    print("ERROR: TELEGRAM_BOT_TOKEN not found in .env")
    sys.exit(1)

API = f"https://api.telegram.org/bot{TOKEN}"

# Session state
created_topics: dict[int, dict] = {}  # message_thread_id -> {name, chat_id}


async def call(method: str, **params: Any) -> dict[str, Any]:
    """Call Telegram Bot API method via HTTPS POST."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{API}/{method}", json=params)
            data = r.json()
            if not data.get("ok"):
                print(f"  API ERROR [{method}]: {data.get('description')!r} (code={data.get('error_code')})")
            return data
    except Exception as e:
        print(f"  HTTP ERROR [{method}]: {type(e).__name__}: {e}")
        return {"ok": False, "description": str(e)}


def _short_json(data: Any, limit: int = 600) -> str:
    s = json.dumps(data, ensure_ascii=False, indent=2)
    return s if len(s) <= limit else s[:limit] + "... [truncated]"


async def handle_message(msg: dict) -> None:
    text = msg.get("text", "") or ""
    chat = msg.get("chat", {})
    chat_id = chat["id"]
    user = msg.get("from", {})
    thread_id = msg.get("message_thread_id")
    is_topic = msg.get("is_topic_message")

    log_prefix = f">>> {user.get('first_name', '?')} ({user.get('id')}) chat={chat_id}"
    if thread_id:
        log_prefix += f" thread={thread_id}"
    if is_topic:
        log_prefix += " is_topic_message=True"
    print(f"\n{log_prefix}: {text!r}")

    if not text.startswith("/spike_"):
        return

    parts = text.split(maxsplit=2)
    cmd = parts[0]

    if cmd == "/spike_help":
        help_text = (
            "Spike commands:\n"
            "/spike_status\n"
            "/spike_create <name>\n"
            "/spike_send <topic_id> <text>\n"
            "/spike_list\n"
            "/spike_delete <topic_id>\n"
            "/spike_cleanup"
        )
        await call("sendMessage", chat_id=chat_id, text=help_text)

    elif cmd == "/spike_status":
        me = await call("getMe")
        chat_info = await call("getChat", chat_id=chat_id)
        bot_user = me.get("result", {})
        chat_data = chat_info.get("result", {})
        info = (
            f"bot: @{bot_user.get('username')}\n"
            f"chat_id: {chat_id}\n"
            f"chat type: {chat_data.get('type')}\n"
            f"is_forum: {chat_data.get('is_forum')}\n"
            f"has_topics: {chat_data.get('has_topics')}\n"
            f"---raw chat---\n{_short_json(chat_data)}"
        )
        print(info)
        await call("sendMessage", chat_id=chat_id, text=info[:4000])

    elif cmd == "/spike_create":
        if len(parts) < 2:
            await call("sendMessage", chat_id=chat_id, text="usage: /spike_create <name>")
            return
        name = parts[1]
        result = await call("createForumTopic", chat_id=chat_id, name=name)
        if result.get("ok"):
            topic = result["result"]
            tid = topic.get("message_thread_id")
            created_topics[tid] = {"name": name, "chat_id": chat_id}
            print(f"  CREATED topic id={tid} name={name!r}")
            print(f"  raw: {_short_json(topic)}")
            await call(
                "sendMessage",
                chat_id=chat_id,
                text=f"OK: created topic '{name}' id={tid}\n{_short_json(topic)}",
            )
        else:
            await call(
                "sendMessage",
                chat_id=chat_id,
                text=f"FAIL createForumTopic: {result.get('description')}\nfull: {_short_json(result)}",
            )

    elif cmd == "/spike_send":
        if len(parts) < 3:
            await call("sendMessage", chat_id=chat_id, text="usage: /spike_send <topic_id> <text>")
            return
        try:
            tid = int(parts[1])
        except ValueError:
            await call("sendMessage", chat_id=chat_id, text="topic_id must be int")
            return
        body = parts[2]
        result = await call(
            "sendMessage",
            chat_id=chat_id,
            message_thread_id=tid,
            text=f"[from spike] {body}",
        )
        if not result.get("ok"):
            await call(
                "sendMessage",
                chat_id=chat_id,
                text=f"FAIL sendMessage: {result.get('description')}",
            )

    elif cmd == "/spike_list":
        if not created_topics:
            await call("sendMessage", chat_id=chat_id, text="(no topics created in this session)")
        else:
            lines = [f"{tid}: {info['name']}" for tid, info in created_topics.items()]
            await call("sendMessage", chat_id=chat_id, text="Topics:\n" + "\n".join(lines))

    elif cmd == "/spike_delete":
        if len(parts) < 2:
            await call("sendMessage", chat_id=chat_id, text="usage: /spike_delete <topic_id>")
            return
        try:
            tid = int(parts[1])
        except ValueError:
            await call("sendMessage", chat_id=chat_id, text="topic_id must be int")
            return
        result = await call("deleteForumTopic", chat_id=chat_id, message_thread_id=tid)
        if result.get("ok"):
            created_topics.pop(tid, None)
            await call("sendMessage", chat_id=chat_id, text=f"Deleted topic {tid}")
        else:
            await call(
                "sendMessage",
                chat_id=chat_id,
                text=f"FAIL deleteForumTopic: {result.get('description')}",
            )

    elif cmd == "/spike_cleanup":
        deleted = 0
        failed = 0
        for tid in list(created_topics.keys()):
            r = await call("deleteForumTopic", chat_id=chat_id, message_thread_id=tid)
            if r.get("ok"):
                deleted += 1
                created_topics.pop(tid, None)
            else:
                failed += 1
        await call(
            "sendMessage",
            chat_id=chat_id,
            text=f"Cleanup: deleted={deleted} failed={failed}",
        )


async def main() -> None:
    print("=" * 60)
    print("Spike: Bot API 10.0 — DM topics test")
    print("=" * 60)

    me = await call("getMe")
    if not me.get("ok"):
        print(f"FAIL getMe: {me}")
        print("\nIs main bot still running? Stop it first (only one polling per token).")
        return
    bot_info = me["result"]
    print(f"Bot: @{bot_info.get('username')} ({bot_info.get('first_name')})")
    print(f"Bot id: {bot_info.get('id')}")
    print()
    print("Now open Telegram -> @{username} -> send /spike_help".format(username=bot_info.get("username")))
    print("Ctrl+C to stop.")
    print("=" * 60)

    offset = 0
    while True:
        try:
            r = await call(
                "getUpdates",
                offset=offset,
                timeout=25,
                allowed_updates=["message"],
            )
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
            print("\nStopping spike...")
            break
        except Exception as e:
            print(f"  POLL ERROR: {type(e).__name__}: {e}")
            await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
