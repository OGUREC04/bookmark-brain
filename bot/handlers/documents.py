"""Phase 3B — Document handler.

Принимает PDF / DOCX / TXT / MD от пользователя, извлекает текст и
сохраняет как закладку (content_type="document").
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from aiogram import F, Router, types

from bot.services.extractor import (
    EmptyDocumentError,
    EncryptedPDFError,
    ExtractError,
    detect_format,
    extract_text,
)
from bot.utils import ephemeral_error, safe_react

logger = logging.getLogger(__name__)

router = Router()

# Telegram Bot API file download limit
_TG_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

# How many chars of extracted text to show as preview reply
_PREVIEW_CHARS = 500

_SUPPORTED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
}


def _is_supported_document(message: types.Message) -> bool:
    """Filter: forward to handler only PDF / DOCX / TXT / MD documents."""
    doc = message.document
    if doc is None:
        return False
    if (doc.mime_type or "").lower() in _SUPPORTED_MIME:
        return True
    # Fallback by extension — Telegram sometimes lacks/wrongs mime_type.
    return detect_format(doc.mime_type, doc.file_name) is not None


@router.message(F.document, _is_supported_document)
async def handle_document(message: types.Message, api, store=None):
    """Document → text extraction → bookmark."""
    from bot.handlers.start import _ensure_user
    from bot.handlers.settings import is_silent

    doc = message.document
    fmt = detect_format(doc.mime_type, doc.file_name)
    if fmt is None:
        # Defensive — filter should have rejected, but be safe.
        return

    file_size = doc.file_size or 0
    if file_size > _TG_MAX_FILE_SIZE:
        mb = file_size / 1024 / 1024
        await ephemeral_error(
            message,
            f"Файл слишком большой ({mb:.1f} МБ). Telegram позволяет скачивать до 20 МБ.",
        )
        return

    token = await _ensure_user(message, api)
    if not token:
        return

    silent = await is_silent(api, token, message.from_user.id)

    reacted = await safe_react(message, "\U0001f4c4")  # 📄

    status_hint = None
    if not reacted:
        try:
            status_hint = await message.reply("Читаю документ...", parse_mode=None)
        except Exception:
            pass

    suffix = Path(doc.file_name or "").suffix.lower() or {
        "pdf": ".pdf",
        "docx": ".docx",
        "plain": ".txt",
    }.get(fmt, "")

    tmp_path: Path | None = None
    try:
        file = await message.bot.get_file(doc.file_id)
        if file.file_path is None:
            await safe_react(message, "\U0001f44e")
            await ephemeral_error(
                message,
                "Не удалось скачать файл. Возможно, он слишком большой (>20 МБ).",
            )
            return

        tmp_dir = Path(tempfile.gettempdir()) / "bookmark-brain-docs"
        tmp_dir.mkdir(exist_ok=True)
        tmp_path = tmp_dir / f"{message.chat.id}_{message.message_id}{suffix}"
        await message.bot.download_file(file.file_path, destination=tmp_path)
        logger.info(
            "Downloaded document %s (%s, %d bytes) -> %s",
            doc.file_name, fmt, file_size, tmp_path,
        )

        result = await extract_text(tmp_path, fmt)

    except EncryptedPDFError as e:
        logger.info("Encrypted PDF rejected: %s", e)
        await safe_react(message, "\U0001f44e")
        await ephemeral_error(message, str(e))
        return
    except EmptyDocumentError as e:
        logger.info("Empty document: %s", e)
        await safe_react(message, "\U0001f44e")
        await ephemeral_error(message, str(e))
        return
    except ExtractError as e:
        logger.error("Extract failed: %s", e)
        await safe_react(message, "\U0001f44e")
        await ephemeral_error(message, f"Не получилось прочитать документ: {e}")
        return
    except Exception as e:
        logger.exception("Document processing failed: %s", e)
        await safe_react(message, "\U0001f44e")
        await ephemeral_error(message, "Ошибка обработки документа. Попробуй ещё раз.")
        return
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        if status_hint:
            try:
                await status_hint.delete()
            except Exception:
                pass

    # Reply with preview (first N chars of extracted text)
    preview = result.text[:_PREVIEW_CHARS]
    if len(result.text) > _PREVIEW_CHARS:
        preview += "..."
    suffix_info = []
    if result.page_count is not None:
        suffix_info.append(f"{result.page_count} стр.")
    if result.truncated:
        suffix_info.append("текст обрезан до 50k символов")
    header = f"📄 {doc.file_name}"
    if suffix_info:
        header += f" ({', '.join(suffix_info)})"
    reply_msg = await message.reply(f"{header}\n\n{preview}", parse_mode=None)

    # Caption (if any) prepended to extracted text in raw_text
    caption = message.caption or ""
    raw_text = f"{caption}\n\n{result.text}".strip() if caption else result.text

    try:
        if silent:
            await api.create_bookmark(
                token=token,
                raw_text=raw_text,
                title=doc.file_name,
                source="telegram",
                source_message_id=message.message_id,
                notify_chat_id=message.chat.id,
                notify_message_id=message.message_id,
                silent=True,
                content_type="document",
                media_file_id=doc.file_id,
                document_page_count=result.page_count,
            )
        else:
            await api.create_bookmark(
                token=token,
                raw_text=raw_text,
                title=doc.file_name,
                source="telegram",
                source_message_id=message.message_id,
                notify_chat_id=reply_msg.chat.id,
                notify_message_id=reply_msg.message_id,
                content_type="document",
                media_file_id=doc.file_id,
                document_page_count=result.page_count,
            )
    except Exception as e:
        # Backend failed AFTER successful extraction — preview is already visible.
        logger.error("Failed to create document bookmark: %s", e)
        await ephemeral_error(
            message,
            "Не удалось сохранить как закладку. Текст выше — можешь скопировать.",
            delay=15,
        )
