"""Канонический рендер списка задач — ОДИН источник для бота и воркера.

Раньше текст списка дублировался вербатим в bot/handlers/tasks/shared.py и
backend/app/services/task_list_renderer.py (синхронизация вручную → дрейф).
Теперь оба делегируют сюда. Порядок — канон: reply → заголовок → тело → доп.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from shared.messages import compose, reply_hint_compact

# Нейтральная шапка без AI-заголовка (он галлюцинирует и добавляет шум).
# Список опознаётся по чекбоксам; общий срок дописывается отдельно.
LIST_HEADER = "📋 <b>Список</b>"

# reply-подсказка списка — единый стиль из kit, в каноне ПЕРВОЙ строкой.
_REPLY_HINT = reply_hint_compact("изменить список")
# Доп-подсказка с примерами — в silent-режиме (reply = единственный путь правки).
_EXAMPLES = "<i>Например: «закрой 1, 3» · «добавь хлеб» · «удали 2»</i>"


def _header_with_deadline(structured_data: dict) -> str:
    header = LIST_HEADER
    cd = structured_data.get("common_deadline")
    if cd:
        try:
            dt = datetime.fromisoformat(cd)
            tag = (
                dt.strftime("%d.%m") if dt.hour == 0 and dt.minute == 0
                else dt.strftime("%d.%m %H:%M")
            )
            header += f"  <i>⏰ {tag}</i>"
        except Exception:
            pass
    return header


def _items_block(tasks: list[dict]) -> tuple[str, int]:
    lines: list[str] = []
    for i, t in enumerate(tasks, start=1):
        check = "✅" if t.get("done") else "☐"
        # HTML-escape: текст пункта идёт в parse_mode=HTML; «A < B», «C++»,
        # «A&B» иначе ломают разметку (TelegramBadRequest) или инжектят теги.
        text = escape(t.get("text", "") or "")
        dl_tag = ""
        deadline = t.get("deadline")
        if deadline:
            try:
                dt = datetime.fromisoformat(deadline)
                _fmt = "%d.%m" if dt.hour == 0 and dt.minute == 0 else "%d.%m %H:%M"
                dl_tag = f" · <i>⏰ {dt.strftime(_fmt)}</i>"
            except Exception:
                pass
        if t.get("done"):
            lines.append(f"{check} <s>{i}. {text}</s>{dl_tag}")
        else:
            lines.append(f"{check} {i}. {text}{dl_tag}")
        note = t.get("note")
        if note:
            lines.append(f"   <i>↳ {escape(str(note))}</i>")
    done = sum(1 for t in tasks if t.get("done"))
    return "\n".join(lines), done


def render_task_list(title: str | None, structured_data: dict, *, silent: bool = False) -> str:
    """HTML-текст списка задач в каноническом порядке.

    ``title`` игнорируется намеренно (нейтральная шапка — AI-заголовок шумит).
    ``silent=True`` добавляет блок примеров (reply — единственный способ правки
    без кнопок).
    """
    tasks = structured_data.get("tasks", [])
    header = _header_with_deadline(structured_data)
    extra = _EXAMPLES if silent else None

    if not tasks:
        return compose(_REPLY_HINT, header, "<i>Нет задач</i>", extra)

    body, done = _items_block(tasks)
    status = f"<i>Выполнено: {done} из {len(tasks)}</i>" if done > 0 else None
    return compose(_REPLY_HINT, header, body, status, extra)
