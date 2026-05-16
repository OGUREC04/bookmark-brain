# Mini App — Code Audit

**Источник:** анализ `D:\projects\bookmark-brain\frontend\` + сопоставление с backend
**Автор:** code-explorer agent
**Дата:** 2026-05-15

---

## 1. Карта компонентов

### Pages

| Файл | Строк | State / Props | Side Effects | Роль |
|---|---|---|---|---|
| `BookmarkList.tsx` | 121 | 5 state, 0 props | useEffect: load(1) on mount | Список с пагинацией кнопками |
| `BookmarkDetail.tsx` | 235 | 6 state, 0 props | load+folders, TG BackButton | Детали: summary, теги, папка, favorite/delete |
| `Search.tsx` | 87 | 5 state, 0 props | нет | SearchBar + SearchSummary + citation-скролл |
| `Folders.tsx` | 168 | 5 state, 0 props | load() on mount | Список папок + inline форма |
| `FolderDetail.tsx` | 131 | 5 state, 0 props | load + BackButton | Закладки папки, удаление из папки |

### Components

| Файл | Строк | Props | Side Effects | Роль |
|---|---|---|---|---|
| `BookmarkCard.tsx` | 70 | `bookmark: Bookmark` | нет | Карточка + TaskListView |
| `BottomNav.tsx` | 34 | нет | нет | Нижняя навигация |
| `SearchBar.tsx` | 37 | onSearch, placeholder, autoFocus | нет | Submit по Enter |
| `SearchSummary.tsx` | 42 | summary, onCitationClick | нет | AI-ответ с кликабельными [N] |
| `TaskListView.tsx` | 88 | bookmarkId, data, onChange? | PATCH при toggle | Чек-лист оптимистичный |

### Lib & CSS
- `api.ts` (215) — fetch wrapper + JWT + типы + 14 API-методов
- `telegram.ts` (72) — обёртка `window.Telegram.WebApp`
- `styles.css` (759) — единый файл, секции по ASCII-комментам, CSS custom properties + `.theme-dark`

---

## 2. API Surface

### Frontend вызывает (14 методов)

| Метод | Endpoint | Backend | Статус |
|---|---|---|---|
| `getBookmarks` | `GET /api/v1/bookmarks/` | `list_bookmarks` | OK |
| `getBookmark` | `GET /api/v1/bookmarks/{id}` | `get_bookmark` | OK |
| `deleteBookmark` | `DELETE /api/v1/bookmarks/{id}` | OK | OK |
| `toggleFavorite` / `updateBookmark` | `PATCH /api/v1/bookmarks/{id}` | OK | OK |
| `search` | `POST /api/v1/search/` | OK | **хрупкость** ↓ |
| `getMe` | `GET /api/v1/users/me` | OK | **не вызывается** |
| `getTags` | `GET /api/v1/search/tags` | OK | **не вызывается** |
| `getFolders` / `createFolder` / `deleteFolder` / `getFolderBookmarks` / `addBookmarkToFolder` / `removeBookmarkFromFolder` | `/api/v1/folders/*` | OK | OK |

**search хрупкость:** Frontend не передаёт `with_summary`. Backend `SearchRequest.with_summary` имеет `default=True`. Если default поменяется — AI-ответ исчезнет без изменений во frontend. **→ передавать явно `with_summary: true`**.

### Backend endpoints, которые НЕ используются во frontend

- `GET /api/v1/bookmarks/random`
- `POST /api/v1/bookmarks/{id}/reprocess`
- `POST /api/v1/bookmarks/{id}/nl-edit`
- `POST /api/v1/bookmarks/{new_id}/merge-into/{old_id}`
- `POST /api/v1/bookmarks/reprocess-all`
- `GET /api/v1/folders/{id}` — **FolderDetail делает `.find()` вместо этого**
- `PATCH /api/v1/folders/{id}` — переименование
- `PATCH /api/v1/users/me/settings`
- `PATCH /api/v1/users/me/timezone`
- **Весь `reminders.py`** — POST/PATCH/DELETE/upcoming/history/apply-decision — **полностью не подключён**

---

## 3. Технический долг и костыли

### Auth: `let authToken` в module-scope
- Обнуляется при reload — `getToken()` повторно вызывает `/auth/telegram`
- ❌ Нет retry-on-401 — если токен протухнет, любой запрос падает
- ❌ Telegram `initData` TTL ~24ч — re-auth упадёт с 401

### BrowserRouter в WebView
- `history.pushState` риски: (1) reload `/bookmark/uuid` без `try_files` → 404, (2) на iOS Telegram блокирует `popstate` при сворачивании
- **Рекомендация:** HashRouter или SDK-навигация

### Нет обработки 401
- `request()` бросает на любой `!res.ok` без различения статусов

### Fetch без abort/cleanup
- Ни один `useEffect` не возвращает cleanup с `AbortController`
- Race condition при смене маршрутов: старый fetch вызывает `setState` после unmount
- Особо критично в `BookmarkDetail.tsx` (Promise.all 2 запросов)

### FolderDetail — лишний запрос
- Вызывает `api.getFolders()` и `.find(f => f.id === id)` вместо `GET /api/v1/folders/{id}`

### Мелочи
- `perPage = 20` — magic number в 2 местах
- `catch { /* ignore */ }` в Folders / FolderDetail — ошибки молча проглатываются
- `document.getElementById` в Search.tsx — обход React-идиомы, надо `useRef`

---

## 4. Что переиспользовать без переписывания

- **`lib/api.ts`** — весь слой целиком. Типы соответствуют backend. **Добавить:** reminders, nl-edit, retry-on-401, явный `with_summary: true`
- **`lib/telegram.ts`** — все 5 функций, чистые обёртки
- **`SearchSummary.tsx`** — изолирован, парсинг `[N]` рабочий
- **`TaskListView.tsx`** — оптимистичный toggle с rollback, иммутабельный, готов
- **`SearchBar.tsx`** — минимальный
- **CSS-дизайн-система** из `styles.css` — custom properties, dark theme, spacing, радиусы, тени. Можно разбить на модули

---

## 5. Что выкинуть

- **Пагинация кнопками** (BookmarkList, FolderDetail) — `← / →` неудобны на touch → infinite scroll
- **Inline форма создания папки** в Folders.tsx (showCreate state) → bottom sheet
- **Хрупкая логика BottomNav** — скрытие через `location.pathname.startsWith(...)` → конфиг с `hideNav: true`
- **`document.getElementById`** в Search.tsx → useRef
- **Мёртвые методы** `getMe()`, `getTags()` — удалить или подключить
- **Молчащие `catch { /* ignore */ }`** → toast/snackbar

---

## Key Files

| Файл | Важность |
|---|---|
| `frontend/src/lib/api.ts` | Критичный, переиспользовать |
| `frontend/src/lib/telegram.ts` | Переиспользовать |
| `frontend/src/components/TaskListView.tsx` | Переиспользовать |
| `frontend/src/components/SearchSummary.tsx` | Переиспользовать |
| `frontend/src/styles.css` | Переиспользовать токены |
| `backend/app/api/reminders.py` | Подключить в редизайне |
| `backend/app/schemas.py` | Проверить SearchRequest.with_summary |
