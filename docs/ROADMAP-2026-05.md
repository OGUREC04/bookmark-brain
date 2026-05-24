# BookmarkBrain — Roadmap (обновлён 2026-05-09)

## Статус проекта

**В проде:** бот работает на VPS Beget Cloud (5.181.109.142), Docker Compose, GigaChat + Voyage AI + Yandex SpeechKit (sync). Async STT настроен локально, на VPS не задеплоен.

**Готово к запуску на реальных юзерах:** ❌ нет. Не хватает Smart Blocks + Mini App.

**Следующее действие (новый порядок, 2026-05-14):**
1. **Bugfix базовых функций** — другой чат (классификация / dedup / task lists / reminders)
2. **Mini App MVP** — этот чат, параллельно
3. **Phase 5 Smart Spaces** — отложен ПОСЛЕ Mini App. PRD готов: `docs/prd/SMART-SPACES-MVP.md`

Причина переноса: в юзер-тесте всплыло много багов в core flow. Smart Spaces поверх неустойчивой базы = усиление проблем. PRD сохраняет весь контекст брейншторма для возврата к фазе.

---

## Замечание про сроки

Старые оценки в roadmap были «соло-разработчик без AI». Реальные сроки с AI-парой ~×5 быстрее (Phase 1 = 1 день вместо 7, Phase 2 = 1 день вместо 3). В этом документе **сроки пересчитаны под реальность**.

---

## Новый порядок (после переоценки 2026-05-09)

```
СДЕЛАНО:
├─ Phase 0    Hardening              ✅
├─ Phase 1    Silent Mode            ✅
├─ Phase 1.5  Dedup + Stale Nudge    ✅
├─ Phase 2    Onboarding             ✅
├─ Phase 3A   Voice Input            ✅
├─ Phase 3B   Documents              ✅
├─ Phase 3D   Voice Features         ✅
├─ Deploy     VPS Beget              ✅ (sync + async STT с 2026-05-12)
├─ Phase R0   Project rule           ✅
├─ Phase R2   Documentation          ✅ (API docs остались)
└─ Phase 2.5  Reminders MVP          ✅ (PR #10 merged + PR #11 фиксы + ADR 0008)

В РАБОТЕ (параллельно):
├─ Bugfix     base functions         ← другой чат (классификация/dedup/tasks/reminders)
└─ Mini App   доделка UI             ← этот чат

ОЧЕРЕДЬ (новый порядок после пересмотра 2026-05-14):
├─ UI cleanup  Вычистить визуал/UX     ← bd bookmark-brain-ntn, ПЕРЕД след. фазой
├─ User test  Запуск на 5-10 юзеров  ← после Mini App (1-2 недели live)
├─ Phase 5    Smart Spaces (PRD ✅)  ← отложен ПОСЛЕ Mini App (4-7 дней)
├─ Phase 4.5  DeepSeek (если нужно)  ← по фидбеку (0.5 дня)
├─ Phase 4    Learning Mechanisms    ← по реальным данным (1-2 дня)
├─ Phase 6    Proactivity 1.0        ← после данных (3-5 дней)
├─ Phase TG   Telegram Userbot       ← ⚠ ТЕСТОВО ТОЛЬКО НА ДЕВЕ (ресёрч ✅, ~2-3 нед)
└─ Phase 7    Proactivity 2.0 R&D    ← research (2-3 дня)

БЭКЛОГ (без приоритета):
├─ Phase 3C   Photo OCR              (1-2 дня)
├─ Phase 5.5  Session Mode           идея
├─ Phase 5.6  Proactive Call Mode    research
├─ Phase 5.7  Daily Digest           идея
├─ Phase L    Программа обучения     параллельно
└─ Deploy     Оставшиеся задачи      (см. ниже)
```

---

## ВЫПОЛНЕНО

### Phase 0 — Hardening & Foundation ✅
Все CRITICAL/HIGH исправлены. API versioning, /health, embedding retry cron, CORS.

### Phase 1 — Silent Mode ✅
Reaction-based receipts, /silent toggle, task lists с reply-командами, deadline extraction.

### Phase 1.5A — Task List Dedup-Alert ✅
Cosine similarity dedup, merge API, bot callbacks.

### Phase 1.5B — Stale List Nudge ✅
Worker cron, reply-based UX, transfer undone tasks.

### Phase 1.5C — General Semantic Dedup ✅
Двухуровневый dedup (embedding + text overlap), NL edit fast-path.

### Phase 2 — Onboarding ✅
Tip-система с TTL 5 мин, plain settings keys, race-protection через optimistic update.

### Phase 3A — Voice Input ✅
WhisperSTT (OpenAI/Groq) + Yandex SpeechKit. Voice/video_note/audio handlers.

### Phase 3B — Documents ✅
PDF/DOCX/TXT/MD extraction, document_page_count.

### Phase 3D — Voice Features ✅
Intent detection (todo/search/note), auto-tag #voice, timestamps.

### Deploy — Частично ✅
VPS Beget Cloud, Docker Compose prod, CI test.yml. Yandex SpeechKit sync на проде. Async STT локально готов, на VPS НЕ задеплоен (ждёт Phase 2.5).

### Phase R0 — Project rule ✅
`.claude/rules/bookmark-brain.md` + `docs/DEVELOPMENT-GUIDE.md`.

### Phase R2 — Документация ✅
`SPEC.md`, `ARCHITECTURE.md`, `BOT-COMMANDS.md`, `API.md`, 5 ADR в `docs/decisions/`. FastAPI `/docs` — отложено.

### Yandex Cloud Async STT инфра ✅ (2026-05-09)
- Bucket `bookmarkbrain-stt` создан, креды валидны
- ACL: `allUsers READ` для SpeechKit
- Lifecycle: `stt-tmp/* → 1 day`, применён через `tools/setup_yandex_s3_lifecycle.py`
- Sanity-check утилиты: `tools/check_yandex_s3.py`, `tools/check_yandex_acl.py`

---

## ◐ В РАБОТЕ

### Phase 2.5 — Reminders MVP (1-2 дня)

**📄 PRD:** [docs/prd/REMINDERS-MVP.md](prd/REMINDERS-MVP.md)

**Декомпозиция (другой чат):**

| Bead | Задача | Статус |
|---|---|---|
| `09n` | T1: Migration `users.timezone` + `scheduled_messages` | ✅ closed (PR #5) |
| `gv6` | T2: `nl_date.parse()` + tests TDD | ✅ closed (PR #5) |
| `bts` | T3: `ReminderIntentDetector` + integration | ✅ closed (PR #6) |
| `6xo` | T4: CRUD API `reminders.py` + tests | ✅ closed (PR #6) |
| `kky` | T7: Bot command `/tz` | ✅ closed (PR #6) |
| `4bu` | T5: Worker `scheduled_dispatcher` + cron | ✅ closed (PR #7) |
| `jps` | T8: Bot patch — кнопка после save (silent-aware) | ✅ closed (PR #7) |
| `cnu` | T6: Bot handlers `reminders.py` (callbacks + reply) | ✅ closed (PR #8) |
| `rj1` | T9: Onboarding tips + docs + ADR 0006/0007 | open (ready) |
| `y2i` | T10: E2E + code-reviewer + security-reviewer | blocked by T9 |

**Прогресс: 8/10.** Основной flow готов: save → offer → reply со временем → reminder с кнопками Done/Snooze. Остались T9 (docs/ADR) и T10 (e2e + security-reviewer).

**Что делает:** бот замечает intent «нужно сделать к X» → предлагает inline-кнопку «🔔 Напомнить». В назначенное время — сообщение с кнопками `✅ Выполнено / 💤 Отложить`.

---

## ОЧЕРЕДЬ (по новому порядку)

### Phase 5 — Smart Spaces MVP (4-7 дней) ⏸ ОТЛОЖЕН ПОСЛЕ Mini App

**Статус:** PRD v1 готов — `docs/prd/SMART-SPACES-MVP.md`. Брейншторм пройден (4 блока), ресёрч 2 агентов сделан, 7 User Stories + 15 edge cases + декомпозиция T1-T20 зафиксированы. Фаза отложена до завершения bugfix + Mini App.

**Цель:** тематические пространства с auto-routing, типизированным членством и связями. Юзер создаёт «пространство Идеи стартапов», бот сам собирает релевантное + строит связи между пространствами.

**Терминология (финал):** называется **«пространство»** (space) — не «блок», не «коллекция». Bot commands: `/spaces *`.

**Ключевые решения брейншторма (для возврата к фазе):**
- Архитектура 3 слоя: теги (keywords) + папки (отложены) + spaces (главное)
- Membership: D-cascade (LLM-setup → embedding-runtime → LLM-fallback)
- Один primary + N auto/manual + rejected как negative signal
- 5 шаблонов (Goals/Ideas/Read Later/Do Someday/Insights), 2 по дефолту (Goals + Ideas)
- Cross-space surfacing через precomputed auto memberships
- Feedback channel = Mini App (удаление неподходящих) → bot UI без confirm/reject
- ADR 0006: топики в DM не работают, идём через БД-only архитектуру
- Split: 5A connections (1-2д) → 5B core (2-3д) → 5C proactivity (1д)

**Что в backlog от Phase 5:**
- `bookmark-brain-???` — proactive insights / mini-research (Phase 6+, P3)
- Шаблоны >5 (юзер хочет подумать после первого запуска)
- Папки внутри пространства (отложены до user feedback)

**Зависит от:** Phase 2.5 ✅ + Bugfix base ⏳ + Mini App ⏳

**При возврате к фазе:**
1. Прочитать `docs/prd/SMART-SPACES-MVP.md` целиком — там весь контекст
2. **Не запускать брейншторм заново**
3. Пересмотреть только: реальные UX-патерны из Mini App user-test, выбор LLM (GigaChat vs DeepSeek после Phase 4.5)
4. Planner agent → формализовать T1-T20 → bd create
5. Beads с зависимостями
6. TDD: тесты до кода
7. Code-reviewer + security-reviewer на финале
8. Squash merge в main

**Depends on:** Phase 2.5 закрыта (чтобы не конфликтовать в `bot/handlers/`)

---

### Mini App — Доделать UI (2-4 дня)

**Цель:** минимально работающий UI для юзер-теста.

**Что есть:** базовый список закладок (актуальное состояние нужно перепроверить).

**Что нужно для юзер-теста:**
- [ ] Поиск (UI + интеграция с `/api/v1/search`)
- [ ] Просмотр закладки + редактирование (текст, теги)
- [ ] Удаление
- [ ] Фильтр по тегам
- [ ] Фильтр по Smart Blocks (после Phase 5)
- [ ] Базовая статистика (количество, последние)
- [ ] Telegram WebView caching — проверить что hard-close обновляет

**Что НЕ нужно для теста (отложить):**
- Графики и аналитика
- Связи между закладками (Phase 6)
- iOS native app

**Depends on:** Phase 5 (фильтр по Smart Blocks).

---

### User Testing — Запуск на реальных юзерах (1-2 недели live)

**Цель:** собрать реальные паттерны использования и баги до Phase 4.

**Подготовка:**
- [ ] Onboarding flow для новых тестеров (отдельная инструкция «как начать»)
- [ ] Канал для фидбека (отдельный TG-чат / Google Form)
- [ ] Метрики: закладок/день, % auto-route ошибок, retention 3-7-14 день, типы сообщений
- [ ] Бэкап-стратегия (postgres pg_dump cron)
- [ ] Error alerting (Telegram notification on crash)
- [ ] Sentry или аналог

**Кого звать:**
- 5-10 человек, разные паттерны (студенты / IT / контент-мейкеры)
- Кто реально будет использовать, не «попробую разок»

**Что мерять:**
- Сколько закладок сохраняется vs пропускается
- Какие типы сообщений: текст / голос / forward / документ
- Где auto-routing ошибается (на каких темах)
- Какие команды реально используются (`/list`, `/search`, `/blocks`?)
- Часто ли юзают Reminders
- Что бесит (фидбек в свободной форме)

**Depends on:** Phase 5 + Mini App.

---

### Phase 4.5 — DeepSeek migration (0.5 дня, если нужно)

**Цель:** заменить GigaChat на DeepSeek для классификации, если по фидбеку юзеров видно что классификатор тупит.

- [ ] `AI_PROVIDER=deepseek` для классификации
- [ ] Fallback chain: DeepSeek → GigaChat
- [ ] Проверить доступность DeepSeek из РФ
- [ ] Сравнение качества на 20 типичных фразах из юзер-теста

**Условие запуска:** по фидбеку юзеров видно проблемы с safety-фильтром или JSON instability на GigaChat.

**Depends on:** User testing — нужна реальная статистика проблем.

---

### Phase 4 — Learning Mechanisms (1-2 дня)

**Цель:** система учится на поведении пользователя. Делается на **реальных данных** после юзер-теста, не раньше.

#### 4A. Classification feedback (полдня)
- [ ] Inline кнопка «не та категория»
- [ ] `POST /api/v1/bookmarks/{id}/feedback`
- [ ] Few-shot selector: топ-3 примера feedback в prompt классификатора

#### 4B. Usage decay в поиске (полдня)
- [ ] Decay coefficient по `last_accessed`
- [ ] Track clicked_id в `search_traces`
- [ ] A/B на старом vs новом ранкинге

#### 4C. Tag co-occurrence (день)
- [ ] Materialized view `tag_cooccurrence`
- [ ] Nightly refresh
- [ ] Inject в classifier prompt

**Depends on:** User testing (нужна база для обучения).

---

### Phase 6 — Proactivity 1.0 (3-5 дней)

**Цель:** мозг напоминает сам. Связи, surfacing, дайджесты.

- [ ] Auto-connections (top-3 by cosine similarity на save)
- [ ] Contextual surfacing (>0.85 similarity alert при новой закладке)
- [ ] Periodic digest (weekly, decay-based resurfacing старых)
- [ ] Goal coaching (item_type=goal, периодические напоминания)

**Depends on:** Phase 4 (decay), Phase 5 (blocks определяют что surface-ить).

---

### Phase 7 — Proactivity 2.0 R&D (2-3 дня)

**Цель:** research only. Бот делает действия за юзера (Calendar, отправка сообщений).

- [ ] Agent action catalog
- [ ] User interviews — что реально нужно автоматизировать
- [ ] Prototypes: Google Calendar, Telegram reminders
- [ ] Architecture: tool-calling pipeline с approval

**Depends on:** Phase 6, user base 100+.

---

### Phase TG — Telegram Userbot Assistant (R&D, ~2-3 нед) ⚠️ ТЕСТОВО ТОЛЬКО НА ДЕВЕ

> **Статус:** ресёрч ✅ ([docs/research/telegram-userbot-assistant.md](research/telegram-userbot-assistant.md)).
> **На прод НЕ выкатывать** — экспериментальная фича, гоняем только на dev.
> Причина осторожности: userbot нарушает Telegram ToS (риск бана **личного**
> аккаунта) + обработка чужих ПД. До прода — отдельное product+правовое решение.

**Цель:** ассистент на **личном** Telegram-аккаунте (userbot на MTProto/Telethon)
читает твои чаты, делает триаж/дайджест, опц. готовит черновики ответов.
Не Bot API — отдельный процесс, логин твоим номером (session string).

**Это НЕ отдельный проект:** новый userbot-сервис в том же `bookmark-brain`,
переиспользует Redis / arq-воркеры / Postgres / существующего @бота как «пульт».
Userbot = «уши» (читает чаты), @bot = «лицо» (шлёт тебе дайджест/черновики).

**Фазировка (строго по нарастанию риска):**
- **TG-1 — read-only триаж/дайджест (низкий риск, ~1 нед):** слушатель →
  Redis → воркер → LLM-суммаризация → дайджест тебе в @бот. Никому ничего не
  шлётся. Проверяет ценность.
- **TG-2 — draft-for-approval (~1 нед):** LLM готовит черновик → ты жмёшь
  «Отправить» → userbot шлёт от твоего имени. Allowlist + away + confidence-гейты.
- **Автономная отправка — НЕ делать** (или максимально гейтить).

**Ключевые риски (см. ресёрч, таблица рисков):**
- Бан личного аккаунта (read-heavy + рандом-тайминг + прогрев).
- Приватность чужих сообщений → локальная LLM или ZDR + Presidio-редакция; не free Gemini.
- 24/7 надёжность (watchdog), дедуп событий (idempotent consumer), session string в секрете.

**Перед продом обязательно:** product-определение (что считаем «важным», нужен
ли автоответ вообще), правовое решение по чужим ПД, выбор LLM (локальная vs облако).

**Depends on:** ничего жёстко (можно гонять на деве параллельно), но по приоритету
— после core (Mini App + user test + Phase 4/6).

---

## БЭКЛОГ — без приоритета

### Phase 3C — Photo OCR (1-2 дня)
Фото → OCR → AI pipeline. Yandex Vision (РФ) или Tesseract (self-hosted). Делать когда юзеры запросят.

### Phase 5.5 — Session Mode
Серия коротких заметок → один конспект. `/session start/end`, автодетект, суммаризация.

### Phase 5.6 — Proactive Call Mode
Google Calendar API → детект звонка → связать заметки с событием.

### Phase 5.7 — Daily Digest & Chat History
`/day` — статистика дня. Mini App: история с пометками «сохранено». Post-factum сохранение пропущенных.

### Phase L — Программа обучения (параллельно)
Модули L1-L7 (Git, Docker, API, БД, AI, Security, Testing) на примере живого кода BookmarkBrain.

---

## DEPLOY — Оставшиеся задачи

| Bead | P | Задача |
|---|---|---|
| `xzq` | P1 | Async STT deploy на VPS (`YANDEX_S3_*` envs, `git pull`, `docker compose up -d --build`) |
| `4e3` | P1 | Live smoke-test после PR #4 (race в onboarding, boto3 lock, длинное голосовое >30s) |
| `y8n` | P2 | GitHub Secrets для CD (`VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`) |
| `d0v` | P2 | Закрыть после `git pull` (lifecycle уже применён через boto3) |

**Дополнительно (вне bead):**
- [ ] Сменить пароль VPS (был светился в чате)
- [ ] Postgres backup cron (pg_dump → локально)
- [ ] Error alerting (Telegram notification on crash)
- [ ] Sentry или аналог error tracking

---

## БЭКЛОГ — окружение и хуки

### Окружение разработчика
- [ ] **Makefile** — `make test` / `make deploy` / `make logs` / `make migrate`
- [ ] **scripts/seed-dev-db.py** — фейковые закладки для локальных тестов
- [ ] **scripts/check-env-sync.sh** — сверяет vars из config.py с .env.production.example
- [ ] **VS Code launch.json** — конфиги для дебага
- [ ] **direnv** — авто-подгрузка .env

### Хуки
- [ ] **check-spec-staleness.py** — варнит если 10+ коммитов или 14+ дней без обновления SPEC.md/ARCHITECTURE.md
- [ ] **check-adr.py** — напоминает создать ADR при добавлении новой зависимости / AI-провайдера
- [ ] **check-env-sync.py** — при изменении config.py напоминает обновить .env.production.example
- [ ] **check-migration.py** — варнит если в коммите новая миграция, но `alembic upgrade head` локально не запускался

### Правила (.claude/rules/bookmark-brain.md)
- [ ] env-var lifecycle (config.py + .env.production.example + memory/deployment.md)
- [ ] migration safety (autogenerate → SQL review → rollback test)
- [ ] API contract (изменение /api/v1/ → проверить bot/handlers)
- [ ] provider fallback (новый AI-провайдер только через BaseClassifier)

### Сделано из бэклога
- [x] **check-secrets.py хук** — блокирует git commit с реальными API-ключами (2026-05-08)

---

## Известные решения (для контекста)

- GigaChat SDK не работает — используем httpx + OAuth напрямую
- GigaChat embeddings 402 на бесплатном тарифе — Voyage AI
- Groq/OpenAI заблокированы из РФ — Yandex SpeechKit
- arq CLI ломается на Python 3.14 — `run_worker.py` с `asyncio.run()`
- Bot Settings: `extra="ignore"` чтобы не падать от лишних env vars
- Backend Settings: `extra="ignore"` (для Yandex переменных)
- Yandex Cloud: нужен платёжный аккаунт + clouds.member на уровне облака
- Async STT lifecycle: минимум 1 день в Yandex S3 (час нельзя)

---

## Метрика успеха roadmap

**До юзер-теста (текущий цикл):**
- Phase 2.5 закрыт (другой чат)
- Phase 5 Smart Blocks работает
- Mini App минимально готов
- 5+ внешних юзеров активно используют 2+ недели

**После юзер-теста:**
- Phase 4 на реальных данных
- Retention day-7 > 50%
- < 10% ошибок auto-routing после Phase 4

**Долгосрочно:**
- Phase 6 запущен
- 50+ активных юзеров
- Mini App / iOS как main UI
