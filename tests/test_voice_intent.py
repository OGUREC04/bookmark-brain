"""Tests for voice intent detection."""
from __future__ import annotations

import pytest

from bot.services.voice_intent import IntentResult, VoiceIntent, detect_intent


class TestTodoDetection:
    """Voice intent → TODO."""

    def test_explicit_prefix_list(self):
        result = detect_intent("список задач купить молоко, хлеб, сыр")
        assert result.intent == VoiceIntent.TODO
        assert "купить молоко" in result.cleaned_text

    def test_explicit_prefix_todo(self):
        result = detect_intent("todo написать тесты, сделать ревью")
        assert result.intent == VoiceIntent.TODO

    def test_explicit_prefix_kupit(self):
        result = detect_intent("купить: молоко, хлеб, масло")
        assert result.intent == VoiceIntent.TODO

    def test_plan_na(self):
        result = detect_intent("план на неделю: дизайн, код, тесты")
        assert result.intent == VoiceIntent.TODO

    def test_nado_sdelat(self):
        result = detect_intent("надо сделать ревью кода и написать документацию")
        assert result.intent == VoiceIntent.TODO

    def test_anywhere_trigger(self):
        result = detect_intent("пожалуйста создай список из этих задач")
        assert result.intent == VoiceIntent.TODO

    def test_cleaned_text_strips_prefix(self):
        result = detect_intent("задачи: первая, вторая, третья")
        assert result.intent == VoiceIntent.TODO
        assert result.cleaned_text == "первая, вторая, третья"


class TestSearchDetection:
    """Voice intent → SEARCH."""

    def test_explicit_prefix_naidi(self):
        result = detect_intent("найди статьи про дизайн", duration=5.0)
        assert result.intent == VoiceIntent.SEARCH
        assert "статьи про дизайн" in result.cleaned_text

    def test_explicit_prefix_poischi(self):
        result = detect_intent("поищи закладку про архитектуру", duration=4.0)
        assert result.intent == VoiceIntent.SEARCH

    def test_question_word_short(self):
        result = detect_intent("где у меня заметки про React", duration=3.0)
        assert result.intent == VoiceIntent.SEARCH

    def test_question_word_short_no_duration(self):
        # Short text (<60 chars) should still detect as search
        result = detect_intent("где закладка про Python")
        assert result.intent == VoiceIntent.SEARCH

    def test_long_message_not_search(self):
        # Even with search prefix, long duration → not search
        long_text = "найди " + "слово " * 100
        result = detect_intent(long_text, duration=45.0)
        # Text is > 60 chars AND duration > 10s → NOTE, not search
        assert result.intent == VoiceIntent.NOTE

    def test_short_question_no_prefix(self):
        result = detect_intent("какие закладки про тесты", duration=3.0)
        assert result.intent == VoiceIntent.SEARCH


class TestNoteDetection:
    """Voice intent → NOTE (default)."""

    def test_regular_speech(self):
        result = detect_intent(
            "Сегодня встретился с Петей, обсудили план на квартал. "
            "��ешили что нужно больше автоматизации.",
            duration=15.0,
        )
        assert result.intent == VoiceIntent.NOTE

    def test_empty_text(self):
        result = detect_intent("")
        assert result.intent == VoiceIntent.NOTE

    def test_none_text(self):
        result = detect_intent(None)
        assert result.intent == VoiceIntent.NOTE

    def test_long_regular_speech(self):
        text = "Это обычная голосовая заметка о том что я делал на работе. " * 5
        result = detect_intent(text, duration=30.0)
        assert result.intent == VoiceIntent.NOTE

    def test_bare_napomni_is_reminder(self):
        # skf/kjo: «напомни» теперь детерминированно reminder, не todo
        # (раньше уходило в TODO → инжект «список задач:» → 2 напоминания).
        result = detect_intent("напомни", duration=2.0)
        assert result.intent == VoiceIntent.REMINDER

    def test_short_text_without_triggers(self):
        result = detect_intent("привет", duration=1.5)
        assert result.intent == VoiceIntent.NOTE
