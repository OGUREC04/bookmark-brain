"""Тесты на _text_overlap.

Регрессии из live smoke-test 2026-05-09:
- Forward бот-рендера должен матчиться с оригинальным голым списком
  (overlap считается симметрично: max от обеих сторон)
- Служебные строки (📋, Reply:, Выполнено:, ☐) не учитываются
"""
from app.services.dedup_checker import _meaningful_lines, _text_overlap

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
