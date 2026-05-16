"""Phase 3A+3D — Voice & Video Note handler.

Скачивает аудио/видео из Telegram, транскрибирует через Whisper,
детектирует intent (todo/search/note), роутит соответственно.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from aiogram import F, Router, types

from bot import onboarding
from bot.config import get_settings
from bot.services.stt import (
    STTError,
    WhisperSTTService,
    YandexHybridSTTService,
    YandexSTTService,
    create_stt_service,
)
from bot.services.timestamps import add_timestamps
from bot.services.voice_intent import VoiceIntent, detect_intent
from bot.utils import ephemeral_error, safe_react

logger = logging.getLogger(__name__)

router = Router()

_settings = get_settings()

# Lazy-init STT service
_stt: WhisperSTTService | YandexSTTService | YandexHybridSTTService | None = None
_stt_checked = False

# Minimum voice duration to avoid Whisper hallucinations on silence/noise
_MIN_DURATION_SEC = 2

# Yandex SpeechKit limits:
# - sync API: 30 сек / 1 MB. Если STT_PROVIDER=yandex без S3 креденшелов
#   и duration > 30 — возвращаем понятную ошибку.
# - async API (через Object Storage): до 60 минут (cap из stt.py).
_YANDEX_SYNC_MAX_DURATION_SEC = 30

# Telegram Bot API file download limit
_TG_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def _get_stt() -> WhisperSTTService | YandexSTTService | YandexHybridSTTService | None:
    global _stt, _stt_checked
    if _stt is not None:
        return _stt

    provider = _settings.STT_PROVIDER

    # Yandex needs its own keys
    if provider == "yandex":
        if not _settings.YANDEX_CLOUD_API_KEY or not _settings.YANDEX_CLOUD_FOLDER_ID:
            if not _stt_checked:
                logger.warning("YANDEX_CLOUD_API_KEY/FOLDER_ID not set — voice disabled")
                _stt_checked = True
            return None
        _stt = create_stt_service(
            provider,
            yandex_api_key=_settings.YANDEX_CLOUD_API_KEY,
            yandex_folder_id=_settings.YANDEX_CLOUD_FOLDER_ID,
            yandex_s3_endpoint=_settings.YANDEX_S3_ENDPOINT,
            yandex_s3_bucket=_settings.YANDEX_S3_BUCKET,
            yandex_s3_access_key=_settings.YANDEX_S3_ACCESS_KEY,
            yandex_s3_secret_key=_settings.YANDEX_S3_SECRET_KEY,
        )
        if not _stt_checked:
            has_async = bool(_settings.YANDEX_S3_BUCKET and _settings.YANDEX_S3_ACCESS_KEY)
            logger.info(
                "Yandex STT initialized: sync only" if not has_async else
                "Yandex STT initialized: hybrid (sync + async via S3 %s)" % _settings.YANDEX_S3_BUCKET
            )
            _stt_checked = True
        return _stt

    # OpenAI/Groq need WHISPER_API_KEY
    key = _settings.WHISPER_API_KEY
    if not key:
        if not _stt_checked:
            logger.warning("WHISPER_API_KEY is not set — voice messages will be rejected")
            _stt_checked = True
        return None
    _stt = create_stt_service(provider, whisper_api_key=key)
    return _stt


# ── Voice messages ────────────────────────────────────────────


@router.message(F.voice)
async def handle_voice(message: types.Message, api, store=None):
    """Голосовое сообщение -> STT -> bookmark."""
    await _process_audio(
        message=message,
        api=api,
        store=store,
        file_id=message.voice.file_id,
        duration=message.voice.duration,
        file_size=message.voice.file_size,
        content_type="voice",
        ext=".ogg",
    )


@router.message(F.video_note)
async def handle_video_note(message: types.Message, api, store=None):
    """Видео-кружок -> STT -> bookmark (только аудио-дорожка)."""
    await _process_audio(
        message=message,
        api=api,
        store=store,
        file_id=message.video_note.file_id,
        duration=message.video_note.duration,
        file_size=message.video_note.file_size,
        content_type="video_note",
        ext=".mp4",
    )


@router.message(F.audio)
async def handle_audio(message: types.Message, api, store=None):
    """Аудио-файл (подкаст, музыка) -> STT -> bookmark."""
    mime = message.audio.mime_type or ""
    ext = {
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/flac": ".flac",
    }.get(mime, ".ogg")
    await _process_audio(
        message=message,
        api=api,
        store=store,
        file_id=message.audio.file_id,
        duration=message.audio.duration,
        file_size=message.audio.file_size,
        content_type="audio",
        ext=ext,
    )


# ── Core processing ──────────────────────────────────────────


async def _process_audio(
    message: types.Message,
    api,
    store,
    file_id: str,
    duration: int | None,
    file_size: int | None,
    content_type: str,
    ext: str,
) -> None:
    """Download -> transcribe -> create bookmark."""
    from bot.common.auth import ensure_user
    from bot.handlers.settings import is_silent

    stt = _get_stt()
    if stt is None:
        await ephemeral_error(
            message,
            "Голосовые сообщения пока не поддерживаются (STT не настроен).",
        )
        return

    # Edge case 1: too short — Whisper hallucinates on silence/noise
    if duration is not None and duration < _MIN_DURATION_SEC:
        await message.reply("Слишком короткое сообщение (менее 2 секунд).", parse_mode=None)
        return

    # Edge case 1b: длинные голосовые на Yandex — нужен async API (Object Storage).
    # Если STT — Hybrid с async, всё ОК (route внутри transcribe). Если только sync
    # (S3 не настроен) — заранее отвергаем с понятной подсказкой.
    if (
        duration is not None
        and duration > _YANDEX_SYNC_MAX_DURATION_SEC
        and isinstance(stt, YandexSTTService)
    ):
        await message.reply(
            f"Голосовые длиннее 30 секунд требуют Yandex Object Storage. "
            f"Запись {duration} сек — попроси админа настроить YANDEX_S3_* "
            f"(или разбей на части по 30 сек).",
            parse_mode=None,
        )
        return

    # Edge case 2: too large — Telegram Bot API caps downloads at 20 MB
    if file_size is not None and file_size > _TG_MAX_FILE_SIZE:
        mb = file_size / 1024 / 1024
        await ephemeral_error(
            message,
            f"Файл слишком большой ({mb:.1f} МБ). "
            f"Telegram позволяет скачивать до 20 МБ.",
        )
        return

    token = await ensure_user(message, api)
    if not token:
        return

    silent = await is_silent(api, token, message.from_user.id)

    # React: processing started
    reacted = await safe_react(message, "\U0001f442")  # ear emoji

    # Edge case 4: groups where reactions are blocked — send fallback text
    status_hint = None
    if not reacted:
        try:
            status_hint = await message.reply("Распознаю...", parse_mode=None)
        except Exception:
            pass

    # Download file from Telegram
    tmp_path: Path | None = None
    try:
        file = await message.bot.get_file(file_id)
        if file.file_path is None:
            await safe_react(message, "\U0001f44e")
            await ephemeral_error(
                message,
                "Не удалось скачать файл. Возможно, он слишком большой (>20 МБ).",
            )
            return

        # Create temp file
        tmp_dir = Path(tempfile.gettempdir()) / "bookmark-brain-stt"
        tmp_dir.mkdir(exist_ok=True)
        tmp_path = tmp_dir / f"{message.chat.id}_{message.message_id}{ext}"

        await message.bot.download_file(file.file_path, destination=tmp_path)
        logger.info(
            "Downloaded %s (%s, %ds) -> %s",
            content_type, file_id[:20], duration or 0, tmp_path,
        )

        # Transcribe.
        # Hybrid Yandex принимает duration kwarg — внутри роутит между sync и async.
        # Whisper и одиночный YandexSTTService не принимают duration → передаём только для Hybrid.
        if isinstance(stt, YandexHybridSTTService):
            text = await stt.transcribe(
                tmp_path,
                duration=float(duration) if duration is not None else None,
            )
        else:
            # language=None → Whisper auto-detects (supports multilingual input)
            text = await stt.transcribe(tmp_path)

    except STTError as e:
        logger.error("STT failed: %s", e)
        await safe_react(message, "\U0001f44e")
        await ephemeral_error(message, f"Ошибка распознавания: {e}")
        return
    except Exception as e:
        logger.error("Media processing failed: %s", e)
        await safe_react(message, "\U0001f44e")
        await ephemeral_error(message, "Ошибка обработки. Попробуй ещё раз.")
        return
    finally:
        # Cleanup temp file
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        # Remove "Распознаю..." hint if it was sent
        if status_hint:
            try:
                await status_hint.delete()
            except Exception:
                pass

    # Add timestamps for long messages (>60s)
    duration_float = float(duration) if duration else None
    text_with_ts = add_timestamps(text, duration_float)

    # Detect voice intent (use original text without timestamps for detection)
    intent_result = detect_intent(text, duration=duration_float)

    # Route by intent
    if intent_result.intent == VoiceIntent.SEARCH:
        await _handle_voice_search(message, api, token, text, intent_result.cleaned_text)
        return

    if intent_result.intent == VoiceIntent.REMINDER:
        await _handle_voice_reminder(
            message, api, token, text, intent_result.cleaned_text, store,
        )
        return

    if intent_result.intent == VoiceIntent.TODO:
        await _handle_voice_todo(
            message, api, token, text, intent_result.cleaned_text,
            file_id=file_id, duration_float=duration_float, silent=silent,
        )
        return

    # Default: save as note bookmark
    # Always reply with transcription text (with timestamps if long)
    reply_msg = await message.reply(text_with_ts, parse_mode=None)

    # Caption (if any) prepended to transcription
    caption = message.caption or ""
    raw_text = f"{caption}\n\n{text}".strip() if caption else text

    saved_ok = False
    try:
        if silent:
            await api.create_bookmark(
                token=token,
                raw_text=raw_text,
                source="telegram",
                source_message_id=message.message_id,
                notify_chat_id=message.chat.id,
                notify_message_id=message.message_id,
                silent=True,
                content_type=content_type,
                media_file_id=file_id,
                transcription=text,
                media_duration=duration_float,
                voice_tag=True,
            )
        else:
            await api.create_bookmark(
                token=token,
                raw_text=raw_text,
                source="telegram",
                source_message_id=message.message_id,
                notify_chat_id=reply_msg.chat.id,
                notify_message_id=reply_msg.message_id,
                content_type=content_type,
                media_file_id=file_id,
                transcription=text,
                media_duration=duration_float,
                voice_tag=True,
            )
        saved_ok = True
    except Exception as e:
        # Edge case 3: backend failed AFTER transcription succeeded.
        # The transcription text is already visible in reply_msg — don't lose it.
        logger.error("Failed to create voice bookmark: %s", e)
        await ephemeral_error(
            message,
            "Не удалось сохранить как закладку. Текст выше — можешь скопировать и отправить заново.",
            delay=15,
        )

    if saved_ok:
        await onboarding.maybe_show_tip(
            api, token, message,
            onboarding.KEY_FIRST_VOICE, onboarding.TIP_FIRST_VOICE,
        )


# ── Voice intent handlers ─────────────────────────────────────


async def _handle_voice_search(
    message: types.Message, api, token: str, full_text: str, query: str,
) -> None:
    """Voice search: transcribe → search bookmarks → show results."""
    from bot.handlers.search import _format_result

    # Reply with transcription + search marker
    await message.reply(f"🔍 {full_text}", parse_mode=None)

    if not query.strip():
        await ephemeral_error(message, "Не удалось распознать поисковый запрос.")
        return

    try:
        data = await api.search_bookmarks(token, query, limit=5)
    except Exception as e:
        logger.error("Voice search failed: %s", e)
        await ephemeral_error(message, "Ошибка поиска. Попробуй позже.")
        return

    results = data.get("results", [])
    total = data.get("total", 0)

    if not results:
        await message.answer(f'Ничего не найдено по запросу "{query}"', parse_mode=None)
        return

    parts = [f'🔍 Результаты по запросу "<b>{query}</b>" ({total} найдено):\n']
    for i, item in enumerate(results, 1):
        parts.append(f"{i}. {_format_result(item, item['score'])}")

    if total > 5:
        parts.append(f"\n...и ещё {total - 5}. Уточни запрос.")

    await message.answer("\n\n".join(parts), parse_mode="HTML", disable_web_page_preview=True)


async def _handle_voice_reminder(
    message: types.Message, api, token: str,
    full_text: str, cleaned_text: str, store,
) -> None:
    """Voice «напомни …» (skf/kjo): детерминированно в reminder-флоу.

    Раньше «напомни» попадало в VoiceIntent.TODO → инжект «список задач:»
    → AI-галлюцинация заголовка с «утром/вечером» → 2 напоминания на 1
    пункт. Теперь — тот же путь, что текстовый /remind
    (`process_explicit_remind_args`): есть время → создаём, нет →
    спрашиваем reply.
    """
    from bot.handlers.reminders.explicit import process_explicit_remind_args

    # Показываем что распознали (как voice-search) — прозрачность STT.
    await message.reply(f"🔔 {full_text}", parse_mode=None)

    args = (cleaned_text or "").strip()
    if not args:
        await ephemeral_error(
            message, "Не разобрал, о чём напомнить. Попробуй ещё раз.",
        )
        return
    await process_explicit_remind_args(message, args, api, store)


async def _handle_voice_todo(
    message: types.Message,
    api,
    token: str,
    full_text: str,
    cleaned_text: str,
    *,
    file_id: str,
    duration_float: float | None,
    silent: bool,
) -> None:
    """Voice todo: transcribe → detect tasks → create task_list bookmark."""
    # Reply with transcription + todo marker
    reply_msg = await message.reply(f"📋 {full_text}", parse_mode=None)

    # Build raw_text with todo prefix so backend task_list_detector picks it up
    raw_text = f"список задач: {cleaned_text}" if cleaned_text else f"список задач: {full_text}"

    saved_ok = False
    try:
        if silent:
            await api.create_bookmark(
                token=token,
                raw_text=raw_text,
                source="telegram",
                source_message_id=message.message_id,
                notify_chat_id=message.chat.id,
                notify_message_id=message.message_id,
                silent=True,
                content_type="voice",
                media_file_id=file_id,
                transcription=full_text,
                media_duration=duration_float,
                voice_tag=True,
            )
        else:
            await api.create_bookmark(
                token=token,
                raw_text=raw_text,
                source="telegram",
                source_message_id=message.message_id,
                notify_chat_id=reply_msg.chat.id,
                notify_message_id=reply_msg.message_id,
                content_type="voice",
                media_file_id=file_id,
                transcription=full_text,
                media_duration=duration_float,
                voice_tag=True,
            )
        saved_ok = True
    except Exception as e:
        logger.error("Failed to create voice todo: %s", e)
        await ephemeral_error(
            message,
            "Не удалось создать список задач. Текст выше — можешь скопировать.",
            delay=15,
        )

    if saved_ok:
        await onboarding.maybe_show_tip(
            api, token, message,
            onboarding.KEY_FIRST_VOICE, onboarding.TIP_FIRST_VOICE,
        )
