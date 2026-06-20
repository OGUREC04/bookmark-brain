"""Тесты force_structure_as_list — конвертация заметки в task_list.

Покрывает кнопку «Сделать списком» на dedup-подтверждении (c6ti):
порог числа пунктов (allow_single), reason-коды, форма structured_data.
"""
from app.services.task_list_detector import force_structure_as_list


# ── ok: текст уже содержит выделяемые пункты ──


def test_multiline_items():
    sd, reason = force_structure_as_list("молоко\nхлеб\nсыр")
    assert reason == "ok"
    assert sd["type"] == "task_list"
    assert [t["text"] for t in sd["tasks"]] == ["молоко", "хлеб", "сыр"]


def test_comma_items():
    sd, reason = force_structure_as_list("молоко, хлеб, сыр")
    assert reason == "ok"
    assert len(sd["tasks"]) == 3


def test_runon_verbs_split():
    """Сплошная надиктовка по глаголам → ≥2 пункта (переиспускает
    _split_runon_by_verbs через forced-детекцию)."""
    sd, reason = force_structure_as_list("купить молоко позвонить маме")
    assert reason == "ok"
    assert [t["text"] for t in sd["tasks"]] == ["купить молоко", "позвонить маме"]


# ── single_phrase: одна фраза, по умолчанию НЕ делаем 1-пунктовый клон ──


def test_single_phrase_blocked_by_default():
    sd, reason = force_structure_as_list("идеи для отпуска")
    assert sd is None
    assert reason == "single_phrase"


def test_single_verb_phrase_blocked_by_default():
    """Один глагол — это одна задача, а не разбиваемый список."""
    sd, reason = force_structure_as_list("позвонить маме срочно")
    assert sd is None
    assert reason == "single_phrase"


def test_single_phrase_allowed_when_explicit():
    """Юзер ПРИСЛАЛ пункты вручную (allow_single) → принимаем даже 1."""
    sd, reason = force_structure_as_list("идеи для отпуска", allow_single=True)
    assert reason == "ok"
    assert len(sd["tasks"]) == 1
    assert sd["tasks"][0]["text"] == "идеи для отпуска"


# ── empty ──


def test_empty_text():
    sd, reason = force_structure_as_list("   ")
    assert sd is None
    assert reason == "empty"


def test_none_safe():
    sd, reason = force_structure_as_list("")
    assert sd is None
    assert reason == "empty"


# ── форма пунктов ──


def test_tasks_shape_done_false_no_deadline():
    sd, _ = force_structure_as_list("молоко\nхлеб")
    for t in sd["tasks"]:
        assert t["done"] is False
        assert t["deadline"] is None
