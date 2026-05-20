"""Approximate timestamps for long voice transcriptions.

Whisper standard API doesn't return word-level timestamps.
We estimate them based on average speech rate (~150 words/minute in Russian).

For voice messages > 60s, we insert [mm:ss] markers every ~30 seconds
to help users navigate long transcriptions.
"""
from __future__ import annotations

# Average speech rate: ~2.5 words/second (150 wpm) for Russian
_WORDS_PER_SECOND = 2.5

# Insert timestamp every N seconds
_TIMESTAMP_INTERVAL_SEC = 30

# Minimum duration to add timestamps
MIN_DURATION_FOR_TIMESTAMPS = 60  # seconds


_EXISTING_TIMESTAMP_RE = __import__("re").compile(r"\[\d{2}:\d{2}\]")
# Стрипа для пайплайнов, которые НЕ хотят таймкоды (task_list AI и т.п.):
# Yandex async STT (>30s) встраивает [MM:SS] в текст. Когда мы потом
# подаём такой текст в AI как список — таймкоды попадают в каждый пункт.
_STRIP_TIMESTAMP_RE = __import__("re").compile(r"\s*\[\d{2}:\d{2}\]\s*")


def strip_timestamps(text: str) -> str:
    """Убрать [MM:SS] маркеры, заменив их на переносы строк.

    Yandex async STT ставит [MM:SS] на границах chunks — это
    естественные точки разреза (паузы). Заменяя на \\n, мы сохраняем
    структуру, что важно для AI-классификатора голосового списка:
    одна строка без переносов → AI делает один пункт; многострочное
    → парсит как список.
    """
    out = _STRIP_TIMESTAMP_RE.sub("\n", text).strip()
    # Коллапсируем подряд идущие пустые строки и срезаем пробелы по краям.
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return "\n".join(lines)


def add_timestamps(text: str, duration: float | None) -> str:
    """Add approximate [mm:ss] timestamps to long transcription.

    Args:
        text: Transcribed text
        duration: Voice message duration in seconds

    Returns:
        Text with [mm:ss] markers, or original text if too short
    """
    if not text or not duration or duration < MIN_DURATION_FOR_TIMESTAMPS:
        return text

    # Если в тексте уже есть таймкоды (от Yandex Async реальные) — не дублируем.
    if _EXISTING_TIMESTAMP_RE.search(text):
        return text

    words = text.split()
    if not words:
        return text

    total_words = len(words)
    words_per_interval = int(_WORDS_PER_SECOND * _TIMESTAMP_INTERVAL_SEC)

    # Don't add timestamps if text is very short for the duration
    # (probably Whisper compressed/summarized)
    if total_words < 20:
        return text

    result_parts: list[str] = []
    result_parts.append("[00:00] ")

    for i, word in enumerate(words):
        result_parts.append(word)
        result_parts.append(" ")

        # Check if we should insert a timestamp after this word
        word_position = i + 1
        if word_position % words_per_interval == 0 and word_position < total_words:
            seconds_elapsed = word_position / _WORDS_PER_SECOND
            minutes = int(seconds_elapsed // 60)
            secs = int(seconds_elapsed % 60)
            result_parts.append(f"\n[{minutes:02d}:{secs:02d}] ")

    return "".join(result_parts).strip()
