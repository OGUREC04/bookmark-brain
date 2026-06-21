"""Тесты превью оффера «Сделать список?» (h3j2 — файл был без тестов).

Граничные случаи: кап по числу пунктов, обрезка по длине (off-by-one),
фильтрация пустых/не-dict, HTML-escape, плюрализация «пункт/пункта/пунктов».
"""
from app.worker.task_list_offer import (
    _MAX_OFFER_ITEM_LEN,
    _MAX_OFFER_ITEMS,
    _offer_items_block,
    _task_list_offer_text,
)


def _tasks(*texts):
    return [{"text": t, "done": False} for t in texts]


# ── кап по числу пунктов ──


def test_exactly_max_items_no_remainder_line():
    block = _offer_items_block(_tasks(*[f"t{i}" for i in range(_MAX_OFFER_ITEMS)]))
    assert "…и ещё" not in block
    assert block.count("•") == _MAX_OFFER_ITEMS


def test_over_max_items_shows_remainder():
    block = _offer_items_block(_tasks(*[f"t{i}" for i in range(_MAX_OFFER_ITEMS + 1)]))
    assert "…и ещё 1" in block
    assert block.count("•") == _MAX_OFFER_ITEMS  # показаны только первые N


# ── обрезка по длине (h3j2 off-by-one) ──


def test_item_exactly_max_len_not_truncated():
    text = "ы" * _MAX_OFFER_ITEM_LEN  # ровно 80
    block = _offer_items_block(_tasks(text))
    assert "…" not in block
    assert text in block


def test_item_over_max_len_truncated_to_full_max():
    text = "ы" * (_MAX_OFFER_ITEM_LEN + 5)  # 85
    block = _offer_items_block(_tasks(text))
    assert "…" in block
    # ровно _MAX_OFFER_ITEM_LEN значимых символов (не 79 — баг исправлен)
    assert block.count("ы") == _MAX_OFFER_ITEM_LEN


# ── фильтрация мусора ──


def test_empty_and_whitespace_and_nondict_filtered():
    block = _offer_items_block([
        {"text": "  "}, {"text": ""}, {"text": "реальный"},
        {"no_text": "x"}, "строка-не-dict",
    ])
    assert block.count("•") == 1
    assert "реальный" in block


def test_empty_list_returns_empty_string():
    assert _offer_items_block([]) == ""
    assert _offer_items_block([{"text": "   "}]) == ""


def test_html_escaped():
    block = _offer_items_block(_tasks("A < B & C"))
    assert "&lt;" in block
    assert "&amp;" in block
    assert "A < B & C" not in block  # сырой не просочился


# ── плюрализация заголовка ──


def test_pluralization():
    assert "— 1 пункт" in _task_list_offer_text({"tasks": _tasks("a")})
    assert "— 3 пункта" in _task_list_offer_text({"tasks": _tasks("a", "b", "c")})
    assert "— 5 пунктов" in _task_list_offer_text(
        {"tasks": _tasks("a", "b", "c", "d", "e")}
    )
