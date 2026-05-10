# ADR 0006 — Smart Blocks без топиков в DM

**Статус:** принято
**Дата:** 2026-05-10
**Связано с:** Phase 5 (Smart Blocks MVP), `tools/spike_dm_topics.py`

## Context

При планировании Phase 5 (Smart Blocks) рассматривались три архитектурных варианта:

- **A.** Smart Blocks = виртуальные сущности в БД, UI через бот-команды + Mini App
- **B.** Smart Blocks = физические топики (forum threads) в чате юзера с ботом
- **C.** Гибрид: БД-блоки как источник истины, топики как опциональный «view»

Триггером для рассмотрения B/C стал релиз **Bot API 10.0** (8 мая 2026), changelog которой заявил: *«Allowed bots to create topics in private chats using createForumTopic»*.

Если бы фича работала в 1-на-1 DM с ботом — это дало бы нативный Telegram UX для блоков (юзер видит топики прямо в чате, без выхода в Mini App). Это могло бы радикально упростить UI и сократить scope Mini App.

## Spike (10 мая 2026)

Создан скрипт `tools/spike_dm_topics.py` — standalone polling-клиент с raw HTTPS-вызовами Bot API на токене `@bookmarkbrain_dev_bot`.

Тестовый сценарий в DM с ботом:

```
/spike_status:
    chat type:    private
    is_forum:     None
    has_topics:   None

/spike_create Goals:
    POST createForumTopic
    → 400 Bad Request: "the chat is not a forum"
```

## Вывод

В **1-на-1 DM** с ботом метод `createForumTopic` возвращает 400. Чат имеет `type: "private"` и **не может быть превращён в форум** — ни юзером через настройки клиента, ни ботом через API.

Формулировка changelog «Allowed bots to create topics in private chats» относится к **приватным супергруппам** (private = не публичная), где forum mode уже включён владельцем. К сценарию «юзер ↔ бот в DM» это **не применимо**.

## Decision

**Smart Blocks реализуем как чисто БД-сущности (вариант A).** Топики не используем — ни сейчас, ни в будущем (в текущей модели Telegram).

UI Smart Blocks:
1. Бот-команды: `/blocks list`, `/blocks <name>`, `/blocks setup`
2. Mini App: фильтр блоков, drag-and-drop, редактирование `ai_prompt`

Связь `bookmark ↔ smart_block` — таблица в Postgres. Auto-routing работает в `worker.py` после classification + embedding, на основе `ai_prompt` блока + правил.

## Consequences

**Плюсы:**
- Не зависим от свежей Bot API (10.0 раскатывается фрагментарно)
- Простая БД-схема, понятная архитектура
- Mini App становится главным UI блоков — это нормально для нашего стека
- Работает на любом Telegram-клиенте

**Минусы:**
- UX блоков целиком завязан на Mini App или бот-команды — нет нативного ощущения «папок» в чате
- Юзер должен открывать Mini App чтобы видеть структуру

**Что сэкономили спайком:**
- ~3 дня работы на реализацию слоя топиков, который не работал бы
- Архитектурный долг от попытки sync БД ↔ Telegram

## Ссылки

- [Bot API Changelog](https://core.telegram.org/bots/api-changelog) — 10.0 (8 мая 2026)
- `tools/spike_dm_topics.py` — спайк-скрипт (можно удалить или оставить как утилиту для проверки в будущем)
- Лог спайка с подтверждением 400 — приложен в commit message

## Что пересмотреть в будущем

Если Telegram добавит метод вроде `enableForumModeInPrivateChat` или новый тип чата для DM с топиками — пересмотреть это решение через новый ADR.
