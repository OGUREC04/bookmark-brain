# Epic: Connections MVP (Phase 5A)

**Статус:** Backlog → ready to decompose
**Дата:** 2026-06-10 · **ревизия 2026-06-13** (два решения ниже)
**PRD:** [../prd/CONNECTIONS-MVP.md](../prd/CONNECTIONS-MVP.md)
**Ресёрч:** [../research/связи-вектор-vs-граф-2026-06.md](../research/связи-вектор-vs-граф-2026-06.md)
**ROADMAP:** Phase 5A (Connections layer)
**Beads root:** `bookmark-brain-7j9`
**Прогресс:** задачи 1–8 (бэкенд + бот) реализованы за тестами (877 passed) и прошли состязательное ревью 2026-06-13. Не задеплоено. Осталось: 9 (Mini App), 10 (калибровка + накат миграции + деплой) — на стороне пользователя.

---

## Overview

Технический план реализации Connections MVP. PRD описал «что и зачем» (авто-связи по смыслу, семантический поиск, граф), edge cases, success criteria. Этот эпик — «как и в каком порядке», грунтованный по реальному коду (разведка 7 подсистем 2026-06).

Главный вывод разведки: **почти вся инфраструктура уже есть** — pgvector + HNSW-индекс, pipeline эмбеддингов Voyage voyage-3 (1024), прототип kNN в дедупликаторе, worker arq с паттернами фоновых джоб и cron-бэкфилла, гибридный поиск. Новый код — тонкий слой поверх: таблица рёбер, функция top-k, эндпоинты, кнопка в боте, таб во фронте. **Без новой инфраструктуры, без Neo4j, 0 токенов LLM.**

**Ревизия 2026-06-13 — два решения, меняющие план:**
1. **Эмбеддинг = реальный текст заметки + ИИ-поля** (а не только ИИ-выжимка, как было). Меняем `_build_embedding_text` — он **общий** с поиском и дедупом, поэтому пороги перепроверяем (AD-7, задача 10). Добавлена задача 2.
2. **Граф on-demand:** локальный (эго) граф — на лету у клиента; полный граф — **по кнопке «Построить граф»**, раскладка считается один раз и **кэшируется**; баннер «устарел — обновить?». Не пересчитываем на каждый вход (AD-8).

Цель — ~7–9 dev-days с минимальной рисковой поверхностью; бэкенд-ядро шипится раньше Mini App-графа.

---

## Architecture Decisions

Из PRD + ресёрча + разведки кода. Где разведка показала расхождение с первой версией PRD — отмечено `⚠ уточнение к PRD`.

| # | Решение | Альтернатива | Причина |
|---|---------|--------------|---------|
| AD-1 | **Денормализованный `user_id` в `bookmark_links`** (NOT NULL FK → users, ON DELETE CASCADE) | Скоупить по двойному JOIN к `bookmarks` | Связи всегда внутри одного юзера (инвариант FR-5) → `user_id` всегда консистентен. Даёт `WHERE user_id=X` одним индексом для графа и related без двойного JOIN. `⚠ уточнение к PRD`. |
| AD-2 | **Сборка связей — inline в worker** после персиста эмбеддинга, best-effort (ошибка не валит обработку закладки) | Отдельная arq-джоба на каждое сохранение | Эмбеддинг уже персистится в `_process_bookmark_task_impl` (processing.py:217-218), дедуп уже вызывается inline сразу после (line 268). Связи — тот же паттерн, та же сессия, 0-LLM. Бота не блокирует (фон, NFR-2 ✅). |
| AD-3 | **Одно ребро + запрос обеих сторон.** Пишем `(from=новая, to=похожая)` один раз; на чтении `WHERE user_id=X AND (from_id=N OR to_id=N)` | Симметричная запись двух рёбер | Не дублируем, нет рассинхрона. Индексы `(from_id,weight DESC)` + `(to_id,weight DESC)` делают OR-запрос дешёвым. Совпадает с PRD. |
| AD-4 | **Новая функция `find_similar_bookmarks()` top-k**, а не правка `find_near_duplicate` | Параметризовать существующий дедуп | `find_near_duplicate` (dedup_checker.py:143) жёстко зашит под дубли: LIMIT 3, порог 0.85, два прохода, один dict. Переиспользуем SQL-сниппет `1-(embedding <=> CAST(:q AS vector))`, логику — новую (LIMIT :k, threshold 0.75, list). Новый сервис `services/connections.py`. |
| AD-5 | **Семантический поиск = поле `mode` в существующем POST `/api/v1/search/`** | Новый `GET /search?mode=semantic` | `⚠ уточнение к PRD`: текущий поиск — POST с телом `SearchRequest` (api/search.py:40), гибрид с динамическими весами. `mode='semantic'` → веса (1.0, 0.0). Минимальная правка, не ломаем API. |
| AD-6 | **Кнопка «🔗 Похожие (N)» на детальной карточке** (`cb_view`), не в списке `/list` | Счётчик у каждого элемента списка | `⚠ уточнение к PRD`: в списке счётчик = N запросов на рендер (gotcha разведки). На детали (bookmark_view.py:29) закладка уже фетчится — один вызов `get_related`. FR-10 «под заметкой» = детальная карточка. |
| **AD-7** | **Эмбеддинг = реальный текст заметки (сырой текст / добытая статья) + ИИ-поля сверху**, обрезка 8000 символов. Чанкинг — НЕ в MVP | Только ИИ-выжимка (как сейчас, `_build_embedding_text`) / чанкинг сырого текста / два эмбеддинга | **Решение ревью 2026-06-13.** Слабый GigaChat искажает выжимку → связи становятся заложником ИИ. Реальный текст держит смысл даже при плохой выжимке. Один общий эмбеддинг (дёшево на масштабе). Чанкинг с усреднением решал бы пока несуществующую проблему — выносим. **Блок-радиус:** эмбеддинг общий с поиском/дедупом → re-validate пороги (задача 10). |
| **AD-8** | **Граф on-demand: локальный — на лету, полный — по кнопке с кэшем раскладки.** Локальный (эго) граф `react-force-graph-2d` на клиенте; полный — ForceAtlas2/Barnes-Hut → координаты в кэш → WebGL-рендер (Cosmograph/Sigma); баннер устаревания | Рендерить весь граф на каждый вход / только эго-граф без полного | **Решение ревью 2026-06-13.** Раскладка O(N·log N) тяжёлая — пересчёт на каждый вход не вывезет на многих юзерах. Кэш координат + явная кнопка = сервер считает редко. Эго-граф мал → на лету без кэша. Кандидат на монетизацию (платная пересборка). |
| AD-9 | **Порог 0.75 — стартовый, калибруется на бэкфилле.** Mutual-kNN — опционально, флагом | Зафиксировать 0.75 / mutual-kNN с старта | Порог `find_near_duplicate`=0.85 (дубли) ≠ порог связей. Распределение косинусов строим на реальном корпусе при бэкфилле, фиксируем по нему. |

Кандидаты на ADR при реализации: `docs/decisions/0008-bookmark-links-schema.md` (AD-1, AD-3), `0009-connections-no-graphdb.md` (вывод ресёрча), `0010-embedding-source.md` (AD-7).

---

## Technical Approach

### Backend (FastAPI + arq + PostgreSQL)

**Новое:**
- `backend/migrations/versions/<id>_add_bookmark_links.py` — таблица `bookmark_links` + enum `link_kind` (через `postgresql.ENUM(..., create_type=False)` + `.create(bind, checkfirst=True)` — паттерн `a7b8c9d0e1f2_add_scheduled_messages.py:33-44`), индексы. `down_revision='f6a7b8c9d0e1'` (текущий head). + (для кэша графа) таблица `graph_layouts`.
- `backend/app/models.py` — модель `BookmarkLink` (UUID PK `func.gen_random_uuid()`, FK user/from/to CASCADE, `kind` PG_ENUM `create_type=False`, `weight` Float, UNIQUE(from_id,to_id,kind), CHECK(from_id≠to_id)) + `GraphLayout`.
- `backend/app/services/connections.py` — ядро:
  - `find_similar_bookmarks(session, bookmark_id, user_id, embedding, k, threshold) -> list[dict]` — top-k kNN (`ORDER BY embedding <=> CAST(:q AS vector)` для HNSW, фильтр `similarity >= threshold`, скоуп `user_id`, `id != current`, `is_archived=false`, `embedding IS NOT NULL`).
  - `build_links_for_bookmark(session, bookmark_id, user_id, embedding) -> int` — пишет рёбра `INSERT ... ON CONFLICT (from_id,to_id,kind) DO NOTHING`.
  - `get_related(session, bookmark_id, user_id, limit, include_all) -> list[...]` — `WHERE user_id AND (from_id=N OR to_id=N)`, `CASE` для «другой» стороны, `ORDER BY weight DESC`, JOIN bookmarks для карточек.
  - `ego_graph(session, user_id, center, depth, node_cap) -> {nodes, edges}` — локальный граф на лету (BFS 1–2 шага по рёбрам, лимит узлов).
  - `build_full_layout(session, user_id) -> GraphLayout` — раскладка ForceAtlas2 → координаты узлов → кэш `graph_layouts`.
  - `get_cached_graph(session, user_id) -> {nodes_with_xy, edges, stale, built_at, node_count}` — отдать кэш + флаг устаревания.
- `backend/app/api/connections.py` (новый router, prefix `/api/v1`):
  - `GET /api/v1/bookmarks/{id}/related?limit=5&all=false` — IDOR через `WHERE user_id==current_user.id`.
  - `GET /api/v1/graph/local?center={id}&depth=2` — эго-граф на лету (node_cap).
  - `POST /api/v1/graph/build` — посчитать раскладку полного графа и закэшировать координаты.
  - `GET /api/v1/graph` — отдать кэш + `stale`/`built_at`/`node_count`.
- `backend/app/schemas.py` — `RelatedResponse`, `GraphResponse` (nodes/edges/stale), поле `mode: Literal['hybrid','semantic']='hybrid'` в `SearchRequest` (schemas.py:173).

**Изменения существующих:**
- `backend/app/services/bookmark_processor.py:23` — **`_build_embedding_text`: основа = реальный текст** (`raw_text` / `full_text` добытой статьи) + ИИ-поля (takeaway/summary/key_ideas/tags) сверху, обрезка 8000 (AD-7). Обновить тесты.
- `backend/app/worker/processing.py` — в `_process_bookmark_task_impl` после персиста эмбеддинга (≈line 218) вызвать `build_links_for_bookmark(...)` в try/except (best-effort, AD-2).
- `backend/app/worker/scheduled.py` — `backfill_bookmark_links(ctx)` по паттерну `retry_failed_task` (scheduled.py:280): SELECT закладок батчами → **переэмбеддинг новым текстом** (AD-7) → `build_links_for_bookmark` → commit. Идемпотентно (UNIQUE + ON CONFLICT). Регистрация в `WorkerSettings` (worker/__init__.py:103).
- `backend/app/services/search.py` — `SearchService.search(...)` принимает `mode`; при `'semantic'` фиксирует `semantic_weight=1.0, text_weight=0.0` (вместо динамики search.py:33-37).
- `backend/app/api/search.py` — прокинуть `data.mode` в сервис.

**Миграция:**
```sql
CREATE TYPE link_kind AS ENUM ('similar', 'manual', 'derived_from_space');  -- только 'similar' в MVP

CREATE TABLE bookmark_links (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id)     ON DELETE CASCADE,   -- AD-1
    from_id    UUID NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
    to_id      UUID NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
    kind       link_kind NOT NULL,
    weight     DOUBLE PRECISION NOT NULL,             -- cosine для similar
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (from_id, to_id, kind),
    CHECK  (from_id <> to_id)
);
CREATE INDEX idx_links_user        ON bookmark_links(user_id);
CREATE INDEX idx_links_from_weight ON bookmark_links(from_id, weight DESC);
CREATE INDEX idx_links_to_weight   ON bookmark_links(to_id, weight DESC);

-- кэш раскладки полного графа (on-demand, AD-8); table vs Redis — open question
CREATE TABLE graph_layouts (
    user_id    UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    nodes      JSONB NOT NULL,            -- [{id, x, y, ...}]
    node_count INTEGER NOT NULL,
    built_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```
`gen_random_uuid()` доступен нативно (pg ≥13, без pgcrypto — как у всех PK проекта).

### Bot (aiogram 3)

- `bot/api_client.py` — метод `get_related(self, token, bookmark_id, limit=5) -> dict` (паттерн `get_bookmark`, api_client.py:279).
- `bot/handlers/bookmark_view.py` — в `cb_view` (line 29) после фетча закладки вызвать `api.get_related`; если `count>0` — строка кнопки `InlineKeyboardButton(text=f"🔗 Похожие ({n})", callback_data=f"rel:{bid}")`.
- Новый callback `@router.callback_query(F.data.startswith("rel:"))` — список связанных с tap-to-open (`view:{other_id}`), валидация UUID (паттерн reminders/callbacks.py:26).

### Mini App (отдельный репо `bookmark-brain-miniapp`, state-driven, БЕЗ react-router — gotcha репо)

- `package.json` — добавить graph-либы: `react-force-graph-2d` (локальный, canvas, лёгкий для мобильного TG WebView); для полного на больших корпусах — `@cosmograph/react` (WebGL). Сейчас graph-либы нет.
- `src/lib/api.ts` — `getRelated(id, limit)`, `getGraphLocal(center, depth)`, `buildGraph()`, `getGraph()`; в `search(query, limit, mode?)` прокинуть `mode`. Типы `RelatedItem`, `GraphData` (зеркалят бэкенд — в том же PR).
- `src/lib/adapters.ts` — `graphDataOf()` (ответ API → nodes/edges) как единственная точка трансформации.
- `src/screens/DetailScreen.tsx` — секция «Связано» (топ-5 + «Посмотреть все») после brain-блока, перед кнопкой источника (≈line 289).
- `src/components/ds/Nav.tsx` (`NavTab`) + `src/App.tsx` — таб `'граф'`, ветка state-machine → `<GraphScreen/>`.
- `GraphScreen` — **локальный граф** (эго вокруг заметки) рисуется сразу `react-force-graph-2d`; **полный граф** — по кнопке «Построить граф» (`buildGraph()` → `getGraph()`, рендер кэшированных координат WebGL); баннер «граф устарел — обновить?» при `stale`.

### Infrastructure
- Docker/compose не меняем — postgres (pgvector) + redis + arq уже есть.
- Backend: для серверной раскладки полного графа (если не web-worker фронта) — опц. `python-igraph`/`networkx`. Решаем на задаче 7.
- Frontend: graph-либы (выше).

---

## Implementation Strategy

5 фаз. Бэкенд — TDD (RED тесты → GREEN). Фронт зависит от готовых API-контрактов.

### Phase A — Foundation (схема + эмбеддинг + ядро)
Параллельно:
- **A1.** Миграция `bookmark_links` (+ `graph_layouts`) + enum + индексы + модели.
- **A2.** Эмбеддинг = реальный текст + ИИ-поля (`_build_embedding_text`, AD-7) + обновить тесты.
- **A3.** `services/connections.py`: `find_similar_bookmarks` + `build_links_for_bookmark` + unit-тесты (**тест на 0 вызовов LLM**). Зависит от A1, A2.

### Phase B — Связи на save + бэкфилл
- **B1.** Связывание: inline в `_process_bookmark_task_impl` (best-effort) + cron `backfill_bookmark_links` (переэмбеддинг новым текстом + связи, идемпотентно). Зависит A3.

### Phase C — API (параллельно)
- **C1.** `GET /bookmarks/{id}/related` + schema + IDOR-тест.
- **C2.** `mode='semantic'` в `SearchRequest` + `SearchService` + тест.
- **C3.** Graph API: `/graph/local` (эго на лету) + `/graph/build` (раскладка+кэш) + `/graph` (кэш+stale) + `graph_layouts`.

### Phase D — UX (параллельно)
- **D1.** Bot: `get_related` + кнопка «🔗 Похожие» + callback `rel:` + тест. Зависит C1.
- **D2.** Mini App: api + секция «Связано» + таб «Граф» (локальный + полный по кнопке + баннер). Зависит C1+C2+C3 + **готовности Mini App**.

### Phase E — Калибровка + Polish
- **E1.** Калибровка порога на бэкфилле (распределение косинусов) + **re-validate дедуп (0.85) и поиск** после смены эмбеддинга (AD-7).
- **E2.** БТ `docs/requirements/бт-07-связи.md` + ADR 0008/0009/0010 + обновить SPEC/ARCHITECTURE.
- **E3.** code-reviewer + security-reviewer (IDOR/утечки между юзерами — NFR-4) + ручной E2E.

---

## Task Breakdown Preview

10 задач (под лимит CCPM ≤10). Каждая = один атомарный PR.

| # | Task | Phase | Parallel | Depends | Est. |
|---|------|-------|----------|---------|------|
| 1 | Миграция `bookmark_links` + `graph_layouts` + enum + модели | A | with 2 | — | 0.5d |
| 2 | Эмбеддинг = реальный текст + ИИ-поля (`_build_embedding_text`) + tests | A | with 1 | — | 0.5d |
| 3 | `services/connections.py`: `find_similar_bookmarks` + `build_links_for_bookmark` + tests (0-LLM) | A | — | 1, 2 | 1d |
| 4 | Связывание на save (inline best-effort) + бэкфилл cron (переэмбеддинг + связи, идемпотентно) | B | — | 3 | 1d |
| 5 | API `GET /bookmarks/{id}/related` + schema + IDOR test | C | with 6, 7 | 3 | 0.5d |
| 6 | API `mode='semantic'` в search + `SearchService` + test | C | with 5, 7 | — | 0.5d |
| 7 | Graph API: `/graph/local` + `/graph/build` (кэш раскладки) + `/graph` + `GraphResponse` + test | C | with 5, 6 | 1 | 1.5d |
| 8 | Bot: `get_related` + кнопка «🔗 Похожие (N)» + callback `rel:` + test | D | with 9 | 5 | 0.5d |
| 9 | Mini App: «Связано» + таб «Граф» (локальный + полный по кнопке + баннер) + `mode` | D | with 8 | 5, 6, 7 | 2d |
| 10 | Калибровка порога + **re-validate дедуп/поиск** + БТ/ADR + review + E2E | E | — | 2, 4, 9 | 1.5d |

**Итого:** ~9 dev-days (бэкенд-ядро 1–8 без фронта ~7). Задача 9 — отдельный репо, идёт своим темпом после готовности контрактов C.

---

## Dependencies

### Есть (переиспользуем)
- ✅ pgvector + HNSW-индекс `idx_bookmarks_embedding` (m=16, ef_construction=64, cosine_ops) — models.py:92, migration 001.
- ✅ Pipeline эмбеддингов Voyage voyage-3 (1024) — `embeddings.py`, персист в `Bookmark.embedding` (models.py:154).
- ✅ SQL-паттерн kNN `1-(embedding <=> CAST(:q AS vector))` — `dedup_checker.py:173`, `search.py:80`.
- ✅ Worker arq: паттерн cron-бэкфилла (`retry_failed_task` scheduled.py:280), inline-вызов после эмбеддинга (dedup processing.py:268).
- ✅ Гибридный поиск + IDOR-паттерн (`get_current_user`, `WHERE user_id==current_user.id`) — auth.py:87, search.py.
- ✅ Bot card/callback инфра — `bookmark_view.py`, `api_client.py`. ENUM-миграция — `a7b8c9d0e1f2`.

### Новое
- 📦 Таблицы `bookmark_links` + `graph_layouts` (+ миграция, enum).
- 📦 `services/connections.py`, эндпоинты related/graph(local/build/get), поле `mode`.
- 📦 Смена `_build_embedding_text` (общий эмбеддинг).
- 📦 Bot: `get_related` + кнопка. Mini App: «Связано», таб «Граф», graph-либы.

### Блокеры
- ⚠️ **Mini App MVP** (отдельный репо) должен быть готов принять таб «Граф» и секцию «Связано» — задача 9 ждёт контрактов C. Координация между репо.
- ⚠️ **Смена эмбеддинга (задача 2) — общий с поиском/дедупом** → перепроверка в задаче 10 обязательна.

---

## Success Criteria (Technical)
- [ ] Миграция применяется/откатывается чисто; рёбра не дублируются (UNIQUE + ON CONFLICT); `ON DELETE CASCADE` чистит с обеих сторон.
- [ ] `find_similar_bookmarks` возвращает top-k ≥ порога, скоуп по `user_id`, исключает self/archived/null-embedding; покрыто тестами.
- [ ] **Тест: сборка связей и семантический поиск делают 0 вызовов LLM** (NFR-1, мок-счётчик).
- [ ] `GET /related` и graph-эндпоинты — IDOR-защита проверена тестом (чужой `id` → пусто/404, NFR-4).
- [ ] Бэкфилл идемпотентен: двойной прогон не плодит рёбра.
- [ ] После смены эмбеддинга (AD-7) дедуп (0.85) и гибридный поиск не деградировали (прогон на выборке).
- [ ] `mode='semantic'` находит релевантное, что FTS по словам пропускает (golden set, ≥70% — SC-2).
- [ ] Локальный граф рендерится мгновенно; полный строится по кнопке и кэшируется (SC-4).
- [ ] code-reviewer + security-reviewer без CRITICAL/HIGH; coverage новых файлов ≥80%.

### Success Criteria (Product) — из PRD
- [ ] ≥80% заметок (у юзера с >20) получают ≥1 осмысленную связь после калибровки (SC-1).
- [ ] Бэкфилл проходит на проде без ручного вмешательства (SC-5).

---

## Estimated Effort
- **Backend (1–8 кроме 9):** ~6–7 dev-days.
- **Mini App (9):** ~2 dev-days (отдельный репо, параллельно).
- **Калибровка + polish (10):** ~1.5 day.
- **Total:** **~7–9 dev-days** (бэкенд критический путь ~7).

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Смена эмбеддинга (AD-7) ухудшила дедуп/поиск | M | Re-validate на выборке (задача 10); если поехало — правим пороги, в крайнем случае откат `_build_embedding_text` |
| Порог 0.75 даёт шум (всё связано) или пусто | M | Калибровка на бэкфилле (E1), опц. mutual-kNN; порог в конфиг, не хардкод |
| HNSW `ef_search` по умолчанию → плохой recall/latency | M | `SET hnsw.ef_search` под нагрузку (gotcha разведки); бенч на бэкфилле |
| Бэкфилл переэмбеддит весь корпус — нагрузка/стоимость Voyage | M | Батчами + отдельная сессия на батч (паттерн `retry_partial_embeddings`), one-time, 0 LLM-токенов |
| WebGL-граф тормозит в Telegram WebView на мобиле | M | Локальный граф мал (эго); полный — кэш координат + node_cap/кластеризация; Cosmograph (GPU) для больших |
| Утечка связей между юзерами (NFR-4) | L→высокая цена | `user_id` скоуп во всех запросах + security-review + IDOR-тесты |
| Рассинхрон типов фронт↔бэк | M | Типы в `lib/api.ts` правим в том же PR что и схемы бэка (паттерн репо) |
| Связи устаревают при редактировании заметки | L | MVP не пересчитывает (Out of Scope); ребро по старому эмбеддингу, CASCADE при удалении |

---

## Open Questions

- [ ] **Порог + mutual-kNN** — финал по распределению косинусов на бэкфилле (E1).
- [ ] **k_store** — 20 vs 50 рёбер на заметку? (объём БД vs «Посмотреть все»). Решаем при задаче 3 / E1.
- [ ] **Кэш раскладки** — таблица `graph_layouts` vs Redis-блоб? (задача 7)
- [ ] **Раскладка полного графа** — считать на бэке (`igraph`) или в web-worker фронта? (задача 7/9)
- [ ] **Порог «граф устарел»** — сколько новых заметок (или %) триггерит баннер? (задача 7/9)
- [ ] **Related в боте** — список текстом или сразу инлайн-кнопки tap-to-open? (задача 8)

---

*Готов к декомпозиции в беды. Команда: «поехали» / «decompose the connections-mvp epic» → создаю child-беды под `bookmark-brain-7j9` и стартую задачу 1.*
