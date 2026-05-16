"""Integration tests for Phase 3D voice features (todo, search, timestamps, auto-tag)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_message(mock_message):
    """Extended mock message for voice tests."""
    return mock_message


@pytest.fixture
def voice_message(mock_message):
    """Create a voice message with STT mocked."""
    def _make(duration=10, file_size=1000, text="тестовый текст"):
        msg = mock_message()
        msg.voice = MagicMock()
        msg.voice.file_id = "voice_123"
        msg.voice.duration = duration
        msg.voice.file_size = file_size
        msg.caption = None
        return msg, text
    return _make


class TestVoiceTodo:
    """Voice message detected as todo → creates task list."""

    @pytest.mark.asyncio
    async def test_todo_prefix_creates_task_list(self, mock_message, mock_api):
        """Voice starting with 'список задач' → task list bookmark."""
        msg = mock_message()
        msg.voice = MagicMock()
        msg.voice.file_id = "voice_todo"
        msg.voice.duration = 8
        msg.voice.file_size = 5000
        msg.caption = None

        transcribed_text = "список задач купить молоко, хлеб, сыр"

        with patch("bot.handlers.media._get_stt") as mock_stt_fn, \
             patch("bot.common.auth.ensure_user", return_value="test-jwt"), \
             patch("bot.handlers.settings.is_silent", return_value=False):

            stt = AsyncMock()
            stt.transcribe = AsyncMock(return_value=transcribed_text)
            mock_stt_fn.return_value = stt

            # Mock bot.get_file
            file_mock = MagicMock()
            file_mock.file_path = "voice/file.ogg"
            msg.bot.get_file = AsyncMock(return_value=file_mock)
            msg.bot.download_file = AsyncMock()

            from bot.handlers.media import handle_voice
            await handle_voice(msg, mock_api)

            # Should reply with 📋 prefix (todo marker)
            msg.reply.assert_called()
            reply_text = msg.reply.call_args[0][0]
            assert "📋" in reply_text
            assert transcribed_text in reply_text

            # Should create bookmark with "список задач:" prefix for backend detection
            mock_api.create_bookmark.assert_called_once()
            call_kwargs = mock_api.create_bookmark.call_args[1]
            assert "список задач:" in call_kwargs["raw_text"]
            assert call_kwargs["voice_tag"] is True
            assert call_kwargs["content_type"] == "voice"

    @pytest.mark.asyncio
    async def test_todo_nado_sdelat(self, mock_message, mock_api):
        """Voice starting with 'надо сделать' → todo."""
        msg = mock_message()
        msg.voice = MagicMock()
        msg.voice.file_id = "voice_todo2"
        msg.voice.duration = 5
        msg.voice.file_size = 3000
        msg.caption = None

        transcribed_text = "надо сделать ревью кода и деплой"

        with patch("bot.handlers.media._get_stt") as mock_stt_fn, \
             patch("bot.common.auth.ensure_user", return_value="test-jwt"), \
             patch("bot.handlers.settings.is_silent", return_value=False):

            stt = AsyncMock()
            stt.transcribe = AsyncMock(return_value=transcribed_text)
            mock_stt_fn.return_value = stt

            file_mock = MagicMock()
            file_mock.file_path = "voice/file.ogg"
            msg.bot.get_file = AsyncMock(return_value=file_mock)
            msg.bot.download_file = AsyncMock()

            from bot.handlers.media import handle_voice
            await handle_voice(msg, mock_api)

            # Should be todo
            reply_text = msg.reply.call_args[0][0]
            assert "📋" in reply_text


class TestVoiceSearch:
    """Short voice with search intent → search results."""

    @pytest.mark.asyncio
    async def test_search_prefix_triggers_search(self, mock_message, mock_api):
        """Voice starting with 'найди' → search."""
        msg = mock_message()
        msg.voice = MagicMock()
        msg.voice.file_id = "voice_search"
        msg.voice.duration = 3
        msg.voice.file_size = 2000
        msg.caption = None

        transcribed_text = "найди закладки про React"

        mock_api.search_bookmarks = AsyncMock(return_value={
            "results": [
                {"bookmark": {"title": "React Guide", "raw_text": "...", "tags": [], "url": None, "summary": "React intro"}, "score": 0.9},
            ],
            "total": 1,
        })

        with patch("bot.handlers.media._get_stt") as mock_stt_fn, \
             patch("bot.common.auth.ensure_user", return_value="test-jwt"), \
             patch("bot.handlers.settings.is_silent", return_value=False):

            stt = AsyncMock()
            stt.transcribe = AsyncMock(return_value=transcribed_text)
            mock_stt_fn.return_value = stt

            file_mock = MagicMock()
            file_mock.file_path = "voice/file.ogg"
            msg.bot.get_file = AsyncMock(return_value=file_mock)
            msg.bot.download_file = AsyncMock()

            from bot.handlers.media import handle_voice
            await handle_voice(msg, mock_api)

            # Should reply with 🔍 prefix
            msg.reply.assert_called()
            reply_text = msg.reply.call_args[0][0]
            assert "🔍" in reply_text

            # Should call search
            mock_api.search_bookmarks.assert_called_once()
            search_query = mock_api.search_bookmarks.call_args[0][1]
            assert "React" in search_query or "закладки про React" in search_query

            # Should NOT create a bookmark
            mock_api.create_bookmark.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_no_results(self, mock_message, mock_api):
        """Voice search with no results → 'ничего не найдено'."""
        msg = mock_message()
        msg.voice = MagicMock()
        msg.voice.file_id = "voice_search2"
        msg.voice.duration = 3
        msg.voice.file_size = 2000
        msg.caption = None

        transcribed_text = "поищи несуществующее"

        mock_api.search_bookmarks = AsyncMock(return_value={"results": [], "total": 0})

        with patch("bot.handlers.media._get_stt") as mock_stt_fn, \
             patch("bot.common.auth.ensure_user", return_value="test-jwt"), \
             patch("bot.handlers.settings.is_silent", return_value=False):

            stt = AsyncMock()
            stt.transcribe = AsyncMock(return_value=transcribed_text)
            mock_stt_fn.return_value = stt

            file_mock = MagicMock()
            file_mock.file_path = "voice/file.ogg"
            msg.bot.get_file = AsyncMock(return_value=file_mock)
            msg.bot.download_file = AsyncMock()

            from bot.handlers.media import handle_voice
            await handle_voice(msg, mock_api)

            # Should show "not found" message
            msg.answer.assert_called()
            answer_text = msg.answer.call_args[0][0]
            assert "не найдено" in answer_text.lower()


class TestVoiceAutoTag:
    """All voice bookmarks get #voice tag."""

    @pytest.mark.asyncio
    async def test_note_gets_voice_tag(self, mock_message, mock_api):
        """Regular voice note → voice_tag=True in API call."""
        msg = mock_message()
        msg.voice = MagicMock()
        msg.voice.file_id = "voice_note"
        msg.voice.duration = 15
        msg.voice.file_size = 10000
        msg.caption = None

        transcribed_text = "Сегодня обсудили архитектуру нового сервиса"

        with patch("bot.handlers.media._get_stt") as mock_stt_fn, \
             patch("bot.common.auth.ensure_user", return_value="test-jwt"), \
             patch("bot.handlers.settings.is_silent", return_value=False):

            stt = AsyncMock()
            stt.transcribe = AsyncMock(return_value=transcribed_text)
            mock_stt_fn.return_value = stt

            file_mock = MagicMock()
            file_mock.file_path = "voice/file.ogg"
            msg.bot.get_file = AsyncMock(return_value=file_mock)
            msg.bot.download_file = AsyncMock()

            from bot.handlers.media import handle_voice
            await handle_voice(msg, mock_api)

            # Should pass voice_tag=True
            mock_api.create_bookmark.assert_called_once()
            call_kwargs = mock_api.create_bookmark.call_args[1]
            assert call_kwargs["voice_tag"] is True


class TestVoiceTimestamps:
    """Long voice messages get [mm:ss] timestamps."""

    @pytest.mark.asyncio
    async def test_long_voice_has_timestamps_in_reply(self, mock_message, mock_api):
        """Voice > 60s → reply includes [00:00] markers."""
        msg = mock_message()
        msg.voice = MagicMock()
        msg.voice.file_id = "voice_long"
        msg.voice.duration = 90
        msg.voice.file_size = 500000
        msg.caption = None

        # Simulate ~90s of speech (~225 words at 2.5 words/sec)
        transcribed_text = " ".join(["слово"] * 225)

        with patch("bot.handlers.media._get_stt") as mock_stt_fn, \
             patch("bot.common.auth.ensure_user", return_value="test-jwt"), \
             patch("bot.handlers.settings.is_silent", return_value=False):

            stt = AsyncMock()
            stt.transcribe = AsyncMock(return_value=transcribed_text)
            mock_stt_fn.return_value = stt

            file_mock = MagicMock()
            file_mock.file_path = "voice/file.ogg"
            msg.bot.get_file = AsyncMock(return_value=file_mock)
            msg.bot.download_file = AsyncMock()

            from bot.handlers.media import handle_voice
            await handle_voice(msg, mock_api)

            # Reply should have timestamps
            reply_text = msg.reply.call_args[0][0]
            assert "[00:00]" in reply_text
            assert "[00:30]" in reply_text

    @pytest.mark.asyncio
    async def test_short_voice_no_timestamps(self, mock_message, mock_api):
        """Voice < 60s → no timestamps."""
        msg = mock_message()
        msg.voice = MagicMock()
        msg.voice.file_id = "voice_short"
        msg.voice.duration = 20
        msg.voice.file_size = 50000
        msg.caption = None

        transcribed_text = "Короткое ��ообщение без таймстемпов"

        with patch("bot.handlers.media._get_stt") as mock_stt_fn, \
             patch("bot.common.auth.ensure_user", return_value="test-jwt"), \
             patch("bot.handlers.settings.is_silent", return_value=False):

            stt = AsyncMock()
            stt.transcribe = AsyncMock(return_value=transcribed_text)
            mock_stt_fn.return_value = stt

            file_mock = MagicMock()
            file_mock.file_path = "voice/file.ogg"
            msg.bot.get_file = AsyncMock(return_value=file_mock)
            msg.bot.download_file = AsyncMock()

            from bot.handlers.media import handle_voice
            await handle_voice(msg, mock_api)

            # Reply should NOT have timestamps
            reply_text = msg.reply.call_args[0][0]
            assert "[00:00]" not in reply_text
