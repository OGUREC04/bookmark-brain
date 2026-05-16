# PRD: Smart Spaces MVP

**Статус:** v1 — после брейншторма + ресёрча 2 агентов. ⏸ **ОТЛОЖЕН** до завершения bugfix-фазы и Mini App.
**Дата:** 2026-05-14
**Фаза:** Phase 5 (5A → 5B → 5C)
**Оценка:** 4-7 dev-days
**Зависит от:**
- Phase 2.5 закрыта (`bot/handlers/` без активных правок другого чата) ✅
- **NEW:** Bugfix базовых функций завершён (другой чат)
- **NEW:** Mini App MVP готов и протестирован
**Источник терминологии:** «пространство» / `space` — выбор юзера. В коде: `smart_space` / `space`. В UI: «пространство».

---

## ⏸ Отложено: причины (2026-05-14)

После завершения брейншторма и написания v1 PRD принято решение **отложить Phase 5** до:

1. **Стабилизации базовых функций.** В юзер-тесте всплыло много багов в core flow (классификация, dedup, task lists, reminders). Smart Spaces поверх неустойчивой базы = усиление проблем
2. **Готовности Mini App.** В PRD заложено что **главный feedback-канал — Mini App** (US-5: удаление неподходящих закладок → негативный сигнал). Без Mini App fallback на бот-кнопки, что нарушает решение брейншторма 4.5
3. **Параллельная работа.** Другой чат чинит баги, этот чат — занимается Mini App. После того как обе ветки сходятся → возвращаемся к Smart Spaces

**Что сохранено для возврата к фазе:**
- Этот PRD целиком — все 4 блока брейншторма, 2 ресёрч-отчёта от агентов, 7 User Stories, 15 edge cases, T1-T20 декомпозиция, 7 open questions
- ADR 0006 (топики в DM не работают — почему мы пошли по этому пути)
- Связанные beads: `bookmark-brain-???` (proactive insights P3 backlog), `bookmark-brain-4nc` (date_time entity), `bookmark-brain-5lt` (typing indicator), `bookmark-brain-6ww` (streaming P3)

**Что НЕ нужно делать при возврате:**
- Не переделывать брейншторм с нуля — все решения зафиксированы в этом PRD
- Не запускать ресёрч-агентов заново — выводы в разделе Architecture
- Не переоценивать модели membership / cascade — выбор обоснован

**Что МОЖНО пересмотреть:**
- Сценарии и приоритеты после Mini App user-test (что юзеры реально просили)
- DeepSeek vs GigaChat (если успели мигрировать в Phase 4.5)
- Список шаблонов >5 (юзер хотел подумать)
- Cross-space surfacing UX — может быть проще на основе реального Mini App

---

---

## Проблема

У юзера копится 50-300+ закладок в плоском списке `/list`. Через 2 недели:
- Не помнит что сохранил
- Не находит когда нужно
- Перестаёт сохранять — «зачем, всё равно потеряется»

Теги частично решают, но:
- Тегов десятки, разрозненные («#идея», «#идеи», «#startup» — юзер не помнит какой использовал)
- Тег = keyword, не пространство. Не даёт «зайти в свои Идеи»
- Не проактивен — статья про AI лежит с тегом #ai, но юзер не вспомнит её когда будет думать про новый стартап

Нужна **тематическая структура поверх закладок** — пространства которые сами собираются и связываются.

---

## Решение

**Smart Spaces** = тематические пространства с auto-routing, типизированным членством и связями.

### Жизненные примеры

**Пример 1: Идеи стартапа**
- Юзер сохраняет: «идея — приложение для трекинга воды» → попадает в Ideas (primary)
- Через неделю сохраняет статью «AI-агенты в продуктовых приложениях» → primary = Read Later, но cascade видит cosine 0.74 с Ideas → добавляет с kind=auto
- Юзер открывает Ideas → видит свою идею + «бот добавил материал из Read Later: AI-агенты в приложениях»
- Если статья не подходит — юзер в Mini App убирает её → негативный сигнал, anchor пересчитывается

**Пример 2: Goals**
- Юзер: «прочитать 12 книг в этом году» → Goals (primary)
- Юзер: «купить новый Кindle» → Read Later (primary), Goals видит cosine 0.71 → auto-добавляет как материал
- В Goals видна цель + сопутствующий материал

**Пример 3: новое пространство по запросу AI**
- У юзера 8 закладок про криптовалюты разбросаны по Read Later и Ideas
- Бот: «вижу 8 материалов про крипту, создать пространство Криптовалюты?»
- Юзер: «да» → создаётся, существующие 8 переезжают как `auto`

---

## User Stories

### US-1: Новый юзер видит структуру с первого взгляда
**Как** новый пользователь
**Я хочу** видеть готовую структуру для своих заметок
**Чтобы** не пугаться пустого экрана

**Acceptance:**
- При первом `/start` создаются 2 пространства: **Goals** + **Ideas** (системные шаблоны)
- Юзер в `/spaces` видит эти 2 + кнопку «➕ Добавить шаблон» (Read Later / Do Someday / Insights)
- Пустое пространство показывает: иконка + название + «пока пусто, материалы появятся когда ты начнёшь сохранять»

### US-2: Закладка автоматически попадает в пространство
**Как** активный пользователь
**Я хочу** чтобы бот сам раскладывал закладки по моим пространствам
**Чтобы** не тратить время на ручную сортировку

**Acceptance:**
- Каждая новая закладка проходит cascade detection (см. ниже)
- Результат: 1 primary space + 0..N auto memberships
- Если ни одно пространство не подошло (max cosine < 0.65) — закладка остаётся без пространства (живёт только в `/list`)
- В боте после save: тихая реакция 👍 (как сейчас), без новых сообщений с подтверждением

### US-3: Юзер открывает пространство и видит контент
**Как** пользователь
**Я хочу** открыть пространство и увидеть всё что в нём

**Acceptance:** при `/spaces Ideas` или открытии в Mini App:
- Шапка: иконка + название + краткое описание (prompt) + кнопка «настроить»
- Summary (если есть): «12 материалов, 3 за неделю»
- Основной список: закладки kind ∈ {primary, manual, auto}, отсортированы по дате
- В Mini App дополнительно: секция «Связи» — пересекающиеся материалы из других пространств (cross-space surfacing)
- Action-кнопки: «🗑 Удалить пространство», «✏ Переименовать», «🔧 Изменить инструкцию», «📊 Сводка», «📅 За неделю»

### US-4: Юзер создаёт кастомное пространство
**Как** пользователь
**Я хочу** создать своё пространство («Инвестиции» / «Книги» / etc.)
**Чтобы** организовать закладки по своим темам

**Acceptance:**
- `/spaces setup` запускает мастер:
  1. «Как назвать?» → юзер: «Инвестиции»
  2. «Что собирать?» → юзер: «всё про инвестиции и недвижимость, но не криптовалюту»
  3. «Выбери стиль» → 5 визуальных шаблонов (цвет + иконка)
- Бот: «Создаю → готово. Существующие закладки сейчас переберу.»
- Worker bulk re-cascade на закладках без primary (или с низким confidence)

### US-5: Юзер убирает неподходящую закладку (feedback)
**Как** пользователь Mini App
**Я хочу** удалить закладку которая не подходит к пространству
**Чтобы** бот учился на моих исправлениях

**Acceptance:**
- В Mini App у каждой закладки в пространстве — кнопка «❌» (удалить из этого пространства)
- Tap → закладка получает `kind=rejected` в этом пространстве (не удаляется из БД, остаётся в primary/других)
- Текст закладки добавляется в negative anchors пространства
- Цент­роид перевычисляется через worker (batch, не сразу)

### US-6: Юзер видит summary пространства
**Как** пользователь
**Я хочу** быстро понять что у меня в пространстве

**Acceptance:**
- В `/spaces Ideas` → в шапке: «12 идей, последняя 3 дня назад, чаще всего теги: #ai #саморазвитие»
- Кнопка «🧠 Суммировать» → запускает LLM (DeepSeek/GigaChat) → возвращает 3-5 строк «у тебя есть идеи про X, Y, Z»

### US-7: AI предлагает новое пространство
**Как** пользователь
**Я хочу** чтобы бот замечал паттерны в моих закладках
**Чтобы** не настраивать пространства вручную

**Acceptance:**
- Worker раз в N дней анализирует закладки без primary или с низким confidence
- Если находит кластер ≥6 закладок про одну тему — посылает юзеру: «у тебя 6 материалов про криптовалюты, создать пространство?»
- Юзер: «да» → создаётся через wizard с предзаполненными данными (тема, иконка предположена)
- Юзер: «нет» → suggestion записывается как dismissed, не повторяется месяц

---

## Functional Requirements

### FR-1: Cascade detection (D-cascade)

Алгоритм определения членства закладки в пространствах при save:

```
1. embedding(bookmark) уже есть из текущего pipeline (Voyage AI voyage-3)

2. Для каждого активного space у юзера:
   a. Параллельно cosine(bookmark.embedding, positive_anchor[i]) для всех positive_anchors
   b. max_pos = max of cosines
   c. Параллельно cosine(bookmark.embedding, negative_anchor[i]) для negative_anchors
   d. max_neg = max of cosines

3. Decision:
   if max_neg ≥ max_pos:           skip (negative anchor сильнее)
   elif max_pos ≥ 0.78:            primary candidate (попадёт если top score)
   elif max_pos ≥ 0.65:            escalate to LLM (1 batch call со всеми пограничными)
   else:                           skip

4. После прохода всех spaces:
   - primary = argmax(scores) среди >= 0.78
   - auto memberships = все остальные где >= 0.78 (multi-membership)
   - LLM fallback подтверждает/отклоняет пограничные

5. Bookmark получает 0..1 primary + 0..N auto в bookmark_space_membership
```

### FR-2: Space setup с positive/negative anchors

При создании/изменении пространства:

```
input:
  name, prompt, visual_template_id

processing:
  1. LLM (DeepSeek/GigaChat fallback) получает prompt + few-shot examples
  2. Генерирует:
     - positive_anchors: 5-8 парафраз/примеров что подходит
     - negative_anchors: 2-4 примера что НЕ подходит (особенно если в prompt есть negation типа "но не X")
  3. Для каждого anchor: voyage-3 embedding
  4. Сохраняем в smart_spaces.positive_anchors[] + .negative_anchors[]

triggers re-setup:
  - изменение prompt
  - юзер пометил ≥5 закладок как rejected → пересчёт negative_anchors
  - юзер вручную добавил ≥5 закладок (manual) → пересчёт positive_anchors
```

### FR-3: Membership types

```sql
kind ENUM:
  'primary'   -- основное пространство закладки (≤1 per bookmark)
  'auto'      -- cascade добавил как secondary
  'manual'    -- юзер вручную в Mini App
  'rejected'  -- юзер убрал; хранится для negative signal, не показывается
```

Правила:
- На bookmark может быть 0 или 1 строка с kind='primary'
- На bookmark может быть N строк с kind ∈ {auto, manual, rejected} в разных spaces
- В одном space одна закладка может иметь только один kind (constraint: UNIQUE bookmark_id, space_id)
- При rejected — старая запись (например auto) UPDATE kind=rejected, не INSERT

### FR-4: Bot commands

```
/spaces                  — список пространств (системные + кастомные)
/spaces <name>           — содержимое пространства (закладки + ссылка в Mini App)
/spaces setup            — wizard создания нового
/spaces delete <name>    — удалить (требует подтверждения)
/spaces rename <name>    — переименовать
/spaces edit <name>      — изменить prompt (re-trigger setup)
/spaces summary <name>   — LLM суммаризация содержимого
```

### FR-5: Cross-space surfacing (#4 из брейншторма)

При открытии пространства X в Mini App или `/spaces X` в боте:
- Запрос: top-N closest bookmarks к anchors X, у которых primary != X
- Показываются в секции «Связи»
- В боте: краткий формат «🔗 3 связанных в Read Later, Goals» с tap-to-view
- В Mini App: полная секция с превью

### FR-6: Weekly stats digest

Раз в неделю (settings.digest_day = по умолчанию Mon) бот шлёт:
```
📊 Эта неделя в твоих пространствах:
  Goals: +2 (всего 5)
  Ideas: +4 (всего 12)
  Read Later: +7 (всего 23)

🔥 Самое популярное: «AI-агенты в продуктах» — открывал 3 раза
```

### FR-7: Mini App requirements

- Список всех пространств с counter
- Открытие пространства: members + связи + summary
- Удаление закладки из пространства (свайп → kind=rejected)
- Перенос между пространствами (drag-and-drop, опционально)
- Поиск внутри пространства

---

## Non-Functional Requirements

| Параметр | Целевое значение |
|---|---|
| Cascade detection latency (save) | < 200 ms (P95) для 10 spaces |
| LLM fallback частота | ≤ 15% всех saves |
| Стоимость LLM на юзера/месяц | < $0.05 (DeepSeek pricing) |
| Точность auto-routing | ≥ 85% по результатам user testing |
| Объём негативного сигнала для пересчёта | ≥ 5 rejected → re-train |
| Mini App latency открытия пространства | < 500 ms (P95) для 100 members |

---

## Architecture

### Sub-phase 5A: Connections layer (1-2 дня)

**Цель:** пре-реквизит — user-facing связи между закладками.

**Что делаем:**
- `bookmark_links` таблица: `(from_id, to_id, kind, weight, created_at)`
  - `kind`: 'similar' | 'manual' | 'derived_from_space'
- API: `GET /api/v1/bookmarks/{id}/related?limit=5`
- На save: автоматически создаём top-3 similar links по cosine
- Bot UI: кнопка `🔗 Похожие` под каждой закладкой (когда есть)
- Mini App: секция «Связано» при открытии закладки

**Не делаем в 5A:** ручное создание связей, граф-визуализация, weight decay.

### Sub-phase 5B: Smart Spaces core (2-3 дня)

**Цель:** базовая структура + cascade detection + bot UI.

**Что делаем:**
- Schema: `smart_spaces`, `bookmark_space_membership`
- Setup pipeline: LLM генерирует anchors, embedding, save
- Cascade detection в worker после classification + embedding
- 5 шаблонов: Goals, Ideas, Read Later, Do Someday, Insights (визуал + поведение)
- Default 2 для нового юзера: Goals + Ideas
- Bot: все команды `/spaces *`
- Mini App API: list, get, members, summary
- Migration: bulk re-cascade существующих закладок (если есть)

### Sub-phase 5C: Proactivity (1 день)

**Цель:** «бот думает за юзера» — связи и предложения.

**Что делаем:**
- Auto memberships видны в Mini App с маркером «🤖 бот добавил»
- Cross-space surfacing (FR-5) — в UI пространства
- Weekly stats digest (FR-6) — простая агрегация
- AI suggests new space (US-7) — worker cron, проверка кластеров

**Не делаем в 5C:** активные DM-уведомления, confirm/reject UI в боте, action templates типа «сделай ресерч» (P3 bead).

---

## Schema

### `smart_spaces`

```sql
CREATE TABLE smart_spaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    name VARCHAR(64) NOT NULL,
    prompt TEXT NOT NULL,                       -- инструкция AI «что собирать»
    visual_template VARCHAR(32) NOT NULL,       -- 'goals'|'ideas'|'read_later'|'do_someday'|'insights'|'custom'
    color VARCHAR(7),                            -- HEX, для custom
    icon VARCHAR(8),                             -- emoji

    positive_anchors JSONB DEFAULT '[]',         -- [{text, embedding[1024]}, ...]
    negative_anchors JSONB DEFAULT '[]',
    threshold_primary FLOAT DEFAULT 0.78,        -- per-space tunable
    threshold_escalate FLOAT DEFAULT 0.65,

    is_system BOOLEAN DEFAULT FALSE,             -- системный шаблон vs кастомный
    system_template_id VARCHAR(32),              -- 'goals'|'ideas'|... NULL для кастомных

    last_anchors_rebuild TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE (user_id, name)
);

CREATE INDEX idx_smart_spaces_user ON smart_spaces(user_id);
```

### `bookmark_space_membership`

```sql
CREATE TYPE space_membership_kind AS ENUM (
    'primary', 'auto', 'manual', 'rejected'
);

CREATE TABLE bookmark_space_membership (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bookmark_id UUID NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
    space_id UUID NOT NULL REFERENCES smart_spaces(id) ON DELETE CASCADE,

    kind space_membership_kind NOT NULL,
    confidence FLOAT,                            -- cosine score на момент добавления
    source VARCHAR(16),                          -- 'cascade'|'user'|'llm_fallback'|'migration'

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE (bookmark_id, space_id)
);

CREATE INDEX idx_membership_space_kind ON bookmark_space_membership(space_id, kind)
    WHERE kind != 'rejected';
CREATE UNIQUE INDEX idx_one_primary_per_bookmark
    ON bookmark_space_membership(bookmark_id)
    WHERE kind = 'primary';
CREATE INDEX idx_membership_bookmark ON bookmark_space_membership(bookmark_id);
```

### `bookmark_links` (5A)

```sql
CREATE TYPE link_kind AS ENUM ('similar', 'manual', 'derived_from_space');

CREATE TABLE bookmark_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_id UUID NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
    to_id UUID NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
    kind link_kind NOT NULL,
    weight FLOAT NOT NULL,                       -- cosine для similar, 1.0 для manual
    derived_from_space UUID REFERENCES smart_spaces(id),  -- для kind='derived_from_space'
    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE (from_id, to_id, kind),
    CHECK (from_id != to_id)
);

CREATE INDEX idx_links_from ON bookmark_links(from_id, weight DESC);
```

---

## API Contracts

### Spaces CRUD

```
POST   /api/v1/spaces/
       body: {name, prompt, visual_template, color?, icon?}
       response: SpaceFull (с anchors NOT в response для размера)

GET    /api/v1/spaces/                  → list (без anchors)
GET    /api/v1/spaces/{id}              → SpaceFull
PATCH  /api/v1/spaces/{id}              → update name/prompt/visual (re-run setup на prompt change)
DELETE /api/v1/spaces/{id}              → cascade удалит memberships

GET    /api/v1/spaces/{id}/members?kind=primary,auto,manual&limit=50
       → list of bookmarks with confidence

GET    /api/v1/spaces/{id}/summary      → LLM summary
GET    /api/v1/spaces/{id}/stats        → counts, weekly delta, top tags

POST   /api/v1/spaces/{id}/members      → manual add
       body: {bookmark_id}
DELETE /api/v1/spaces/{id}/members/{bid}
       → kind переходит в 'rejected', записывается в negative signal
```

### Connections (5A)

```
GET    /api/v1/bookmarks/{id}/related?limit=5
       → list of {bookmark_id, kind, weight}
POST   /api/v1/bookmarks/{id}/links     → manual link
       body: {to_id}
```

### Onboarding

```
POST   /api/v1/spaces/setup-defaults    → создаёт Goals + Ideas для нового юзера
                                          (вызывается при первом /start если spaces пусты)
```

---

## Cascade Detection — детально

### Flow в worker.py

```python
async def classify_and_route(bookmark: Bookmark):
    # Существующий шаг
    ai_result = await classify(bookmark.content)
    bookmark.tags = ai_result.tags
    bookmark.embedding = await embed(bookmark.content)

    # NEW: cascade routing
    spaces = await get_user_spaces(bookmark.user_id, only_active=True)
    if not spaces:
        return  # юзер без пространств — exit

    candidates = []
    borderline = []

    for space in spaces:
        max_pos = max_cosine(bookmark.embedding, space.positive_anchors)
        max_neg = max_cosine(bookmark.embedding, space.negative_anchors)

        if max_neg >= max_pos:
            continue  # ближе к negative → skip

        if max_pos >= space.threshold_primary:
            candidates.append((space, max_pos))
        elif max_pos >= space.threshold_escalate:
            borderline.append((space, max_pos))

    # LLM fallback на пограничных (1 batch call)
    if borderline:
        llm_result = await llm_classify_batch(
            text=bookmark.content,
            spaces=[s for s, _ in borderline],
        )
        for space, fits in llm_result.items():
            if fits:
                candidates.append((space, 0.78))  # сброс к threshold

    if not candidates:
        return  # ни одно не подошло

    # Сортируем, лучший = primary
    candidates.sort(key=lambda x: x[1], reverse=True)
    primary_space, primary_score = candidates[0]
    auto_spaces = candidates[1:]

    # Insert memberships
    await insert_membership(bookmark.id, primary_space.id, 'primary', primary_score)
    for space, score in auto_spaces:
        await insert_membership(bookmark.id, space.id, 'auto', score)
```

### Anchor generation (LLM)

```python
PROMPT_ANCHORS = """
Ты помогаешь настроить пространство для заметок.

Название: {name}
Инструкция от пользователя: {prompt}

Сгенерируй:
1. positive_examples: 5-8 коротких фраз (1-2 предложения), которые ДОЛЖНЫ попадать в это пространство
2. negative_examples: 2-4 коротких фразы, которые НЕ должны попадать (особенно если в инструкции есть отрицание типа "не X")

Вернуть JSON:
{
  "positive_examples": [...],
  "negative_examples": [...]
}
"""
```

---

## Edge cases (≥10)

1. **Юзер удалил все пространства** → cascade в worker делает `return` на пустом списке; закладка живёт без membership
2. **Юзер изменил prompt пространства** → trigger setup re-run, старые anchors удаляются, новые генерируются; существующие memberships НЕ пересчитываются (только новые saves)
3. **Юзер пометил 5+ закладок как rejected** → worker cron перегенерирует negative_anchors с учётом rejected texts
4. **LLM fallback недоступен** (DeepSeek/GigaChat 5xx) → пограничные пропускаем (не попадают в auto), primary считается только по >= 0.78
5. **Embedding API недоступен** (Voyage 5xx) → закладка сохраняется без membership, worker retry через cron
6. **Закладка совпадает с anchors двух кастомных пространств с одинаковым score** → primary = первое по `created_at` (стабильный tiebreaker)
7. **Кастомное пространство с пустым prompt** → запрещаем при создании (validation), prompt min length = 10 символов
8. **Юзер создал >50 пространств** → soft limit с предупреждением, hard limit 100 (performance)
9. **Anchors пересчитываются параллельно для двух пространств юзера** → row-level lock на `smart_spaces.id`, второй ждёт
10. **Bookmark без embedding (старая закладка)** → cascade skipped; migration job ставит embeddings в фоне
11. **Юзер удалил пространство в момент классификации** → INSERT membership упадёт по FK; обработать gracefully
12. **Bot/Mini App запросили summary пространства с 0 закладок** → возвращаем "пока пусто, начни добавлять заметки"
13. **Юзер сразу создаёт пространство с противоречивым prompt** ("всё про спорт и крипту") → LLM создаст широкие anchors, точность упадёт; не блокируем, warning в UI
14. **Системное пространство (Goals) удалено юзером** → разрешено, но в `/spaces setup defaults` юзер может восстановить
15. **Параллельные saves на одну и ту же bookmark** → INSERT membership через ON CONFLICT DO UPDATE по UNIQUE(bookmark_id, space_id)

---

## Success Criteria

### MVP (5A + 5B + 5C complete)

- [ ] Юзер создаёт пространство через `/spaces setup` менее чем за 60 секунд
- [ ] При сохранении новой закладки она попадает в правильное primary пространство ≥ 85% случаев (на 50 ручных проверках)
- [ ] LLM fallback вызывается < 20% saves в worker logs
- [ ] Среднее время cascade detection < 200 ms (worker metrics)
- [ ] `/spaces <name>` корректно показывает members без duplicates
- [ ] Mini App отображает пространство с 100 members за < 500 ms

### Live (после user testing)

- [ ] ≥ 50% активных юзеров создали хотя бы одно кастомное пространство
- [ ] < 10% rejected memberships от общего числа auto (бот не агрессивно ошибается)
- [ ] retention day-7 ≥ 50% среди тех у кого создано ≥ 1 пространство

---

## Out of Scope

- **Папки внутри пространства** — отложено (см. брейншторм 3.2)
- **Активные DM-уведомления** про новые suggestions — отложено (брейншторм 4.5)
- **Confirm/reject кнопки в боте** под bot_suggested — отложено, feedback идёт через Mini App
- **Action-шаблоны** типа «сделай ресерч» / «экспортируй» — отложено (bd P3)
- **Cross-space surfacing с runtime cosine query** — в MVP только через precomputed auto memberships (см. брейншторм #4 vs #1)
- **Графика связей / визуализация графа** — Phase 6+
- **Manual создание связей между закладками** — 5A только auto similar links
- **Per-space настройка thresholds юзером** — в MVP только дефолтные 0.78/0.65
- **Шаблоны >5** — фиксируем что юзер хочет, добавляем в backlog для итерации после user testing

---

## Dependencies

### Что должно быть готово

- [x] Embeddings pipeline (Voyage AI voyage-3) — есть
- [x] pgvector + cosine similarity — есть (используется в dedup)
- [x] LLM провайдер (GigaChat) — есть, миграция на DeepSeek опциональна
- [x] Phase 2.5 Reminders MVP merged — есть (PR #10)
- [ ] Mini App базовый список закладок работает — нужно перепроверить состояние

### Новое что добавляем

- `bookmark_links` таблица (5A)
- `smart_spaces` + `bookmark_space_membership` (5B)
- ENUMs: `space_membership_kind`, `link_kind`
- Bot handler `bot/handlers/spaces.py`
- Service `backend/app/services/space_router.py` (cascade)
- Service `backend/app/services/anchor_generator.py` (LLM-based)
- Worker integration в `backend/app/worker.py`
- API endpoints `backend/app/api/v1/spaces.py`, `backend/app/api/v1/links.py`
- Mini App: новый экран спaces, удаление с feedback

---

## Open questions

1. **Lazy re-cascade** — если юзер изменил prompt пространства, пересчитывать ли membership существующих закладок? **Текущее решение:** нет, только новые saves. Старые остаются. Юзер может вручную добавить через Mini App
2. **Performance pgvector** — anchors хранятся как JSONB; для cosine нужно либо доставать в Python либо использовать vector type. **Решение в реализации:** хранить как массив pgvector-полей в отдельной join-таблице `space_anchors(space_id, kind, embedding vector(1024))` — позволит индекс HNSW
3. **Шаблоны >5 в будущем** — добавлять как? Через миграцию visual_template enum или сделать его VARCHAR с допустимыми значениями в коде? **Решение в реализации:** VARCHAR для гибкости
4. **DeepSeek vs GigaChat для anchor generation** — DeepSeek дешевле и стабильнее JSON, но не запущен в проде. **Решение:** Phase 4.5 DeepSeek migration перед 5B (опционально), пока GigaChat
5. **Bulk re-cascade у нового юзера** — у новых пользователей закладок нет (US-1 справедлив на момент Phase 5 release). У будущих active users проблема: если они появятся ДО релиза Phase 5, нужен bulk job. **Решение:** добавить background job в Phase 5B, активируется только когда пользователь делает `/spaces setup defaults`
6. **AI suggests new space (US-7)** — частота cron, минимум закладок в кластере, как кластеризовать? **Решение для MVP:** простая агрегация — раз в неделю, минимум 6 закладок с cosine >= 0.7 друг к другу, нет primary space. Параметры подкручиваем после user testing
7. **Mini App scope** — какие фичи войдут в Phase 5 Mini App vs последующий Mini App polish? **Решение:** в 5C только member-list + удаление с feedback. Остальное (поиск, drag-drop, фильтры) — в Mini App phase после 5C

---

## Decomposition (черновая, утвердим через planner agent)

### 5A — Connections layer (1-2 дня)
- **T1**: Schema migration `bookmark_links` + ENUM `link_kind`
- **T2**: Service `link_builder.py` — top-3 similar по cosine на save (in worker)
- **T3**: API `GET /api/v1/bookmarks/{id}/related`
- **T4**: Bot — кнопка «🔗 Похожие» под закладкой, ответ списком
- **T5**: Tests + code-review

### 5B — Smart Spaces core (2-3 дня)
- **T6**: Schema migrations `smart_spaces`, `bookmark_space_membership`, `space_anchors`, ENUM `space_membership_kind`
- **T7**: Service `anchor_generator.py` — LLM генерация positive/negative anchors
- **T8**: Service `space_router.py` — cascade detection algorithm (FR-1)
- **T9**: API CRUD spaces + members + summary (`api/v1/spaces.py`)
- **T10**: 5 встроенных шаблонов (visual + behavior) + seed defaults (Goals + Ideas)
- **T11**: Bot handler `bot/handlers/spaces.py` со всеми командами (FR-4)
- **T12**: Worker integration — cascade после classify+embed
- **T13**: `POST /api/v1/spaces/setup-defaults` + вызов из onboarding flow
- **T14**: Tests (unit + integration на реальной Postgres)

### 5C — Proactivity (1 день)
- **T15**: Mini App — список пространств + member list + remove с feedback
- **T16**: Cross-space surfacing (FR-5) — в `/spaces <name>` + Mini App
- **T17**: Weekly digest cron + сообщение (FR-6)
- **T18**: AI suggests new space (US-7) — worker cron + bot prompt
- **T19**: Negative-signal pipeline — при rejected ≥5 пересчёт negative_anchors
- **T20**: E2E + code-reviewer + security-reviewer

---

## Глоссарий

- **Пространство (space)** — тематический контейнер для закладок с auto-routing и связями
- **Anchor** — точка в семантическом пространстве: positive (что подходит) или negative (что нет). Embedding + text
- **Cascade detection** — алгоритм определения членства: embedding → cosine → LLM fallback на пограничных
- **Primary space** — главное пространство закладки (≤1 per bookmark)
- **Auto membership** — secondary пространство, добавлено ботом
- **Manual membership** — добавлено юзером в Mini App
- **Rejected** — юзер убрал закладку из пространства; запись хранится как negative signal
- **Cross-space surfacing** — показ материалов из других пространств с высокой relevance к текущему

---

## История ревью

- **2026-05-12/13** — брейншторм 4 блока (концепция / membership / пространство как «space» / финальные решения)
- **2026-05-12** — параллельный ресёрч 2 агентами по membership detection и one-vs-many UX
- **2026-05-14** — v1 PRD написан, ожидает ревью planner + architect
