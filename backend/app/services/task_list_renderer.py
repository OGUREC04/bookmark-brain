"""Общий рендерер task_list.

Используется воркером при первичной обработке — бот перерисовывает своим
рендерером (bot/handlers/tasks.py) при взаимодействии. Два рендерера ДОЛЖНЫ
выдавать одинаковый HTML + клавиатуру, иначе переключение между ними
визуально ломает сообщение.
"""
from __future__ import annotations

# Текст списка — ЕДИНЫЙ канонический источник в shared.task_list_render
# (раньше дублировался вербатим тут и в bot/handlers/tasks/shared.py).
# LIST_HEADER ре-экспортируется для обратной совместимости (тесты/импорты).
from shared.task_list_render import LIST_HEADER, render_task_list


def render_task_list_text(
    bookmark_title: str | None,
    structured_data: dict,
    duration_seconds: float | None = None,  # сохранён в сигнатуре для совместимости
    silent: bool = False,
) -> str:
    """Тонкий делегат к каноническому рендеру (см. shared.task_list_render)."""
    return render_task_list(bookmark_title, structured_data, silent=silent)


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
