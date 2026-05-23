# ADR 0010 — Metrics Foundation: Postgres event store + (later) Prometheus

**Дата:** 2026-05-23
**Статус:** Accepted (Phase M1 — event store реализован)
**Связано:** PRD `docs/prd/PHASE-2.7-REMINDERS-OMNIFORMAT.md` (B2 form_hint measurement — первый клиент)

## Контекст

Появилась потребность мерить **качество router-решений** (B2: расходится ли
решение роутера с холистической категорией AI `reminder_form_hint`). Первая
реализация писала это в `logger.info` → worker stdout → эфемерный лог-файл:
не персистит, не queryable, теряется при рестарте. Возник вопрос: где
правильно хранить метрики «на годы», чтобы не переделывать.

Ресёрч (2024-2026 практики) дал ключевой вывод: **«все метрики в одно место»
— анти-цель.** Events и metrics — разные типы данных:

- **Events** (наш route-audit) — высокая кардинальность, дименшены, запрос
  `GROUP BY` постфактум → event store (SQL).
- **Metrics** (latency, error rate, токены, очередь) — низкая кардинальность,
  time-series → Prometheus. Высокая кардинальность в Prometheus = взрыв.

Унификация — на уровне **дашборда** (Grafana с двумя источниками), не sink.

## Решение

**Сейчас (Phase M1):** generic Postgres event store `analytics_events`.

- Партиционирована **помесячно** `PARTITION BY RANGE(ts)` + DEFAULT-партиция
  (INSERT никогда не падает). Retention = `DROP PARTITION` (без bloat/VACUUM).
- PK композитный `(id, ts)` — Postgres требует partition key в PK.
- Колонки: `ts, event_name, source, dimensions JSONB`. Дименшены в JSONB
  (payload держим < 2KB — выше TOAST-cliff). GIN-индекс по dimensions +
  `(event_name, ts)`.
- Запись через `emit_event(name, source, **dims)` — **fire-and-forget,
  failure-isolated** (своя сессия/транзакция; сбой метрики НИКОГДА не
  отравляет транзакцию вызывающего флоу).
- Партиции катит cron `analytics_partition_maintenance` (worker, daily +
  run_at_startup): создаёт current+next месяц, дропает старше 6 мес.
- Первый клиент: `bookmark_processor` после `route()` пишет
  `reminder_router_decision` (router_form, ai_hint, agree, dated_count, …).

**Потом (Phase M2, отложено):** Prometheus + Grafana для ops-метрик
(latency / токены / очередь) — когда реально понадобятся. Grafana с двумя
источниками (Postgres events + Prometheus metrics) = «один дашборд».

**НЕ делаем:** OpenTelemetry (оверкилл на solo-dev/single-VPS — это
инструментация без хранилища, всё равно нужен backend + Collector),
self-host PostHog (требует 4 vCPU / 16 GB RAM, ClickHouse — обуза; PostHog
сам не рекомендует self-host ниже 100k событий/мес).

## Последствия

**Плюсы:**
- Queryable аналитика сразу (`SELECT … GROUP BY` по дименшенам).
- Не загоняет в угол: эмиссия за `emit_event()` → смена sink = тело одной
  функции. Партиционирование с day-one → retention тривиален.
- Ops-метрики добавятся независимо (другое хранилище, тот же дашборд).

**Минусы / границы:**
- Postgres event store ломается при ~десятках млн строк/мес или нужде в
  funnels/session-replay. Не наш масштаб (solo Telegram-бот). При выходе за
  предел — events → ClickHouse / PostHog Cloud (свап тела `emit_event`).
- `emit_event` своя сессия = +1 коннект из пула на событие. На нашем объёме
  (единицы событий/мин) незначительно.

## Migration path (без переписывания)

1. **Now:** `analytics_events` + `emit_event()`. Продуктовые вопросы.
2. **Ops-метрики:** `prometheus-client` + `/metrics` per-service + Prometheus
   + Grafana контейнеры. ~полдня, независимо от шага 1.
3. **Unify view:** Grafana, два источника (Postgres + Prometheus).
4. **Если перерастём:** OTel SDK / events → ClickHouse. Аддитивно.

## Источники

Honeycomb/BetterStack (events vs metrics, кардинальность), pganalyze/Snowflake
(JSONB TOAST cliff ~2KB), PostHog self-host disclaimer, prometheus-client
multiprocess, OneUptime (OTel для малых команд). См. ресёрч-бриф в истории
сессии 2026-05-23.
