"""Speech-to-Text service via OpenAI-compatible Whisper API.

Supports OpenAI and Groq (free tier) as STT providers.
Uses raw httpx instead of openai SDK for Python 3.14 compatibility.

Provider URLs:
- openai: https://api.openai.com/v1/audio/transcriptions (model: whisper-1)
- groq:   https://api.groq.com/openai/v1/audio/transcriptions (model: whisper-large-v3)
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_PROVIDERS = {
    "openai": {
        "url": "https://api.openai.com/v1/audio/transcriptions",
        "model": "whisper-1",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/audio/transcriptions",
        "model": "whisper-large-v3",
    },
}

# Whisper limits: 25 MB file size
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB


class STTError(Exception):
    """Raised when transcription fails."""


class WhisperSTTService:
    """Transcribe audio files using OpenAI-compatible Whisper API via raw httpx."""

    def __init__(self, api_key: str, provider: str = "openai"):
        if not api_key:
            raise ValueError("WHISPER_API_KEY is not set")
        self._api_key = api_key
        cfg = _PROVIDERS.get(provider, _PROVIDERS["openai"])
        self._url = cfg["url"]
        self._model = cfg["model"]
        logger.info("STT provider: %s (%s)", provider, self._url)

    async def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> str:
        """Transcribe an audio file to text.

        Args:
            audio_path: Path to the audio file (ogg, mp3, wav, etc.)
            language: Optional ISO-639-1 language hint (e.g. "ru", "en")

        Returns:
            Transcribed text string.

        Raises:
            STTError: If transcription fails or file is too large.
        """
        if not audio_path.exists():
            raise STTError(f"Audio file not found: {audio_path}")

        file_size = audio_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            raise STTError(
                f"Audio file too large: {file_size / 1024 / 1024:.1f} MB "
                f"(max {MAX_FILE_SIZE / 1024 / 1024:.0f} MB)"
            )

        if file_size == 0:
            raise STTError("Audio file is empty")

        # Determine MIME type from extension
        ext = audio_path.suffix.lower()
        mime_types = {
            ".ogg": "audio/ogg",
            ".oga": "audio/ogg",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/m4a",
            ".webm": "audio/webm",
            ".mp4": "video/mp4",
        }
        mime_type = mime_types.get(ext, "application/octet-stream")

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

                logger.info(
                    "Transcription complete: %d chars", len(text),
                )
                return text

        except httpx.TimeoutException:
            raise STTError("Whisper API timeout (120s)")
        except httpx.HTTPError as e:
            raise STTError(f"HTTP error during transcription: {e}")
