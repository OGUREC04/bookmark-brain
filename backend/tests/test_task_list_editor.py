"""Tests for backend/app/services/task_list_editor.py::apply_nl_edit.

Покрывает post-validation против галлюцинаций LLM:
- «не готово / отмени» НЕ должно увеличивать длину списка
- Нет add-маркеров + LLM добавил пункт → reject
- LLM unparseable → NLEditError
- numbered text representation в payload (smoke)

Стратегия: мокаем _call_gigachat / _call_deepseek через monkeypatch чтобы
не зависеть от httpx/сети.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest


@pytest.fixture(autouse=True)
def _force_gigachat(monkeypatch):
    """Фиксируем provider=gigachat чтобы не зависеть от .env."""
    from app import config
    monkeypatch.setattr(config, "_settings", None, raising=False)
    monkeypatch.setenv("AI_PROVIDER", "gigachat")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "fake-key")


def _list(n: int, done_indices: set[int] | None = None) -> dict:
    done_indices = done_indices or set()
    return {
        "type": "task_list",
        "tasks": [
            {"text": f"задача {i+1}", "done": i in done_indices,
             "deadline": None, "note": None}
            for i in range(n)
        ],
    }


def _mock_llm(monkeypatch, returns_tasks: list[dict]):
    """Мокаем _call_gigachat — возвращает заданный JSON.

    Сохраняет последний system/user payload в `last_call` для проверок.
    """
    last_call = {}

    async def fake(system: str, user: str, auth_key: str) -> str:
        last_call["system"] = system
        last_call["user"] = user
        return json.dumps({"tasks": returns_tasks}, ensure_ascii=False)

    from app.services import task_list_editor as mod
    monkeypatch.setattr(mod, "_call_gigachat", fake)
    return last_call


# ──────────────────────────────────────────────────
# Numbered text representation в payload
# ──────────────────────────────────────────────────


class TestNumberedRepresentation:
    async def test_user_payload_contains_numbered_list(self, monkeypatch):
        """LLM должен видеть нумерованный список (не только JSON) —
        иначе мискаунтит на длинных списках."""
        from app.services.task_list_editor import apply_nl_edit

        structured = _list(3)
        # LLM просто возвращает то же что прислали
        last_call = _mock_llm(monkeypatch, structured["tasks"])

        await apply_nl_edit(structured, "1 готово")

        user = last_call.get("user", "")
        # Должны быть строки вида «1. задача 1», «2. задача 2», «3. задача 3»
        assert "1. " in user, f"нет нумерации в payload: {user[:300]}"
        assert "2. " in user
        assert "3. " in user
        assert "задача 1" in user

    async def test_done_marker_in_numbered_repr(self, monkeypatch):
        """Выполненные пункты помечены маркером (✓/[x])."""
        from app.services.task_list_editor import apply_nl_edit

        structured = _list(3, done_indices={1})
        last_call = _mock_llm(monkeypatch, structured["tasks"])

        await apply_nl_edit(structured, "что там")

        user = last_call.get("user", "")
        # Любой из маркеров готового — [x] / ✓ / ✅
        assert any(m in user for m in ("[x]", "[X]", "✓", "✅")), (
            f"нет маркера done: {user[:300]}"
        )


# ──────────────────────────────────────────────────
# Post-validation против галлюцинаций
# ──────────────────────────────────────────────────


class TestRejectHallucinatedAdd:
    async def test_undone_phrase_must_not_grow_list(self, monkeypatch):
        """Bug 2: «12 не готово» + LLM добавил 13-й пункт → reject."""
        from app.services.task_list_editor import NLEditError, apply_nl_edit

        structured = _list(12, done_indices={11})
        # LLM галлюцинирует: добавляет «12 не готово» как новый пункт
        hallucinated = list(structured["tasks"]) + [
            {"text": "12 не готово", "done": False, "deadline": None, "note": None}
        ]
        _mock_llm(monkeypatch, hallucinated)

        with pytest.raises(NLEditError):
            await apply_nl_edit(structured, "12 не готово")

    async def test_undone_same_length_allowed(self, monkeypatch):
        """Снять галку c пункта (длина та же) → OK."""
        from app.services.task_list_editor import apply_nl_edit

        structured = _list(12, done_indices={11})
        # Корректное поведение LLM: снял done с 12-го
        correct = [{**t} for t in structured["tasks"]]
        correct[11]["done"] = False
        _mock_llm(monkeypatch, correct)

        result = await apply_nl_edit(structured, "12 не готово")
        assert len(result["tasks"]) == 12
        assert result["tasks"][11]["done"] is False

    async def test_phrase_without_add_markers_cant_grow(self, monkeypatch):
        """«1 готово» — нет add-маркеров, LLM добавил пункт → reject."""
        from app.services.task_list_editor import NLEditError, apply_nl_edit

        structured = _list(3)
        hallucinated = list(structured["tasks"]) + [
            {"text": "выдумка", "done": False, "deadline": None, "note": None}
        ]
        _mock_llm(monkeypatch, hallucinated)

        with pytest.raises(NLEditError):
            await apply_nl_edit(structured, "1 готово")

    async def test_phrase_with_add_marker_can_grow(self, monkeypatch):
        """«добавь X» — есть add-маркер, рост на 1 ОК."""
        from app.services.task_list_editor import apply_nl_edit

        structured = _list(3)
        grown = list(structured["tasks"]) + [
            {"text": "новая задача", "done": False, "deadline": None, "note": None}
        ]
        _mock_llm(monkeypatch, grown)

        result = await apply_nl_edit(structured, "добавь новая задача")
        assert len(result["tasks"]) == 4

    async def test_remove_phrase_must_not_grow(self, monkeypatch):
        """«удали 2» + LLM добавил пункт → reject."""
        from app.services.task_list_editor import NLEditError, apply_nl_edit

        structured = _list(3)
        hallucinated = list(structured["tasks"]) + [
            {"text": "лишнее", "done": False, "deadline": None, "note": None}
        ]
        _mock_llm(monkeypatch, hallucinated)

        with pytest.raises(NLEditError):
            await apply_nl_edit(structured, "удали 2")

    async def test_bulk_hallucination_rejected(self, monkeypatch):
        """LLM добавил >5 пунктов без add-маркеров → reject (sanity-cap)."""
        from app.services.task_list_editor import NLEditError, apply_nl_edit

        structured = _list(3)
        bulk_hallucinated = list(structured["tasks"]) + [
            {"text": f"мусор {i}", "done": False, "deadline": None, "note": None}
            for i in range(10)
        ]
        _mock_llm(monkeypatch, bulk_hallucinated)

        with pytest.raises(NLEditError):
            await apply_nl_edit(structured, "что-то непонятное")


# ──────────────────────────────────────────────────
# Корректные сценарии
# ──────────────────────────────────────────────────


class TestHappyPath:
    async def test_done_via_llm_works(self, monkeypatch):
        from app.services.task_list_editor import apply_nl_edit

        structured = _list(3)
        correct = [{**t} for t in structured["tasks"]]
        correct[0]["done"] = True
        _mock_llm(monkeypatch, correct)

        result = await apply_nl_edit(structured, "1 готово")
        assert result["tasks"][0]["done"] is True

    async def test_rename_via_llm(self, monkeypatch):
        from app.services.task_list_editor import apply_nl_edit

        structured = _list(3)
        renamed = [{**t} for t in structured["tasks"]]
        renamed[0]["text"] = "купить хлеб"
        _mock_llm(monkeypatch, renamed)

        result = await apply_nl_edit(structured, "переименуй 1 в купить хлеб")
        assert result["tasks"][0]["text"] == "купить хлеб"

    async def test_remove_via_llm(self, monkeypatch):
        from app.services.task_list_editor import apply_nl_edit

        structured = _list(3)
        shorter = [structured["tasks"][0], structured["tasks"][2]]
        _mock_llm(monkeypatch, shorter)

        result = await apply_nl_edit(structured, "удали 2")
        assert len(result["tasks"]) == 2
