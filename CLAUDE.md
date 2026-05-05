# BookmarkBrain

AI-инструмент для организации сохранённого контента. Telegram-бот → AI классификация/теги/саммари → быстрый поиск через бота, Mini App, iOS.

> **Где искать детали (читай on-demand, НЕ авто):**
> - 🚀 Запуск проекта (Docker / Backend / Worker / Bot / ngrok) — `.claude/STARTUP.md`
> - 📐 Архитектура, data model, auth, env vars, статус — `docs/ARCHITECTURE.md`
> - 🤖 Команды бота, clean chat, task list UX, AI pipeline — `docs/BOT-UX.md`
> - 🩹 Известные проблемы и решения — `docs/TROUBLESHOOTING.md`

---

## Главный принцип: ПРОСТОТА И СКОРОСТЬ

Продукт должен быть таким же быстрым, как Telegram Избранное. Сохранение в один шаг: написал → отправил.

1. **Дефолтный путь — ноль кликов.** AI работает в фоне. Категории/теги/типы — auto-detect.
2. **Обогащение опционально.** Inline-кнопки только если AI считает нужным; пропуск юзером не блокирует сохранение.
3. **Бот — primary UX для быстрых действий.** Mini App/iOS — для просмотра, поиска, редактирования.
4. **Не заставляй структурировать.** Юзер пишет как попало — AI причёсывает.
5. **Заметка не обязана жить долго.** Не требуй метаданных от одноразовых.

Любая фича, добавляющая трение → антипаттерн. Ищи zero-click или опциональный путь.

### Правило чистого чата

Чат с ботом должен напоминать Telegram Избранное — в истории видны в основном сообщения юзера, а не бота.

- **Один ответ на одно действие** — не "Жди..." + "Готово!", а edit одного сообщения.
- **Транзитные сообщения авто-удаляются** через 3–8 сек (хелпер `_ephemeral`).
- **Подсказки/ошибки → инлайн-alert** (`callback.answer(show_alert=True)`), не отдельное сообщение.
- **Итоговая форма > процесс.** Показываем отформатированный результат, не "обрабатываю...готово!".

Юзер должен чувствовать, что пишет сам себе. Бот — невидимый помощник.

---

## Связь с D:\brain (внешняя память)

- **Knowledge Base Index** грузится через SessionStart hook — техническая память (грабли окружения).
- На ключевые слова окружения (`bat, cmd, pip, python, venv, ngrok, docker, alembic, postgres, redis, OneDrive, encoding, .env, PATH`) — сначала смотрю Knowledge Base Index, читаю релевантные `concepts/*` через `mcp__brain__read_text_file`.
- MCP `mcp__brain__*` — **deferred**. Подгружай через `ToolSearch` `select:mcp__brain__read_text_file` когда нужно.
- Для чисто кодовых задач в этом репо — в `D:\brain\` не лезу.

### Записать в долгосрочную память

Если "это тянет на статью" / "сохрани как learned" / "зафиксируй грабли" → пишу в `D:\brain\claude-memory-compiler\daily\<YYYY-MM-DD>.md`, секция `### Session [bookmark-brain] (ЧЧ:ММ)`, блок `**Lessons Learned:**`. Atomic-формат «проблема → решение» (не сырой диалог).

---

## Стек (кратко)

FastAPI + PostgreSQL/pgvector + Redis/arq + aiogram 3.x. AI: GigaChat (классификация) + Voyage AI (embeddings 1024d). Frontend: Expo (React Native) для iOS + Mini App. Деплой: Railway.

## Constraints

- Async SQLAlchemy (AsyncSession), arq для фоновых задач (не Celery).
- AI отвечает на русском (settings.SYSTEM_PROMPT).
- Embedding dim: 1024 (voyage-3).
- Бот: polling в dev, webhook в prod.
- Все endpoints → Pydantic schemas.
- Если AI падает — закладка сохраняется без классификации, retry позже.
- **Отвечать пользователю на русском.**
