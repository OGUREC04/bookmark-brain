"""Onboarding tips — подсказки на первые действия пользователя.

Хранение состояния: User.settings JSONB на бэкенде. Используются плоские ключи,
потому что PATCH /users/me/settings делает shallow-merge и вложенный dict
перезаписался бы целиком.

Локальный кэш: TTL 5 минут на flags, чтобы не дёргать /me на каждое сообщение.
Инвалидируется в `mark_shown()` после успешного апдейта.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from aiogram.types import Message

from bot.utils import _delete_after

if TYPE_CHECKING:
    from bot.api_client import BackendClient

logger = logging.getLogger(__name__)

# Ключи флагов в user.settings
KEY_WELCOMED = "onboarding_welcomed"
KEY_FIRST_SAVE = "onboarding_first_save"
KEY_FIRST_TASK_LIST = "onboarding_first_task_list"
KEY_FIRST_VOICE = "onboarding_first_voice"

ALL_KEYS = (KEY_WELCOMED, KEY_FIRST_SAVE, KEY_FIRST_TASK_LIST, KEY_FIRST_VOICE)

TIP_TTL_SECONDS = 60  # сколько живёт ephemeral-подсказка в чате

# telegram_id -> {key: bool, "_expires_at": float}
_flag_cache: dict[int, dict] = {}
_CACHE_TTL = 300  # 5 минут
_CACHE_MAX_ENTRIES = 5000  # защита от роста при нагрузке


def _evict_if_oversized() -> None:
    """Если кэш разросся — выбрасываем самые старые по `_expires_at`.

    Дёшево, потому что вызывается редко (только при превышении лимита).
    """
    if len(_flag_cache) <= _CACHE_MAX_ENTRIES:
        return
    # Удаляем 20% самых протухших — батч-eviction чтобы не делать на каждом save
    sorted_ids = sorted(
        _flag_cache.items(),
        key=lambda kv: kv[1].get("_expires_at", 0),
    )
    drop_n = max(1, len(_flag_cache) // 5)
    for tg_id, _ in sorted_ids[:drop_n]:
        _flag_cache.pop(tg_id, None)


async def _load_flags(api: BackendClient, token: str, telegram_id: int) -> dict:
    """Возвращает флаги онбординга из user.settings (с кэшем)."""
    cached = _flag_cache.get(telegram_id)
    if cached and time.monotonic() < cached["_expires_at"]:
        return cached

    try:
        user = await api.get_me(token)
    except Exception as e:
        logger.debug("onboarding: get_me failed: %s", e)
        # Conservative: считаем что флагов нет, подскажем — лучше показать
        # приветствие лишний раз, чем пропустить
        return {key: False for key in ALL_KEYS} | {"_expires_at": 0}

    settings = user.get("settings") or {}
    # dict хранит mixed-type значения: bool для флагов + float для _expires_at
    flags: dict[str, bool | float] = {key: bool(settings.get(key, False)) for key in ALL_KEYS}
    flags["_expires_at"] = time.monotonic() + _CACHE_TTL
    _flag_cache[telegram_id] = flags
    _evict_if_oversized()
    return flags


def invalidate_cache(telegram_id: int) -> None:
    """Сбросить кэш — после toggle, при logout/re-auth."""
    _flag_cache.pop(telegram_id, None)


async def is_flag_set(
    api: BackendClient, token: str, telegram_id: int, key: str
) -> bool:
    """Проверить установлен ли флаг."""
    flags = await _load_flags(api, token, telegram_id)
    return bool(flags.get(key, False))


async def mark_shown(
    api: BackendClient, token: str, telegram_id: int, key: str
) -> None:
    """Поставить флаг True на бэкенде, обновить локальный кэш."""
    if key not in ALL_KEYS:
        logger.warning("onboarding: unknown key %s", key)
        return

    try:
        await api.update_settings(token, {key: True})
    except Exception as e:
        logger.error("onboarding: failed to mark %s: %s", key, e)
        return

    # Обновляем кэш на месте, не дёргаем /me снова
    cached = _flag_cache.get(telegram_id)
    if cached:
        cached[key] = True
    else:
        _flag_cache[telegram_id] = {
            **{k: False for k in ALL_KEYS},
            key: True,
            "_expires_at": time.monotonic() + _CACHE_TTL,
        }


async def maybe_show_tip(
    api: BackendClient,
    token: str,
    message: Message,
    key: str,
    text: str,
    *,
    telegram_id: int | None = None,
    ephemeral: bool = False,
) -> bool:
    """Показать подсказку если флаг ещё не установлен.

    Возвращает True если подсказка была показана, False если уже была.

    telegram_id: переопределить идентификатор пользователя. Нужно когда `message`
    принадлежит боту (например, callback.message — это reply бота), а нам
    нужно проверить флаг настоящего пользователя. По умолчанию берётся из
    message.from_user.

    ephemeral=False (default): подсказка остаётся в чате — пользователь сам
    решает когда её прочитать/убрать. Установить True если нужно автоудаление
    через TIP_TTL_SECONDS (используется только когда подсказка дублирует
    какую-то частую инфо).

    Race-protection: оптимистично выставляем флаг в локальном кэше до
    `message.answer`, чтобы параллельный второй вызов вернул False сразу.
    Если запись на бэкенд провалится — кэш-флаг останется True, и юзер
    не увидит подсказку до истечения TTL кэша или рестарта процесса.
    Trade-off приемлем: повторный показ подсказки хуже чем её пропуск.
    """
    tg_id = telegram_id
    if tg_id is None:
        if not message.from_user:
            return False
        tg_id = message.from_user.id

    # Race-protection: проверяем кэш СИНХРОННО до любого await.
    # Если флаг уже True в кэше — выходим, не дёргая бэк.
    cached = _flag_cache.get(tg_id)
    if cached and time.monotonic() < cached.get("_expires_at", 0) and cached.get(key):
        return False

    # Slow-path: загружаем с бэка (await — окно гонки).
    if await is_flag_set(api, token, tg_id, key):
        return False

    # После await другой coroutine мог успеть claim'нуть слот — перепроверяем.
    cached = _flag_cache.get(tg_id)
    if cached and cached.get(key):
        return False

    # Атомарный claim в кэше — следующий вызов увидит True и выйдет на fast-path
    if cached:
        cached[key] = True
    else:
        _flag_cache[tg_id] = {
            **{k: False for k in ALL_KEYS},
            key: True,
            "_expires_at": time.monotonic() + _CACHE_TTL,
        }

    try:
        sent = await message.answer(text, parse_mode=None, disable_web_page_preview=True)
    except Exception as e:
        logger.error("onboarding: failed to send tip %s: %s", key, e)
        return False

    # Фиксируем на бэкенде; если упадёт — лог, кэш уже обновлён
    await mark_shown(api, token, tg_id, key)

    if ephemeral:
        asyncio.create_task(_delete_after(sent, delay=TIP_TTL_SECONDS))

    return True


# ─── Тексты подсказок (одно место для редактирования) ───

TIP_FIRST_SAVE = (
    "💡 Совет:\n"
    "• Перешли мне любое сообщение или ссылку — я сохраню и разберу AI-ом\n"
    "• Голосом тоже можно — распознаю и сохраню текст\n"
    "• /list — посмотреть всё сохранённое\n"
    "• /search <запрос> — найти по смыслу, не только по словам"
)

TIP_FIRST_TASK_LIST = (
    "💡 Это список задач — я распознал его автоматически.\n\n"
    "Чтобы редактировать — отвечай (reply) на это сообщение:\n"
    "• «закрой 1, 3» — отметить пункты выполненными\n"
    "• «добавь купить хлеб» — новый пункт\n"
    "• «удали 2» — убрать пункт\n"
    "• «удали список» — убрать всё"
)

TIP_FIRST_VOICE = (
    "💡 Голос распознан и сохранён.\n\n"
    "Что я могу с голосовыми:\n"
    "• Короткое сообщение (<10с) с поиском в начале — выполню как /search\n"
    "• «todo: купить ...» — создам задачу/список\n"
    "• Длинные (>30с) — добавлю таймкоды\n"
    "• Все голосовые получают тег #voice"
)
