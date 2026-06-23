import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ParseMode
from aiogram.methods import (
    CopyMessage,
    ForwardMessage,
    SendAnimation,
    SendAudio,
    SendDocument,
    SendMediaGroup,
    SendMessage,
    SendPhoto,
    SendVideo,
    SendVoice,
)
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from bot.api_client import BackendClient
from bot.config import get_settings
from bot.handlers import (
    bookmark_view,
    clean,
    clear,
    documents,
    media,
    random,
    reminder_choice,
    search,
    start,
    tasks,
)
from bot.handlers import (
    reminders as reminders_handler,
)
from bot.handlers import (
    settings as settings_handler,
)
from bot.handlers import (
    timezone as timezone_handler,
)
from bot.state_store import StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# Методы, возвращающие Message — их мы трекаем для /clean
_TRACKED_METHODS = (
    SendMessage, SendPhoto, SendDocument, SendAudio, SendVoice,
    SendVideo, SendAnimation, SendMediaGroup, CopyMessage, ForwardMessage,
)


class TrackingMiddleware(BaseRequestMiddleware):
    """Запоминаем каждое отправленное ботом сообщение для последующего /clean."""

    def __init__(self, store):
        self.store = store

    async def __call__(self, make_request, bot, method):
        result = await make_request(bot, method)
        try:
            if isinstance(method, _TRACKED_METHODS) and result is not None and hasattr(result, "chat"):
                await self.store.track_bot_message(result.chat.id, result.message_id)
                await self.store.bump_last_seen(result.chat.id, result.message_id)
        except Exception as e:
            logger.debug(f"TrackingMiddleware failed: {e}")
        return result


async def main():
    settings = get_settings()

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    api = BackendClient(
        base_url=settings.BACKEND_URL,
        bot_secret=settings.BOT_SECRET,
    )
    store = StateStore(settings.REDIS_URL)

    # Порядок роутеров важен:
    # 1. reminders.strong_router САМЫЙ ПЕРВЫЙ (T13 v2.1) — ловит strong-intent
    #    сообщения ДО того как они попадут в start.handle_text и отправятся
    #    в AI. Если intent не сильный → SkipHandler → событие падает дальше.
    # 2. reminders.router — callbacks rsk:/rsn:/rdone:/rsnz:/rstrong_*,
    #    /remind команда, /reminders команда, reply-handler.
    # 3. tasks — reply на task_list ДО catch-all в start.
    dp.include_router(reminders_handler.strong_router)
    dp.include_router(reminders_handler.router)
    # Phase 2.6 T4: 3-button «📋/🔔/✕» callbacks (rch_*) — отдельный
    # router т.к. не конфликтует с reminders_handler по prefix'ам.
    dp.include_router(reminder_choice.router)
    dp.include_router(tasks.router)
    dp.include_router(settings_handler.router)
    dp.include_router(timezone_handler.router)
    dp.include_router(clean.router)
    dp.include_router(clear.router)   # /clearlists, /clearreminders — до catch-all
    dp.include_router(media.router)   # voice, video_note, audio — до catch-all
    dp.include_router(documents.router)  # PDF/DOCX/TXT/MD — до catch-all в start
    dp.include_router(bookmark_view.router)  # view: callback — раньше start
    dp.include_router(start.router)
    dp.include_router(search.router)
    dp.include_router(random.router)

    # Прокидывание api + store во все хендлеры
    @dp.update.outer_middleware()
    async def inject_deps(handler, event, data):
        data["api"] = api
        data["store"] = store
        # Обновляем last_seen на любой incoming Message (юзерский или наш edited).
        # Это нужно rerender_at_bottom чтобы не двигать список если он и так
        # последний в чате.
        try:
            msg = getattr(event, "message", None) or getattr(event, "edited_message", None)
            if msg is not None and msg.chat is not None:
                await store.bump_last_seen(msg.chat.id, msg.message_id)
        except Exception as e:
            logger.debug(f"bump_last_seen failed: {e}")
        return await handler(event, data)

    # Session middleware — трекаем все исходящие сообщения для /clean
    bot.session.middleware(TrackingMiddleware(store))

    # Slash-команды в UI Telegram
    try:
        await bot.set_my_commands([
            BotCommand(command="todo", description="Список задач: /todo пункт1, пункт2"),
            BotCommand(command="remind", description="Создать напоминание: /remind текст время"),
            BotCommand(command="repeat", description="Регулярное: /repeat текст каждый день в 10:00"),
            BotCommand(command="reminders", description="Активные напоминания + история"),
            BotCommand(command="list", description="Все закладки"),
            BotCommand(command="lists", description="Только списки задач"),
            BotCommand(command="search", description="Поиск: /search запрос"),
            BotCommand(command="random", description="Случайная закладка"),
            BotCommand(command="unpin", description="Открепить все списки"),
            BotCommand(command="stats", description="Статистика"),
            BotCommand(command="silent", description="Тихий/обычный режим"),
            BotCommand(command="help", description="Справка"),
            # /clean и /reprocess работают, но скрыты из меню (доступны через /help)
        ])
        logger.info("Bot commands registered")
    except Exception as e:
        logger.error(f"Failed to set commands: {e}")

    if settings.MINI_APP_URL:
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="📚 Открыть",
                    web_app=WebAppInfo(url=settings.MINI_APP_URL),
                )
            )
            logger.info(f"Menu button set to Mini App: {settings.MINI_APP_URL}")
        except Exception as e:
            logger.error(f"Failed to set menu button: {e}")

    logger.info("Bot starting in polling mode...")

    try:
        await dp.start_polling(bot)
    finally:
        await api.close()
        await store.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
