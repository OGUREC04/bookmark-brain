# BookmarkBrain — Feature Roadmap (May 2026)

## Overview

6 phases, ~44-62 dev-days total. Each phase is independently shippable.
Based on: code review (2026-05-02), architecture review, wiki recommendations, product vision.

---

## Phase 0: Hardening & Foundation (8-10 days)

**Goal:** Fix CRITICAL/HIGH issues, build shared infrastructure.

### 0A. Security (day 1-2)
- [ ] Remove SECRET_KEY default, make required + startup guard
- [ ] Remove BOT_SECRET default, add empty-string guard
- [ ] Bundle Sber CA cert for GigaChat TLS (`verify=False` → `verify="certs/sber_ca.pem"`)
- [ ] Fix IDOR: add `user_id` to bookmark fetch WHERE clause
- [ ] Escape LIKE wildcards in search fallback
- [ ] Add rate limiting (slowapi)

### 0B. Bot stability (day 2-3)
- [ ] Fix `_pending_saves` keying → by message_id + 5min TTL
- [ ] Guard `InaccessibleMessage` in all callback handlers
- [ ] Token cache with TTL, re-auth on 401
- [ ] httpx retry/limits on bot API client

### 0C. Worker & data integrity (day 3-4)
- [ ] Batch tag creation with ON CONFLICT
- [ ] Fix bookmarks_count inflation on reprocess
- [ ] Fix worker double-commit race on task_list
- [ ] Extract Telegram notification from worker → NotificationService
- [ ] Fix `_rerender_at_bottom` race with per-(chat,bookmark) lock

### 0D. Shared infrastructure (day 5-8)
- [ ] `search_traces` table + logging every search
- [ ] `classification_feedback` table
- [ ] Embedding retry cron for `ai_status = 'partial'`
- [ ] API versioning: `/api/v1/` prefix
- [ ] `/health` with Postgres + Redis ping
- [ ] Extract NotificationService (shared worker/bot)

**Depends on:** Nothing. Foundation for everything.

---

## Phase 1: Silent Mode (3-4 days)

**Goal:** Zero-noise saves. Reaction-based receipts like Telegram Saved Messages.

- [ ] Add `silent_mode` to User.settings JSONB (default: true)
- [ ] `/silent` toggle command
- [ ] Replace text confirmation with `setMessageReaction(⏳)` 
- [ ] On complete: reaction → ✅, NO text message
- [ ] On error: reaction → ❌, ephemeral auto-delete message (10s)
- [ ] Remove short-message confirmation prompt in silent mode
- [ ] Non-silent mode as opt-in (legacy behavior)

**Key:** Task lists still get interactive message (checkboxes are essential).

**Depends on:** Phase 0B (bot stability), 0C (NotificationService)

---

## Phase 1.5: Task List Smartening (3-4 days)

**Goal:** Списки задач становятся умнее — объединение дубликатов, stale-уведомления.

### 1.5A. Dedup-alert при создании (day 1-2)
- [ ] При создании нового task_list — embedding similarity с незакрытыми списками (7 дней)
- [ ] Если similarity > 0.7 → предложить объединить: «У тебя похожий список от вчера (2/5 выполнено). Объединить?»
- [ ] «Объединить» = NL-edit старого: добавить новые пункты, убрать дубли
- [ ] «Создать отдельный» = как сейчас

### 1.5B. Stale list nudge (day 3-4)
- [ ] Cron (утро): проверить незакрытые списки старше 24ч с done < total
- [ ] Ephemeral: «Вчерашний список: 1/4 выполнено. Перенести незакрытое?»
- [ ] [Перенести] = новый список из невыполненных, старый → closed
- [ ] [Закрыть] = пометить старый как done
- [ ] [Оставить] = не трогать

**Depends on:** Phase 1 (silent mode, task list foundation)

---

## Phase 2: Learning Mechanisms (5-7 days)

**Goal:** System learns from user behavior.

### 2A. Classification feedback (day 1-3)
- [ ] Inline "wrong classification" button on bookmark card
- [ ] Callback: item_type picker (action/thought/content/reference)
- [ ] `POST /api/v1/bookmarks/{id}/feedback` endpoint
- [ ] Store correction, update bookmark
- [ ] Few-shot selector: top-3 feedback examples by embedding similarity in classifier prompt
- [ ] `included_in_prompt` flag for high-confidence corrections

### 2B. Usage decay (day 3-4)
- [ ] Decay coefficient in search scoring based on `last_accessed`
- [ ] Update `last_accessed` on view/search-click
- [ ] Track `clicked_id` in search_traces

### 2C. Tag co-occurrence (day 5-6)
- [ ] Materialized view `tag_cooccurrence`
- [ ] Nightly refresh cron (CONCURRENTLY)
- [ ] Inject co-occurring tags into classifier prompt

**Depends on:** Phase 0D (traces + feedback tables)

---

## Phase 3: Multi-format Input (7-10 days)

**Goal:** Voice, files, photos → text → existing AI pipeline.

### 3A. Voice/video notes ✅ DONE (2026-05-06)
- [x] `WHISPER_API_KEY` / `STT_PROVIDER` in config (backend + bot)
- [x] `WhisperSTTService` via raw httpx (OpenAI + Groq providers)
- [x] Bot: download → STT → reply with transcription → save as bookmark
- [x] Store `content_type=voice|video_note|audio`, `media_file_id` (Text), `transcription`, `media_duration`
- [x] Migration: `transcription` (Text), `media_duration` (Float), `media_file_id` VARCHAR→Text
- [x] Edge cases: duration <2s guard, file >20MB guard, group fallback, backend-fail graceful
- [x] Removed voice/audio/video_note from start.py catch-all filter

### 3B. Documents (day 5-7)
- [ ] `DocumentExtractor` service (pymupdf for PDF, python-docx for DOCX)
- [ ] Bot: download document, detect type, extract text, enqueue
- [ ] Truncation to 8000 chars before AI

### 3C. Photo OCR (day 8-9)
- [ ] OCR service (Tesseract or Claude Vision)
- [ ] Bot: download photo, OCR, feed to pipeline

### 3D. Voice Features (day 10-12)
- [ ] Голосовой /todo — если транскрипция похожа на список задач → авто task list
- [ ] Голосовой поиск — голосовое < 10с без текста → `/search {transcription}`
- [ ] Авто-тег `#voice` — все голосовые получают тег для фильтрации
- [ ] Таймкоды для длинных голосовых (>2мин) — Whisper timestamps → chunks

**Architecture:** All formats converge to text → existing classify → embed → tag pipeline.

**Depends on:** Phase 1 (silent mode UX)

---

## Phase 4: Smart Blocks MVP (10-14 days)

**Goal:** Intelligent collections beyond tags/folders. Blocks = folder + AI behavior + auto-routing.

### 4A. Data model (day 1-3)
- [ ] `smart_blocks` table: id, user_id, name, emoji, template_type, ai_prompt, routing_rules (JSONB), display_config (JSONB)
- [ ] `block_id` FK on Bookmark (nullable, alongside existing `folder_id`)
- [ ] CRUD API: `POST/GET/PUT/DELETE /api/v1/blocks`
- [ ] `GET /api/v1/blocks/{id}/bookmarks` with pagination

### 4B. Auto-routing (day 4-6)
- [ ] `BlockRouter` service: evaluate routing rules vs classification output
- [ ] Integrate into `BookmarkProcessor` after classification
- [ ] Fallback: unmatched = no block (not error)

### 4C. Base templates (day 7-9)
- [ ] 5 preset templates: Goals, Ideas, Read Later, Do Someday, Insights
- [ ] `POST /api/v1/blocks/from-template`
- [ ] Bot: `/blocks` command, `/block <name>` view

### 4D. Bot UX (day 10-12)
- [ ] Show block name in save notification
- [ ] `/blocks setup` guided creation
- [ ] Block stats in `/stats`

**Future:** AI-suggested personalized blocks after 50-100 bookmarks.

**Depends on:** Phase 0D (API versioning), benefits from Phase 2 (feedback for routing)

---

## Phase 4.5: LLM Provider Migration (2-3 days)

**Goal:** Заменить GigaChat на DeepSeek для NL-операций. GigaChat нестабилен с JSON — NL edit task_list ломается в ~20% случаев.

### Контекст проблемы
- GigaChat не поддерживает `response_format: {"type": "json_object"}` — возвращает markdown/текст вместо JSON
- Два раза пришлось обходить LLM: мета-команды (удали список) и fast-path (deadline, toggle, add, remove)
- Fast-path покрывает ~80% команд, но сложные фразы всё ещё ломаются
- DeepSeek: гарантированный JSON, $0.14/1M tokens, OpenAI-совместимый API

### Задачи
- [ ] Получить DeepSeek API key, добавить в `.env`
- [ ] Переключить `AI_PROVIDER=deepseek` (или отдельный `NL_EDIT_PROVIDER`)
- [ ] Проверить классификацию на DeepSeek (может быть лучше GigaChat)
- [ ] Fallback chain: DeepSeek → GigaChat (если DeepSeek недоступен)
- [ ] Сравнить качество: 20 тестовых фраз на обоих провайдерах

**Depends on:** Phase 4 (Smart Blocks). Можно начать раньше если NL edit критичен.

---

## Phase 5: Proactivity 1.0 (8-12 days)

**Goal:** Brain reminds you. Connections, surfacing, digests.

### 5A. Auto-connections on save (day 1-3)
- [ ] `bookmark_connections` table (bookmark_id, related_id, similarity_score)
- [ ] After embedding: top-3 nearest by cosine similarity
- [ ] API: `GET /api/v1/bookmarks/{id}/related`
- [ ] Bot: "Related" section in bookmark view

### 5B. Contextual surfacing (day 4-5)
- [ ] High-similarity (>0.85) → "You saved something similar X days ago"
- [ ] Entity matching (from classification) for named connections

### 5C. Periodic digest (day 6-9)
- [ ] `digest_settings` in User.settings (frequency, time, timezone)
- [ ] `/digest` command to configure
- [ ] Cron job: select forgotten-but-important bookmarks using decay scoring
- [ ] "Still relevant?" buttons (Yes/Archive)

### 5D. Dedup detection (day 10-11)
- [ ] Similarity > 0.95 → "You already saved this" warning
- [ ] Offer: merge or keep both

### 5E. Goal coaching (day 12)
- [ ] Новый item_type=`goal` — долгосрочные цели/намерения (без чекбоксов)
- [ ] При сохранении goal без дедлайна → coaching hint: «Добавь срок и первый шаг»
- [ ] Периодическое surfacing: «Как продвигается цель X?»
- [ ] Отличие от action: goal живёт долго, нет чекбоксов, бот напоминает

**Depends on:** Phase 2 (decay), Phase 4 (blocks context for digest)

---

## Phase 5.5: Session Mode (идея, требует дизайна)

**Goal:** Не всё что пишешь боту — отдельная закладка. Иногда это серия коротких заметок во время рабочей сессии (звонок, работа в Фигме, мозговой штурм). Сохранять по отдельности бессмысленно — нужно собрать в один конспект.

### Сценарий
- Юзер 2-3 часа пишет короткие фрагменты: вопросы, договорённости, идеи
- Бот копит сообщения без обработки (реакция 📝 вместо 👍)
- По завершению сессии — бот собирает всё в один конспект → classify → embed → одна закладка

### Механика
- [ ] `/session start` — начать сессию (или автодетект: серия коротких сообщений за N минут)
- [ ] `/session end` — завершить (или авто-закрытие по таймауту 30 мин тишины)
- [ ] `chat_messages` таблица — временное хранение сообщений сессии
- [ ] При закрытии: LLM суммаризация → одна закладка типа `session_notes`
- [ ] Mini App: показ истории переписки (7-14 дней), возможность сделать закладку из сообщения

### Открытые вопросы
- [ ] Хранить в `chat_messages` или читать через Telegram API?
- [ ] Какой TTL у истории? (7 дней? 30 дней?)
- [ ] Как отличить "мысль вслух" от короткой закладки?
- [ ] Автодетект сессии vs. ручной старт?

**Depends on:** Phase 5 (Mini App). Требует UX-дизайна.

---

## Phase 5.6: Proactive Call Mode (идея, требует дизайна)

**Goal:** Бот понимает контекст звонка и связывает заметки с событием из календаря.

### Сценарий
- У юзера стоит звонок в Google Calendar
- Во время звонка юзер пишет заметки в бота
- Бот: определяет что сейчас идёт звонок → связывает заметки с событием
- После звонка: забирает конспект (Google Meet transcript / Otter.ai)
- Дополняет смысл заметок контекстом из конспекта

### Что нужно
- [ ] Google Calendar API интеграция (OAuth2)
- [ ] Детект "сейчас идёт событие" по времени + участники
- [ ] Линковка заметок с calendar event_id
- [ ] Post-call: fetch transcript, enrich session notes
- [ ] Архитектура: event-driven (webhook от Calendar push notifications)

### Зависимости
- Phase 5.5 (Session Mode — сессия как концепт)
- Google Calendar API доступ
- Transcript API (Google Meet / Otter.ai / Fireflies.ai)

**Depends on:** Phase 5.5, Phase 6 (Proactivity 2.0). Research only.

---

## Phase 5.7: Daily Digest & Chat History (идея, требует дизайна)

**Goal:** Показать юзеру итоги дня: что он отправил, что ушло в заметки, что нет. Интерактивная «лента дня» с метриками.

### Сценарий
- Юзер вечером нажимает `/day` (или cron-сообщение в 21:00)
- Бот показывает дайджест: 12 сообщений, 3 голосовых (4м 32с), 8 → закладки, 4 → пропущены
- В Mini App: полная история диалога за день с пометками «сохранено ✅» / «не сохранено»
- Юзер может кликнуть на несохранённое → сделать закладку пост-фактум

### Механика
- [ ] `chat_messages` таблица — все сообщения в боте (текст, тип, timestamp, bookmark_id|null)
- [ ] Bot middleware: логировать каждое входящее сообщение (не только сохранённые)
- [ ] `/day` команда — краткая статистика в Telegram
- [ ] Mini App: `/history` страница — лента сообщений за день/неделю
- [ ] Маркер «сохранено» — сообщения с bookmark_id подсвечены

### Метрики дня
- Всего сообщений / голосовых / текстовых / медиа
- Сохранено в закладки / пропущено
- Суммарная длительность голосовых
- Топ-категории сохранённого

### Открытые вопросы
- [ ] Хранить полный текст или только metadata? (privacy vs. полнота)
- [ ] TTL хранения: 7 дней? 30 дней? настраиваемый?
- [ ] Связь с Session Mode (5.5) — сессии как группировка внутри дня?

**Depends on:** Phase 5 (Mini App для визуализации). Бот-часть (`/day`) можно раньше.

---

## Deploy (3-5 days)

**Goal:** Вывести бота в продакшен. Доступен 24/7 без локальной машины.

### Инфраструктура
- [ ] VPS/cloud выбор (Hetzner / Timeweb / Selectel / Railway)
- [ ] Docker Compose production config (postgres, redis, backend, worker, bot)
- [ ] Nginx reverse proxy + SSL (Let's Encrypt)
- [ ] Environment management (.env.production, secrets)

### CI/CD
- [ ] GitHub Actions: lint + test on PR
- [ ] Auto-deploy on merge to main (SSH / Docker push)
- [ ] Health check monitoring (UptimeRobot / Healthchecks.io)

### Data
- [ ] Postgres backup strategy (pg_dump cron → S3/local)
- [ ] Redis persistence config (AOF)
- [ ] Migration strategy (Alembic on deploy)

### Observability
- [ ] Structured logging (JSON) → file rotation
- [ ] Error alerting (Telegram notification on crash)
- [ ] Basic metrics (bookmarks/day, AI latency)

**Depends on:** Phase 3 (Multi-format Input — продукт должен быть полноценным перед деплоем)

---

## Phase 6: Proactivity 2.0 — Research Only (3-5 days)

**Goal:** Explore feasibility. Do NOT build full agent.

- [ ] Define agent action catalog (survey users)
- [ ] Prototype: Google Calendar event from action bookmark
- [ ] Prototype: scheduled Telegram reminder from bookmark deadline
- [ ] Architecture: action pipeline with approval workflow

**Depends on:** Phase 5, significant user base (100+ active users)

---

## Shared Components (build once, use everywhere)

| Component | Built in | Used by |
|-----------|----------|---------|
| `NotificationService` | Phase 0C | 1, 3, 5 |
| `SimilarityService` | Phase 5A | 4 (routing), 5 (connections) |
| `UserSettingsManager` | Phase 1 | 2, 5, 6 |
| `MediaDownloader` | Phase 3A | 3 (all formats) |
| `SchedulerService` | Phase 5C | 5, 6 |

---

## New External Dependencies

| Service | Phase | Cost | Purpose |
|---------|-------|------|---------|
| OpenAI Whisper API | 3 | $0.006/min | STT |
| pymupdf | 3 | Free (AGPL) | PDF extraction |
| python-docx | 3 | Free | DOCX extraction |
| Tesseract | 3 | Free | OCR |
| slowapi | 0 | Free | Rate limiting |

---

## New API Endpoints Summary

| Endpoint | Phase |
|----------|-------|
| `PATCH /api/v1/users/settings` | 1 |
| `POST /api/v1/bookmarks/{id}/feedback` | 2 |
| `GET/POST/PUT/DELETE /api/v1/blocks` | 4 |
| `POST /api/v1/blocks/from-template` | 4 |
| `POST /api/v1/blocks/suggest` | 4 (future) |
| `GET /api/v1/bookmarks/{id}/related` | 5 |
| `GET /api/v1/digest/preview` | 5 |
| `POST/GET/DELETE /api/v1/integrations` | 6 |

---

## New Data Model Changes

| Table/Column | Phase |
|-------------|-------|
| `search_traces` table | 0D |
| `classification_feedback` table | 0D |
| `Bookmark.transcription` column | 3 |
| `Bookmark.media_duration` column | 3 |
| `smart_blocks` table | 4 |
| `Bookmark.block_id` FK | 4 |
| `bookmark_connections` table | 5 |
| `Bookmark.last_surfaced_at` column | 5 |
| `Bookmark.importance_score` column | 5 |

---

## Scalability Notes

- **1K bookmarks:** All phases fine
- **10K:** Search CTE needs ANN pre-filter; reprocess-all needs batching
- **100K (multi-user):** Connection pool tuning; random() → TABLESAMPLE; consider partitioning
- **Worker:** Pool httpx connections at worker level, not per-job
