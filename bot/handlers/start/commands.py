"""Команды /start и /help."""
import logging

from aiogram import Router, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from bot import onboarding
from bot.common.auth import ensure_user
from bot.config import get_settings

_settings = get_settings()
logger = logging.getLogger(__name__)

router = Router()


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
    "• Reply на список: «закрой 1, 3», «добавь ...», «удали 2», «удали список»\n"
    "• /lists — только списки задач (отдельно от закладок)\n"
    "• /unpin — открепить все списки (сами списки остаются)\n\n"
    "🔔 Напоминания:\n"
    "• /remind <текст> <когда> — создать напоминание (без аргументов — справка)\n"
    "• /reminders — активные + reply «отмени 1» / «перенеси 2 на ...»\n"
    "• /reminders история — последние выполненные/отменённые\n"
    "• «надо/нужно/срочно/не забыть ...» — спрошу: напоминание или заметка\n\n"
    "⚙️ Режимы:\n"
    "• /silent — переключить тихий режим (реакции 👀→👍)\n"
    "• /silent on / /silent off — явное переключение\n\n"
    "🗑 Уборка:\n"
    "• /clean — удалить мои сообщения за последние 48ч (списки задач сохраняются)\n"
    "• /clearlists — архивировать все списки задач (с подтверждением, обратимо)\n"
    "• /clearreminders — отменить все активные напоминания (с подтверждением)"
)


@router.message(CommandStart())
async def cmd_start(message: types.Message, api):
    token = await ensure_user(message, api)
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
    token = await ensure_user(message, api)
    if not token:
        return
    await message.answer(_HELP_TEXT, parse_mode=None, disable_web_page_preview=True)
