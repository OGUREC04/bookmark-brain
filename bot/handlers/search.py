import logging

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.utils.chat_action import ChatActionSender

from bot.config import get_settings

logger = logging.getLogger(__name__)

router = Router()

_settings = get_settings()


def _format_result(item: dict, score: float) -> str:
    """Форматирует один результат поиска."""
    bookmark = item["bookmark"]
    title = bookmark.get("title") or "Без названия"
    summary = bookmark.get("summary") or bookmark["raw_text"][:100]
    tags = bookmark.get("tags", [])
    url = bookmark.get("url")

    lines = [f"<b>{title}</b>"]
    lines.append(summary)

    if tags:
        tag_str = " ".join(f"#{t['name']}" for t in tags[:4])
        lines.append(f"<i>{tag_str}</i>")

    if url:
        lines.append(f'<a href="{url}">Открыть</a>')

    lines.append(f"Релевантность: {score:.0%}")
    return "\n".join(lines)


def _format_result_rich(item: dict, score: float) -> str:
    """Один результат в rich-markdown: ## title, summary, строка тегов/релевантности/ссылки."""
    bookmark = item["bookmark"]
    title = bookmark.get("title") or "Без названия"
    summary = bookmark.get("summary") or bookmark["raw_text"][:100]
    tags = bookmark.get("tags", [])
    url = bookmark.get("url")

    lines = [f"## {title}", summary]

    meta = []
    if tags:
        meta.append(" ".join(f"#{t['name']}" for t in tags[:4]))
    meta.append(f"релевантность **{score:.0%}**")
    if url:
        meta.append(f"[Открыть]({url})")
    lines.append(" · ".join(meta))

    return "\n".join(lines)


def _build_rich_markdown(query: str, results: list, total: int) -> str:
    """Собирает rich-markdown для всех результатов поиска."""
    blocks = [f"# 🔍 Поиск: «{query}»", f"_Найдено {total}_"]
    for item in results:
        blocks.append(_format_result_rich(item, item["score"]))
    if total > 5:
        blocks.append(f"_…и ещё {total - 5}. Уточни запрос для точных результатов._")
    return "\n\n".join(blocks)


@router.message(Command("search"))
async def cmd_search(message: types.Message, api):
    from bot.common.auth import ensure_user

    token = await ensure_user(message, api)
    if not token:
        return

    # Извлекаем запрос после /search
    query = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""

    if not query:
        await message.answer("Напиши запрос после /search\nПример: /search статьи про дизайн")
        return

    try:
        # «печатает…» пока ищем по базе.
        async with ChatActionSender(bot=message.bot, chat_id=message.chat.id, action="typing"):
            data = await api.search_bookmarks(token, query, limit=5)
    except Exception as e:
        logger.error(f"Search failed: {e}")
        await message.answer("Ошибка поиска. Попробуй позже.")
        return

    results = data.get("results", [])
    total = data.get("total", 0)

    if not results:
        await message.answer(f'Ничего не найдено по запросу "{query}"')
        return

    parts = [f'Результаты по запросу "<b>{query}</b>" ({total} найдено):\n']
    for i, item in enumerate(results, 1):
        parts.append(f"{i}. {_format_result(item, item['score'])}")

    if total > 5:
        parts.append(f"\n...и ещё {total - 5}. Уточни запрос для точных результатов.")

    if _settings.RICH_MESSAGES:
        try:
            from aiogram.types import InputRichMessage

            markdown = _build_rich_markdown(query, results, total)
            await message.bot.send_rich_message(
                chat_id=message.chat.id,
                rich_message=InputRichMessage(markdown=markdown),
            )
            return
        except Exception as e:
            # Rich-режим bleeding-edge — при любой ошибке падаем на текущий HTML.
            logger.warning(f"Rich search message failed, falling back to HTML: {e}")

    await message.answer("\n\n".join(parts), parse_mode="HTML", disable_web_page_preview=True)
