"""Tests for timestamp insertion in long voice transcriptions."""
from __future__ import annotations

import pytest

from bot.services.timestamps import MIN_DURATION_FOR_TIMESTAMPS, add_timestamps


class TestAddTimestamps:
    """Timestamp insertion for long voice messages."""

    def test_short_duration_unchanged(self):
        text = "Короткое сообщение"
        result = add_timestamps(text, duration=30.0)
        assert result == text
        assert "[00:00]" not in result

    def test_none_duration_unchanged(self):
        text = "Без длительности"
        result = add_timestamps(text, duration=None)
        assert result == text

    def test_long_duration_has_timestamps(self):
        # 100 words at ~2.5 words/sec = 40 seconds of speech
        # With 90s duration, should get timestamps
        words = ["слово"] * 100
        text = " ".join(words)
        result = add_timestamps(text, duration=90.0)
        assert "[00:00]" in result
        assert "[00:30]" in result

    def test_timestamp_format(self):
        words = ["слово"] * 200
        text = " ".join(words)
        result = add_timestamps(text, duration=120.0)
        # Should have [00:00], [00:30], [01:00] approximately
        assert "[00:00]" in result
        # At word 75 (2.5*30), we get [00:30]
        assert "[00:30]" in result

    def test_very_long_has_multiple_timestamps(self):
        words = ["тест"] * 500
        text = " ".join(words)
        result = add_timestamps(text, duration=300.0)
        # 500 words / 75 words per interval = ~6 intervals
        assert result.count("[") >= 5

    def test_short_text_long_duration_no_timestamps(self):
        # Only 10 words but 90s duration — probably Whisper summarized
        text = "Это очень короткий текст из десяти слов всего"
        result = add_timestamps(text, duration=90.0)
        # < 20 words → no timestamps
        assert "[00:00]" not in result

    def test_exactly_threshold_no_timestamps(self):
        text = "слово " * 50
        # duration exactly at threshold
        result = add_timestamps(text.strip(), duration=MIN_DURATION_FOR_TIMESTAMPS - 0.1)
        assert "[00:00]" not in result

    def test_just_above_threshold_has_timestamps(self):
        words = ["слово"] * 80
        text = " ".join(words)
        result = add_timestamps(text, duration=MIN_DURATION_FOR_TIMESTAMPS + 1)
        assert "[00:00]" in result

    def test_empty_text(self):
        result = add_timestamps("", duration=120.0)
        assert result == ""

    def test_preserves_original_words(self):
        text = "первое второе третье четвёртое пятое"
        # Short duration — no change
        result = add_timestamps(text, duration=10.0)
        assert result == text
