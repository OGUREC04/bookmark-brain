import logging
import re
import time

from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from bot.config import get_settings
from bot import onboarding
from bot.utils import ephemeral_error, safe_react

_settings = get_settings()

logger = logging.getLogger(__name__)

router = Router()

# Кэш токенов: telegram_id -> (JWT token, expires_at)
_user_tokens: dict[int, tuple[str, float]] = {}

_TOKEN_TTL = 6 * 24 * 3600  # 6 days (JWT is 7 days, refresh before expiry)

# Временное хранилище коротких сообщений для подтверждения
# Keyed by message_id (not user_id) to avoid overwriting on rapid sends
_pending_saves: dict[int, dict] = {}

_PENDING_TTL = 300  # 5 minutes

# media_group_id -> timestamp последнего показа предупреждения "без подписи"
# TTL короткий: альбом приходит за <1 секунду; защита от повторного предупреждения
# на каждом медиа в альбоме (Telegram шлёт каждое отдельным update).
_media_group_warned: dict[str, float] = {}
_MEDIA_GROUP_WARN_TTL = 60
_MEDIA_GROUP_MAX_ENTRIES = 10000  # защита от роста при флуде разных альбомов


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


URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")

MIN_AUTO_SAVE_LENGTH = 15


async def _ensure_user(message_or_callback, api) -> str | None:
    """Получить JWT-токен юзера, создав его при необходимости."""
    user = message_or_callback.from_user

    tg_id = user.id
    cached = _user_tokens.get(tg_id)
    if cached:
        token, expires_at = cached
        if time.monotonic() < expires_at:
            return token

    try:
        data = await api.get_or_create_user(
            telegram_id=tg_id,
            username=user.username,
            first_name=user.first_name,
        )
        token = data["access_token"]
        _user_tokens[tg_id] = (token, time.monotonic() + _TOKEN_TTL)
        return token
    except Exception as e:
        logger.error(f"Failed to auth user {tg_id}: {e}")
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.answer("Ошибка подключения к серверу.", show_alert=True)
        else:
            await message_or_callback.answer("Ошибка подключения к серверу. Попробуй позже.", parse_mode=None)
        return None


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


# ─── Команды ───


_NEW_USER_WELCOME = (
    "Привет, {name}! Я BookmarkBrain — твой второй мозг для сохранения и поиска заметок.\n\n"
    "Что можно делать:\n"
    "• Пересылать сообщения и ссылки — я разберу AI-ом и сохраню\n"
    "• Записывать голосовые — распознаю и сохраню текст\n"
    "• Кидать PDF/DOCX — извлеку текст\n"
    "• Писать списки задач — распознаю и сделаю интерактивным\n\n"
    "Попробуй прямо сейчас: перешли мне любое сообщение или скинь ссылку.\n\n"
    "Команды:\n"
    "/list — все закладки\n"
    "/search <запрос> — найти по смыслу\n"
    "/random — случайная закладка\n"
    "/silent — тихий режим (реакции вместо текста)\n"
    "/help — полная справка"
)

_RETURNING_USER_WELCOME = (
    "С возвращением, {name}! Я на месте.\n\n"
    "Перешли мне что-нибудь, или используй /list, /search, /random, /help."
)

_HELP_TEXT = (
    "BookmarkBrain — справка\n\n"
    "📥 Сохранение:\n"
    "• Перешли любое сообщение → сохраню\n"
    "• Скинь ссылку → подтяну текст статьи и саммари\n"
    "• Запиши голосовое → распознаю в текст (тег #voice)\n"
    "• Прикрепи PDF/DOCX/TXT/MD → извлеку текст\n"
    "• Короткое сообщение (<15 знаков) → спрошу подтверждение\n\n"
    "🔍 Поиск и просмотр:\n"
    "• /list — список закладок (5 на страницу)\n"
    "• /search <запрос> — семантический поиск\n"
    "• /random — случайная закладка\n\n"
    "✅ Списки задач:\n"
    "• Напиши список через • или 1. 2. 3. — распознаю как task list\n"
    "• Reply на список: «закрой 1, 3», «добавь ...», «удали 2», «удали список»\n\n"
    "🔔 Напоминания:\n"
    "• /remind <текст> <когда> — создать напоминание (без аргументов — справка)\n"
    "• /reminders — активные + reply «отмени 1» / «перенеси 2 на ...»\n"
    "• /reminders история — последние выполненные/отменённые\n"
    "• «надо/нужно/срочно/не забыть ...» — спрошу: напоминание или заметка\n\n"
    "⚙️ Режимы:\n"
    "• /silent — переключить тихий режим (реакции 👀→👍)\n"
    "• /silent on / /silent off — явное переключение\n\n"
    "🗑 Уборка:\n"
    "• /clean — удалить мои сообщения за последние 48ч (списки задач сохраняются)"
)


@router.message(CommandStart())
async def cmd_start(message: types.Message, api):
    token = await _ensure_user(message, api)
    if not token:
        return

    kb = None
    if _settings.MINI_APP_URL:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="📚 Открыть приложение",
                    web_app=WebAppInfo(url=_settings.MINI_APP_URL),
                )
            ]]
        )

    name = (message.from_user.first_name if message.from_user else None) or "друг"

    welcomed = await onboarding.is_flag_set(
        api, token, message.from_user.id if message.from_user else 0,
        onboarding.KEY_WELCOMED,
    )

    if welcomed:
        text = _RETURNING_USER_WELCOME.format(name=name)
    else:
        text = _NEW_USER_WELCOME.format(name=name)

    await message.answer(text, parse_mode=None, reply_markup=kb, disable_web_page_preview=True)

    if not welcomed and message.from_user:
        await onboarding.mark_shown(
            api, token, message.from_user.id, onboarding.KEY_WELCOMED,
        )


@router.message(Command("help"))
async def cmd_help(message: types.Message, api):
    """Полная справка по возможностям бота."""
    token = await _ensure_user(message, api)
    if not token:
        return
    await message.answer(_HELP_TEXT, parse_mode=None, disable_web_page_preview=True)


@router.message(Command("list"))
async def cmd_list(message: types.Message, api):
    """Просмотр закладок с inline-кнопками."""
    token = await _ensure_user(message, api)
    if not token:
        return

    parts = message.text.split()
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    await _send_list(message, api, token, page)


async def _send_list(target, api, token: str, page: int = 1):
    """Отправляет список закладок. target — Message или CallbackQuery."""
    per_page = 5

    try:
        data = await api.get_bookmarks(token, page=page, per_page=per_page)
    except Exception as e:
        logger.error(f"List failed: {e}")
        if isinstance(target, CallbackQuery):
            await target.answer("Ошибка загрузки", show_alert=True)
        else:
            await target.answer("Ошибка. Попробуй позже.", parse_mode=None)
        return

    items = data.get("items", [])
    total = data.get("total", 0)

    if not items:
        text = "У тебя пока нет сохранённых закладок."
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text)
        else:
            await target.answer(text, parse_mode=None)
        return

    total_pages = (total + per_page - 1) // per_page
    lines = [f"<b>Закладки</b> (стр. {page}/{total_pages}, всего {total}):\n"]

    for i, b in enumerate(items, start=(page - 1) * per_page + 1):
        title = b.get("title") or "Без названия"
        summary = b.get("summary") or b["raw_text"][:80]
        tags = b.get("tags", [])
        created = b.get("created_at", "")

        # Форматируем дату
        date_str = ""
        if created:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                date_str = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                date_str = ""

        entry = f"{i}. <b>{title}</b>"
        if date_str:
            entry += f"  <i>({date_str})</i>"
        entry += f"\n{summary}"
        if tags:
            tag_str = " ".join(f"#{t['name']}" for t in tags[:4])
            entry += f"\n{tag_str}"

        lines.append(entry)

    text = "\n\n".join(lines)

    # Inline-кнопки для каждой закладки
    buttons = []
    for b in items:
        bid = b["id"]
        title_short = (b.get("title") or "Без названия")[:25]
        buttons.append([
            InlineKeyboardButton(text=f"📖 {title_short}", callback_data=f"view:{bid}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del:{bid}"),
        ])

    # Навигация
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page:{page - 1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)


# ─── Callback-и для inline-кнопок ───


@router.callback_query(F.data.startswith("page:"))
async def cb_page(callback: CallbackQuery, api):
    """Пагинация списка."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    token = await _ensure_user(callback, api)
    if not token:
        return

    page = int(callback.data.split(":")[1])
    await _send_list(callback, api, token, page)
    await callback.answer()


@router.callback_query(F.data.startswith("view:"))
async def cb_view(callback: CallbackQuery, api):
    """Просмотр полной закладки."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    token = await _ensure_user(callback, api)
    if not token:
        return

    bid = callback.data.split(":")[1]

    try:
        bookmark = await api.get_bookmark(token, bid)
    except Exception as e:
        logger.error(f"View failed: {e}")
        await callback.answer("Ошибка загрузки", show_alert=True)
        return

    title = bookmark.get("title") or "Без названия"
    raw_text = bookmark.get("raw_text", "")
    summary = bookmark.get("summary") or ""
    category = bookmark.get("category") or ""
    url = bookmark.get("url")
    tags = bookmark.get("tags", [])
    ai_status = bookmark.get("ai_status", "pending")

    lines = [f"<b>{title}</b>"]

    if category:
        lines.append(f"Категория: {category}")

    if tags:
        tag_str = " ".join(f"#{t['name']}" for t in tags)
        lines.append(f"Теги: {tag_str}")

    status_map = {"completed": "✅", "processing": "⏳", "pending": "🕐", "failed": "❌", "partial": "⚠️"}
    lines.append(f"Статус: {status_map.get(ai_status, '?')} {ai_status}")

    if summary:
        lines.append(f"\n<b>Саммари:</b>\n{summary}")

    if url:
        lines.append(f'\n<b>Ссылка:</b> <a href="{url}">{url[:60]}...</a>' if len(url) > 60 else f'\n<b>Ссылка:</b> <a href="{url}">{url}</a>')

    # Полный текст (обрезаем до 3000 символов для Telegram)
    if raw_text and raw_text != summary:
        display_text = raw_text[:3000]
        if len(raw_text) > 3000:
            display_text += "\n\n... (текст обрезан)"
        lines.append(f"\n<b>Полный текст:</b>\n{display_text}")

    text = "\n".join(lines)

    # Кнопки
    buttons = [
        [
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{bid}"),
            InlineKeyboardButton(text="◀️ К списку", callback_data="page:1"),
        ]
    ]
    if url:
        buttons.insert(0, [InlineKeyboardButton(text="🔗 Открыть ссылку", url=url)])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Telegram ограничивает edit_text до 4096 символов
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (обрезано)"

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data.startswith("del:"))
async def cb_delete_confirm(callback: CallbackQuery, api):
    """Запрос подтверждения удаления."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    bid = callback.data.split(":")[1]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_del:{bid}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="page:1"),
        ]
    ])

    await callback.message.edit_text("Удалить эту закладку?", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_del:"))
async def cb_delete_execute(callback: CallbackQuery, api):
    """Удаление закладки после подтверждения."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    token = await _ensure_user(callback, api)
    if not token:
        return

    bid = callback.data.split(":")[1]

    try:
        await api.delete_bookmark(token, bid)
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        await callback.answer("Ошибка удаления", show_alert=True)
        return

    await callback.answer("Удалено!")
    # Возвращаемся к списку
    await _send_list(callback, api, token, page=1)


# ─── Подтверждение сохранения коротких сообщений ───


@router.callback_query(F.data.startswith("save_yes:"))
async def cb_save_confirm(callback: CallbackQuery, api):
    """Подтверждение сохранения короткого сообщения."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение устарело.", show_alert=True)
        return

    token = await _ensure_user(callback, api)
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
async def cb_save_cancel(callback: CallbackQuery):
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
    token = await _ensure_user(message, api)
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


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: types.Message, api, store=None):
    """Обработка обычных текстовых сообщений (не команд)."""
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

    token = await _ensure_user(message, api)
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
    token = await _ensure_user(message, api)
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
