import logging

from aiogram import Router, types
from aiogram.filters import Command

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("random"))
async def cmd_random(message: types.Message, api):
    from bot.common.auth import ensure_user

    token = await ensure_user(message, api)
    if not token:
        return

    try:
        bookmark = await api.get_random_bookmark(token)
    except Exception as e:
        logger.error(f"Random failed: {e}")
        await message.answer("Ошибка. Попробуй позже.")
        return

    if not bookmark:
        await message.answer("У тебя пока нет сохранённых закладок.")
        return

    title = bookmark.get("title") or "Без названия"
    summary = bookmark.get("summary") or bookmark["raw_text"][:150]
    tags = bookmark.get("tags", [])
    url = bookmark.get("url")
    category = bookmark.get("category") or "other"

    lines = [f"<b>{title}</b>", f"Категория: {category}", "", summary]

    if tags:
        tag_str = " ".join(f"#{t['name']}" for t in tags[:5])
        lines.append(f"\n<i>{tag_str}</i>")

    if url:
        lines.append(f'\n<a href="{url}">Открыть ссылку</a>')

    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("stats"))
async def cmd_stats(message: types.Message, api):
    from bot.common.auth import ensure_user

    token = await ensure_user(message, api)
    if not token:
        return

    try:
        bookmarks_data = await api.get_bookmarks(token, page=1, per_page=1)
        tags = await api.get_tags(token)
    except Exception as e:
        logger.error(f"Stats failed: {e}")
        await message.answer("Ошибка. Попробуй позже.")
        return

    total = bookmarks_data.get("total", 0)

    lines = [
        "<b>Статистика BookmarkBrain</b>",
        f"\nВсего закладок: {total}",
    ]

    if tags:
        lines.append("\nТоп теги:")
        for tag in tags[:10]:
            lines.append(f"  #{tag['name']} — {tag['bookmarks_count']}")

    if total == 0:
        lines.append("\nПерешли мне сообщение чтобы начать!")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("reprocess"))
async def cmd_reprocess(message: types.Message, api):
    """Переобработать старые закладки новым AI-пайплайном (Phase 1)."""
    from bot.common.auth import ensure_user

    token = await ensure_user(message, api)
    if not token:
        return

    # /reprocess all → переобработать ВСЕ (принудительно)
    args = (message.text or "").split()
    force = len(args) > 1 and args[1].lower() == "all"

    status_msg = await message.answer("Ставлю в очередь...")

    try:
        result = await api.reprocess_all(token, only_missing_phase1=not force)
    except Exception as e:
        logger.error(f"Reprocess all failed: {e}")
        await status_msg.edit_text("Ошибка. Попробуй позже.")
        return

    enqueued = result.get("enqueued", 0)
    if enqueued == 0:
        await status_msg.edit_text(
            "Нечего переобрабатывать — все закладки уже прошли новый AI-пайплайн.\n"
            "Чтобы пересобрать всё принудительно: /reprocess all"
        )
        return

    await status_msg.edit_text(
        f"Поставлено в очередь: {enqueued} закладок.\n"
        f"Воркер обработает их по одной — следи за уведомлениями."
    )
