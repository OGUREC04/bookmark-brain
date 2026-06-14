# ADR 0011 — Приём голоса и файлов из Mini App

**Статус:** принято
**Дата:** 2026-06-14 (фича 3sr, ветка `feat/miniapp-media-upload`)
**Связано с:** `shared/media/`, `backend/app/api/uploads.py`, `backend/app/worker/uploads.py`, бриф `docs/prd/MINIAPP-MEDIA-UPLOAD.md`, тикеты `bookmark-brain-3sr` / `ti0`

## Context

В боте голос и документы уже работают: бот скачивает файл из Telegram, прогоняет STT (`bot/services/stt.py`) или извлечение текста (`bot/services/extractor.py`), и шлёт готовый `raw_text` в backend через `POST /bookmarks/`. Mini App так не может — он живёт в браузере внутри Telegram и не отправляет Telegram-сообщения. Значит нужен HTTP-путь приёма медиа прямо в backend, а STT/extract должны стать доступны вне процесса бота.

Четыре развязки требовали решения: где взять STT/extract код для backend; как передать загруженный файл между контейнерами; как перегнать браузерный звук в формат распознавалки; и как не заставлять Mini App ждать синхронно.

## Decision

**AD-1. Общий пакет `shared/media/`.** `stt.py` и `extractor.py` вынесены из `bot/services/` в `shared/media/` (корень репо) — их импортят и бот, и backend-воркер. Пакет — лист: не импортит `bot`/`app`, конфиг инжектится аргументами. Заморожено import-linter контрактом + pytest-зеркалом (`tests/test_shared_is_leaf.py`). Перенос — verbatim `git mv` + механическая замена пути импорта, ноль изменений поведения.

**AD-2. Файл API→воркер через Object Storage (S3).** У контейнеров backend и worker нет общего тома. Загруженные байты кладутся в Yandex Object Storage (`uploads/{uuid}`), воркер качает и удаляет. Переиспользуем уже настроенный бакет (тот же, что async STT). Тонкая обёртка `shared/media/storage.py` (`UploadStorage`).

**AD-3. Транскод браузерного аудио через ffmpeg в воркере.** Браузер пишет WebM/Opus (Android) или MP4/AAC (iOS); Yandex SpeechKit принимает только OGG Opus / MP3 / LPCM. Воркер перегоняет неродной формат в OGG Opus (`shared/media/transcode.py`, ffmpeg-бинарь в worker-образе). Голос из Telegram (уже OGG Opus) и MP3 транскод пропускают.

**AD-4. Черновик + асинхронная обработка.** `POST /api/v1/bookmarks/upload` валидирует, кладёт файл в S3, создаёт заметку-черновик (`ai_status` = `transcribing` для аудио / `extracting` для документов, `source=miniapp`) и **сразу** возвращает `BookmarkResponse` 201. Воркер-джоба `process_upload_task` делает STT/extract, дозаполняет заметку, ставит `ai_status=pending` и отдаёт её в ОБЫЧНЫЙ конвейер (`process_bookmark_task`) — эмбеддинг/классификация/связи не дублируются. Mini App опрашивает `GET /bookmarks/{id}` и видит `transcribing → pending → completed` (или `failed` + `ai_error`).

**AD-5. Docker build-контекст бэка/воркера — корень репо.** Чтобы образы могли скопировать `shared/`, контекст сборки backend/worker/migrations поднят с `./backend` до `.`; ffmpeg ставится в worker-образ. Бот (контекст уже `.`) тоже теперь копирует `shared/`.

## Alternatives

- **STT/extract: отдельный pip-пакет** — версионирование и чистая граница, но overhead сборки wheel ради двух файлов (YAGNI). Отклонено в пользу пакета в монорепо.
- **Передача файла: общий Docker volume** — быстрее, без сети, но не масштабируется на несколько хостов и требует ручного cleanup/гонок. **Redis** — не для блобов (prod `maxmemory 128mb`). Выбран S3 как уже готовая инфра.
- **Транскод на фронте (WASM)** — backend без ffmpeg, но тяжелее приложение, капризно в Telegram WebView, дублирование форматной логики. **Whisper вместо Yandex** для Mini App (ест WebM/MP4 напрямую) — но OpenAI/Groq заблокированы из РФ (см. ADR 0002), а прод-VPS в РФ. Выбран backend-ffmpeg.
- **Синхронный upload (ждать STT в HTTP-ответе)** — проще для фронта, но STT (особенно async Yandex) идёт минутами → таймаут/повисший запрос. Выбран черновик + поллинг.

## Consequences

**Плюсы:**
- Голос/файлы работают прямо в Mini App, бот и backend делят один код STT/extract без дублирования.
- Граница `shared` заморожена контрактами — backend можно деплоить без кода бота.
- Поллинг `ai_status` уже есть во фронте — новый эндпоинт встроился без нового механизма.

**Минусы:**
- Новая инфра-зависимость: **ffmpeg** в worker-образе (+~50 МБ) и провижн **S3** (бакет уже есть).
- Build-контекст бэка/воркера расширен до корня — сборка тащит больше файлов; **обязательно проверить `docker compose build` перед деплоем** (контекст менялся).
- Длинное аудио упирается в таймаут джобы — поднят per-job `_job_timeout=300`, но очень длинные записи (минуты) всё ещё риск.
- Исходник лежит в S3 до обработки и удаляется в `finally`; орфаны при падении воркера — нужна lifecycle-политика на бакете (TTL).

## Open questions

- Lifecycle-правило на бакете (`uploads/` TTL) для подчистки орфанов — настроить на стороне Yandex Cloud.
- Документы (PDF/DOCX) — фаза 2 тем же эндпоинтом; фаза 1 фокус на голосе.
