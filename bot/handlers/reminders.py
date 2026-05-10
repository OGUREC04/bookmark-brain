"""Бот-handlers для напоминаний (Phase 2.5 T6).

Состоит из:
1. Четыре callback'а на inline-кнопках:
   - rsk:{bookmark_id}    — юзер подтвердил создание после save → просим время
   - rsn:{bookmark_id}    — отказ → убираем кнопки, чистим state
   - rdone:{reminder_id}  — нажал «Выполнено» на отправленном reminder
   - rsnz:{reminder_id}   — нажал «Продлить» → просим новое время
2. Reply-handler: ловит reply на сообщение с pending offer или snooze,
   парсит время через `backend.app.services.nl_date.parse()`, дёргает API.

Ключи Redis (ставит worker, читает бот):
  reminder_pending:{chat_id}:{msg_id} → bookmark_id (TTL 1ч)
  reminder:{chat_id}:{msg_id}         → reminder_id (TTL 25ч)
  reminder_snooze:{chat_id}:{msg_id}  → reminder_id (TTL 1ч)
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)

router = Router()

# Часовой пояс по умолчанию — если у юзера в users.timezone пусто или
# зона не распарсилась.
DEFAULT_TZ = "Europe/Moscow"

# Подсказка с примерами для reply'я (используется в rsk: и rsnz:)
TIME_EXAMPLES = (
    "Примеры:\n"
    "• <code>через час</code>\n"
    "• <code>завтра в 9</code>\n"
    "• <code>в субботу в 18</code>\n"
    "• <code>15 мая</code>"
)


# ──────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────


async def _get_user_tz_name(api, token: str) -> str:
    """IANA-имя часового пояса юзера. Fallback Europe/Moscow если поле
    пусто или невалидно. Возвращаем строку — `nl_date.parse()` сам
    валидирует через ZoneInfo внутри."""
    try:
        user = await api.get_me(token)
        tz_name = (user or {}).get("timezone") or DEFAULT_TZ
    except Exception as e:
        logger.warning(f"_get_user_tz_name: get_me failed, using {DEFAULT_TZ}: {e}")
        return DEFAULT_TZ
    try:
        ZoneInfo(tz_name)  # валидируем
        return tz_name
    except Exception:
        logger.warning(f"_get_user_tz_name: invalid tz {tz_name!r}, fallback {DEFAULT_TZ}")
        return DEFAULT_TZ


def _format_fire_at(fire_at: datetime, tz_name: str) -> str:
    """Локализованное «11.05 09:00» для подтверждения юзеру."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_TZ)
    local = fire_at.astimezone(tz)
    return local.strftime("%d.%m %H:%M")


# ──────────────────────────────────────────────────
# /remind — explicit команда (T11 v2.1)
# ──────────────────────────────────────────────────


REMIND_HELP_TEXT = (
    "❓ <b>Создание напоминания</b>\n\n"
    "<code>/remind &lt;текст&gt; &lt;когда&gt;</code>\n\n"
    "<b>Пример:</b>\n"
    "<code>/remind купить хлеб завтра в 9</code>\n"
    "<code>/remind позвонить маме в субботу</code>\n"
    "<code>/remind заплатить за квартиру 15.05</code>\n\n"
    "💡 <b>Когда:</b> завтра, через час, в субботу, 15.05, в 18:00, "
    "утром / вечером / ночью\n\n"
    "📋 <code>/reminders</code> — список активных + история"
)


def _split_remind_text_and_time(args: str) -> tuple[str, str | None]:
    """Разделяет аргументы /remind на текст напоминания и временную часть.

    Стратегия: пробуем парсить ВСЁ как время — если ParseStatus.OK,
    значит времени нет (всё - время). Иначе ищем временную фразу с конца:
    последние 2-5 токенов отдаём парсеру, если OK — это время, остальное
    — текст. Если ничего не парсится — весь ввод считается текстом без
    времени.

    Возвращает (text, time_part_or_None).
    """
    from backend.app.services.nl_date import ParseStatus, parse

    args = args.strip()
    if not args:
        return "", None

    tokens = args.split()
    n = len(tokens)

    # Эвристика: пробуем БÓЛЬШЕЕ окно с конца (5..1 токенов).
    # Учитываем OK И IN_PAST как «time match» — иначе «вчера в 9» (3 токена)
    # пропускается потому что «в 9» (2 токена) парсится в OK раньше.
    # IN_PAST потом ловится в cmd_remind с осмысленным сообщением юзеру.
    valid_statuses = (ParseStatus.OK, ParseStatus.IN_PAST)
    for window in range(min(5, n), 0, -1):
        time_part = " ".join(tokens[n - window:])
        text_part = " ".join(tokens[: n - window])
        result = parse(time_part)
        if result.status in valid_statuses and text_part:
            return text_part.strip(), time_part.strip()

    # Время не найдено — весь ввод как текст.
    return args, None


@router.message(Command("remind"))
async def cmd_remind(message: Message, command: CommandObject, api, store):
    """T11: explicit команда /remind для создания напоминания без AI/закладки."""
    from bot.handlers.start import _ensure_user
    from backend.app.services.nl_date import ParseStatus, parse

    args = (command.args or "").strip()

    # Без аргументов — справка
    if not args:
        await message.answer(REMIND_HELP_TEXT, parse_mode="HTML")
        return

    token = await _ensure_user(message, api)
    if not token:
        return

    user_tz_name = await _get_user_tz_name(api, token)
    text_part, time_part = _split_remind_text_and_time(args)

    if time_part is None:
        # Текст без времени — спрашиваем reply со временем.
        prompt = await message.answer(
            f"Когда напомнить «<b>{text_part or args}</b>»? "
            f"<b>Reply</b> на это сообщение со временем.\n\n"
            f"{TIME_EXAMPLES}",
            parse_mode="HTML",
        )
        # Сохраняем pending state — bookmark_id=None т.к. это explicit
        # /remind без закладки. Используем отдельный ключ из-за специфики:
        # reminder_pending_explicit:{chat}:{msg} → text (а не bookmark_id).
        if prompt is not None and getattr(prompt, "message_id", None) is not None:
            try:
                # Reuse store_reminder_pending — но bid сохраним в формате
                # "explicit:<text>" чтобы reply-handler различал.
                # Альтернатива — отдельный метод, но это +API surface.
                payload_marker = f"__explicit__|{text_part or args}"
                # Сохраним через прямой Redis-set чтобы избежать API-расширения.
                # store.set_reminder_pending пока нет — используем _r напрямую.
                r = await store._get()
                await r.set(
                    f"reminder_pending:{message.chat.id}:{prompt.message_id}",
                    payload_marker,
                    ex=3600,
                )
            except Exception as e:
                logger.warning(f"cmd_remind: failed to save pending state: {e}")
        return

    # Время есть — парсим, создаём reminder сразу
    parse_result = parse(time_part, user_tz=user_tz_name)

    if parse_result.status == ParseStatus.IN_PAST:
        await message.answer(
            "Это в прошлом. Назначь время в будущем.", parse_mode=None,
        )
        return

    if parse_result.status == ParseStatus.NEEDS_TIME:
        await message.answer(
            "Уточни время (например «в 9»). " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        return

    if parse_result.status == ParseStatus.UNPARSEABLE or parse_result.dt is None:
        # Странно — мы же пропустили через _split. Скорее всего dateparser
        # моргнул. Просим reply со временем.
        await message.answer(
            f"Не понял время «{time_part}». " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        return

    if parse_result.status == ParseStatus.FALLBACK_DEFAULT:
        # Размытое — confirm flow (F2 паттерн)
        proposed = _format_fire_at(parse_result.dt, user_tz_name)
        prompt = await message.answer(
            f"Не понял точное время. Поставить «<b>{text_part}</b>» на "
            f"<b>{proposed}</b>?\n<b>Reply «да»</b> или укажи точнее.",
            parse_mode="HTML",
        )
        if prompt is not None and getattr(prompt, "message_id", None) is not None:
            try:
                # Для explicit /remind в fallback используем kind="explicit_create"
                # чтобы _apply_reminder_action знал что bookmark_id=None и брал
                # text из target_id.
                await store.store_reminder_fallback(
                    message.chat.id, prompt.message_id,
                    kind="explicit_create",
                    target_id=text_part,
                    proposed_dt_iso=parse_result.dt.isoformat(),
                )
            except Exception as e:
                logger.warning(f"store_reminder_fallback failed: {e}")
        return

    # ParseStatus.OK — создаём reminder сразу
    try:
        await api.create_reminder(
            token,
            parse_result.dt.isoformat(),
            bookmark_id=None,
            payload={"text": text_part, "source": "explicit_remind"},
        )
    except Exception as e:
        logger.warning(f"cmd_remind create failed: {e}")
        await message.answer(
            "Не получилось создать напоминание. Попробуй ещё раз.",
            parse_mode=None,
        )
        return

    when = _format_fire_at(parse_result.dt, user_tz_name)
    await message.answer(
        f"🔔 Напомню <b>{when}</b> — «{text_part}»",
        parse_mode="HTML",
    )


# ──────────────────────────────────────────────────
# Callbacks
# ──────────────────────────────────────────────────


@router.callback_query(F.data.startswith("rsk:"))
async def cb_create_reminder(callback: CallbackQuery, api, store):
    """Юзер нажал «🔔 Создать напоминание?» — просим reply со временем.

    Bookmark_id мы НЕ берём из callback_data (хотя он там есть) — берём
    из Redis-ключа `reminder_pending:{chat_id}:{msg_id}` который ставит
    worker. Так не зависим от целостности callback_data.
    """
    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id

    try:
        await callback.message.edit_text(
            "Когда напомнить? <b>Ответь reply</b> на это сообщение со временем.\n\n"
            f"{TIME_EXAMPLES}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.debug(f"cb_create_reminder: edit_text failed: {e}")
    # Redis key (reminder_pending:...) уже стоит — worker его поставил.
    # TTL 1ч хватит на ответ.
    try:
        await callback.answer("Жду время")
    except Exception:
        pass


@router.callback_query(F.data.startswith("rsn:"))
async def cb_dismiss_reminder(callback: CallbackQuery, api, store):
    """Юзер отказался от напоминания — убираем кнопки, чистим state."""
    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id

    try:
        await callback.message.edit_text(
            "Окей, без напоминания.",
            parse_mode=None,
        )
    except Exception as e:
        logger.debug(f"cb_dismiss_reminder: edit_text failed: {e}")
    try:
        await store.delete_reminder_pending(chat_id, msg_id)
    except Exception as e:
        logger.debug(f"cb_dismiss_reminder: delete state failed: {e}")
    try:
        await callback.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("rdone:"))
async def cb_done_reminder(callback: CallbackQuery, api, store):
    """«✅ Выполнено» на отправленном reminder — DELETE через API
    (status='cancelled') + edit message без кнопок."""
    from bot.handlers.start import _ensure_user

    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id
    reminder_id = (callback.data or "").split(":", 1)[1] if ":" in (callback.data or "") else ""

    token = await _ensure_user(callback, api)
    if not token:
        return

    cancelled_ok = False
    try:
        await api.cancel_reminder(token, reminder_id)
        cancelled_ok = True
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            # Уже cancelled / auto_done / second click — считаем успехом.
            cancelled_ok = True
        else:
            logger.warning(f"cb_done_reminder: cancel 5xx: {e}")
    except Exception as e:
        logger.warning(f"cb_done_reminder: cancel failed: {e}")

    if not cancelled_ok:
        # Не редактируем сообщение и не чистим state — юзер сможет
        # повторить клик. Показываем popup.
        try:
            await callback.answer(
                "Не получилось отметить — попробуй ещё раз",
                show_alert=False,
            )
        except Exception:
            pass
        return

    try:
        await callback.message.edit_text("✅ Выполнено", parse_mode=None)
    except Exception as e:
        logger.debug(f"cb_done_reminder: edit_text failed: {e}")
    try:
        await store.delete_reminder_id(chat_id, msg_id)
    except Exception as e:
        logger.debug(f"cb_done_reminder: delete state failed: {e}")
    try:
        await callback.answer("Готово")
    except Exception:
        pass


@router.callback_query(F.data.startswith("rsnz:"))
async def cb_snooze_reminder(callback: CallbackQuery, api, store):
    """«💤 Продлить» — сохраняем reminder_id в snooze-state, просим
    новое время через reply."""
    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id
    reminder_id = (callback.data or "").split(":", 1)[1] if ":" in (callback.data or "") else ""

    # F4: invert order — edit_text first, store_snooze only on success.
    # Иначе: если edit упадёт, в Redis висит orphan reminder_snooze key
    # (TTL 1ч), и любой reply на этот msg_id будет ошибочно ловиться как
    # snooze-ответ.
    try:
        await callback.message.edit_text(
            "💤 На сколько продлить? <b>Ответь reply</b> со временем.\n\n"
            f"{TIME_EXAMPLES}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"cb_snooze_reminder: edit_text failed, NOT storing state: {e}")
        try:
            await callback.answer("Не получилось — попробуй ещё раз")
        except Exception:
            pass
        return

    if reminder_id:
        try:
            await store.store_reminder_snooze(chat_id, msg_id, reminder_id)
        except Exception as e:
            logger.warning(f"cb_snooze_reminder: store_snooze failed: {e}")

    try:
        await callback.answer()
    except Exception:
        pass


# ──────────────────────────────────────────────────
# Reply-handler — парсинг времени
# ──────────────────────────────────────────────────


async def handle_reminder_reply(message: Message, api, store) -> bool:
    """Обработка reply'я когда чат ждёт время от юзера.

    Возвращает True если reply распознан как reminder-related (не важно
    успешно или с ошибкой — просто чтобы вызывающий код не передавал в
    catch-all). False — этот reply нас не касается.
    """
    rt = message.reply_to_message
    if rt is None:
        return False

    chat_id = message.chat.id
    reply_to_id = rt.message_id

    # Read-only: state удалим ТОЛЬКО после успеха API. Иначе на 5xx
    # юзеру говорим «попробуй ещё раз», но retry'нуть нечем — state уже
    # consumed. Read+delete-on-success жертвует GETDEL-атомарностью, но
    # double-reply защищён tем что после delete второй reply пойдёт по
    # пути «state нет» → SkipHandler → tasks-fallback (не страшно).

    # F2: confirm-state имеет приоритет над snooze/pending. Если бот ждёт
    # «да/уточни» по предложенному fallback-времени — обрабатываем здесь.
    fallback_state = None
    try:
        fallback_state = await store.get_reminder_fallback(chat_id, reply_to_id)
    except Exception as e:
        logger.debug(f"handle_reminder_reply: get_fallback failed: {e}")

    if fallback_state is not None:
        return await _handle_fallback_confirm_reply(
            message, api, store, fallback_state, reply_to_id,
        )

    snooze_rid = None
    try:
        snooze_rid = await store.get_reminder_snooze(chat_id, reply_to_id)
    except Exception as e:
        logger.debug(f"handle_reminder_reply: get_snooze failed: {e}")

    pending_bid = None
    if not snooze_rid:
        try:
            pending_bid = await store.get_reminder_pending(chat_id, reply_to_id)
        except Exception as e:
            logger.debug(f"handle_reminder_reply: get_pending failed: {e}")

    if not snooze_rid and not pending_bid:
        return False  # reply не наш

    from bot.handlers.start import _ensure_user

    token = await _ensure_user(message, api)
    if not token:
        return True  # наш reply, но без токена — просто молча выйти

    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Не понял время. " + TIME_EXAMPLES, parse_mode="HTML",
        )
        return True

    # Парсер живёт в backend/app/services/nl_date.py.
    # Оба процесса (bot, worker) импортируют его одинаково.
    from backend.app.services.nl_date import ParseStatus, parse

    user_tz_name = await _get_user_tz_name(api, token)
    result = parse(text, user_tz=user_tz_name)

    if result.status == ParseStatus.UNPARSEABLE:
        await message.answer(
            "Не понял время. " + TIME_EXAMPLES, parse_mode="HTML",
        )
        return True
    if result.status == ParseStatus.IN_PAST:
        await message.answer(
            "Это в прошлом. Назначь время в будущем.",
            parse_mode=None,
        )
        return True
    if result.status == ParseStatus.NEEDS_TIME:
        await message.answer(
            "Уточни время (например «в 9» или «в 18:30»). " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        return True

    # F2: FALLBACK_DEFAULT — НЕ создаём reminder молча. Спрашиваем confirm.
    if result.status == ParseStatus.FALLBACK_DEFAULT and result.dt is not None:
        kind = "snooze" if snooze_rid else "create"
        target_id = snooze_rid or pending_bid
        proposed = _format_fire_at(result.dt, user_tz_name)
        prompt = await message.answer(
            f"Не понял точное время. Поставить на <b>{proposed}</b>?\n"
            f"<b>Reply «да»</b> — подтверждаю, или укажи время точнее "
            f"(например «через час», «завтра в 9»).",
            parse_mode="HTML",
        )
        # Сохраняем proposed в state до confirm.
        if prompt is not None and getattr(prompt, "message_id", None) is not None:
            try:
                await store.store_reminder_fallback(
                    chat_id, prompt.message_id,
                    kind=kind, target_id=target_id,
                    proposed_dt_iso=result.dt.isoformat(),
                )
            except Exception as e:
                logger.warning(f"store_reminder_fallback failed: {e}")
        return True

    # OK — у нас валидный datetime
    if result.dt is None:
        await message.answer(
            "Не понял время. " + TIME_EXAMPLES, parse_mode="HTML",
        )
        return True

    fire_at_iso = result.dt.isoformat()

    if snooze_rid:
        try:
            await api.update_reminder(token, snooze_rid, fire_at_iso)
        except Exception as e:
            logger.warning(f"update_reminder failed: {e}")
            # State не трогаем — юзер сможет повторить reply.
            await message.answer(
                "Не получилось продлить — попробуй ещё раз.",
                parse_mode=None,
            )
            return True

        # Успех — теперь чистим state (защита от double-reply).
        try:
            await store.delete_reminder_snooze(chat_id, reply_to_id)
        except Exception as e:
            logger.debug(f"delete_reminder_snooze failed: {e}")

        await message.answer(
            f"💤 Продлено до <b>{_format_fire_at(result.dt, user_tz_name)}</b>",
            parse_mode="HTML",
        )
        return True

    # pending_bid — создание нового reminder.
    # Если bid начинается с "__explicit__|" — это /remind без времени,
    # bid в действительности содержит текст напоминания. bookmark_id=None.
    explicit_text = None
    actual_bid = pending_bid
    if isinstance(pending_bid, str) and pending_bid.startswith("__explicit__|"):
        explicit_text = pending_bid[len("__explicit__|"):]
        actual_bid = None  # explicit /remind не привязан к bookmark

    payload = {
        "text": explicit_text if explicit_text else text,
        "source": "explicit_remind" if explicit_text else "implicit_weak",
    }

    try:
        await api.create_reminder(
            token,
            fire_at_iso,
            bookmark_id=actual_bid,
            payload=payload,
        )
    except Exception as e:
        logger.warning(f"create_reminder failed: {e}")
        # State не трогаем — юзер может повторить.
        await message.answer(
            "Не получилось создать напоминание — попробуй ещё раз.",
            parse_mode=None,
        )
        return True

    # Успех — чистим pending state.
    try:
        await store.delete_reminder_pending(chat_id, reply_to_id)
    except Exception as e:
        logger.debug(f"delete_reminder_pending failed: {e}")

    await message.answer(
        f"🔔 Напомню <b>{_format_fire_at(result.dt, user_tz_name)}</b>",
        parse_mode="HTML",
    )
    return True


# ──────────────────────────────────────────────────
# Router-level message hook
# ──────────────────────────────────────────────────


_FALLBACK_CONFIRM_YES = ("да", "ага", "ок", "окей", "yes", "y", "+", "подтверждаю")


async def _handle_fallback_confirm_reply(
    message: Message, api, store,
    fallback_state: dict,
    reply_to_id: int,
) -> bool:
    """F2: юзер reply'ит на «поставить на 11.05 22:00? да / уточни».

    Если ответ — confirm-слово → создаём/обновляем reminder с предложенным
    временем. Если другое — пробуем парсить как новое время. Если и оно
    fallback — снова спрашиваем confirm (с новым state).
    """
    from bot.handlers.start import _ensure_user
    from backend.app.services.nl_date import ParseStatus, parse

    chat_id = message.chat.id
    text = (message.text or "").strip()
    text_lower = text.lower()

    token = await _ensure_user(message, api)
    if not token:
        return True

    kind = fallback_state.get("kind")
    target_id = fallback_state.get("target_id")
    dt_iso = fallback_state.get("dt_iso")

    if not target_id or not dt_iso or kind not in ("create", "snooze", "explicit_create"):
        # Битый state — лучше выйти.
        try:
            await store.pop_reminder_fallback(chat_id, reply_to_id)
        except Exception:
            pass
        return True

    user_tz_name = await _get_user_tz_name(api, token)

    is_confirm = any(text_lower == w or text_lower.startswith(w + " ") for w in _FALLBACK_CONFIRM_YES)

    if is_confirm:
        return await _apply_reminder_action(
            message, api, store, kind, target_id, dt_iso, user_tz_name,
            confirm_msg_id=reply_to_id,
        )

    # Не confirm — пробуем парсить как новое время.
    result = parse(text, user_tz=user_tz_name)
    if result.status == ParseStatus.OK and result.dt is not None:
        return await _apply_reminder_action(
            message, api, store, kind, target_id, result.dt.isoformat(), user_tz_name,
            confirm_msg_id=reply_to_id,
        )

    if result.status == ParseStatus.IN_PAST:
        await message.answer("Это в прошлом. Назначь время в будущем.", parse_mode=None)
        return True

    if result.status == ParseStatus.NEEDS_TIME:
        await message.answer(
            "Уточни время (например «в 9» или «в 18:30»). " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        return True

    if result.status == ParseStatus.FALLBACK_DEFAULT and result.dt is not None:
        # Снова размытое — спрашиваем confirm с новым предложенным временем.
        proposed = _format_fire_at(result.dt, user_tz_name)
        prompt = await message.answer(
            f"Снова не понял. Поставить на <b>{proposed}</b>?\n"
            f"<b>Reply «да»</b> или укажи точнее.",
            parse_mode="HTML",
        )
        if prompt is not None and getattr(prompt, "message_id", None) is not None:
            try:
                await store.store_reminder_fallback(
                    chat_id, prompt.message_id,
                    kind=kind, target_id=target_id,
                    proposed_dt_iso=result.dt.isoformat(),
                )
                # Старый state можно почистить — мы заменили его новым.
                await store.pop_reminder_fallback(chat_id, reply_to_id)
            except Exception as e:
                logger.warning(f"fallback re-store failed: {e}")
        return True

    # UNPARSEABLE — оставляем старый state, просим переформулировать.
    await message.answer(
        "Не понял. " + TIME_EXAMPLES + "\nИли reply «да» чтобы согласиться с прошлым временем.",
        parse_mode="HTML",
    )
    return True


async def _apply_reminder_action(
    message: Message, api, store,
    kind: str, target_id: str, fire_at_iso: str, user_tz_name: str,
    confirm_msg_id: int,
) -> bool:
    """Финальный create/update reminder + чистка fallback-state."""
    from datetime import datetime
    chat_id = message.chat.id

    # Получаем токен
    from bot.handlers.start import _ensure_user
    token = await _ensure_user(message, api)
    if not token:
        return True

    text_payload = (message.text or "").strip()

    try:
        if kind == "snooze":
            await api.update_reminder(token, target_id, fire_at_iso)
        elif kind == "explicit_create":
            # explicit /remind: target_id содержит ТЕКСТ (не bookmark_id)
            await api.create_reminder(
                token, fire_at_iso,
                bookmark_id=None,
                payload={"text": target_id, "source": "explicit_remind"},
            )
        else:  # create (implicit_weak fallback confirm)
            await api.create_reminder(
                token, fire_at_iso,
                bookmark_id=target_id,
                payload={"text": text_payload, "source": "implicit_weak"},
            )
    except Exception as e:
        logger.warning(f"_apply_reminder_action {kind} failed: {e}")
        # State не трогаем — юзер может повторить «да».
        await message.answer(
            "Не получилось — попробуй ещё раз.",
            parse_mode=None,
        )
        return True

    # Успех — чистим fallback state.
    try:
        await store.pop_reminder_fallback(chat_id, confirm_msg_id)
    except Exception as e:
        logger.debug(f"pop_reminder_fallback failed: {e}")

    try:
        dt = datetime.fromisoformat(fire_at_iso)
    except Exception:
        dt = None

    when = _format_fire_at(dt, user_tz_name) if dt else fire_at_iso
    label = "💤 Продлено до" if kind == "snooze" else "🔔 Напомню"
    await message.answer(f"{label} <b>{when}</b>", parse_mode="HTML")
    return True


@router.message(F.reply_to_message & F.text & ~F.text.startswith("/"))
async def _reply_dispatch(message: Message, api, store):
    """Перехватываем reply ДО tasks/start. Если это reminder-reply —
    обработали и возвращаемся. Иначе `raise SkipHandler`, чтобы aiogram
    передал событие следующему router'у (tasks → ... → start catch-all).
    """
    from aiogram.dispatcher.event.bases import SkipHandler

    handled = await handle_reminder_reply(message, api, store)
    if handled:
        return
    raise SkipHandler()
