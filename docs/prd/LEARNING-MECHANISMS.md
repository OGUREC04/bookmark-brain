# PRD: Learning Mechanisms

**Статус:** Draft
**Дата:** 2026-05-02
**Фаза:** Phase 2 (после Silent Mode)
**Оценка:** 5-7 dev-days

---

## Проблема

Система не учится на поведении пользователя:
- ИИ-классификация ошибается, но нет механизма коррекции
- Поиск не учитывает давность — статья годовой давности ранжируется наравне со вчерашней
- Закладки со статусом `partial` (классификация ок, embedding упал) зависают навсегда
- Нет данных о качестве поиска (что ищут, находят ли)

## Решение

Три подсистемы + одна cron-задача:

---

## 1. Classification Feedback (Mini App / приложение)

### Что видит юзер

В карточке закладки (Mini App) — кнопка "Не так" рядом с item_type.

```
📎 "позвонить в банк"
Тип: thought  [Не так]
Категория: финансы
Теги: банк, задачи
```

Юзер нажимает "Не так" → 4 кнопки: action / thought / content / reference.
Выбирает правильный → закладка обновляется, коррекция сохраняется.

### Только item_type

На первом этапе исправляем только item_type (4 класса). Category — свободное поле, сложнее UI, меньше impact. Добавим позже если будет спрос.

### Как коррекции улучшают классификацию

При классификации новой заметки:
1. Берём embedding текста новой заметки
2. Ищем в `classification_corrections` top-3 коррекции по cosine similarity
3. Добавляем их в промпт как few-shot примеры

```
Примеры предпочтений пользователя:
- "купить подарок маме" → action (было: thought)
- "записаться к врачу" → action (было: reference)
- "идея: сделать бота" → thought (было: action)

Классифицируй: "позвонить в банк"
```

ИИ видит паттерн и точнее классифицирует.

### Защита от противоречий

- Если юзер исправил A→B и потом B→A — обе коррекции помечаются `is_valid = false`
- Коррекции старше 6 месяцев не используются
- Minimum similarity threshold: 0.3 (нерелевантные коррекции не инжектятся)

### Данные

**Таблица `classification_corrections`:**

```sql
CREATE TABLE classification_corrections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bookmark_id UUID NOT NULL REFERENCES bookmarks(id) ON DELETE CASCADE,
    original_item_type VARCHAR(20) NOT NULL,
    corrected_item_type VARCHAR(20) NOT NULL,
    text_embedding vector(1024),       -- embedding текста закладки
    example_text TEXT NOT NULL,         -- краткий текст для few-shot (<500 символов)
    is_valid BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_corrections_user ON classification_corrections(user_id);
CREATE INDEX idx_corrections_embedding ON classification_corrections
    USING hnsw (text_embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

### API

```
POST /api/v1/bookmarks/{id}/feedback
Body: { "corrected_item_type": "action" }

Действия:
1. Обновить bookmark.item_type
2. Сохранить коррекцию в classification_corrections
3. Проверить consistency (нет ли обратных коррекций)
```

### Затронутые файлы

| Файл | Изменение |
|------|-----------|
| `backend/app/models.py` | Модель ClassificationCorrection |
| `backend/app/schemas.py` | FeedbackRequest schema |
| `backend/app/api/bookmarks.py` | POST feedback endpoint |
| `backend/app/services/ai_classifier.py` | _build_few_shot_section(), инжекция в промпт |
| `migrations/` | Новая миграция для таблицы |

---

## 2. Usage Decay в поиске

### Формула

Логарифмический decay от `last_accessed` (не `created_at`):

```
decay = 1 / (1 + 0.1 * ln(1 + age_days))
```

| Возраст | Коэффициент | Смысл |
|---------|------------|-------|
| Сегодня | 1.00 | Полный вес |
| 1 неделя | 0.84 | Почти полный |
| 1 месяц | 0.74 | Немного ниже |
| 3 месяца | 0.68 | Заметно ниже |
| 1 год | 0.63 | Всё ещё 63% — не убивает |

### Ключевые принципы

1. **Decay от last_accessed, не created_at** — если юзер открыл заметку вчера, decay считается от вчера. Вечнозелёный контент (рецепты, документация) не тонет, пока юзер к нему возвращается.

2. **Заметки НИКОГДА не убиваются** — даже через 3 года decay = 0.57. Заметка всегда находится в поиске, просто ниже свежих.

3. **is_favorite = буст +0.05** — избранное чуть выше при прочих равных.

### SQL в SearchService

```sql
-- В scored CTE добавить:
1.0 / (1.0 + 0.1 * LN(1.0 + EXTRACT(EPOCH FROM
    (now() - COALESCE(b.last_accessed, b.created_at))) / 86400.0
)) AS recency_score

-- В итоговом score:
(:semantic_weight * semantic_score + :text_weight * text_score) * recency_score
+ CASE WHEN b.is_favorite THEN 0.05 ELSE 0 END
```

### Обновление last_accessed

При любом просмотре закладки (GET bookmark, click в поиске, открытие в Mini App):

```python
await session.execute(text(
    "UPDATE bookmarks SET last_accessed = now() WHERE id = :bid"
), {"bid": str(bookmark_id)})
```

### Затронутые файлы

| Файл | Изменение |
|------|-----------|
| `backend/app/services/search.py` | Добавить recency_score в SQL |
| `backend/app/api/bookmarks.py` | Обновлять last_accessed при GET |

---

## 3. Embedding Retry для partial

### Проблема

Текущий `retry_failed_task` (cron 3:00 AM) ретраит только `ai_status = 'failed'`. Закладки со статусом `partial` (классификация ок, embedding упал) зависают навсегда.

### Решение

Новая cron-задача: раз в день найти все `partial` → повторить только embedding.

### Логика

```python
async def retry_partial_embeddings(ctx: dict) -> None:
    """Ретрай embedding для partial-закладок. Раз в день."""
    
    # 1. Найти partial с retry_count < 5
    # 2. Для каждой: попробовать embedding
    # 3. Успех → ai_status = 'completed'
    # 4. Провал → retry_count += 1
    # 5. retry_count >= 5 → ai_status = 'completed_no_embedding' (permanent)
    # 6. Circuit breaker: 5 подряд фейлов → стоп
```

### Отличие transient от permanent

| Ошибка | Тип | Что делаем |
|--------|-----|-----------|
| Voyage API timeout | Transient | Retry |
| Voyage API 429 (rate limit) | Transient | Retry |
| Voyage API 402 (quota) | Transient (длинный) | Retry |
| Текст пустой | Permanent | Не retry |
| API вернул "content policy" | Permanent | Не retry |

### Дополнительные поля на Bookmark

```sql
ALTER TABLE bookmarks ADD COLUMN embedding_retry_count INTEGER DEFAULT 0;
ALTER TABLE bookmarks ADD COLUMN embedding_last_attempt TIMESTAMPTZ;
```

### Cron

```python
# В WorkerSettings.cron_jobs:
cron(retry_partial_embeddings, hour=5, minute=0)  # после retry_failed (3:00)
```

### Затронутые файлы

| Файл | Изменение |
|------|-----------|
| `backend/app/worker.py` | Новая cron-задача retry_partial_embeddings |
| `backend/app/models.py` | embedding_retry_count, embedding_last_attempt |
| `migrations/` | ALTER TABLE |

---

## 4. Search Traces — БЭКЛОГ

Таблица `search_traces` для логирования поисковых запросов. Строить когда будет Mini App (там натуральный click tracking).

Зафиксировано в бэклоге: логировать query, results_count, top_scores, clicked_id, search_ms. Анализировать после 500+ поисков.

---

## 5. Tag Co-occurrence — ОТЛОЖЕНО до Phase 4

Перенесено в Phase 4 (Smart Blocks). Ценность появляется при 200+ закладках. В Phase 4 co-occurrence нужна для auto-routing закладок в блоки.

---

## Порядок реализации

```
1. Embedding retry для partial      (~1-2 дня)  — quick win, баг-фикс
2. Usage decay в поиске             (~1-2 дня)  — правка SQL + last_accessed
3. Classification feedback           (~3-4 дня)  — таблица + API + few-shot injection
```

Feedback идёт последним: нужен UI в Mini App для кнопки "Не так". Можно подготовить backend (таблица + API + injection), а UI добавить когда будет Mini App.

---

## Что НЕ входит в scope

- Click tracking в боте (только Mini App)
- Category feedback (только item_type)
- Tag co-occurrence (Phase 4)
- Search traces (бэклог, ждём Mini App)
- Автоматический re-training модели (few-shot injection достаточно)
- Более 3 few-shot примеров (начинаем с 3)

---

## Зависимости

- **Phase 0:** IDOR fix (feedback endpoint должен проверять ownership)
- **Phase 0:** NotificationService (embedding retry использует worker)
- **Mini App:** для UI кнопки "Не так" (backend готовим сейчас, UI позже)
