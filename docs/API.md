# API — справочник

Базовый URL: `/api/v1/`. Полная интерактивная документация Swagger живёт на `/docs` (FastAPI). Тут — обзор для людей.

## Авторизация

Два способа получить JWT-токен:

**Из бота (server-to-server):**
- `POST /auth/bot` с заголовком `X-Bot-Secret: <BOT_SECRET>` и телом `{ telegram_id, username, first_name }`. Бэкенд создаёт юзера если его нет, выдаёт JWT.

**Из Mini App (когда появится):**
- `POST /auth/telegram` с `initData` от Telegram. Бэкенд проверяет HMAC-подпись (ключ — токен бота), выдаёт JWT.

Дальше во все запросы — `Authorization: Bearer <JWT>`.

## Юзер

- `GET /users/me` — данные текущего юзера, его настройки, счётчики.
- `PATCH /users/me/settings` — обновить настройки (`silent_mode`, прочие toggles).

## Закладки

Главный ресурс системы.

- `POST /bookmarks/` — создать. Тело: `raw_text`, опц. `source`, `source_message_id`, `url`. Возвращает закладку с `ai_status='pending'` и сразу ставит её в очередь воркера.
- `GET /bookmarks/` — список с пагинацией (query: `limit`, `offset`, `category`, `is_archived`). Возвращает `BookmarkListResponse` с `total` и `items`.
- `GET /bookmarks/random` — случайная закладка юзера.
- `GET /bookmarks/{id}` — одна закладка.
- `PATCH /bookmarks/{id}` — обновить (title, raw_text, is_favorite, is_archived и т.д.).
- `DELETE /bookmarks/{id}` — удалить.
- `POST /bookmarks/{id}/reprocess` — заново прогнать через AI-пайплайн.
- `POST /bookmarks/reprocess-all` — принудительно переобработать все. Долгая операция.
- `POST /bookmarks/{id}/nl-edit` — редактирование обычным языком («сделай задачу 2», «перенеси на завтра»). Используется ботом для reply-команд на task lists.
- `POST /bookmarks/{new_id}/merge-into/{old_id}` — слияние при дедупликации. Новая закладка переносит свои теги/контент в старую, потом удаляется.

## Папки (folders)

Зарезервировано под Smart Blocks (Phase 5). Сейчас работают как обычные коллекции.

- `GET /folders/`, `POST /folders/`, `GET /folders/{id}`, `PATCH /folders/{id}`, `DELETE /folders/{id}` — стандартный CRUD.
- `GET /folders/{id}/bookmarks` — закладки внутри папки.
- `POST /folders/{id}/bookmarks/{bookmark_id}` — добавить закладку в папку.
- `DELETE /folders/{id}/bookmarks/{bookmark_id}` — убрать.

## Поиск

- `POST /search/` — гибридный поиск. Тело: `{ query, limit, offset }`. Возвращает результаты + общее число + опционально AI-обзор найденного.
- `GET /search/tags` — все теги юзера со счётчиками. Используется для UI с облаком тегов (Mini App).

## Health & служебное

- `GET /health` — проверка живости. Возвращает `{ status: "ok" }` если БД и Redis отвечают. Используется Docker `--wait` и мониторингом.

## Заголовки и коды

- Успех создания: `201 Created`.
- Успех удаления: `204 No Content`.
- Не найдено: `404`.
- Не твоя закладка (IDOR-защита): `404` (не `403` — не палим существование).
- Не авторизован: `401`.

## Что не задокументировано здесь

Точные схемы Pydantic — смотри `backend/app/schemas.py` или Swagger на `/docs`. Там будут все поля с типами и примерами.
