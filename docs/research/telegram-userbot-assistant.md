# Ресёрч: AI-ассистент на личном Telegram (userbot + LLM)

> Май 2026 · 4 области (A/B/C/D) · ~40 источников · уверенность: средняя-высокая
> (часть anti-ban — форумная молва, помечено). Research-only, без кода.

## Краткое резюме

Фича технически реализуема, но это **userbot на MTProto** (не Bot API) — со
всеми последствиями: нарушение ToS, риск бана, обработка чужих персональных
данных. Главные выводы:

1. Архитектурно — **отдельный процесс-слушатель + очередь + воркеры**, не в одном
   event-loop с aiogram.
2. **Чтение — низкий риск, авто-отправка — высокий.**
3. Безопаснее всего — **draft-for-approval + локальная LLM**.
4. Полная автономность отправки — главный источник «жути» и провалов у аналогов.

---

## A. Архитектура 24/7-слушателя

**Каноничный паттерн:** один `asyncio.run(main())` → `client.start()` →
`run_until_disconnected()`, хендлеры на `events.NewMessage`. **Критично: внутри
хендлера нельзя блокировать** — LLM-вызов забьёт очередь апдейтов; работу
выносить в очередь.

**Resilience:** `auto_reconnect=True` (default), `flood_sleep_threshold` (60с —
короче спит сам, длиннее кидает `FloodWaitError`). **Тихие дисконнекты реальны**
— на проде ставят watchdog+keep-alive поверх `run_until_disconnected`.
`catch_up=True` (replay пропущенного) — слабое место, не всегда отдаёт
пропущенное. **Дубли апдейтов задокументированы** (Telethon #1410, #336) →
**дедуп на твоей стороне обязателен** (idempotent consumer: хранить
обработанные `chat_id+msg_id`).

**Сессия:** `StringSession` (в env/секрет) vs файловая SQLite. **Жёсткое
ограничение: одна сессия = один процесс** — переиспользование в двух процессах
даёт `database is locked` / «wrong session ID». StringSession не снимает правило
«один аккаунт = одно живое соединение».

**Деплой рядом со стеком bookmark-brain (aiogram3 + FastAPI + arq + Redis + PG):**
Telethon и aiogram *технически* живут в одном loop, но **продакшен-форма —
отдельный процесс/контейнер** для userbot: независимый рестарт, обход
session-lock, разные модели отказа MTProto vs getUpdates. Loop нельзя менять
после `connect()` — частый источник «attached to a different loop».

**Рекомендуемый паттерн (decoupling):** userbot = тонкий ingester →
валидирует+дедупит → `XADD` в Redis Stream / arq-job → **существующие
arq-воркеры** гонят LLM, пишут в Postgres, опц. отвечают. MTProto-loop остаётся
отзывчивым, LLM масштабируется отдельно, обработка crash-safe. Идеально ложится
на текущую архитектуру bookmark-brain — userbot новый, воркеры/Redis/PG
переиспользуются.

## B. Ban-avoidance (2026, с пометками о достоверности)

**Проверенное (офиц./либы):** Telegram **не публикует** точные лимиты.
`FloodWaitError` = RPC 420 с `.seconds`, обработка = exponential backoff.
Софт-пороги ~30 msg/s агрегат, ~20 msg/min в один чат — это **Bot API**, для
userbot строже и недокументировано.

**Детекция поведенческая, не по ключевым словам** (консистентно во всех
источниках): равномерные интервалы, отсутствие пауз, бёрсты, новые аккаунты,
VoIP-номера, одинаковые сообщения многим.

**Помечено как НЕпроверенное:**
- «6ч (2023) → 24ч (2026)» — *эскалация* флуд-вейта до 24ч реальна (форумы), но
  точная траектория «6→24» нигде в офиц. источниках = **молва**.
- «Contributor Quality Score» — такого термина в доках Telegram **нет**. Есть
  реальный **Trust Score** (Anti-Spam v2). CQS = маркетинговое имя anti-ban-блогов.
- Числа warm-up — от GoLogin (вендор anti-detect, biased, но конкретно).

**Actionable (с оговоркой про источник):** прогрев 7 дней (дни 1-2 только читать;
3-5 по 3-5 сообщений знакомым; 6-7 до 10-20/день). 2-3 непрошеных DM незнакомцам
в первые 48ч → «Spam Prison». 10+ групп за час = риск. **Главное правило по
таймингу: рандомизировать (не фиксированные 30с)**, а не конкретное число
джиттера. **Чтение/лёрк = низкий риск; равномерная авто-отправка = высокий** —
подтверждено напрямую. Аппел через @SpamBot: первый раз часто авто-снимается за
24-72ч.

## C. Приватность/правовое (чужие сообщения через LLM)

**GDPR:** «бытовое исключение» (Art. 2(2)(c)) трактуется **узко** — ломается,
когда обработка «направлена вовне» приватной сферы. Прогон чужих сообщений в
облачную LLM аргументированно выводит их за домашний контур → ты становишься
контролёром (lawful basis, прозрачность, минимизация). Согласие каждого автора
непрактично. *Точная граница для «LLM-assisted personal use» в гайдах EDPB не
устоялась — помечено.*

**Политики облачных LLM (2026):**
- **Anthropic API** — на инпутах **не тренируются**, retention 30→**7 дней**,
  есть **ZDR**.
- **OpenAI API** — с 2023 не тренируются на API, до 30 дней для abuse, ZDR.
- **Google Gemini** — *платный* tier не тренируется; **бесплатный/AI Studio
  ЯВНО тренируется + human review** → **не использовать для чужих сообщений**.

**Локальная LLM = самая чистая позиция** (данные не уходят). 2025-26 open-weight
(Qwen2.5/3, Llama 3.3, Gemma 3, Mistral) через Ollama/llama.cpp/vLLM. Железо:
8GB VRAM→7B, 16GB→13-14B, ~24GB (RTX 3090)→больше. 14B-модель ≈80-90% качества
фронтира на суммаризации/экстракции — достаточно для триажа чатов.

**Минимизация:** Microsoft Presidio для PII-редакции до вызова (с обратимой
подстановкой); обрабатывать только метаданные/релевантное; ephemeral (без
хранения).

**РФ (152-ФЗ):** исключение «для личных/семейных нужд» (как GDPR — узко);
передача чужих сообщений зарубежному процессору рискует выйти за него. *Прямых
разъяснений по LLM нет — помечено.*

## D. Продуктовое определение (как делают аналоги)

**Три тира продуктов:** (1) хобби-userbot'ы на Telethon (keyword-триггеры,
away-mode, форвард «срочного» человеку); (2) «digital twin / клон себя» (файнтюн
на истории чатов — самая этически проблемная категория, эксперименты); (3) зрелые
email-продукты с human-in-the-loop (Gmail Smart Reply, Superhuman Auto Drafts —
пишет черновик в папку drafts, **никогда не шлёт сам**).

**Триггеры (безопасно→рискованно):** away/offline-режим → keyword/intent-гейтинг
→ эскалация срочного человеку → allowlist знакомых → confidence-порог.

**UX:** доминирует **draft-for-approval** (AI пишет — человек правит и шлёт).
Полностью автономная отправка — почти только в хобби-away-ботах с генеричными
сообщениями. Раскрытие «это AI» стандартно в саппорте, но **отсутствует в
clone-проектах — главный creep-фактор**.

**Полезно vs жутко:** полезно = триаж/черновик, которым владеет человек. Жутко =
молчаливое выдавание себя за пользователя. Задокументированные провалы:
галлюцинированные обещания, prompt injection из входящих, инцидент фев-2026 с
автономным агентом. Получатели всё чаще распознают и не любят AI-почту.

**Консенсус best-practice:** suggestion, не automation; human-in-the-loop по
умолчанию; автономность только за allowlist + away + intent + confidence;
**суммаризация/триаж вместо авто-ответа при сомнении** — самый безопасный
value-add.

---

## Таблица рисков

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Бан/ограничение аккаунта (userbot ToS) | Средняя | Высокое (личный аккаунт!) | Read-heavy, no auto-send; рандомный тайминг; прогрев; @SpamBot-аппел |
| Тихий дисконнект 24/7-сервиса | Высокая | Среднее | Watchdog + keep-alive поверх run_until_disconnected |
| Дубли событий → двойная обработка/ответ | Высокая | Среднее | Idempotent consumer (дедуп по chat_id+msg_id) |
| Утечка чужих ПД в облачную LLM | Средняя | Высокое (правовое) | Локальная LLM или ZDR + Presidio-редакция; не free Gemini |
| Session string compromised | Низкая | Критичное (полный доступ) | env/секрет-менеджер, не в коде/гите |
| AI шлёт ложь от твоего имени | Средняя | Высокое (репутация) | Draft-for-approval, без автономной отправки |
| Prompt injection из входящих | Средняя | Среднее | Санитизация (chigwell/telegram-mcp умеет), не выполнять инструкции из сообщений |

## Рекомендуемая архитектура (MVP)

```
[Telethon userbot — отдельный контейнер]
   listens events.NewMessage (read-only)
   dedup (chat_id+msg_id) → XADD Redis Stream
        │
        ▼
[существующие arq-воркеры]
   LLM (локальная или Anthropic ZDR + Presidio-redaction)
   → суммаризация / триаж / ЧЕРНОВИК ответа
   → Postgres
        │
        ▼
[aiogram-бот bookmark-brain] показывает черновик/дайджест
   юзер одобряет → отправка (через userbot)
```

**Фазировка:**
- **Фаза 1** — только **чтение + триаж/дайджест** (низкий риск, реальная польза,
  проверяет ценность).
- **Фаза 2** — **draft-for-approval** (юзер жмёт «отправить»).
- Автономную отправку — не делать или максимально гейтить (allowlist + away +
  confidence).

---

## Источники

**A — Архитектура**
- https://docs.telethon.dev/en/stable/concepts/updates.html
- https://docs.telethon.dev/en/stable/concepts/sessions.html
- https://docs.telethon.dev/en/stable/quick-references/faq.html
- https://dev.to/btcmiles/troubleshooting-and-resolving-telegram-bot-disconnection-issues-a-practical-pitfall-sharing-527g
- https://github.com/LonamiWebs/Telethon/issues/1410 , /issues/336 (дубли), /issues/1039 (shared session)

**B — Ban-avoidance**
- https://docs.telethon.dev/en/stable/concepts/errors.html
- https://github.com/python-telegram-bot/python-telegram-bot/wiki/Avoiding-flood-limits
- https://gologin.com/blog/telegram-account-banned/ (вендор, biased)
- https://limits.tginfo.me/en
- https://www.blackhatworld.com/seo/getting-fed-up-from-peer-flood-error-from-telegram.1602385/ (форум)

**C — Приватность/правовое**
- https://www.edpb.europa.eu/sites/default/files/files/file1/edpb_guidelines_201903_video_devices.pdf
- https://platform.claude.com/docs/en/manage-claude/api-and-data-retention
- https://developers.openai.com/api/docs/guides/your-data
- https://ai.google.dev/gemini-api/terms , https://ai.google.dev/gemini-api/docs/zdr
- https://ploomber.io/blog/presidio/
- https://www.consultant.ru/document/cons_doc_LAW_61801/ (152-ФЗ)

**D — Продукты/UX**
- https://github.com/Muaath5/AutoReplyUserBot , https://github.com/dulagudeta/Telegram-Auto-Reply-Bot
- https://github.com/kinggongzilla/ai-clone-whatsapp
- https://research.google/pubs/pub48231/ (Gmail Smart Compose)
- https://superhuman.com/products/mail/ai , https://help.superhuman.com/hc/en-us/articles/40144492186515-Auto-Reminders-Auto-Drafts
- https://time.com/7216284/dont-let-ai-write-your-emails-essay/
- https://news.slashdot.org/story/26/02/14/0553208/

---

*Сгенерировано: 2026-05-24. Статус: research-only, требует product-решения перед PRD.*
