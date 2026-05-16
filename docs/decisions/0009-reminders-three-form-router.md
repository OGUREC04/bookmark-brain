# ADR 0009 — Three-form Reminders × Task Lists (Phase 2.6)

**Дата:** 2026-05-14
**Статус:** Accepted (in production after Phase 2.6 deploy)
**Связано:** ADR 0008 (Phase 2.5 three-flow), PRD `docs/prd/PHASE-2.6-REMINDERS-X-TASKS.md`

## Контекст

Phase 2.5 ввела одну форму reminder'а — «один text + один fire_at»,
через 3 пути входа (strong-intent / weak-intent / explicit `/remind`).
На проде проявились пробелы:

1. **Long messages с 2+ задачами и датами** — попадали в bookmark-flow,
   weak-intent изредка предлагал кнопку, но юзер не получал per-task reminders.
2. **«Сделай напоминание»** в свободном тексте — не триггер для Phase 2.5
   strong-flow (нет в списке маркеров) → шёл в bookmark с предложением
   `save_yes/save_no` и обычно отклонялся юзером.
3. **Task_list и reminders жили отдельно** — пункт «контрольная завтра»
   в чек-листе оставался чекбоксом, никакого напоминания.

## Решение

Расширить save-flow тремя формами reminder'а, выбираемыми **роутером** на
основе AI-extracted items + nl_date-resolved fire_at:

| reminder_form | Триггер (детектируется в router) | Эффект |
|---|---|---|
| `single_reminder` | 1 dated item, single_statement=true | Auto-create один reminder |
| `task_list_with_reminders` | 2+ dated items | Auto-create N reminders, по одному на dated item |
| `composite_reminder` | 1 date + multi-item, юзер выбрал 🔔 | Один reminder на весь raw_text |
| `needs_button_choice` | 1 date + multi-item, ждём юзера | 3 кнопки «📋/🔔/✕» в чате |
| `needs_hour` | дата без часа | Reply-ask «во сколько?» |
| `strong_intent_3button` | strong-intent, single, без dated | Phase 2.5 flow (без изменений) |
| `task_list_no_reminders` | 0 дат, multi-item | Phase 2 task_list (без изменений) |
| `none` | прочее | Обычный bookmark |

## Архитектура

**Pipeline (save-flow):**

```
1. BookmarkProcessor (backend/app/services/bookmark_processor.py)
   ├─ classification = ai_classifier.classify(text)
   │  → AIClassification.reminder_items[], single_statement, reminder_form_hint
   │
   ├─ task_list_detector (Phase 2) — regex/heuristic, не AI
   │
   └─ reminder_router.route(text, classification, user_tz)
       → RouterDecision(form, items[ResolvedItem], strong_intent, explicit)
          persisted в bookmark.structured_data.reminder_decision

2. Worker._dispatch_reminder_decision (backend/app/worker.py)
   ├─ TASK_LIST_WITH_REMINDERS → reminder_creator.create_per_item_reminders
   ├─ SINGLE_REMINDER → reminder_creator.create_single_reminder
   ├─ NEEDS_BUTTON_CHOICE → _send_choice_ui (3-button via Telegram)
   ├─ NEEDS_HOUR → _send_hour_ask (reply-pending state)
   └─ остальные → fallback на legacy _maybe_offer_reminder

3. Bot reminder_choice.cb_choice_{list,reminder,dismiss}
   → POST /api/v1/reminders/apply-decision/{bid}?form=...
   → reminder_creator + idempotency-flag
```

**Date extraction strategy:** regex first, AI только для split.
GigaChat (текущий провайдер) не калибрует confidence → доверять регекс
надёжнее. `nl_date.parse(raw_date_phrase)` → ParseStatus + UTC datetime.

**Universal time rule (см. PRD Solution Detail):**
- Час («в 9», «18:30») → создаём молча
- Часть суток («утром», «вечером») → default 9:00 / 14:00 / 18:00 / 22:00
- Только дата → NEEDS_HOUR (Reply-ask)
- Только намерение без даты → Phase 2.5 STRONG_INTENT_3BUTTON

## Альтернативы

| Альтернатива | Почему отвергнута |
|---|---|
| Один reminder на task_list (общая дата) | Конфликтует с pinned list UX, ломает existing Phase 2 |
| Spec'ифичная таблица `reminders` отдельно от `scheduled_messages` | Дублирование схемы. Phase 6 переиспользует kind enum |
| AI extraction дат с confidence threshold | GigaChat не калибрует confidence; deepseek/claude не подключены |
| Inline 4-button «список/один/оба/✕» | Слишком много опций для one-tap UX |

## Trade-offs / открытые вопросы

- **Idempotency** реализована через `bookmark.structured_data.reminder_decision_applied`.
  Backend apply-decision endpoint возвращает 409 если флаг уже стоит. Bot 3-button
  click handler делает atomic GETDEL state → второй клик возвращает «устарело».
- **Cascade на NL-edit task_list** (T9): match по нормализованному тексту пункта.
  Не идеально — переименование меняет матч. Альтернатива (item_index) хуже
  потому что NL-edit сдвигает индексы при del/add.
- **Confidence-threshold UX** оставлен как slot в schema (`ReminderItem.confidence` —
  TODO в Phase 3). Сейчас GigaChat → regex детерминирован, не нужен.

## Связанная инфра

- `backend/app/services/reminder_router.py` — pure routing
- `backend/app/services/reminder_creator.py` — фабрика ScheduledMessage
- `backend/app/services/reminder_cascade.py` — каскад на NL-edit
- `backend/app/api/reminders.py::apply_reminder_decision` — endpoint для bot 3-button
- `bot/handlers/reminder_choice.py` — callbacks rch_list / rch_rem / rch_x
- `bot/handlers/reminders.py::process_explicit_remind_args` — T8 trigger (shared с `/remind`)
- `bot/handlers/tasks.py::_handle_remind_on_task_list` — T7 reply trigger

## Тесты

- `tests/test_nl_date.py` — 47 (включая NEEDS_HOUR rename)
- `tests/test_explicit_remind_trigger.py` — 17 (T7/T8 regex)
- `backend/tests/test_ai_classification_schema.py` — 5 (T1)
- `backend/tests/test_reminder_router.py` — 15 (T3)
- `backend/tests/test_reminder_creator.py` — 12 (T5/T6)
- `backend/tests/test_reminder_cascade.py` — 15 (T9)
- `backend/tests/test_phase26_scenarios.py` — 7 (T11 e2e)

Итого Phase 2.6: ~118 unit/scenario tests, общий test suite ≥479 passed.
