# Архитектура BookmarkBrain

> Проверено: 2026-05-16 · класс: evergreen · конвенция обновления: `docs/README.md`

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

> Структурные правила и слои — в разделе ниже «Слои и import-контракты».
> Карта репо для агентов/разработчиков — корневой `AGENTS.md`.

### Bot (`bot/`)
aiogram 3.x. Dev — long polling под `@bookmarkbrain_dev_bot` (локально Python 3.14); prod — long polling в Docker (`python:3.12-slim`, `@N0teeBot`).

Хэндлеры — **package-by-feature**: крупные домены вынесены в пакеты с
facade-`__init__.py` (агрегирует sub-роутеры через `include_router`,
публичный API в `__all__`):

- `handlers/start.py` — `/start`, forwarded, plain text → bookmark; orchestration-хаб
- `handlers/reminders/` — пакет: `list` (`/reminders`), `explicit` (`/remind`+T8), `callbacks` (rsk/rsn/rdone/rsnz), `reply` (reply-парсинг), `strong` (T13 3-кнопки, отдельный `strong_router`), `shared`
- `handlers/tasks/` — пакет: `task_callbacks`, `dedup`, `fast_edit`, `nl_edit`, `commands`, `shared`
- `handlers/media.py` — voice / video_note / audio → STT
- `handlers/documents.py` — PDF / DOCX / TXT / MD
- `handlers/{search,random,settings,clean,timezone,reminder_choice}.py`
- `common/` — **shared-слой** (самый низ): `text.safe`, `datetime.{format_fire_at,get_user_tz_name}`, `nl.{split_remind_text_and_time,extract_explicit_remind_body}`, `telegram.send_ephemeral`, `auth.ensure_user` (JWT-bootstrap + token-cache). Фичи делятся **только** через `bot.common` — латеральные reminders↔tasks импорты запрещены import-linter'ом.

Бот не делает AI-вызовов сам — всё через REST API бэкенда (`api_client.py` + `BOT_SECRET` header).

### Backend (`backend/`)
FastAPI + async SQLAlchemy. Версионирование `/api/v1/`, healthcheck `/health`, CORS.

- `main.py` — приложение, роутеры, CORS, startup hooks
- `app/api/` — `users.py`, `bookmarks.py`, `search.py`, `feedback.py`, `reminders.py`
- `app/services/` — бизнес-логика (см. ниже)
- `app/auth.py` — JWT, Telegram initData HMAC, X-Bot-Secret
- `app/worker/` — **пакет** arq-воркера (см. ниже); `WorkerSettings` импортируется из `app.worker`

### Worker (`backend/run_worker.py` + `app/worker/`)
arq на Redis. Запуск — `python run_worker.py` → `create_worker(WorkerSettings)` через `asyncio.run()` (CLI arq ломается на Python 3.14, см. TROUBLESHOOTING). `app/worker/` — пакет:

- `processing.py` — `process_bookmark_task` (основной AI pipeline)
- `reminder_decision.py` — Phase 2.6 three-form dispatch, CAS-идемпотентность
- `reminder_offer.py` — weak-offer «🔔 Создать напоминание?»
- `scheduled.py` — 5 cron: `scheduled_dispatcher`, `auto_done_reminders`, `retry_failed_task`, `retry_partial_embeddings`, `stale_list_nudge`
- `dedup.py`, `telegram.py` — dedup-стораджи и low-level Telegram-хелперы
- `__init__.py` — facade: собирает `WorkerSettings` (functions + cron_jobs)

### Services
- `ai_classifier.py` — `BaseClassifier` → GigaChat (slot под DeepSeek/Claude, `AI_PROVIDER`)
- `embeddings.py` — `BaseEmbeddingService` → Voyage AI / GigaChat (`EMBEDDING_PROVIDER`)
- `bookmark_processor.py` — оркестратор пайплайна (classify → embed → tag → dedup → save)
- `dedup_checker.py` — двухуровневая дедупликация (cosine + text overlap)
- `search.py` / `search_summary.py` — гибридный поиск + AI-обзор
- `task_list_*` — детекция, рендеринг, NL-редактирование списков задач
- `reminder_*` (`router`/`creator`/`cascade`) — Phase 2.6 three-form reminders
- `nl_date.py` — парсинг естественного времени («завтра в 9», NEEDS_HOUR)
- `article_fetcher.py` / `telegram_import.py` — fetch по URL / импорт Saved Messages

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

JWT живёт 7 дней; бот кэширует токен в памяти `bot.common.auth` 6 дней (рефреш до истечения). `BOT_SECRET` — shared secret бота и backend, никогда не покидает сервер.

### DEV-only auth bypass (headless E2E)

Для прогона Mini App в обычном браузере без Telegram-клиента — `/auth/telegram` принимает `init_data="dev:<DEV_AUTH_TELEGRAM_ID>"` за **тройным** guard'ом:

1. `settings.ENVIRONMENT != "production"`
2. `settings.DEV_AUTH_BYPASS == True`
3. `tid == settings.DEV_AUTH_TELEGRAM_ID` (id должен быть > 1e12 — startup guard в `config.py` рефьюзит запуск иначе)

При успешном bypass — WARNING в лог с `event=dev_auth_bypass`. Сид тестовых данных под этот id: `backend/scripts/seed_dev_e2e.sql` (двойная защита: db-name allowlist + порог по числу юзеров — в прод не зальётся). Фронт-сторона — localStorage-fallback в `src/lib/api.ts`: `__dev_init_data` подсасывается когда нет реального Telegram. `.env` гитнорится, флаги локальные.

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
