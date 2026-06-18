"""
Spike: Rich Messages (Bot API 10.1, sendRichMessage) — рендер-тест ПЕРЕД интеграцией.

Telegram 11.06.2026 добавил Rich Messages — формат с заголовками, списками,
чекбокс-пунктами, таблицами, цитатами, разворачивающимися блоками. aiogram 3.29
дал типы (InputRichMessage / RichBlock* / RichText*), но это bleeding-edge:
клиенты могут рендерить с багами. Поэтому СНАЧАЛА смотрим как это выглядит у тебя
на телефоне/десктопе, и только потом решаем — вшивать в реальные хендлеры или нет.

Каждая команда шлёт ДВА сообщения: «СЕЙЧАС» (текущий формат бота) и «RICH»
(тот же контент через sendRichMessage) — чтобы сравнить бок о бок.

USAGE:
    1. ОСТАНОВИ основной бот (один polling на токен): stop.bat
    2. python tools/spike_rich_message.py
    3. В Telegram отправь боту: /rich_help
    4. Прогони /rich_all — пришлёт всё. Посмотри как рисует у тебя.
    5. Скажи вердикт: что выглядит лучше текущего, что сломано/не рисуется.

NB: sendRichMessage работает через серверный Bot API напрямую (raw HTTP) —
    версия aiogram тут не важна, важно что Telegram выкатил метод серверно.
"""
from __future__ import annotations

import asyncio
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


async def label(chat_id: int, text: str) -> None:
    """Серый разделитель-подпись между вариантами."""
    await call("sendMessage", chat_id=chat_id, text=f"— — — {text} — — —")


async def send_plain(chat_id: int, text: str) -> None:
    await call(
        "sendMessage",
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def send_rich(chat_id: int, *, markdown: str | None = None, html: str | None = None) -> None:
    """sendRichMessage с авто-fallback markdown→html.

    Если markdown-диалект не тот и API ответит ошибкой — пробуем html,
    чтобы юзер всё равно увидел rich-рендер. Печатаем какой вариант прошёл.
    """
    if markdown is not None:
        body = {"markdown": markdown}
        r = await call("sendRichMessage", chat_id=chat_id, rich_message=body)
        if r.get("ok"):
            print("  rich OK (markdown)")
            return
        print("  markdown не прошёл → пробую html")
    if html is not None:
        r = await call("sendRichMessage", chat_id=chat_id, rich_message={"html": html})
        if r.get("ok"):
            print("  rich OK (html)")
            return
    print("  rich FAILED (см. API ERROR выше)")


# ─── Контент: текущие форматы (1:1 с кодом бота) ─────────────────

NOTE_PLAIN = (
    "✅ <b>Рекомендации по контексту пользователя</b>\n"
    "Категория: Продукт\n"
    "Голосовая заметка о механизме рекомендаций на основе контекста: "
    "что человек смотрел, сохранял и искал — из этого собираем подсказки.\n"
    "\n⏱ Обработано за 8.0 сек"
)

SEARCH_PLAIN = (
    'Результаты по запросу "<b>дизайн</b>" (12 найдено):\n\n'
    "1. <b>Гайд по сетке 8pt</b>\n"
    "Системный подход к вертикальному ритму и отступам в интерфейсах.\n"
    "<i>#дизайн #сетки</i>\n"
    '<a href="https://example.com/grid">Открыть</a>\n'
    "Релевантность: 87%\n\n"
    "2. <b>Цвет в продуктовом дизайне</b>\n"
    "Как строить доступные палитры и токены тем.\n"
    "<i>#дизайн #цвет</i>\n"
    '<a href="https://example.com/color">Открыть</a>\n'
    "Релевантность: 81%\n\n"
    "...и ещё 10. Уточни запрос для точных результатов."
)

TASKS_PLAIN = (
    "📋 <b>Список</b>  <i>⏰ 25.06</i>\n\n"
    "☐ 1. купить хлеб · <i>⏰ 25.06</i>\n"
    "☐ 2. позвонить маме\n"
    "   <i>↳ узнать про выходные</i>\n"
    "✅ <s>3. оплатить счёт</s>\n\n"
    "<i>Выполнено: 1 из 3</i>\n\n"
    "↩️ <i>Reply: закрыть · добавить · удалить пункт или список</i>"
)

# ─── Контент: Rich-версии того же самого ─────────────────────────

NOTE_RICH_MD = """# ✅ Рекомендации по контексту пользователя

> Голосовая заметка о механизме рекомендаций на основе контекста: что человек смотрел, сохранял и искал — из этого собираем подсказки.

**Категория:** Продукт
`#идеи` `#продукт` `#рекомендации`

---
_⏱ Обработано за 8.0 сек_
"""

NOTE_RICH_HTML = """<h1>✅ Рекомендации по контексту пользователя</h1>
<blockquote>Голосовая заметка о механизме рекомендаций на основе контекста: что человек смотрел, сохранял и искал — из этого собираем подсказки.</blockquote>
<p><b>Категория:</b> Продукт<br>#идеи #продукт #рекомендации</p>
<p><i>⏱ Обработано за 8.0 сек</i></p>"""

SEARCH_RICH_MD = """# 🔍 Поиск: «дизайн»
_Найдено 12_

## Гайд по сетке 8pt
Системный подход к вертикальному ритму и отступам в интерфейсах.
`#дизайн` `#сетки` · релевантность **87%** · [Открыть](https://example.com/grid)

## Цвет в продуктовом дизайне
Как строить доступные палитры и токены тем.
`#дизайн` `#цвет` · релевантность **81%** · [Открыть](https://example.com/color)

---
_…и ещё 10. Уточни запрос для точных результатов._
"""

SEARCH_RICH_HTML = """<h1>🔍 Поиск: «дизайн»</h1>
<p><i>Найдено 12</i></p>
<h2>Гайд по сетке 8pt</h2>
<p>Системный подход к вертикальному ритму и отступам в интерфейсах.<br>#дизайн #сетки · релевантность <b>87%</b> · <a href="https://example.com/grid">Открыть</a></p>
<h2>Цвет в продуктовом дизайне</h2>
<p>Как строить доступные палитры и токены тем.<br>#дизайн #цвет · релевантность <b>81%</b> · <a href="https://example.com/color">Открыть</a></p>
<p><i>…и ещё 10. Уточни запрос для точных результатов.</i></p>"""

# Главная фишка для списков: чекбокс-пункты нативно (display-only)
TASKS_RICH_MD = """# 📋 Список  ⏰ 25.06

- [ ] купить хлеб  ⏰ 25.06
- [ ] позвонить маме — узнать про выходные
- [x] оплатить счёт

_Выполнено: 1 из 3_
"""

TASKS_RICH_HTML = """<h1>📋 Список ⏰ 25.06</h1>
<ul>
<li>☐ купить хлеб ⏰ 25.06</li>
<li>☐ позвонить маме — <i>узнать про выходные</i></li>
<li>✅ <s>оплатить счёт</s></li>
</ul>
<p><i>Выполнено: 1 из 3</i></p>"""

# Kitchen sink: прогоняем ВСЕ возможности формата за раз
KITCHEN_MD = """# Заголовок H1
## Заголовок H2
### Заголовок H3

Абзац с **жирным**, *курсивом*, ~~зачёркнутым~~, `моноширинным` и ||спойлером||.

Маркированный список:
- Первый пункт
- Второй пункт
  - Вложенный

Нумерованный:
1. Раз
2. Два

Чекбоксы:
- [ ] Не сделано
- [x] Сделано

> Цитата (blockquote)

---

| Колонка A | Колонка B |
| --- | --- |
| значение 1 | значение 2 |
| значение 3 | значение 4 |

```
def hello():
    return "world"
```
"""

KITCHEN_HTML = """<h1>Заголовок H1</h1>
<h2>Заголовок H2</h2>
<h3>Заголовок H3</h3>
<p>Абзац с <b>жирным</b>, <i>курсивом</i>, <s>зачёркнутым</s>, <code>моноширинным</code> и <span class="tg-spoiler">спойлером</span>.</p>
<ul><li>Первый</li><li>Второй</li></ul>
<blockquote>Цитата blockquote</blockquote>
<details><summary>Развернуть подробности</summary>Скрытый контент внутри details-блока — раскрывается по тапу.</details>
<pre><code>def hello():
    return "world"</code></pre>"""


# ─── Сценарии ────────────────────────────────────────────────────


async def scenario_note(chat_id: int) -> None:
    await label(chat_id, "КАРТОЧКА ЗАМЕТКИ · СЕЙЧАС")
    await send_plain(chat_id, NOTE_PLAIN)
    await asyncio.sleep(0.4)
    await label(chat_id, "КАРТОЧКА ЗАМЕТКИ · RICH")
    await send_rich(chat_id, markdown=NOTE_RICH_MD, html=NOTE_RICH_HTML)


async def scenario_search(chat_id: int) -> None:
    await label(chat_id, "ПОИСК · СЕЙЧАС")
    await send_plain(chat_id, SEARCH_PLAIN)
    await asyncio.sleep(0.4)
    await label(chat_id, "ПОИСК · RICH")
    await send_rich(chat_id, markdown=SEARCH_RICH_MD, html=SEARCH_RICH_HTML)


async def scenario_tasks(chat_id: int) -> None:
    await label(chat_id, "СПИСОК ЗАДАЧ · СЕЙЧАС")
    await send_plain(chat_id, TASKS_PLAIN)
    await asyncio.sleep(0.4)
    await label(chat_id, "СПИСОК ЗАДАЧ · RICH (нативные чекбоксы)")
    await send_rich(chat_id, markdown=TASKS_RICH_MD, html=TASKS_RICH_HTML)


async def scenario_kitchen(chat_id: int) -> None:
    await label(chat_id, "KITCHEN SINK · markdown")
    await send_rich(chat_id, markdown=KITCHEN_MD)
    await asyncio.sleep(0.4)
    await label(chat_id, "KITCHEN SINK · html (+ details/collapsible)")
    await send_rich(chat_id, html=KITCHEN_HTML)


# ─── Диспетчер ───────────────────────────────────────────────────

HELP = (
    "Rich Messages — рендер-тест (Bot API 10.1)\n\n"
    "/rich_kitchen — все возможности формата (заголовки, списки,\n"
    "    чекбоксы, таблица, цитата, код, details)\n"
    "/rich_note    — карточка заметки: сейчас vs rich\n"
    "/rich_search  — результаты поиска: сейчас vs rich\n"
    "/rich_tasks   — список задач: сейчас vs rich (чекбоксы)\n"
    "/rich_all     — прогнать всё подряд\n\n"
    "Смотри как рисует у тебя. Что лучше текущего — вшиваем."
)


async def handle_message(msg: dict) -> None:
    text = msg.get("text", "") or ""
    chat_id = msg["chat"]["id"]
    user = msg.get("from", {})
    print(f"\n>>> {user.get('first_name', '?')} ({user.get('id')}) chat={chat_id}: {text!r}")

    if not text.startswith("/rich"):
        return
    cmd = text.split()[0]

    if cmd == "/rich_help":
        await call("sendMessage", chat_id=chat_id, text=HELP)
    elif cmd == "/rich_kitchen":
        print("  kitchen sink"); await scenario_kitchen(chat_id); print("  done")
    elif cmd == "/rich_note":
        print("  note"); await scenario_note(chat_id); print("  done")
    elif cmd == "/rich_search":
        print("  search"); await scenario_search(chat_id); print("  done")
    elif cmd == "/rich_tasks":
        print("  tasks"); await scenario_tasks(chat_id); print("  done")
    elif cmd == "/rich_all":
        print("  ALL")
        await scenario_kitchen(chat_id)
        await scenario_note(chat_id)
        await scenario_search(chat_id)
        await scenario_tasks(chat_id)
        print("  done ALL")


async def main() -> None:
    print("=" * 60)
    print("Spike: Rich Messages (sendRichMessage)")
    print("=" * 60)

    me = await call("getMe")
    if not me.get("ok"):
        print(f"FAIL getMe: {me}")
        return
    print(f"Bot: @{me['result'].get('username')}")
    print("Send /rich_help in Telegram. Ctrl+C to stop.")
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
