"""Tests для task_list_detector — фокус на anti-false-positive heuristics.

Покрывает фиксы из коммита fix(detector) PR #4: длинные пункты, ad-patterns,
длинная прелюдия не должны детектиться как task_list.
"""
import pytest
from app.services.task_list_detector import (
    AD_PATTERNS,
    MAX_PREAMBLE_WORDS,
    MAX_TASK_LENGTH,
    _is_preamble_line,
    detect,
)

# ── Положительные кейсы (должно детектить) ──


def test_simple_bulleted_list_detected():
    text = "- молоко\n- хлеб\n- сыр"
    result = detect(text, ai_item_type="action")
    assert result.is_list is True
    assert len(result.tasks) == 3


def test_explicit_trigger_forces_list():
    text = "Сделай список:\nмолоко\nхлеб"
    result = detect(text)
    assert result.is_list is True
    assert result.forced_by_user is True


def test_forced_drops_leading_preamble():
    """«Сегодня нужно» — вводная преамбула, не пункт. forced newline-split
    должен её снять (баг: голосовой список плодил её пунктом №1)."""
    text = "Список задач:\nСегодня нужно\nпозвонить маме\nкупить хлеб"
    result = detect(text)
    assert result.is_list is True
    assert result.tasks == ["позвонить маме", "купить хлеб"]


def test_forced_keeps_action_with_preamble_word():
    """«Сделать отчёт» содержит преамбульное слово «сделать», но «отчёт» —
    контентное слово → это реальный пункт, НЕ дропаем."""
    text = "Список задач:\nсделать отчёт\nпозвонить маме"
    result = detect(text)
    assert result.is_list is True
    assert "сделать отчёт" in result.tasks


def test_is_preamble_line_unit():
    # Чистая преамбула — все слова преамбульные/филлеры
    assert _is_preamble_line("Сегодня нужно") is True
    assert _is_preamble_line("Мне надо.") is True
    assert _is_preamble_line("Так, короче") is True
    # Реальный пункт с контентным словом
    assert _is_preamble_line("сделать отчёт") is False
    assert _is_preamble_line("позвонить маме") is False
    # Слишком длинная — не преамбула
    assert _is_preamble_line("нужно " * 10) is False


def test_inline_comma_list_detected():
    text = "молоко, хлеб, сыр, яйца"
    result = detect(text, ai_item_type="action")
    assert result.is_list is True
    assert len(result.tasks) == 4


def test_explicit_trigger_overrides_article_filter():
    """Юзер явно попросил список — не применяем anti-article фильтр."""
    text = (
        "Список задач:\n"
        "- " + "очень длинная задача " * 20 + "\n"  # длиннее MAX_TASK_LENGTH
        "- короткая задача"
    )
    result = detect(text)
    assert result.is_list is True
    assert result.forced_by_user is True


# ── Anti-false-positive (НЕ должно детектить) ──


def test_long_task_treated_as_article():
    """Пункт длиннее MAX_TASK_LENGTH = это абзац статьи, не задача."""
    long_para = "очень детальное описание чего-то " * 10  # > 100 chars
    text = f"- {long_para}\n- ещё пункт"
    result = detect(text, ai_item_type="action")
    assert result.is_list is False


def test_post_with_hashtags_not_list():
    """Рекламный пост с хэштегами не детектится как список."""
    text = (
        "- Купи новый iPhone #акция\n"
        "- Скидка только сегодня #промо\n"
        "- Звони +7 (495) 123-45-67"
    )
    result = detect(text, ai_item_type="action")
    assert result.is_list is False


def test_long_preamble_treated_as_article():
    """Длинная описательная прелюдия → это статья с нумерацией."""
    preamble = " ".join(["слово"] * (MAX_PREAMBLE_WORDS + 5))
    text = f"{preamble}\n- пункт 1\n- пункт 2"
    result = detect(text, ai_item_type="action")
    assert result.is_list is False


def test_post_with_phones_not_list():
    """≥2 пунктов с телефонами = информационный пост."""
    text = (
        "- Магазин: +7 495 123-45-67\n"
        "- Доставка: 8 800 555-35-35\n"
        "- График: пн-пт"
    )
    result = detect(text, ai_item_type="action")
    assert result.is_list is False


def test_post_with_urls_not_list():
    """≥2 пунктов со ссылками = пост, не список задач."""
    text = (
        "- Сайт: https://example.com\n"
        "- Подписывайся на канале example.ru\n"
        "- Заходи в чат"
    )
    result = detect(text, ai_item_type="action")
    assert result.is_list is False


def test_single_url_item_still_list():
    """Один url не делает пост из списка — нужно ≥2 ad-маркеров."""
    text = "- купить молоко\n- посмотреть https://example.com\n- забрать посылку"
    result = detect(text, ai_item_type="action")
    assert result.is_list is True


# ── Edge cases ──


def test_empty_text_returns_no_list():
    assert detect("").is_list is False
    assert detect("   ").is_list is False


def test_single_line_no_trigger_no_list():
    """Одна строка без триггера — обычная заметка."""
    result = detect("просто заметка")
    assert result.is_list is False


def test_detector_never_raises():
    """Защитный контракт: детектор никогда не бросает исключений."""
    weird_inputs = [
        None,
        "",
        " " * 1000,
        "🔥" * 100,
        "\n" * 50,
        "a" * 10000,
    ]
    for inp in weird_inputs:
        try:
            if inp is None:
                # detect() ожидает str — None это не его контракт, пропускаем
                continue
            result = detect(inp)
            assert isinstance(result.is_list, bool)
        except Exception as e:
            pytest.fail(f"detect({inp!r}) raised {e!r}")


def test_ad_patterns_compile_correctly():
    """Все AD_PATTERNS — валидные regex'ы."""
    test_strings = ["#tag", "https://x.ru", "+7 999 1234567", "@username", "канал"]
    for pattern in AD_PATTERNS:
        for s in test_strings:
            # Главное чтобы не падало
            pattern.search(s)


def test_max_constants_are_sane():
    """Защита от случайного обнуления порогов."""
    assert MAX_TASK_LENGTH > 50
    assert MAX_PREAMBLE_WORDS > 5


def test_bot_rendered_list_recognized_when_copypasted():
    """Юзер переслал/скопировал отрендеренный нами список — должен опять
    стать task_list. Иначе copy-paste своего же сообщения создаёт дубль
    в виде обычной заметки и dedup не срабатывает.
    """
    text = (
        "📋 Список задач\n"
        "\n"
        "✅ 1. хуй\n"
        "☐ 2. пизда\n"
        "☐ 3. бля\n"
        "\n"
        "Выполнено: 1 из 3\n"
        "\n"
        "↩️ Reply: закрыть · добавить · удалить пункт или список\n"
        "Примеры: «закрой 1, 3» / «добавь хлеб» / «удали 2»"
    )
    result = detect(text, ai_item_type="content")
    assert result.is_list is True
    assert len(result.tasks) == 3
    # Нумерация и bullet-маркеры должны исчезнуть из текста пунктов
    assert "хуй" in result.tasks[0]
    assert "1." not in result.tasks[0]
    assert "✅" not in result.tasks[0]
    assert "📋" not in " ".join(result.tasks)
    assert "Reply:" not in " ".join(result.tasks)


def test_bot_rendered_with_voice_timestamps():
    """Длинный голосовой транскрипт с [mm:ss] не должен детектиться как список."""
    text = (
        "[00:00] первое предложение длинное и содержит много слов про разное\n"
        "[00:30] второе предложение продолжает мысль и тоже довольно длинное\n"
        "[01:00] третье предложение завершает рассказ"
    )
    result = detect(text, ai_item_type="content")
    assert result.is_list is False
