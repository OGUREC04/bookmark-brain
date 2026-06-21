"""Тесты единого превью для dedup/merge-алертов (shared/dup_preview).

Правило: алерт «уже есть» показывает САМ состав. Список → без заголовка, полный
состав; заметка → заголовок + содержание. Merge → GitHub-дифф (текущие + добавятся).
Всё HTML-escape'ится.
"""
from shared.dup_preview import dup_preview, merge_diff_preview

# ── заметка ──


def test_note_title_and_summary():
    out = dup_preview(title="Поездка в Рим", summary="Колизей, паста, вино")
    assert "📖" in out
    assert "Поездка в Рим" in out
    assert "Колизей" in out


def test_note_summary_truncated_to_300():
    out = dup_preview(title="t", summary="y" * 500)
    assert out.count("y") <= 300


def test_note_escapes_html():
    out = dup_preview(title="A < B", summary="C & D")
    assert "&lt;" in out and "&amp;" in out


# ── список (без заголовка, полный состав) ──


def test_list_no_title_full_items():
    sd = {"type": "task_list", "tasks": [
        {"text": "молоко", "done": False},
        {"text": "хлеб", "done": True},
    ]}
    out = dup_preview(structured_data=sd)
    assert "📋" in out
    assert "(1/2)" in out
    assert "☐ 1. молоко" in out
    assert "✅ 2. хлеб" in out
    # AI-заголовок НЕ показываем
    assert "📖" not in out


def test_list_escapes_html():
    sd = {"type": "task_list", "tasks": [{"text": "A < B", "done": False}]}
    out = dup_preview(structured_data=sd)
    assert "&lt;" in out


# ── merge-дифф ──


def test_merge_diff_shows_current_and_additions():
    old = {"type": "task_list", "tasks": [
        {"text": "позвонить в банк", "done": False},
        {"text": "оплатить интернет", "done": True},
    ]}
    new = {"type": "task_list", "tasks": [
        {"text": "купить молоко", "done": False},
        {"text": "позвонить в банк", "done": False},  # дубль — пропустится
    ]}
    out = merge_diff_preview(old, new)
    assert "Сейчас в списке" in out
    assert "☐ позвонить в банк" in out     # current
    assert "✅ оплатить интернет" in out
    assert "➕ купить молоко" in out         # addition
    assert "(+1)" in out                     # только 1 (банк уже есть)


def test_merge_diff_all_duplicate():
    old = {"type": "task_list", "tasks": [{"text": "a", "done": False}]}
    new = {"type": "task_list", "tasks": [{"text": "a", "done": False}]}
    out = merge_diff_preview(old, new)
    assert "уже есть" in out.lower()


def test_merge_diff_escapes():
    out = merge_diff_preview(
        {"type": "task_list", "tasks": []},
        {"type": "task_list", "tasks": [{"text": "A < B", "done": False}]},
    )
    assert "&lt;" in out


# ── лимиты / edge (из ревью) ──


def test_long_item_text_capped():
    sd = {"type": "task_list", "tasks": [{"text": "ы" * 200, "done": False}]}
    out = dup_preview(structured_data=sd)
    assert "…" in out          # обрезано
    assert out.count("ы") < 200


def test_merge_new_unavailable_is_honest():
    """new_structured=None (упал fetch) → честное сообщение, а не «нечего добавлять»."""
    old = {"type": "task_list", "tasks": [{"text": "a", "done": False}]}
    out = merge_diff_preview(old, None)
    assert "недоступен" in out.lower()
    assert "уже есть" not in out.lower()


def test_empty_list_falls_to_note_branch():
    out = dup_preview(
        structured_data={"type": "task_list", "tasks": []},
        title="Заголовок", summary="Содержание",
    )
    assert "Заголовок" in out      # пустой список → заголовок+содержание
    assert "Содержание" in out


# ── безопасность ──


def test_none_safe():
    assert dup_preview(structured_data=None, title="t", summary="s")
    assert merge_diff_preview(None, None)
    assert dup_preview(structured_data={"type": "task_list", "tasks": []})
