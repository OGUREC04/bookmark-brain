"""Превью записи для dedup/merge-алертов — единый формат бот + воркер.

Правило (решение пользователя): любой алерт «уже есть похожее» показывает САМ
СОСТАВ записи, а не только заголовок:
- список: БЕЗ AI-заголовка (он шумит), полный состав чекбоксов + N/M;
- заметка: заголовок + содержание (3-4 строки ≈ 300 симв).
Напоминания дедупятся молча («👌 Уже напомню …»), отдельного алерта нет.

merge_diff_preview — GitHub-style дифф для «Объединить списки?»: текущие пункты
старого списка + что добавится из нового. Дубли по нормализованному тексту
пропускаются — зеркало backend `merge_task_lists`.

Лимиты (защита от Telegram 4096): не больше _MAX_ITEMS пунктов на блок, текст
пункта обрезается до _MAX_ITEM_LEN. Всё HTML-escape'ится (parse_mode=HTML).
"""
from __future__ import annotations

from html import escape

_MAX_ITEMS = 15
_MAX_ITEM_LEN = 70
_MAX_SUMMARY = 300


def _norm(text: str | None) -> str:
    return (text or "").strip().lower()


def _cap(text: str | None, limit: int = _MAX_ITEM_LEN) -> str:
    t = text or ""
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def _checkbox_lines(tasks: list, *, limit: int = _MAX_ITEMS, numbered: bool = True) -> list[str]:
    dicts = [t for t in tasks if isinstance(t, dict)]
    out: list[str] = []
    for i, t in enumerate(dicts[:limit], 1):
        check = "✅" if t.get("done") else "☐"
        prefix = f"{i}. " if numbered else ""
        out.append(f"{check} {prefix}{escape(_cap(t.get('text', '')))}")
    extra = len(dicts) - min(len(dicts), limit)
    if extra > 0:
        out.append(f"<i>…и ещё {extra}</i>")
    return out


def dup_preview(
    *,
    title: str | None = None,
    summary: str | None = None,
    structured_data: dict | None = None,
) -> str:
    """Превью существующей записи для dedup-алерта — по типу.

    Непустой список → без заголовка, полный состав. Иначе (заметка ИЛИ пустой
    список) → заголовок + содержание.
    """
    sd = structured_data if isinstance(structured_data, dict) else {}
    tasks = (
        [t for t in (sd.get("tasks") or []) if isinstance(t, dict)]
        if sd.get("type") == "task_list" else []
    )
    if tasks:  # непустой список — показываем состав без AI-заголовка
        done = sum(1 for t in tasks if t.get("done"))
        head = f"📋 <b>Список</b> <i>({done}/{len(tasks)})</i>"
        return "\n".join([head, *_checkbox_lines(tasks)])
    # Заметка (или пустой список): заголовок + содержание 3-4 строки.
    t = escape((title or "Без названия").strip())
    out = f"📖 <b>{t}</b>"
    body = (summary or "").strip()
    if body:
        out += "\n" + escape(body[:_MAX_SUMMARY])
    return out


def merge_diff_preview(
    old_structured: dict | None, new_structured: dict | None,
) -> str:
    """GitHub-style дифф объединения списков: текущие пункты + добавляемые.

    Дубли (по нормализованному тексту) не добавляются — как в backend merge.
    ``new_structured is None`` — состав нового списка недоступен (упал fetch):
    честно говорим об этом, а не показываем ложное «нечего добавлять».
    """
    new_unavailable = new_structured is None
    old = old_structured if isinstance(old_structured, dict) else {}
    new = new_structured if isinstance(new_structured, dict) else {}
    old_tasks = [t for t in (old.get("tasks") or []) if isinstance(t, dict)]
    new_tasks = [t for t in (new.get("tasks") or []) if isinstance(t, dict)]

    existing = {_norm(t.get("text")) for t in old_tasks if _norm(t.get("text"))}
    additions = [t for t in new_tasks if _norm(t.get("text")) and _norm(t.get("text")) not in existing]
    done = sum(1 for t in old_tasks if t.get("done"))

    lines = [f"<b>Сейчас в списке</b> <i>({done}/{len(old_tasks)})</i>:"]
    lines += _checkbox_lines(old_tasks, numbered=False)
    lines.append("")
    if new_unavailable:
        lines.append("<i>Состав нового списка временно недоступен — при объединении всё добавится.</i>")
    elif additions:
        lines.append(f"<b>Добавятся</b> <i>(+{len(additions)})</i>:")
        for t in additions[:_MAX_ITEMS]:
            lines.append(f"➕ {escape(_cap(t.get('text', '')))}")
        if len(additions) > _MAX_ITEMS:
            lines.append(f"<i>…и ещё {len(additions) - _MAX_ITEMS}</i>")
    else:
        lines.append("<i>Все пункты уже есть в списке — нового не добавится.</i>")
    return "\n".join(lines)
