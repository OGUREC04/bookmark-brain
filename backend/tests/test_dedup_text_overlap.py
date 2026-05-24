"""Тесты на _text_overlap.

Регрессии из live smoke-test 2026-05-09:
- Forward бот-рендера должен матчиться с оригинальным голым списком
  (overlap считается симметрично: max от обеих сторон)
- Служебные строки (📋, Reply:, Выполнено:, ☐) не учитываются
"""
from app.services.dedup_checker import (
    _dup_overlap,
    _meaningful_lines,
    _task_items,
    _task_list_overlap,
    _text_overlap,
)

# ── Симметричный overlap ─────────────────────────────


def test_forward_of_bot_render_matches_original():
    """Старый список голый → юзер форвардит бот-рендер обратно → должен дубль."""
    original = "- что то\n- что то\n- еще"
    bot_render = (
        "📋 Список задач\n"
        "\n"
        "☐ 1. что то\n"
        "☐ 2. что то\n"
        "☐ 3. еще\n"
        "\n"
        "↩️ Reply: закрыть · добавить · удалить пункт или список\n"
        "Примеры: «закрой 1, 3» / «добавь хлеб» / «удали 2»"
    )
    overlap_a = _text_overlap(bot_render, original)
    overlap_b = _text_overlap(original, bot_render)
    # Симметричность гарантирует что оба порядка одинаково ловят дубль
    assert overlap_a == overlap_b
    assert overlap_a >= 0.6, f"expected >=0.6, got {overlap_a}"


def test_completely_different_texts():
    a = "купить молоко\nхлеб\nсыр"
    b = "записаться к врачу\nоплатить счёт"
    assert _text_overlap(a, b) == 0.0


def test_partial_overlap_below_threshold():
    """Частичное пересечение (1 из 5) не должно считаться дублём."""
    a = "купить молоко\nхлеб\nсыр\nяйца\nмасло"
    b = "купить молоко\nзаписаться к врачу"
    overlap = _text_overlap(a, b)
    # max(1/5, 1/2) = 0.5 — выше 0.5 (одна линия совпадает с одной из двух),
    # но всё ещё ниже нашего порога 0.6
    assert overlap < 0.6


def test_full_match():
    a = "пункт 1\nпункт 2\nпункт 3"
    b = "пункт 1\nпункт 2\nпункт 3"
    assert _text_overlap(a, b) == 1.0


# ── Фильтрация служебных строк ───────────────────────


def test_bot_noise_filtered_from_meaningful_lines():
    text = (
        "📋 Список задач\n"
        "☐ 1. купить молоко\n"
        "✅ 2. позвонить маме\n"
        "Выполнено: 1 из 2\n"
        "↩️ Reply: …\n"
        "Примеры: «закрой 1»"
    )
    lines = _meaningful_lines(text)
    # Должны остаться только пункты, без шапки/футера
    assert any("купить молоко" in l for l in lines)
    assert any("позвонить маме" in l for l in lines)
    # Заглавных меток быть не должно
    assert not any(l.startswith("список задач") for l in lines)
    assert not any("выполнено" in l for l in lines)
    assert not any("reply" in l for l in lines)
    assert not any("примеры" in l for l in lines)


def test_voice_timestamps_treated_as_noise():
    """[mm:ss] метки голосовых не должны давать ложные совпадения между транскриптами."""
    transcript_a = (
        "[00:00] первый рассказ про погоду и дождь\n"
        "[00:30] продолжаем тему ливней"
    )
    transcript_b = (
        "[00:00] совсем другой рассказ про работу\n"
        "[00:30] про задачи на завтра"
    )
    overlap = _text_overlap(transcript_a, transcript_b)
    # Только [00:00] и [00:30] совпадали бы — но они отфильтрованы → overlap=0
    assert overlap == 0.0


# ── task_list сравнение по пунктам (bug u4z) ─────────


def _tl(*items: str) -> dict:
    return {"type": "task_list", "tasks": [{"text": t} for t in items]}


def test_task_items_extracts_clean_texts():
    """_task_items берёт только text пунктов, нормализованный."""
    items = _task_items(_tl("Купить молоко", "Хлеб", "—"))
    assert "купить молоко" in items
    assert "хлеб" in items
    # «—» нормализуется в пустое/короткое → отброшено
    assert len(items) == 2


def test_task_list_overlap_identical_items():
    a = _tl("молоко", "хлеб", "яйца")
    b = _tl("молоко", "хлеб", "яйца")
    assert _task_list_overlap(a, b) == 1.0


def test_task_list_overlap_none_when_not_task_list():
    """Если хоть один не task_list — None (caller падает на raw_text overlap)."""
    assert _task_list_overlap(_tl("молоко"), None) is None
    assert _task_list_overlap(None, _tl("молоко")) is None
    assert _task_list_overlap({"type": "note"}, _tl("молоко")) is None


def test_dup_overlap_ignores_bot_chrome_for_task_lists():
    """Главный кейс u4z: два списка с одинаковыми пунктами, но РАЗНЫМ
    бот-заголовком/подсказками в raw_text → дубль по пунктам, не по chrome."""
    new_raw = (
        "📋 Покупки на неделю\n☐ молоко\n☐ хлеб\n☐ яйца\n"
        "↩️ Reply: закрыть · добавить"
    )
    existing_raw = (
        "📋 Совсем другой заголовок списка\n✅ молоко\n☐ хлеб\n☐ яйца\n"
        "Примеры: «закрой 1»"
    )
    new_s = _tl("молоко", "хлеб", "яйца")
    existing_s = _tl("молоко", "хлеб", "яйца")
    overlap = _dup_overlap(new_raw, new_s, existing_raw, existing_s)
    assert overlap == 1.0


def test_dup_overlap_different_items_not_dup():
    """Разные пункты → не дубль, даже если бот-chrome (заголовок/подсказки) общий."""
    new_raw = "📋 Список\n☐ купить молоко\n↩️ Reply: закрыть"
    existing_raw = "📋 Список\n☐ позвонить врачу\n↩️ Reply: закрыть"
    new_s = _tl("купить молоко")
    existing_s = _tl("позвонить врачу")
    overlap = _dup_overlap(new_raw, new_s, existing_raw, existing_s)
    assert overlap == 0.0


def test_dup_overlap_falls_back_to_text_for_non_task_lists():
    """Не-task_list пара → обычный текстовый overlap."""
    a = "пункт 1\nпункт 2\nпункт 3"
    b = "пункт 1\nпункт 2\nпункт 3"
    assert _dup_overlap(a, None, b, None) == 1.0
