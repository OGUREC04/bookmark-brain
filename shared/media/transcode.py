"""Transcode browser audio to OGG Opus for Yandex SpeechKit (3sr).

The Mini App records audio via the browser MediaRecorder, which yields
WebM/Opus (Chrome/Android) or MP4/AAC (iOS Safari). Yandex SpeechKit accepts
only OGG Opus / MP3 / LPCM, so non-native uploads are transcoded with ffmpeg
before recognition. Telegram voice (already OGG Opus) and MP3 skip this.

ffmpeg is invoked as an external binary (installed in the backend image at
шаг 3b). Pure subprocess + paths, no project deps — keeps ``shared`` a leaf.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Formats Yandex SpeechKit ingests directly — no ffmpeg needed.
_NATIVE_AUDIO_EXTS = {".ogg", ".oga", ".mp3"}


class TranscodeError(Exception):
    """Raised when ffmpeg transcoding fails or the binary is unavailable."""


def needs_transcode(filename: str) -> bool:
    """True if ``filename``'s audio format must be converted for Yandex STT."""
    return Path(filename).suffix.lower() not in _NATIVE_AUDIO_EXTS


async def transcode_to_ogg_opus(src: Path, dest: Path) -> None:
    """Transcode any audio/video file at ``src`` to OGG Opus at ``dest``.

    Drops the video track (``-vn``) so video notes work too. Raises
    ``TranscodeError`` on a non-zero exit or a missing ffmpeg binary.
    """
    cmd = (
        "ffmpeg", "-y",
        "-i", str(src),
        "-vn",            # audio only — mp4 / video_note carry a video track
        "-c:a", "libopus",
        "-b:a", "32k",    # speech-grade bitrate keeps the file small
        str(dest),
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise TranscodeError(
            "ffmpeg не установлен в окружении — не могу перекодировать аудио."
        ) from e

    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = (stderr or b"").decode("utf-8", "replace")[-400:]
        logger.error("ffmpeg transcode failed (rc=%s): %s", proc.returncode, tail)
        raise TranscodeError(
            f"ffmpeg не смог перекодировать аудио (код {proc.returncode})."
        )
