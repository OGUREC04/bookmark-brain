# ADR 0004 — pgvector вместо отдельной vector DB (FAISS / Qdrant / Pinecone)

**Статус:** принято
**Дата:** 2026-03
**Связано с:** `backend/app/models.py` (`Bookmark.embedding`), миграции

## Context

Для семантического поиска нужны embeddings + ANN-индекс. Кандидаты:

- **pgvector** — расширение PostgreSQL.
- **FAISS** — библиотека, нужно self-host + отдельный сторадж.
- **Qdrant / Weaviate / Milvus** — отдельный сервис.
- **Pinecone** — managed, платный, не из РФ.

Объём — десятки тысяч заметок на пользователя в обозримой перспективе, не миллионы.

## Decision

Использовать **pgvector** (расширение PostgreSQL) с HNSW-индексом (`vector_cosine_ops`, m=16, ef_construction=64).

## Consequences

**Плюсы:**
- **Одна БД на всё** — bookmarks, tags, users и embeddings в одном PostgreSQL. Транзакции консистентны (создание закладки и embedding — атомарно).
- **Один контейнер в docker-compose** — деплой проще, бэкап один (pg_dump покрывает всё).
- **Гибридный поиск из коробки** — semantic (embedding cosine) + full-text (TSVECTOR) в одном SQL-запросе с `UNION` или `score = α·sem + β·fts`.
- **JOIN на metadata** без cross-system запросов — фильтр «embedding similar AND user_id=X AND is_archived=false» — обычный WHERE.
- **Доказанная экосистема** — Supabase, Timescale, AWS RDS — все поддерживают pgvector.

**Минусы:**
- **Производительность на миллиардах векторов** хуже чем у Qdrant / специализированных решений. Для нашего масштаба (десятки тысяч на юзера) — не проблема.
- **Нет встроенных hybrid-search abstractions** как в Weaviate — пишем SQL руками.
- **HNSW параметры** требуют тюнинга при росте (recall vs latency).
- **При миграции эмбеддинг-провайдера с разной размерностью** — нужно reindex (новая колонка `vector(N)` или ALTER). Зафиксировано в TROUBLESHOOTING.
