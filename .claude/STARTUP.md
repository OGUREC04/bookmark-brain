# Инструкция по запуску проекта для Claude

> Эта инструкция — для Claude, чтобы не тратить токены на диагностику каждую сессию.
> **Если структура проекта или зависимости изменятся — обнови этот файл.**

## ВАЖНО: setup через venv

Проект лежит в `D:\projects\bookmark-brain\` (вне OneDrive — OneDrive Files On-Demand скрывал
пакеты из cmd-процессов, поэтому переехали на D:).

**venv создаётся в `%LOCALAPPDATA%\bookmark-brain\venv`** — Local не синхронизируется OneDrive.

- `install.bat` — разовая установка venv + requirements (запускать один раз после клонирования или при обновлении requirements)
- `start.bat` — запуск всех сервисов, использует venv
- `stop.bat` — остановка сервисов
- `refresh-ngrok-bot.bat` — **если ngrok отвалился/сменил URL посреди сессии** (Mini App показывает `ERR_NGROK_3200` / offline). Получает текущий ngrok URL (рестартит ngrok если мёртв), обновляет `MINI_APP_URL` в `.env`, перезапускает только бота (бэкенд/воркер не трогает). Закрывает классический рассинхрон «ngrok сменился → бот держит старый menu button».

Если cmd-Python не видит модуль, а bash видит — **НЕ копайся в PYTHONPATH**, просто запусти `install.bat`.

## Быстрый старт (копипаст)

Все 5 процессов запускаются фоном через `run_in_background: true`. Порядок: Docker → Backend → Worker → Bot → Frontend → ngrok.

### 0. Проверка состояния (первый шаг всегда)

```bash
docker ps --format "{{.Names}}"                     # postgres + redis должны быть up
curl -s http://localhost:8000/health                 # {"status":"ok"} — бэкенд жив
curl -s http://127.0.0.1:4040/api/tunnels | grep -o "https://[^\"]*ngrok[^\"]*" | head -1   # ngrok URL
tasklist | grep python                               # сколько процессов python.exe
```

Если что-то отсутствует — запустить по списку ниже.

### 1. Docker (PostgreSQL + Redis)

```bash
docker compose -f "D:/projects/bookmark-brain/docker-compose.yml" up -d
```

Контейнеры: `bookmarkbrain_postgres` (5432), `bookmarkbrain_redis` (6379).

### 2. Backend (FastAPI, порт 8000)

```bash
cd "D:/projects/bookmark-brain/backend" && python -m uvicorn main:app --host 0.0.0.0 --port 8000
```
Запускать с `run_in_background: true`.

### 3. Worker (arq, AI-обработка)

```bash
cd "D:/projects/bookmark-brain/backend" && python run_worker.py
```
Запускать с `run_in_background: true`. **ВАЖНО:** воркер может упасть один раз с `redis.TimeoutError` при первом poll — просто перезапусти его.

### 4. Telegram Bot (@N0teeBot)

```bash
cd "D:/projects/bookmark-brain" && python -m bot.main
```
Запускать с `run_in_background: true`. **ВАЖНО:** только ОДИН экземпляр бота может работать. Если видишь `TelegramConflictError` — убей все лишние python-процессы через `taskkill //PID <pid> //F`, подожди 10–12 сек и запусти снова.

### 5. Frontend (Vite dev server, порт 3000)

> **Фронтенд вынесен в ОТДЕЛЬНЫЙ репо** `bookmark-brain-miniapp`
> (соседняя папка `D:\projects\bookmark-brain-miniapp`,
> https://github.com/OGUREC04/bookmark-brain-miniapp). В монорепо его больше нет.

```bash
cd "D:/projects/bookmark-brain-miniapp" && npm run dev
```
Запускать с `run_in_background: true`. Vite слушает :3000 и **проксирует `/api` →
`localhost:8000`** (бэкенд из монорепо), так что менять ничего не нужно — backend,
worker, bot, ngrok по-прежнему стартуют из монорепо. ngrok указывает на :3000
независимо от того, из какого репо поднят Vite.

Вся НОВАЯ работа по UI — в `bookmark-brain-miniapp`, НЕ в монорепо.

### 6. ngrok (HTTPS-туннель для Telegram Mini App)

```bash
npx ngrok http 3000 --log=stdout
```
Запускать с `run_in_background: true`. URL получить так:
```bash
curl -s http://127.0.0.1:4040/api/tunnels | grep -o "https://[^\"]*ngrok[^\"]*" | head -1
```

**ВАЖНО:** URL ngrok меняется при каждом перезапуске. После получения нового URL:
1. Обнови `MINI_APP_URL=...` в `/.env`
2. Перезапусти бота (`TaskStop` + новый запуск) — он выставит menu button с новым URL

## Параллельный запуск

Когда стартуют независимые сервисы, **запускай их одновременно** одним сообщением с несколькими `Bash` tool calls (Docker не нужен в параллель — проверь что он уже up):
- Backend, Worker, Bot, ngrok можно стартовать параллельно
- Frontend — `npm run dev` из соседнего репо `bookmark-brain-miniapp` (отдельно)

## Типовые ошибки и решения

| Симптом | Что делать |
|---|---|
| `TelegramConflictError` у бота | Убить все python.exe кроме бэкенда, подождать 12 сек, запустить заново |
| `redis.TimeoutError` в воркере при старте | Перезапустить воркер (один раз бывает флаки) |
| PowerShell: `ModuleNotFoundError: No module named 'arq'` | Юзер использует системный Python 3.14 с user site-packages. Явно `C:\Python314\python.exe` + если нет модуля — `python -m pip install --user <pkg>`. **НЕ** `pip install -r requirements.txt` — там pydantic-core падает при компиляции (нет msvcrt.lib). |
| Vite: `Blocked request. This host is not allowed` | В `bookmark-brain-miniapp/vite.config.ts` уже стоит `allowedHosts: true`, `host: true`. Если нет — добавить. |
| Mini App: `Auth failed` | Бэкенд не запущен или упал. Проверь `/health`. |
| Бот не отвечает на сообщения | Процесс бота умер. Проверь `bot.log` / task output. |
| Mini App: `ERR_NGROK_3200` / endpoint offline | ngrok сменил URL, бот держит старый menu button. Запусти `refresh-ngrok-bot.bat` (или вручную: get ngrok URL → `update_env.py MINI_APP_URL <url>` → kill `python -m bot.main` → подожди 12с → старт бота). Потом **hard-close Mini App** в Telegram (свайп + ×), не refresh — WebView кеширует. |

## Зависимости между сервисами

```
Docker (postgres + redis)
  ├── Backend (нужен postgres)
  │     └── Bot (нужен Backend)
  └── Worker (нужен redis + postgres)

Frontend (Vite)
  └── ngrok (проксирует Frontend по HTTPS)
        └── Mini App в Telegram (открывается через ngrok URL)
```

## После запуска — сообщить пользователю

Вернуть короткий список статусов:
- ✅ Бэкенд (localhost:8000)
- ✅ Воркер (arq)
- ✅ Бот @N0teeBot
- ✅ Фронтенд (localhost:3000)
- ✅ ngrok URL: `https://xxxx.ngrok-free.app`

Если URL ngrok поменялся — напомнить обновить в BotFather (если Mini App привязан через BotFather) или просто — menu button бота уже обновлён автоматически при его перезапуске.

## Что НЕ надо делать

- ❌ Не тратить токены на `pip install` — всё уже установлено у пользователя (user site-packages для Python 3.14)
- ❌ Не предлагать пользователю руками запускать что-то в PowerShell — там кривой PATH и компиляторы не настроены
- ❌ Не проверять версии Python, Docker, Node — они работают
- ❌ Не читать `docker-compose.yml` и другие конфиги — они стабильны
