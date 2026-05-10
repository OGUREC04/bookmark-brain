# ADR 0008 — Reminders MVP: three-flow architecture

**Статус:** принято
**Дата:** 2026-05-11
**Связано с:** Phase 2.5 (Reminders MVP), `docs/prd/REMINDERS-MVP.md`,
ветка `feat/reminders-v2-separate-from-bookmarks`

## Context

Phase 2.5 = «бот напоминает о вещах». Изначально планировалась как «вешаем
кнопку 🔔 на каждую закладку». Live smoke на T10 показал что для half-сценариев
(«надо позвонить маме завтра в 9») закладка и AI-обработка — оверхед,
а strong-intent отлавливать постфактум после AI слишком поздно (юзер уже
видит «📌 Сохранено» и кнопку, которая не предлагает того что он хочет).

Из этого выросли **3 отдельных flow**, каждый со своей точкой входа.

## Решение

### 1. Three flows, не один универсальный

| Flow | Точка входа | UX |
|------|-------------|-----|
| **Explicit** | `/remind <текст> <когда>` | Команда. Без AI/закладки. |
| **Implicit strong** | Regex pre-AI на «надо / нужно / не забыть / срочно / обязательно» в начале сообщения | 3-кнопка «🔔 / 📝 / ✕» ДО AI-обработки |
| **Implicit weak** | AI определил intent=reminder в обычной закладке | 2-кнопка «🔔 Напомнить? / ✕» после save |

Альтернативой был «один универсальный flow с AI-классификацией всего».
Отверг: задержка AI на каждый текст (3-5 с) + расход GigaChat-кредитов
на сообщения которые юзер сам видно отметил как напоминание.

### 2. Pre-AI strong intent detector — regex

`bot/handlers/reminders.py::is_strong_intent` — компилированный regex
по первым 80 символам:
```
^\s*(надо|нужно|не\s+забыт[ьи]|срочно|обяза(тельно|н))\b
```

Высокая точность, низкий recall. Лучше пропустить strong как weak (попадёт
в обычный flow с offer'ом), чем спросить «напоминание или заметка?»
там где юзер вообще не хотел reminder'а.

Альтернатива — AI-классификатор перед save: отверг из-за латентности.

### 3. Anti-double-offer Redis flag

Когда strong-flow поймал сообщение, юзер выбрал «📝 Заметка» → дальше идёт
обычный AI-flow с save. Без защиты worker._maybe_offer_reminder покажет
weak-offer «🔔 Создать напоминание?» — это double-offer на одно сообщение.

**Решение:** перед маршрутом «📝» ставим в Redis флажок
`strong_handled:{chat_id}:{src_msg_id}` (TTL 5 мин). Worker.maybe_offer
проверяет флажок и не показывает weak-offer.

### 4. Snapshot IDs для NL-reply на /reminders

`/reminders` показывает нумерованный список. Reply «отмени 1 / перенеси 2
на завтра в 9 / история» — естественный UX.

Проблема: к моменту reply список может измениться (другой клиент тоже
делает изменения). Сопоставление по номеру → off-by-one.

**Решение:** при ответе на `/reminders` сохраняем snapshot UUID-ов
в Redis (`reminders_list:{chat_id}:{msg_id}` TTL 1 час). NL-reply
разрезолвливает «1» в UUID из snapshot, а не из текущего состояния БД.

### 5. Атомарный pop (GETDEL) для pending/snooze state

Раньше: `get_reminder_pending` → API call → `delete_reminder_pending`.
Не атомарно: между read и delete второй reply (быстрый double-tap)
тоже читает значение и создаёт второй reminder.

**Решение (post-review fix, T18):** `pop_reminder_pending`/`pop_reminder_snooze`
через Redis GETDEL. State consumed атомарно. Цена: на 5xx state уже
исчез, юзеру предлагаем повторить flow заново через `/remind` или
кнопку «💤 Продлить» — компромисс в пользу no-double-create.

### 6. CAS RETURNING + `.mappings().one_or_none()`

Worker делает `UPDATE ... RETURNING id, user_id, payload, retry_count`
для CAS-lock. SQLAlchemy `cas_result.scalar_one_or_none()` вернёт
**только первую колонку** (id) как scalar, не Row-объект.

**Решение (post-review fix, T18):** `cas_result.mappings().one_or_none()` —
возвращает dict-like объект с доступом по имени. Иначе `getattr(locked, "payload")`
всегда `None`, и обновлённый snooze'ом payload не дойдёт до Telegram.

### 7. HTML-escape пользовательского текста (`_safe`)

Все confirmation-сообщения используют `parse_mode="HTML"` чтобы выделить
дату через `<b>`. Текст напоминания приходит из user input — без escape
атакер может вставить `<a href="tg://...">` для фишинга.

**Решение (post-review fix, T18):** `html.escape()` обёртка `_safe()`
применяется ко всем юзерским подстановкам.

### 8. Length cap (`_cap_text` = 500 chars)

Юзер мог бы отправить 4000-символьное сообщение → попадает в Redis
TTL 1 час. При высоком QPS — DoS Redis-памяти.

**Решение (post-review fix, T18):** все пользовательские строки перед
записью в Redis обрезаются `_cap_text(s, limit=500)`.

### 9. UUID validation для callback_data

callback_data — attacker-controlled. `rdone:not-a-uuid` или
`rdone:../../etc/passwd` мог бы дойти до API URL.

**Решение (post-review fix, T18):** все callback handlers с UUID-аргументом
валидируют через `_is_valid_uuid()` до API-вызова.

## Trade-offs

- **Три отдельных flow** = больше кода, но каждый flow прямолинеен.
  Универсальная архитектура с AI-классификацией дала бы 1 flow, но
  с непредсказуемой латентностью и расходом кредитов.
- **Regex strong-detector** упускает фразы где «надо» в середине
  («думаю надо как-то»). Сознательный trade-off — низкий recall ради
  низкого false-positive.
- **Атомарный pop** жертвует retry-friendliness в обмен на no-double-create.
  Юзер на 5xx видит «попробуй ещё раз через /remind», а не магическое
  «нажми reply опять — старое сообщение помнит контекст».
- **Snapshot IDs** добавляют Redis read на каждый reply. Цена: 1 TTL-ключ
  на каждое /reminders. Альтернатива — фетчить список из БД и матчить
  по номеру — дороже.

## Открытые вопросы (вне scope MVP)

- Per-user rate limiting на reply handlers (M1 из security-review) —
  пока не нужен (никто не флудит), но добавить когда появится метрика.
- Connection pool для worker._maybe_offer_reminder Redis (создаётся
  client на каждый cron-tick) — оптимизация на P2.
- Bot API 9.5 sendChecklist с date_time chip — недоступен для не-business
  ботов. Полагаемся на client-side NSDataDetector через формат
  «ДД.ММ.ГГГГ ЧЧ:ММ».

## Метрики (как поймём что работает)

- `/remind` исп. > offer-кнопки в течение 2 недель — explicit flow прижился.
- < 5% reminder'ов в `status='failed'` — F1 (notify) + retry работают.
- Нет жалоб «двойной reminder» — anti-double-offer + атомарный pop работают.

## Связанные документы

- `docs/prd/REMINDERS-MVP.md` — продуктовое описание + edge cases
- `backend/app/services/nl_date.py` — NL-парсер времени (тонкая обёртка
  над dateparser + tz fix)
- `backend/app/worker.py::scheduled_dispatcher` — cron-диспатчер
- `bot/handlers/reminders.py` — все три flow + callback handlers
- Code review T18: 1 CRITICAL + 5 MAJOR + 3 MINOR — все CRITICAL+MAJOR пофикшены
- Security review T18: 1 CRITICAL + 2 HIGH + 3 MEDIUM + 2 LOW — все CRITICAL+HIGH пофикшены
