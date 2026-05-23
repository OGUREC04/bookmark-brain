"""Tests for STT service — multi-provider support (whisper, groq, yandex)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bot.services.stt import (
    _MAX_FILE_SIZE_YANDEX,
    STTError,
    WhisperSTTService,
    YandexSTTService,
    _validate_file,
    create_stt_service,
)

# ── Factory tests ─────────────────────────────────────────────


class TestCreateSTTService:
    def test_creates_whisper_for_openai(self):
        svc = create_stt_service("openai", whisper_api_key="sk-test")
        assert isinstance(svc, WhisperSTTService)

    def test_creates_whisper_for_groq(self):
        svc = create_stt_service("groq", whisper_api_key="gsk-test")
        assert isinstance(svc, WhisperSTTService)

    def test_creates_yandex(self):
        # Factory всегда возвращает Hybrid для yandex provider (sync + опциональный async).
        # Без S3 envs внутри только sync — длинные голосовые рестрикшен в media handler.
        from bot.services.stt import YandexHybridSTTService
        svc = create_stt_service(
            "yandex",
            yandex_api_key="AQVN-test",
            yandex_folder_id="b1g-test",
        )
        assert isinstance(svc, YandexHybridSTTService)

    def test_yandex_requires_api_key(self):
        with pytest.raises(ValueError, match="YANDEX_CLOUD_API_KEY"):
            create_stt_service("yandex", yandex_api_key="", yandex_folder_id="b1g")

    def test_yandex_requires_folder_id(self):
        with pytest.raises(ValueError, match="YANDEX_CLOUD_FOLDER_ID"):
            create_stt_service("yandex", yandex_api_key="key", yandex_folder_id="")

    def test_unknown_provider_defaults_to_openai(self):
        svc = create_stt_service("unknown", whisper_api_key="sk-test")
        assert isinstance(svc, WhisperSTTService)


# ── YandexSTTService tests ─────────────────────────────────────


class TestYandexSTTService:
    @pytest.fixture
    def svc(self):
        return YandexSTTService(api_key="AQVN-test", folder_id="b1g-test")

    @pytest.fixture
    def audio_file(self, tmp_path: Path) -> Path:
        p = tmp_path / "test.ogg"
        p.write_bytes(b"\x00" * 1024)  # 1KB fake audio
        return p

    @pytest.mark.asyncio
    async def test_transcribe_success(self, svc, audio_file):
        mock_response = httpx.Response(
            200,
            json={"result": "привет мир"},
            request=httpx.Request("POST", "https://stt.api.cloud.yandex.net"),
        )

        with patch("bot.services.stt.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            text = await svc.transcribe(audio_file)

        assert text == "привет мир"
        # Verify correct auth header
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Api-Key AQVN-test"
        # Verify folder_id in params
        assert call_kwargs.kwargs["params"]["folderId"] == "b1g-test"

    @pytest.mark.asyncio
    async def test_transcribe_api_error(self, svc, audio_file):
        mock_response = httpx.Response(
            400,
            json={"error": "bad request"},
            request=httpx.Request("POST", "https://stt.api.cloud.yandex.net"),
        )

        with patch("bot.services.stt.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(STTError, match="ошибка 400"):
                await svc.transcribe(audio_file)

    @pytest.mark.asyncio
    async def test_transcribe_empty_result(self, svc, audio_file):
        mock_response = httpx.Response(
            200,
            json={"result": ""},
            request=httpx.Request("POST", "https://stt.api.cloud.yandex.net"),
        )

        with patch("bot.services.stt.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(STTError, match="empty transcription"):
                await svc.transcribe(audio_file)

    @pytest.mark.asyncio
    async def test_transcribe_timeout(self, svc, audio_file):
        with patch("bot.services.stt.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(STTError, match="timeout"):
                await svc.transcribe(audio_file)

    @pytest.mark.asyncio
    async def test_file_too_large_for_yandex(self, svc, tmp_path):
        p = tmp_path / "big.ogg"
        p.write_bytes(b"\x00" * (_MAX_FILE_SIZE_YANDEX + 1))

        with pytest.raises(STTError, match="too large"):
            await svc.transcribe(p)

    @pytest.mark.asyncio
    async def test_file_not_found(self, svc, tmp_path):
        p = tmp_path / "missing.ogg"

        with pytest.raises(STTError, match="not found"):
            await svc.transcribe(p)

    @pytest.mark.asyncio
    async def test_custom_language(self, svc, audio_file):
        mock_response = httpx.Response(
            200,
            json={"result": "hello world"},
            request=httpx.Request("POST", "https://stt.api.cloud.yandex.net"),
        )

        with patch("bot.services.stt.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            text = await svc.transcribe(audio_file, language="en-US")

        assert text == "hello world"
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["params"]["lang"] == "en-US"


# ── Validation helper tests ────────────────────────────────────


class TestValidateFile:
    def test_missing_file(self, tmp_path):
        with pytest.raises(STTError, match="not found"):
            _validate_file(tmp_path / "nope.ogg", 1024)

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.ogg"
        p.write_bytes(b"")
        with pytest.raises(STTError, match="empty"):
            _validate_file(p, 1024)

    def test_oversized_file(self, tmp_path):
        p = tmp_path / "big.ogg"
        p.write_bytes(b"\x00" * 2048)
        with pytest.raises(STTError, match="too large"):
            _validate_file(p, 1024)

    def test_valid_file(self, tmp_path):
        p = tmp_path / "ok.ogg"
        p.write_bytes(b"\x00" * 512)
        _validate_file(p, 1024)  # Should not raise
