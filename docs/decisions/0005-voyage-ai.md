# ADR 0005 — Voyage AI как embeddings-провайдер

**Статус:** принято
**Дата:** 2026-03
**Связано с:** `backend/app/services/embeddings.py`, `Bookmark.embedding vector(1024)`

## Context

Для семантического поиска нужны embeddings. Изначальный план — использовать GigaChat embeddings (один провайдер на всё, меньше vendor sprawl). На практике GigaChat embeddings возвращают **HTTP 402 на бесплатном тарифе** — embeddings доступны только на платном. Платить отдельно за embeddings + классификацию — раздувает costs на этапе MVP без выручки.

Кандидаты:
- **OpenAI text-embedding-3-small** — заблокирован из РФ.
- **Voyage AI** — доступен из РФ, бесплатный тариф щедрый, качество для семантики высокое.
- **Cohere Embed** — заблокирован из РФ.
- **Self-hosted (sentence-transformers, e5)** — нужен GPU или медленный CPU inference.
- **GigaChat embeddings (платный)** — дорого на MVP.

## Decision

Использовать **Voyage AI** (`voyage-3`, размерность 1024) как primary `EMBEDDING_PROVIDER`. GigaChat embeddings оставить как fallback (через `EMBEDDING_PROVIDER=gigachat`) — на случай если Voyage заблокируют или счёт истечёт.

Размерность 1024 фиксирована в схеме — `bookmarks.embedding vector(1024)`. Миграция на другую размерность потребует ALTER + reindex (см. ADR 0004).

## Consequences

**Плюсы:**
- **Бесплатный тариф** — 50M токенов/мес, нам хватит надолго.
- **Доступен из РФ** без VPN.
- **Качество** — voyage-3 один из топов на MTEB, особенно на русских/мультиязычных задачах.
- **Простой API** — REST с Bearer token, без OAuth-плясок как у GigaChat.

**Минусы:**
- **Vendor lock-in на размерности** — все embeddings в БД сделаны voyage-3 1024d. Смена провайдера = массовый reindex.
- **Зависимость от стабильности Voyage AI** — стартап, не Big Tech. На случай прекращения сервиса — есть GigaChat fallback и план миграции (Phase 4.5).
- **Мультиязычность** — voyage-3 хорош, но для чисто русского контента можно проверить специализированные модели (e5-multilingual). Пока не приоритет.
- **Английский биллинг** — нужна карта, проходящая в Voyage. Беречь ключ.
