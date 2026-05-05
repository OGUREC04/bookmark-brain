"""Извлечение полного текста статьи по URL.

Используется trafilatura — state-of-the-art readability-экстрактор:
- очищает навигацию, футеры, рекламу, комментарии
- возвращает title + основной текст + lang
- лучше чем <title>+raw_text для качественной AI-классификации

Вызывается из bookmark_processor.py на шаге 0 (до классификации).
Если fetch не удался — fallback на raw_text (это как сейчас).
"""
import asyncio
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Максимальный размер статьи в символах — чтобы не раздувать контекст LLM.
# 20k ~ 5-6k токенов, влезает в любой тариф.
MAX_ARTICLE_CHARS = 20_000

# Таймаут на загрузку страницы
FETCH_TIMEOUT = 15.0

USER_AGENT = (
    "Mozilla/5.0 (compatible; BookmarkBrain/1.0; "
    "+https://github.com/bookmarkbrain)"
)


@dataclass
class ArticleData:
    title: str | None
    text: str | None  # Очищенный основной текст. None если не удалось.
    lang: str | None  # Код языка, определённый trafilatura. None если не удалось.


async def fetch_article(url: str) -> ArticleData:
    """Скачивает страницу и извлекает title+text через trafilatura.

    Полностью async: httpx для сети, trafilatura в thread executor
    (trafilatura — sync-only библиотека).

    Никогда не бросает — любая ошибка = ArticleData(None, None, None).
    """
    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.debug(f"fetch_article {url}: HTTP {resp.status_code}")
                return ArticleData(None, None, None)
            html = resp.text
    except httpx.HTTPError as e:
        logger.debug(f"fetch_article {url}: network error: {e}")
        return ArticleData(None, None, None)

    # trafilatura парсит sync — гоним в thread pool чтобы не блокировать event loop
    try:
        return await asyncio.to_thread(_extract, html, url)
    except Exception as e:
        logger.warning(f"fetch_article {url}: parse error: {e}")
        return ArticleData(None, None, None)


def _extract(html: str, url: str) -> ArticleData:
    """Sync-часть, запускается в thread executor."""
    import trafilatura
    from trafilatura.settings import use_config

    # Дефолтный конфиг + включаем извлечение метаданных
    config = use_config()
    # Trafilatura по умолчанию ругается на некоторые кодировки — подавляем
    config.set("DEFAULT", "EXTRACTION_TIMEOUT", "10")

    # with_metadata=True чтобы получить title/lang структурировано
    # include_comments=False — комменты не нужны
    # favor_precision=True — лучше выкинуть сомнительное, чем добавить мусор
    extracted = trafilatura.extract(
        html,
        url=url,
        config=config,
        with_metadata=True,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
        output_format="json",
    )
    if not extracted:
        return ArticleData(None, None, None)

    import json
    data = json.loads(extracted)

    title = data.get("title")
    if title:
        title = title.strip()[:500]

    text = data.get("text") or data.get("raw_text")
    if text:
        text = text.strip()[:MAX_ARTICLE_CHARS]

    lang = data.get("language")
    if lang:
        lang = lang.strip()[:10]

    return ArticleData(title=title or None, text=text or None, lang=lang or None)
