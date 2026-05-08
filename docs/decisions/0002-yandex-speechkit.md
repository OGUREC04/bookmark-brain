# ADR 0002 — Yandex SpeechKit как STT-провайдер

**Статус:** принято
**Дата:** 2026-04 (миграция с Groq при деплое на VPS)
**Связано с:** `backend/app/services/` (STT интеграция в pipeline голоса)

## Context

Phase 3A добавила голосовой ввод. На локальном dev использовали Groq Whisper (быстро и дёшево). При деплое на прод-VPS обнаружилось — **Groq заблокирован из РФ** (бот живёт на VPS Beget Cloud, RU-IP). OpenAI Whisper — та же проблема. Self-hosted Whisper — тяжёлый (CPU-only inference на VPS = 30+ сек на минуту аудио, неприемлемо).

## Decision

Использовать **Yandex SpeechKit** для production STT. Локально dev может оставлять Groq (`STT_PROVIDER=groq`) — переключение через env var.

Реализация — абстрактный `BaseSTTProvider`, конкретные классы `YandexSTT`, `GroqSTT`, `OpenAISTT`. Выбор в рантайме по `STT_PROVIDER`.

## Consequences

**Плюсы:**
- Доступен из РФ — Beget Cloud + Yandex Cloud работают без VPN.
- Хорошее качество русской речи (Yandex родной для русского).
- Стабильный API, документация на русском.
- Платежи в рублях, без блокировок.

**Минусы:**
- Нужен платёжный аккаунт + role `clouds.member` на уровне облака — больше bureaucracy чем у Groq.
- Платный с первого запроса (нет бесплатного тарифа как у Groq), но цены копеечные.
- Латентность чуть выше чем у Groq (Groq был чемпион).
- API ключи Yandex имеют другой формат — пришлось обновлять `.env.production.example` и `memory/deployment.md`.
