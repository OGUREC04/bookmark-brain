"""TDD-тесты для wrap_expandable — сворачиваемая цитата длинных транскриптов.

Все тесты — чистые unit-тесты без Telegram/сети/aiogram.
"""
from __future__ import annotations

import pytest

from bot.services.transcript_format import LONG_TRANSCRIPT_CHARS, wrap_expandable


class TestWrapExpandableShort:
    """Короткий транскрипт → без изменений, parse_mode=None."""

    def test_short_text_returned_as_is(self):
        text = "Купить молоко и хлеб"
        result_text, parse_mode = wrap_expandable(text)
        assert result_text == text
        assert parse_mode is None

    def test_empty_string_returned_as_is(self):
        result_text, parse_mode = wrap_expandable("")
        assert result_text == ""
        assert parse_mode is None

    def test_single_word_returned_as_is(self):
        result_text, parse_mode = wrap_expandable("Привет")
        assert result_text == "Привет"
        assert parse_mode is None

    def test_exactly_at_threshold_not_wrapped(self):
        # Ровно на пороге — НЕ оборачиваем (> а не >=)
        text = "а" * LONG_TRANSCRIPT_CHARS
        result_text, parse_mode = wrap_expandable(text)
        assert result_text == text
        assert parse_mode is None


class TestWrapExpandableLong:
    """Длинный транскрипт (>600 символов) → expandable blockquote + parse_mode='HTML'."""

    def test_long_text_wrapped_in_blockquote(self):
        text = "слово " * 120  # ~720 символов
        result_text, parse_mode = wrap_expandable(text)
        assert result_text.startswith("<blockquote expandable>")
        assert result_text.endswith("</blockquote>")
        assert parse_mode == "HTML"

    def test_long_text_one_char_over_threshold_wrapped(self):
        text = "а" * (LONG_TRANSCRIPT_CHARS + 1)
        result_text, parse_mode = wrap_expandable(text)
        assert "<blockquote expandable>" in result_text
        assert parse_mode == "HTML"

    def test_long_text_content_preserved_inside_blockquote(self):
        # Обычный текст без спецсимволов — контент внутри без изменений
        inner = "Это длинный транскрипт " * 30  # >600 символов
        result_text, parse_mode = wrap_expandable(inner)
        assert parse_mode == "HTML"
        # Контент должен быть внутри тегов
        assert result_text == f"<blockquote expandable>{inner.strip()}</blockquote>" or inner in result_text


class TestWrapExpandableHtmlEscape:
    """Спецсимволы HTML экранируются внутри blockquote."""

    def test_ampersand_escaped(self):
        text = ("Текст с амперсандом & ещё текст. " * 25)  # >600 символов
        result_text, parse_mode = wrap_expandable(text)
        assert parse_mode == "HTML"
        assert "&amp;" in result_text
        assert "& ещё" not in result_text  # исходный & не должен быть в результате

    def test_less_than_escaped(self):
        text = ("сравниваем a < b в цикле. " * 25)  # >600 символов
        result_text, parse_mode = wrap_expandable(text)
        assert parse_mode == "HTML"
        assert "&lt;" in result_text
        assert "a < b" not in result_text

    def test_greater_than_escaped(self):
        text = ("сравниваем x > 0 тут. " * 30)  # >600 символов (~660)
        result_text, parse_mode = wrap_expandable(text)
        assert parse_mode == "HTML"
        assert "&gt;" in result_text
        assert "x > 0" not in result_text

    def test_short_text_with_html_chars_not_escaped(self):
        # Короткий текст → plain, экранировать не надо
        text = "a < b & c > d"
        result_text, parse_mode = wrap_expandable(text)
        assert parse_mode is None
        assert result_text == text  # возвращаем как есть

    def test_all_three_html_chars_escaped_in_long_text(self):
        text = ("x < y & z > w — вот пример сравнений. " * 20)  # >600 символов
        result_text, parse_mode = wrap_expandable(text)
        assert parse_mode == "HTML"
        assert "&lt;" in result_text
        assert "&amp;" in result_text
        assert "&gt;" in result_text


class TestWrapExpandableTimecodes:
    """Текст с таймкодами [MM:SS] оборачивается даже если короче 600 символов."""

    def test_multiple_timecodes_wraps_even_if_short(self):
        # Несколько строк с таймкодами → длинный транскрипт (навигационный)
        text = "[00:00] Начало разговора\n[00:30] Продолжение\n[01:00] Итог"
        result_text, parse_mode = wrap_expandable(text)
        assert parse_mode == "HTML"
        assert "<blockquote expandable>" in result_text

    def test_single_timecode_not_enough_to_wrap(self):
        # Один таймкод — не «несколько», не оборачиваем
        text = "[00:00] Короткое сообщение без длины"
        result_text, parse_mode = wrap_expandable(text)
        assert parse_mode is None

    def test_two_timecodes_triggers_wrap(self):
        # Два — уже «несколько» → оборачиваем
        text = "[00:00] Первая часть разговора здесь\n[00:30] Вторая часть здесь"
        result_text, parse_mode = wrap_expandable(text)
        assert parse_mode == "HTML"
        assert "<blockquote expandable>" in result_text

    def test_timecodes_with_html_chars_escaped(self):
        text = "[00:00] Привет & мир\n[00:30] x < y\n[01:00] z > w"
        result_text, parse_mode = wrap_expandable(text)
        assert parse_mode == "HTML"
        assert "&amp;" in result_text
        assert "&lt;" in result_text
        assert "&gt;" in result_text

    def test_long_text_with_timecodes_wraps_once(self):
        # Длинный + таймкоды — обёртка одна
        text = "[00:00] " + "слово " * 120 + "\n[00:30] продолжение"
        result_text, parse_mode = wrap_expandable(text)
        assert parse_mode == "HTML"
        assert result_text.count("<blockquote expandable>") == 1
        assert result_text.count("</blockquote>") == 1


class TestWrapExpandableReturnType:
    """Проверяем типы возвращаемых значений."""

    def test_returns_tuple(self):
        result = wrap_expandable("текст")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_short_second_element_is_none(self):
        _, parse_mode = wrap_expandable("короткий")
        assert parse_mode is None

    def test_long_second_element_is_html_string(self):
        _, parse_mode = wrap_expandable("а" * (LONG_TRANSCRIPT_CHARS + 1))
        assert parse_mode == "HTML"
        assert isinstance(parse_mode, str)
