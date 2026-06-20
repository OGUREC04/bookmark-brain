"""HTML-escaping в каноническом рендере списка (CRITICAL из ревью c6ti-кластера).

Текст пункта идёт в parse_mode=HTML. «A < B», «C++», «A&B» без escape ломают
разметку (TelegramBadRequest) или инжектят теги.
"""
from shared.task_list_render import render_task_list


def test_special_chars_escaped():
    sd = {"type": "task_list", "tasks": [
        {"text": "review A < B & C++", "done": False, "deadline": None},
    ]}
    out = render_task_list(None, sd)
    assert "&lt;" in out
    assert "&amp;" in out
    # сырой неэкранированный фрагмент не должен присутствовать
    assert "A < B & C++" not in out


def test_injected_tags_neutralized():
    sd = {"type": "task_list", "tasks": [
        {"text": "<b>fake bold</b>", "done": True, "deadline": None},
    ]}
    out = render_task_list(None, sd)
    assert "&lt;b&gt;fake bold&lt;/b&gt;" in out


def test_note_escaped():
    sd = {"type": "task_list", "tasks": [
        {"text": "task", "done": False, "deadline": None, "note": "see <doc> & ref"},
    ]}
    out = render_task_list(None, sd)
    assert "&lt;doc&gt;" in out
    assert "&amp;" in out


def test_plain_text_unchanged():
    sd = {"type": "task_list", "tasks": [
        {"text": "купить молоко", "done": False, "deadline": None},
    ]}
    out = render_task_list(None, sd)
    assert "купить молоко" in out
