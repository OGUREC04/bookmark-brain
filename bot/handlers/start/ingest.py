"""Ингест сообщений (forward / text / media) + подтверждение коротких сохранений.

handle_text — catch-all для обычного текста: explicit-remind trigger, pending-dedup
ответ, короткое сообщение → запрос подтверждения, иначе save. Save-подтверждение
(`save_yes`/`save_no`) живёт здесь же, т.к. связано с `handle_text` через
общий `_pending_saves` (essential coupling).
"""
import logging
import re
import time

from aiogram import F, Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import onboarding
from bot.common.auth import ensure_user
from bot.utils import ephemeral_error, safe_react

logger = logging.getLogger(__name__)

router = Router()

# Временное хранилище коротких сообщений для подтверждения.
# Keyed by message_id (not user_id) to avoid overwriting on rapid sends.
_pending_saves: dict[int, dict] = {}
_PENDING_TTL = 300  # 5 minutes

# media_group_id -> timestamp последнего показа предупреждения "без подписи".
# TTL короткий: альбом приходит за <1 секунду; защита от повторного предупреждения
# на каждом медиа в альбоме (Telegram шлёт каждое отдельным update).
_media_group_warned: dict[str, float] = {}
_MEDIA_GROUP_WARN_TTL = 60
_MEDIA_GROUP_MAX_ENTRIES = 10000  # защита от роста при флуде разных альбомов

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
MIN_AUTO_SAVE_LENGTH = 15


def _media_group_seen_warning(group_id: str) -> bool:
    """Возвращает True если для этой группы уже показывали предупреждение
    (значит, новое показывать НЕ надо). False если впервые — и заодно
    регистрирует факт показа.
    """
    now = time.monotonic()
    # Lazy eviction по TTL
    expired = [k for k, v in _media_group_warned.items() if now - v > _MEDIA_GROUP_WARN_TTL]
    for k in expired:
        _media_group_warned.pop(k, None)

    # Hard cap: если кэш вырос (флуд уникальных альбомов) — выбрасываем 20% старейших
    if len(_media_group_warned) > _MEDIA_GROUP_MAX_ENTRIES:
        sorted_items = sorted(_media_group_warned.items(), key=lambda kv: kv[1])
        drop_n = max(1, len(_media_group_warned) // 5)
        for k, _ in sorted_items[:drop_n]:
            _media_group_warned.pop(k, None)

    if group_id in _media_group_warned:
        return True
    _media_group_warned[group_id] = now
    return False


def _extract_urls(message: types.Message) -> list[str]:
    """Извлекает URL из entities сообщения."""
    urls = []
    if message.entities:
        for entity in message.entities:
            if entity.type == "url":
                urls.append(message.text[entity.offset : entity.offset + entity.length])
            elif entity.type == "text_link":
                urls.append(entity.url)
    # Fallback: regex
    if not urls and message.text:
        urls = URL_PATTERN.findall(message.text)
    return urls


def _extract_text(message: types.Message) -> str:
    """Извлекает текст из сообщения (включая caption)."""
    return message.text or message.caption or ""


# ─── Подтверждение сохранения коротких сообщений ───


@router.callback_query(F.data.startswith("save_yes:"))
async def cb_save_confirm(callback, api):
    """Подтверждение сохранения короткого сообщения."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    token = await ensure_user(callback, api)
    if not token:
        return

    orig_msg_id = int(callback.data.split(":")[1])
    pending = _pending_saves.pop(orig_msg_id, None)
    if not pending:
        await callback.answer("Сообщение устарело, отправь ещё раз.", show_alert=True)
        return

    silent = pending.get("silent", False)

    saved_ok = False
    try:
        if silent:
            # Удаляем сообщение-вопрос, ставим 👍 на оригинал
            try:
                await callback.message.delete()
            except Exception:
                pass
            await api.create_bookmark(
                token=token,
                raw_text=pending["text"],
                url=pending.get("url"),
                source="bot_message",
                source_message_id=orig_msg_id,
                notify_chat_id=callback.message.chat.id,
                notify_message_id=orig_msg_id,
                silent=True,
            )
            saved_ok = True
        else:
            await callback.message.edit_text("⏳ Сохранено! Обрабатываю...")
            await api.create_bookmark(
                token=token,
                raw_text=pending["text"],
                url=pending.get("url"),
                source="bot_message",
                source_message_id=orig_msg_id,
                notify_chat_id=callback.message.chat.id,
                notify_message_id=callback.message.message_id,
            )
            saved_ok = True
    except Exception as e:
        logger.error(f"Failed to create bookmark: {e}")
        if silent:
            await ephemeral_error(callback.message, "Ошибка при сохранении. Попробуй ещё раз.")
        else:
            await callback.message.edit_text("Ошибка при сохранении.")

    if saved_ok and isinstance(callback.message, Message):
        await onboarding.maybe_show_tip(
            api, token, callback.message,
            onboarding.KEY_FIRST_SAVE, onboarding.TIP_FIRST_SAVE,
            telegram_id=callback.from_user.id,
        )

    await callback.answer()


@router.callback_query(F.data.startswith("save_no:"))
async def cb_save_cancel(callback):
    """Отмена сохранения."""
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    orig_msg_id = int(callback.data.split(":")[1])
    _pending_saves.pop(orig_msg_id, None)
    await callback.message.edit_text("Не сохраняю.")
    await callback.answer()


# ─── Обработка сообщений ───


@router.message(F.forward_date)
async def handle_forward(message: types.Message, api):
    """Обработка пересланных сообщений."""
    token = await ensure_user(message, api)
    if not token:
        return

    text = _extract_text(message)
    if not text:
        # Forwarded media group: Telegram шлёт каждое фото/видео отдельным апдейтом.
        # Caption есть только у одного из них — остальные приходят без текста.
        # Предупреждаем только один раз на альбом.
        if message.media_group_id:
            if not _media_group_seen_warning(message.media_group_id):
                await message.answer(
                    "Получил альбом, но без подписи. "
                    "Чтобы сохранить — добавь caption к одному из медиа в альбоме.",
                    parse_mode=None,
                )
        else:
            await message.answer("Не могу извлечь текст из этого сообщения.", parse_mode=None)
        return

    urls = _extract_urls(message)

    from bot.handlers.settings import is_silent
    silent = await is_silent(api, token, message.from_user.id)

    saved_ok = False
    if silent:
        await safe_react(message, "\U0001f440")
        try:
            await api.create_bookmark(
                token=token,
                raw_text=text,
                url=urls[0] if urls else None,
                source="bot_forward",
                source_message_id=message.message_id,
                notify_chat_id=message.chat.id,
                notify_message_id=message.message_id,
                silent=True,
            )
            saved_ok = True
        except Exception as e:
            logger.error(f"Failed to create bookmark: {e}")
            await safe_react(message, "\U0001f44e")
            await ephemeral_error(message, "Ошибка при сохранении. Попробуй ещё раз.")
    else:
        status_msg = await message.answer("⏳ Сохранено! Обрабатываю...", parse_mode=None)
        try:
            await api.create_bookmark(
                token=token,
                raw_text=text,
                url=urls[0] if urls else None,
                source="bot_forward",
                source_message_id=message.message_id,
                notify_chat_id=status_msg.chat.id,
                notify_message_id=status_msg.message_id,
            )
            saved_ok = True
        except Exception as e:
            logger.error(f"Failed to create bookmark: {e}")
            await status_msg.edit_text("Ошибка при сохранении. Попробуй ещё раз.")

    if saved_ok:
        await onboarding.maybe_show_tip(
            api, token, message,
            onboarding.KEY_FIRST_SAVE, onboarding.TIP_FIRST_SAVE,
        )


@router.message(
    F.text
    & ~F.text.startswith("/")
    & ~(F.reply_to_message.from_user.is_bot)
)
async def handle_text(message: types.Message, api, store=None):
    """Обработка обычных текстовых сообщений (не команд).

    53j: reply НА БОТА сюда НЕ доходит — его обрабатывают upstream
    (reminders `_reply_dispatch`, tasks `msg_nl_edit_on_reply`). Без
    этого reply со временем на strong-intent «когда?» дублировался
    catch-all'ом «Сохранить как заметку?». Reply на чужое/своё
    сообщение по-прежнему сохраняется заметкой (regression-safe).
    """
    # Pending dedup: следующее сообщение обрабатывается как ответ на dedup
    if store and not message.reply_to_message:
        pending_mid = await store.get_pending_dedup(message.chat.id)
        if pending_mid:
            from bot.common import send_ephemeral
            from bot.handlers.tasks import handle_pending_dedup, parse_dedup_intent
            dedup = await store.get_general_dedup(message.chat.id, pending_mid)
            if dedup:
                intent = parse_dedup_intent(message.text or "")
                if intent != "unknown":
                    await handle_pending_dedup(
                        message, api, store, dedup, intent, pending_mid,
                    )
                    return
                else:
                    # Неизвестное — переспрашиваем, не пускаем в обычный flow
                    await send_ephemeral(
                        message,
                        "Не понял. Напиши или ответь reply:\n"
                        "открой / удали / обнови / сохрани как новую",
                        delay=10,
                    )
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    return

    token = await ensure_user(message, api)
    if not token:
        return

    text = message.text.strip()
    if not text:
        return

    # Phase 2.6 T8: explicit-trigger «сделай напоминание <текст> <время>» — БЕЗ
    # AI/закладки, идёт сразу в reminder flow. Должно стоять до URL-extract /
    # short-save / AI-save чтобы команда не превращалась в bookmark.
    #
    # Note: «срочно напомни...» / «надо напомни...» перехватываются strong_router
    # раньше (matches /^(надо|нужно|срочно|…)/i) — это намеренное поведение,
    # urgency-маркер сильнее T8 trigger'а. См. ADR 0008 / 0009.
    from bot.common import extract_explicit_remind_body
    from bot.handlers.reminders import process_explicit_remind_args
    explicit_body = extract_explicit_remind_body(text)
    if explicit_body is not None:
        if not explicit_body:
            # Юзер написал просто «напомни» — спрашиваем что и когда вместо
            # дампа полной справки /remind.
            await message.answer(
                "🔔 Что напомнить и когда?\n"
                "Например: <code>напомни купить хлеб завтра в 9</code>",
                parse_mode="HTML",
            )
            return
        await process_explicit_remind_args(message, explicit_body, api, store)
        return

    urls = _extract_urls(message)

    from bot.handlers.settings import is_silent
    silent = await is_silent(api, token, message.from_user.id)

    # Короткие сообщения — запрос подтверждения (в обоих режимах)
    if len(text) < MIN_AUTO_SAVE_LENGTH and not urls:
        # Evict expired entries lazily
        now = time.monotonic()
        expired = [k for k, v in _pending_saves.items() if now - v["ts"] > _PENDING_TTL]
        for k in expired:
            _pending_saves.pop(k, None)

        _pending_saves[message.message_id] = {
            "text": text,
            "url": None,
            "ts": now,
            "silent": silent,
        }
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, сохранить", callback_data=f"save_yes:{message.message_id}"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"save_no:{message.message_id}"),
            ]
        ])
        await message.answer(f'Сохранить "{text}" как заметку?', reply_markup=kb, parse_mode=None)
        return

    saved_ok = False
    if silent:
        # Silent mode: ставим 👀 и отправляем ID оригинального сообщения
        await safe_react(message, "\U0001f440")
        try:
            await api.create_bookmark(
                token=token,
                raw_text=text,
                url=urls[0] if urls else None,
                source="bot_message",
                source_message_id=message.message_id,
                notify_chat_id=message.chat.id,
                notify_message_id=message.message_id,
                silent=True,
            )
            saved_ok = True
        except Exception as e:
            logger.error(f"Failed to create bookmark: {e}")
            await safe_react(message, "\U0001f44e")
            await ephemeral_error(message, "Ошибка при сохранении. Попробуй ещё раз.")
    else:
        # Verbose mode: текстовое подтверждение (legacy)
        status_msg = await message.answer("⏳ Сохранено! Обрабатываю...", parse_mode=None)
        try:
            await api.create_bookmark(
                token=token,
                raw_text=text,
                url=urls[0] if urls else None,
                source="bot_message",
                source_message_id=message.message_id,
                notify_chat_id=status_msg.chat.id,
                notify_message_id=status_msg.message_id,
            )
            saved_ok = True
        except Exception as e:
            logger.error(f"Failed to create bookmark: {e}")
            await status_msg.edit_text("Ошибка при сохранении. Попробуй ещё раз.")

    if saved_ok:
        await onboarding.maybe_show_tip(
            api, token, message,
            onboarding.KEY_FIRST_SAVE, onboarding.TIP_FIRST_SAVE,
        )


@router.message(F.photo | F.video | F.sticker)
async def handle_media(message: types.Message, api):
    """Обработка медиа-сообщений (фото, видео и т.д.)."""
    token = await ensure_user(message, api)
    if not token:
        return

    caption = message.caption or ""
    if not caption:
        # Media group: Telegram шлёт каждое фото/видео отдельным апдейтом, у всех
        # один media_group_id. Предупреждаем только на первом — иначе спам.
        # Без media_group_id (одиночное фото без подписи) — обычный ответ.
        if message.media_group_id:
            if not _media_group_seen_warning(message.media_group_id):
                await message.answer(
                    "Получил медиа, но без текста. "
                    "Добавь подпись (caption) к одному из медиа в альбоме — сохраню весь альбом.",
                    parse_mode=None,
                )
        else:
            await message.answer(
                "Получил медиа, но без текста. Добавь подпись к сообщению, чтобы я мог сохранить.",
                parse_mode=None,
            )
        return

    urls = []
    if message.caption_entities:
        for entity in message.caption_entities:
            if entity.type == "url":
                urls.append(caption[entity.offset : entity.offset + entity.length])
            elif entity.type == "text_link":
                urls.append(entity.url)

    from bot.handlers.settings import is_silent
    silent = await is_silent(api, token, message.from_user.id)

    saved_ok = False
    if silent:
        await safe_react(message, "\U0001f440")
        try:
            await api.create_bookmark(
                token=token,
                raw_text=caption,
                url=urls[0] if urls else None,
                source="bot_forward",
                source_message_id=message.message_id,
                notify_chat_id=message.chat.id,
                notify_message_id=message.message_id,
                silent=True,
            )
            saved_ok = True
        except Exception as e:
            logger.error(f"Failed to create bookmark from media: {e}")
            await safe_react(message, "\U0001f44e")
            await ephemeral_error(message, "Ошибка при сохранении. Попробуй ещё раз.")
    else:
        status_msg = await message.answer("⏳ Сохранено! Обрабатываю...", parse_mode=None)
        try:
            await api.create_bookmark(
                token=token,
                raw_text=caption,
                url=urls[0] if urls else None,
                source="bot_forward",
                source_message_id=message.message_id,
                notify_chat_id=status_msg.chat.id,
                notify_message_id=status_msg.message_id,
            )
            saved_ok = True
        except Exception as e:
            logger.error(f"Failed to create bookmark from media: {e}")
            await status_msg.edit_text("Ошибка при сохранении. Попробуй ещё раз.")

    if saved_ok:
        await onboarding.maybe_show_tip(
            api, token, message,
            onboarding.KEY_FIRST_SAVE, onboarding.TIP_FIRST_SAVE,
        )
