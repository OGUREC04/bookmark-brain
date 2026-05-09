# BookmarkBrain — Roadmap (обновлён 2026-05-08)

## Статус проекта

**Готово:** Phase 0-1.5 (Hardening, Silent Mode, Dedup, Stale Nudge), Phase 3A (Voice), Phase 3B (Documents), Phase 3D (Voice Features), Deploy (VPS Beget Cloud).

**В проде:** бот работает на VPS 5.181.109.142, Docker Compose, GigaChat + Voyage AI + Yandex SpeechKit.

**Регламент разработки:** покрыт правилами в `~/.claude/rules/common/` (development-workflow, code-review, security, testing, git-workflow, docs-with-code) + хуком `enforce-review.py` который блокирует `git commit` без security-reviewer на security-sensitive коде. Отдельная фаза R1 не нужна.

---

## Приоритеты (порядок выполнения)

```
Phase R0: Project-specific правило      ✅ DONE (2026-05-08)
Phase R2: Документация продукта         ⏳ почти DONE (API docs остались)
Phase 2:  Onboarding                    ✅ DONE (2026-05-09)
Phase 2.5: Reminders MVP                ← СЛЕДУЮЩИЙ (3-5 дней)
Phase 3C: Photo OCR                     (2-3 дня)
Phase 4:  Learning Mechanisms           (5-7 дней)
Phase 4.5: LLM Migration                (2-3 дня)
Phase 5:  Smart Blocks MVP              (10-14 дней)
Phase 6:  Proactivity 1.0               (8-12 дней)
Phase 7:  Proactivity 2.0 Research      (3-5 дней)
Phase L:  Программа обучения            (параллельно, после R2)

Бэклог:   Улучшения окружения и хуки    (см. секцию "Бэклог" ниже)
```

---

## ВЫПОЛНЕНО

### Phase 0 — Hardening & Foundation ✅
- Все CRITICAL/HIGH исправлены (SECRET_KEY, BOT_SECRET, verify=False, IDOR, N+1)
- API versioning /api/v1/, /health, embedding retry cron, CORS

### Phase 1 — Silent Mode ✅
- Reaction-based receipts (👀→👍/👎), /silent toggle
- Task lists: silent rendering, reply-инструкция, мета-команды
- Deadline extraction, onboarding, /clean защита task lists

### Phase 1.5A — Task List Dedup-Alert ✅
- Cosine similarity dedup, merge API, bot callbacks

### Phase 1.5B — Stale List Nudge ✅
- Worker cron, reply-based UX, transfer undone tasks

### Phase 1.5C — General Semantic Dedup ✅
- Двухуровневый dedup (embedding + text overlap), NL edit fast-path

### Phase 3A — Voice Input ✅
- WhisperSTT (OpenAI/Groq), voice/video_note/audio handlers
- Migration: transcription, media_duration, media_file_id

### Phase 3B — Documents ✅
- PDF/DOCX/TXT/MD extraction, document_page_count migration

### Phase 3D — Voice Features ✅
- Intent detection (todo/search/note), auto-tag #voice, timestamps

### Deploy — Частично ✅
- VPS Beget Cloud, Docker Compose prod, CI (test.yml)
- Yandex SpeechKit вместо Groq (заблокирован из РФ)
- CD pipeline настроен, но GitHub Secrets не добавлены

---

## Phase R0: Project-specific правило + человеко-читаемый гайд (2-3 часа) ← СЛЕДУЮЩИЙ

**Цель:** Зафиксировать BookmarkBrain-специфику которая НЕ покрыта generic правилами Claude.

**Зачем:** Глобальные правила в `~/.claude/rules/common/` уже покрывают git-flow, тесты, security, code review, документацию. Хук `enforce-review.py` блокирует коммит без security-reviewer. Не хватает только проектной специфики и человеко-читаемого гайда для тебя.

### Что уже покрыто (НЕ делать)
- ✅ TDD workflow → `common/testing.md` + `tdd-guide` агент
- ✅ Git-flow и формат коммитов → `common/git-workflow.md`
- ✅ Security checklist → `common/security.md`
- ✅ Code review триггеры → `common/code-review.md` + хук `enforce-review.py`
- ✅ Doc-with-code → `common/docs-with-code.md`
- ✅ Dev workflow (Research → Plan → TDD → Review → Commit) → `common/development-workflow.md`

### Что делать

#### 1. Правило для Claude (1 час)
- [x] `.claude/rules/bookmark-brain.md` — ТОЛЬКО проектная специфика:
  - Dev-бот @bookmarkbrain_dev_bot vs prod @N0teeBot — никогда не путать токены
  - Перед коммитом с .env — проверить что нет реальных ключей (Yandex/GigaChat/Voyage)
  - При изменении схемы БД — `alembic revision --autogenerate` + ручная проверка
  - При деплое: `pytest` локально → ручной тест через dev-бота → `git push` → `git pull && ./deploy.sh` на VPS → `docker compose logs bot --tail 20`
  - Russian API constraints — не предлагать Groq/OpenAI для прода
  - GigaChat embeddings 402 — embeddings только через Voyage AI

#### 2. Человеко-читаемый гайд (1-2 часа)
- [x] `docs/DEVELOPMENT-GUIDE.md` (на русском) — для тебя:
  - Как запустить локально (ссылка на `start.bat`)
  - Как создать ветку и PR (5 строк, не лекция)
  - Как деплоить (одна команда)
  - Что проверить перед коммитом (чеклист 5 пунктов)
  - Откат если сломалось

**Depends on:** Ничего.

---

## Phase R2: Документация продукта (3-5 дней)

**Цель:** Задокументировать что есть, зачем, и как работает. Чтобы через месяц не гадать.

**Не путать с регламентом:** регламент = «как разрабатывать» (покрыт правилами + хуком). Здесь = «что построено и почему».

### Спецификация продукта
- [x] `docs/SPEC.md` — что продукт делает, для кого, какие фичи
- [x] User stories: основные сценарии использования
- [x] Границы продукта: что НЕ делает BookmarkBrain

### Архитектурная документация
- [x] `docs/ARCHITECTURE.md` — компоненты, связи, схема
- [x] Диаграмма: Bot → Backend → Worker → AI providers
- [x] Data flow: сообщение → classify → embed → tag → dedup
- [x] Database schema diagram

### Каталог решений (ADR)
- [x] `docs/decisions/` — Architecture Decision Records
- [x] Почему GigaChat (доступен в РФ, бесплатный tier)
- [x] Почему Yandex SpeechKit (Groq заблокирован из РФ)
- [x] Почему arq а не Celery (легковесный, async-native)
- [x] Почему pgvector а не FAISS (единая БД, проще деплой)
- [x] Почему Voyage AI (GigaChat embeddings 402 на бесплатном тарифе)

### API-документация
- [ ] Привести в порядок FastAPI `/docs` (описания, примеры) — нужна правка кода в `backend/`, отложено до окна без параллельных фич
- [x] Документировать bot commands (/start, /list, /search, /silent, /stats) → `docs/BOT-COMMANDS.md`
- [x] API-обзор для людей → `docs/API.md` (Swagger на `/docs` остаётся источником схем)

**Depends on:** Phase R0 (project-specific правило)

---

## Phase 2: Onboarding ✅ DONE (2026-05-09)

**Цель:** Новый пользователь понимает что делать без инструкций.

- [x] Приветственное сообщение при первом /start (с примерами) — split new vs returning user
- [x] Первое сохранение — подсказка про forward / голос / /list / /search (4 точки: text, forward, media, short)
- [x] Первый task list — подсказка про reply-команды (worker → ephemeral 60s)
- [x] Первое голосовое — подсказка про intent / таймкоды / #voice
- [x] `/help` с актуальным списком возможностей

**Реализация:**
- `bot/onboarding.py` — утилита `maybe_show_tip` + cache (TTL 5 мин, batch-eviction при > 5000 записей)
- State в `user.settings` JSONB через PATCH /users/me/settings (плоские ключи: `onboarding_welcomed`, `onboarding_first_save`, `onboarding_first_task_list`, `onboarding_first_voice`)
- Race-protection: оптимистичное обновление кэша до `message.answer`
- Worker → подсказка task_list через `_send_ephemeral` (flush до отправки, чтобы не показывать снова при ошибке БД)
- Code-review: 0 CRITICAL/HIGH, 3 MEDIUM зафиксированы и устранены

**Depends on:** Phase R2 (спецификация определяет что показывать) — выполнено параллельно

---

## Phase 2.5: Reminders MVP (3-5 дней) ← СЛЕДУЮЩИЙ

**📄 PRD:** [docs/prd/REMINDERS-MVP.md](prd/REMINDERS-MVP.md) — детальная спецификация с UX, schema, edge cases, success metrics.

**Цель:** Бот замечает сообщения с временными маркерами или намерением «нужно сделать» и предлагает напоминание одной кнопкой.

### Зачем

Пользователь часто пишет себе:
- «До 15 мая нужно подать на мат помощь»
- «Поискать на праздниках кто задротит ОС»
- «Нужно сделать фичу с напоминаниями»

Сейчас это просто сохраняется в закладки и тонет. Хочется чтобы бот замечал намерение и предлагал «напомнить завтра?» — одной кнопкой, без явных команд.

### User stories

1. Юзер пишет сообщение с намерением → бот сохраняет как закладку **+ предлагает «🔔 Напомнить завтра?»** одной inline-кнопкой
2. Если в сообщении есть явная дата («до 15 мая», «в пятницу», «на праздниках») → бот предлагает напомнить **за день до даты**
3. Подсказка под кнопкой: «или ответь reply: завтра в 9, через час, в субботу...»
4. Юзер reply на закладку с reminder-фразой → парсим NL-дату → создаём reminder
5. В назначенное время — бот шлёт сообщение с текстом закладки и кнопкой «✅ Выполнено / 💤 Отложить»

### Технические задачи

#### Backend
- [ ] Миграция: таблица `reminders` (id, user_id, bookmark_id, fire_at, status: pending/sent/done/cancelled, created_at)
- [ ] CRUD API: `POST /api/v1/reminders/`, `PATCH /id`, `DELETE /id`, `GET /upcoming`
- [ ] Сервис: `IntentDetector.detect_reminder_intent(text)` — паттерны «нужно», «надо», «до X», «к X», «не забыть» + явные даты
- [ ] Сервис: `parse_natural_date(text, now=...)` — «завтра в 9», «в пятницу», «через час», «на праздниках» (next weekend), «15 мая»
- [ ] Worker cron: проверка `fire_at <= now()` каждую минуту → отправка сообщения юзеру → `status=sent`

#### Bot
- [ ] При создании bookmark — если intent «reminder» детектится → добавить inline-кнопку `🔔 Напомнить завтра?`
- [ ] Callback `rem:{bid}:tomorrow|hour|saturday` → создать reminder, обновить сообщение
- [ ] Reply-handler на bookmark с фразой типа «через час», «в субботу» → `parse_natural_date` → создать reminder
- [ ] При срабатывании reminder — кнопки `✅ Выполнено` / `💤 +1 день` / `💤 +неделя`

### Открытые вопросы (обсудить перед стартом)

- **Глубина detection:** только явные маркеры («до X»), или ML-классификатор намерения? MVP — паттерны + явные даты, ML — позже (Phase 4 Learning Mechanisms).
- **Часовой пояс:** хранить fire_at в UTC, отображать пользователю в его TZ. Откуда брать TZ — настройка `/tz` или из Telegram language? MVP — захардкодить MSK (UTC+3), потом /tz.
- **Если юзер ничего не нажал** — оставить кнопку или удалить через TTL? MVP — оставить inline-кнопку постоянно, юзер сам решает.

**Depends on:** ничего блокирующего. Зависит от того, что Phase 2 (Onboarding) задал паттерн «бот замечает и предлагает» — продолжаем в том же духе.

---

## Phase 3C: Photo OCR (2-3 дня)

**Цель:** Фото → текст → AI pipeline.

- [ ] OCR service (Tesseract или Yandex Vision)
- [ ] Bot: download photo, OCR, feed to pipeline
- [ ] Учитывать что Yandex Vision работает из РФ (Tesseract — self-hosted)

**Depends on:** Phase 3B (Documents — аналогичный паттерн)

---

## Phase 4: Learning Mechanisms (5-7 дней)

**Цель:** Система учится на поведении пользователя.

### 4A. Classification feedback (day 1-3)
- [ ] Inline "неправильная категория" кнопка
- [ ] `POST /api/v1/bookmarks/{id}/feedback`
- [ ] Few-shot selector: топ-3 примера в prompt классификатора

### 4B. Usage decay (day 3-4)
- [ ] Decay coefficient в поиске по `last_accessed`
- [ ] Track clicked_id в search_traces

### 4C. Tag co-occurrence (day 5-6)
- [ ] Materialized view `tag_cooccurrence`
- [ ] Nightly refresh, inject в classifier prompt

**Depends on:** Phase 0D (search_traces, feedback tables)

---

## Phase 4.5: LLM Provider Migration (2-3 дня)

**Цель:** DeepSeek для NL-операций (стабильный JSON).

- [ ] `AI_PROVIDER=deepseek` для классификации
- [ ] Fallback chain: DeepSeek → GigaChat
- [ ] Сравнение качества на 20 тестовых фразах
- [ ] **Проверить доступность DeepSeek из РФ** (аналог проблемы с Groq)

**Depends on:** Phase 4

---

## Phase 5: Smart Blocks MVP (10-14 дней)

**Цель:** Умные коллекции = папка + AI-поведение + авто-роутинг.

- [ ] `smart_blocks` таблица, CRUD API
- [ ] `BlockRouter` — автоматическая маршрутизация после классификации
- [ ] 5 шаблонов: Goals, Ideas, Read Later, Do Someday, Insights
- [ ] Bot: `/blocks`, `/blocks setup`

**Depends on:** Phase 4 (feedback для routing)

---

## Phase 6: Proactivity 1.0 (8-12 дней)

**Цель:** Мозг напоминает. Связи, surfacing, дайджесты.

- [ ] Auto-connections (top-3 by cosine similarity)
- [ ] Contextual surfacing (>0.85 similarity alert)
- [ ] Periodic digest (weekly, decay-based)
- [ ] Goal coaching (item_type=goal)

**Depends on:** Phase 4 (decay), Phase 5 (blocks)

---

## Phase 7: Proactivity 2.0 — Research Only (3-5 дней)

- [ ] Agent action catalog
- [ ] Prototype: Google Calendar, Telegram reminders
- [ ] Architecture: tool-calling pipeline with approval

**Depends on:** Phase 6, user base 100+

---

## Идеи (не в плане, требуют дизайна)

### Phase 5.5 — Session Mode
Серия коротких заметок во время рабочей сессии → один конспект.
`/session start/end`, автодетект, суммаризация.

### Phase 5.6 — Proactive Call Mode
Google Calendar API → детект звонка → связать заметки с событием.
Post-call transcript enrichment.

### Phase 5.7 — Daily Digest & Chat History
`/day` — статистика дня. Mini App: история с пометками "сохранено".
Post-factum сохранение несохранённых.

---

## Phase L: Программа обучения (параллельно, после R2)

**Цель:** Обучить владельца проекта основам разработки на живом примере BookmarkBrain.

**Формат:** Модули по темам, каждый на примере реального кода проекта. Не абстрактные туториалы — а "вот наш файл, вот что каждая строчка делает".

### Модули

#### L1. Git и командная работа
- Что такое коммит, ветка, PR — на примере наших PR (#1, #2, #3)
- Как читать `git log`, `git diff`
- Когда создавать ветку, когда можно в main

#### L2. Docker и деплой
- Что такое контейнер — на примере нашего `docker-compose.prod.yml`
- Что делает каждый сервис (postgres, redis, backend, worker, bot)
- Как работает `deploy.sh`, что значит "здоровый контейнер"

#### L3. API и бэкенд
- Что такое REST API — на примере нашего `/api/v1/bookmarks/`
- Как работает авторизация (JWT, bot secret)
- Как добавить новый endpoint (практическое задание)

#### L4. База данных
- Что такое миграция — на примере Alembic
- Как устроена наша схема (bookmarks, tags, users)
- SQL basics: SELECT, INSERT, JOIN — на примере наших данных

#### L5. AI-интеграции
- Как работает классификация (GigaChat API)
- Что такое embedding и semantic search
- Как работает STT (Yandex SpeechKit)

#### L6. Безопасность
- Что такое SQL-инъекция, XSS, IDOR — на примере наших фиксов из Phase 0
- Почему секреты в .env а не в коде
- Как проверять безопасность (чеклист из `~/.claude/rules/common/security.md` + хук `enforce-review.py`)

#### L7. Тестирование
- Что такое unit test — на примере наших `test_stt_providers.py`
- Зачем моки (mock) — на примере тестов бота
- Как запускать тесты, читать результаты

**Формат доставки:** `docs/learning/` — по одному .md файлу на модуль. Практические задания в конце каждого.

**Depends on:** Phase R2 (спецификация даёт контекст для обучения)

---

## Deploy — Оставшиеся задачи

- [ ] GitHub Secrets для CD (VPS_HOST, VPS_USER, VPS_SSH_KEY)
- [ ] Сменить пароль VPS (был в чате)
- [ ] Postgres backup cron (pg_dump → локально)
- [ ] Error alerting (Telegram notification on crash)
- [ ] Обновить .env на VPS (Yandex STT ключи)

---

## Бэклог (улучшения окружения и процесса)

Не привязано к фазам. Брать когда заболит или появится время.

### Окружение разработчика
- [ ] **Makefile** — короткие команды: `make test` / `make deploy` / `make logs` / `make migrate` (вместо длинных ssh+docker)
- [ ] **scripts/seed-dev-db.py** — засеивает локальную БД 10-20 фейковыми закладками для тестов
- [ ] **scripts/check-env-sync.sh** — сверяет что все vars из `bot/config.py` и `backend/app/config.py` есть в `.env.production.example`
- [ ] **VS Code launch.json** — конфиги для дебага бота / бэкенда / воркера (если используется VS Code)
- [ ] **direnv** — авто-подгрузка `.env` при cd в проект (опционально)
- [ ] **Sentry / error tracking** — когда появятся реальные юзеры
- [ ] **pre-commit framework** (black, ruff, mypy) — если pytest в CI станет недостаточно

### Хуки (после реализации зависимостей)
- [ ] **check-spec-staleness.py** — варнит если 10+ коммитов или 14+ дней без обновления `SPEC.md`/`ARCHITECTURE.md` (после Phase R2)
- [ ] **check-adr.py** — напоминает создать ADR в `docs/decisions/` при добавлении новой зависимости или AI-провайдера (после Phase R2)
- [ ] **check-env-sync.py** — при изменении `config.py` напоминает обновить `.env.production.example` и `memory/deployment.md`
- [ ] **check-migration.py** — варнит если в коммите новая миграция в `alembic/versions/`, но `alembic upgrade head` локально не запускался

### Правила (.claude/rules/bookmark-brain.md, добавить в Phase R0)
- [ ] **env-var lifecycle** — новая переменная одновременно в `config.py` + `.env.production.example` + `memory/deployment.md` + (если на VPS) задача в Deploy секции
- [ ] **migration safety** — `alembic revision` → ручная проверка SQL → тест rollback (`alembic downgrade -1; alembic upgrade head`) перед коммитом
- [ ] **API contract** — изменение `/api/v1/` endpoint → проверить bot/handlers что не сломается
- [ ] **provider fallback** — новый AI-провайдер только через `BaseClassifier`/`BaseEmbeddingService`, не привязываться к конкретному

### Сделано из бэклога
- [x] **check-secrets.py хук** — блокирует `git commit` если в staged файлах найдены реальные API-ключи (2026-05-08)

---

## Известные решения (для контекста)

- GigaChat SDK не работает — используем httpx напрямую с OAuth
- GigaChat embeddings 402 на бесплатном тарифе — используем Voyage AI
- Groq/OpenAI заблокированы из РФ — используем Yandex SpeechKit
- arq CLI ломается на Python 3.14 — используем run_worker.py с asyncio.run()
- Bot Settings: extra="ignore" чтобы не падать от лишних переменных
- Backend Settings: extra="ignore" (добавлено для Yandex переменных)
- Yandex Cloud: нужен платёжный аккаунт + clouds.member на уровне облака
