"""Tests for Phase 3B — document extraction & handler."""
from __future__ import annotations

import asyncio
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services.extractor import (
    EmptyDocumentError,
    EncryptedPDFError,
    ExtractError,
    MAX_CHARS,
    detect_format,
    extract_text,
)


# ── Format detection ─────────────────────────────────────────


@pytest.mark.parametrize(
    "mime,name,expected",
    [
        ("application/pdf", "doc.pdf", "pdf"),
        (None, "report.PDF", "pdf"),
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "memo.docx",
            "docx",
        ),
        (None, "letter.DOCX", "docx"),
        ("text/plain", "notes.txt", "plain"),
        ("text/markdown", "readme.md", "plain"),
        (None, "log.txt", "plain"),
        (None, "spec.md", "plain"),
        ("image/png", "image.png", None),
        ("application/zip", "archive.zip", None),
        (None, None, None),
    ],
)
def test_detect_format(mime, name, expected):
    assert detect_format(mime, name) == expected


# ── Plain text extraction ─────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_plain_utf8(tmp_path: Path):
    f = tmp_path / "note.txt"
    f.write_text("Привет, мир!\nLine 2", encoding="utf-8")
    result = await extract_text(f, "plain")
    assert "Привет, мир!" in result.text
    assert "Line 2" in result.text
    assert result.page_count is None
    assert result.truncated is False


@pytest.mark.asyncio
async def test_extract_plain_cp1251(tmp_path: Path):
    f = tmp_path / "note.txt"
    f.write_bytes("Тест кириллица".encode("cp1251"))
    result = await extract_text(f, "plain")
    assert "Тест" in result.text


@pytest.mark.asyncio
async def test_extract_plain_truncates(tmp_path: Path):
    f = tmp_path / "big.txt"
    f.write_text("a" * (MAX_CHARS + 1000), encoding="utf-8")
    result = await extract_text(f, "plain")
    assert result.truncated is True
    assert "[обрезано]" in result.text
    # Body length is capped (allow small marker overhead)
    assert len(result.text) <= MAX_CHARS + 50


@pytest.mark.asyncio
async def test_extract_plain_empty_file(tmp_path: Path):
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    with pytest.raises(EmptyDocumentError):
        await extract_text(f, "plain")


@pytest.mark.asyncio
async def test_extract_plain_whitespace_only(tmp_path: Path):
    f = tmp_path / "spaces.txt"
    f.write_text("   \n\n  \t  ", encoding="utf-8")
    with pytest.raises(EmptyDocumentError):
        await extract_text(f, "plain")


@pytest.mark.asyncio
async def test_extract_missing_file(tmp_path: Path):
    with pytest.raises(ExtractError):
        await extract_text(tmp_path / "nope.txt", "plain")


# ── PDF extraction ────────────────────────────────────────────

pypdf = pytest.importorskip("pypdf")


def _make_pdf(tmp_path: Path, pages_text: list[str]) -> Path:
    """Build a minimal PDF using pypdf (test-only helper)."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject,
        ContentStream,
        DecodedStreamObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        NumberObject,
        TextStringObject,
    )

    writer = PdfWriter()
    for text in pages_text:
        page = writer.add_blank_page(width=612, height=792)
        # Build a simple content stream: BT /F1 12 Tf 50 700 Td (text) Tj ET
        stream_data = (
            f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode("latin-1")
        )
        content = DecodedStreamObject()
        content.set_data(stream_data)
        page[NameObject("/Contents")] = content
        # Add a font resource
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        resources = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        page[NameObject("/Resources")] = resources

    pdf_path = tmp_path / "test.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


@pytest.mark.asyncio
async def test_extract_pdf_basic(tmp_path: Path):
    pdf = _make_pdf(tmp_path, ["Hello PDF", "Page two text"])
    result = await extract_text(pdf, "pdf")
    assert result.page_count == 2
    assert "Hello PDF" in result.text or "Hello" in result.text


@pytest.mark.asyncio
async def test_extract_pdf_corrupted(tmp_path: Path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a real pdf at all, just garbage")
    with pytest.raises(ExtractError):
        await extract_text(bad, "pdf")


@pytest.mark.asyncio
async def test_extract_pdf_encrypted(tmp_path: Path):
    pdf = _make_pdf(tmp_path, ["Secret"])
    # Re-open and encrypt with non-empty password
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(pdf))
    writer = PdfWriter(clone_from=reader)
    writer.encrypt(user_password="hunter2", owner_password="hunter2")
    enc_path = tmp_path / "enc.pdf"
    with open(enc_path, "wb") as f:
        writer.write(f)

    with pytest.raises(EncryptedPDFError):
        await extract_text(enc_path, "pdf")


# ── DOCX extraction ───────────────────────────────────────────

docx = pytest.importorskip("docx")


def _make_docx(tmp_path: Path, paragraphs: list[str]) -> Path:
    from docx import Document

    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    out = tmp_path / "test.docx"
    doc.save(str(out))
    return out


@pytest.mark.asyncio
async def test_extract_docx_basic(tmp_path: Path):
    f = _make_docx(tmp_path, ["First paragraph", "Второй абзац"])
    result = await extract_text(f, "docx")
    assert "First paragraph" in result.text
    assert "Второй абзац" in result.text
    assert result.page_count is None
    assert result.truncated is False


@pytest.mark.asyncio
async def test_extract_docx_empty(tmp_path: Path):
    f = _make_docx(tmp_path, [])
    with pytest.raises(EmptyDocumentError):
        await extract_text(f, "docx")


@pytest.mark.asyncio
async def test_extract_docx_truncates(tmp_path: Path):
    big = "x" * 1000
    paragraphs = [big] * 60  # ~60 000 chars total
    f = _make_docx(tmp_path, paragraphs)
    result = await extract_text(f, "docx")
    assert result.truncated is True
    assert "[обрезано]" in result.text


# ── Handler-level smoke test ──────────────────────────────────


@pytest.mark.asyncio
async def test_handler_rejects_oversized_document(
    mock_message, mock_api, monkeypatch, tmp_path: Path,
):
    # Settings need env vars at import time of bot.handlers.start.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("BOT_SECRET", "test-secret")
    from bot.handlers import documents as docs_handler

    msg = mock_message()
    msg.document = MagicMock()
    msg.document.mime_type = "application/pdf"
    msg.document.file_name = "huge.pdf"
    msg.document.file_size = 25 * 1024 * 1024  # 25 MB > 20 MB cap
    msg.document.file_id = "abc"

    with patch("bot.handlers.documents.ephemeral_error", new=AsyncMock()) as ephem:
        await docs_handler.handle_document(msg, mock_api, store=None)

    ephem.assert_called_once()
    args = ephem.call_args.args
    assert "слишком большой" in args[1]
    mock_api.create_bookmark.assert_not_called()
