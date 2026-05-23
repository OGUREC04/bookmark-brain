"""Tests for Phase 3A voice handler edge cases.

Covers all 5 fixed corner cases:
1. Short voice (<2s) — reject before STT
2. Large file (>20 MB) — reject with clear message
3. Backend fail after STT — graceful, keep transcription visible
4. Group fallback — text hint when reactions blocked
5. STT not configured — clear error message
Plus: happy path, STT error handling, file cleanup.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# We test _process_audio directly to avoid module-level import issues
# with aiogram router decorators


@pytest.fixture(autouse=True)
def reset_stt_singleton():
    """Reset the module-level _stt singleton between tests."""
    import bot.handlers.media as media_mod

    media_mod._stt = None
    media_mod._stt_checked = False
    yield
    media_mod._stt = None
    media_mod._stt_checked = False


@pytest.fixture
def fake_stt():
    """A mock STT service that returns canned text."""
    stt = AsyncMock()
    stt.transcribe = AsyncMock(return_value="Тестовая транскрипция голосового сообщения")
    return stt


# ─── Edge Case 1: Short voice (<2 seconds) ───────────────────


@pytest.mark.asyncio
async def test_short_voice_rejected(mock_message, mock_api, mock_store):
    """Voice <2s should be rejected without calling STT."""
    import bot.handlers.media as media_mod
    from bot.handlers.media import _MIN_DURATION_SEC, _process_audio

    # Set up STT so we can verify it's NOT called
    fake_stt = AsyncMock()
    media_mod._stt = fake_stt

    msg = mock_message()

    # Короткое голосовое теперь шлётся через message.reply, не ephemeral_error
    # (ошибки больше не auto-delete после Phase 2 фидбека).
    msg.reply = AsyncMock()
    await _process_audio(
        message=msg,
        api=mock_api,
        store=mock_store,
        file_id="test_file_id",
        duration=1,  # <2 seconds
        file_size=5000,
        content_type="voice",
        ext=".ogg",
    )

    # STT should NOT be called
    fake_stt.transcribe.assert_not_called()
    # Reply should mention "короткое"
    msg.reply.assert_called_once()
    assert "короткое" in msg.reply.call_args[0][0]


@pytest.mark.asyncio
async def test_exactly_2s_voice_not_rejected(mock_message, mock_api, mock_store):
    """Voice exactly at 2s threshold should proceed (not rejected)."""
    import bot.handlers.media as media_mod
    from bot.handlers.media import _process_audio

    fake_stt = AsyncMock()
    fake_stt.transcribe = AsyncMock(return_value="Текст")
    media_mod._stt = fake_stt

    msg = mock_message()
    # Mock file download
    file_mock = MagicMock()
    file_mock.file_path = "voice/file.ogg"
    msg.bot.get_file = AsyncMock(return_value=file_mock)
    msg.bot.download_file = AsyncMock()

    with (
        patch("bot.handlers.media.safe_react", new_callable=AsyncMock, return_value=True),
        patch("bot.handlers.media.ephemeral_error", new_callable=AsyncMock),
        patch("bot.common.auth.ensure_user", new_callable=AsyncMock, return_value="jwt"),
        patch("bot.handlers.settings.is_silent", new_callable=AsyncMock, return_value=False),
    ):
        await _process_audio(
            message=msg,
            api=mock_api,
            store=mock_store,
            file_id="test_file_id",
            duration=2,  # exactly 2s — should pass
            file_size=5000,
            content_type="voice",
            ext=".ogg",
        )

    # STT SHOULD be called (duration >= 2)
    fake_stt.transcribe.assert_called_once()


@pytest.mark.asyncio
async def test_none_duration_not_rejected(mock_message, mock_api, mock_store):
    """Voice with duration=None (unknown) should proceed."""
    import bot.handlers.media as media_mod
    from bot.handlers.media import _process_audio

    fake_stt = AsyncMock()
    fake_stt.transcribe = AsyncMock(return_value="Текст")
    media_mod._stt = fake_stt

    msg = mock_message()
    file_mock = MagicMock()
    file_mock.file_path = "voice/file.ogg"
    msg.bot.get_file = AsyncMock(return_value=file_mock)
    msg.bot.download_file = AsyncMock()

    with (
        patch("bot.handlers.media.safe_react", new_callable=AsyncMock, return_value=True),
        patch("bot.handlers.media.ephemeral_error", new_callable=AsyncMock),
        patch("bot.common.auth.ensure_user", new_callable=AsyncMock, return_value="jwt"),
        patch("bot.handlers.settings.is_silent", new_callable=AsyncMock, return_value=False),
    ):
        await _process_audio(
            message=msg,
            api=mock_api,
            store=mock_store,
            file_id="test_file_id",
            duration=None,  # unknown duration
            file_size=5000,
            content_type="voice",
            ext=".ogg",
        )

    fake_stt.transcribe.assert_called_once()


# ─── Edge Case 2: Large file (>20 MB) ────────────────────────


@pytest.mark.asyncio
async def test_large_file_rejected(mock_message, mock_api, mock_store):
    """File >20 MB should be rejected with clear size message."""
    import bot.handlers.media as media_mod
    from bot.handlers.media import _TG_MAX_FILE_SIZE, _process_audio

    fake_stt = AsyncMock()
    media_mod._stt = fake_stt

    msg = mock_message()

    with patch("bot.handlers.media.ephemeral_error", new_callable=AsyncMock) as mock_err:
        await _process_audio(
            message=msg,
            api=mock_api,
            store=mock_store,
            file_id="test_file_id",
            duration=30,
            file_size=25 * 1024 * 1024,  # 25 MB > 20 MB limit
            content_type="voice",
            ext=".ogg",
        )

    fake_stt.transcribe.assert_not_called()
    mock_err.assert_called_once()
    error_text = mock_err.call_args[0][1]
    assert "большой" in error_text
    assert "20" in error_text


@pytest.mark.asyncio
async def test_file_at_limit_not_rejected(mock_message, mock_api, mock_store):
    """File exactly at 20 MB should proceed."""
    import bot.handlers.media as media_mod
    from bot.handlers.media import _TG_MAX_FILE_SIZE, _process_audio

    fake_stt = AsyncMock()
    fake_stt.transcribe = AsyncMock(return_value="Текст")
    media_mod._stt = fake_stt

    msg = mock_message()
    file_mock = MagicMock()
    file_mock.file_path = "voice/file.ogg"
    msg.bot.get_file = AsyncMock(return_value=file_mock)
    msg.bot.download_file = AsyncMock()

    with (
        patch("bot.handlers.media.safe_react", new_callable=AsyncMock, return_value=True),
        patch("bot.handlers.media.ephemeral_error", new_callable=AsyncMock),
        patch("bot.common.auth.ensure_user", new_callable=AsyncMock, return_value="jwt"),
        patch("bot.handlers.settings.is_silent", new_callable=AsyncMock, return_value=False),
    ):
        await _process_audio(
            message=msg,
            api=mock_api,
            store=mock_store,
            file_id="test_file_id",
            duration=30,
            file_size=_TG_MAX_FILE_SIZE,  # exactly at limit — should pass
            content_type="voice",
            ext=".ogg",
        )

    fake_stt.transcribe.assert_called_once()


# ─── Edge Case 3: Backend fail after STT ─────────────────────


@pytest.mark.asyncio
async def test_backend_fail_keeps_transcription(mock_message, mock_api, mock_store):
    """If backend fails after STT, transcription reply should stay visible."""
    import bot.handlers.media as media_mod
    from bot.handlers.media import _process_audio

    fake_stt = AsyncMock()
    fake_stt.transcribe = AsyncMock(return_value="Важный текст из голосового")
    media_mod._stt = fake_stt

    msg = mock_message()
    file_mock = MagicMock()
    file_mock.file_path = "voice/file.ogg"
    msg.bot.get_file = AsyncMock(return_value=file_mock)
    msg.bot.download_file = AsyncMock()

    # Backend will fail
    mock_api.create_bookmark = AsyncMock(side_effect=Exception("Backend timeout"))

    with (
        patch("bot.handlers.media.safe_react", new_callable=AsyncMock, return_value=True),
        patch("bot.handlers.media.ephemeral_error", new_callable=AsyncMock) as mock_err,
        patch("bot.common.auth.ensure_user", new_callable=AsyncMock, return_value="jwt"),
        patch("bot.handlers.settings.is_silent", new_callable=AsyncMock, return_value=False),
    ):
        await _process_audio(
            message=msg,
            api=mock_api,
            store=mock_store,
            file_id="test_file_id",
            duration=10,
            file_size=5000,
            content_type="voice",
            ext=".ogg",
        )

    # Transcription reply SHOULD have been sent before backend call
    msg.reply.assert_called_once_with("Важный текст из голосового", parse_mode=None)

    # Error should mention "скопировать", NOT show thumbs-down reaction
    mock_err.assert_called_once()
    error_text = mock_err.call_args[0][1]
    assert "скопировать" in error_text or "Текст выше" in error_text

    # Error should have longer delay (15s)
    assert mock_err.call_args[1].get("delay") == 15


# ─── Edge Case 4: Group fallback when reactions blocked ───────


@pytest.mark.asyncio
async def test_group_fallback_when_reactions_fail(mock_message, mock_api, mock_store):
    """In groups where reactions are blocked, send text fallback."""
    import bot.handlers.media as media_mod
    from bot.handlers.media import _process_audio

    fake_stt = AsyncMock()
    fake_stt.transcribe = AsyncMock(return_value="Текст из группы")
    media_mod._stt = fake_stt

    msg = mock_message()
    file_mock = MagicMock()
    file_mock.file_path = "voice/file.ogg"
    msg.bot.get_file = AsyncMock(return_value=file_mock)
    msg.bot.download_file = AsyncMock()

    # Track reply calls to distinguish "Распознаю..." from transcription
    reply_calls = []
    hint_msg = AsyncMock()
    hint_msg.delete = AsyncMock()

    async def track_reply(text, **kwargs):
        reply_calls.append(text)
        if text == "Распознаю...":
            return hint_msg
        result = AsyncMock()
        result.chat = MagicMock()
        result.chat.id = 100
        result.message_id = 43
        return result

    msg.reply = AsyncMock(side_effect=track_reply)

    with (
        # safe_react returns False — reactions not available
        patch("bot.handlers.media.safe_react", new_callable=AsyncMock, return_value=False),
        patch("bot.handlers.media.ephemeral_error", new_callable=AsyncMock),
        patch("bot.common.auth.ensure_user", new_callable=AsyncMock, return_value="jwt"),
        patch("bot.handlers.settings.is_silent", new_callable=AsyncMock, return_value=False),
    ):
        await _process_audio(
            message=msg,
            api=mock_api,
            store=mock_store,
            file_id="test_file_id",
            duration=10,
            file_size=5000,
            content_type="voice",
            ext=".ogg",
        )

    # Should have sent "Распознаю..." hint first
    assert "Распознаю..." in reply_calls
    # Then transcription
    assert "Текст из группы" in reply_calls
    # Hint should be deleted after transcription
    hint_msg.delete.assert_called_once()


@pytest.mark.asyncio
async def test_private_chat_uses_reaction_not_text(mock_message, mock_api, mock_store):
    """In private chat where reactions work, no text hint is sent."""
    import bot.handlers.media as media_mod
    from bot.handlers.media import _process_audio

    fake_stt = AsyncMock()
    fake_stt.transcribe = AsyncMock(return_value="Текст")
    media_mod._stt = fake_stt

    msg = mock_message()
    file_mock = MagicMock()
    file_mock.file_path = "voice/file.ogg"
    msg.bot.get_file = AsyncMock(return_value=file_mock)
    msg.bot.download_file = AsyncMock()

    reply_calls = []

    async def track_reply(text, **kwargs):
        reply_calls.append(text)
        result = AsyncMock()
        result.chat = MagicMock()
        result.chat.id = 100
        result.message_id = 43
        return result

    msg.reply = AsyncMock(side_effect=track_reply)

    with (
        # safe_react returns True — reactions work
        patch("bot.handlers.media.safe_react", new_callable=AsyncMock, return_value=True),
        patch("bot.handlers.media.ephemeral_error", new_callable=AsyncMock),
        patch("bot.common.auth.ensure_user", new_callable=AsyncMock, return_value="jwt"),
        patch("bot.handlers.settings.is_silent", new_callable=AsyncMock, return_value=False),
    ):
        await _process_audio(
            message=msg,
            api=mock_api,
            store=mock_store,
            file_id="test_file_id",
            duration=10,
            file_size=5000,
            content_type="voice",
            ext=".ogg",
        )

    # "Распознаю..." should NOT be in replies
    assert "Распознаю..." not in reply_calls
    # Only transcription reply
    assert "Текст" in reply_calls


# ─── Edge Case 5: STT not configured ─────────────────────────


@pytest.mark.asyncio
async def test_stt_not_configured(mock_message, mock_api, mock_store):
    """When WHISPER_API_KEY is empty, show clear error."""
    import bot.handlers.media as media_mod
    from bot.handlers.media import _process_audio

    # Ensure STT is None (no key)
    media_mod._stt = None
    media_mod._stt_checked = False

    msg = mock_message()

    # Патчим _get_stt напрямую — поддержка multi-provider (yandex/openai/groq)
    # делает патч одной ENV-переменной ненадёжным.
    with (
        patch("bot.handlers.media._get_stt", return_value=None),
        patch("bot.handlers.media.ephemeral_error", new_callable=AsyncMock) as mock_err,
    ):
        await _process_audio(
            message=msg,
            api=mock_api,
            store=mock_store,
            file_id="test_file_id",
            duration=10,
            file_size=5000,
            content_type="voice",
            ext=".ogg",
        )

    mock_err.assert_called_once()
    assert "не поддерживаются" in mock_err.call_args[0][1]


# ─── Happy Path ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_voice(mock_message, mock_api, mock_store):
    """Full successful flow: download → STT → reply → bookmark."""
    import bot.handlers.media as media_mod
    from bot.handlers.media import _process_audio

    transcription = "Купи молоко и хлеб по дороге домой"
    fake_stt = AsyncMock()
    fake_stt.transcribe = AsyncMock(return_value=transcription)
    media_mod._stt = fake_stt

    msg = mock_message()
    file_mock = MagicMock()
    file_mock.file_path = "voice/file.ogg"
    msg.bot.get_file = AsyncMock(return_value=file_mock)
    msg.bot.download_file = AsyncMock()

    with (
        patch("bot.handlers.media.safe_react", new_callable=AsyncMock, return_value=True),
        patch("bot.handlers.media.ephemeral_error", new_callable=AsyncMock) as mock_err,
        patch("bot.common.auth.ensure_user", new_callable=AsyncMock, return_value="jwt"),
        patch("bot.handlers.settings.is_silent", new_callable=AsyncMock, return_value=False),
    ):
        await _process_audio(
            message=msg,
            api=mock_api,
            store=mock_store,
            file_id="test_file_id_abc",
            duration=10,
            file_size=50000,
            content_type="voice",
            ext=".ogg",
        )

    # Reply with transcription
    msg.reply.assert_called_once_with(transcription, parse_mode=None)

    # Bookmark created with correct params
    mock_api.create_bookmark.assert_called_once()
    call_kwargs = mock_api.create_bookmark.call_args[1]
    assert call_kwargs["raw_text"] == transcription
    assert call_kwargs["content_type"] == "voice"
    assert call_kwargs["media_file_id"] == "test_file_id_abc"
    assert call_kwargs["transcription"] == transcription
    assert call_kwargs["media_duration"] == 10.0
    assert call_kwargs["source"] == "telegram"

    # No errors
    mock_err.assert_not_called()


@pytest.mark.asyncio
async def test_happy_path_with_caption(mock_message, mock_api, mock_store):
    """Voice with caption: caption prepended to transcription in raw_text."""
    import bot.handlers.media as media_mod
    from bot.handlers.media import _process_audio

    transcription = "длинное описание проекта"
    fake_stt = AsyncMock()
    fake_stt.transcribe = AsyncMock(return_value=transcription)
    media_mod._stt = fake_stt

    msg = mock_message()
    msg.caption = "Заметка про работу"
    file_mock = MagicMock()
    file_mock.file_path = "voice/file.ogg"
    msg.bot.get_file = AsyncMock(return_value=file_mock)
    msg.bot.download_file = AsyncMock()

    with (
        patch("bot.handlers.media.safe_react", new_callable=AsyncMock, return_value=True),
        patch("bot.handlers.media.ephemeral_error", new_callable=AsyncMock),
        patch("bot.common.auth.ensure_user", new_callable=AsyncMock, return_value="jwt"),
        patch("bot.handlers.settings.is_silent", new_callable=AsyncMock, return_value=False),
    ):
        await _process_audio(
            message=msg,
            api=mock_api,
            store=mock_store,
            file_id="test_file_id",
            duration=10,
            file_size=5000,
            content_type="voice",
            ext=".ogg",
        )

    call_kwargs = mock_api.create_bookmark.call_args[1]
    # raw_text should be caption + transcription
    assert call_kwargs["raw_text"] == "Заметка про работу\n\nдлинное описание проекта"
    # transcription stays pure (without caption)
    assert call_kwargs["transcription"] == transcription


# ─── STT Service Tests ───────────────────────────────────────


class TestWhisperSTTService:
    """Tests for the STT service itself."""

    def test_init_with_empty_key_raises(self):
        from bot.services.stt import WhisperSTTService

        with pytest.raises(ValueError, match="WHISPER_API_KEY"):
            WhisperSTTService("", provider="groq")

    def test_init_openai_provider(self):
        from bot.services.stt import WhisperSTTService

        svc = WhisperSTTService("test-key", provider="openai")
        assert "openai.com" in svc._url
        assert svc._model == "whisper-1"

    def test_init_groq_provider(self):
        from bot.services.stt import WhisperSTTService

        svc = WhisperSTTService("test-key", provider="groq")
        assert "groq.com" in svc._url
        assert svc._model == "whisper-large-v3"

    def test_init_unknown_provider_falls_back_to_openai(self):
        from bot.services.stt import WhisperSTTService

        svc = WhisperSTTService("test-key", provider="unknown_provider")
        assert "openai.com" in svc._url

    @pytest.mark.asyncio
    async def test_transcribe_missing_file(self, tmp_path):
        from bot.services.stt import STTError, WhisperSTTService

        svc = WhisperSTTService("test-key")
        with pytest.raises(STTError, match="not found"):
            await svc.transcribe(tmp_path / "nonexistent.ogg")

    @pytest.mark.asyncio
    async def test_transcribe_empty_file(self, tmp_path):
        from bot.services.stt import STTError, WhisperSTTService

        empty_file = tmp_path / "empty.ogg"
        empty_file.write_bytes(b"")
        svc = WhisperSTTService("test-key")
        with pytest.raises(STTError, match="empty"):
            await svc.transcribe(empty_file)

    @pytest.mark.asyncio
    async def test_transcribe_oversized_file(self, tmp_path):
        from bot.services.stt import _MAX_FILE_SIZE_WHISPER, STTError, WhisperSTTService

        big_file = tmp_path / "big.ogg"
        # Create a file just over the limit (write sparse)
        big_file.write_bytes(b"x" * (_MAX_FILE_SIZE_WHISPER + 1))
        svc = WhisperSTTService("test-key")
        with pytest.raises(STTError, match="too large"):
            await svc.transcribe(big_file)
