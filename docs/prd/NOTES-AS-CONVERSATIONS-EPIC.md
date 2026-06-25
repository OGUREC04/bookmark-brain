# Эпик: Заметка-как-диалог — декомпозиция (v2, после адверсариал-ревью)

> Источник: [`NOTES-AS-CONVERSATIONS.md`](NOTES-AS-CONVERSATIONS.md) (PRD) · Создан: 2026-06-25 · Ревизия v2: 2026-06-26
> v2 = свод адверсариал-ревью плана (31 находка: 6 critical / 8 high). Ключевая правка: **B3 (индексация дописок) — самостоятельный тяжёлый кусок, не «правка функции»**, и он — ОБЩАЯ зависимость для B2/B4, а не параллельная ветка.
> Процесс: PRD ✅ → этот эпик → план по TDD на задачу → код → code-reviewer → БТ.

## Зафиксированные решения (закрыты по ревью — вход в код)

| # | Решение | Почему |
|---|---------|--------|
| DEC-1 | **Re-index = НОВЫЙ classify-free воркер-джоб** `reembed_bookmark_task` (образец `reembed_all_bookmarks`, `worker/scheduled.py`). Грузит bookmark + неудалённые `note_entries`, строит embedding-текст, пишет `embedding`, зовёт `build_links_for_bookmark`. **НЕ трогает `ai_status`/classify/summary/title.** Регистрируется в `WorkerSettings.functions`. | Единственный существующий reprocess (`process_bookmark_task`) гонит полный LLM-пайплайн (classify) — нарушает FR-5/NFR-1. Embedding-only пути в коде НЕТ |
| DEC-2 | **FTS дописок:** денормализованная колонка `bookmarks.entries_text` (конкатенация неудалённых дописок), которую ведёт re-index-джоб; расширить триггер `bookmarks_search_vector_trigger` чтобы включал `entries_text`. Миграция — часть B3. | `search_vector` строит Postgres-триггер (`001_initial.py:124-145`) по `title/raw_text/summary`; он физически не видит таблицу `note_entries`. Без миграции FTS-поиск дописок молча не работает |
| DEC-3 | **Debounce:** `enqueue_job(..., _job_id=f'reembed:{bid}', _defer_by=N)` → arq дедуплицирует по `job_id` (повтор в окне не плодит джоб). N ≈ 30–60с. Проверить, что версия arq так умеет; иначе — таблица `dirty_bookmarks` + cron. | Наивный enqueue на каждую дописку = N эмбеддингов на N дописок (нарушение NFR-1). arq встроенного debounce не имеет |
| DEC-4 | **Схема `Entry` — ПЛОСКАЯ** (`transcription`/`duration`/`entry_ai_status` на верхнем уровне, как `BookmarkResponse`), не вложенный `voice{}`. Заморожена в `schemas.py` (B2) до старта F1. | Весь существующий API плоский; вложенный объект — новый паттерн → риск рассинхрона контракта для F1 |
| DEC-5 | **`duration` = DOUBLE PRECISION** (float), не SMALLINT. | `media_duration` уже Float, `upload` принимает `duration: float`, фронт шлёт число (может быть дробным) |
| DEC-6 | **Пагинация thread — вне MVP.** GET `/thread` отдаёт все неудалённые записи; на фронте — виртуализация при необходимости. Keyset (before/after+limit) — fast-follow. | Логи на старте короткие; keyset усложняет замороженный контракт. Зафиксировать как осознанную границу (edge #9) |
| DEC-7 | **F4-текст:** захватить `const bm = await api.createThought(text); openDetail(bm)` прямо в `App.tsx` (без правки контракта `ComposeScreen.onSave`). **F4-голос:** `openDetail(bm)` в `onCreated` (bm уже есть). | `onSave` сейчас возвращает void, результат `createThought` (Promise<Bookmark>) выбрасывается. Захват в App проще правки ComposeScreen |
| DEC-8 | **F3 дробится** на F3a/b/c/d (LOC-правило: DetailScreen уже 449 строк, цельный F3 пробьёт 800). Логику ленты — в `lib/`, строки — в ds-компоненты. **Переиспользовать `ds/ChatRow.tsx` + `DaySeparator` + `formatters`**, не плодить новые. | Жёсткое правило стиля (>800 блок); готовые компоненты уже есть |
| DEC-9 | **Удаление дописки НЕ откатывает уже построенные связи** (нет DELETE в `build_links`, ON CONFLICT DO NOTHING). Принять как MVP-долг, записать в PRD edge. | Откат рёбер — отдельная подсистема; для MVP приемлемо (как и непересчёт весов, edge #13) |
| DEC-10 | **Гонка re-index ↔ 0rn-reprocess** (оба пишут embedding/search_vector/links): last-writer-wins, оба заканчиваются `build_links`. Низкий риск, зафиксировать. | Полноценная блокировка — оверкилл для MVP |
| DEC-11 | **Per-entry статус:** фронт поллит GET `/thread` (поле `entry_ai_status`) пока есть запись `transcribing` — ОТДЕЛЬНО от note-level поллинга шапки. | Текущий поллинг (`App.tsx:242-268`) завязан на `ai_status` всей заметки через `GET /bookmarks/{id}` — голос-дописку не видит (тот же класс бага, что чинили в ti0) |

## Карта зависимостей (DAG v2)

```
B1 (таблица note_entries + миграция; duration=float; индекс через op.execute)
 └── B2 (CRUD текст: GET thread / POST,PATCH,DELETE entries + ПЛОСКАЯ Entry-схема + IDOR + 422)
       └── B3 (re-index: classify-free джоб + FTS-миграция (entries_text+триггер) + связи + debounce;
                ВШИВАЕТ вызов re-index в эндпоинты B2)                         ← тяжёлый, критич. путь
             └── B4 (голос-в-запись: новый эндпоинт + process_entry_upload; по готовности → re-index B3)

F2 (вынести ТЕКСТОВЫЙ композер; recording-состояние через проп)   ← без бэк-зависимостей
F1 (api.entries по ЗАМОРОЖЕННОЙ Entry-схеме из B2)                 ← после схемы B2
 ├── F3a (лента-чтение: GET thread + lib группировки + ChatRow/DaySeparator + маркер «саммари без дописок»)
 ├── F3b (текст-композер, закреплён внизу, из F2)
 ├── F3c (правка/удаление записи inline)
 └── F3d (голос-дописка + ОТДЕЛЬНЫЙ thread-поллинг entry_ai_status)
F4 (после создания → openDetail; текст — захват createThought в App.tsx)
D1 (БТ-14 + правки бт-01/02/07/11 на стыках)
```

**Критический путь (бэк):** B1 → B2 → **B3** → B4. **B3 — самое тяжёлое звено** (новый джоб + DDL-миграция FTS + debounce), сопоставимо с B4, а не «правка функции».
**Фронт-дорожка** идёт параллельно: F2 рано; F1 после заморозки схемы B2; F3a–d после F1 (+живой B2/B3). F4 — независим (openDetail уже есть), логично слить в финал F3.

## Порядок шипа

| PR | Задача | Зависит | Параллельно |
|----|--------|---------|-------------|
| 1 | **B1** таблица+миграция | — | F2 |
| 2 | **F2** вынос текст-композера | — | B1 |
| 3 | **B2** CRUD текст + заморозка Entry-схемы | B1 | F1 (после схемы) |
| 4 | **B3** re-index джоб + FTS-миграция + debounce + вшивка в B2 | B2 | F1/F3a |
| 5 | **B4** голос-в-запись (+ re-index по готовности) | B3 | F3 |
| 6 | **F1** api.entries | B2 (схема) | B3/B4 |
| 7 | **F3a** лента-чтение | F1 | — |
| 8 | **F3b** текст-композер внизу | F3a, F2 | — |
| 9 | **F3c** правка/удаление | F3a | — |
| 10 | **F3d** голос-дописка + thread-поллинг | F3a, B4 | — |
| 11 | **F4** openDetail после создания | — (слить в F3) | — |
| 12 | **D1** БТ-14 + правки стыков | по факту | — |

> Опция фазирования (если захочешь шипить быстрее): после **B2** лог уже рабочий (дописываешь/читаешь/правишь/удаляешь), но дописки НЕ в поиске/связях. **B3** — отдельный «делает дописки искомыми» шаг. Можно вынести B3 в fast-follow, если хочется раньше пощупать сам лог. Сейчас план — B3 в MVP (твой выбор «дописки попадают в поиск»).

---

## Задачи (бриф для холодного старта)

### B1 — Таблица `note_entries` + миграция
- **Файлы:** `backend/app/models.py` (модель `NoteEntry` рядом с `BookmarkLink`), новая миграция (`down_revision = c2d3e4f5a6b7` — подтверждён HEAD; образец `a9b0c1d2e3f4_add_bookmark_links.py`).
- **Схема:** id, bookmark_id FK CASCADE, kind (TEXT, default `user`), body TEXT, created_at, edited_at NULL, is_deleted BOOL default false, media_file_id TEXT NULL, transcription TEXT NULL, **duration DOUBLE PRECISION NULL** (DEC-5), entry_ai_status TEXT NULL. **+ колонка `bookmarks.entries_text` TEXT NULL** (под FTS, DEC-2 — заводим здесь, наполняет B3).
- **Индекс:** partial `ix_note_entries_thread (bookmark_id, created_at) WHERE NOT is_deleted` — **через `op.execute(sa.text(...))`** (конвенция репо), downgrade — drop_index по имени.
- **Relationship:** грузить дописки отдельным `select` по bookmark_id (как `connections`), БЕЗ ORM relationship на Bookmark (или `lazy='noload'`) — зафиксировать, чтобы B2 не упёрся.
- **Acceptance/тесты:** миграция up/down на чистой БД; модель импортируется; дефолты; smoke CRUD.

### B2 — CRUD текст + заморозка Entry-схемы
- **Файлы:** новый `backend/app/api/entries.py` (НЕ `connections.py`/`bookmarks.py` — тот уже 682 строки); регистрация в `backend/main.py` (8-роутерный паттерн, не `app/main.py`); `backend/app/schemas.py` — **плоская `Entry`** (DEC-4) + EntryCreate/EntryUpdate/ThreadResponse.
- **Эндпоинты:** GET `/bookmarks/{id}/thread` (неудалённые, по created_at, **все — без пагинации, DEC-6**), POST `/entries {body}`, PATCH `/entries/{eid} {body}` (edited_at), DELETE `/entries/{eid}` (soft). IDOR через владение заметкой (404). Пустой body → 422.
- **Заморозка контракта:** `Entry`-схема — single source of truth для F1 (DEC-4). Зафиксировать ДО F1.
- **Дедуп окна (NFR-3):** вне MVP (клиентской блокировки кнопки достаточно, edge #2) — НЕ закладывать поле/индекс.
- **Acceptance/тесты:** CRUD happy; IDOR (чужая → 404); пустой → 422; soft-delete не в thread; каскад при удалении заметки.

### B3 — Индексация дописок (re-index джоб + FTS + связи + debounce) ⚠️ тяжёлый
- **DEC-1/2/3 — это и есть тело задачи.** Перед стартом — мини-ADR по DEC-2 (триггер vs денорм-колонка) и DEC-3 (проверить arq `_job_id`-дедуп).
- **Файлы:** `backend/app/worker/` (новый `reembed_bookmark_task`), `worker/__init__.py` (регистрация в `WorkerSettings.functions`), `backend/app/services/bookmark_processor.py` (`_build_embedding_text` — **новая сигнатура** `entries_bodies: list[str] | None`; обновить ОБА вызова: `process_bookmark` и `reembed_all_bookmarks`), новая миграция (entries_text в триггер), `backend/app/api/entries.py` (вшить `enqueue reembed` с debounce в POST/PATCH/DELETE).
- **Логика джоба:** load bookmark + неудалённые entries → embedding-текст (raw_text + AI-поля + конкатенация entries.body, cap 8000; **порядок: raw_text, затем дописки; при переполнении хвост обрезается — windowing вне MVP**) → `get_embedding` → `bookmark.embedding` + `bookmark.entries_text` → `build_links_for_bookmark(session, bid, uid, emb)` → commit. **classify/summary/title/ai_status НЕ трогаем.**
- **Acceptance/тесты:** дописка → находится семантикой И FTS по слову из дописки (в пределах окна debounce); classify НЕ вызывается (мок/счётчик); N дописок подряд → ≤1 джоб (DEC-3); удалённая запись исключена из embedding/FTS; `reembed_all_bookmarks` не падает на новой сигнатуре; новое ребро связи при наличии похожей (вес старых не пересчитывается — edge #13).

### B4 — Голос-в-запись
- **НЕ переиспользовать `process_upload_task` as-is** (создаёт Bookmark + гонит полный конвейер). Новый путь.
- **Файлы:** `backend/app/api/entries.py` (POST `/bookmarks/{id}/entries/upload`, multipart), `backend/app/worker/` (новый `process_entry_upload`: STT через `shared.media` → `note_entries.body`/`transcription`, `entry_ai_status` done/failed; по готовности → enqueue re-index B3), `worker/__init__.py` (регистрация).
- **Acceptance/тесты:** upload → entry `transcribing`; worker заполняет body; failed-путь (запись остаётся); голос-дописка НЕ запускает classify заметки; по готовности дёргается re-index.

### F2 — Вынос текст-композера ⚠️ не zero-risk
- В `ComposeScreen` композер сращён с 100dvh-контейнером, героем и **полноэкранным recording-оверлеем** (ветка записи заменяет композер таймером+волной). Чистый «вынести как есть» не выйдет.
- **Файлы:** новый `bookmark-brain-miniapp/src/components/ds/Composer.tsx` — выносим ТОЛЬКО текстовую часть (textarea авто-рост + `canSend`/`shouldExpandComposer` + отправка + lead-слот); recording-состояние передаём пропом (`onMicTap`/слот). `ComposeScreen.tsx` использует его.
- **Решить до F3d:** как показывать запись голоса ВНУТРИ ленты (не полноэкранно).
- **Acceptance/тесты:** ComposeScreen без регресса (build+vitest зелёные); существующие compose.test держатся.

### F1 — API-клиент thread
- **Файлы:** `bookmark-brain-miniapp/src/lib/api.ts` — `api.entries.list/create/upload/edit/remove`, тип `Entry` (строго по замороженной плоской схеме B2). upload — через `requestRaw`/FormData на `/bookmarks/{id}/entries/upload` (НЕ переиспользовать `uploadMedia` — другой путь, тот же транспорт).
- **Acceptance:** типы совпадают со схемой B2; собирается.

### F3a — Лента-чтение
- **Файлы:** `DetailScreen.tsx` (рендер ленты под шапкой), `lib/` (группировка по дням, порядок), переиспользовать `ds/ChatRow.tsx` + `DaySeparator` + `formatters` (`formatRelativeDate`/`formatDaySeparator`). Тихий маркер «саммари не учитывает дописки» (edge #12 / open q #3) — здесь.
- **Acceptance/тесты:** lib-логика ленты (порядок, дни); рендер по GET thread; DetailScreen остаётся тонким (LOC-правило).

### F3b — Текст-композер внизу
- **Файлы:** `DetailScreen.tsx` (закреплённый снизу `Composer` из F2), `App.tsx`/`api` проводка POST entry. Аккуратно с клавиатурой/safe-area (NFR-5, известная боль 100dvh).
- **Acceptance:** дописка появляется внизу, автоскролл; поле не уезжает за клавиатуру.

### F3c — Правка/удаление записи
- **Файлы:** `DetailScreen.tsx`/ds-компонент записи — тап = inline-правка (как тело, авто-сейв на blur), удаление. PATCH/DELETE через F1.
- **Acceptance:** правка ставит edited_at; удаление убирает из ленты.

### F3d — Голос-дописка + thread-поллинг
- **Файлы:** `DetailScreen.tsx`/`Composer` (🎤 в append), `App.tsx` (ОТДЕЛЬНЫЙ поллинг GET thread пока есть `transcribing`, DEC-11 — паттерн setInterval/cleanup, не текущий note-level цикл).
- **Acceptance:** голос-дописка доходит до текста; поллинг записи не конфликтует с note-level.

### F4 — openDetail после создания (слить в финал F3)
- **Файлы:** `App.tsx` — текст: `const bm = await api.createThought(text); openDetail(bm)` (DEC-7); голос: `openDetail(bm)` в `onCreated`. Снять 2 TODO(notes-as-conversations).
- **Acceptance:** создал текст/голос → открылась переписка заметки.

### D1 — Документация
- Новый `docs/requirements/бт-14-заметка-как-диалог.md` (Bot/Backend + Mini App); правки бт-01/02/07/11 на стыках. По мере шипа (docs-with-code).

---

## Изменения в PRD по итогам ревью (внести в NOTES-AS-CONVERSATIONS.md)
- FR-5/NFR-1: re-embed = отдельный classify-free джоб; FTS дописок = миграция триггера (DEC-1/2).
- `duration` SMALLINT → DOUBLE PRECISION (DEC-5).
- Entry-контракт — плоский, не вложенный `voice{}` (DEC-4).
- edge #7/#13: удаление дописки не откатывает связи (DEC-9, MVP-долг).
- Open questions #1 (debounce) и #2 (per-entry статус) — закрыты (DEC-3, DEC-11); #4 (пагинация) — вне MVP (DEC-6).
- Новый edge: cap 8000 эмбеддинга обрезает длинный хвост дописок (windowing вне MVP).
