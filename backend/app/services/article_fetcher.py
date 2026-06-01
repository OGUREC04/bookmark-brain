"""Извлечение контекста по URL: полный текст статьи + OG/meta карточка.

Два слоя:
1. **Полный текст** — trafilatura (readability): чистый title+text+lang. Лучший
   вход для AI-классификации. Работает на обычных публичных статьях.
2. **OG/meta fallback** (тикет z9q) — когда полного текста нет (auth-wall типа
   LinkedIn, JS-страницы), достаём карточку-предпросмотр (og:title/og:description)
   из `<head>` стандартной библиотекой. Она есть даже за логином.

Все сетевые запросы проходят SSRF-проверку (`link_security`) — и литеральный
URL, и каждый редирект-хоп. Размер скачивания ограничен. Контракт: никогда не
бросает — любая ошибка = пустой ArticleData.

Вызывается из bookmark_processor.py на шаге 0 (до классификации).
"""
from __future__ import annotations

import asyncio
import html as _htmlmod
import json
import logging
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from app.services.link_security import UnsafeUrlError, assert_public_url

logger = logging.getLogger(__name__)

# Максимальный размер статьи в символах — чтобы не раздувать контекст LLM.
MAX_ARTICLE_CHARS = 20_000

# Лимит скачивания страницы (защита от гигантских ответов). ~3 МБ хватает на
# любой нормальный <head>+<body>.
MAX_DOWNLOAD_BYTES = 3_000_000

# Сколько редиректов проходим (t.co / bit.ly → финальный URL). Каждый хоп
# проверяется SSRF-guard'ом.
MAX_REDIRECTS = 5

FETCH_TIMEOUT = 15.0

USER_AGENT = (
    "Mozilla/5.0 (compatible; BookmarkBrain/1.0; "
    "+https://github.com/bookmarkbrain)"
)


@dataclass
class ArticleData:
    title: str | None
    text: str | None       # Очищенный основной текст (trafilatura). None если нет.
    lang: str | None       # Код языка. None если не определён.
    summary: str | None = None  # og:description — карточка-предпросмотр (z9q).


# ──────────────────────────── Сеть (SSRF-safe) ────────────────────────────


def _safe_log_url(url: str) -> str:
    """URL без userinfo — чтобы `https://user:pass@host` не утёк в логи."""
    try:
        p = urlparse(url)
        if p.username or p.password:
            netloc = p.hostname or ""
            if p.port:
                netloc = f"{netloc}:{p.port}"
            p = p._replace(netloc=netloc)
        return urlunparse(p)
    except Exception:  # noqa: BLE001
        return "<url>"


async def _fetch_html_safe(url: str) -> str | None:
    """Скачивает HTML с SSRF-защитой, ручными редиректами и лимитом размера.

    Возвращает строку HTML или None (заблокировано / не HTML / ошибка сети).
    """
    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,  # редиректы — вручную, чтобы проверять каждый хоп
        ) as client:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                assert_public_url(current)  # SSRF-guard на КАЖДОМ хопе
                async with client.stream("GET", current) as resp:
                    if resp.is_redirect:
                        loc = resp.headers.get("location")
                        if not loc:
                            return None
                        current = urljoin(str(resp.url), loc)
                        continue

                    if resp.status_code != 200:
                        logger.debug("fetch %s: HTTP %s", _safe_log_url(current), resp.status_code)
                        return None

                    ctype = resp.headers.get("content-type", "").lower()
                    if ctype and "html" not in ctype and "xml" not in ctype:
                        # не-HTML (PDF / картинка / видео) — нечего парсить
                        logger.debug("fetch %s: non-HTML content-type %r", _safe_log_url(current), ctype)
                        return None

                    total = 0
                    chunks: list[bytes] = []
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_DOWNLOAD_BYTES:
                            break  # обрезаем — достаточно для <head>/og
                        chunks.append(chunk)
                    raw = b"".join(chunks)

                    enc = resp.charset_encoding or "utf-8"
                    try:
                        return raw.decode(enc, errors="replace")
                    except (LookupError, TypeError):
                        return raw.decode("utf-8", errors="replace")
            logger.debug("fetch %s: too many redirects", _safe_log_url(url))
            return None
    except UnsafeUrlError as e:
        logger.warning("fetch blocked by SSRF guard: %s — %s", _safe_log_url(url), e)
        return None
    except httpx.HTTPError as e:
        logger.debug("fetch %s: network error: %s", _safe_log_url(url), e)
        return None
    except Exception as e:  # noqa: BLE001 — контракт: никогда не бросаем
        logger.warning("fetch %s: unexpected error: %s", _safe_log_url(url), e)
        return None


async def fetch_article(url: str) -> ArticleData:
    """Контекст по URL: полный текст (trafilatura) + OG-карточка (fallback).

    Никогда не бросает — любая ошибка = ArticleData(None, None, None, None).
    """
    html = await _fetch_html_safe(url)
    if not html:
        return ArticleData(None, None, None, None)

    # Полный текст — best-effort (trafilatura sync → thread; может отсутствовать
    # в окружении, тогда просто остаётся OG-карточка).
    title = text = lang = None
    try:
        title, text, lang = await asyncio.to_thread(_extract_fulltext, html, url)
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_article %s: fulltext extract failed: %s", _safe_log_url(url), e)

    # OG/meta карточка — стандартная библиотека, всегда доступна.
    og_title, og_desc = _extract_og_meta(html)

    return ArticleData(
        title=title or og_title,
        text=text,
        lang=lang,
        summary=og_desc,
    )


# ──────────────────────── Полный текст (trafilatura) ───────────────────────


def _extract_fulltext(html: str, url: str) -> tuple[str | None, str | None, str | None]:
    """Sync-часть для thread executor: (title, text, lang) через trafilatura."""
    import trafilatura
    from trafilatura.settings import use_config

    config = use_config()
    config.set("DEFAULT", "EXTRACTION_TIMEOUT", "10")

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
        return None, None, None

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

    return title or None, text or None, lang or None


# ─────────────────────── OG/meta карточка (stdlib) ─────────────────────────


class _MetaParser(HTMLParser):
    """Достаёт og:/twitter:/standard meta + <title> + JSON-LD из HTML.

    Стандартная библиотека — без зависимостей, толерантна к кривой разметке.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self._in_title = False
        self.title_text: str | None = None
        self._in_ldjson = False
        self.ldjson_blobs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            d = {k.lower(): (v or "") for k, v in attrs}
            key = (d.get("property") or d.get("name") or "").lower()
            content = d.get("content")
            # Лимит против spam-страниц с тысячами <meta> (нам нужны единицы).
            if key and content and key not in self.meta and len(self.meta) < 200:
                self.meta[key] = content
        elif tag == "title":
            self._in_title = True
        elif tag == "script":
            d = {k.lower(): (v or "") for k, v in attrs}
            if "ld+json" in d.get("type", "").lower():
                self._in_ldjson = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_ldjson = False

    def handle_data(self, data: str) -> None:
        if self._in_title and self.title_text is None:
            t = data.strip()
            if t:
                self.title_text = t
        elif self._in_ldjson:
            self.ldjson_blobs.append(data)


def _clean(value: str | None, *, limit: int) -> str | None:
    if not value:
        return None
    cleaned = _htmlmod.unescape(value).strip()
    return cleaned[:limit] if cleaned else None


def _is_garbage_description(desc: str) -> bool:
    """Эвристика edge-кейса: cookie-баннер / «включите JS» вместо описания."""
    low = desc.lower()
    markers = (
        "enable javascript", "включите javascript", "enable js",
        "accept cookies", "we use cookies", "используем cookie",
        "are you a robot", "verify you are human",
    )
    return len(desc) < 80 and any(m in low for m in markers)


def _ldjson_description(blobs: list[str]) -> tuple[str | None, str | None]:
    """Из JSON-LD (Article и т.п.) достаём (headline, description)."""
    for blob in blobs:
        try:
            data = json.loads(blob)
        except (ValueError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            headline = obj.get("headline") or obj.get("name")
            desc = obj.get("description")
            if headline or desc:
                return (
                    headline if isinstance(headline, str) else None,
                    desc if isinstance(desc, str) else None,
                )
    return None, None


def _extract_og_meta(html: str) -> tuple[str | None, str | None]:
    """(title, description) из OG → Twitter → standard → JSON-LD → <title>."""
    parser = _MetaParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 — кривая разметка не должна ронять
        pass
    m = parser.meta

    ld_title, ld_desc = _ldjson_description(parser.ldjson_blobs)

    title = (
        _clean(m.get("og:title"), limit=500)
        or _clean(m.get("twitter:title"), limit=500)
        or _clean(ld_title, limit=500)
        or _clean(parser.title_text, limit=500)
    )

    desc = (
        _clean(m.get("og:description"), limit=1000)
        or _clean(m.get("twitter:description"), limit=1000)
        or _clean(m.get("description"), limit=1000)
        or _clean(ld_desc, limit=1000)
    )
    if desc and _is_garbage_description(desc):
        desc = None

    return title, desc
