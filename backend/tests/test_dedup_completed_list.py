"""Тест: выполненный список не считается дублем (не блокирует новый).

Баг: юзер заново отправил список, идентичный уже ВЫПОЛНЕННОМУ — дедуп писал
«такое уже есть». find_near_duplicate теперь исключает полностью завершённые
task_list через _is_completed_task_list.
"""
from app.services.dedup_checker import _is_completed_task_list


def _tl(*done_flags):
    return {
        "type": "task_list",
        "tasks": [{"text": f"t{i}", "done": d} for i, d in enumerate(done_flags)],
    }


def test_all_done_is_completed():
    assert _is_completed_task_list(_tl(True, True, True)) is True


def test_partial_not_completed():
    assert _is_completed_task_list(_tl(True, False, True)) is False


def test_none_done_not_completed():
    assert _is_completed_task_list(_tl(False, False)) is False


def test_empty_list_not_completed():
    assert _is_completed_task_list({"type": "task_list", "tasks": []}) is False


def test_not_a_task_list():
    assert _is_completed_task_list({"type": "article"}) is False
    assert _is_completed_task_list(None) is False
    assert _is_completed_task_list("nope") is False


def test_missing_done_treated_as_undone():
    # пункт без поля done → не выполнен → список не завершён
    structured = {"type": "task_list", "tasks": [{"text": "t"}]}
    assert _is_completed_task_list(structured) is False
