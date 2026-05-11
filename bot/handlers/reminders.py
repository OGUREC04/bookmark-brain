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

import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID
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

# Безопасные лимиты на пользовательский текст перед записью в Redis.
# Защита от DoS-наполнения памяти Redis (H2 из security review).
MAX_REMINDER_TEXT_LEN = 500
# Максимальная длина reply-текста перед передачей в dateparser (M2 защитный).
MAX_PARSE_INPUT_LEN = 200


def _safe(s: str | None) -> str:
    """HTML-escape для встраивания юзерского текста в parse_mode=HTML.

    Telegram HTML mode допускает `<a>`, `<b>`, `<i>`, `<code>`, `<pre>` —
    без экранирования юзер может вставить `<a href="tg://...">` (C-sec).
    """
    return html.escape(s or "", quote=False)


def _cap_text(s: str | None, limit: int = MAX_REMINDER_TEXT_LEN) -> str:
    """Обрезаем пользовательский текст до безопасного лимита."""
    if not s:
        return ""
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


def _is_valid_uuid(s: str | None) -> bool:
    """Проверка что строка из callback_data — валидный UUID.

    Защита от подделанного callback_data (H1): без валидации значение
    напрямую улетает в API URL.
    """
    if not s:
        return False
    try:
        UUID(s)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


async def _send_reminder_confirmation_with_chip(
    message: Message, fire_at: datetime, reminder_text: str, tz_name: str,
) -> None:
    """Подтверждение reminder с полным форматом даты для авто-детекции
    клиентом Telegram.

    Bot API 9.5 разрешает date_time MessageEntity только в checklist /
    quote / gift, причём checklist требует business_connection_id —
    обычные боты её слать не могут. Поэтому полагаемся на client-side
    NSDataDetector / TextClassifier: полный формат «12.05.2026 09:00»
    распознаётся iOS/Android клиентами как дата с long-press меню
    «добавить в календарь». Работает не на всех клиентах, но это
    лучшее что доступно без business-режима.
    """
    short_text = (reminder_text or "").strip() or "напоминание"
    if len(short_text) > 60:
        short_text = short_text[:57] + "..."

    # Полный формат даты ДД.ММ.ГГГГ ЧЧ:ММ — авто-детект на стороне клиента.
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_TZ)
    local = fire_at.astimezone(tz)
    formatted_full = local.strftime("%d.%m.%Y %H:%M")

    await message.answer(
        f"🔔 Напомню <b>{_safe(formatted_full)}</b> — «{_safe(short_text)}»",
        parse_mode="HTML",
    )


def extract_first_datetime_entity(message: Message) -> datetime | None:
    """T19 (Bot API 9.5): если в сообщении есть MessageEntity type='date_time' —
    Telegram-клиент уже определил дату в локали и таймзоне юзера. Используем
    готовый unix_time, парсер не нужен.

    Fallback на nl_date.parse если entity нет (старые клиенты до Bot API 9.5).
    """
    entities = list(message.entities or []) + list(message.caption_entities or [])
    for ent in entities:
        ent_type = getattr(ent, "type", None)
        # aiogram отдаёт enum или строку — поддержим оба
        if hasattr(ent_type, "value"):
            ent_type = ent_type.value
        if ent_type == "date_time":
            unix_ts = getattr(ent, "unix_time", None)
            if unix_ts is not None:
                try:
                    return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc)
                except (TypeError, ValueError, OSError):
                    continue
    return None

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
# T13: Pre-AI strong intent detector (отдельный router)
# ──────────────────────────────────────────────────

# Регекс strong-маркеров — только в начале сообщения (50 первых символов).
# Высокая точность, низкий recall: лучше пропустить strong как weak (попадёт в
# обычный flow с offer'ом), чем спросить «напоминание или заметка?» где
# юзер не хотел никакого reminder'а.
_STRONG_INTENT_RE = re.compile(
    r"^\s*(надо|нужно|не\s+забыт[ьи]|срочно|обяза(тельно|н))\b",
    re.IGNORECASE,
)


def is_strong_intent(text: str) -> bool:
    """True если сообщение начинается с strong-маркера.

    Триггеры (только в начале):
      надо, нужно, не забыть/не забыти, срочно, обязательно, обязан

    NOT-trigger:
      «думаю надо как-то» (не в начале)
      «нужное направление» (полное слово другое — \\b защищает)
      «надобность» (\\b после «надо» защищает)
    """
    if not text:
        return False
    head = text[:80]  # с запасом: «не забыть» это 9 символов
    return bool(_STRONG_INTENT_RE.match(head))


# Отдельный router — регистрируется в bot/main.py ПЕРЕД start.router.
strong_router = Router()


_STRONG_PROMPT_TTL = 60 * 60  # 1 час
_STRONG_HANDLED_TTL = 5 * 60  # 5 мин для anti-double-offer flag


@strong_router.message(
    F.text
    & ~F.text.startswith("/")
    & ~F.reply_to_message
    & (F.chat.type == "private")  # защитный — на случай добавления в группы
)
async def handle_strong_intent_message(message: Message, api, store):
    """T13: ловим сообщения с strong intent ДО AI/закладки.

    Если intent сильный — показываем 3-button prompt и ставим anti-double-
    offer флажок. Worker._maybe_offer_reminder проверит флажок и не пошлёт
    weak-offer если юзер выбрал «📝 Заметка».

    Если intent НЕ сильный — `raise SkipHandler` → событие падает дальше
    на start.handle_text без изменений.
    """
    from aiogram.dispatcher.event.bases import SkipHandler

    text = (message.text or "").strip()
    if not is_strong_intent(text):
        raise SkipHandler()

    chat_id = message.chat.id

    # Pre-validation: длина, не команда, не пустота
    if len(text) < 4 or len(text) > 1000:
        raise SkipHandler()

    # 3 кнопки: 🔔 / 📝 / ✕
    buttons = {
        "inline_keyboard": [
            [
                {"text": "🔔 Напомнить", "callback_data": "rstrong_b"},
                {"text": "📝 Заметка", "callback_data": "rstrong_n"},
                {"text": "✕", "callback_data": "rstrong_x"},
            ]
        ]
    }

    try:
        prompt = await message.answer(
            "🔔 Это напоминание или заметка?",
            reply_markup=buttons,
            parse_mode=None,
        )
    except Exception as e:
        logger.warning(f"strong_intent: failed to send prompt: {e}")
        raise SkipHandler()

    if prompt is None or not getattr(prompt, "message_id", None):
        raise SkipHandler()

    # Pre-parse time из исходного текста (auto-detect).
    # Если есть — сэкономим юзеру шаг «когда?».
    # T19 приоритет: если у юзера Telegram client с Bot API 9.5 — берём
    # date_time entity напрямую (правильная локаль и таймзона). Иначе fallback
    # на текстовый парсер.
    parsed_dt_iso = None
    try:
        from bot.handlers.start import _ensure_user
        token = await _ensure_user(message, api)
        if token:
            user_tz_name = await _get_user_tz_name(api, token)
            entity_dt = extract_first_datetime_entity(message)
            if entity_dt is not None and entity_dt > datetime.now(timezone.utc):
                parsed_dt_iso = entity_dt.isoformat()
                # Не трогаем text — в payload идёт оригинал юзера. Entity offset
                # не вырезаем чтобы юзер видел «надо купить хлеб 13 мая в 9»
                # как полную фразу в reminder.
            else:
                from backend.app.services.nl_date import ParseStatus, parse
                split_text, split_time = _split_remind_text_and_time(text, user_tz_name)
                if split_time:
                    pr = parse(split_time, user_tz=user_tz_name)
                    if pr.status == ParseStatus.OK and pr.dt is not None:
                        parsed_dt_iso = pr.dt.isoformat()
                        text = split_text  # обрезаем время — в payload пойдёт чистый текст
    except Exception as e:
        logger.debug(f"strong_intent: pre-parse failed: {e}")

    # Сохраняем state в Redis (с capped text — H2 защита от DoS)
    state = {
        "text": _cap_text(text),
        "source_msg_id": message.message_id,
        "parsed_dt_iso": parsed_dt_iso,
    }
    try:
        await store.store_reminder_strong(chat_id, prompt.message_id, state)
    except Exception as e:
        logger.warning(f"strong_intent: failed to save state: {e}")
        # Удалим уже отправленный prompt чтобы не было broken-button
        try:
            await prompt.delete()
        except Exception:
            pass
        raise SkipHandler()


def _strong_callback_data_kind(data: str) -> str | None:
    """rstrong_b → 'remind', rstrong_n → 'note', rstrong_x → 'cancel'."""
    if data == "rstrong_b":
        return "remind"
    if data == "rstrong_n":
        return "note"
    if data == "rstrong_x":
        return "cancel"
    return None


@strong_router.callback_query(F.data.startswith("rstrong_"))
async def cb_strong_choice(callback: CallbackQuery, api, store):
    """3 callback'а strong-flow: 🔔 / 📝 / ✕."""
    from bot.handlers.start import _ensure_user

    kind = _strong_callback_data_kind(callback.data or "")
    if kind is None:
        try:
            await callback.answer()
        except Exception:
            pass
        return

    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id

    # Достаём state (атомарный GETDEL через типизированный метод)
    state: dict = {}
    try:
        loaded = await store.pop_reminder_strong(chat_id, msg_id)
    except Exception as e:
        logger.warning(f"cb_strong_choice: state get failed: {e}")
        try:
            await callback.answer("Это сообщение устарело")
        except Exception:
            pass
        return

    if loaded is None:
        # Истёк TTL или второй клик
        try:
            await callback.answer("Это сообщение устарело")
            await callback.message.edit_text("⏱ Это сообщение устарело.", parse_mode=None)
        except Exception:
            pass
        return
    state = loaded

    text = state.get("text", "")
    source_msg_id = state.get("source_msg_id")
    parsed_dt_iso = state.get("parsed_dt_iso")

    if kind == "cancel":
        # ✕ — удаляем prompt, ничего не сохраняем
        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.message.edit_text("✕", parse_mode=None)
            except Exception:
                pass
        try:
            await callback.answer()
        except Exception:
            pass
        return

    token = await _ensure_user(callback, api)
    if not token:
        return

    if kind == "note":
        # 📝 — отправить в обычный AI/bookmark flow напрямую.
        # 1) Ставим anti-double-offer флажок на ИСХОДНОЕ сообщение (не prompt).
        # 2) Edit prompt в «📝 Сохраняю...» и используем его как notify-target
        #    для статуса AI обработки.
        # 3) api.create_bookmark — обычная закладка. Worker увидит флажок и
        #    не покажет offer.
        if source_msg_id is not None:
            try:
                r = await store._get()
                await r.set(
                    f"strong_handled:{chat_id}:{source_msg_id}",
                    "1",
                    ex=_STRONG_HANDLED_TTL,
                )
            except Exception as e:
                logger.warning(f"strong note: set anti-double flag failed: {e}")

        try:
            await callback.message.edit_text("📝 Сохраняю как заметку...", parse_mode=None)
        except Exception:
            pass

        try:
            await api.create_bookmark(
                token=token,
                raw_text=text,
                source="bot_forward",
                source_message_id=source_msg_id,
                notify_chat_id=chat_id,
                notify_message_id=msg_id,  # обновляем prompt-сообщение
                silent=False,  # verbose flow — чтобы edit'ы статуса работали
            )
        except Exception as e:
            logger.warning(f"strong note: create_bookmark failed: {e}")
            try:
                await callback.message.edit_text(
                    "⚠️ Не удалось обработать. Попробуй ещё раз.", parse_mode=None,
                )
            except Exception:
                pass

        try:
            await callback.answer()
        except Exception:
            pass
        return

    # kind == "remind"
    # Если время уже распознано → создаём reminder сразу
    if parsed_dt_iso:
        try:
            await api.create_reminder(
                token, parsed_dt_iso,
                bookmark_id=None,
                payload={"text": text, "source": "strong_intent"},
            )
        except Exception as e:
            logger.warning(f"strong remind auto-create failed: {e}")
            try:
                await callback.message.edit_text(
                    "⚠️ Не получилось. Попробуй ещё раз.", parse_mode=None,
                )
            except Exception:
                pass
            try:
                await callback.answer()
            except Exception:
                pass
            return

        from datetime import datetime
        try:
            dt = datetime.fromisoformat(parsed_dt_iso)
            user_tz_name = await _get_user_tz_name(api, token)
            when = _format_fire_at(dt, user_tz_name)
        except Exception:
            when = parsed_dt_iso
        try:
            await callback.message.edit_text(
                f"🔔 Напомню <b>{_safe(when)}</b> — «{_safe(text)}»", parse_mode="HTML",
            )
        except Exception:
            pass
        try:
            await callback.answer("Готово")
        except Exception:
            pass
        return

    # Времени нет → просим reply со временем (используя explicit-marker)
    try:
        new_prompt = await callback.message.edit_text(
            f"Когда напомнить «<b>{_safe(text)}</b>»? <b>Reply</b> со временем.\n\n"
            f"{TIME_EXAMPLES}",
            parse_mode="HTML",
        )
    except Exception:
        new_prompt = None

    target_msg_id = (
        new_prompt.message_id if new_prompt and getattr(new_prompt, "message_id", None)
        else msg_id
    )
    try:
        await store.store_reminder_pending_explicit(
            chat_id, target_msg_id, _cap_text(text),
        )
    except Exception as e:
        logger.warning(f"strong remind: failed to save pending: {e}")

    try:
        await callback.answer("Жду время")
    except Exception:
        pass


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


def _split_remind_text_and_time(
    args: str, user_tz: str = DEFAULT_TZ,
) -> tuple[str, str | None]:
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
        result = parse(time_part, user_tz=user_tz)
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
    text_part, time_part = _split_remind_text_and_time(args, user_tz_name)

    if time_part is None:
        # Текст без времени — спрашиваем reply со временем.
        display_text = _cap_text(text_part or args, limit=200)
        prompt = await message.answer(
            f"Когда напомнить «<b>{_safe(display_text)}</b>»? "
            f"<b>Reply</b> на это сообщение со временем.\n\n"
            f"{TIME_EXAMPLES}",
            parse_mode="HTML",
        )
        # 12y: explicit /remind без времени — typed envelope через store
        if prompt is not None and getattr(prompt, "message_id", None) is not None:
            try:
                await store.store_reminder_pending_explicit(
                    message.chat.id, prompt.message_id,
                    _cap_text(text_part or args),
                )
            except Exception as e:
                logger.warning(f"cmd_remind: failed to save pending state: {e}")
        return

    # T19: если в исходном /remind сообщении есть date_time entity —
    # юзер сам ввёл «13 мая в 9» и Telegram-клиент уже определил дату.
    # Пропускаем парсер.
    entity_dt = extract_first_datetime_entity(message)
    if entity_dt is not None:
        now_utc = datetime.now(timezone.utc)
        if entity_dt < now_utc - timedelta(seconds=30):
            await message.answer(
                "Это в прошлом. Назначь время в будущем.", parse_mode=None,
            )
            return
        try:
            await api.create_reminder(
                token, entity_dt.isoformat(),
                bookmark_id=None,
                payload={"text": text_part, "source": "explicit_remind"},
            )
        except Exception as e:
            logger.warning(f"cmd_remind entity create failed: {e}")
            await message.answer(
                "Не получилось создать напоминание. Попробуй ещё раз.",
                parse_mode=None,
            )
            return
        # Эксперимент: confirmation через sendChecklist с date_time chip
        await _send_reminder_confirmation_with_chip(
            message, entity_dt, text_part, user_tz_name,
        )
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
            f"Не понял время «{_safe(time_part)}». " + TIME_EXAMPLES,
            parse_mode="HTML",
        )
        return

    if parse_result.status == ParseStatus.FALLBACK_DEFAULT:
        # Размытое — confirm flow (F2 паттерн)
        proposed = _format_fire_at(parse_result.dt, user_tz_name)
        prompt = await message.answer(
            f"Не понял точное время. Поставить «<b>{_safe(text_part)}</b>» на "
            f"<b>{_safe(proposed)}</b>?\n<b>Reply «да»</b> или укажи точнее.",
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
                    target_id=_cap_text(text_part),
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

    # Эксперимент: confirmation через sendChecklist с date_time chip
    await _send_reminder_confirmation_with_chip(
        message, parse_result.dt, text_part, user_tz_name,
    )


# ──────────────────────────────────────────────────
# /reminders — список + история + NL-reply mgmt (T12 v2.1)
# ──────────────────────────────────────────────────


def _format_reminder_short(rem: dict, tz_name: str) -> str:
    """Одна строка для /reminders: «купить хлеб — 11.05 09:00».

    Возвращает HTML-safe строку — текст напоминания экранирован
    (он может прийти из юзерского ввода и попасть в parse_mode=HTML).
    """
    payload = rem.get("payload") or {}
    text = (payload.get("text") or "").strip() or "(без текста)"
    if len(text) > 60:
        text = text[:57] + "..."
    fire_at_iso = rem.get("fire_at") or ""
    when = ""
    try:
        dt = datetime.fromisoformat(fire_at_iso.replace("Z", "+00:00"))
        when = _format_fire_at(dt, tz_name)
    except Exception:
        when = fire_at_iso
    return f"{_safe(text)} — {_safe(when)}"


@router.message(Command("reminders"))
async def cmd_reminders(message: Message, command: CommandObject, api, store):
    """T12: список активных reminder'ов или история (с аргументом «история»)."""
    from bot.handlers.start import _ensure_user

    token = await _ensure_user(message, api)
    if not token:
        return

    arg = (command.args or "").strip().lower()
    show_history = arg in ("история", "history")

    user_tz_name = await _get_user_tz_name(api, token)

    if show_history:
        try:
            data = await api.list_reminder_history(token, limit=20, days=30)
        except Exception as e:
            logger.warning(f"cmd_reminders history failed: {e}")
            await message.answer("Не получилось получить историю.", parse_mode=None)
            return
        items = data.get("items", []) if isinstance(data, dict) else []
        if not items:
            await message.answer(
                "📋 История пуста (за последние 30 дней).", parse_mode=None,
            )
            return
        lines = ["📋 <b>История</b> (последние 30 дней):\n"]
        for i, rem in enumerate(items, 1):
            status_icon = "✅" if rem.get("status") == "done" else "✕"
            lines.append(f"{i}. {status_icon} {_format_reminder_short(rem, user_tz_name)}")
        await message.answer("\n".join(lines), parse_mode="HTML")
        return

    # Активные
    try:
        data = await api.list_upcoming_reminders(token, limit=50)
    except Exception as e:
        logger.warning(f"cmd_reminders upcoming failed: {e}")
        await message.answer("Не получилось получить список.", parse_mode=None)
        return

    items = data.get("items", []) if isinstance(data, dict) else []
    if not items:
        await message.answer(
            "🔔 Активных напоминаний нет.\n\n"
            "Создать: <code>/remind &lt;текст&gt; &lt;когда&gt;</code>",
            parse_mode="HTML",
        )
        return

    lines = ["🔔 <b>Активные напоминания:</b>\n"]
    for i, rem in enumerate(items, 1):
        lines.append(f"{i}. {_format_reminder_short(rem, user_tz_name)}")
    lines.append(
        "\n<i>Reply на это сообщение:</i>\n"
        "• «отмени 1»\n"
        "• «перенеси 2 на завтра в 9»\n"
        "• «история» — выполненные"
    )

    sent = await message.answer("\n".join(lines), parse_mode="HTML")
    if sent is not None and getattr(sent, "message_id", None) is not None:
        # Snapshot IDs — порядок фиксируется
        ids = [str(rem.get("id")) for rem in items]
        try:
            await store.store_reminders_list_snapshot(
                message.chat.id, sent.message_id, ids,
            )
        except Exception as e:
            logger.warning(f"store_reminders_list_snapshot failed: {e}")


# Regex для NL-reply на /reminders
_REMINDERS_CANCEL_RE = re.compile(
    r"^\s*(?:отмен[ия]|удали)\s+(\d+)\s*$",
    re.IGNORECASE,
)
_REMINDERS_RESCHEDULE_RE = re.compile(
    r"^\s*(?:перенеси|продли|снузни|snooze)\s+(\d+)\s+на\s+(.+?)\s*$",
    re.IGNORECASE,
)
_REMINDERS_HISTORY_RE = re.compile(
    r"^\s*(?:истори[яю]|history)\s*$",
    re.IGNORECASE,
)


async def handle_reminders_list_reply(
    message: Message, api, store,
) -> bool:
    """NL-reply на сообщение /reminders.

    Returns True если обработано (наш reply), False иначе.
    """
    rt = message.reply_to_message
    if rt is None:
        return False

    chat_id = message.chat.id
    reply_to_id = rt.message_id

    snapshot = None
    try:
        snapshot = await store.get_reminders_list_snapshot(chat_id, reply_to_id)
    except Exception as e:
        logger.debug(f"get_reminders_list_snapshot failed: {e}")

    if not snapshot:
        return False  # не наш reply

    text = (message.text or "").strip()
    if len(text) > MAX_PARSE_INPUT_LEN:
        # Слишком длинный reply — точно не «отмени 1» / «перенеси 2 на ...».
        # Защита от M2 (длинный ввод в dateparser).
        return False

    # «история» — переключиться на историю
    if _REMINDERS_HISTORY_RE.match(text):
        from aiogram.filters import CommandObject as _CO
        # Эмулируем команду /reminders история
        fake_cmd = _CO(prefix="/", command="reminders", args="история")
        await cmd_reminders(message, fake_cmd, api, store)
        return True

    # «отмени N»
    m = _REMINDERS_CANCEL_RE.match(text)
    if m:
        idx = int(m.group(1)) - 1
        if idx < 0 or idx >= len(snapshot):
            await message.answer(
                f"Нет пункта {idx + 1} в списке. Сделай /reminders заново.",
                parse_mode=None,
            )
            return True
        rid = snapshot[idx]
        from bot.handlers.start import _ensure_user
        token = await _ensure_user(message, api)
        if not token:
            return True
        try:
            await api.cancel_reminder(token, rid)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                await message.answer(
                    "Этот пункт уже отменён или выполнен.", parse_mode=None,
                )
                return True
            await message.answer("Не получилось отменить.", parse_mode=None)
            return True
        except Exception:
            await message.answer("Не получилось отменить.", parse_mode=None)
            return True
        await message.answer(f"✕ Отменено: пункт {idx + 1}", parse_mode=None)
        return True

    # «перенеси N на ...»
    m = _REMINDERS_RESCHEDULE_RE.match(text)
    if m:
        idx = int(m.group(1)) - 1
        time_part = m.group(2).strip()[:MAX_PARSE_INPUT_LEN]  # M2 защита
        if idx < 0 or idx >= len(snapshot):
            await message.answer(
                f"Нет пункта {idx + 1} в списке.", parse_mode=None,
            )
            return True
        rid = snapshot[idx]
        from bot.handlers.start import _ensure_user
        from backend.app.services.nl_date import ParseStatus, parse
        token = await _ensure_user(message, api)
        if not token:
            return True
        user_tz_name = await _get_user_tz_name(api, token)
        result = parse(time_part, user_tz=user_tz_name)
        if result.status == ParseStatus.IN_PAST:
            await message.answer("Это в прошлом.", parse_mode=None)
            return True
        if result.status not in (ParseStatus.OK, ParseStatus.FALLBACK_DEFAULT) or result.dt is None:
            await message.answer(
                f"Не понял время «{_safe(time_part)}». " + TIME_EXAMPLES,
                parse_mode="HTML",
            )
            return True
        try:
            await api.update_reminder(token, rid, result.dt.isoformat())
        except Exception:
            await message.answer("Не получилось перенести.", parse_mode=None)
            return True
        when = _format_fire_at(result.dt, user_tz_name)
        await message.answer(
            f"💤 Перенесено на <b>{_safe(when)}</b>",
            parse_mode="HTML",
        )
        return True

    # Неизвестная команда — показываем подсказку, считаем reply нашим
    await message.answer(
        "Не понял. Reply: «отмени N» / «перенеси N на завтра в 9» / «история»",
        parse_mode=None,
    )
    return True


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

    # H1: callback_data — attacker-controlled. Валидируем как UUID до API.
    if not _is_valid_uuid(reminder_id):
        try:
            await callback.answer("Сообщение устарело")
        except Exception:
            pass
        return

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

    # H1: validate UUID — иначе храним мусор в Redis и потом отдаём в API.
    if not _is_valid_uuid(reminder_id):
        try:
            await callback.answer("Сообщение устарело")
        except Exception:
            pass
        return

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

    # Атомарный pop (GETDEL) — защита от double-reply / race.
    # Цена: на 5xx state уже consumed, юзеру даём «попробуй ещё раз»
    # с одним хвостом — пусть пошлёт reply ещё раз руками, чем оставлять
    # окно для двойного create при быстром double-tap.

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
        snooze_rid = await store.pop_reminder_snooze(chat_id, reply_to_id)
    except Exception as e:
        logger.debug(f"handle_reminder_reply: pop_snooze failed: {e}")

    pending_bid = None
    if not snooze_rid:
        try:
            pending_bid = await store.pop_reminder_pending(chat_id, reply_to_id)
        except Exception as e:
            logger.debug(f"handle_reminder_reply: pop_pending failed: {e}")

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

    # T19: Bot API 9.5 — date_time entity. Telegram-клиент сам определил
    # дату в локали и таймзоне юзера. Если entity есть — пропускаем парсер.
    user_tz_name = await _get_user_tz_name(api, token)
    entity_dt = extract_first_datetime_entity(message)
    if entity_dt is not None:
        # Проверка прошлое/будущее на стороне бота (валидация одинаковая)
        now_utc = datetime.now(timezone.utc)
        if entity_dt < now_utc - timedelta(seconds=30):
            await message.answer(
                "Это в прошлом. Назначь время в будущем.", parse_mode=None,
            )
            return True
        # 12y: pending_bid теперь dict {kind, bookmark_id|text}
        if snooze_rid:
            kind_arg, target_arg = "snooze", snooze_rid
        elif isinstance(pending_bid, dict) and pending_bid.get("kind") == "explicit":
            kind_arg, target_arg = "explicit_create", pending_bid.get("text", "")
        else:
            kind_arg = "create"
            target_arg = (
                pending_bid.get("bookmark_id")
                if isinstance(pending_bid, dict) else None
            )
        return await _apply_reminder_action(
            message, api, store,
            kind=kind_arg,
            target_id=target_arg,
            fire_at_iso=entity_dt.isoformat(),
            user_tz_name=user_tz_name,
            confirm_msg_id=reply_to_id,
        )

    # Fallback: nl_date.parse (для клиентов без Bot API 9.5)
    from backend.app.services.nl_date import ParseStatus, parse
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
        if snooze_rid:
            kind, target_id = "snooze", snooze_rid
        elif isinstance(pending_bid, dict) and pending_bid.get("kind") == "explicit":
            kind, target_id = "explicit_create", pending_bid.get("text", "")
        else:
            kind = "create"
            target_id = (
                pending_bid.get("bookmark_id")
                if isinstance(pending_bid, dict) else None
            )
        proposed = _format_fire_at(result.dt, user_tz_name)
        prompt = await message.answer(
            f"Не понял точное время. Поставить на <b>{_safe(proposed)}</b>?\n"
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
            # State уже consumed (атомарный pop) — юзеру предлагаем
            # пройти заново через «💤 Продлить» на оригинальном напоминании.
            await message.answer(
                "Не получилось продлить — нажми «💤 Продлить» ещё раз.",
                parse_mode=None,
            )
            return True

        await message.answer(
            f"💤 Продлено до <b>{_safe(_format_fire_at(result.dt, user_tz_name))}</b>",
            parse_mode="HTML",
        )
        return True

    # 12y: pending_bid теперь dict {kind, bookmark_id|text}
    explicit_text = None
    actual_bid = None
    if isinstance(pending_bid, dict):
        if pending_bid.get("kind") == "explicit":
            explicit_text = pending_bid.get("text", "")
        else:  # "bookmark"
            actual_bid = pending_bid.get("bookmark_id")

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
        # State уже consumed (атомарный pop) — пользователю надо
        # пройти заново через /remind или offer-кнопку.
        await message.answer(
            "Не получилось создать напоминание — попробуй ещё раз через /remind.",
            parse_mode=None,
        )
        return True

    await message.answer(
        f"🔔 Напомню <b>{_safe(_format_fire_at(result.dt, user_tz_name))}</b>",
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
            f"Снова не понял. Поставить на <b>{_safe(proposed)}</b>?\n"
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

    text_payload = _cap_text((message.text or "").strip())

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
    await message.answer(f"{label} <b>{_safe(when)}</b>", parse_mode="HTML")
    return True


@router.message(F.reply_to_message & F.text & ~F.text.startswith("/"))
async def _reply_dispatch(message: Message, api, store):
    """Перехватываем reply ДО tasks/start. Проверяем по приоритету:
    1. /reminders list NL-reply (отмени/перенеси/история по номеру)
    2. Reminder reply (создание/snooze/fallback-confirm)
    3. SkipHandler — событие падает дальше на tasks/start.
    """
    from aiogram.dispatcher.event.bases import SkipHandler

    handled = await handle_reminders_list_reply(message, api, store)
    if handled:
        return

    handled = await handle_reminder_reply(message, api, store)
    if handled:
        return

    raise SkipHandler()
