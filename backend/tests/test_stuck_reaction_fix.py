"""Регрессия bookmark-brain-yh3: 👀 не должен застревать, если
process_bookmark бросает исключение.

Корень бага: process_bookmark на RetryableError ставил ai_status='failed'
и делал raise (для ретрая arq). Исключение пролетало через
process_bookmark_task, где вызов НЕ был обёрнут → блок выставления финальной
реакции (👍/👎) не достигался → 👀 висел навсегда.

Фикс: safety-net в воркере. На последней попытке (job_try >= _PROCESS_MAX_TRIES)
ставим 👎 + сообщение; на промежуточных — re-raise (arq ретраит, 👀 ждёт).
"""
from __future__ import annotations

import contextlib
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

THUMBS_DOWN = "\U0001f44e"


def _async_session_factory(session):
    """Фабрика, имитирующая `async with async_session() as session:`."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


@contextlib.contextmanager
def _harness(processor_raises: Exception):
    """Патчит зависимости воркера; процессор бросает заданное исключение.

    Возвращает (set_reaction_mock, send_message_mock).
    """
    session = AsyncMock()
    processor = MagicMock()
    processor.process_bookmark = AsyncMock(side_effect=processor_raises)
    embedding_service = AsyncMock()  # .close() awaitable

    with patch("app.worker.processing._set_reaction") as set_reaction, \
            patch("app.worker.processing._send_message") as send_message, \
            patch("app.worker.processing._edit_message"), \
            patch("app.database.async_session", _async_session_factory(session)), \
            patch("app.services.ai_classifier.create_classifier", MagicMock()), \
            patch(
                "app.services.embeddings.create_embedding_service",
                MagicMock(return_value=embedding_service),
            ), \
            patch(
                "app.services.bookmark_processor.BookmarkProcessor",
                MagicMock(return_value=processor),
            ):
        yield set_reaction, send_message


@pytest.mark.asyncio
async def test_final_attempt_sets_thumbs_down_not_stuck_eyes():
    """Последняя попытка + silent: ставится 👎, сообщение, без re-raise."""
    from app.worker.processing import _PROCESS_MAX_TRIES, process_bookmark_task

    with _harness(RuntimeError("classifier transient down")) as (set_reaction, send_message):
        # Не должно бросить наружу на финальной попытке.
        await process_bookmark_task(
            {"job_try": _PROCESS_MAX_TRIES},
            str(uuid.uuid4()),
            chat_id=123, message_id=456, silent=True,
        )

        set_reaction.assert_awaited_once()
        args = set_reaction.await_args.args
        assert args[0] == 123 and args[1] == 456
        assert args[2] == THUMBS_DOWN, "на финальной ошибке должен стоять 👎, не застрявший 👀"
        # _send_message вызывается через asyncio.create_task (fire-and-forget):
        # вызов регистрируется сразу, await может не успеть к моменту проверки.
        send_message.assert_called()  # юзеру отправлено «не удалось обработать»


@pytest.mark.asyncio
async def test_non_final_attempt_reraises_for_retry():
    """Промежуточная попытка: re-raise (arq ретраит), 👎 НЕ ставится."""
    from app.worker.processing import process_bookmark_task

    with _harness(RuntimeError("transient")) as (set_reaction, _send_message):
        with pytest.raises(RuntimeError):
            await process_bookmark_task(
                {"job_try": 1},
                str(uuid.uuid4()),
                chat_id=123, message_id=456, silent=True,
            )

        # 👎 не ставим — 👀 остаётся как «ещё обрабатываю», задача уйдёт на ретрай.
        for call in set_reaction.await_args_list:
            assert call.args[2] != THUMBS_DOWN
