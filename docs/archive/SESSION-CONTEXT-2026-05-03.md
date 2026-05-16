# Контекст сессии 2026-05-03

Сводка всех изменений Phase 0 (Hardening).
Источник для будущих сессий — чтобы не терять контекст после compact.

Предыдущая сессия: `docs/SESSION-CONTEXT-2026-05-02.md` (ревью, PRD, roadmap).

---

## Что сделано в этой сессии

**Phase 0: Hardening — 20 fixes, 14 файлов, 1 миграция.**

Все 5 CRITICAL и 13 HIGH из code review (`docs/REVIEW-2026-05-02.md`) закрыты.

---

## Phase 0A: Security

| # | Issue | Fix | Файлы |
|---|-------|-----|-------|
| C1 | SECRET_KEY = "change-me-in-production" | Убран дефолт, сделан required, startup guard | `backend/app/config.py` |
| C2 | BOT_SECRET = "" | Убран дефолт в обоих конфигах, startup guard | `backend/app/config.py`, `bot/config.py` |
| C3 | verify=False для GigaChat | Configurable `GIGACHAT_CA_BUNDLE`, warning если disabled | `ai_classifier.py`, `embeddings.py` |
| C4 | _pending_saves keyed by tg_id | Ключ — message_id + TTL 5 мин с lazy eviction | `bot/handlers/start.py` |
| C5 | InaccessibleMessage не обработан | Guard `isinstance(callback.message, Message)` в 13 callback handlers | `start.py`, `tasks.py` |
| H1 | IDOR — 403 reveals existence | user_id добавлен в WHERE, единый 404 (5 endpoints) | `bookmarks.py` |
| H11 | Token cache no TTL | TTL 6 дней (`time.monotonic()`), auto-refresh | `start.py` |
| H12 | LIKE wildcards unescaped | `%`, `_`, `\` escaped + `ESCAPE '\\'` в SQL | `search.py` |

### Важные решения по C3 (verify=False):
- Сертификаты Сбера (MinTsifry CA) НЕ входят в стандартный CA bundle Python
- Если `GIGACHAT_CA_BUNDLE` не задан → `verify=False` (как было) + warning в логах
- Если задан → используется как путь к CA bundle
- Попытка сразу ставить `verify=True` сломала GigaChat — откатили к safe default

---

## Phase 0B: Bot stability

| # | Issue | Fix | Файлы |
|---|-------|-----|-------|
| H10 | httpx no retry/limits | `AsyncHTTPTransport(retries=2)`, timeout 30→10s | `bot/api_client.py` |
| H6 | _rerender_at_bottom race | Per-(chat_id, bookmark_id) `asyncio.Lock` + eviction после использования | `bot/handlers/tasks.py` |
| H7 | StateStore._get() lazy init race | `asyncio.Lock` double-check pattern | `bot/state_store.py` |
| H8 | bump_last_seen non-atomic | Atomic Lua script (GET + compare + SET в одном eval) | `bot/state_store.py` |
| H9 | Pin message offset heuristic | Убрали heuristic, полагаемся на `on_pin_service_message` handler | `bot/handlers/tasks.py` |

### Архитектурные решения:
- `_rerender_locks` dict evict-ит lock-и после использования (если `not lock.locked()`)
- `_rerender_at_bottom` разделена на wrapper (lock) + `_rerender_at_bottom_inner` (логика)
- httpx `retries=2` retry-ит только connection-level ошибки (DNS, connect timeout), не HTTP-level — безопасно для POST

---

## Phase 0C: Worker & data integrity

| # | Issue | Fix | Файлы |
|---|-------|-----|-------|
| H2 | N+1 queries в tag creation | Batch `pg_insert().on_conflict_do_nothing()` + batch `BookmarkTag` insert | `bookmark_processor.py` |
| H3 | bookmarks_count inflation on reprocess | Increment только при `ai_processed_at is None` (first processing) | `bookmark_processor.py` |
| H4 | Worker double-commit race на task_list | `session.commit()` → `session.flush()` для is_favorite + final `session.commit()` в конце | `worker.py` |

### Batch tag upsert детали:
- `INSERT ... ON CONFLICT DO NOTHING RETURNING id, name` — вставляет новые
- Для уже существующих — отдельный SELECT по `Tag.name.in_(missing)`
- `BookmarkTag` — тоже `on_conflict_do_nothing()` (composite PK = unique constraint)

---

## Phase 0D: Infrastructure

| # | Item | Реализация | Файлы |
|---|------|-----------|-------|
| 1 | /health с проверкой зависимостей | `SELECT 1` для Postgres, `PING` для Redis, 503 если degraded | `main.py` |
| 2 | API versioning | `/api/` → `/api/v1/` во всех роутерах + bot client + frontend | 4 роутера, `api_client.py`, `api.ts` |
| 3 | Embedding retry cron | Cron 5:00 AM, max 5 retries, circuit breaker (5 подряд → стоп) | `worker.py` |
| 4 | CORS fix | Explicit origins вместо `["*"]`, dev: localhost:3000/5173 | `main.py` |

### Миграция:
- `c3d4e5f6a7b8_add_embedding_retry_fields.py`
- Добавляет `bookmarks.embedding_retry_count` (int, default 0) и `embedding_last_attempt` (timestamptz)
- Применена: `alembic upgrade head` — успешно

### Embedding retry cron детали:
- Находит все `ai_status = 'partial'` с `embedding_retry_count < 5`
- Пересоздаёт embedding text из существующих полей (title + takeaway + summary + key_ideas)
- Успех → `ai_status = 'completed'`
- 5 ретраев → `ai_status = 'completed_no_embedding'` (permanent, не retry больше)
- Circuit breaker: 5 подряд фейлов → стоп (API может быть down)

---

## Все изменённые файлы

| Файл | Изменения |
|------|-----------|
| `backend/app/config.py` | SECRET_KEY required, BOT_SECRET required, GIGACHAT_CA_BUNDLE, startup guards |
| `backend/app/api/bookmarks.py` | IDOR fix (user_id в WHERE, 404), API versioning /api/v1/ |
| `backend/app/api/search.py` | ca_bundle pass-through, API versioning |
| `backend/app/api/folders.py` | API versioning |
| `backend/app/api/users.py` | API versioning |
| `backend/app/services/ai_classifier.py` | ca_bundle param, verify=False conditional |
| `backend/app/services/embeddings.py` | ca_bundle param, verify=False conditional |
| `backend/app/services/search.py` | LIKE escape + ESCAPE clause |
| `backend/app/services/bookmark_processor.py` | Batch tag upsert, bookmarks_count first-time only |
| `backend/app/worker.py` | ca_bundle, flush fix, retry_partial_embeddings cron |
| `backend/app/models.py` | embedding_retry_count, embedding_last_attempt fields |
| `backend/main.py` | /health with deps, CORS explicit origins |
| `bot/config.py` | BOT_SECRET required + startup guard |
| `bot/api_client.py` | httpx retry/limits, API versioning /api/v1/ |
| `bot/handlers/start.py` | _pending_saves fix, token TTL, InaccessibleMessage guards |
| `bot/handlers/tasks.py` | Rerender lock, pin offset removed, InaccessibleMessage guards |
| `bot/state_store.py` | asyncio.Lock init, atomic Lua bump_last_seen |
| `frontend/src/lib/api.ts` | API versioning /api/v1/ |
| `migrations/versions/c3d4e5f6a7b8_...py` | NEW — embedding retry fields |

---

## Phase 1: Silent Mode — DONE

**Реализация: 2 новых файла, 7 изменённых, ~250 строк.**

### Что сделано

| Файл | Изменение |
|------|-----------|
| `bot/utils.py` | **NEW** — safe_react(), safe_remove_reaction(), ephemeral_error(), _delete_after() |
| `bot/handlers/settings.py` | **NEW** — /silent toggle, is_silent() с кэшем 5 мин |
| `bot/handlers/start.py` | handle_text/forward/media/cb_save_confirm — ветвление silent/verbose |
| `bot/main.py` | Регистрация settings router, /silent в командах бота |
| `bot/api_client.py` | get_me(), update_settings(), silent param в create_bookmark() |
| `backend/app/schemas.py` | silent: bool = False в BookmarkCreate |
| `backend/app/api/bookmarks.py` | Передача data.silent в enqueue_job worker |
| `backend/app/worker.py` | _set_reaction(), _send_ephemeral(), ветвление в process_bookmark_task |
| `bot/handlers/tasks.py` | /silent в HELP_TEXT |

### Архитектура Silent Mode

```
Silent (дефолт):
  Юзер → сообщение → бот ставит 👀 → worker обрабатывает → worker ставит 👍
  
  Ошибка: бот ставит 👎 + ephemeral сообщение (10с автоудаление)
  Task list: 👀 убирается → отправляется интерактивное сообщение + пин

Verbose (opt-in):
  Юзер → сообщение → бот: "⏳ Обрабатываю..." → worker: "✅ Готово! Категория: X"
```

### Ключевые решения
- Silent по умолчанию для ВСЕХ юзеров (User.settings.silent_mode default True)
- Настройка в JSONB — миграция не нужна
- Кэш is_silent() на 5 мин (in-memory dict), инвалидируется при /silent toggle
- _send_ephemeral: два отдельных httpx клиента (send + sleep + delete), не держим TCP
- Task list = исключение из silent: убирает 👀, отправляет интерактивное сообщение
- Короткие сообщения (<15 символов): подтверждение "Сохранить?" работает в обоих режимах
- /reprocess: всегда verbose (known limitation, не критично)

### Code review fixes
- cb_save_confirm: добавлен ephemeral_error при ошибке в silent mode
- Task list: добавлен _set_reaction(None) для очистки 👀 перед отправкой списка
- _send_ephemeral: разделён на два httpx клиента (не держим соединение 10с)

---

## Roadmap статус

```
Phase 0: Hardening (8-10 дней) ← DONE
Phase 1: Silent Mode (3-4 дня) ← DONE
Phase 2: Learning Mechanisms (5-7 дней) ← NEXT
Phase 3: Multi-format (7-10 дней)
Phase 4: Smart Blocks MVP (10-14 дней)
Phase 5: Proactivity 1.0 (8-12 дней)
Phase 6: Proactivity 2.0 research (3-5 дней)
```
