# PRD: Phase 2.6 — Reminders × Task Lists

**Статус:** v2 — все open Q закрыты, готов к T1+T2
**Дата:** 2026-05-14
**Фаза:** Phase 2.6
**Зависит от:** Phase 2.5 Reminders MVP (мержен, в проде)
**Оценка:** ~12 часов работы (2–3 dev-сессии)
**Bead:** `bookmark-brain-8yn`

---

## Problem Statement

После shipping Phase 2.5 (Reminders MVP) обнаружились пробелы в реальном использовании:

1. **«Завтра мне надо сделать контрольную, ещё тесты Eltex, ещё подготовка к сессии»** — длинное сообщение с несколькими задачами и датой попадает в обычный bookmark-flow. Strong-intent не срабатывает (ключевое слово «надо» не в начале), AI weak-intent изредка предлагает кнопку «🔔 Создать напоминание?». Результат: юзер не получает напоминаний для multi-task сообщений.

2. **«Сделай напоминание»** — explicit-команда не распознаётся. Она не в strong-intent словаре (`надо/нужно/не забыть/срочно/обязательно`), не команда (`/remind`). Идёт в save_yes/no flow и юзер вынужден отказаться.

3. **Task lists и reminders живут отдельно.** Сейчас task_list — это checklist без понятия «дедлайн на пункт». Reminders — отдельная сущность. Если в списке есть пункт «контрольная завтра» — он живёт как чекбокс, без напоминания.

## Evidence

- Live screenshot (2026-05-14, юзер @testuser в проде @N0teeBot): длинное сообщение с 4 задачами + «Сделай напоминание» → бот молча сохраняет, не предлагает reminder
- Live screenshot Phase 2.5 повторный баг: «надо купить молока завтра утром» → strong-flow, click 🔔, reply «Завтра утром» → ModuleNotFoundError в `from backend.app.services.nl_date` (см. commit 8325113)
- Юзер прямо просит: «1. Список с per-item датами → напоминания. 2. Простой remind работает. 3. Составной remind — большое сообщение целиком как один reminder.»

## Proposed Solution

Расширить save-flow тремя классификациями (определяет AI на этапе обработки bookmark'а):

| reminder_form | Триггер | Что происходит |
|---|---|---|
| `task_list_with_reminders` | 2+ даты в сообщении OR multi-item с датами (≥1) | Создаём task_list + per-item reminders для пунктов с датами |
| `single_reminder` | 1 дата, single statement OR explicit «сделай напоминание» | Один reminder на текст |
| `composite_reminder` | 1 дата, multi-statement (несколько пунктов в тексте), не классифицируется как task_list | Один reminder на весь текст |
| `none` | 0 дат, single item | Обычная закладка (как сейчас) |
| `task_list_no_reminders` | 0 дат, multi-item | Task_list без reminder'ов (как сейчас) |

## Key Hypothesis

> Мы верим, что разделение reminder'ов на 3 формы (per-item / single / composite) с AI-классификацией дат закроет 80% юзкейсов «у меня список дел, напомни мне про важное» без явных команд.
>
> Знаем что прав, если: 7 из 10 длинных сообщений с датами в течение недели после деплоя создают reminder без отмены юзером.

## What We're NOT Building

- **Per-item reply «напомни про пункт 3 завтра»** — сложный UX, отдельная итерация
- **Reminder на весь task_list одним временем** (Case 1d из brainstorm) — конфликтует с pinned list UX
- **Recurring reminders** («каждый понедельник в 9») — Phase 3+
- **Cross-language reminders** — пока только русский
- **AI-suggestion даты когда юзер не написал явно** («контрольная скоро» → AI ставит «послезавтра»?) — нет, только явные

## Success Metrics

| Метрика | Цель | Как измеряем |
|---|---|---|
| Reminders созданы из длинных сообщений | 70%+ когда есть дата | `payload.source IN ('task_list_per_item', 'composite_reminder', 'single_reminder_long')` / total long messages с датой |
| False positive rate (reminder отменён юзером в течение 1 мин) | <15% | `DELETE /reminders/{id}` через <60с после CREATE |
| AI date extraction accuracy | >90% правильных дат | Ручная разметка 30 случаев после недели проды |
| «Сделай напоминание» reply trigger покрытие | 100% когда есть reply на bookmark/task_list | Логи: `explicit_reminder_trigger` count vs `should-have-fired` (ручная разметка) |

---

## Users & Context

**Primary User**
- **Кто:** студент / разработчик, ведёт планы и заметки в боте
- **Текущее поведение:** длинные сообщения с задачами и датами идут просто в /list, без напоминаний
- **Триггер:** хочет напоминания на дедлайны без явных команд («контрольная завтра» должно работать)
- **Success state:** на дату/время напоминания приходит сообщение с текстом конкретной задачи

**Job to Be Done**
> Когда у меня список дел и часть из них с датами, я хочу что чтобы бот сам понял и поставил напоминания, чтобы я не забыл важные дедлайны.

---

## Solution Detail

### Detection rules (финальный после brainstorm v2)

**Date extraction strategy:** regex first (надёжно), AI только для split на items.

GigaChat (текущий провайдер) не возвращает откалиброванный confidence — поэтому confidence сейчас остаётся как **slot в schema** для будущего DeepSeek/Claude.

```
Pipeline:
  1. AI (GigaChat) split сообщение на items[]: list of {text, raw_date_phrase}
  2. Regex extract date из raw_date_phrase: nl_date.parse() (уже есть из Phase 2.5)
  3. AI отдельно отмечает single_statement: True/False
  4. Worker применяет detection rules ниже
```

**structured_data контракт:**
```json
{
  "items": [
    {"text": "контрольная по дискретной", "raw_date_phrase": "завтра"},
    {"text": "тесты Eltex", "raw_date_phrase": null},
    {"text": "сессия", "raw_date_phrase": null}
  ],
  "single_statement": false,
  "reminder_form": "task_list_with_reminders"
}
```

Worker берёт `raw_date_phrase`, прогоняет через `nl_date.parse()` → получает UTC datetime или fail → определяет финальный reminder_form по правилам ниже.

**Правила (применяются в порядке):**

1. **Strong-intent (Phase 2.5) — single-statement only**
   - Сообщение начинается с `надо/нужно/не забыть/срочно/обязательно/обязан`
   - И `single_statement == True`
   - → Старый 3-button flow (🔔 / 📝 / ✕)
   - **Если в тексте уже есть час или часть суток** → пропустить 3-button, создать reminder молча (универсальное правило времени, см. ниже)

2. **2+ дат → `task_list_with_reminders` молча**
   - Создать task_list + reminders per dated item

3. **1 дата + multi-item → кнопки «📋 Список / 🔔 Напоминание / ✕»**
   - «📋» = task_list_with_reminders на 1 пункт + остальные как чекбоксы
   - «🔔» = composite_reminder на весь текст
   - «✕» = просто bookmark

4. **1 дата + single-item → `single_reminder`**

5. **0 дат + multi-item → task_list_no_reminders** (как сейчас)

6. **0 дат + single-item → обычный bookmark** (как сейчас)

### Универсальное правило времени (применяется ВЕЗДЕ где создаём reminder)

| В тексте | Действие |
|---|---|
| **Конкретный час** («в 9», «в 18:30», «через час», «завтра в 9 утра») | Создаём молча, показываем «🔔 Напомню завтра в 9:00» |
| **Часть суток без часа** («утром», «вечером», «днём», «ночью», «в полдень») | Создаём молча, подставляем default: утром=9:00, днём=14:00, вечером=18:00, ночью=22:00, полдень=12:00 |
| **Только дата без часа** («завтра», «в пятницу», «15 мая») | Спрашиваем Reply: «Во сколько напомнить? Reply на это сообщение со временем» |
| **Только намерение без даты** («надо купить молоко») | Phase 2.5 strong-intent 3 кнопки 🔔/📝/✕ |

Уже реализовано частично в `nl_date.py::_preprocess_short_time` (`утром→9:00`, `вечером→18:00`). Расширить:
- `nl_date.parse()` возвращает новый статус `NEEDS_HOUR` если есть дата но нет часа — bot спрашивает Reply
- Все handler'ы (strong, weak, per-item, composite) используют единый flow.

### Confidence threshold (slot на будущее)

- AI **может** вернуть `confidence: 0.0-1.0` для каждой даты (опционально, для DeepSeek/Claude)
- Сейчас (GigaChat): не используется, regex детерминирован
- Когда подключим DeepSeek/Claude — `REMINDER_CONFIDENCE_THRESHOLD = 0.7`: выше → молча, ниже → кнопка подтверждения

### Explicit trigger «сделай напоминание»

Поддерживаем 2 формы (a и c, без b — too magic).

**(a) Reply на сохранённый bookmark / task_list:**
- Юзер reply'ит сообщение бота с текстом «сделай напоминание» / «напомни» / «поставь reminder»
- Если reply на bookmark → создаём reminder на этот bookmark по универсальному правилу времени
- Если reply на task_list **с датами** → создаём per-item reminders для dated items (как `task_list_with_reminders`)
- Если reply на task_list **без дат** → создаём **composite reminder на весь список**, по универсальному правилу времени. Если хочется per-item позже — отдельным NL-edit («перенеси контрольную на пятницу» добавит per-item; см. cascade ниже)

**(c) Inline команда с текстом:**
- «сделай напоминание купить молоко завтра» = аналог `/remind купить молоко завтра`
- По универсальному правилу времени

### Task_list edit с reminder'ами

- **Удалил пункт где был reminder** → отменить reminder молча
- **Добавил пункт с датой** через NL-edit («добавь врач в пятницу») → создать reminder молча, в reply бот пишет «✅ +1 напоминание»
- **Изменил дату пункта** через NL-edit («перенеси контрольную на пятницу») → обновить reminder, в reply «✅ перенёс напоминание»

### Show-time UX (что юзер видит когда reminder сработал)

| Тип | Что показывается |
|---|---|
| `single_reminder` | Текст напоминания + кнопки Выполнено / Продлить |
| `composite_reminder` | **Весь** текст оригинального сообщения + кнопки |
| Per-item из task_list | **Текст пункта** + ссылка «📋 Открыть список» + кнопки Выполнено / Продлить |

---

## Open Questions — все закрыты

- [x] **Q-OPEN-1 (AI provider)**: GigaChat не калибрует confidence → используем **regex для дат** (надёжно), AI только для **items split**. Confidence — slot в schema на будущее (когда подключим DeepSeek/Claude).
- [x] **Q-OPEN-2 (cascade lookup)**: Связь reminder↔item только в **payload reminder'а** (`task_list_id` + `item_index`). Task_list ничего не знает про reminders — search через `SELECT * FROM reminders WHERE payload->>'task_list_id' = '...' AND payload->>'item_index' = '...'`.
- [x] **Q-OPEN-3 («сделай напоминание» reply на task_list без дат)**: composite reminder на весь список. Можно потом менять отдельные пункты через NL-edit (с конфликт-разрешением кнопкой если уже есть composite).
- [x] **Q-OPEN-4 (strong-intent priority)**: Универсальное правило времени (выше) решает конфликт. Strong-intent → 3 кнопки **только** если в тексте нет часа/части суток. Иначе создаём reminder молча.

---

## Technical Approach

**Feasibility:** MEDIUM
- AI extension: расширить промпт `ai_classifier.py` чтобы возвращал items + reminder_form
- DB: миграция на `reminders` — добавить `payload.task_list_id`, `payload.item_index`, `payload.confidence`
- Bot handlers: новый flow в worker._post_save_actions для классификации, новые кнопки в `bot/handlers/save_buttons.py`
- Bot state: chat-level `last_bookmark:{chat_id}` (TTL 5 мин) для new-message trigger

**Architecture Notes**
- Reminder.payload расширяется без breaking change (JSONB)
- Task_list edit cascade — через event/hook в `task_list_editor.py` (добавить колбэки on_item_add/delete/update_date)
- Confidence threshold живёт в `app/config.py` как `REMINDER_CONFIDENCE_THRESHOLD = 0.7` (легко перекалибровать)

**Technical Risks**

| Risk | Likelihood | Mitigation |
|---|---|---|
| AI возвращает не-JSON / неверный schema | M | Pydantic-валидация ответа + fallback на старый flow |
| DeepSeek confidence не откалиброван (всегда 0.95) | H | Если не работает — fallback на regex date detection (Q6 вариант c) |
| Telegram editMessageReplyMarkup race с пользовательскими click | L | Уже есть anti-double через Redis (Phase 2.5) |
| Per-item reminders создаются дублями при retry | M | Idempotency через unique `(bookmark_id, item_index)` constraint |

---

## Implementation Phases

| # | Phase | Описание | Status | Parallel | Depends | PRP |
|---|-------|----------|--------|----------|---------|------|
| 1 | AI Classifier extend | `ai_classifier.py` + промпт: возвращать items[], confidence, reminder_form | pending | with 2 | - | - |
| 2 | DB migration | `reminders.payload` schema: task_list_id, item_index, confidence | pending | with 1 | - | - |
| 3 | Save-flow router | worker.\_post_save определяет reminder_form, маршрутизирует | pending | - | 1, 2 | - |
| 4 | 3-button «1 дата + multi-item» | UI + callbacks в `bot/handlers/save_buttons.py` | pending | with 5 | 3 | - |
| 5 | Per-item reminders create | для task_list_with_reminders — auto-create reminders на dated items | pending | with 4 | 3 | - |
| 6 | Composite reminder create | для composite_reminder — один reminder с full text | pending | - | 3 | - |
| 7 | «Сделай напоминание» reply | `tasks.py::msg_nl_edit_on_reply` ловит «напомни» — Case a | pending | with 8 | 3 | - |
| 8 | «Сделай напоминание» inline | `start.py::handle_text` ловит «сделай напоминание <текст>» — Case c | pending | with 7 | 3 | - |
| 9 | Task_list edit cascade | NL-edit обновляет связанные reminders (add/delete/update_date) | pending | - | 5 | - |
| 10 | Confidence threshold UX | Кнопка подтверждения если confidence < 0.7 | pending | - | 5, 6 | - |
| 11 | Tests + integration smoke | Unit + integration на реальной Postgres | pending | - | 4,5,6,7,8,9,10 | - |
| 12 | ADR + docs update | ADR 0009 (3-form reminders), BOT-COMMANDS, TROUBLESHOOTING | pending | - | 11 | - |

### Parallelism Notes

- T1 (AI) и T2 (DB) — независимы, можно параллельно
- T4-T8 — после T3, между собой независимы (4,5,7,8)
- T9-T10 — после core flow готов
- T11-T12 — финал

---

## Decisions Log

| Decision | Выбор | Альтернативы | Rationale |
|---|---|---|---|
| Date extraction | Regex (nl_date.parse) + AI items split | Pure AI / Pure regex | Регекс детерминирован, GigaChat не калибрует confidence. AI остаётся для split на пункты. |
| Confidence threshold | Slot в schema, не используется (GigaChat). 0.7 когда подключим DeepSeek/Claude | Сразу threshold / never | Текущий LLM не отдаёт confidence — не можем фильтровать. Slot заранее под будущий апгрейд. |
| Time-of-day handling | Универсальное правило: час → молча, часть суток → default 9/14/18/22, только дата → Reply ask | Always-ask / Always-silent | Юзер явно зафиксировал на brainstorm |
| 2+ dates classification | Молча в task_list_with_reminders | Спросить кнопками | Юзер явно дал контекст, можно не переспрашивать |
| 1 date + multi-item | Кнопки 📋/🔔/✕ | Авто-выбор по эвристике | Юзер сам знает что хотел |
| Task_list edit on reminder | Cascade молча | Спрашивать каждый раз | Не отвлекать на NL-edit |
| Strong-intent (Phase 2.5) | Остаётся для single-statement | Заменить новым flow | Минимальный регресс, простой случай — простой UI |
| Weak-intent (Phase 2.5) | Остаётся для коротких bookmark'ов | Заменить полностью | Не конфликтует с новыми case'ами |

---

## Research Summary

**Brainstorm session (2026-05-14):**
- Юзер указал 3 чёткие категории: список с per-item датами, базовый remind, composite remind
- Q6 (date detection): юзер выбрал AI ((b))
- Q7 (confidence): юзер согласился с threshold-based ((c)), запросил пояснение confidence — дано на конкретных примерах
- Q8 (edit cascade): silent on update, reply-feedback с пометкой «+1 напоминание»
- Q9 (weak-intent конфликт): keep old button for short, new buttons for long ((a))
- Q10 (strong-intent конфликт): single-statement → old strong, multi → new flow ((c))

**Related ADRs:**
- ADR 0008 — Phase 2.5 three-flow architecture (basis для extension)
- Будет создан ADR 0009 — Three-form reminders (per-item / single / composite)

---

*Generated: 2026-05-14*
*Status: APPROVED — все open Q закрыты юзером 2026-05-14, готов к T1+T2*
