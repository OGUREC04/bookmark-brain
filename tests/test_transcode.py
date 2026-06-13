"""TDD for shared.media.transcode (3sr, шаг 4).

Браузер (Mini App) пишет звук в WebM/Opus (Android/Chrome) или MP4/AAC (iOS) —
Yandex SpeechKit их НЕ принимает (только OGG Opus / MP3 / LPCM). Эта обёртка
гоняет ffmpeg, чтобы перегнать произвольный браузерный звук в OGG Opus.

Без живого ffmpeg: подпроцесс замокан. Реальный бинарь нужен только на сервере
(ставится в Docker, шаг 3b).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.media.transcode import (
    TranscodeError,
    needs_transcode,
    transcode_to_ogg_opus,
)

# ── needs_transcode ────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["voice.ogg", "voice.oga", "podcast.mp3", "REC.MP3"])
def test_native_formats_skip_transcode(name):
    assert needs_transcode(name) is False


@pytest.mark.parametrize("name", ["rec.webm", "clip.mp4", "note.m4a", "sound.wav", "x"])
def test_browser_formats_need_transcode(name):
    assert needs_transcode(name) is True


# ── transcode_to_ogg_opus ──────────────────────────────────────────────────

def _proc(returncode=0, stderr=b""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(b"", stderr))
    return proc


async def test_transcode_invokes_ffmpeg_with_src_and_dest(tmp_path: Path):
    src = tmp_path / "in.webm"
    dest = tmp_path / "out.ogg"
    src.write_bytes(b"fake")

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_proc(returncode=0)),
    ) as mk:
        await transcode_to_ogg_opus(src, dest)

    args = mk.call_args.args
    assert args[0] == "ffmpeg"
    assert str(src) in args
    assert str(dest) in args
    assert "libopus" in args  # opus codec for the ogg container


async def test_transcode_nonzero_exit_raises(tmp_path: Path):
    src = tmp_path / "in.webm"
    dest = tmp_path / "out.ogg"
    src.write_bytes(b"fake")

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_proc(returncode=1, stderr=b"bad input")),
    ):
        with pytest.raises(TranscodeError, match="ffmpeg"):
            await transcode_to_ogg_opus(src, dest)


async def test_transcode_missing_binary_raises_clear_error(tmp_path: Path):
    src = tmp_path / "in.webm"
    dest = tmp_path / "out.ogg"
    src.write_bytes(b"fake")

    with patch(
        "asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=FileNotFoundError("ffmpeg")),
    ):
        with pytest.raises(TranscodeError, match="ffmpeg"):
            await transcode_to_ogg_opus(src, dest)
