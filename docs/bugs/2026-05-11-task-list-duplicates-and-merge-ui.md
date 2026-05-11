# Bug 2026-05-11 — task list duplicates и UI после merge

**Дата:** 2026-05-11
**Серьёзность:** P1 (юзер видит «Ошибка при сохранении», merge не показывает результат)
**Затронуты:** `backend/app/api/bookmarks.py`, `bot/handlers/tasks.py`
**Commit с фиксом:** TBD на ветке `fix/task-list-nl-edit-bugs`

## Симптомы

1. Юзер отправил список («— молоко / — хлеб / …»). Бот определил дубликат
   с уже существующим списком и показал alert «🔗 Объединить / 📋 Оставить
   отдельно». Юзер выбрал «🔗 Объединить» — **в чате ничего не произошло**:
   обновлённый старый список не пришёл, сообщение нового списка не удалилось.
2. Юзер отправил тот же список повторно. Бот ответил `👎 Ошибка при
   сохранении. Попробуй ещё раз.`

## Корневые причины

### Bug A — UI не обновился после успешного merge

`bot/handlers/tasks.py::cb_dedup_merge` — порядок шагов после успешного
`api.merge_task_list`:

```python
# СТАРЫЙ КОД:
await callback.message.bot.delete_message(chat_id, new_msg_id)  # silent swallow
await store.unbind_list_message(...)                            # silent swallow
await callback.message.delete()                                 # silent swallow
# ... затем _rerender_at_bottom(...)
```

Каждый шаг обёрнут в `try / except TelegramBadRequest: pass`. Когда
`delete_message` падает (например, сообщение запинено, или Telegram
вернул edge-case), все хвостовые операции продолжают выполнение —
но **ни одного лога нет**, поэтому диагностика невозможна. Юзер
видит «ничего».

В исходном инциденте merge API отработал успешно
(`PATCH 200` + `DELETE 204` по логу backend в 15:26:31), но визуальной
обратной связи юзер не получил. Подтверждено по `bot.log` —
`Update is handled. Duration 1851 ms` без последующих сообщений в чате.

### Bug B — 500 на повторе списка

`backend/app/api/bookmarks.py::create_bookmark` делал `session.add(bookmark);
await session.flush()` без обработки `IntegrityError`. Когда юзер повторно
отправлял такой же список, INSERT падал на уникальном индексе
`idx_bookmarks_source_dedup`:

```
asyncpg.exceptions.UniqueViolationError:
duplicate key value violates unique constraint "idx_bookmarks_source_dedup"
DETAIL: Key (user_id, source, source_message_id)=
        (d96f6183-..., bot_message, 382) already exists.
```

FastAPI отдавал 500. Бот видел исключение → ставил 👎 и писал
«Ошибка при сохранении. Попробуй ещё раз.» — но повтор бессмысленный,
причина не транзиентная.

Гипотеза почему `source_message_id=382` совпал: внутри одного чата ID
коротких сообщений могут попадать в один из двух сценариев:
- forward / edit с сохранением исходного ID
- ретрай бота с тем же `bot_message_id`

В любом случае — обработка не должна делать 500.

## Фиксы

### Fix B (backend) — идемпотентный POST

`backend/app/api/bookmarks.py::create_bookmark` теперь:

```python
try:
    await session.flush()
except IntegrityError as e:
    err = str(getattr(e, "orig", e)).lower()
    if "idx_bookmarks_source_dedup" in err or "source_message_id" in err:
        if data.source_message_id is not None:
            await session.rollback()
            existing = await session.execute(select(Bookmark).where(...))
            existing_bm = existing.scalar_one_or_none()
            if existing_bm:
                logger.warning("Duplicate POST bookmark: returned existing ...")
                return existing_bm  # idempotent
            raise HTTPException(409, "Concurrent duplicate detected")
    raise
```

Семантика:
- При попытке создать с уже занятыми `(user_id, source, source_message_id)` —
  возвращаем **существующий** bookmark (а не 500).
- Бот ничего не меняет — `create_bookmark` API client уже умеет работать с
  ответом 201. Полученный existing bookmark пройдёт нормальный flow.
- Если existing не найден (гонка с DELETE) — отдаём 409, не 500. Бот может
  ретраить.

### Fix A (bot) — переупорядочивание + явные логи

`bot/handlers/tasks.py::cb_dedup_merge`:

1. **Re-render старого списка ПЕРВЫМ** (до удалений).
   Даже если последующие `delete_message` упадут — юзер уже увидел результат.
2. **Unpin перед delete** для запиненного task-list сообщения
   (`unpin_chat_message` → `delete_message`).
3. **`logger.warning` на каждое падение** Telegram-операции с текстом
   ошибки. `pass` без логов запрещён.
4. **Fallback `send_message` если re-render упал** — гарантия что юзер
   увидит обновлённый список.

```python
# НОВЫЙ ПОРЯДОК:
# 1. API merge
updated_old = await api.merge_task_list(...)

# 2. Сначала видимый результат
if old_msg_id найден → _rerender_at_bottom (с try/except + logger.warning)
else / если упало → send_message fallback + bind + logger

# 3. Затем чистим хвосты
unpin_chat_message(new_msg_id)  # debug если skipped
delete_message(new_msg_id)       # WARNING если упало
unbind_list_message(...)         # debug
delete alert                     # WARNING если упало

# 4. Confirm
callback.answer("Списки объединены ✅")
```

## Test coverage

### Новые тесты

**`backend/tests/integration/test_bookmarks_duplicate.py`** (4 теста на live Postgres):
- `test_duplicate_raises_integrity` — подтверждает что constraint реально работает
- `test_different_message_ids_ok` — разные ID не конфликтуют
- `test_null_source_message_id_ok_multiple` — NULL не конфликтует (WHERE clause)
- `test_post_duplicate_returns_existing` — **главный** тест: POST дубликата возвращает existing, не 500

**`tests/test_dedup_merge_ui.py`** (6 unit тестов):
- `test_renders_updated_list_visible_to_user` — после merge юзер ВСЕГДА видит обновлённый список
- `test_renders_via_rerender_when_old_msg_known` — приоритет re-render
- `test_render_happens_even_if_delete_new_msg_fails` — независимость render от delete
- `test_warning_logged_on_delete_failure` — silent failure запрещён, WARNING обязателен
- `test_api_failure_shows_user_message` — graceful error на 500 backend
- `test_state_already_consumed_returns_gracefully` — double-tap protection

## Прогон тестов

```bash
# Unit
pytest tests/ backend/tests/ -q
# 401 passed

# Integration (требует docker-compose + .env)
pytest backend/tests/integration/ -m integration -v
# 9 passed (5 reminders T16 + 4 bookmarks duplicate)
```

## Corner case 2 — «Оригинал обновлён» без видимого списка

**Симптом (последующий смок):** после фиксов A+B юзер отправил список повторно,
сработал auto-dedup → intent="update" → API обновил старый task_list данными
нового → бот вывел **только** `✅ Оригинал обновлён` (мини-confirm) → юзер не
увидел обновлённый список и не понял что произошло.

**Правило различия:**

| Сценарий | Что юзер ожидает |
|----------|------------------|
| Reply на список: «добавь хлеб» | Inline-edit того же сообщения списка (текущее поведение OK) |
| Новое сообщение со списком (юзер забыл что список уже есть) | Показать обновлённый список **последним** сообщением + удалить юзер-сообщение |

Источник правила: feedback пользователя 2026-05-11.

**Фикс:** новый helper `_show_updated_task_list_after_dedup_update`:
- Проверяет что `old_bm.structured_data.type == "task_list"`. Для статей/voice
  поведение остаётся прежним («Оригинал обновлён» + auto-delete через 5с).
- Для task_list: ищет старое сообщение списка в Redis → `_rerender_at_bottom`
  (двигает список вниз чата с актуальным содержимым). Если не нашли —
  `send_message` свежим сообщением + `bind_list_message`.
- В обоих flow (`_handle_general_dedup_reply` + `_handle_pending_dedup`) после
  успешного рендера alert/replied **удаляется** (не оставляем дубль-confirm).

**Тесты** (`tests/test_dedup_merge_ui.py::TestDedupUpdateRerendersTaskList`):
- `test_general_dedup_update_shows_updated_list` — task_list → re-render
- `test_pending_dedup_update_shows_updated_list` — то же для pending variant
- `test_general_dedup_update_non_task_list_no_rerender` — статья → старое
  поведение сохранено (regression guard)
- `test_user_source_message_deleted_on_update` — юзер-сообщение удаляется

## Уроки

1. **Silent `except: pass` запрещён** в любом UI-флоу. Минимум — `logger.debug`,
   для visible-affecting операций — `logger.warning`. Этот баг был
   обнаружен только потому, что юзер показал скрин — никакого лога не было.
2. **IntegrityError на любом public POST endpoint обязан быть обработан.**
   Constraint существует не просто так — он часть контракта. Бот должен
   получать предсказуемый ответ.
3. **Порядок видимых операций — сначала «дать обратную связь», потом «чистить
   мусор»**. Если чистка упадёт, юзер уже получил то, ради чего нажал кнопку.
4. **Integration tier тесты ловят то, что моки не видят** (PR #9 ENUM bug,
   этот IntegrityError). Стоит сохранять и расширять.

## Связанные документы

- `docs/decisions/0008-reminders-three-flow.md` — упоминает silent-failure
  как класс багов (F1-F5 фиксы для reminders шли по тому же паттерну)
- `~/.claude/rules/common/coding-style.md` — раздел «Error Handling: never
  silently swallow errors»
