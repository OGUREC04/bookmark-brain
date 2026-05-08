"""Speech-to-Text service — multi-provider.

Supported providers:
- openai: OpenAI Whisper API (blocked from Russia)
- groq:   Groq Whisper API (blocked from Russia)
- yandex: Yandex SpeechKit (works in Russia/CIS)

Uses raw httpx for all providers.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_WHISPER_PROVIDERS = {
    "openai": {
        "url": "https://api.openai.com/v1/audio/transcriptions",
        "model": "whisper-1",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/audio/transcriptions",
        "model": "whisper-large-v3",
    },
}

# Whisper limits: 25 MB, Yandex: 1 MB
_MAX_FILE_SIZE_WHISPER = 25 * 1024 * 1024
_MAX_FILE_SIZE_YANDEX = 1 * 1024 * 1024

_YANDEX_STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"


class STTError(Exception):
    """Raised when transcription fails."""


class WhisperSTTService:
    """Transcribe audio files using OpenAI-compatible Whisper API via raw httpx."""

    def __init__(self, api_key: str, provider: str = "openai"):
        if not api_key:
            raise ValueError("WHISPER_API_KEY is not set")
        self._api_key = api_key
        cfg = _WHISPER_PROVIDERS.get(provider, _WHISPER_PROVIDERS["openai"])
        self._url = cfg["url"]
        self._model = cfg["model"]
        logger.info("STT provider: %s (%s)", provider, self._url)

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> str:
        _validate_file(audio_path, _MAX_FILE_SIZE_WHISPER)
        mime_type = _get_mime_type(audio_path)
        file_size = audio_path.stat().st_size

        data = {
            "model": self._model,
            "response_format": "text",
        }
        if language:
            data["language"] = language

        logger.info(
            "Transcribing %s (%.1f KB, %s)",
            audio_path.name, file_size / 1024, mime_type,
        )

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                with open(audio_path, "rb") as f:
                    response = await client.post(
                        self._url,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        data=data,
                        files={"file": (audio_path.name, f, mime_type)},
                    )

                if response.status_code != 200:
                    error_text = response.text[:500]
                    logger.error(
                        "Whisper API error %d: %s",
                        response.status_code, error_text,
                    )
                    raise STTError(
                        f"Не удалось распознать речь (ошибка {response.status_code})"
                    )

                text = response.text.strip()
                if not text:
                    raise STTError("Whisper returned empty transcription")

                logger.info("Transcription complete: %d chars", len(text))
                return text

        except STTError:
            raise
        except httpx.TimeoutException:
            raise STTError("Whisper API timeout (120s)")
        except httpx.HTTPError as e:
            raise STTError(f"HTTP error during transcription: {e}")


class YandexSTTService:
    """Transcribe audio via Yandex SpeechKit (works in Russia/CIS).

    API: POST https://stt.api.cloud.yandex.net/speech/v1/stt:recognize
    Auth: Api-Key header
    Body: raw binary audio (OGG Opus natively supported)
    Limits: 1 MB, 30 seconds
    """

    def __init__(self, api_key: str, folder_id: str):
        if not api_key:
            raise ValueError("YANDEX_CLOUD_API_KEY is not set")
        if not folder_id:
            raise ValueError("YANDEX_CLOUD_FOLDER_ID is not set")
        self._api_key = api_key
        self._folder_id = folder_id
        logger.info("STT provider: yandex (SpeechKit)")

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> str:
        _validate_file(audio_path, _MAX_FILE_SIZE_YANDEX)
        file_size = audio_path.stat().st_size
        lang = language or "ru-RU"

        logger.info(
            "Transcribing %s (%.1f KB) via Yandex SpeechKit",
            audio_path.name, file_size / 1024,
        )

        params = {
            "folderId": self._folder_id,
            "lang": lang,
            "format": "oggopus",
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                with open(audio_path, "rb") as f:
                    audio_data = f.read()

                response = await client.post(
                    _YANDEX_STT_URL,
                    params=params,
                    headers={
                        "Authorization": f"Api-Key {self._api_key}",
                        "Content-Type": "application/octet-stream",
                    },
                    content=audio_data,
                )

                if response.status_code != 200:
                    error_text = response.text[:500]
                    logger.error(
                        "Yandex STT error %d: %s",
                        response.status_code, error_text,
                    )
                    raise STTError(
                        f"Не удалось распознать речь (ошибка {response.status_code})"
                    )

                # Response: {"result": "распознанный текст"}
                body = response.json()
                text = body.get("result", "").strip()

                if not text:
                    raise STTError("Yandex SpeechKit returned empty transcription")

                logger.info("Transcription complete: %d chars", len(text))
                return text

        except STTError:
            raise
        except json.JSONDecodeError as e:
            logger.error("Yandex STT invalid JSON: %s", e)
            raise STTError("Yandex SpeechKit вернул некорректный ответ")
        except httpx.TimeoutException:
            raise STTError("Yandex SpeechKit timeout (120s)")
        except httpx.HTTPError as e:
            raise STTError(f"HTTP error during transcription: {e}")


def create_stt_service(
    provider: str,
    *,
    whisper_api_key: str = "",
    yandex_api_key: str = "",
    yandex_folder_id: str = "",
) -> WhisperSTTService | YandexSTTService:
    """Factory: create the right STT service based on provider name."""
    if provider == "yandex":
        return YandexSTTService(api_key=yandex_api_key, folder_id=yandex_folder_id)
    return WhisperSTTService(api_key=whisper_api_key, provider=provider)


# ── Helpers ──────────────────────────────────────────────────


def _validate_file(audio_path: Path, max_size: int) -> None:
    """Check file exists, not empty, within size limit."""
    if not audio_path.exists():
        raise STTError(f"Audio file not found: {audio_path}")
    file_size = audio_path.stat().st_size
    if file_size == 0:
        raise STTError("Audio file is empty")
    if file_size > max_size:
        raise STTError(
            f"Audio file too large: {file_size / 1024 / 1024:.1f} MB "
            f"(max {max_size / 1024 / 1024:.0f} MB)"
        )


def _get_mime_type(audio_path: Path) -> str:
    """Determine MIME type from file extension."""
    return {
        ".ogg": "audio/ogg",
        ".oga": "audio/ogg",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/m4a",
        ".webm": "audio/webm",
        ".mp4": "video/mp4",
    }.get(audio_path.suffix.lower(), "application/octet-stream")
