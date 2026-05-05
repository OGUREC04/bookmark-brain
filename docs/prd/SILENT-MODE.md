# PRD: Silent Mode

**Статус:** Draft
**Дата:** 2026-05-02
**Фаза:** Phase 1 (после Hardening)
**Оценка:** 3-4 dev-days

---

## Проблема

Бот отвечает текстовым сообщением на каждое входящее сообщение. Это создаёт ощущение диалога и обязывает юзера реагировать. В Telegram Saved Messages такого давления нет — кинул и забыл. Текущее поведение:

```
Юзер: "идея для продукта"
Бот: "📝 Сохраняю..."
Бот: "✅ Сохранено! Категория: thought, Теги: идеи, продукт"
```

Два сообщения от бота на одно от юзера. Шум.

## Решение

Бот молчит по умолчанию. Подтверждение — через реакции Telegram (Bot API 7.0+).

```
Юзер: "идея для продукта"
Бот: 👀 (реакция на сообщение)
     ... обработка в фоне ...
Бот: 👍 (реакция меняется)
```

Ноль сообщений от бота. Юзер видит что бот принял (👀) и обработал (👍).

---

## Режимы

### Silent (по умолчанию)

| Событие | Реакция бота |
|---------|-------------|
| Текст / форвард / медиа принят | 👀 реакция |
| Обработка завершена | 👀 → 👍 |
| Ошибка обработки | 👀 → 👎 + ephemeral сообщение (автоудаление 10с) |
| Task list определён | 👀 → отправка интерактивного сообщения (список + кнопки) |
| NL-команда (reply на сообщение бота) | Текстовый ответ |
| Slash-команда (/search, /list, /stats) | Текстовый ответ (как сейчас) |

### Verbose (opt-in, legacy)

Текущее поведение: текстовые сообщения "Сохраняю..." → "Готово! Категория: X, Теги: Y".
Включается через `/silent off`.

---

## Переключение

Команда `/silent`:
- `/silent` или `/silent on` — включить silent mode (дефолт)
- `/silent off` — включить verbose mode

Хранится в `User.settings` (JSONB): `{"silent_mode": true}`.

Когда будет Mini App — дублируется в UI настроек.

---

## NL-команды (Natural Language)

Бот отвечает текстом ТОЛЬКО когда юзер **отвечает reply на сообщение бота**. Это уже работает для task list editing. Расширяем:

| Действие юзера | Реакция бота |
|---------------|-------------|
| Reply на bookmark-сообщение: "что тут?" | Summary закладки |
| Reply на task list: "добавь молоко" | Обновлённый список (существующий NL-edit) |
| Reply на ошибку: "попробуй ещё раз" | Повторная обработка |
| Просто текст (не reply) | Silent save (реакция) |

**Правило:** Reply на бота = команда. Всё остальное = заметка для сохранения.

Это простое, детерминированное правило без AI-классификации intent. Легко объяснить юзеру в onboarding.

---

## Onboarding

Контекстный — срабатывает при первом прохождении фичи.

### Первое сообщение юзера (после /start)

Когда юзер отправляет первое сообщение (не команду), бот ОДИН РАЗ отвечает развёрнуто:

```
👀 (реакция на сообщение)

ℹ️ Я сохранил твою заметку! Обычно я работаю тихо — 
ставлю 👀 когда принял и 👍 когда обработал.

Это сообщение ты видишь только один раз. 
Дальше — только реакции, без лишних сообщений.

Ответь reply на любое моё сообщение, чтобы задать вопрос.
```

Флаг `User.settings.onboarding_silent_done = true` — показываем один раз.

### Первый task list

Когда юзер впервые создаёт task list:

```
📋 [интерактивный список]

ℹ️ Это список задач! Нажимай на пункты чтобы отмечать. 
Ответь reply чтобы изменить список текстом.
Это сообщение ты видишь только один раз.
```

Флаг `User.settings.onboarding_tasklist_done = true`.

---

## Task Lists в Silent Mode

Task list — исключение из полной тишины. Поток:

```
Юзер: "купить молоко, хлеб, сыр"
Бот: 👀 (реакция мгновенно)
Worker: определяет task_list → отправляет интерактивное сообщение
Бот: 📋 список + кнопки-чекбоксы (одно сообщение, без "Обработка...")
```

Убираем промежуточное сообщение "Обработка...". Реакция → готовый список. Минимум шума.

Реакция 👀 остаётся на оригинальном сообщении (не убираем — это маркер что бот обработал).

---

## Обработка ошибок

В silent mode ошибки — ephemeral (автоудаление):

```python
# При ошибке обработки
await message.react([ReactionTypeEmoji(emoji="👎")])
error_msg = await message.reply(
    "⚠️ Не удалось обработать. Попробуй ещё раз или напиши /help",
    parse_mode=None,
)
asyncio.create_task(_delete_after(error_msg, delay=10))
```

В verbose mode — как сейчас (постоянное сообщение с деталями ошибки).

---

## Технические детали

### Реакции (Telegram Bot API 7.0+)

```python
from aiogram.types import ReactionTypeEmoji

# Поставить реакцию
await message.react([ReactionTypeEmoji(emoji="👀")])

# Изменить реакцию
await message.react([ReactionTypeEmoji(emoji="👍")])

# Убрать реакцию
await message.react(reaction=[])
```

**Ограничения:**
- Боты (non-premium) — максимум 1 реакция на сообщение
- ⏳ и ✅ НЕ доступны для ботов. Используем 👀 и 👍/👎
- Реакции работают на все типы сообщений (text, photo, voice, forward)
- Best-effort: ошибки реакций логируются, не ломают основной flow

### Утилита safe_react

```python
async def safe_react(message: Message, emoji: str) -> None:
    """Best-effort реакция — не ломает основной flow при ошибке."""
    try:
        await message.react([ReactionTypeEmoji(emoji=emoji)])
    except Exception as e:
        logger.debug("Reaction failed (chat=%s, msg=%s): %s",
                     message.chat.id, message.message_id, e)
```

### Изменения в worker

Worker сейчас вызывает `editMessageText` для прогресса. В silent mode:
- НЕ создавать промежуточное сообщение "Обработка..."
- После обработки: вызвать `setMessageReaction(👍)` на оригинальное сообщение юзера
- При ошибке: `setMessageReaction(👎)` + ephemeral reply

Worker получает `silent: bool` через arq job kwargs. Источник: `User.settings.silent_mode`.

### Изменения в bot handlers

**`handle_text` (start.py):**
```
Было:  сообщение → отправить "Сохраняю..." → enqueue → worker edits
Стало: сообщение → safe_react(👀) → enqueue(silent=True) → worker reacts(👍)
```

**`handle_forward` (start.py):**
Аналогично.

**`handle_media` (start.py):**
Аналогично.

### Хранение настройки

`User.settings` JSONB (уже существует):
```json
{
  "silent_mode": true,
  "onboarding_silent_done": false,
  "onboarding_tasklist_done": false
}
```

Миграция не нужна — JSONB schemaless.

### TrackingMiddleware

В silent mode бот не отправляет сообщения → TrackingMiddleware не трекает → `/clean` не удаляет реакции (реакции не являются сообщениями). Это корректное поведение — реакции не мусорят в чате.

---

## Затронутые файлы

| Файл | Изменение |
|------|-----------|
| `bot/handlers/start.py` | handle_text, handle_forward, handle_media → safe_react вместо send_message |
| `bot/handlers/tasks.py` | task list flow → без промежуточного сообщения |
| `bot/handlers/settings.py` | **NEW** — /silent command |
| `bot/utils.py` | **NEW** — safe_react(), safe_remove_reaction() |
| `backend/app/worker.py` | process_bookmark_task: silent kwarg → react вместо editMessage |
| `backend/app/services/notification.py` | **NEW** (Phase 0) — NotificationService абстракция |

---

## Метрики (измерять после MVP)

| Метрика | Определение | Хороший сигнал |
|---------|------------|----------------|
| Messages/day/user | Среднее сохранений в день | 3-5 = привычка |
| Streak | Дни подряд с ≥1 сохранением | >7 дней = sticky |
| Bulk ratio | % сессий где >10 сообщений за 5 мин | Низкий = daily habit, не "сгрузил" |
| Silent adoption | % юзеров оставивших silent mode | >80% = дефолт правильный |
| Verbose switch | % юзеров включивших verbose | <20% = silent достаточен |

Мерить после набора ≥20 активных юзеров. До этого — качественный фидбек.

---

## Что НЕ входит в scope

- Адаптивный режим (разное поведение для коротких/длинных сообщений) — Phase 2+
- AI-классификация intent (save vs query) — не нужна, правило "reply = команда"
- Уровни болтливости (silent/informative/verbose) — YAGNI, два режима достаточно
- Группы — corner case, отложен
- Метрики на стадии MVP — только качественный фидбек

---

## Зависимости

- **Phase 0C:** NotificationService должен быть выделен из worker.py
- **Phase 0B:** Bot stability fixes (InaccessibleMessage guards, token cache TTL)
- **aiogram 3.x:** Уже установлен 3.27.0, поддерживает `message.react()`
- **Bot API 7.0+:** Поддерживается текущей версией Telegram
