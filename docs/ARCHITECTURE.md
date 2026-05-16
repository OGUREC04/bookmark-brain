# Архитектура BookmarkBrain

## Высокоуровневая диаграмма

```
┌─────────────┐                              ┌─────────────────────────────┐
│  Telegram   │ ◀────── polling/webhook ───▶ │  Bot (aiogram 3.x)          │
│  (юзер)     │                              │  bot/main.py + handlers/    │
└─────────────┘                              └─────────────┬───────────────┘
                                                           │ httpx + JWT
                                                           ▼
                                             ┌─────────────────────────────┐
                                             │  Backend API (FastAPI)      │
                                             │  backend/main.py + /api/v1/ │
                                             └──┬──────────────────────┬───┘
                                                │                      │
                                          enqueue                  read/write
                                                │                      │
                                                ▼                      ▼
                                  ┌─────────────────────┐    ┌──────────────────┐
                                  │  Redis + arq queue  │    │  PostgreSQL +    │
                                  │  (job: process_     │    │  pgvector        │
                                  │   bookmark_task)    │    │                  │
                                  └──────────┬──────────┘    └──────────────────┘
                                             │ pop job              ▲
                                             ▼                      │ write
                                  ┌──────────────────────────────────────────┐
                                  │  Worker (arq, run_worker.py)             │
                                  │  bookmark_processor.py                   │
                                  └──┬─────────┬─────────┬─────────┬─────────┘
                                     │         │         │         │
                                     ▼         ▼         ▼         ▼
                                ┌────────┐ ┌──────┐ ┌────────┐ ┌─────────┐
                                │GigaChat│ │Voyage│ │ Yandex │ │ dedup   │
                                │ classy │ │ embed│ │SpeechKit│ │ checker │
                                │ /tags  │ │ 1024d│ │  STT   │ │(local)  │
                                └────────┘ └──────┘ └────────┘ └─────────┘
```

## Компоненты

### Bot (`bot/`)
aiogram 3.x на Python 3.14. В dev — long polling (`@bookmarkbrain_dev_bot`), в prod — long polling в Docker контейнере (`@N0teeBot`). Хэндлеры разбиты по типам:

- `start.py` — `/start`, forwarded messages, plain text → bookmark
- `media.py` — voice / video_note / audio → STT pipeline
- `documents.py` — PDF / DOCX / TXT / MD
- `tasks.py` — task list rendering, reply-команды (NL edit)
- `search.py` — `/search <query>`
- `random.py` — `/random`, `/stats`
- `settings.py` — `/silent`, прочие toggle
- `clean.py` — `/clean` (но защищает task lists от удаления)

Бот не делает AI-вызовов сам — всё через REST API бэкенда (`api_client.py` + `BOT_SECRET` header).

### Backend (`backend/`)
FastAPI + async SQLAlchemy. Версионирование `/api/v1/`, healthcheck `/health`, CORS.

- `main.py` — приложение, роутеры, CORS, startup hooks
- `app/api/` — `users.py`, `bookmarks.py`, `search.py`, `feedback.py`
- `app/services/` — бизнес-логика (см. ниже)
- `app/auth.py` — JWT, Telegram initData HMAC, X-Bot-Secret
- `app/worker.py` — arq WorkerSettings (используется и run_worker.py)

### Worker (`backend/run_worker.py` + `app/worker.py`)
arq на Redis. Запускается через `asyncio.run()` (CLI arq ломается на Python 3.14 — см. ADR не в этом списке, но в TROUBLESHOOTING). Один воркер процессит все типы задач:

- `process_bookmark_task` — основной AI pipeline
- `embedding_retry_cron` — переобработка `ai_status=failed`
- `stale_list_nudge` — крон для напоминаний по task lists

### Services
- `ai_classifier.py` — `BaseClassifier` → GigaChat / Claude (переключается через `AI_PROVIDER`)
- `embeddings.py` — `BaseEmbeddingService` → Voyage AI / GigaChat (`EMBEDDING_PROVIDER`)
- `bookmark_processor.py` — оркестратор пайплайна (classify → embed → tag → dedup → save)
- `dedup_checker.py` — двухуровневая дедупликация (cosine + text overlap)
- `search.py` — гибридный поиск (semantic + full-text)
- `search_summary.py` — AI-обзор результатов поиска
- `task_list_*` — детекция, рендеринг, NL-редактирование списков задач
- `article_fetcher.py` — fetch+extract по URL для линков
- `telegram_import.py` — импорт из Saved Messages

## Data flow — основной сценарий «юзер пишет текст»

```
1. Telegram webhook/polling → bot/handlers/start.py
2. Bot: ставит реакцию 👀, шлёт POST /api/v1/bookmarks/ (с X-Bot-Secret)
3. Backend: создаёт Bookmark(ai_status='pending'), enqueue arq job, отвечает 201
4. Bot: возвращает control юзеру (≤ 2 сек)
5. Worker pops job → bookmark_processor.process(bookmark_id):
   a. classify (GigaChat) → category, language, summary
   b. dedup_checker → ищет похожие через embedding cosine + text overlap
       → если найден → ai_status='completed', dedup_alert callback в боте
   c. embed (Voyage AI) → vector(1024)
   d. tag extraction → upsert в tags + bookmark_tags
   e. UPDATE bookmarks SET ai_status='completed', updated_at=now()
6. Bot: callback от воркера через Redis pub/sub → меняет реакцию 👀 → 👍
```

**Failure mode:** если на шаге 5 что-то падает (GigaChat 402, Voyage timeout) — `ai_status='failed'`, `retry_count++`. Закладка остаётся в БД с `raw_text`, юзер её всё равно видит. `embedding_retry_cron` каждый час пытается переобработать.

## Схема БД (главное)

```
users
├── id            UUID PK
├── telegram_id   BIGINT UNIQUE
├── settings      JSONB        ← silent_mode, prefs
├── bookmarks_count INT
└── created_at, last_active

bookmarks
├── id            UUID PK
├── user_id       FK → users CASCADE
├── source        ENUM (text, voice, document, forward, url)
├── source_message_id  BIGINT
├── raw_text      TEXT NOT NULL
├── title         TEXT
├── url           TEXT
├── content_type  VARCHAR
├── summary       TEXT          ← AI
├── category      VARCHAR       ← AI
├── language      VARCHAR       ← AI
├── embedding     vector(1024)  ← Voyage AI
├── search_vector TSVECTOR      ← триггер из raw_text+title+summary
├── ai_status     ENUM (pending, processing, completed, failed)
├── retry_count   INT
├── transcription TEXT          ← для voice
├── media_duration INT
├── media_file_id  TEXT
├── document_page_count INT
├── is_favorite   BOOL
├── is_archived   BOOL
└── created_at, updated_at

tags
├── id            UUID PK
├── user_id       FK
├── name          VARCHAR(100)
├── color         VARCHAR
├── bookmarks_count INT
└── UNIQUE(user_id, name)

bookmark_tags  -- M2M
├── bookmark_id  FK PK
└── tag_id       FK PK

folders         -- зарезервировано под Smart Blocks (Phase 5)
```

### Индексы и триггеры
- HNSW на `bookmarks.embedding` (`vector_cosine_ops`, m=16, ef_construction=64)
- GIN на `bookmarks.search_vector`
- Partial unique на `(user_id, source, source_message_id) WHERE source_message_id IS NOT NULL` — дедупликация на уровне БД
- Триггер обновления `search_vector` (русская конфигурация)

## Аутентификация

| Клиент | Flow |
|--------|------|
| Bot | `from_user.id` + `X-Bot-Secret` header → backend issue JWT |
| Mini App (план) | Telegram initData → HMAC-SHA256 (BOT_TOKEN secret) → JWT |
| iOS App (план) | Через Mini App → JWT |

JWT короткоживущий (24h). `BOT_SECRET` — shared secret между ботом и backend, никогда не покидает сервер.

## Инфраструктура

### Production
- **VPS:** Beget Cloud (Ubuntu 22.04, 2 CPU, 4GB RAM)
- **Docker Compose** (`docker-compose.prod.yml`): postgres, redis, backend, worker, bot
- **Деплой:** `git pull && ./deploy.sh` (см. `docs/DEVELOPMENT-GUIDE.md`)
- **CI:** GitHub Actions (`.github/workflows/test.yml`) — pytest на push
- **CD:** настроен, но `VPS_HOST`/`VPS_USER`/`VPS_SSH_KEY` ещё не добавлены в GitHub Secrets

### Локальная разработка
- `start.bat` / `stop.bat` — Docker (postgres + redis) + venv-процессы (backend, worker, bot)
- venv в `%LOCALAPPDATA%\bookmark-brain\venv` (вне OneDrive — Python 3.14 ломается на синхронизируемом)
- Dev-бот `@bookmarkbrain_dev_bot`, отдельный токен в локальном `.env`

## Переменные окружения

См. `.env.production.example`. Главное:

```bash
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://redis:6379
TELEGRAM_BOT_TOKEN=...
BOT_SECRET=...
SECRET_KEY=...                # JWT

AI_PROVIDER=gigachat          # gigachat | claude
EMBEDDING_PROVIDER=voyage     # voyage | gigachat
GIGACHAT_AUTH_KEY=...
VOYAGE_API_KEY=...
ANTHROPIC_API_KEY=...         # опционально

STT_PROVIDER=yandex           # yandex | groq | openai
YANDEX_STT_API_KEY=...
YANDEX_FOLDER_ID=...

ENVIRONMENT=production
```

## Слои и import-контракты (living contract)

Структурные правила кодовой базы — **машинно-enforced**, не «по договорённости».
Источник истины: `pyproject.toml [tool.importlinter]` + `[tool.ruff]`;
hard-fail в CI (`.github/workflows/test.yml`).

| Правило | Что запрещает | Чем enforced |
|---|---|---|
| **Feature independence** | `bot.handlers.reminders` ↔ `bot.handlers.tasks` прямые импорты друг друга | import-linter `independence` |
| **Layering** | `bot.common` импортит handler/composition root (upward) | import-linter `layers` |
| **No relative cross-package** | relative-импорт между пакетами | ruff `TID` |
| **File size** | новый код в файл > 800 LOC | `~/.claude/rules` + review |

Слои (сверху вниз): `bot.main` → `bot.handlers` (features + `start.py`
оркестратор в одном слое) → `bot.common` (shared инфра, самый низ).
Общий код фич живёт в `bot.common` (публичные имена, `__all__`); фичи
делятся **только** через него или через `start.py`-оркестрацию.

Почему: split трёх 1600–1900-LOC монолитов однажды зашипил CRITICAL-баг
из-за латеральной связи (`tasks/nl_edit` лез в приватные внутренности
`reminders`). Контракты делают регресс невозможным. Полная карта,
команды и правила добавления кода — в корневом **`AGENTS.md`** (читать
первым). Guard-тесты: `tests/test_architecture_contracts.py`,
`tests/test_cross_package_import_contract.py`.

## Связанные документы

- `AGENTS.md` — карта репо, команды, dependency-контракт (entrypoint).
- `docs/SPEC.md` — что строит этот стек.
- `docs/decisions/` — почему именно эти технологии.
- `docs/BOT-UX.md` — детали бот-логики, clean chat, task lists.
- `docs/TROUBLESHOOTING.md` — известные грабли (GigaChat 402, arq + Python 3.14, и т.д.).
- `docs/DEVELOPMENT-GUIDE.md` — как запускать и деплоить.
