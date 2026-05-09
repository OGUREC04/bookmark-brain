# PRD: Reminders MVP

**Статус:** Draft
**Дата:** 2026-05-09
**Фаза:** Phase 2.5 (после Onboarding)
**Оценка:** 3-5 dev-days
**Связано с:** [[Phase 1.5B Stale List Nudge]] (паттерн worker→bot push), [[Phase 6 Proactivity 1.0]] (унификация в `scheduled_messages`)

---

## Проблема

Юзер часто пишет себе в бот сообщения типа:

- «До 15 мая нужно подать на матпомощь»
- «Поискать на праздниках кто задротит ОС»
- «Надо позвонить маме завтра»

Сейчас это **просто сохраняется в закладки и тонет**. Через неделю юзер забывает что писал. Дедлайны пропускаются. Идея «вернуться к этому» не возвращается.

Telegram-напоминаний внутри бота нет. Альтернативы плохо стыкуются:

- **/remind в системных ботах** — отдельный flow, надо переключать контекст.
- **Календарь** — overhead на ввод (открой → создай событие → введи название).
- **Apple/Google Tasks** — отдельное приложение, нет связи с заметками.
- **Saved Messages** — пассивный, ничего не пушит.

Боль: **юзер уже в чате с ботом, уже написал контекст — но напоминания нет**. Хочется чтобы бот замечал интенцию и предлагал напомнить **одним тапом**, без переключения контекстов.

## Решение

Бот замечает в сохраняемой заметке намерение «надо сделать» или временной маркер. Предлагает inline-кнопку «🔔 Создать напоминание?». Юзер задаёт время через reply на естественном языке. В назначенное время бот пушит напоминание с кнопками `✅ Выполнено / 💤 Продлить`.

```
Юзер: "Надо позвонить маме завтра"
Бот:  👀 (реакция)
       ... AI обработка ...
Бот:  👍 (реакция)

Бот:  [новое сообщение]
       🔔 Создать напоминание?
       [Да]  [Отказ]
       
       Когда напомнить? Ответь reply'ем:
       завтра в 9, через час, в субботу,
       в субботу в 18, 15 мая, на праздниках
```

Юзер жмёт `Да` → бот ждёт reply. Юзер reply'ит «завтра в 9» → бот парсит → создаёт reminder → убирает кнопки → подтверждает «🔔 Напомню 10 мая в 9:00».

В назначенное время:

```
Бот:  🔔 Напоминание: позвонить маме
       (твоя заметка от 9 мая)
       
       [✅ Выполнено]  [💤 Продлить]
```

---

## User Stories

### US-1. Бот замечает намерение и предлагает

**Как** юзер, который пишет себе мысли с дедлайнами,
**я хочу** чтобы бот сам предложил создать напоминание из моего сообщения,
**чтобы** не переключаться в календарь / другой бот.

**Acceptance:**
- Сообщение содержит маркер интенции («надо», «нужно», «не забыть», «до X», «к X», явная дата) → бот после AI-обработки шлёт **одно** сообщение с кнопкой `🔔 Создать напоминание?`
- Сообщение не содержит маркеров → кнопки нет, обычный flow.
- Кнопка появляется **после** реакции 👍 (не блокирует основной save flow).

### US-2. Юзер задаёт время через reply

**Как** юзер,
**я хочу** ответить reply'ем на естественном языке,
**чтобы** не возиться с date-picker'ами и кнопками.

**Acceptance:**
- Reply на сообщение-предложение → парсится как время напоминания.
- Поддержанные форматы (минимум): «завтра», «завтра в 9», «через час», «через 2 часа», «в субботу», «в субботу в 18», «15 мая», «15 мая в 18:00», «на праздниках» (= ближайший выходной).
- Парсер не понял → бот шлёт уточнение: «не разобрал, попробуй: завтра в 9, через час, 15 мая в 18:00».

### US-3. Юзер получает напоминание и реагирует

**Как** юзер,
**я хочу** в назначенное время получить сообщение с возможностью отметить выполненным или перенести,
**чтобы** не лезть в админку.

**Acceptance:**
- В `fire_at` бот шлёт сообщение с текстом заметки (или его summary) + кнопки `✅ Выполнено / 💤 Продлить`.
- `Выполнено` → reminder = done, кнопки убираются, эфемерное «Готово».
- `Продлить` → бот шлёт новое сообщение «На сколько? Ответь reply'ем: через час, завтра, на неделю, 15 мая в 18...»
- Юзер reply'ит → парсится → reminder пересоздаётся, кнопки старого сообщения убираются.
- 24 часа без реакции после `fire_at` → reminder автоматически = done.

---

## Functional Requirements

### Детектор интенции `ReminderIntentDetector`

Запускается **после** `BookmarkProcessor.process_bookmark`, в воркере. Не AI-классификатор — паттерн-based для скорости и предсказуемости (ML — Phase 4).

Маркеры:
- **Глаголы намерения:** `надо`, `нужно`, `не забыть`, `сделать`, `позвонить`, `купить`, `написать`, `подать`, `проверить`
- **Временные предлоги:** `до <X>`, `к <X>`, `на <X>`
- **Явные даты:** `завтра`, `послезавтра`, `в <день недели>`, `<число> <месяц>`, `<DD.MM>`, `через <N> <часов/дней/недель>`, `на праздниках`, `на выходных`

Возвращает `(has_intent: bool, suggested_datetime: datetime | None)`. Если distance ≥ 1: предлагать кнопку.

### NL-парсер дат `nl_date.parse()`

Тонкая обёртка над `dateparser` (PyPI library, ru/en, RELATIVE_BASE, timezone-aware).

```python
parse(text="завтра в 9", user_tz="Europe/Moscow", now=...) -> datetime | None
```

Edge cases:
- `dt is None` → обёртка возвращает `None`, бот переспрашивает.
- `dt < now` → возвращает `None` + флаг `in_past=True`, бот шлёт «время в прошлом, ты про будущее?».
- День недели без времени («в пятницу») → возвращает `None` + флаг `needs_time=True`, бот шлёт «в пт утром или в пт в 9?».
- «не знаю», «потом», «как-нибудь» → дефолт через 24ч от now.

### Inline-кнопки (callback_data, лимит 64 байта)

| Формат | Значение |
|---|---|
| `rsk:{bid}` | Создать reminder для bookmark id (юзер нажал «Да») |
| `rsn:{bid}` | Отказ (юзер нажал «Отказ»), сообщение бота → удаляется |
| `rdone:{rid}` | Reminder выполнен |
| `rsnz:{rid}` | Продлить reminder (бот шлёт уточнение) |

### Schema

Generic `scheduled_messages` (см. ADR `0006-scheduled-messages.md` — создать вместе с реализацией). Это позволит Phase 6 (digest, surfacing) переиспользовать ту же таблицу.

```sql
CREATE TYPE scheduled_kind AS ENUM ('reminder','digest','surfacing','nudge');
CREATE TYPE scheduled_status AS ENUM ('pending','sending','sent','done','cancelled','failed');

CREATE TABLE scheduled_messages (
  id           UUID PRIMARY KEY,
  user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  bookmark_id  UUID REFERENCES bookmarks(id) ON DELETE CASCADE,  -- nullable для digest
  kind         scheduled_kind NOT NULL,
  fire_at      TIMESTAMPTZ NOT NULL,                              -- UTC
  status       scheduled_status NOT NULL DEFAULT 'pending',
  payload      JSONB DEFAULT '{}',                                -- per-kind data
  retry_count  INT NOT NULL DEFAULT 0,
  message_id   BIGINT,                                            -- Telegram msg_id после отправки
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at      TIMESTAMPTZ,
  cancelled_at TIMESTAMPTZ
);

CREATE INDEX scheduled_messages_pending_fire ON scheduled_messages (fire_at)
  WHERE status = 'pending';
CREATE INDEX scheduled_messages_user ON scheduled_messages (user_id, status);
```

`payload` для kind=reminder: `{"snooze_count": 0, "original_fire_at": "..."}`.

`bookmark_id ON DELETE CASCADE` — юзер удалил заметку → reminder тоже удалён (вариант A — каскадное удаление).

### Worker cron

`scheduled_dispatcher` — `cron(minute='*')` (каждую минуту). Логика:

1. Atomic claim: `UPDATE scheduled_messages SET status='sending' WHERE status='pending' AND fire_at <= now() AND retry_count < 3 RETURNING *` (CAS-защита от дублей).
2. Dispatch по `kind` → handler. Для MVP реализован только `handle_reminder`.
3. `handle_reminder`: загрузить bookmark (если есть), сформировать текст + кнопки, послать через `_send_message`.
4. Сохранить `message_id` + Redis ключ `reminder:{chat_id}:{message_id} → reminder_id` (TTL 25 часов — для auto-done).
5. Status → `sent`. На fail: `retry_count++`, status → `pending` (попробуем через минуту). После 2 retry → `failed`.

### Auto-done через 24ч

Отдельный cron `auto_done_reminders` (`cron(hour=*)`):

```sql
UPDATE scheduled_messages SET status='done'
WHERE kind='reminder' AND status='sent' AND sent_at < now() - interval '24 hours';
```

### Bot handlers

- `handlers/reminders.py::cb_create_reminder` — callback `rsk:{bid}`, edit message: убрать кнопки, добавить «Жду время... ответь reply'ем». Сохранить в Redis `reminder_pending:{chat_id}:{message_id} → bookmark_id` (TTL 1 час).
- `handlers/reminders.py::cb_cancel_reminder` — callback `rsn:{bid}`, удалить сообщение бота.
- `handlers/reminders.py::cb_done` — callback `rdone:{rid}`, status → done, edit без кнопок.
- `handlers/reminders.py::cb_snooze` — callback `rsnz:{rid}`, edit «На сколько? Ответь reply'ем: ...», сохранить в Redis `reminder_snooze:{chat_id}:{message_id} → reminder_id` (TTL 1 час).
- `handlers/reminders.py::on_reply` — обработчик reply, читает Redis ключ, парсит дату через `nl_date`, создаёт/обновляет reminder.
- TTL очистка: после 1 часа Redis сам удаляет ключи. Сообщение бота с кнопкой `🔔 Создать напоминание?` → бот удаляет cron-задачей (`reminder_button_cleanup`, тоже через `scheduled_messages` с `kind='nudge'`? Или просто через arq deferred job — для MVP проще deferred).

---

## Non-Functional Requirements

| Требование | Целевое значение |
|---|---|
| Точность срабатывания | ±60 сек от `fire_at` |
| Latency показа кнопки | ≤ 5 сек после AI-обработки bookmark |
| Reminder retry | 2 попытки с интервалом ~5 мин |
| Auto-done | через 24ч после `sent` |
| Idempotency | гарантия одного срабатывания через CAS-update |

---

## Часовой пояс

**Решение:** колонка `users.timezone TEXT DEFAULT 'Europe/Moscow'`. В БД храним всё в UTC. Все вычисления — через `zoneinfo.ZoneInfo(user.timezone)`.

**Команда `/tz <зона>`** (минимум для MVP) — позволяет сменить. Без интерактивного picker'а — просто `/tz Europe/Kaliningrad`. Default остаётся MSK.

Без этого юзер из Калининграда получит «завтра в 9» в 8 утра по своим часам — баг через неделю в проде. Это явный fork из `surface-architecture-forks.md` — простой путь регрессит позже.

---

## Тихий режим (`/silent`)

Reminder приходит **обычным текстом**, даже в silent mode. Юзер сам попросил — это не «бот навязывается», это запрос. Кнопки `✅ / 💤` тоже показываются.

Кнопка `🔔 Создать напоминание?` (на этапе предложения) — **не показывается** в silent mode. В silent режиме юзер хочет минимум интерактива; если нужен reminder — пусть напишет явно «напомни через час» (попадёт через voice intent flow или будет добавлено в Phase 4).

---

## Onboarding

Первое срабатывание кнопки `🔔 Создать напоминание?` — добавляется развёрнутая подсказка:

```
🔔 Создать напоминание?  [Да]  [Отказ]

Я заметил что в твоей заметке есть про срок. Если хочешь — 
поставлю напоминание. Жми Да и напиши когда (например: 
"завтра в 9", "через час"). Это сообщение ты видишь
только один раз.
```

Флаг `User.settings.onboarding_reminder_done = true`.

Первое сообщение от reminder'а — добавляется подсказка:

```
🔔 Напоминание: ...

Ты можешь нажать ✅ если сделал, или 💤 чтобы перенести.
Если ничего не нажмёшь — через 24 часа я сам отмечу выполненным.
Это сообщение ты видишь только один раз.
```

Флаг `User.settings.onboarding_reminder_fire_done = true`.

---

## Success Criteria

| Метрика | Цель | Как мерить |
|---|---|---|
| Юзер использует фичу | ≥ 1 reminder создан в первую неделю активного юзера | `COUNT scheduled_messages WHERE kind=reminder AND user_id=X` |
| Confirm-flow конвертит | ≥ 30% показов кнопки → reminder создан | `created / shown` |
| Парсер дат не злит | ≤ 10% попыток с «не разобрал» из всех reply'ев | `parse_failed / parse_attempts` |
| Точность срабатывания | ≥ 95% reminder'ов отправлены в окне ±60 сек от fire_at | log + manual check |
| Auto-done не злит | ≤ 5% юзеров отключают фичу через `/tz` или жалуются | manual / surveys |

**Hypothesis:**
> *Юзеры, которые раньше теряли дедлайны из своих Saved Messages, начнут использовать BookmarkBrain как single inbox для «надо сделать» когда увидят что бот сам предлагает напомнить — без переключения в календарь.*
>
> *Узнаем правда ли это, когда: ≥ 30% активных юзеров создадут хотя бы один reminder в первую неделю И ≤ 10% reply'ев получат «не разобрал» от парсера.*

---

## Constraints & Assumptions

### Constraints

- **Stack:** PostgreSQL + arq cron + aiogram 3 (как и весь проект).
- **NL parser:** библиотека `dateparser` (PyPI, MIT, поддержка ru). Самописный regex отвергнут (см. ADR 0007 — parser choice).
- **Schema:** generic `scheduled_messages` с `kind` вместо specific `reminders` table — это инвестиция в Phase 6 reuse (digest, surfacing).
- **Timezone:** `users.timezone` поле + `/tz` команда обязательны в MVP (не отложены).
- **Idempotency:** CAS-update через `WHERE status='pending' RETURNING` — критично для multi-worker setup.

### Assumptions

- ≥ 50% сохраняемых заметок не имеют интенции — кнопка появляется НЕ всегда, не должна быть навязчивой.
- `dateparser` покрывает наши реальные кейсы из коробки. Edge case'ы лечим тонким wrapper'ом.
- Юзер активен в Telegram достаточно часто чтобы заметить reminder в течение 24ч (auto-done после 24ч — приемлемая дефолт).
- Multi-worker scaling в обозримой перспективе не нужен (один воркер справится с reminders + nudge + bookmark processing).

---

## Out of Scope

Явно НЕ строим в Phase 2.5:

- ❌ **Recurring reminders** («каждый понедельник», «каждый месяц») — Phase 6.
- ❌ **Множественные reminders на один bookmark** («за день и в день») — один на bookmark в MVP, оценить нужду по фидбеку.
- ❌ **Список активных reminders** командой `/reminders` — добавится позже как фича Mini App.
- ❌ **Редактирование fire_at после создания** — только cancel + new (через Продлить).
- ❌ **Кастомные snooze-кнопки** (`+1ч`, `+1 неделя` и т.д.) — только одна кнопка `Продлить` с reply.
- ❌ **Приоритеты, цвета, теги для reminders** — overengineering для MVP.
- ❌ **Quiet hours** — бот шлёт честно по времени, юзер сам ставил.
- ❌ **ML-классификатор намерения** — Phase 4 (Learning Mechanisms), feedback loop.
- ❌ **Reminder без bookmark** («просто напомни через час, без заметки») — Phase 6 или never, мы не Apple Reminders.
- ❌ **Push в silent mode для confirm-кнопки** — silent юзер пишет явно, кнопка-предложение не показывается.

---

## Dependencies

### Внутренние

- ✅ Worker `_send_message` helper в `worker.py` (используется в stale_list_nudge).
- ✅ Redis state store (`bot/state_store.py`) — паттерн nudge:{...} ключей.
- ✅ Inline callback паттерн (`bot/handlers/tasks.py` — `tg:`, `tldm:`, `tlds:` callbacks).
- ✅ AI bookmark processor pipeline (`backend/app/services/bookmark_processor.py`).
- ⚠️ `users.timezone` колонка — **новая миграция**.
- ⚠️ `scheduled_messages` таблица — **новая миграция**.

### Внешние

- 📦 `dateparser>=1.2` — добавить в `backend/requirements.txt`.
- 📦 `python-zoneinfo` — стандартная библиотека Python 3.9+ (уже доступна).

### Code reuse

| Что переиспользуем | Откуда |
|---|---|
| Pattern «cron шлёт сообщение → bot reads reply через Redis-ключ» | `stale_list_nudge` + `nudge:{...}` |
| Inline callback parsing | `bot/handlers/tasks.py` |
| Date parsing помощники (расширим/заменим) | `bot/handlers/tasks.py::_parse_date` |
| Worker cron registration | `backend/app/worker.py::WorkerSettings.cron_jobs` |
| AI pipeline hook (после processing) | `bookmark_processor.process_bookmark` |

---

## Связанные документы

- [[ROADMAP-2026-05.md]] — секция Phase 2.5
- [[ARCHITECTURE.md]] — общая архитектура backend + worker + bot
- [[SPEC.md]] — продуктовый контекст BookmarkBrain
- [[BOT-UX.md]] — правила clean chat и реакций
- [[decisions/0006-scheduled-messages.md]] — будет создан как ADR при реализации (generic schema)
- [[decisions/0007-dateparser.md]] — будет создан как ADR при реализации (NL parser choice)
- [[Phase 1.5B Stale List Nudge]] — twin-feature, общий паттерн worker→bot push
- [[Phase 6 Proactivity 1.0]] — будущий потребитель `scheduled_messages.kind`

---

## Открытые вопросы (нерешённые)

- [ ] **Команда `/tz` — формат ввода.** `Europe/Moscow` (IANA) или дружелюбное «MSK / Калининград / Самара»? IANA — robust но не интуитивно. Список городов — UX-friendly но maintenance.
- [ ] **`scheduled_messages.kind='nudge'` для cleanup кнопок** или просто arq deferred job? Deferred проще для MVP, но не пишется в БД и не даёт visibility.
- [ ] **Миграция существующего `stale_list_nudge`** на `scheduled_messages` — сейчас или Phase 6? MVP — оставить как есть, Phase 6 унифицировать.
- [ ] **Что показывать в reminder-сообщении** если bookmark.summary длинный (> 200 символов)? Truncate с «...» или показывать оригинальный raw_text? MVP — summary с truncate.

---

*Готов к Plan→Epic transition. Команда: «turn the reminders-mvp PRD into an epic».*
