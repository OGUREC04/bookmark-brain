# PRD: Reminders MVP

**Статус:** v2.1 — после ревью трёх агентов (architect / planner / silent-failure-hunter)
**Дата v1:** 2026-05-09
**Дата v2:** 2026-05-10
**Дата v2.1:** 2026-05-10 (вечер)
**Фаза:** Phase 2.5
**Оценка v2.1:** ~2 dev-days (12–14 часов) к уже сделанным 7/10 задачам

> ⚠️ **v2.1 = v2 + 14 правок после ревью трёх агентов.** Ключевые добавления к v2: отдельный router для strong-flow (не правим start.py), anti-double-offer flag, snapshot IDs для `/reminders` reply, fresh-migration в live-smoke, фиксы 5 silent-failure багов в уже мерженом v1 коде, недостающие куски (bot menu, /help, ADR 0008, onboarding tips, integration-tests на реальной Postgres, Definition of Done на каждую задачу). Старая часть PRD (T1–T8 уже реализованы по v1) остаётся в истории.

---

## Architecture v2: reminders ≠ bookmarks (решение после live-теста)

### Что показал live E2E

После мерджа T1–T8 (PR #5/6/7/8) прогнали **первый живой тест**. Юнит-тесты с моками пропустили **четыре проблемы**:

1. **CRITICAL**: `ScheduledMessage.kind/status` объявлены `String(32)`, но Postgres-миграция создала их как ENUM. Каждый ORM `INSERT` падал с ошибкой `column "kind" is of type scheduled_kind but expression is of type character varying`. (Фикс: PR #9 — `postgresql.ENUM(create_type=False)`.)
2. **`_maybe_offer_reminder` пропускал silent-mode**: дефолт `silent_mode=True` для всех юзеров → 100% не видели offer. (Фикс: убран silent-gate, есть в working tree.)
3. **«завтра утром» не парсится**: `dateparser` не поддерживает «утром» без явного времени. NEEDS_TIME → юзер фрустрирован.
4. **Reminders попадают в архив закладок**: «надо купить мясо» сохраняется как bookmark, через неделю «надо купить мясо» снова — dedup-алерт. Юзер: «напоминания и заметки должны разделяться».

### Корневая причина: смешение двух разных сущностей

| | Закладка | Напоминание |
|---|---|---|
| Цель | архив | действие |
| Жизненный цикл | вечно | до выполнения / 24ч |
| Идемпотентность | дубль = алерт | дубль = ОК (повторное событие) |
| AI-обработка | да | нет |
| Поиск | vector + text | по списку |
| Smart blocks | да | нет |

В v1 каждый «надо X» проходил через AI и dedup, копился в `bookmarks`, мешался с архивом. v2 разделяет три ветки.

### Три потока в v2

#### Поток 1: `/remind` — explicit (новый, T11)

```
Юзер: /remind купить хлеб завтра в 9
   ↓
Бот: 🔔 Напомню 11.05 09:00 — «купить хлеб»
```

- Закладка **не** создаётся
- AI **не** запускается
- Управление через `/reminders` (T12)
- Без аргументов `/remind` — справка с примерами (по образцу `/create` из task_list)
- Без времени `/remind купить хлеб` — бот спрашивает время через reply

#### Поток 2: Implicit **strong** intent (новый, T13)

«**Надо** купить хлеб», «**Нужно** позвонить маме», «**Не забыть** оплатить счёт», «**Срочно** доделать отчёт».

```
Юзер: «надо купить хлеб»
   ↓
[регекс детектор по первым 50 символам, ДО AI]
   ↓
strong intent ✓ → AI пропускается
   ↓
Бот (👀):
Это напоминание или заметка?

  [🔔 Напомнить] [📝 Заметка] [✕]
```

- 🔔 → reply со временем → reminder, **без** закладки
- 📝 → отправить в обычный AI-flow → закладка как обычно, **без** второго оффера
- ✕ → удалить prompt-сообщение, **ничего** не сохранять
- Timeout 1ч → state в Redis протухает, кнопки при позднем клике отвечают «устарело»

**Архитектурное решение (по architect-review):** strong-flow — это **отдельный router** (`reminders_strong.router`), зарегистрированный в `bot/main.py` ПЕРЕД `start.router`. Filter:

```python
F.text & ~F.text.startswith("/") & ~F.reply_to_message & is_strong_intent_filter
```

Если match — handle 3-button prompt. Если no match — `raise SkipHandler` → событие падает дальше на `start.handle_text` без изменений. **Не трогаем `start.py` и его 788 строк** — снимаем риск сломать silent / dedup / voice / document / task_list пути.

**Anti-double-offer (по architect-review):** при выборе «📝 Заметка» сообщение идёт в обычный AI-flow. AI обработает и worker `_maybe_offer_reminder` снова найдёт `reminder_intent=true` → офер появится **второй раз** на одно сообщение. Решение: при срабатывании strong-detector ставим Redis-флажок:

```
strong_handled:{chat_id}:{source_msg_id} → "1"   (TTL 5 минут)
```

Worker `_maybe_offer_reminder` перед отправкой офера проверяет наличие флажка — если есть, skip. Альтернатива (передать `source="strong_intent_note"` в `payload` закладки) сложнее в реализации, выбираем Redis-флажок.

#### Поток 3: Implicit **weak** intent (текущий v1 flow)

«Купить чайник», «Позвонить врачу», «Погладить рубашку» — глагол без сильного маркера.

```
Юзер: «купить чайник»
   ↓
weak intent → AI обрабатывает закладку
   ↓
Бот: 👍 (закладка сохранена)
   ↓
Бот:  [🔔 Создать напоминание?] [✕]
```

- 🔔 → reply со временем → reminder связан с закладкой (`bookmark_id`)
- ✕ → закладка остаётся, без reminder
- Это **текущий** v1 flow, ничего не меняем кроме отказа от silent-gate

#### Поток 4: None intent

«Интересная статья», ссылки, мысли — обычная закладка, никакого offer'а.

### Сводная таблица по сценариям

| Ввод юзера | Закладка | Напоминание | Кнопок |
|---|---|---|---|
| `/remind купить X завтра в 9` | нет | ✓ | 0 |
| `/remind купить X` | нет | ✓ (после reply) | 0 |
| `/remind` | нет | нет | 0 (только справка) |
| «надо купить X» + 🔔 | нет | ✓ | 3→0 |
| «надо купить X» + 📝 | ✓ | нет | 3→0 |
| «надо купить X» + ✕ | нет | нет | 3→0 |
| «купить X» + 🔔 | ✓ | ✓ (linked) | 2→0 |
| «купить X» + ✕ | ✓ | нет | 2→0 |
| «Статья про React» | ✓ | нет | 0 |
| Сработавший reminder + ✅ | — | done | 2→0 |
| Сработавший reminder + 💤 | — | reschedule | 2→0 |

Максимум **3 кнопки** в одном месте (strong intent), везде остальное ≤ 2.

### Auto-detect времени в исходном тексте

Если юзер в strong-flow или `/remind` уже указал время (`«надо купить хлеб завтра в 9»` или `/remind купить хлеб завтра в 9`), бот **не спрашивает** «когда?» — сразу подтверждение:

```
Бот: 🔔 Напомню 11.05 09:00 — «купить хлеб»
```

Реализуется через `nl_date.parse()` на исходном тексте: если `ParseStatus.OK` → используем `dt`, остаток текста становится `payload.text`. Если `UNPARSEABLE/NEEDS_TIME` → классический «Когда напомнить?» через reply.

Парсер времени дополняется: «утром» → `09:00`, «днём» → `14:00`, «вечером» → `18:00`, «ночью» → `22:00`.

### Команды для управления

#### `/reminders` — список активных + история

```
🔔 Активные:
1. купить хлеб — 11.05 09:00
2. позвонить маме — 12.05 18:00
3. оплатить счёт — 15.05 12:00

Reply на это сообщение:
• «отмени 1»
• «перенеси 2 на 15:00»
• «перенеси 3 на завтра»
• «история» — выполненные
```

`/reminders история` — последние 20 завершённых (status=done/cancelled) за 30 дней, без действий, для справки.

NL-reply парсится так же как в `tasks.py` `msg_nl_edit_on_reply` — нумерация → action на reminder. Используется тот же `nl_date.parse()` для распознавания нового времени.

**Snapshot IDs (по architect-review):** в момент показа списка фиксируем порядок reminders в Redis:

```
reminders_list:{chat_id}:{prompt_msg_id} → ["uuid-A", "uuid-B", "uuid-C"]   (TTL 1ч)
```

NL-reply парсер: `«отмени 2»` → берёт индекс 2 → uuid-B → cancel by uuid. **Не пересчитывает позиции в момент reply** — иначе через 5 минут после показа, если первый reminder уже сработал и ушёл из активных, «отмени 2» отменит совсем не то.

Парсинг через **regex first**: `«отмени \d+»`, `«перенеси \d+ на ...»`, `«история»`. Покрывает 95%, дешёво и тестируемо. LLM-edit (как в `tasks.py`) — только на miss, для странных формулировок.

### Что меняется в схеме

`scheduled_messages.payload` уже jsonb — добавляем поля без миграции:
- `payload.text` — оригинальный текст напоминания (для отображения в `/reminders`)
- `payload.source` — `"explicit_remind"` | `"strong_intent"` | `"weak_intent"` (для аналитики)
- `payload.auto_done` — флаг авто-выполнения (уже есть, остаётся)

`bookmark_id` остаётся nullable: для strong и /remind = NULL, для weak = id закладки.

Никаких миграций БД не требуется — только код.

### Detector: какие триггеры strong

Регекс на нормализованный (lowercase) text, **только в начале** сообщения (первые 50 символов):

```
^(надо|нужно|не забыт[ьи]|срочно|ну[жн]но\s*бы|обяза(тельно|н))\b
```

Тестовые кейсы:
- ✓ «надо купить хлеб»
- ✓ «нужно позвонить маме»
- ✓ «Не забыть оплатить счёт»
- ✓ «срочно доделать отчёт»
- ✗ «купить хлеб» (нет маркера)
- ✗ «думаю надо как-то сделать» (маркер не в начале)
- ✗ «нужное направление» (полное слово другое)

Точное regex обсуждаем при реализации (T13). Главный принцип: **высокая точность, низкий recall** — лучше пропустить strong как weak, чем спросить «напоминание или заметка?» там где юзер не хотел никакого reminder'а.

### Edge cases (обсуждены)

| Кейс | Поведение |
|---|---|
| Юзер не нажал кнопку 1ч | Redis TTL чистит state → клик → «устарело». Ничего не сохранено. |
| Юзер нажал 🔔, не reply'нул со временем 1ч | Тот же TTL. Reminder не создан. Через час reply'нет — «устарело». |
| `/remind` с временем в прошлом | Ошибка «время в прошлом». Не создаётся. |
| `/remind` с невалидным временем | Бот: «не понял время. Примеры…», ждём reply. |
| `/remind` без аргументов | Справка, ничего не создаётся. |
| Reply попал на чужое сообщение бота (Telegram swipe-bug) | Если у того сообщения нет state → SkipHandler → стандартное «не нашёл». UX-проблема существует, не решаем в v2 (отдельная задача). |
| Дубль strong intent («надо купить мясо» дважды) | Каждый раз отдельный prompt с 3 кнопками. Юзер выбирает каждый раз. Никаких dedup-алертов. |
| Strong intent + время уже в тексте + 🔔 | Сразу подтверждение без вопроса «когда» (auto-detect). |
| Strong intent + 📝 (заметка) | Передаём в текущий AI-flow, силу intent игнорируем дальше. Закладка как обычно. |
| Юзер пишет команду `/list` пока висит strong-prompt | Команда обрабатывается, prompt остаётся висеть до click/timeout. |
| Конфликт с task_list reply (reminders router ДО tasks router) | Уже решено в v1: `SkipHandler` пропускает чужие reply'и. |

### Silent-failure фиксы в УЖЕ мерженом v1 коде (5 багов)

Найдены агентом `silent-failure-hunter`. Все — в проде, потенциально сломают фичу до релиза. Включаем в v2.1 PR.

#### F1: Permanent send failure → юзер не узнаёт

**Где:** `backend/app/worker.py` ~line 918, после `status='failed'`.

**Сейчас:** Reminder помечается failed, в логи пишется `logger.error`, юзер ждёт сообщение которое никогда не придёт.

**Фикс:**

```python
asyncio.create_task(_send_message(
    telegram_id,
    f"⚠️ Не удалось отправить напоминание «{payload_text[:60]}». "
    f"Попробуй создать заново через /remind."
))
```

#### F2: `FALLBACK_DEFAULT` ставит +24h без подтверждения

**Где:** `bot/handlers/reminders.py` line 292, обработка `ParseStatus`.

**Сейчас:** Юзер пишет «потом» / «ладно» в reply на «когда напомнить?» → `nl_date.parse()` возвращает `FALLBACK_DEFAULT` со временем `now + 24h`. Хендлер обрабатывает это **как `OK`** → молча ставит reminder на завтра.

**Фикс:** Отдельная ветка для FALLBACK_DEFAULT — спрашиваем явно:

```python
if result.status == ParseStatus.FALLBACK_DEFAULT:
    await message.answer(
        f"Не понял точное время. Поставить напоминание на "
        f"<b>{_format_fire_at(result.dt, user_tz_name)}</b>? "
        f"Reply «да» или укажи точнее.",
        parse_mode="HTML",
    )
    # Сохраняем pending-confirm состояние в Redis (TTL 5 минут).
    await store.store_reminder_fallback_pending(
        chat_id, message.message_id, pending_bid_or_snooze_id, result.dt.isoformat(),
    )
    return True
```

Дополнительная reply-ветка `«да»` / `«ага»` / `«ок»` подтверждает время. Любой другой текст → новый парсинг.

#### F3: Redis записывается ПОСЛЕ Telegram send → broken button

**Где:** `backend/app/worker.py` lines 738-762, `_maybe_offer_reminder`.

**Сейчас:** Сначала `_send_message(...)`, потом `redis.set(reminder_pending:...)`. Если Redis моргнул — кнопка в чате есть, клик не работает.

**Фикс:** Инвертировать порядок:

```python
# 1. Сохранить state в Redis (попадание в exception → не отправлять)
try:
    r = aioredis_from_url(settings.REDIS_URL)
    try:
        await r.set(f"reminder_pending:{chat_id}:{tmp_key}", bookmark_id, ex=TTL)
    finally:
        await r.aclose()
except Exception as e:
    logger.warning(f"_maybe_offer_reminder: Redis pre-write failed, skipping offer: {e}")
    return  # лучше не показать офер чем показать broken

# 2. Только потом — Telegram send
sent = await _send_message(chat_id, text, buttons)
if not sent or not sent.get("message_id"):
    # Telegram не отправилось — чистим Redis, чтобы не висел orphan key
    await store.delete_reminder_pending(chat_id, tmp_key)
    return

# 3. Перепривязать ключ к реальному message_id
await store.delete_reminder_pending(chat_id, tmp_key)
await store.set_reminder_pending(chat_id, sent["message_id"], bookmark_id, ttl=TTL)
```

Стало сложнее на 1 шаг (двойной set-delete), но избавляемся от broken button класса.

#### F4: `cb_snooze_reminder` сохраняет state ДО edit_text

**Где:** `bot/handlers/reminders.py` lines 194-211.

**Сейчас:** Сначала `store.store_reminder_snooze(...)`, потом `callback.message.edit_text(...)`. Если edit упал (например, сообщение слишком старое) — state в Redis есть, но кнопки на сообщении остались. Юзер жмёт «✅ Выполнено» (`rdone:`) → reminder cancelled. Но `reminder_snooze:` ключ висит ещё час.

**Фикс:** Инвертировать порядок: сначала edit, потом store:

```python
try:
    await callback.message.edit_text(
        "💤 На сколько продлить? <b>Ответь reply</b> со временем.\n\n"
        f"{TIME_EXAMPLES}",
        parse_mode="HTML",
    )
except Exception as e:
    logger.warning(f"cb_snooze_reminder: edit_text failed: {e}")
    await callback.answer("Не получилось — попробуй ещё раз")
    return

# Только если edit прошёл — сохраняем state.
if reminder_id:
    try:
        await store.store_reminder_snooze(chat_id, msg_id, reminder_id)
    except Exception as e:
        logger.warning(f"cb_snooze_reminder: store_snooze failed: {e}")

await callback.answer()
```

#### F5: `auto_done_reminders` может отметить snoozed reminder как done

**Где:** `backend/app/worker.py` line 964, cron `auto_done_reminders`.

**Сейчас:** Запрос:

```sql
UPDATE scheduled_messages
SET status = 'done', payload = ... || jsonb_build_object('auto_done', true)
WHERE kind = 'reminder' AND status = 'sent'
  AND sent_at < NOW() - (:hours || ' hours')::interval
```

После snooze API ставит `status='pending'`, `fire_at=<future>`, **но `sent_at` остаётся** от первой отправки. Если status почему-то снова стал `sent` (race?) или мы упустили reset — auto_done за 24h помечает done. Snooze никогда не сработает.

**Фикс:** Добавить guard `fire_at <= NOW()`:

```sql
UPDATE scheduled_messages
SET status = 'done', payload = ... || jsonb_build_object('auto_done', true)
WHERE kind = 'reminder' AND status = 'sent'
  AND sent_at < NOW() - (:hours || ' hours')::interval
  AND fire_at <= NOW()   -- <<< NEW: не трогать snoozed
```

Дополнительно проверить `update_reminder` API в `backend/app/api/reminders.py` — после snooze должен сбрасывать `sent_at = NULL`.

### Что переименовываем / убираем из v1

| v1 | v2 |
|---|---|
| `_maybe_offer_reminder(silent=True)` skip | Убран silent-gate. Offer работает в любом режиме. |
| После save offer всегда (если intent flag) | Только при weak intent. Strong → 3-button предзапрос ДО AI. |
| Callback `rsk:{bookmark_id}` (после save) | Остаётся для weak. Для strong новый callback `rstrong_r:{request_id}`. |
| Worker `_maybe_offer_reminder` | Остаётся для weak. Strong-flow живёт в `bot/handlers/reminders.py` ДО передачи в worker. |
| Закладка для каждого «надо X» | Закладки только для weak / 📝 в strong. Strong-🔔 = только reminder. |

### Список задач v2.1

Продолжаем нумерацию после T1–T10. **Реалистичная общая оценка: 12–14 часов = 2 dev-days.**

| Bead | Задача | Время | Зависимости |
|---|---|---|---|
| `T14` | Удалить silent-gate из `_maybe_offer_reminder` (есть в working tree) | 10 мин | — |
| `T15` | nl_date: маппинг «утром/днём/вечером/ночью» + тесты | 45 мин | — |
| `F1`  | **Silent-fix:** notify юзеру при permanent send failure | 30 мин | — |
| `F2`  | **Silent-fix:** explicit confirm для FALLBACK_DEFAULT времени | 1 ч | — |
| `F3`  | **Silent-fix:** invert Redis/Telegram order в `_maybe_offer_reminder` | 30 мин | — |
| `F4`  | **Silent-fix:** edit_text перед store_snooze | 15 мин | — |
| `F5`  | **Silent-fix:** `fire_at <= NOW()` guard в `auto_done_reminders` + проверка `sent_at` reset на snooze API | 30 мин | — |
| `T11` | `/remind` команда + справка + auto-detect time + `Pydantic ReminderPayload` | 2.5 ч | T15 |
| `T11a`| Bot menu: `set_my_commands` для `/remind`, `/reminders` + `/help` обновление | 30 мин | T11, T12 |
| `T13` | Pre-AI strong intent detector (отдельный router) + 3-button flow + anti-double-offer flag | 3 ч | T15 |
| `T12` | `/reminders` команда + история + Redis-snapshot IDs + NL-reply mgmt (regex first) | 3 ч | T11, T13 |
| `T16` | Tests: unit (mocks) + integration (testcontainers / docker-compose) для всех потоков | 2 ч | T11, T12, T13, T14, T15, F1–F5 |
| `T17` | **Live smoke**: fresh migration apply + 11 сценариев из таблицы | 1 ч | T16 |
| `T18` | Code-reviewer + security-reviewer + правки | 45 мин | T17 |
| `T18a`| ADR 0008 «Reminders three-flow architecture» + onboarding tips для новых команд | 30 мин | T18 |
|       | **Итого** | **~14 ч** | |

**Параллелизм:** T11 и T13 оба правят `bot/handlers/reminders.py` — coupling. Делать **последовательно**: T14 → T15 → F1–F5 (5 параллельных мелких) → T11 → T13 → T11a → T12 → T16 → T17 → T18 → T18a. Параллелить только F1-F5 между собой.

### Definition of Done

Каждая задача считается выполненной только при:
- [ ] Код написан и юнит-тесты зелёные
- [ ] Integration-тест (где применимо) на реальной Postgres зелёный
- [ ] Покрыты все edge cases из таблицы edge cases v2.1
- [ ] Acceptance test добавлен (см. ниже на каждую задачу)
- [ ] CLAUDE.md / docstring / комментарий в коде обновлён если меняется публичный contract

**Acceptance per task:**
- **T11** `/remind`: с временем → reminder создан, без аргументов → справка, с невалидным временем → fallback FALLBACK_DEFAULT-confirm
- **T11a** menu: `/remind` и `/reminders` видны в меню Telegram, `/help` упоминает их
- **T12** `/reminders`: список активных нумерован, `«отмени 1»` работает после 5 минут (snapshot), `история` показывает последние 20
- **T13** strong: 3 кнопки в чате, все 3 пути работают, ✕ не оставляет ничего в БД, anti-double-offer проверен
- **T14** silent-gate: тест `test_offered_in_silent_mode_too` зелёный
- **T15** «утром/вечером»: 4 unit-теста зелёные на `«завтра утром»`, `«сегодня вечером»`, `«в субботу днём»`, `«ночью»`
- **F1** notify: ручной тест — отключить токен бота на 5 минут, создать reminder с fire_at через 1 минуту, после 2 retries должен прийти warning
- **F2** confirm fallback: «потом» в reply → подтверждение, «да» → reminder создан, «через 2 часа» → новый парсинг
- **F3** invert order: при `MockRedis.set` бросает exception → офер не отправляется
- **F4** edit-then-store: при `edit_text` бросает → snooze state не сохранён
- **F5** auto_done guard: snoozed reminder с `fire_at` через 6 часов не трогается auto_done крон'ом
- **T16** integration: `alembic downgrade base && upgrade head`, потом INSERT через ORM с правильным ENUM — проходит
- **T17** live smoke: все 11 сценариев из сводной таблицы воспроизведены на dev-боте, скриншоты в PR description
- **T18a** ADR: файл `docs/decisions/0008-reminders-three-flow.md` существует, описывает strong/weak split и причины

### Out of scope в v2.1

Документируем явно (для history и чтобы reviewers не спрашивали):

- **Group chat поведение** — бот используется в DM (single-user). В group chat strong-detector отключён, реминдеры не предлагаются.
- **English input** — детектор только на русский. «I need to buy bread» не сработает strong → попадёт в обычный flow закладок. Допустимо для MVP.
- **Caption фото** — strong-detector работает только на text-сообщениях. Caption на фото (с интенсивным intent в подписи) идёт в обычный flow.
- **`/reminders история` пагинация** — fixed last-20. Если у юзера >20 done за месяц, остальное недоступно. Phase 6.
- **Reply-bug Telegram swipe** (юзер reply'ит на чужое сообщение бота) — не решаем, документируем как known limitation. Юзер увидит «не нашёл этот список» от tasks-fallback.
- **Concurrency dispatcher >60s** — стик-recovery threshold 5 минут. Если dispatcher тик действительно растянулся на 5+ минут — отдельная задача performance-tuning.

### Известные риски и митигация

Top 3 риска от `planner`:

| # | Риск | Митигация |
|---|---|---|
| 1 | Strong-detector false positives («надо бы что-то почитать») → юзер хочет закладку, но получает 3-button prompt | Логировать каждое срабатывание strong c `payload.source="strong_intent"`, ручной review за неделю → подкрутить regex или добавить exclusion `^надо бы\s` |
| 2 | aiogram filter ordering: `/remind` и `/reminders` команды должны зарегистрироваться раньше generic message handler. Strong-detector router ДО `start.router`. | Test в T16: явная проверка router order — отправляем strong-сообщение, ожидаем что handle зацепил его, не start.handle_text |
| 3 | Redis key collision: `reminder_strong:`, `reminder_pending:`, `reminder_snooze:`, `reminder_fallback_pending:`, `strong_handled:`, `reminders_list:` — много ключей рядом | Audit в T16: список всех ключей в `bot/state_store.py` docstring + namespace-test «никакая операция не пишет в чужой namespace» |

### Тесты на реальной Postgres (новый tier)

Урок PR #9 (CRITICAL ENUM bug пропущен моками): добавляем integration-tier тестов.

**Реализация (T16):** через docker-compose (поднят локально, dev box) или testcontainers (правильнее для CI, дороже). Для MVP — локальный docker-compose:

```python
# backend/tests/integration/test_reminders_real_db.py
@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_reminder_via_orm_real_postgres():
    """Regression test для PR #9: ORM INSERT должен пройти на ENUM-колонках."""
    async with async_session() as session:
        rem = ScheduledMessage(
            user_id=test_user_id,
            kind="reminder",
            fire_at=datetime.now(timezone.utc) + timedelta(hours=1),
            payload={"text": "test"},
        )
        session.add(rem)
        await session.flush()  # тут раньше падало с DatatypeMismatchError
        await session.refresh(rem)
        assert rem.id is not None
```

Маркером `@pytest.mark.integration` → запуск отдельной командой `pytest -m integration`. CI запускает оба тира.

### Live smoke (T17): обязательный чек-лист перед PR

**Подготовка:**

```bash
docker compose down -v  # стираем БД
docker compose up -d
cd backend && alembic upgrade head  # fresh schema
# перезапустить bot, worker, backend на ветке PR
```

**Проверить 11 сценариев из сводной таблицы. Скриншоты в PR description.**

1. `/remind купить хлеб завтра в 9` → подтверждение «🔔 Напомню 11.05 09:00 — купить хлеб»
2. `/remind купить хлеб` → «Когда напомнить?» → reply «через час» → подтверждение
3. `/remind` без аргументов → справка
4. «надо купить хлеб» → 3 кнопки → 🔔 → reply «через 2 минуты» → reminder приходит через 2 мин
5. «надо купить хлеб» → 3 кнопки → 📝 → AI обработка → закладка, **без** второго оффера
6. «надо купить хлеб» → 3 кнопки → ✕ → нет ни закладки ни reminder в БД
7. «купить чайник» → AI → 👍 → 1 кнопка офера → ✕ → закладка есть, reminder нет
8. «Статья про React» → закладка, никаких кнопок
9. Пришедший reminder → ✅ Выполнено → status=cancelled, message edit «✅ Выполнено»
10. Пришедший reminder → 💤 Продлить → reply «через час» → status=pending fire_at +1h
11. `/reminders` → список → «отмени 1» → отмена корректна. Подождать 5 минут (или сделать руками так чтобы первый сработал) → «отмени 1» теперь должно отменить **другой** reminder который был №2

### Новое правило: live smoke перед мержем

В v1 моки пропустили 4 серьёзные проблемы. Новое глобальное правило (записать в `~/.claude/rules/common/live-smoke.md`):

> **Любая фича которая разговаривает с БД, Redis или внешним API должна быть прогнана живьём минимум 1 раз перед PR**, в условиях fresh-migration (`docker compose down -v && alembic upgrade head`). Чек-лист live-теста — обязательное приложение к PR description.

---

## v1 PRD (для истории, частично устарел в v2)

> Разделы ниже — оригинальный PRD от 2026-05-09. По части flow («один тап после save», silent-skip) v2 переписала дизайн. Раздел оставлен для контекста того, что уже реализовано (T1–T8).

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
