# Контекст сессии 2026-05-02

Сводка всех решений, research-результатов и договорённостей.
Источник для будущих сессий — чтобы не терять контекст после compact.

---

## Что сделано в этой сессии

1. **Полное ревью кода** (3 параллельных агента: backend, bot, architecture)
2. **CCPM brainstorm + research** для Silent Mode и Learning Mechanisms
3. **PRD** для обеих фич
4. **Roadmap** на 7 фаз (~44-62 dev-days)
5. Обсуждение 5 фича-направлений с пользователем

---

## Ревью: ключевые находки

Полный список: `docs/REVIEW-2026-05-02.md`

### CRITICAL (5 штук)
1. SECRET_KEY = "change-me-in-production" → JWT подделываем
2. BOT_SECRET = "" → auth отключён
3. verify=False для GigaChat → MITM
4. _pending_saves keyed by tg_id → сохраняет не то сообщение
5. InaccessibleMessage не обработан → AttributeError на старых кнопках

### Архитектурные рекомендации
- Worker напрямую дёргает Telegram API → coupling, выделить NotificationService
- Bookmark = God Object (30+ колонок) → выделить BookmarkAnalysis
- API versioning /api/v1/ до появления Mini App
- /health не проверяет Postgres/Redis
- CORS ["*"] с credentials → браузеры блокируют

---

## Research: Telegram Reactions API

**Источник:** Telegram Bot API docs, aiogram 3.27.0 source, GitHub (nanobot, pyTelegramBotAPI)

- `setMessageReaction` — Bot API 7.0 (декабрь 2023)
- aiogram: `await message.react([ReactionTypeEmoji(emoji="👀")])`
- Можно менять реакцию повторным вызовом, убрать через `reaction=[]`
- **⏳ и ✅ НЕ доступны** для ботов. Используем 👀 → 👍/👎
- Бот = 1 реакция на сообщение (non-premium)
- Работает на все типы: text, photo, voice, forward
- Rate limit: ~30 req/s общий
- Best practice (nanobot pattern): best-effort, non-blocking, ошибки логируются

### Доступные эмодзи для ботов
👍 👎 ❤️ 🔥 🥰 👏 😁 🤔 🤯 😱 🤬 😢 🎉 🤩 🤮 💩 🙏 👌 🕊 🤡 🥱 🥴 😍 🐳 ❤️‍🔥 🌚 🌭 💯 🤣 ⚡ 🍌 🏆 💔 🤨 😐 🍓 🍾 💋 🖕 😈 😴 😭 🤓 👻 👨‍💻 👀 🎃 🙈 😇 😨 🤝 ✍ 🤗 🫡 🎅 🎄 ☃ 💅 🤪 🗿 🆒 💘 🙉 🦄 😘 💊 🙊 😎 👾 🤷‍♂ 🤷 🤷‍♀ 😡

### Код-паттерн для Silent Mode
```python
async def safe_react(message: Message, emoji: str) -> None:
    try:
        await message.react([ReactionTypeEmoji(emoji=emoji)])
    except Exception as e:
        logger.debug("Reaction failed: %s", e)
```

---

## Research: Learning Mechanisms

### Few-shot injection
- 3 примера по cosine similarity — оптимум для старта
- Защита: consistency check (A→B и B→A = невалидны), similarity > 0.3, TTL 6 мес
- Паттерн: SemanticSimilarityExampleSelector (LangChain), но на сыром SQL + pgvector

### Usage Decay
- Логарифмический: `1 / (1 + 0.1 * ln(1 + age_days))`
- Сегодня=1.0, неделя=0.84, месяц=0.74, год=0.63
- Decay от last_accessed (сбрасывается при просмотре)
- is_favorite = буст +0.05
- Заметки НИКОГДА не убиваются (min ~0.5)
- Источник: Jones & Teevan (2007) — для personal info recency менее важна

### Embedding Retry
- Текущий баг: retry_failed_task не трогает partial
- Решение: cron 1/день, max 5 retries, circuit breaker (5 подряд фейлов → стоп)
- Exponential backoff: 2^retry_count часов
- Permanent failures: пустой текст, content policy → не retry

### Tag Co-occurrence — отложено до Phase 4
- PMI точнее чем простой count
- Materialized view + REFRESH CONCURRENTLY
- Ценность при 200+ закладках

### Search Traces — бэклог
- Таблица: query, results_count, top_scores[], clicked_id, search_ms, used_fallback
- Click tracking только в Mini App (не в боте)
- MRR как метрика качества: AVG(1/clicked_position)
- Zero-result analysis: логировать, смотреть руками

---

## Решения по Silent Mode

| # | Вопрос | Решение |
|---|--------|---------|
| 1 | Ошибки | Явный текст, ephemeral (автоудаление 10с) |
| 2 | Onboarding | Контекстный: первый раз через фичу → развёрнуто, с пометкой "только один раз" |
| 3 | Task lists | Реакция 👀 → готовый список (без промежуточного "Обработка...") |
| 4 | NL-команды | Только reply на сообщение бота = команда. Остальное = save |
| 5 | Группы | Corner case, отложен |
| 6 | Прогресс | 👀 → 👍 (два состояния, K.I.S.S.) |
| 7 | Batch/debounce | Не нужен (реакция = 1 API call, ~50ms) |
| 8 | Настройка | `/silent` toggle + Mini App. Silent по дефолту |
| 9 | Уровни | Два режима: Silent (дефолт) + Verbose (opt-in). Без промежуточного |
| 10 | Метрики | messages/day, streak, bulk ratio. Мерить после MVP |

## Решения по Learning Mechanisms

| # | Вопрос | Решение |
|---|--------|---------|
| 1 | Click tracking | Только в Mini App/приложении, не в боте |
| 2 | Search traces | Бэклог, не сейчас |
| 3 | Zero-result | Логировать, смотреть руками |
| 4 | Feedback UI | Только Mini App/приложение, не в боте |
| 5 | Granularity | Только item_type (4 кнопки) |
| 6 | Few-shot count | 3 примера для старта |
| 7 | Decay для вечнозелёного | Сброс при просмотре (last_accessed) |
| 8 | Формула decay | Логарифмическая |
| 9 | Tag co-occurrence | Перенесено в Phase 4 (Smart Blocks) |
| 10 | Embedding retry | Cron 1/день, max 5 retries, circuit breaker |

---

## 5 фича-направлений (от пользователя)

### F1: Silent Mode
Бот как избранное — кинул и забыл. Реакции вместо сообщений.

### F2: Multi-format
Voice → STT → text → pipeline. PDF, DOCX, фото (OCR). Голосовые = killer feature.

### F3: Smart Blocks (Спецблоки)
НЕ папки. Блок = папка + AI-поведение + auto-routing.
Примеры: "Глобальные цели", "Идеи для продукта", "Что почитать", "Важно когда-нибудь сделать".
Персонализация: ИИ предлагает блоки после 50-100 закладок.
5 базовых шаблонов оформления, но содержание персональное.

### F4: Проактивность 1.0
Продукт напоминает заметки при удобном случае, строит связи.
Как Obsidian brain-wiki: trace → feedback → connections → decay.
Привычки пользователя → knowledge + instincts на основе обратной связи.

### F5: Проактивность 2.0
AI-агент с руками: календарь, задачи, файлы, рабочие советы.
Только research — не строить без пользовательской базы.

### Ключевая мысль пользователя
"За общением юзер может к любой нейронке сходить, у нас другая цель."
Цель = инструмент для быстрого сохранения + умная организация + проактивные напоминания.

---

## Roadmap (порядок работы)

```
Phase 0: Hardening (8-10 дней) ← НАЧИНАЕМ
Phase 1: Silent Mode (3-4 дня)
Phase 2: Learning Mechanisms (5-7 дней)
Phase 3: Multi-format (7-10 дней)
Phase 4: Smart Blocks MVP (10-14 дней)
Phase 5: Proactivity 1.0 (8-12 дней)
Phase 6: Proactivity 2.0 research (3-5 дней)
```

Mini App — после Phase 2, когда бэкенд hardened и есть чем наполнить UI.

---

## Файлы созданные в сессии

| Файл | Содержание |
|------|-----------|
| `docs/REVIEW-2026-05-02.md` | Полные результаты code + architecture review |
| `docs/ROADMAP-2026-05.md` | Детальный roadmap 7 фаз с задачами и оценками |
| `docs/prd/SILENT-MODE.md` | PRD Silent Mode |
| `docs/prd/LEARNING-MECHANISMS.md` | PRD Learning Mechanisms |
| `docs/SESSION-CONTEXT-2026-05-02.md` | Этот файл — сводка всего контекста |
