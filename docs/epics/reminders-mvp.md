# Epic: Reminders MVP

**Статус:** Backlog → ready to start
**Дата:** 2026-05-09
**PRD:** [../prd/REMINDERS-MVP.md](../prd/REMINDERS-MVP.md)
**ROADMAP:** Phase 2.5
**Beads root:** `bookmark-brain-whv`
**Прогресс:** 0%

---

## Overview

Технический план реализации Reminders MVP. PRD ([REMINDERS-MVP.md](../prd/REMINDERS-MVP.md)) описал «что и зачем», edge cases, success metrics. Этот эпик — «как и в каком порядке».

Цель — превратить идею «бот пушит напоминания по запросу юзера» в работающий код за 3-5 dev-days с минимальной рисковой поверхностью.

---

## Architecture Decisions

Из PRD + результатов прогона через `planner` + `architect` + `code-explorer`. Зафиксированы три ключевых решения:

| # | Решение | Альтернатива | Причина |
|---|---|---|---|
| AD-1 | **Generic schema:** таблица `scheduled_messages` с `kind ENUM`, dispatch if/elif | Specific `reminders` table | Phase 6 (digest, surfacing) уже в роадмапе — не speculative generality. Стоимость абстракции — одна колонка `kind`, payload jsonb opaque. |
| AD-2 | **NL parser:** библиотека `dateparser` + thin wrapper | Самописный regex / расширение существующего `_parse_date` из `tasks.py` | dateparser покрывает ru/en/relative/absolute из коробки, ~10M downloads/mo, MIT. Самописное будем чинить год. |
| AD-3 | **Timezone:** колонка `users.timezone TEXT DEFAULT 'Europe/Moscow'` + команда `/tz` | Хардкод MSK, `/tz` отложить | Юзер из Калининграда получит «завтра в 9» в 8 утра — баг через неделю. +30 минут сейчас vs дни багов потом (см. правило `surface-architecture-forks.md`). |
| AD-4 | **Scheduler:** arq cron каждую минуту + Postgres source of truth + CAS-update | arq deferred jobs (`_defer_until`) / отдельный timer-loop | Идиоматично текущему коду (`stale_list_nudge`, `retry_failed_task`), переживает рестарт worker'а, idempotent через CAS, легко дебажить через SQL. |
| AD-5 | **Idempotency:** `UPDATE ... WHERE status='pending' RETURNING` | Redis NX lock | Atomic SQL-уровень, не нужен внешний lock. |
| AD-6 | **Каскадное удаление reminder при удалении bookmark:** ON DELETE CASCADE | Reminder живёт сам с copy текста | По решению юзера — Вариант A в corner-case discussion. |

Каждое решение — кандидат на ADR (`docs/decisions/0006-...md` и т.д.) при реализации.

---

## Technical Approach

### Backend (FastAPI + arq + PostgreSQL)

**Новые модули:**
- `backend/app/models.py` — модель `ScheduledMessage` (Enum `ScheduledKind`, `ScheduledStatus`)
- `backend/app/schemas.py` — Pydantic схемы для CRUD reminder API
- `backend/app/services/nl_date.py` — обёртка над `dateparser` с edge-case handling
- `backend/app/services/reminder_intent.py` — детектор «надо/нужно/до/к + явные даты»
- `backend/app/api/reminders.py` — CRUD endpoints (`POST /reminders`, `PATCH /id`, `DELETE /id`, `GET /upcoming`)

**Изменения существующих:**
- `backend/app/worker.py` — добавить cron `scheduled_dispatcher` + `auto_done_reminders` + helper `handle_reminder`
- `backend/app/services/bookmark_processor.py` — после процессинга проверить `ReminderIntentDetector`, если intent → enqueue background job отправки кнопки в бот
- `backend/app/api/users.py` — добавить `PATCH /users/me/timezone`

**Миграции (Alembic):**
- `xxx_add_users_timezone.py` — `ALTER TABLE users ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Europe/Moscow'`
- `xxx_add_scheduled_messages.py` — таблица + 2 индекса (см. PRD schema)

### Bot (aiogram 3)

**Новые модули:**
- `bot/handlers/reminders.py` — все callback'и + reply-handler:
  - `cb_create_reminder` (`rsk:{bid}` → ждать reply)
  - `cb_cancel_reminder` (`rsn:{bid}` → удалить сообщение бота)
  - `cb_done` (`rdone:{rid}` → status=done, edit message)
  - `cb_snooze` (`rsnz:{rid}` → ждать reply на «когда продлить»)
  - `on_reply_for_reminder` — проверяет Redis-ключи `reminder_pending:*` / `reminder_snooze:*`, парсит дату через backend API, создаёт reminder
- `bot/handlers/timezone.py` — команда `/tz <zone>`

**Изменения:**
- `bot/api_client.py` — методы `create_reminder`, `update_reminder`, `delete_reminder`, `set_timezone`
- `bot/state_store.py` — методы для `reminder_pending` и `reminder_snooze` Redis ключей
- `bot/main.py` — регистрация `reminders` роутера (после `tasks` — порядок важен из-за reply-handler коллизий)

### Infrastructure

- `backend/requirements.txt` — добавить `dateparser>=1.2`
- Docker compose не меняем — всё через существующие `redis` и `postgres`

---

## Implementation Strategy

5 фаз. Большинство параллелится через TDD-друзья: сначала RED тесты, потом GREEN imp.

### Phase A — Foundation (Day 1)

Параллельно (3 потока):
- **A1.** Миграция `users.timezone`
- **A2.** Миграция `scheduled_messages` + индексы
- **A3.** TDD `nl_date.parse()` — RED тесты на 25+ кейсов (см. PRD), потом GREEN через `dateparser` + wrapper

Зависимости: ничего. Слияние в конце дня.

### Phase B — Detection + API (Day 2)

Параллельно (2 потока):
- **B1.** TDD `reminder_intent.py` — RED тесты на positive/negative + интеграция в `bookmark_processor`
- **B2.** CRUD API `reminders.py` + integration tests против test DB

Зависимости: A2 (таблица существует), A3 (для тестов B1 с временами).

### Phase C — Worker dispatcher (Day 3)

- **C1.** Cron `scheduled_dispatcher` с CAS-claim
- **C2.** Handler `handle_reminder` (формирование сообщения + кнопки + Redis ключ)
- **C3.** Cron `auto_done_reminders` (24ч timeout)
- **C4.** Тесты с замороженным временем (`freezegun`)

Зависимости: A2, B2.

### Phase D — Bot UX (Day 4)

Параллельно (3 потока, минимум коллизий):
- **D1.** `bot/handlers/reminders.py` — все callback'и + reply-handler
- **D2.** `bot/handlers/timezone.py` — команда `/tz`
- **D3.** Patch `bot/handlers/start.py` или `media.py` — показ кнопки `🔔 Создать напоминание?` после save (учитывая silent-mode skip)

Зависимости: B2 (API), C2 (cron шлёт через bot).

### Phase E — E2E + Polish (Day 5)

- **E1.** Ручной E2E через `@bookmarkbrain_dev_bot`: создать заметку с интенцией → нажать → reply «через 2 минуты» → дождаться → snooze → проверить auto-done
- **E2.** Onboarding tip (`onboarding_reminder_done`, `onboarding_reminder_fire_done` в `User.settings`)
- **E3.** Обновить `docs/SPEC.md`, `docs/ARCHITECTURE.md` (data flow), `docs/BOT-COMMANDS.md` (новая команда `/tz`)
- **E4.** Создать ADR `docs/decisions/0006-scheduled-messages.md` и `0007-dateparser.md` (закрепить AD-1 и AD-2)
- **E5.** Code review через агента, security review

---

## Task Breakdown Preview

8 задач (под лимит CCPM ≤10). Каждая = один атомарный PR.

| # | Task | Phase | Parallel | Depends | Est. |
|---|------|-------|----------|---------|------|
| 1 | Migration: `users.timezone` + `scheduled_messages` | A | with 2 | - | 0.5d |
| 2 | `nl_date.parse()` + tests (TDD) | A | with 1 | - | 0.5d |
| 3 | `ReminderIntentDetector` + integration в `bookmark_processor` | B | with 4 | 1, 2 | 0.5d |
| 4 | CRUD API `reminders.py` + tests | B | with 3 | 1 | 0.5d |
| 5 | Worker `scheduled_dispatcher` + `auto_done_reminders` cron | C | - | 1, 4 | 1d |
| 6 | Bot handlers: `reminders.py` (callbacks + reply) | D | with 7, 8 | 4, 5 | 1d |
| 7 | Bot command `/tz` | D | with 6, 8 | 1 | 0.25d |
| 8 | Bot patch: показ кнопки после save (silent-aware) | D | with 6, 7 | 3 | 0.5d |
| 9 | Onboarding tips + docs update + ADR | E | - | 6, 7, 8 | 0.5d |
| 10 | Manual E2E + code-reviewer + security-reviewer | E | - | 9 | 0.5d |

**Итого:** ~5.25 dev-days. Соответствует оценке PRD (3-5 days) с буфером.

---

## Dependencies

### Blocking (внутренние)

- ✅ Worker `_send_message` (`worker.py`) — есть, работает в `stale_list_nudge`
- ✅ Redis state store паттерн — есть в `bot/state_store.py`
- ✅ Inline callback parsing pattern — есть в `bot/handlers/tasks.py`
- ✅ AI bookmark processor pipeline — есть в `bookmark_processor.process_bookmark`
- ⚠️ Параллельная фича-работа в `bot/handlers/`, `backend/app/api/`, `backend/app/services/` (другой чат) — **координация обязательна** перед стартом C/D

### External

- 📦 `dateparser>=1.2` (PyPI, MIT) — добавить в `backend/requirements.txt`

### Code reuse

- Pattern «cron шлёт сообщение → bot reads reply через Redis ключ» → `stale_list_nudge` + `nudge:{...}`
- Inline callback dispatch → `tasks.py` (`tg:`, `tldm:`, `tlds:`)
- Worker cron registration → `worker.py::WorkerSettings.cron_jobs`

---

## Success Criteria (Technical)

- [ ] Все 25+ unit-тестов `nl_date.parse()` зелёные (с freezegun для `now`)
- [ ] `ReminderIntentDetector` precision > 80% на тестовом датасете 50 фраз (positive/negative)
- [ ] Cron `scheduled_dispatcher` обрабатывает 100 reminder'ов за тик < 1 сек (бенчмарк)
- [ ] Idempotency: при двойном тике cron — нет дублей (test через симуляцию)
- [ ] CRUD API tests зелёные (создание / чтение / отмена / IDOR-защита)
- [ ] E2E: создать заметку «купить молоко завтра в 18» → кнопка появилась → жму Да → reply «через 2 минуты» → reminder пришёл → snooze работает → auto-done через 24ч (симуляция)
- [ ] code-reviewer и security-reviewer не нашли CRITICAL/HIGH issues
- [ ] Coverage по новым файлам ≥ 80%

### Success Criteria (Product) — из PRD

- [ ] ≥ 30% показов кнопки → reminder создан (после первой недели)
- [ ] ≤ 10% reply'ев получают «не разобрал» (после первой недели)
- [ ] ≥ 95% reminders отправлены в окне ±60 сек от fire_at
- [ ] ≤ 5% юзеров жалуются на спам / отключают через `/tz`

---

## Estimated Effort

- **Dev:** ~5.25 dev-days (по разбивке выше)
- **Risk buffer:** +1 day на NL-парсер edge cases (русский язык — головная боль)
- **Total estimate:** **5-6 days**

Соответствует PRD-оценке «3-5 days» с реалистичным буфером.

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `dateparser` плохо парсит «на праздниках» / редкие фразы | M | Тонкий wrapper с pre-processing (заменять «на праздниках» → «next saturday») перед dateparser |
| Reply-handler коллизия с `tasks.py` (юзер reply'ит на task list, попадает в reminder logic) | M | Регистрация `reminders` роутера ПОСЛЕ `tasks`, проверка что reply-target — bookmark не task_list |
| Race condition: 2 worker'а параллельно обрабатывают тот же reminder | L | CAS-update через `WHERE status='pending' RETURNING` (атомарно) |
| Telegram API rate limits на массовых reminder'ах | L | `max_jobs=5` в worker, batch не больше 50 за тик |
| Юзер удалил bookmark между creation и fire — reminder ссылается на null | L | `ON DELETE CASCADE` решает (вариант A из PRD) |
| TZ обработка ломается на DST-границах | M | `zoneinfo.ZoneInfo` (не pytz), все вычисления через `dt.astimezone(UTC)` перед записью |

---

## Open Questions (наследовано из PRD)

- [ ] Команда `/tz` — формат ввода: IANA (`Europe/Moscow`) или дружелюбный (`MSK`)?
- [ ] Truncate `bookmark.summary` в reminder-сообщении — по символам или по первой строке?
- [ ] Cleanup кнопки `🔔 Создать напоминание?` через 1ч — `scheduled_messages.kind='nudge'` или arq deferred job?

Решаем перед стартом соответствующей фазы (D для первых двух, C для третьего).

---

*Готов к декомпозиции в отдельные task-файлы. Команда: «decompose the reminders-mvp epic».*
