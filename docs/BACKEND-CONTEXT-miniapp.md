Both load-bearing points verified against source. The reminder schema confirms `text: str | None = None` (8uu YES), and `task_list_offer.py` confirms `_MAX_OFFER_ITEM_LEN = 80` with an off-by-one in the clip logic (`tx[: _MAX_OFFER_ITEM_LEN - 1]` keeps 79 chars + "…", so an 80-char item gets needlessly truncated). That reconciles the two readers' disagreement. Here is the brief.

---

# BACKEND CONTEXT BRIEF — BookmarkBrain DEV

> Для холодной backend-сессии. Репозиторий: `D:/projects/bookmark-brain` (FastAPI в `backend/app`, arq-воркер в `backend/app/worker`, общий код в `shared/`). **Только DEV, прода нет.** Фронт Mini App живёт в отдельном репо `D:/projects/bookmark-brain-miniapp` — сюда не лезем, но его ожидания формируют контракты ниже.

Термины простыми словами по ходу: **arq** — очередь фоновых задач на Redis (фронт не ждёт, воркер делает в фоне); **STT** (speech-to-text) — распознавание речи в текст; **эмбеддинг** — числовой вектор (1024 числа), которым кодируется смысл текста, чтобы искать похожее; **cosine similarity** — мера схожести двух векторов от 0 до 1; **pgvector** — расширение PostgreSQL для хранения векторов и поиска ближайших; **IDOR** — проверка «ресурс принадлежит этому юзеру», защита от подглядывания чужих данных.

---

## 1. Что включено во фронте и что это требует от бэка

**Voice (`VOICE_UPLOAD=true`).** Mini App открывает полноэкранный ComposeScreen, пишет голос и шлёт его как файл в `POST /api/v1/bookmarks/upload` (multipart — то есть обычная загрузка файла формой). Бэк обязан: принять файл, проверить формат и размер, положить в S3 (облачное файловое хранилище Yandex), создать **черновик** закладки со статусом `ai_status="transcribing"` (аудио) или `"extracting"` (документ), поставить в очередь arq задачу `process_upload_task` и сразу вернуть `201` с телом закладки. Дальше фронт **опрашивает** (polling) `GET /bookmarks/{id}` раз в 1–2 сек и смотрит поле `ai_status`, пока оно не дойдёт до терминального состояния (`completed`/`partial`/`failed`). Контракт: эндпоинт `backend/app/api/uploads.py`, воркер `backend/app/worker/uploads.py`, медиа-утилиты в `shared/media/`.

**Connections (`CONNECTIONS=true`).** Вкладка «Граф» и секция «Связано» во фронте опираются на семантический граф закладок (Phase 5A). Бэк строит рёбра графа **без единого вызова LLM** — только через pgvector kNN (поиск ближайших векторов): при сохранении закладки `build_links_for_bookmark` находит топ-30 кандидатов с cosine ≥ 0.73 и пишет их в таблицу `bookmark_links`. Фронт берёт полный граф через `GET /graph` (+ флаг `stale`, нужно ли пересчитать раскладку), строит координаты локально через react-force-graph и кэширует их обратно через `POST /graph/build`. Секция «Связано» — это `GET /bookmarks/{id}/related` (топ-5 по cosine). Контракт: `backend/app/api/connections.py`, сервис `backend/app/services/connections.py`.

**Text-edit (`TEXT_EDIT=false`, ждёт включения).** Флаг во фронте пока выключен, потому что висел вопрос: принимает ли `PATCH /api/v1/reminders/{id}` поле `text` (тикет 8uu)? **Ответ — да, принимает** (см. §6, проверено по коду). Правка текста напоминания идёт через `PATCH /reminders/{id}` с полем `text`; правка текста заметки (0rn) — через `PATCH /bookmarks/{id}` с полем `raw_text`. Оба бэкенд-контракта уже реализованы, фронт можно включать.

---

## 2. API-контракты

### POST /api/v1/bookmarks/upload — `backend/app/api/uploads.py`
| | |
|---|---|
| Метод/путь | `POST /api/v1/bookmarks/upload` |
| Запрос | `multipart/form-data`: **file** (обязателен), **kind** (`audio`/`document`, авто-детект если пусто), **caption** (≤50k симв.), **duration** (float, сек — для роутинга Yandex sync/async), **title** (≤500). JWT в `Authorization`. `source` авто = `miniapp`. |
| Ответ | `201` + `BookmarkResponse` (`ai_status="transcribing"` для аудио / `"extracting"` для документа). Ошибки: `400` (пустой/неподдержанный), `413` (больше лимита), `415` (неподдержанный MIME/расширение). |
| Подводные камни | Аудио: `.ogg .oga .mp3 .m4a .wav .webm .mp4 .aac .flac`. Документы: PDF/DOCX/TXT/MD. Лимиты `UPLOAD_MAX_AUDIO_MB=25`, `UPLOAD_MAX_DOC_MB=20`. Задача ставится с `_defer_by=3s`, чтобы строка-черновик успела закоммититься до того, как воркер её прочитает. Валидация размера через `read(limit+1)` — без OOM на огромных файлах. |

### GET /api/v1/bookmarks/{id} — `backend/app/api/bookmarks.py`
| | |
|---|---|
| Метод/путь | `GET /api/v1/bookmarks/{bookmark_id}` |
| Запрос | UUID в пути, JWT. Возвращает только если `user_id` совпадает с текущим юзером (IDOR-защита). |
| Ответ | `200` + `BookmarkResponse` (поля `ai_status`, `ai_error`, `transcription`, `document_page_count`, `summary`, `category`, `tags`…). `404` если не найдено / чужое. |
| Подводные камни | **Это polling-эндпоинт фронта.** Терминальные `ai_status`: `completed` / `partial` / `failed`. На `failed` заполняется `ai_error`. |

### GET /api/v1/graph + /graph/local + POST /graph/build — `backend/app/api/connections.py`
| | |
|---|---|
| `GET /api/v1/graph` | JWT. → `GraphResponse {nodes:[{id,title,item_type}], edges:[{from,to,weight}], layout, stale:bool, node_count, built_at}`. Кап **300 узлов** (с эмбеддингом, неархивные, новые первыми). `stale=true` если layout пуст ИЛИ `|текущее число рёбер − layout.edge_count| ≥ GRAPH_STALE_EDGE_DELTA (=8)`. |
| `GET /api/v1/graph/local?center={UUID}&depth={1-3}` | Эго-граф (BFS вокруг узла), depth по умолчанию 2, кап **150 узлов**, без кэша. IDOR: `center` должен принадлежать юзеру (иначе `404`, не `403`). |
| `POST /api/v1/graph/build` | Тело `GraphBuildRequest {nodes:[...]}`, макс **350** (отвергает > cap+50 → `422`). Сохраняет координаты в `graph_layouts` + снимок `edge_count` для расчёта `stale`. Идемпотентно: `ON CONFLICT (user_id) DO UPDATE`. → `{node_count, saved:true}`. |

### GET /api/v1/bookmarks/{id}/related — `backend/app/api/connections.py`
| | |
|---|---|
| Метод/путь | `GET /api/v1/connections/bookmarks/{bookmark_id}/related?all={bool}&limit={1-50}` |
| Запрос | UUID в пути, JWT. `limit` по умолчанию **5**. |
| Ответ | `200` + `RelatedResponse {items:[{id,title,summary,item_type,weight,created_at}], total}`. `weight` = cosine. |
| Подводные камни | **0 вызовов LLM** — чистый pgvector hnsw-индекс. Берёт обе стороны ребра (`from_id=X OR to_id=X`), фильтрует архивные, сортирует по `weight DESC`. IDOR по `user_id`. `total` — точный если `all=true`, иначе кэшированный счётчик (метка кнопки «Похожие (N)»). |

### PATCH /api/v1/bookmarks/{id} — `backend/app/api/bookmarks.py` (тикет 0rn)
| | |
|---|---|
| Метод/путь | `PATCH /api/v1/bookmarks/{bookmark_id}` |
| Запрос | `BookmarkUpdate {title, is_favorite, is_archived, folder_id, structured_data, raw_text (≤50000)}`. JWT. |
| Ответ | `200` + `BookmarkResponse`. `422` если `raw_text` пустой/>50k. |
| Подводные камни | **Materiality gate** (`bookmarks.py:34-58`): порог `_REPROCESS_TEXT_SIMILARITY_THRESHOLD=0.85`. `_text_changed_materially()` сравнивает старый/новый текст через `difflib.SequenceMatcher` **по первым 4000 символам** (защита от O(n²)). Если ratio < 0.85 **или** дельта длины > 30% → `ai_status=pending` + переочередь `process_bookmark_task` (пересчёт эмбеддинга/summary/тегов). Мелкая правка (опечатка) — тихо сохраняется без LLM. Правка `structured_data` каскадит на напоминания через `apply_cascade()` (best-effort, падение каскада не валит основной апдейт). |

### PATCH /api/v1/reminders/{id} — `backend/app/api/reminders.py` (тикет 8uu)
| | |
|---|---|
| Метод/путь | `PATCH /api/v1/reminders/{id}` |
| Запрос | `ReminderUpdate {fire_at: datetime\|null, text: str\|null}` — **оба опциональны**, хотя бы одно для не-no-op. |
| Ответ | `200` + `ReminderResponse {id, bookmark_id, kind, fire_at, status, payload, created_at, sent_at, bookmark_title, bookmark_raw_text, deduplicated}`. |
| Подводные камни | `fire_at` только → snooze (`status=pending`, чистит `sent_at`/`cancelled_at`). `text` только → пишет в `payload["text"]`, время/статус не трогает. Оба — вместе. **`text` правится только для `status="pending"`** → иначе `409`. Пусто/>2000 → `422` (`MAX_REMINDER_TEXT_LEN=2000`, `reminders.py:51`). Запись через **пересборку нового dict** (JSONB-safe), не in-place мутация. Реализация `reminders.py:128-197`, запись текста `185-188`. |

---

## 3. Модель данных — `backend/app/models.py`

**Bookmark** (`id` UUID PK, `user_id` FK CASCADE):
- Источник: `source` (`telegram`/`miniapp`/`bot`), `source_message_id` (unique per user+source — дедуп), `source_date`, `url`, `content_type` (`voice`/`document`/`other`…).
- Текст/медиа: `raw_text` (NOT NULL), `title` (≤500), `transcription` (результат STT, только аудио), `media_file_id`, `media_duration` (float, сек), `document_page_count` (int, только PDF).
- AI-поля (16 шт.): `summary`, `category`, `language`, `item_type` (`action`/`thought`/`content`/`reference`), `key_ideas` JSONB, `entities` JSONB, `open_questions` JSONB, `takeaway`, `structured_data` JSONB (списки задач, формы напоминаний), `embedding` `Vector(1024)`, `search_vector` TSVECTOR.
- Статус: **`ai_status` (String(20))** — `pending` → `processing` → терминал; для upload-цепочки добавлены `transcribing`/`extracting` как стартовые. Терминальные: **`completed`** (полный AI-выход), **`partial`** (деградировавший успех — текст есть, но что-то отвалилось, напр. таймаут GigaChat или ошибка эмбеддинга), **`failed`** (постоянная ошибка). `ai_error` (Text, ≤500), `ai_processed_at`, `retry_count`, `embedding_retry_count`, `embedding_last_attempt`.
- Флаги/связи: `folder_id` FK SET NULL, `is_favorite`, `is_archived`, теги через M2M `BookmarkTag`.

**BookmarkLink** (`id` UUID, `user_id` FK CASCADE денормализован — для одно-индексных запросов, `from_id` FK, `to_id` FK, `kind` ENUM `similar`/`manual`/`derived_from_space` — в MVP только `similar`, `weight` float = cosine 0–1, `created_at`). Ограничения: `UNIQUE(from_id, to_id, kind)`, `CHECK(from_id != to_id)`. Рёбра пишутся канонически (`from_id ≤ to_id`) с `ON CONFLICT DO NOTHING` → идемпотентность. Индексы: `(user_id)`, `(from_id, weight DESC)`, `(to_id, weight DESC)`.

**ScheduledMessage** (`id` UUID, `user_id` FK CASCADE, `bookmark_id` FK CASCADE nullable, `kind` ENUM `reminder`/`digest`/`surfacing`/`nudge`, `fire_at` datetime UTC, `status` ENUM `pending`/`sending`/`sent`/`done`/`cancelled`/`failed`, `payload` JSONB `{text?:str,...}`, `retry_count`, `message_id` (Telegram message_id после отправки), `created_at`, `sent_at`, `cancelled_at`). Текст напоминания живёт в `payload["text"]` (≤2000).

**GraphLayout** (`user_id` UUID PK FK CASCADE, `nodes` JSONB `[{id,x,y,vx,vy}]`, `node_count`, `edge_count` — снимок на момент build, `built_at`).

Прочее: **Users** (`telegram_id` bigint unique, `timezone` default `Europe/Moscow`, `settings` JSONB), **Tags**, **Folders**, **AnalyticsEvent** (партиционирован по месяцам).

**Ключевые индексы:** `idx_bookmarks_ai_pending` (partial `where ai_status != completed`), `idx_bookmarks_source_dedup` (unique partial), `idx_bookmarks_embedding` (hnsw m=16 ef=64), `idx_scheduled_messages_pending_fire` (partial `where status=pending`). Тред/messages-таблицы (заметки-как-диалоги) в коде **нет** — решение «тихий append-лог сначала», новой схемы пока не существует.

---

## 4. Потоки обработки

### Voice/document upload chain (S3 → ffmpeg → STT → AI-pipeline)
1. **Upload** (`uploads.py`): валидация формата и размера → S3 put в `s3://{bucket}/uploads/{bookmark_id}.{ext}` → создание черновика `Bookmark` (`raw_text=caption.trim()`, `ai_status=transcribing|extracting`, `source=miniapp`) → enqueue `process_upload_task` с `_defer_by=3s` → `201`.
2. **Polling**: фронт опрашивает `GET /bookmarks/{id}` ~1–2 сек, крутит спиннер пока `transcribing|extracting`.
3. **`process_upload_task`** (`backend/app/worker/uploads.py`, `timeout=300s`, `max_tries=5`): скачивает файл из S3 в `/tmp`. **Идемпотентность** — если статус уже не `transcribing|extracting` (`_ACTIVE_DRAFT`), пропускает (повторный arq-retry после успеха не перетранскодит/не перераспознаёт).
   - **Аудио**: `needs_transcode` сверяет расширение с `_NATIVE_AUDIO_EXTS={.ogg,.mp3,.oga}`; если надо — ffmpeg перегоняет WebM/MP4 → **OGG Opus** (`shared/media/transcode.py`, `TranscodeError`). Затем STT (`shared/media/stt.py`): Yandex sync ≤30 сек, async >30 сек (через S3 + поллинг до 200×3с = 10 мин; >60 мин — отказ).
   - **Документ**: `detect_format(content_type, filename)` → `extract_text` (`shared/media/extractor.py`, PDF/DOCX/TXT/MD через `asyncio.to_thread`, кап **50k символов** + маркер `[обрезано]`).
   - Объединяет `caption + extracted_text` → `final_text`.
4. **Ошибки**: ловит `STTError`/`ExtractError`/`TranscodeError` → `ai_status=failed` + `ai_error` (≤500) + удаление S3-объекта. На транзиентной ошибке (`try < 5`) — re-raise для arq-retry, S3-объект сохраняется. На последней попытке — `failed` + чистка S3.
5. **Finalize**: пишет `raw_text=final_text`, `transcription` (аудио), `document_page_count` (док), `ai_status=pending`. **Enqueue `process_bookmark_task` ДО коммита** (fail-safe: если enqueue упал — строка откатывается в черновик, arq-retry перезапустит). Коммит.
6. **AI-pipeline** (`process_bookmark_task`, дальше — общий путь, см. ниже).

### AI-pipeline + connection-building (embedding → cosine → edges)
`process_bookmark_task` (`backend/app/worker/processing.py`, ~750 строк; сервис `bookmark_processor.py`):
1. Если есть URL — фетч статьи (trafilatura).
2. **Классификация** через LLM (`ai_classifier.py`: GigaChat / DeepSeek / Claude) → `summary`, `category`, `language`, `item_type`, `takeaway`, `key_ideas`, `entities`, `open_questions`, `reminder_items`. На `RetryableError` → re-enqueue (max 5). На `ClassificationError` → `failed` + fallback на эвристический детектор списков (без LLM).
3. Детект списка задач (Phase 2) → `structured_data` + NL-парсинг дедлайнов.
4. **Embedding** (`embeddings.py`, провайдер Voyage или GigaChat, 1024-dim; текст: реальный контент primary + AI-поля secondary, ≤8000 символов). Ошибка эмбеддинга → `ai_status=partial`, сохраняем.
5. Теги (batch upsert).
6. **Reminder router** (Phase 2.6, `reminder_decision.py`): `route_reminder` выбирает форму (`single_reminder`/`composite_reminder`/`task_list_with_reminders`/`needs_button_choice`/`none`).
7. `ai_status=completed`.
8. **Best-effort `_maybe_build_connections`**: `build_links_for_bookmark` (`services/connections.py`) — pgvector kNN, топ-30 кандидатов с **cosine ≥ 0.73**, канонические рёбра (`from_id ≤ to_id`) → `bookmark_links`, `ON CONFLICT DO NOTHING`. Ошибки эмбеддинга/линковки **не валят задачу** (логируются).
9. **Dedup** (Phase 5D-lite, `find_near_duplicate`): Pass 1 cosine ≥ 0.85; Pass 2 текстовый `difflib.SequenceMatcher` (ratio < 0.70) если эмбеддинг недоступен. Нашли → алерт в Telegram.
10. **Safety net**: на последней попытке (try 5/5) — реакция 👎, сообщение об ошибке в чат, без re-raise.

---

## 5. Инфра / env на DEV — `backend/app/config.py`, `.env.example`, `docker-compose.yml`

- **PostgreSQL** `pgvector:pg16` (Docker), драйвер asyncpg: `DATABASE_URL=postgresql+asyncpg://...`. pgvector — векторы + cosine kNN; TSVECTOR — полнотекст; кастомные ENUM (`scheduled_kind`, `scheduled_status`, `link_kind`).
- **Redis** `7-alpine` (Docker): `REDIS_URL`. Очередь arq + кэш состояния напоминаний (`reminder:{chat_id}:{message_id}`, TTL 25ч) + дедуп-алерты + `task_list_pending`.
- **arq worker**: 6 python-процессов, `max_jobs=5`, базовый `job_timeout=120s`, override для `process_upload_task` (`timeout=300s`, `max_tries=5`). Cron'ы (`backend/app/worker/scheduled.py`): `scheduled_dispatcher` (1/мин — рассылка due-напоминаний через CAS-апдейт `pending→sending→sent`), `auto_done_reminders` (`AUTO_DONE_HOURS=24`), `retry_failed_task` (30 мин), `retry_partial_embeddings` (часовой — добивает `partial`-эмбеддинги, `embedding_retry_count<3`), `stale_list_nudge` (`NUDGE_HOUR_UTC=6` MSK), `analytics_partition_maintenance` (daily). Конфиг: `backend/app/worker/__init__.py` (WorkerSettings — фасад, ре-экспорт из processing/scheduled/reminder_decision).
- **S3** (Yandex Object Storage): `YANDEX_S3_ENDPOINT=https://storage.yandexcloud.net`, `YANDEX_S3_BUCKET` (напр. `bookmarkbrain-stt`, общий с ботом), `YANDEX_S3_ACCESS_KEY` / `YANDEX_S3_SECRET_KEY` (статические из Yandex Cloud IAM). Префиксы: `uploads/{bookmark_id}.{ext}` (Mini App), `stt-tmp/{uuid}.{ext}` (async STT). boto3 lazy-init под `threading.Lock` (`shared/media/storage.py`).
- **Yandex STT (+billing)**: `STT_PROVIDER=yandex` (рекоменд. для RU/CIS — Whisper-API заблокированы из РФ), `YANDEX_CLOUD_API_KEY` (SpeechKit), `YANDEX_CLOUD_FOLDER_ID` (привязка к биллингу Yandex Cloud — без folder_id запросы не тарифицируются и падают). Альтернативы: `WHISPER_API_KEY` (если `openai`/`groq`).
- **ffmpeg**: бинарь на PATH, **v8.1.1 подтверждён** (перегон WebM/MP4 → OGG Opus). В Docker-образ бэка/воркера должен быть включён (directory-level COPY + package-импорты — file→package прозрачно для прода).
- **GigaChat**: `AI_PROVIDER=gigachat` (дефолт) — нужны `GIGACHAT_AUTH_KEY` + `GIGACHAT_CA_BUNDLE` (TLS-сертификат Минцифры/Сбера). Альтернативы: DeepSeek (`DEEPSEEK_API_KEY`), Claude (`ANTHROPIC_API_KEY`).
- **Voyage**: `EMBEDDING_PROVIDER=voyage` → `VOYAGE_API_KEY` (или `gigachat`). 1024-dim на выходе в любом случае.
- **Прочее**: `MINI_APP_URL` (ngrok-туннель, синхронизирован с .env), `SECRET_KEY` (обязателен, не должен иметь дефолт), `BOT_SECRET` (общий с ботом), `ENVIRONMENT=development`, `DEV_AUTH_BYPASS` (только dev; если включён — `ENVIRONMENT != production` И `DEV_AUTH_TELEGRAM_ID > 1e12`), `TELEGRAM_BOT_TOKEN`, `UPLOAD_MAX_AUDIO_MB=25`, `UPLOAD_MAX_DOC_MB=20`.

---

## 6. Открытые пункты (что проверить / сделать)

**❓ «PATCH /reminders принимает text?» → ДА (проверено по исходнику).** `backend/app/api/schemas.py:257-266`:
```python
class ReminderUpdate(BaseModel):
    """Тело PATCH /api/v1/reminders/{id}.
    Snooze: меняем `fire_at` (статус → pending). Правка текста: `text`
    персистится в `payload["text"]`. Хотя бы одно из полей — иначе no-op.
    Можно слать только `text`, только `fire_at`, или оба (тикет 8uu).
    """
    fire_at: datetime | None = None
    text: str | None = None
```
Эндпоинт `reminders.py:128-197`, запись текста через JSONB-safe пересборку dict (`185-188`), `MAX_REMINDER_TEXT_LEN=2000` (`reminders.py:51`). Правка только для `status="pending"` (иначе `409`), пусто/>2000 → `422`. Тесты: `backend/tests/test_reminders_api_validation.py:194-268` (`TestUpdateReminderText`). **Тикет 8uu закрыт, доработок не требуется — фронт можно включать `TEXT_EDIT`.** То же для 0rn (`raw_text` + materiality gate 0.85) — готово, тесты `test_bookmark_text_edit.py:51-100`.

**backfill_bookmark_links** (`backend/app/worker/scheduled.py`, ~строка 83). One-shot задача Phase 5A: массово строит рёбра `bookmark_links` для **старых** закладок (созданных до включения авто-линковки). Что делает: keyset-итерация по закладкам с эмбеддингом (батчи 200), вызов `build_links_for_bookmark` на каждую, коммит по батчу, 0 LLM, идемпотентно (`ON CONFLICT`). **Не в расписании — только ручной запуск.** Как прогнать на DEV:
```python
# из python-сессии с настроенным arq-пулом
await pool.enqueue_job("backfill_bookmark_links", batch_size=200)
```
Проверить: (1) **идемпотентность** — повторный прогон не плодит дубли пар; (2) что строит эмбеддинг если его нет, либо **gracefully пропускает** закладки без вектора (не падает); (3) на 1000+ закладок — что keyset-итерация не жрёт память. **Важно (AD-7):** если эмбеддинги пересчитывались по новому рецепту — `reembed_all_bookmarks` должен пройти **до** backfill, иначе рёбра строятся в несогласованном векторном пространстве. **CONNECTIONS зависит от backfill** — для старых юзеров граф будет пустым, пока не прогнан.

**Тикет h3j2 (off-by-one 79/80 + тесты `task_list_offer`)** — `backend/app/worker/task_list_offer.py`. **Реконструировано по исходнику** (читатели расходились: «off-by-one 79/80» против «не найдено»). Истина посередине — баг реальный, но не в пагинации:
```python
_MAX_OFFER_ITEMS = 8      # строка 45
_MAX_OFFER_ITEM_LEN = 80  # строка 46
...
for tx in texts[:_MAX_OFFER_ITEMS]:        # строка 59
    if len(tx) > _MAX_OFFER_ITEM_LEN:      # строка 60: триггер при len > 80
        tx = tx[: _MAX_OFFER_ITEM_LEN - 1].rstrip() + "…"   # строка 61: оставляет 79 символов + «…»
```
**Off-by-one здесь:** граница — это длина строки превью пункта (80 символов), не количество пунктов в списке. Текст ровно 80 символов проходит без обрезки (`len(tx) > 80` ложно), а текст 81+ обрезается до **79** символов + «…» (срез `[:79]`). То есть видимый текст превью максимум 79 значимых символов, хотя лимит заявлен 80 — классический off-by-one в `_MAX_OFFER_ITEM_LEN - 1`. **Что сделать:** решить, какое поведение каноничное (обрезать при `> 80` оставляя 79+«…», или при `>= 80`, или оставлять полные 80). **Тестов на этот файл нет** — добавить `backend/tests/test_task_list_offer.py` на граничные случаи: ровно 8 пунктов (без «…и ещё»), 9 пунктов (есть «…и ещё 1»), пункт ровно 80 символов (не режется), пункт 81 символ (режется, проверить итоговую длину), пустые/whitespace-only пункты (отфильтрованы).

**Риски, которые стоит держать в голове:**
- **GigaChat ломает JSON** (известный инстинкт проекта) → нужен retry; DeepSeek стабильнее. Проявляется как `ai_status=partial` (текст есть, классификация не разобралась). Задокументировать в `processing.py`, когда именно ставится `partial` vs `completed`.
- **Стоимость эмбеддингов / STT**: встроенного учёта расходов (токены GigaChat, Voyage, Yandex STT async) **нет**. backfill на большом юзере = заметный счёт. Рассмотреть per-user cap / circuit breaker.
- **Dedup / connection churn**: `GRAPH_STALE_EDGE_DELTA=8` — если баннер «пересчитать граф» мигает слишком часто/редко, порог тюнить. Дедуп-алерты (cosine ≥ 0.85) могут быть навязчивыми.
- **Orphaned S3**: чистка best-effort на всех терминальных путях — проверить, нет ли осиротевших `uploads/{uuid}` за неделю нормальной работы.
- **Async STT UX**: запись >60 мин отвергается; протестировать на границе ~55 мин.
- **IDOR consistency**: на всех эндпоинтах чужой ресурс должен давать `404` (не `403`/`500`). Хелперы: `_get_user_reminder()` (`reminders.py:526-545`), проверки владения в `bookmarks.py:314-322`.

---

## 7. Что уже подтверждено живьём (НЕ перепроверять)

- `/health` — **ok**, postgres + redis отвечают.
- **ffmpeg v8.1.1** на PATH.
- Маршруты зарегистрированы (upload / graph / related / reminders / bookmarks).
- **ngrok** синхронизирован с `.env` `MINI_APP_URL`.
- **6 python-процессов** воркера запущено.
- Тикеты **8uu** (reminder `text`) и **0rn** (bookmark `raw_text` + materiality gate 0.85) — реализованы и покрыты тестами (`test_reminders_api_validation.py`, `test_bookmark_text_edit.py`).

> Напоминание про среду: ngrok-URL меняется каждую сессию → при рестарте обновлять `MINI_APP_URL` в `.env` и перезапускать. Один способ запуска за раз (start.bat **или** из чата, не одновременно); перед повторным `start.bat` — `stop.bat`.

---
**Применил:**
- `bt-writer` (`skill`) — стиль БТ bookmark-brain (понятный язык + пояснение терминов + корнер-кейсы) как образец для брифа
- `tracking` (`rule`) — увязал тикеты 8uu/0rn/h3j2 с файлами и acceptance для холодной сессии

**Цель ответа:** один связный backend-бриф, по которому холодная сессия поднимает контракты/модель/потоки/инфру и закрывает открытые пункты (8uu=да, backfill, h3j2 off-by-one 79/80).

---