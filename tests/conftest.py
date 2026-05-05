"""Shared test fixtures for BookmarkBrain tests."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest


@pytest.fixture
def mock_message():
    """Create a mock Telegram Message with sane defaults."""

    def _make(
        chat_id: int = 100,
        message_id: int = 42,
        user_id: int = 999,
        username: str = "testuser",
    ):
        msg = AsyncMock()
        msg.chat = MagicMock()
        msg.chat.id = chat_id
        msg.message_id = message_id
        msg.from_user = MagicMock()
        msg.from_user.id = user_id
        msg.from_user.username = username
        msg.from_user.first_name = "Test"
        msg.caption = None

        # reply returns a mock message
        reply_msg = AsyncMock()
        reply_msg.chat = MagicMock()
        reply_msg.chat.id = chat_id
        reply_msg.message_id = message_id + 1
        reply_msg.delete = AsyncMock()
        msg.reply = AsyncMock(return_value=reply_msg)

        # react returns True by default
        msg.react = AsyncMock()

        # bot mock
        msg.bot = AsyncMock()

        # delete
        msg.delete = AsyncMock()
        msg.answer = AsyncMock()

        return msg

    return _make


@pytest.fixture
def mock_api():
    """Create a mock BackendClient."""
    api = AsyncMock()
    api.get_or_create_user = AsyncMock(return_value={"access_token": "test-jwt"})
    api.get_me = AsyncMock(return_value={"settings": {}})
    api.create_bookmark = AsyncMock(return_value={"id": "test-bid"})
    return api


@pytest.fixture
def mock_store():
    """Create a mock StateStore."""
    return AsyncMock()
