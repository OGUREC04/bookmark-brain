# Бэк-бриф: «заметка-как-диалог» (B1–B4) + структурный /recurring — для независимой проверки

> Кому: бэкенд-сессия/разработчик. Цель: самостоятельно проверить, что сделано в Mini-App-сессии на стороне бэка.
> Дата: 2026-06-26 · Всё закоммичено и в `origin/main`. Прода нет — проверка на деве (Docker postgres+redis).
> Контекст-документы: [`docs/prd/NOTES-AS-CONVERSATIONS.md`](prd/NOTES-AS-CONVERSATIONS.md) (PRD), [`docs/prd/NOTES-AS-CONVERSATIONS-EPIC.md`](prd/NOTES-AS-CONVERSATIONS-EPIC.md) (эпик v2, решения DEC-1..11).

## TL;DR что сделано на бэке

1. **Структурный `/recurring`** (коммит `7493f63`): эндпоинт принимает ЛИБО `raw` (бот `/repeat`), ЛИБО `{text, rule, hour, minute}` (Mini App — без парсинга). Фикс: слова расписания внутри текста серии больше не искажают сохранённый текст.
2. **«Заметка-как-диалог», бэк-ядро** — дописки (append-лог) к заметке:
   - **B1** (`6e1070f`): таблица `note_entries` + модель `NoteEntry` + миграция `d3e4f5a6b7c8` + колонка `bookmarks.entries_text`.
   - **B2** (`3306c99`): CRUD-эндпоинты `entries.py` (thread/entries) + плоская `Entry`-схема.
   - **B3** (`6b5d549`): classify-free re-index `reembed_bookmark_task` + FTS-миграция `e4f5a6b7c8d9` + debounce в эндпоинтах + расширение `_build_embedding_text`.
   - **B4** (текущий коммит): голос-в-дописку — `POST /bookmarks/{id}/entries/upload` (только аудио) + воркер `process_entry_upload` (STT → `body`/`transcription`, `entry_ai_status` `done`/`failed`; по готовности → debounce re-index B3). Миграции НЕ нужны (voice-поля `media_file_id`/`transcription`/`duration`/`entry_ai_status` уже в B1).

Brain **молчит** (kind всегда `user`), но дописки **попадают в поиск и связи** (отдельный classify-free джоб, 0 LLM-classify на дописку). Голос-дописка classify заметки тоже **не** запускает — только STT записи + re-index.

## Изменённые файлы

| Файл | Что |
|------|-----|
| `backend/app/models.py` | `NoteEntry` (kind ENUM user/brain/system `create_type=False`; soft-delete `is_deleted`; voice-поля; `duration` Float) + `Bookmark.entries_text` (Text, под FTS) |
| `backend/app/api/entries.py` | **новый** роутер: GET `/bookmarks/{id}/thread`, POST/PATCH/DELETE entries; IDOR; `_schedule_reindex` (debounce). **B4:** `POST .../entries/upload` (аудио, лимиты/415/413, валидация `duration`, basename имени) |
| `backend/app/worker/entry_uploads.py` | **новый (B4):** `process_entry_upload` — STT голос-дописки (reuse `_transcribe`/`_build_storage` из `worker/uploads.py`), идемпотентность по `entry_ai_status`, по готовности → debounce re-index |
| `backend/app/schemas.py` | `EntryCreate`/`EntryUpdate`/`EntryResponse` (**плоская**, без `voice{}`)/`ThreadResponse`; ранее — `RecurringCreate` (структурный) |
| `backend/main.py` | регистрация `entries_router` |
| `backend/app/services/bookmark_processor.py` | `_build_embedding_text(bm, clf, entries_bodies=None)` — дописки в основу эмбеддинга (обратно совместимо) |
| `backend/app/worker/scheduled.py` | **новый** `reembed_bookmark_task` (classify-free re-index одной заметки) |
| `backend/app/worker/__init__.py` | `reembed_bookmark_task` + `process_entry_upload` (B4, `func(..., timeout=300)`) в `WorkerSettings.functions` + `__all__` |
| `backend/app/api/recurring.py` | структурная ветка create (ранее) |
| migrations | `d3e4f5a6b7c8_add_note_entries.py`, `e4f5a6b7c8d9_fts_include_entries.py` |
| tests | `test_note_entry_model.py`, `test_entries_api.py`, `test_reembed_bookmark.py` (+ `test_recurring_api.py` дополнен) |

## Контракт (для справки)

**Note entries** (`prefix=/api/v1`, IDOR через владение заметкой → 404):
- `GET /bookmarks/{id}/thread` → `{entries: Entry[], total}` — неудалённые, по `created_at`, БЕЗ пагинации (MVP).
- `POST /bookmarks/{id}/entries` `{body}` → `Entry` (kind=`user`); пустой body → 422.
- `PATCH /bookmarks/{id}/entries/{eid}` `{body}` → `Entry` (ставит `edited_at`).
- `DELETE /bookmarks/{id}/entries/{eid}` → 204 (soft-delete `is_deleted=true`).
- Каждая мутация ставит debounce-джоб `reembed_bookmark_task` (`_job_id=f"reembed:{bid}"`, `_defer_by=45с`, best-effort).

`Entry` = `{id, kind, body, created_at, edited_at, transcription?, duration?, entry_ai_status?}` — **плоская** форма (как `BookmarkResponse`).

**Голос-дописка (B4):** `POST /bookmarks/{id}/entries/upload` (multipart: `file` + опц. `duration`). Только аудио (документ → 415); пустой → 400; больше лимита → 413; невалидная `duration` (NaN/inf/<0/>6ч) → 422. Создаёт `Entry` `kind='user'`, `body=''`, `entry_ai_status='transcribing'`, `media_file_id` (ключ S3). Воркер `process_entry_upload` распознаёт → `body`/`transcription`, статус `done`/`failed`; по готовности → `reembed_bookmark_task` (debounce). Фронт поллит GET `/thread` пока есть `transcribing` (DEC-11).

**Recurring** (`POST /api/v1/recurring/`): `RecurringCreate` = `raw` (бот) ИЛИ `{text, rule, hour, minute}` (Mini App); структурный путь не вызывает `recurrence_parser`.

## ✅ Чеклист независимой проверки

> Запуск из корня репо. Бэк-тесты — системный Python 3.14 (как в STARTUP), мок-сессии, БД не нужна.

**1. Unit-тесты (без БД):**
```bash
python -m pytest backend/tests/test_note_entry_model.py backend/tests/test_entries_api.py \
  backend/tests/test_reembed_bookmark.py backend/tests/test_recurring_api.py \
  backend/tests/test_process_entry_upload.py backend/tests/test_entry_upload_endpoint.py -q
```
Ожидаемо: всё зелёное (~65). B4-инварианты: только аудио (415); невалидная `duration` → 422; воркер заполняет `body`/`transcription` + статус `done`; STT-ошибка → `failed` (запись остаётся); soft-delete до старта джоба → пропуск (без STT); по готовности → debounce re-index; classify заметки НЕ вызывается. Ключевые инварианты в тестах: IDOR 404 на чужой заметке; пустой body 422; soft-delete не в thread; `reembed_bookmark_task` НЕ вызывает classify; дописки попадают в `_build_embedding_text`; debounce-enqueue с верным `_job_id`; структурный recurring хранит текст дословно.

**2. Миграции вживую (Docker postgres):**
```bash
cd backend && export PYTHONPATH=..   # или как в проекте
python -m alembic upgrade head            # → e4f5a6b7c8d9
python -m alembic current                 # подтвердить head
python -m alembic downgrade c2d3e4f5a6b7  # откат обеих
python -m alembic upgrade head            # обратно (проверка обратимости)
```
Ожидаемо: накат/откат/накат без ошибок; единственный head `e4f5a6b7c8d9`.
Без Docker — офлайн-SQL: `alembic upgrade c2d3e4f5a6b7:e4f5a6b7c8d9 --sql`.

**3. FTS-смок (дописка реально находится поиском):**
```sql
BEGIN;
WITH u AS (INSERT INTO users (telegram_id) VALUES (987654321) RETURNING id)
INSERT INTO bookmarks (user_id, raw_text, entries_text)
SELECT id, 'тело заметки', 'абракадабратест' FROM u
RETURNING search_vector @@ to_tsquery('russian','абракадабратест');  -- ждём t
ROLLBACK;
```
Триггер `bookmarks_search_vector_trigger` должен срабатывать на `UPDATE OF ... entries_text` и включать `entries_text` в `to_tsvector`.

**4. Глаз на главное:**
- `reembed_bookmark_task` (`worker/scheduled.py`) — НЕ трогает `ai_status`/classify/summary/title; только `embedding` + `entries_text` + `build_links_for_bookmark`. Образец — `reembed_all_bookmarks` рядом.
- `_build_embedding_text` — 3-й арг `entries_bodies` опционален; два старых вызова (там же и `reembed_all_bookmarks`) дают 2 аргумента → поведение прежнее.

## Принятые MVP-границы (НЕ баги — зафиксировать при ревью)

- **Удаление дописки НЕ откатывает уже построенные связи** (`build_links` только добавляет, ON CONFLICT DO NOTHING). DEC-9.
- **Эмбеддинг cap 8000 симв** — очень длинный лог обрежет хвост (windowing вне MVP).
- **Гонка** `reembed_bookmark_task` ↔ note-level reprocess (0rn, полный classify): оба пишут embedding/links, last-writer-wins; самолечится при следующей дописке. DEC-10.
- **Debounce-окно фиксированное** (`_defer_by=45с`, не сдвигается); burst в окне → 1 джоб (arq `_job_id`-дедуп). DEC-3.
- `search_vector` — конфигурация `'russian'` (как и было для заметок).

## Открытые follow-up (НЕ в этом скоупе)

- ⚠️ **Batch-джобы `reembed_all_bookmarks` и `retry_partial_embeddings` НЕ учитывают дописки** — для заметки с логом перезапишут embedding без дописок (самолечится при следующей дописке). Заведена отдельная задача — сделать их entries-aware.
- Фронт (F1–F4), БТ-14 + `docs/API.md` — ещё не сделаны. (B4 голос-в-дописку — сделан, см. выше.)
- Голос-дописка: per-entry `ai_error` колонки нет — при `failed` статус есть, текст ошибки только в логах (фронт показывает общий «не распозналось» + перезапись). MVP-граница.

## Что проверить особенно (если есть сомнения)
- Транзакционность `reembed_bookmark_task`: `flush` до `build_links`, единый `commit`.
- Что `entries_text` денормализуется корректно при добавлении/правке/удалении дописки (через debounce-джоб), и search_vector обновляется.
- IDOR на всех 4 эндпоинтах (тесты есть, но проверь руками на чужой заметке → 404).
