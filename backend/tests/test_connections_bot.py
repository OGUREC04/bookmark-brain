"""Тесты бот-части связей — задача 8 (без сети/Telegram).

api_client.get_related (правильный путь/параметры/авторизация) +
хелпер _related_view (список связанных с tap-to-open + «Назад»).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from bot.api_client import BackendClient
from bot.handlers.bookmark_view import _related_view


async def test_get_related_calls_endpoint():
    client = BackendClient.__new__(BackendClient)  # без реального __init__
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"items": [{"id": "x"}], "total": 3})
    client.client = MagicMock()
    client.client.get = AsyncMock(return_value=resp)

    out = await client.get_related("tok", "bid-1", limit=5)

    assert out == {"items": [{"id": "x"}], "total": 3}
    call = client.client.get.call_args
    assert call.args[0] == "/api/v1/bookmarks/bid-1/related"
    assert call.kwargs["params"] == {"limit": 5}
    assert call.kwargs["headers"]["Authorization"] == "Bearer tok"


def test_related_view_builds_buttons_and_back():
    items = [
        {"id": "id-1", "title": "Первая"},
        {"id": "id-2", "title": None},  # без названия
    ]
    text, kb = _related_view(items, "center-bid")

    assert "Похожие заметки" in text
    assert "Первая" in text and "Без названия" in text

    rows = kb.inline_keyboard
    assert len(rows) == 3  # 2 заметки + «Назад»
    assert rows[0][0].callback_data == "view:id-1"  # tap-to-open
    assert rows[1][0].callback_data == "view:id-2"
    assert rows[2][0].callback_data == "view:center-bid"  # назад к исходной заметке
