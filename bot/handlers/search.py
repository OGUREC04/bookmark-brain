import logging

from aiogram import Router, types
from aiogram.filters import Command

logger = logging.getLogger(__name__)

router = Router()


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


@router.message(Command("search"))
async def cmd_search(message: types.Message, api):
    from bot.handlers.start import _ensure_user

    token = await _ensure_user(message, api)
    if not token:
        return

    # Извлекаем запрос после /search
    query = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""

    if not query:
        await message.answer("Напиши запрос после /search\nПример: /search статьи про дизайн")
        return

    try:
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

    await message.answer("\n\n".join(parts), parse_mode="HTML", disable_web_page_preview=True)
