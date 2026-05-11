"""NL-редактор task_list.

Применяет свободную фразу пользователя к текущему списку задач через LLM.
GigaChat получает текущий JSON + нумерованное текстовое представление + фразу,
возвращает НОВЫЙ JSON списка.

Все операции (add/remove/update/deadline/note/done) выражаются через разницу
старого и нового JSON — нам не надо их парсить отдельно.

ВАЖНО:
- Numbered text representation в user payload снижает мискаунт LLM на длинных
  списках (фикс bug 2026-05-11 «10 готово → 12 зачеркнут»).
- Post-validation отклоняет галлюцинации: «не готово / отмени / удали» не
  должны увеличивать длину списка (фикс bug 2026-05-11 «12 не готово → 13-й
  пункт»).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Ты — редактор списка задач. Получаешь текущий список (JSON + нумерованный текст) и фразу пользователя,
возвращаешь обновлённый JSON списка.

ПРАВИЛА:
- Не трогай пункты, о которых пользователь не упомянул.
- Нумерация в фразе пользователя — 1-based (задача №1 = индекс 0 в массиве).
- "добавь X", "+ X", "запиши X", "новый: X" — добавить в конец массива.
- "удали N", "убери N", "- N" — убрать пункт по номеру.
- "N готово", "сделано N", "✓ N", "сделал N", "закончил N", "гтв N" — выставить done=true (НЕ toggle).
- "N не готово", "отмени N", "верни N", "снять N", "открой N" — выставить done=false (ТОЛЬКО done, НЕ добавлять пункт).
- "всё готово", "закрой всё" — done=true для всех.
- "N: до <дата>", "N <дата>", "N — <дата>" — проставить deadline.
- "N = новый текст", "переименуй N в Y", "N: Y" — изменить text (но НЕ если это похоже на дедлайн).
- "к N: <описание>", "N — заметка: X" — проставить note.
- Даты → ISO YYYY-MM-DD. Сегодня = {today}. "завтра", "пятница", "через неделю" — вычисли.
- Время не указано → null в time-части.

КРИТИЧНО:
- Если фраза похожа на «N не готово» / «отмени N» — это снятие галки. НИКОГДА не добавляй пункт.
- Если фраза непонятна — верни список БЕЗ изменений. НЕ добавляй пункты "на всякий случай".
- Не выдумывай задачи, которых нет и о которых пользователь не просил.

ФОРМАТ ОТВЕТА — ТОЛЬКО JSON, без markdown, без пояснений:
{{"tasks": [{{"text": "...", "done": false, "deadline": null, "note": null}}, ...]}}

Каждый пункт ОБЯЗАТЕЛЬНО содержит поля text, done, deadline, note (null если нет).
"""


# Маркеры что фраза снимает галку / удаляет — НЕ может увеличивать список.
_NON_ADD_PHRASE_RE = re.compile(
    r"(?:"
    r"не\s+готов[оы]?|не\s+сделано?|"
    r"отмени|отменить|"
    r"верни|вернуть|снять|сними|открой|открыть|"
    r"удали|удалить|убери|убрать"
    r")",
    re.IGNORECASE,
)
# Маркеры что фраза добавляет пункт — длина может вырасти.
_ADD_PHRASE_RE = re.compile(
    r"(?:^|\W)(?:добав[ьитл]|запиши|записать|внеси|внести|новый|новая|новое|ещё|еще|плюс|\+)",
    re.IGNORECASE,
)
# Sanity-cap: одна фраза не может добавить >5 пунктов.
_MAX_LIST_GROWTH = 5


def _build_numbered_repr(tasks: list[dict]) -> str:
    """Нумерованное текстовое представление для LLM.

    Формат: «1. [ ] купить хлеб», «12. [x] резюме».
    Помогает LLM не мискаунтить на длинных списках.
    """
    lines: list[str] = []
    for i, t in enumerate(tasks, start=1):
        mark = "[x]" if t.get("done") else "[ ]"
        text = (t.get("text") or "").strip()
        lines.append(f"{i}. {mark} {text}")
    return "\n".join(lines)


def _validate_no_hallucinated_add(
    old_tasks: list[dict], new_tasks: list[dict], phrase: str,
) -> None:
    """Защита от LLM-галлюцинаций (фикс bug 2026-05-11).

    Raises NLEditError если:
    - фраза «не готово/отмени/удали» и список вырос
    - в фразе нет add-маркеров и список вырос
    - рост >MAX_LIST_GROWTH (sanity-cap)
    """
    growth = len(new_tasks) - len(old_tasks)
    if growth <= 0:
        return

    if growth > _MAX_LIST_GROWTH:
        raise NLEditError(
            f"LLM hallucination: list grew by {growth} (>{_MAX_LIST_GROWTH}), "
            f"phrase: {phrase!r}"
        )

    if _NON_ADD_PHRASE_RE.search(phrase):
        raise NLEditError(
            f"LLM hallucination: phrase {phrase!r} should not grow list, "
            f"but grew by {growth}"
        )

    if not _ADD_PHRASE_RE.search(phrase):
        raise NLEditError(
            f"LLM hallucination: phrase {phrase!r} has no add-marker, "
            f"but list grew by {growth}"
        )


class NLEditError(Exception):
    pass


async def apply_nl_edit(
    structured_data: dict,
    user_phrase: str,
) -> dict:
    """Применяет фразу пользователя к списку. Возвращает новый structured_data.

    Raises NLEditError если LLM не вернул валидный JSON или список.
    """
    settings = get_settings()

    tasks = structured_data.get("tasks", [])
    # Нормализуем: гарантируем все 4 поля
    norm_tasks = []
    for t in tasks:
        norm_tasks.append({
            "text": t.get("text", ""),
            "done": bool(t.get("done", False)),
            "deadline": t.get("deadline"),
            "note": t.get("note"),
        })

    payload = {"tasks": norm_tasks}
    numbered = _build_numbered_repr(norm_tasks)
    system = SYSTEM_PROMPT.format(today=date.today().isoformat())
    user_msg = (
        f"Текущий список (JSON):\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        f"Текущий список (нумерованный, для счёта):\n{numbered}\n\n"
        f"Фраза пользователя: {user_phrase.strip()}\n\n"
        "Верни обновлённый JSON."
    )

    try:
        if settings.AI_PROVIDER == "gigachat":
            raw = await _call_gigachat(system, user_msg, settings.GIGACHAT_AUTH_KEY)
        elif settings.AI_PROVIDER == "deepseek":
            raw = await _call_deepseek(system, user_msg, settings.DEEPSEEK_API_KEY)
        else:
            raise NLEditError(f"NL-edit not supported for provider {settings.AI_PROVIDER}")
    except NLEditError:
        raise
    except Exception as e:
        logger.error(f"NL-edit LLM call failed: {e}")
        raise NLEditError(f"LLM call failed: {e}") from e

    logger.debug(f"NL-edit raw LLM response: {raw[:500]}")
    parsed = _extract_json(raw)
    new_tasks = parsed.get("tasks")
    if not isinstance(new_tasks, list):
        raise NLEditError("LLM did not return tasks array")

    # Фильтруем мусор, фиксируем обязательные поля
    clean: list[dict[str, Any]] = []
    for t in new_tasks:
        if not isinstance(t, dict):
            continue
        text = str(t.get("text", "")).strip()
        if not text:
            continue
        clean.append({
            "text": text[:500],
            "done": bool(t.get("done", False)),
            "deadline": t.get("deadline") or None,
            "note": (str(t["note"]).strip() if t.get("note") else None) or None,
        })

    # Защита от LLM-галлюцинаций (фикс bug 2026-05-11):
    # «12 не готово» → LLM добавил пункт «12 не готово» 13-м.
    _validate_no_hallucinated_add(norm_tasks, clean, user_phrase)

    new_structured = dict(structured_data)
    new_structured["type"] = "task_list"
    new_structured["tasks"] = clean
    return new_structured


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    # Снимаем markdown-фенсы на всякий случай
    if raw.startswith("```"):
        lines = raw.split("\n")
        # убираем первую и последнюю строку с фенсами
        raw = "\n".join(lines[1:-1]) if len(lines) >= 2 else raw
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Пытаемся найти { ... } внутри текста
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError as e:
                raise NLEditError(f"Invalid JSON from LLM: {e}") from e
        raise NLEditError("No JSON found in LLM response")


async def _call_gigachat(system: str, user: str, auth_key: str) -> str:
    """Прямой вызов GigaChat через httpx (как в ai_classifier)."""
    # OAuth
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        oauth = await client.post(
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={
                "Authorization": f"Basic {auth_key}",
                "RqUID": "00000000-0000-0000-0000-000000000001",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"scope": "GIGACHAT_API_PERS"},
        )
        oauth.raise_for_status()
        access_token = oauth.json()["access_token"]

        resp = await client.post(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "model": "GigaChat",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.1,
                "max_tokens": 1500,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _call_deepseek(system: str, user: str, api_key: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
