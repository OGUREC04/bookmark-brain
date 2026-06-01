"""OG/meta извлечение карточки-предпросмотра (тикет z9q).

Тестирует stdlib-парсер `_extract_og_meta` (не требует trafilatura/сети).
Покрывает auth-wall (нет текста, но есть OG), приоритеты источников,
JSON-LD, и фильтр мусорных описаний.
"""
from __future__ import annotations

from app.services.article_fetcher import _extract_og_meta, fetch_article


def test_open_graph_extracted():
    html = (
        "<html><head>"
        '<meta property="og:title" content="Заголовок поста">'
        '<meta property="og:description" content="Краткое описание для предпросмотра.">'
        "<title>linkedin.com</title>"
        "</head><body><p>Login required</p></body></html>"
    )
    title, desc = _extract_og_meta(html)
    assert title == "Заголовок поста"
    assert desc == "Краткое описание для предпросмотра."


def test_og_preferred_over_title_tag():
    html = (
        "<html><head>"
        '<meta property="og:title" content="Настоящий заголовок">'
        "<title>example.com</title>"
        "</head></html>"
    )
    title, _ = _extract_og_meta(html)
    assert title == "Настоящий заголовок"


def test_twitter_fallback_when_no_og():
    html = (
        "<html><head>"
        '<meta name="twitter:title" content="Twitter заголовок">'
        '<meta name="twitter:description" content="Twitter описание">'
        "</head></html>"
    )
    title, desc = _extract_og_meta(html)
    assert title == "Twitter заголовок"
    assert desc == "Twitter описание"


def test_standard_meta_description_fallback():
    html = (
        "<html><head>"
        "<title>Просто заголовок</title>"
        '<meta name="description" content="Стандартное мета-описание">'
        "</head></html>"
    )
    title, desc = _extract_og_meta(html)
    assert title == "Просто заголовок"
    assert desc == "Стандартное мета-описание"


def test_attribute_order_independent():
    # content раньше property — атрибуты в обратном порядке
    html = (
        "<html><head>"
        '<meta content="Описание сначала" property="og:description">'
        "</head></html>"
    )
    _, desc = _extract_og_meta(html)
    assert desc == "Описание сначала"


def test_html_entities_unescaped():
    html = (
        "<html><head>"
        '<meta property="og:title" content="Мама &amp; папа &lt;3">'
        "</head></html>"
    )
    title, _ = _extract_og_meta(html)
    assert title == "Мама & папа <3"


def test_json_ld_fallback():
    html = (
        "<html><head>"
        '<script type="application/ld+json">'
        '{"@type":"Article","headline":"JSON-LD заголовок","description":"JSON-LD описание"}'
        "</script></head></html>"
    )
    title, desc = _extract_og_meta(html)
    assert title == "JSON-LD заголовок"
    assert desc == "JSON-LD описание"


def test_garbage_cookie_description_dropped():
    html = (
        "<html><head>"
        '<meta property="og:title" content="Сайт">'
        '<meta property="og:description" content="Please enable JavaScript">'
        "</head></html>"
    )
    title, desc = _extract_og_meta(html)
    assert title == "Сайт"
    assert desc is None  # мусорное описание отброшено


def test_empty_html_returns_none():
    title, desc = _extract_og_meta("<html><head></head><body></body></html>")
    assert title is None
    assert desc is None


def test_malformed_html_does_not_crash():
    title, desc = _extract_og_meta('<meta property="og:title" content="X"')
    # не падает; что-то могло распарситься или нет — главное без исключения
    assert title in ("X", None)


async def test_fetch_article_blocks_private_url(monkeypatch):
    """SSRF-guard подключён в fetch_article: приватный URL → пустой результат,
    и httpx НЕ вызывается (запрос блокируется до сети)."""
    def _boom(*a, **k):
        raise AssertionError("httpx.stream не должен вызываться для приватного URL")
    monkeypatch.setattr(
        "app.services.article_fetcher.httpx.AsyncClient.stream", _boom
    )
    result = await fetch_article("http://169.254.169.254/latest/meta-data/")
    assert result.title is None
    assert result.text is None
    assert result.summary is None
