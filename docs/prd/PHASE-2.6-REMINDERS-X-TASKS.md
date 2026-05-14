# PRD: Phase 2.6 — Reminders × Task Lists

**Статус:** draft v1 — после brainstorm-сессии с юзером
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

### Detection rules (финальный после brainstorm)

```
AI получает сообщение → возвращает structured_data:
{
  "items": [
    {"text": "контрольная по дискретной", "date_iso": "2026-05-15T00:00:00", "confidence": 0.9},
    {"text": "тесты Eltex", "date_iso": null, "confidence": null},
    {"text": "сессия", "date_iso": null, "confidence": null}
  ],
  "single_statement": false,
  "reminder_form": "task_list_with_reminders"  // или single_reminder / composite_reminder / task_list_no_reminders / none
}
```

**Правила (применяются в порядке):**

1. **Strong-intent (Phase 2.5) — single-statement only**
   - Сообщение начинается с `надо/нужно/не забыть/срочно/обязательно/обязан`
   - И `single_statement == True` (один пункт)
   - → Старый 3-button flow (🔔 / 📝 / ✕)

2. **2+ дат → `task_list_with_reminders` молча**
   - Создать task_list + reminders per dated item (confidence > 0.7) или с подтверждением (≤ 0.7)
   - В save-ответе: «📋 Список сохранён. 🔔 +N напоминаний»

3. **1 дата + multi-item → кнопки «📋 Список / 🔔 Напоминание / ✕»**
   - «📋» = task_list_with_reminders на 1 пункт + остальные как чекбоксы
   - «🔔» = composite_reminder на весь текст
   - «✕» = просто bookmark, ничего не предлагать

4. **1 дата + single-item → `single_reminder`**
   - Молча создаём reminder
   - В save-ответе: «🔔 Напомню завтра в 9»

5. **0 дат + multi-item → task_list_no_reminders** (как сейчас)

6. **0 дат + single-item → обычный bookmark** (как сейчас, weak-intent offer если AI намекнул)

### Confidence threshold

- AI возвращает `confidence: 0.0-1.0` для каждой даты
- Calibration: «1.0 — дата явно прописана («завтра в 9»). 0.7 — день недели без года («в четверг»). 0.5 — неоднозначно («скоро», «к маю»). <0.3 — догадка»
- Threshold `0.7`: выше → создаём молча, ниже → кнопка подтверждения

### Explicit trigger «сделай напоминание»

**(a) Reply на сохранённый bookmark / task_list:**
- Юзер reply'ит сообщение бота с текстом «сделай напоминание» / «напомни» / «поставь reminder»
- Если reply на bookmark → создаём reminder на этот bookmark, спрашиваем время (Reply)
- Если reply на task_list → берём пункты с датами → создаём per-item reminders. Если дат нет — спрашиваем «напомни о всём списке когда?»

**(c) Inline команда с текстом:**
- «сделай напоминание купить молоко завтра» = `/remind купить молоко завтра`
- Если время есть — создаём молча, иначе спрашиваем Reply

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

## Open Questions

- [ ] **Q-OPEN-1**: AI confidence — реально ли DeepSeek возвращает откалиброванную вероятность? Возможно нужен self-consistency (3 sampling и majority vote)
- [ ] **Q-OPEN-2**: Когда меняем дату пункта через NL-edit, как находим связанный reminder? По `bookmark_id` + `item_index`? Или хранить reminder_id в task_list payload?
- [ ] **Q-OPEN-3**: «сделай напоминание» reply на task_list где НЕТ дат — что делать? Спросить «на какой пункт?» или создать composite_reminder для всего списка?
- [ ] **Q-OPEN-4**: Конфликт со strong-intent для пограничных случаев. «Надо контрольную завтра» — single-statement, начинается с «надо», есть дата. По правилу #1 → strong-intent. Но AI может классифицировать как `single_reminder`. Кто wins? Решение: правило #1 имеет приоритет.

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
| Date extraction | AI (DeepSeek в structured_data) | Regex / Hybrid | AI уже разбирает каждое сообщение, добавить поле дёшево |
| Confidence threshold | 0.7 калибруемый | 0.5 / 0.9 / без threshold | Баланс false-positive vs пропусков |
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
*Status: DRAFT — ждёт финального ревью пользователем перед началом T1*
