# BookmarkBrain — Архитектурный план и промпты для сборки

## Context
Проект BookmarkBrain — AI-инструмент для организации сохранённого контента. Скелет создан (папки, пустые файлы, конфиги), кода нет. Нужен полный план: ревью архитектуры, схема БД, фазы разработки, и последовательность промптов для Claude Code.

---

## 1. РЕВЬЮ АРХИТЕКТУРЫ

### Проблемы в текущем стеке

**Telethon — главный риск проекта.**
- Требует user session (полный доступ к аккаунту Telegram). Утечка БД = утечка аккаунтов.
- Telegram банит аккаунты за автоматизацию. FloodWait ошибки гарантированы.
- **Рекомендация для MVP**: отказаться от Telethon. Вместо этого — пользователь пересылает сообщения боту. Это безопаснее, проще, и покрывает 90% use case. Telethon можно добавить в V2 если реально понадобится.

**Celery → заменить на arq.**
- Celery — sync-first, а весь backend async. Вечная боль с event loops.
- arq — async-native, использует тот же Redis, значительно проще в настройке.
- Для проекта с 1 типом фоновых задач (AI-обработка) — идеальная замена.

**Ошибки в CLAUDE.md:**
- Embedding dimension указан как 1536 — должен быть **1024** (voyage-3)
- Нет `VOYAGE_API_KEY` в `.env.example`
- `passlib[bcrypt]` избыточен — паролей нет, только Telegram auth
- `nginx.conf` не нужен для Railway

### Коммуникация компонентов

```
[Expo iOS] ──REST──> [FastAPI Backend] <──REST── [Telegram Bot (aiogram)]
                           │
                      [Redis Queue]
                           │
                      [arq Worker] ──> [Claude API / Voyage API]

[Mini App] ──REST──> [FastAPI Backend]
```

REST везде. WebSocket не нужен — закладки не real-time.

### Стратегия аутентификации

| Клиент | Flow |
|--------|------|
| Mini App | Telegram initData → HMAC-SHA256 верификация → JWT |
| Bot | `message.from_user.id` + shared secret header |
| iOS App | Первичная авторизация через Mini App → JWT |

Единая точка входа — `telegram_id`. Единый JWT для всех клиентов.

---

## 2. DATA MODEL

### Таблицы

**users** — `id` UUID PK, `telegram_id` BIGINT UNIQUE, `telegram_username`, `telegram_first_name`, `settings` JSONB, `import_status`, `bookmarks_count` INT, `created_at`, `last_active`

**bookmarks** — `id` UUID PK, `user_id` FK→users CASCADE, `source` (telegram/manual/bot_forward), `source_message_id` BIGINT, `source_date`, `url` TEXT, `raw_text` TEXT NOT NULL, `title`, `content_type`, `summary` TEXT (AI), `category` (AI), `language` (AI), `embedding` vector(1024), `search_vector` TSVECTOR, `ai_status` (pending/processing/completed/failed), `ai_error`, `retry_count`, `is_favorite`, `is_archived`, `created_at`, `updated_at`, `last_accessed`

**tags** — `id` UUID PK, `user_id` FK, `name` VARCHAR(100), `color`, `bookmarks_count`, UNIQUE(user_id, name)

**bookmark_tags** — `bookmark_id` FK PK, `tag_id` FK PK (M2M)

### Ключевые индексы
- HNSW на `embedding` (vector_cosine_ops, m=16, ef_construction=64)
- GIN на `search_vector`
- Partial unique на `(user_id, source, source_message_id)` — дедупликация
- Partial на `ai_status WHERE != 'completed'` — быстрый поиск необработанных
- Триггер на `search_vector` — автообновление при INSERT/UPDATE

---

## 3. ФАЗЫ РАЗРАБОТКИ

### Фаза 0: Инфраструктура (1-2 дня)
- Git init, Docker Compose работает, models + migrations, FastAPI /health
- Заменить celery на arq в requirements.txt
- **Валидация:** `docker compose up` → `alembic upgrade head` → `curl /health`

### Фаза 1: MVP — Bot + AI (5-7 дней)
- Бот принимает пересланные сообщения → сохраняет как закладки
- AI-классификация (Claude) + embeddings (Voyage) через arq worker
- Семантический + full-text поиск через бота (/search)
- /random, /stats
- **Валидация:** Переслать 20 сообщений боту, все обработаны, поиск работает

### Фаза 2: Mini App + iOS (7-10 дней)
- Expo app: feed, search, filters, bookmark detail, settings
- Telegram Mini App: Expo Web + Telegram SDK
- **Валидация:** Открыть Mini App из Telegram, авторизация автоматическая, поиск работает

### Фаза 3: Deploy + Polish
- Dockerfiles, Railway deploy (3 сервиса: backend, worker, bot)
- Sentry, логирование, rate limiting

---

## 4. ПРОМПТЫ ДЛЯ CLAUDE CODE (13 штук)

Порядок строгий. Каждый зависит от предыдущего.

---

### Промпт 1 — Database & Models
```
Реализуй database layer для BookmarkBrain.

Файлы:
- backend/app/database.py
- backend/app/models.py
- backend/app/config.py (новый — pydantic-settings)

database.py:
- AsyncEngine через create_async_engine(DATABASE_URL)
- async_sessionmaker с expire_on_commit=False
- get_session() — async generator для Depends()

config.py:
- class Settings(BaseSettings): DATABASE_URL, REDIS_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH, ANTHROPIC_API_KEY, VOYAGE_API_KEY, SECRET_KEY, ENVIRONMENT
- model_config с env_file=".env"
- get_settings() с lru_cache

models.py (async SQLAlchemy, все DateTime с timezone=True, UUID default через func.gen_random_uuid()):
- User: id(UUID PK), telegram_id(BigInteger UNIQUE NOT NULL), telegram_username, telegram_first_name, settings(JSONB default={}), import_status(String default='none'), bookmarks_count(Integer default=0), created_at, last_active
- Bookmark: id(UUID PK), user_id(FK→users CASCADE), source(String NOT NULL), source_message_id(BigInteger nullable), source_date, url(Text nullable), raw_text(Text NOT NULL), title(String(500)), content_type(String default='other'), summary(Text nullable), category(String(30) nullable), language(String(10) nullable), embedding(Vector(1024) nullable), search_vector(TSVECTOR nullable), ai_status(String default='pending'), ai_error, ai_processed_at, retry_count(Integer default=0), is_favorite(Boolean default=False), is_archived(Boolean default=False), created_at, updated_at, last_accessed
- Tag: id(UUID PK), user_id(FK), name(String(100) NOT NULL), color(String(7) nullable), bookmarks_count(Integer default=0), created_at. UniqueConstraint(user_id, name)
- BookmarkTag: bookmark_id(UUID FK PK), tag_id(UUID FK PK)

Индексы: telegram_id; (user_id, created_at DESC); partial ai_status WHERE != 'completed'; unique partial (user_id, source, source_message_id); GIN на search_vector; HNSW на embedding vector_cosine_ops (m=16, ef_construction=64); tag_id в bookmark_tags.

Используй: pgvector.sqlalchemy.Vector, sqlalchemy.dialects.postgresql (UUID, JSONB, TSVECTOR, BIGINT). Relationships между User↔Bookmark, Bookmark↔Tag.

## Important
- Respond in Russian
- You can suggest changes to the stack if you see better alternatives. Explain why clearly. I'm open to changes if the argument is strong.
```
**Тест:** `python -c "from app.models import User, Bookmark, Tag; print('OK')"`

---

### Промпт 2 — Alembic + Migrations
```
Настрой Alembic для async миграций в backend/.

1. Инициализируй alembic в backend/migrations
2. env.py: async engine, target_metadata = Base.metadata из app.models, sqlalchemy.url из Settings
3. alembic.ini в backend/, script_location = migrations
4. Начальная миграция с autogenerate. В upgrade() добавь:
   - CREATE EXTENSION IF NOT EXISTS "vector"
   - CREATE EXTENSION IF NOT EXISTS "pg_trgm"
   - Триггер для автообновления search_vector (функция + trigger на bookmarks)

## Important
- Respond in Russian
```
**Тест:** `cd backend && alembic upgrade head` (с запущенным Docker PostgreSQL)

---

### Промпт 3 — Pydantic Schemas
```
Создай Pydantic schemas в backend/app/schemas.py.

Все с ConfigDict(from_attributes=True).

- UserCreate(telegram_id, telegram_username?, telegram_first_name?)
- UserResponse(id, telegram_id, telegram_username, bookmarks_count, created_at)
- BookmarkCreate(raw_text, url?=None, title?=None, source="manual", source_message_id?=None, source_date?=None, content_type="other")
- BookmarkResponse(id, user_id, source, url, raw_text, title, content_type, summary, category, tags: list[TagResponse], ai_status, is_favorite, is_archived, created_at, updated_at)
- BookmarkListResponse(items: list[BookmarkResponse], total, page, per_page)
- BookmarkUpdate(title?=None, is_favorite?=None, is_archived?=None)
- SearchRequest(query, limit=20, offset=0, category?=None, tags?=None)
- SearchResult(bookmark: BookmarkResponse, score: float)
- SearchResponse(results: list[SearchResult], total, query)
- TagResponse(id, name, color, bookmarks_count)
- TagCreate(name, color?=None)
- AIClassification(summary, tags: list[str], category, language) — internal
- TelegramAuthData(init_data: str)
- TokenResponse(access_token, token_type="bearer")

## Important
- Respond in Russian
```
**Тест:** `python -c "from app.schemas import BookmarkCreate, SearchRequest; print('OK')"`

---

### Промпт 4 — Auth + User API
```
Реализуй аутентификацию и user endpoints.

backend/app/auth.py (новый):
- verify_telegram_init_data(init_data, bot_token) → dict: HMAC-SHA256 верификация по алгоритму Telegram (secret = HMAC("WebAppData", bot_token), data_check_string = sorted params без hash, joined by \n)
- create_access_token(user_id, telegram_id) → JWT (exp=7 days, python-jose)
- get_current_user(token = Depends(OAuth2PasswordBearer)) → User из БД
- verify_bot_request(x_bot_secret: Header) → проверка shared secret

backend/app/api/users.py (prefix="/api"):
- POST /auth/telegram — TelegramAuthData → verify → create/update User → TokenResponse
- GET /users/me → UserResponse
- PATCH /users/me/settings → обновить settings JSONB

backend/main.py:
- FastAPI app, CORS middleware, include router, GET /health, lifespan

## Important
- Respond in Russian
```
**Тест:** `uvicorn main:app --reload` → Swagger на `/docs` показывает endpoints

---

### Промпт 5 — AI Classifier
```
Реализуй AI-классификацию через Claude API.

backend/app/services/ai_classifier.py:

class AIClassifier:
    def __init__(self, api_key): self.client = anthropic.AsyncAnthropic(api_key=api_key)
    
    async def classify(self, text, url=None) → AIClassification:
        Claude claude-sonnet-4-20250514, structured JSON output.
        System prompt: "Проанализируй закладку, верни JSON: summary (1-2 предложения на языке оригинала), tags (3-5, lowercase, на языке оригинала), category (article/course/idea/event/tool/video/other), language (ru/en/etc)."
        User: f"URL: {url}\n\nТекст:\n{text[:4000]}"
        max_tokens=500, temperature=0.3
        Retry 1 раз если не JSON. При повторном fail — raise ClassificationError.

Ошибки: RateLimitError → RetryableError, APIError → log + ClassificationError, timeout 30s.

## Important
- Respond in Russian
```
**Тест:** Скрипт с 3 текстами (статья, идея, цитата) → валидный AIClassification

---

### Промпт 6 — Embedding Service
```
Реализуй embeddings через Voyage AI.

backend/app/services/embeddings.py:

class EmbeddingService:
    def __init__(self, api_key): httpx.AsyncClient, base_url="https://api.voyageai.com/v1", model="voyage-3"
    async def get_embedding(self, text) → list[float]: POST /embeddings, input=[text[:8000]], return 1024-dim vector
    async def get_embeddings_batch(self, texts, batch_size=128) → list[list[float]]: батчи по 128
    async def close()

Rate limit (429) → RetryableError. Добавь VOYAGE_API_KEY в config.py и .env.example.

## Important
- Respond in Russian
```
**Тест:** Embedding для "тестовый текст", проверить len == 1024

---

### Промпт 7 — Search Service
```
Реализуй гибридный поиск (semantic + full-text).

backend/app/services/search.py:

class SearchService:
    async def search(self, user_id, query, limit=20, offset=0, category=None, tags=None):
        1. Embedding запроса через EmbeddingService
        2. Semantic: 1 - (embedding <=> query_embedding) AS semantic_score
        3. Full-text: ts_rank(search_vector, plainto_tsquery('russian', query))
        4. Combined: 0.7 * semantic + 0.3 * text (больше веса full-text для коротких запросов)
        5. Фильтры по category, tags (JOIN bookmark_tags + tags)
        6. Пагинация LIMIT/OFFSET
        7. Return (bookmarks + scores, total)

Raw SQL через text() для pgvector. Parameterized queries.

## Important
- Respond in Russian
```
**Тест:** 10 закладок с AI → 5 поисковых запросов → проверить релевантность

---

### Промпт 8 — arq Worker
```
Реализуй фоновый воркер для AI-обработки.

backend/app/worker.py (новый):
- process_bookmark_task(ctx, bookmark_id): создать session → BookmarkProcessor.process_bookmark()
- retry_failed_task(ctx): cron ночной retry для failed bookmarks
- WorkerSettings: functions, cron_jobs, redis_settings, max_jobs=5, job_timeout=120

backend/app/services/bookmark_processor.py (новый):
class BookmarkProcessor:
    async def process_bookmark(self, bookmark_id):
        1. Load bookmark, check ai_status
        2. Set ai_status='processing'
        3. classifier.classify() → summary, category, language
        4. embedder.get_embedding() → embedding
        5. Get-or-create Tags, create BookmarkTag links
        6. Update bookmark: all AI fields, ai_status='completed'
        7. Update counts (User.bookmarks_count, Tag.bookmarks_count)
        Error: classifier fail → ai_status='failed', retry_count++. Embedder fail → ai_status='partial'. retry_count >= 3 → stop.

Замени celery на arq==0.26.1 в requirements.txt.

## Important
- Respond in Russian
```
**Тест:** Создать закладку через API → через 10 сек ai_status='completed', summary и tags заполнены

---

### Промпт 9 — Bookmark API
```
Реализуй CRUD и поиск endpoints.

backend/app/api/bookmarks.py (prefix="/api/bookmarks"):
- POST / — BookmarkCreate → save + queue arq task → 201
- GET / — список с пагинацией, фильтры (category, is_favorite, is_archived)
- GET /{id} — одна закладка (проверка ownership), update last_accessed
- PATCH /{id} — BookmarkUpdate
- DELETE /{id} — 204
- POST /{id}/reprocess — сброс ai_status, новая задача в очередь

backend/app/api/search.py (prefix="/api/search"):
- POST / — SearchRequest → SearchService → SearchResponse
- GET /tags — теги пользователя sorted by bookmarks_count DESC

Все endpoints через Depends(get_current_user). Pydantic schemas only. Добавить routers в main.py.

## Important
- Respond in Russian
```
**Тест:** Swagger UI: создать 3 закладки → список → поиск → favorite → удалить

---

### Промпт 10 — Telegram Bot
```
Реализуй Telegram бота на aiogram 3.x.

bot/config.py — Settings: BOT_TOKEN, BACKEND_URL, BOT_SECRET
bot/api_client.py — BackendClient(httpx): get_or_create_user, create_bookmark, search_bookmarks, get_random_bookmark, get_user_stats

bot/main.py — Bot + Dispatcher, webhook для prod, polling для dev
bot/handlers/start.py:
- /start → создать user, приветствие + inline кнопка "Открыть приложение" (web_app)
- Forwarded messages → извлечь текст + URLs → create_bookmark → "Сохранено!"
- Обычные текстовые сообщения → тоже сохранить как закладку

bot/handlers/search.py — /search <query> → результаты (max 5) + "Показать ещё"
bot/handlers/random.py — /random → случайная закладка; /stats → статистика по категориям

## Important
- Respond in Russian
```
**Тест:** Polling mode → /start → переслать 5 сообщений → /search → /random → /stats

---

### Промпт 11 — Expo Frontend
```
Реализуй iOS приложение на Expo с expo-router.

Новые файлы: frontend/lib/api.ts, lib/auth.ts, lib/types.ts, components/BookmarkCard.tsx, components/TagChip.tsx, components/SearchBar.tsx
Новые deps: @react-native-async-storage/async-storage, expo-secure-store, @tanstack/react-query

app/_layout.tsx — Stack nav, auth check, React Query Provider
app/index.tsx — FlatList + BookmarkCard, pull-to-refresh, infinite scroll, category фильтры
app/search.tsx — SearchBar с debounce 500ms, результаты, теги-фильтры
app/bookmark/[id].tsx — полная карточка, кнопки Favorite/Archive/Open URL
app/settings.tsx — профиль, статистика, logout

Дизайн: минимализм, light/dark auto, нейтральные серые + синий акцент.

## Important
- Respond in Russian
```
**Тест:** `npx expo start --web` → все экраны рендерятся, навигация работает

---

### Промпт 12 — Telegram Mini App
```
Добавь Telegram Mini App поддержку в Expo Web.

frontend/lib/telegram.ts: isTelegramMiniApp(), getTelegramInitData(), authenticateViaTelegram(backendUrl), setupTelegramUI(), hapticFeedback()
Dep: @telegram-apps/sdk

app/_layout.tsx: если Mini App → auto-auth + setupTelegramUI(), скрыть header. Если iOS → обычный flow.
Код @telegram-apps/sdk только для Platform.OS === 'web'.

## Important
- Respond in Russian
```
**Тест:** Expo Web → браузер работает. Deploy → открыть из Telegram → auto-auth

---

### Промпт 13 — Deploy
```
Подготовь деплой на Railway.

backend/Dockerfile — python:3.12-slim, uvicorn
bot/Dockerfile — python:3.12-slim, python main.py

Railway: 3 сервиса (backend, worker: arq app.worker.WorkerSettings, bot).
POST /bot/webhook endpoint в FastAPI для Telegram webhook.
Bot: webhook в prod, polling в dev.

## Important
- Respond in Russian
```
**Тест:** `railway up` → health check → бот отвечает → закладки обрабатываются

---

## 5. Файлы для модификации/создания

### Существующие (будут заполнены):
- `backend/app/models.py`, `database.py`, `schemas.py`
- `backend/app/api/bookmarks.py`, `users.py`, `search.py`
- `backend/app/services/ai_classifier.py`, `embeddings.py`, `search.py`, `telegram_import.py`
- `backend/main.py`
- `bot/main.py`, `bot/handlers/start.py`, `search.py`, `random.py`
- `frontend/app/index.tsx`, `search.tsx`, `settings.tsx`, `bookmark/[id].tsx`
- `backend/requirements.txt` — заменить celery на arq, добавить voyageai

### Новые файлы:
- `backend/app/config.py`
- `backend/app/auth.py`
- `backend/app/worker.py`
- `backend/app/services/bookmark_processor.py`
- `backend/Dockerfile`, `bot/Dockerfile`
- `bot/config.py`, `bot/api_client.py`
- `frontend/lib/api.ts`, `auth.ts`, `types.ts`, `telegram.ts`
- `frontend/components/BookmarkCard.tsx`, `TagChip.tsx`, `SearchBar.tsx`

## 6. Верификация (end-to-end)

1. `docker compose up` — postgres + redis запущены
2. `cd backend && alembic upgrade head` — миграции прошли
3. `uvicorn main:app --reload` + `arq app.worker.WorkerSettings` — backend + worker
4. Бот в polling → переслать 10 сообщений → подождать 30 сек → /search "дизайн" → релевантные результаты
5. `npx expo start --web` → авторизация → feed с закладками → поиск работает
6. Mini App из Telegram → auto-auth → те же закладки
