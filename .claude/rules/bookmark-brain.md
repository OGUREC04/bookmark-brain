# BookmarkBrain — Project-Specific Rules

Generic best practices (TDD, code review, security, git-flow) → `~/.claude/rules/common/`.
Здесь — только то, что специфично для **этого** проекта и легко забывается.

---

## 1. Два бота: dev и prod — НЕ путать

| | Dev | Prod |
|---|---|---|
| Username | `@bookmarkbrain_dev_bot` | `@N0teeBot` |
| Token | local `D:\projects\bookmark-brain\.env` | VPS `~/bookmark-brain/.env` |
| База/Redis | local Docker | VPS Docker |
| Когда юзать | Любая разработка, тесты STT/handlers | Только реальные пользователи |

**Правило:** при просьбе «протестируй на боте» — **всегда dev-бот**, никогда не запускать локально с prod-токеном (сломает прод: `TelegramConflictError`, getUpdates конфликт).

При деплое: `git push` → `ssh user@5.181.109.142` → `cd bookmark-brain && git pull && ./deploy.sh` → `docker compose -f docker-compose.prod.yml logs bot --tail 30`.
**Не запускать `deploy.sh` или `docker compose` локально** — они для VPS.

---

## 2. Env-var lifecycle (САМАЯ ЧАСТАЯ ОШИБКА)

При добавлении новой переменной окружения — **одновременно**, в одном PR:

1. `backend/app/config.py` или `bot/config.py` (или оба) — поле в `Settings` с дефолтом
2. `.env.production.example` — переменная с placeholder-значением (`your-key-here`)
3. `D:\projects\bookmark-brain\memory\deployment.md` — что переменная делает, откуда брать значение
4. Если переменная нужна на VPS — добавить пункт в секцию **Deploy → Оставшиеся задачи** в `docs/ROADMAP-2026-05.md`: «Обновить .env на VPS (XXX)»

Оба `Settings`-класса используют `extra="ignore"` — это намеренно, не убирать. Бот и бэк делят один `.env` в корне проекта; без `extra="ignore"` они падают друг на друге.

`get_settings()` обёрнут в `@lru_cache` — после правки `.env` локально нужен **перезапуск процесса**, не «hot reload».

---

## 3. AI-провайдеры — только через абстракцию

Никогда не вызывать `httpx.AsyncClient()` к GigaChat/Voyage/Yandex напрямую из handler/endpoint. Только через фабрики:

| Что | Файл | Фабрика | Env var |
|---|---|---|---|
| Классификация | `backend/app/services/ai_classifier.py` | `create_classifier(provider, ...)` | `AI_PROVIDER` |
| Embeddings | `backend/app/services/embeddings.py` | `create_embedding_service(provider, ...)` | `EMBEDDING_PROVIDER` |
| STT | `bot/services/stt.py` | `create_stt_service(provider, ...)` | `STT_PROVIDER` |

Новый провайдер — отдельный класс наследник `BaseClassifier` / `BaseEmbeddingService`, плюс ветка в фабрике. Не «прокидывать httpx в worker».

**Russian hosting constraints (не предлагать для prod):**
- ❌ Groq, OpenAI — заблокированы из РФ (403)
- ❌ DeepSeek — **проверить** перед использованием в prod (Phase 4.5 имеет это пунктом)
- ✅ GigaChat (Sber), Voyage AI, Yandex SpeechKit — работают из РФ

**Известные тупики (не пытаться):**
- GigaChat **SDK** не работает (401) → используем `httpx` напрямую с OAuth
- GigaChat **embeddings** возвращают 402 на бесплатном тарифе → embeddings только через Voyage AI
- arq **CLI** падает на Python 3.14 (`get_event_loop` deprecated) → запуск через `backend/run_worker.py` с `asyncio.run()`, **не** `arq worker app.worker.WorkerSettings`
- Yandex SpeechKit без активного **billing account** → 401 даже с правильными ролями

---

## 4. Миграции (alembic) — рабочая директория

Alembic ini лежит в `backend/alembic.ini`. Команды запускать **из `backend/` директории**:

```bash
cd backend
python -m alembic revision --autogenerate -m "add_xxx"
python -m alembic upgrade head
python -m alembic downgrade -1   # rollback test
```

**Перед коммитом миграции:**
1. Прочитать сгенерированный SQL — alembic иногда придумывает лишнее
2. Применить вверх: `alembic upgrade head`
3. Откатить и снова вверх: `alembic downgrade -1; alembic upgrade head` — проверка что миграция reversible
4. Если миграция меняет существующую колонку с данными — write migration вручную, не autogenerate

В **prod** миграции применяются автоматически: сервис `migrations` в `docker-compose.prod.yml` (контейнер `bb_migrations`) выполняет `alembic upgrade head` через `depends_on: condition: service_completed_successfully` перед запуском backend/worker. Деплой → миграции сами накатятся.

**Embedding dim фиксирована = 1024** в pgvector. Поменять модель embedding с другой dim — нельзя без пересоздания колонки `bookmarks.embedding` и переиндексации всех записей. Смена провайдера embedding = миграция + бэкфилл.

---

## 5. IDOR-проверка на каждом endpoint

Все endpoints `/api/v1/bookmarks/*` обязаны проверять `user_id == current_user.id` в WHERE. Это было одной из CRITICAL-уязвимостей Phase 0.

**При добавлении нового endpoint** (GET/PATCH/DELETE по id):
- В query явно `WHERE bookmarks.user_id == current_user.id`
- Тест с двумя пользователями: user A не может прочитать/изменить bookmark user B
- Если endpoint админский — explicit role check

`security-reviewer` агент обязателен на любом изменении `backend/app/api/` (общее правило `code-review.md` это уже требует — здесь напоминание потому что у нас были баги).

---

## 6. structured_data JSONB — хрупкая схема

`bookmarks.structured_data` — JSONB без строгой схемы. Task list определяется как `structured_data.get("type") == "task_list"`.

**При изменении формата структуры** (добавил поле, переименовал) — обновить **одновременно**:
- `backend/app/services/task_list_renderer.py`
- `backend/app/services/task_list_editor.py`
- `backend/app/services/dedup_checker.py`
- Cron `stale_list_nudge` в `backend/app/worker.py`

Иначе старые task lists в БД сломаются на render/edit. Дополнительно — миграция-бэкфилл если меняется существующее поле.

---

## 7. Redis-ключи — общая схема между bot и worker

`bot/state_store.py` — каноничные ключи. Worker иногда пишет в Redis напрямую, дублируя часть.
**При добавлении нового Redis-ключа:**

1. Добавить метод в `StateStore` (не «голый» `redis.set`)
2. Если worker тоже пишет — использовать тот же `StateStore`, не своё
3. Закомментировать TTL и формат значения в docstring метода
4. Ключ-схема (на 2026-05): `task_list_msg:`, `bot_msgs:`, `bot_msgs_pinned:`, `dedup_alert:`, `general_dedup:`, `pending_dedup:`, `nudge:`, `nudged:`. Менять формат существующих ключей — миграция Redis (или TTL-инвалидация).

---

## 8. Бот: parse_mode и кириллица

При отправке plain-text ответа из бота — **`parse_mode=None`**. Иначе кириллица в `<угловых скобках>` ловит HTML parse error («unsupported tag `<слово>`»).

Если действительно нужен Markdown/HTML — экранировать через `aiogram.utils.markdown.text` или `html.escape`.

---

## 9. Локальный venv — не в OneDrive

Venv лежит в `%LOCALAPPDATA%\bookmark-brain\venv`, **не** в папке проекта. Причина: проект в OneDrive, Files On-Demand скрывал пакеты от Python. Не предлагать `python -m venv .venv` в корне проекта.

Установка зависимостей: `start.bat` делает это сам. Если вручную — `%LOCALAPPDATA%\bookmark-brain\venv\Scripts\activate`.

`pip install -r requirements.txt` на Python 3.14 может частично провалиться (`pydantic-core`, `asyncpg` без cp314 wheels). Пакеты уже установлены в user site-packages из предыдущих попыток. Прежде чем переустанавливать — проверить `python -c "import pydantic_core, asyncpg"`.

---

## 10. Бот — single instance

Только один процесс с `TELEGRAM_BOT_TOKEN` одного бота может быть запущен. Иначе `TelegramConflictError: Conflict: terminated by other getUpdates request`.

Перед запуском локального бота: `taskkill /F /IM python.exe` → подождать 10–12 секунд → `start.bat` (или вручную `python bot/main.py`).

---

## 11. Чеклист перед коммитом (project-specific дополнение к common/security.md)

В `~/.claude/rules/common/security.md` уже есть generic security checklist + хук `check-secrets.py` блокирует утечку API-ключей. Здесь — **только специфичное для этого проекта**:

- [ ] Если меняли `bot/config.py` или `backend/app/config.py` → обновили `.env.production.example` и `memory/deployment.md`
- [ ] Если есть новая alembic-миграция → запустили `downgrade -1; upgrade head` локально
- [ ] Если меняли `/api/v1/` endpoint → проверили что `bot/api_client.py` всё ещё совместим
- [ ] Если меняли `structured_data` формат → обновили все 4 потребителя (renderer/editor/dedup/cron)
- [ ] Если новый AI-провайдер → реализован через `Base*` абстракцию + фабрика, провайдер доступен из РФ
- [ ] Если меняли Redis-ключи → схема в `state_store.py` обновлена

---

## 12. Тесты — текущее состояние и цель

На 2026-05 в проекте есть `tests/test_stt_providers.py` (~17 тестов), `tests/test_media_edge_cases.py`. Это всё. Generic правило `~/.claude/rules/common/testing.md` требует 80% покрытия — реальность сильно ниже.

**Прагматичный режим до Phase 4:**
- Любая **новая** функция в `services/` или handler с нетривиальной логикой — с unit-тестом (моки `respx` для httpx)
- Не требовать ретроактивные тесты на старый код в существующих PR
- Каждый PR не должен **уменьшать** покрытие
- Phase 4 (Learning Mechanisms) — серьёзная фича, перед ней довести покрытие services до 60%+

---

## 13. Архитектурные развилки — выносить наружу

См. `~/.claude/rules/common/surface-architecture-forks.md` — обязательное правило.

**Реальный кейс этого проекта:** Yandex SpeechKit имеет sync (30 сек) и async (до 4 часов) API. Я молча реализовал только sync — спустя время это привело к регрессии Phase 3D (таймкоды для длинных записей). Не повторять.

**Типичные развилки в этом проекте**, на которых надо останавливаться и спрашивать:
- Новый AI-провайдер: какую модель брать? (стоимость, качество, доступность из РФ)
- Sync vs async (Yandex STT, в будущем Yandex Vision OCR — у Vision тоже два API)
- Inline в боте vs background через arq worker (зависит от latency и риска заморозки)
- Миграция со схемой: in-place ALTER vs новая колонка + backfill
- Кэш в Redis vs кэш в памяти процесса (масштабируемость vs latency)

---

## 14. Источники истины

- `D:\projects\bookmark-brain\docs\ROADMAP-2026-05.md` — текущий план + бэклог
- `D:\projects\bookmark-brain\docs\TROUBLESHOOTING.md` — known issues
- `D:\projects\bookmark-brain\.claude\STARTUP.md` — canonical startup
- `D:\projects\bookmark-brain\memory\deployment.md` — VPS, токены, env vars
- `D:\projects\bookmark-brain\memory\project_status.md` — что готово
- `D:\projects\bookmark-brain\docs\SPEC.md` / `ARCHITECTURE.md` / `decisions/` — продукт и решения

При противоречии между этим правилом и ROADMAP → ROADMAP свежее, обновить правило.
