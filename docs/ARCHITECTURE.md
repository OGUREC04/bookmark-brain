# Архитектура BookmarkBrain

## Стек

### Backend
- **FastAPI** — основной API-сервер
- **PostgreSQL + pgvector** — БД + семантический поиск
- **Redis + arq** — async очередь задач для AI-обработки
- **aiogram 3.x** — Telegram Bot

### AI (мульти-провайдер)
- **GigaChat** — классификация, теги, саммари (текущий провайдер)
- **Claude Sonnet** — альтернативный провайдер (переключается через .env)
- **Voyage AI** — embeddings (voyage-3, 1024 dims)

### Frontend (в разработке)
- **Expo (React Native)** — iOS app
- **Expo Web** — Telegram Mini App (тот же codebase)

### Инфраструктура
- **Railway** — деплой (FastAPI + Worker + Bot)
- **Docker Compose** — локальная разработка (PostgreSQL + Redis)

---

## Структура проекта

```
/
├── CLAUDE.md
├── .env / .env.example
├── docker-compose.yml
├── /backend
│   ├── main.py              — FastAPI app, CORS, routers, /health
│   ├── run_worker.py         — arq worker launcher (Python 3.14+ compatible)
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── /app
│   │   ├── config.py         — pydantic-settings, env из корневого .env
│   │   ├── database.py       — AsyncEngine, async_sessionmaker, get_session()
│   │   ├── models.py         — User, Bookmark, Tag, BookmarkTag (SQLAlchemy)
│   │   ├── schemas.py        — 14 Pydantic v2 schemas
│   │   ├── auth.py           — JWT, Telegram initData HMAC, bot secret
│   │   ├── worker.py         — arq WorkerSettings, process_bookmark_task
│   │   ├── /api
│   │   │   ├── users.py      — auth/telegram, auth/bot, /users/me
│   │   │   ├── bookmarks.py  — CRUD + reprocess
│   │   │   └── search.py     — hybrid search + tags
│   │   └── /services
│   │       ├── ai_classifier.py     — BaseClassifier → GigaChat / Claude
│   │       ├── embeddings.py        — BaseEmbedding → Voyage / GigaChat
│   │       ├── search.py            — SearchService (semantic + full-text)
│   │       └── bookmark_processor.py — AI pipeline: classify → embed → tag
│   └── /migrations
│       └── /versions/001_initial.py
├── /bot
│   ├── main.py              — aiogram Bot + Dispatcher, polling mode
│   ├── config.py            — Bot Settings
│   ├── api_client.py        — BackendClient (httpx → FastAPI)
│   ├── state_store.py        — Redis state (task_list_msg, bot_msgs)
│   └── /handlers
│       ├── start.py         — /start, forwarded messages, plain text → bookmark
│       ├── search.py        — /search <query>
│       └── random.py        — /random, /stats
└── /frontend (ещё не реализован)
    └── /app
```

---

## Data Model

### users
`id` UUID PK, `telegram_id` BIGINT UNIQUE, `telegram_username`, `telegram_first_name`, `settings` JSONB, `bookmarks_count` INT, `created_at`, `last_active`

### bookmarks
`id` UUID PK, `user_id` FK→users CASCADE, `source`, `source_message_id`, `url`, `raw_text` NOT NULL, `title`, `content_type`, `summary` (AI), `category` (AI), `language` (AI), `embedding` vector(1024), `search_vector` TSVECTOR, `ai_status` (pending/processing/completed/failed), `retry_count`, `is_favorite`, `is_archived`, `created_at`, `updated_at`

### tags
`id` UUID PK, `user_id` FK, `name` VARCHAR(100), `color`, `bookmarks_count`, UNIQUE(user_id, name)

### bookmark_tags
`bookmark_id` FK PK, `tag_id` FK PK (M2M)

### Индексы
- HNSW на `embedding` (vector_cosine_ops, m=16, ef_construction=64)
- GIN на `search_vector`
- Partial unique на `(user_id, source, source_message_id)` — дедупликация
- Триггер авто-обновления `search_vector`

---

## Аутентификация

| Клиент | Flow |
|--------|------|
| Bot | `message.from_user.id` + X-Bot-Secret header → JWT |
| Mini App | Telegram initData → HMAC-SHA256 → JWT |
| iOS App | Через Mini App → JWT |

---

## Переменные окружения (.env)

```bash
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/bookmarkbrain
REDIS_URL=redis://localhost:6379
TELEGRAM_BOT_TOKEN=your_bot_token
BOT_SECRET=shared_secret_for_bot_auth
MINI_APP_URL=https://your-mini-app.vercel.app

# AI — переключение провайдера
AI_PROVIDER=gigachat          # gigachat | claude
EMBEDDING_PROVIDER=voyage     # voyage | gigachat
GIGACHAT_AUTH_KEY=your_key
ANTHROPIC_API_KEY=your_key
VOYAGE_API_KEY=your_key

SECRET_KEY=random_secret_for_jwt
ENVIRONMENT=development
```

---

## Статус разработки

### Готово (Промпты 1-10)
- [x] Docker Compose (PostgreSQL + Redis)
- [x] Models + Alembic migrations
- [x] Pydantic schemas
- [x] Auth (JWT + Telegram initData + bot secret)
- [x] AI Classifier (GigaChat + Claude, абстракция)
- [x] Embeddings (Voyage AI, 1024 dims)
- [x] Hybrid Search (semantic + full-text)
- [x] arq Worker (фоновая AI-обработка)
- [x] Bookmark API (17 endpoints)
- [x] Telegram Bot (@N0teeBot — /start, forward, /search, /random, /stats)

### Следующие шаги
- [ ] Telegram Mini App (Промпт 12) — приоритет
- [ ] Expo iOS App (Промпт 11)
- [ ] Deploy на Railway (Промпт 13)
