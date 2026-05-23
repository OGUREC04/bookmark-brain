"""Общий рендерер task_list.

Используется воркером при первичной обработке — бот перерисовывает своим
рендерером (bot/handlers/tasks.py) при взаимодействии. Два рендерера ДОЛЖНЫ
выдавать одинаковый HTML + клавиатуру, иначе переключение между ними
визуально ломает сообщение.
"""
from __future__ import annotations

from datetime import datetime

# Нейтральная шапка без AI-заголовка: он галлюцинирует и добавляет шум.
# Список и так опознаётся по чекбоксам; общий срок дописывается отдельно.
LIST_HEADER = "📋 <b>Список</b>"

HINT_LINE = "💬 <i>Ответь на это сообщение чтобы изменить список</i>"
# Компактная подсказка — 2 строки: действия + примеры. Помещается под список,
# не плодит отдельных «Не понял»-сообщений для типовых случаев.
HINT_LINE_SILENT = (
    "↩️ <i>Reply: закрыть · добавить · удалить пункт или список</i>\n"
    "<i>Примеры: «закрой 1, 3» / «добавь хлеб» / «удали 2»</i>"
)


def _format_deadline_tag(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.hour == 0 and dt.minute == 0:
            return f" · <i>⏰ {dt.strftime('%d.%m')}</i>"
        return f" · <i>⏰ {dt.strftime('%d.%m %H:%M')}</i>"
    except Exception:
        return ""


def render_task_list_text(
    bookmark_title: str | None,
    structured_data: dict,
    duration_seconds: float | None = None,  # сохранён в сигнатуре для совместимости
    silent: bool = False,
) -> str:
    """HTML-текст для сообщения со списком задач.

    silent=True: без кнопок, подсказка про reply.
    silent=False: с кнопками (verbose, legacy).
    """
    tasks = structured_data.get("tasks", [])
    header = LIST_HEADER

    common_deadline = structured_data.get("common_deadline")
    if common_deadline:
        try:
            dt = datetime.fromisoformat(common_deadline)
            tag = (
                dt.strftime('%d.%m') if dt.hour == 0 and dt.minute == 0
                else dt.strftime('%d.%m %H:%M')
            )
            header += f"  <i>⏰ {tag}</i>"
        except Exception:
            pass

    hint = HINT_LINE_SILENT if silent else HINT_LINE

    lines = [header]
    if not tasks:
        lines.append("\n<i>Нет задач</i>")
        lines.append("")
        lines.append(hint)
        return "\n".join(lines)

    lines.append("")
    for i, t in enumerate(tasks, start=1):
        check = "✅" if t.get("done") else "☐"
        text = t.get("text", "")
        dl_tag = _format_deadline_tag(t.get("deadline"))
        if t.get("done"):
            lines.append(f"{check} <s>{i}. {text}</s>{dl_tag}")
        else:
            lines.append(f"{check} {i}. {text}{dl_tag}")
        note = t.get("note")
        if note:
            lines.append(f"   <i>↳ {note}</i>")

    done = sum(1 for t in tasks if t.get("done"))
    if done > 0:
        lines.append(f"\n<i>Выполнено: {done} из {len(tasks)}</i>")

    lines.append("")
    lines.append(hint)
    return "\n".join(lines)


def build_task_list_keyboard(bookmark_id: str, structured_data: dict) -> dict:
    """Клавиатура списка: чекбоксы + ряд [⏰ Срок] [🗑 Удалить].

    Добавление/удаление/редактирование пунктов — через reply на сообщение
    свободной фразой (NL-редактор). Кнопок для этого нет намеренно.

    Callback-префиксы:
      tg:{id}:{idx}  — toggle задачи
      tldm:{id}      — меню срока для всего списка
      td:{id}        — удалить список целиком
    """
    tasks = structured_data.get("tasks", [])
    rows: list[list[dict]] = []

    for i, t in enumerate(tasks[:15]):
        check = "✅" if t.get("done") else "☐"
        text = t.get("text", "")[:40]
        rows.append([
            {"text": f"{check} {text}", "callback_data": f"tg:{bookmark_id}:{i}"},
        ])

    rows.append([
        {"text": "⏰ Срок", "callback_data": f"tldm:{bookmark_id}"},
        {"text": "🗑 Удалить", "callback_data": f"td:{bookmark_id}"},
    ])

    return {"inline_keyboard": rows}


def build_list_deadline_menu(bookmark_id: str) -> dict:
    """Меню единого срока для всего списка."""
    return {
        "inline_keyboard": [
            [
                {"text": "Всё сегодня", "callback_data": f"tlds:{bookmark_id}:t"},
                {"text": "Всё завтра", "callback_data": f"tlds:{bookmark_id}:tm"},
            ],
            [
                {"text": "За неделю", "callback_data": f"tlds:{bookmark_id}:w"},
                {"text": "Убрать сроки", "callback_data": f"tlds:{bookmark_id}:n"},
            ],
            [{"text": "◀ Назад", "callback_data": f"tback:{bookmark_id}"}],
        ]
    }
