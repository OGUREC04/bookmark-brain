"""NL-редактор task_list.

Применяет свободную фразу пользователя к текущему списку задач через LLM.
GigaChat получает текущий JSON + фразу, возвращает НОВЫЙ JSON списка.

Все операции (add/remove/update/deadline/note/toggle) выражаются через разницу
старого и нового JSON — нам не надо их парсить отдельно.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Ты — редактор списка задач. Получаешь текущий список в JSON и фразу пользователя,
возвращаешь обновлённый JSON списка.

ПРАВИЛА:
- Не трогай пункты, о которых пользователь не упомянул.
- Нумерация в фразе пользователя — 1-based (задача №1 = индекс 0 в массиве).
- "добавь X", "+ X", просто "X" отдельной строкой — добавить в конец массива.
- "удали N", "убери N", "- N" — убрать пункт по номеру.
- "N: до <дата>", "N <дата>", "N — <дата>" — проставить deadline.
- "N = новый текст", "переименуй N в Y", "N: Y" — изменить text (но НЕ если это похоже на дедлайн).
- "к N: <описание>", "N — заметка: X" — проставить note.
- "N готово", "сделано N", "✓ N" — toggle done=true.
- Даты → ISO YYYY-MM-DD. Сегодня = {today}. "завтра", "пятница", "через неделю" — вычисли.
- Время не указано → null в time-части.
- Если фраза непонятна — верни список БЕЗ изменений.
- Не выдумывай задачи, которых нет и о которых пользователь не просил.

ФОРМАТ ОТВЕТА — ТОЛЬКО JSON, без markdown, без пояснений:
{{"tasks": [{{"text": "...", "done": false, "deadline": null, "note": null}}, ...]}}

Каждый пункт ОБЯЗАТЕЛЬНО содержит поля text, done, deadline, note (null если нет).
"""


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
    system = SYSTEM_PROMPT.format(today=date.today().isoformat())
    user_msg = (
        f"Текущий список:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
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
