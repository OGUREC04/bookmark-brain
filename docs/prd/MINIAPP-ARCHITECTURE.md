# Mini App Redesign — Implementation Blueprint

> ⚠️ **2026-05-16: hifi-locked Design System v1** в `docs/design-system/`.
> **Сначала читать `MINIAPP-DS-INTEGRATION.md`** — дельта, 3 конфликта, Фаза R (rework T1-T7).

**Версия:** 1.1 (DS-corrected)
**Дата:** 2026-05-15 · ревизия 2026-05-16
**Источники:** MINIAPP-REDESIGN.md, MINIAPP-PLAN.md, MINIAPP-CODE-AUDIT.md, MINIAPP-UX-PATTERNS.md, tokens.css + полный аудит `frontend/src/` и `backend/app/`

---

## 1. Summary

~70% кода переписывается: карточки, навигация, стейт, стили. ~30% переиспользуется: `api.ts`, `telegram.ts`, `TaskListView`, `SearchBar`, `SearchSummary`. Backend трогаем минимально (3 правки без миграций): relationship `ScheduledMessage → Bookmark`, `joinedload` в `/upcoming`, query param `item_type`.

UI-термин «Мысли» существует только во frontend. Backend остаётся с `Bookmark`. Адаптер `lib/adapters.ts` изолирует расхождение.

**Главный архитектурный выбор:** глобальный `SheetContext` со stack-based `openSheet(Component, props)` вместо per-page `useState`. Это решает `ReminderPickerSheet`, открытый из `ActionSheet` с сохранением `thoughtId`.

**Расхождения между артефактами:**
- BottomNav: REDESIGN говорит 3+FAB, финальный стиль — 5 пунктов с центральным FAB. **Реализуем 5**
- `item_type` в backend: 4 значения (`action|thought|content|reference`), UX-docs упоминает 6 визуальных типов → best-effort маппинг в адаптере
- Таб «Я», `adapters.ts`, `formatters.ts`, `SheetContext` — отсутствуют в T1-T14 PLAN.md → добавлены в обновлённый build order

---

## 2. TypeScript-интерфейсы

### 2.1 Thought (`lib/types.ts`)

```typescript
export type ThoughtKind =
  | 'link' | 'article' | 'voice' | 'task' | 'idea' | 'action' | 'other';

export interface TaskProgress { done: number; total: number; }

export interface Thought {
  id: string;
  title: string;           // bookmark.title || bookmark.raw_text.slice(0, 60)
  summary: string | null;
  tags: Array<{ id: string; name: string }>;
  isFavorite: boolean;
  createdAt: string;
  folderId: string | null;
  aiStatus: string;
  url: string | null;
  rawText: string;
  structuredData: import('./api').TaskListData | null;

  // Деривативы (адаптер)
  kind: ThoughtKind;
  taskProgress: TaskProgress | null;
  hasReminder: boolean;
  reminderAt: string | null;
}
```

### 2.2 ThoughtCardProps

```typescript
export type CardVariant = 'feed' | 'chats';

export interface ThoughtCardProps {
  thought: Thought;
  variant: CardVariant;
  onTap: (id: string) => void;
  onLongPress: (id: string, position: { x: number; y: number }) => void;
  onMenuTap: (id: string) => void;
}
```

### 2.3 BottomSheetProps

```typescript
export interface BottomSheetProps {
  isOpen: boolean;
  onClose: () => void;
  snapHeight?: number;       // 0-100, % viewportStableHeight
  showHandle?: boolean;
  children: React.ReactNode;
}
```

### 2.4 useLongPress

```typescript
export function useLongPress(
  onLongPress: (position: { x: number; y: number }) => void,
  options?: { delay?: number; moveThreshold?: number },
): {
  onPointerDown, onPointerUp, onPointerMove, onPointerCancel, onClick
}
// pointer events (не touch — кроссплатформенно)
// CSS: touch-action: pan-y; user-select: none; -webkit-touch-callout: none
```

### 2.5 useTheme / useViewMode

```typescript
export function useTheme(): { isDark: boolean }

export function useViewMode(): {
  viewMode: 'feed' | 'chats';
  setViewMode: (m) => void;
  toggleViewMode: () => void;
}
// localStorage 'bb_view_mode', default 'feed', sync setItem
```

---

## 3. Структура папок

```
frontend/src/
├── main.tsx                       # T1: HashRouter, applyTheme sync до createRoot
├── App.tsx                        # T3: Layout + SheetContext.Provider + SheetHost
│
├── lib/
│   ├── api.ts                     # EXTEND: reminders.*, createThought, item_type param
│   ├── telegram.ts                # EXTEND: applyTheme, themeChanged, haptic
│   ├── adapters.ts                # NEW T5: bookmarkToThought, deriveKind, buildRemindersMap
│   ├── formatters.ts              # NEW T2: formatDate, formatRelativeDate
│   └── types.ts                   # NEW T1: Thought, ThoughtKind, TaskProgress
│
├── hooks/
│   ├── useLongPress.ts            # T6-dep
│   ├── useTheme.ts                # T2-dep
│   ├── useViewMode.ts             # T3-dep
│   ├── useInfiniteThoughts.ts     # T7: IntersectionObserver + AbortController
│   └── useReminderCount.ts        # T8-dep
│
├── state/
│   └── SheetContext.tsx           # T3/T8-dep: stack-based openSheet
│
├── components/
│   ├── nav/
│   │   ├── AppHeader.tsx          # T3
│   │   └── BottomNav.tsx          # T4 liquid-glass 5 items
│   ├── cards/
│   │   ├── ThoughtCard.tsx        # T6: switch variant + longPress wrapper
│   │   ├── ThoughtCardFeed.tsx
│   │   ├── ThoughtCardChats.tsx
│   │   ├── ThoughtMeta.tsx        # shared: date, tags, badges
│   │   └── IconType.tsx           # T5
│   ├── sheets/
│   │   ├── BottomSheet.tsx        # T8 generic
│   │   ├── ActionSheet.tsx        # T8 4 actions
│   │   ├── RemindersSheet.tsx     # T9
│   │   ├── ReminderPickerSheet.tsx # T10
│   │   ├── MoveToSpaceSheet.tsx   # T12
│   │   └── QuickCreateSheet.tsx   # T13
│   └── ui/
│       ├── FilterChips.tsx        # T7 sticky auto-hide
│       ├── Skeleton.tsx           # T7 shimmer
│       ├── Toast.tsx              # T7 aria-live polite
│       └── EmptyState.tsx         # T7
│
├── pages/
│   ├── Thoughts.tsx               # T7
│   ├── ThoughtDetail.tsx          # бывший BookmarkDetail + AbortController + ⏰
│   ├── Search.tsx                 # T14 cosmetics
│   ├── Spaces.tsx                 # T11
│   ├── SpaceDetail.tsx            # T11
│   └── Profile.tsx                # T4 stub
│
└── styles/
    ├── tokens.css                 # REUSE Echo/Sage
    ├── layout.css                 # T2 layout/header/nav/safe-area
    ├── cards.css                  # T6
    └── sheets.css                 # T8
```

**Удалятся:** BookmarkList, Folders, FolderDetail, BookmarkCard, старый BottomNav.

---

## 4. ThoughtCard — variant render pattern

**Решение:** `ThoughtCard` обёртка + 2 layout-компонента + shared sub-components.

```tsx
function ThoughtCard({ thought, variant, onTap, onLongPress, onMenuTap }: ThoughtCardProps) {
  const lp = useLongPress((pos) => onLongPress(thought.id, pos), { delay: 500 });
  const Layout = variant === 'feed' ? ThoughtCardFeed : ThoughtCardChats;

  return (
    <div role="listitem" aria-label={thought.title} {...lp} onClick={() => onTap(thought.id)}>
      <Layout thought={thought} onMenuTap={() => onMenuTap(thought.id)} />
    </div>
  );
}
```

**Tap feedback:** CSS `:active { transform: scale(0.97); transition: 80ms; }` — без JS.
**Почему не children composition:** variant — runtime из localStorage, не compile-time. Feed и Chats слишком разные визуально.

---

## 5. Sheet-стратегия — SheetContext stack

**Причина:** `ActionSheet` открывает `ReminderPickerSheet` с `thoughtId` — без context требуется prop drilling через 3 уровня.

```typescript
interface SheetEntry {
  id: string;
  component: React.ComponentType<any>;
  props: Record<string, unknown>;
}

interface SheetContextValue {
  openSheet: <P extends object>(c: React.ComponentType<P>, props: P) => void;
  closeSheet: (id?: string) => void;  // без id = закрыть верхний
  closeAll: () => void;
}
```

**Stack, не singleton:** `ActionSheet → ReminderPickerSheet` могут жить одновременно. Закрытие верхнего возвращает к нижнему.

**Исключение:** confirm delete — boolean `isConfirming` внутри `ActionSheet`. Атомарно, без вложенности.

---

## 6. Auth refresh — singleton promise

**Проблема:** 5 параллельных 401 → 5 POST `/auth/telegram`. Решение — общий promise:

```typescript
let authToken: string | null = null;
let refreshPromise: Promise<string> | null = null;

async function getToken(): Promise<string> {
  if (authToken) return authToken;
  if (refreshPromise) return refreshPromise;   // дедупликация

  refreshPromise = (async () => {
    /* fetch /auth/telegram */
    return authToken!;
  })().finally(() => { refreshPromise = null; });

  return refreshPromise;
}

async function request<T>(path, options = {}, retryCount = 0): Promise<T> {
  const token = await getToken();
  const res = await fetch(path, { ...options, headers: { Authorization: `Bearer ${token}`, ... } });

  if (res.status === 401) {
    authToken = null;
    if (retryCount > 0) throw new AuthExpiredError();
    return request(path, options, 1);
  }
  /* ... */
}
```

**`AuthExpiredError` global:** `window.addEventListener('unhandledrejection', e => { if (e.reason instanceof AuthExpiredError) showAuthExpiredScreen() })`. Full-screen с `WebApp.close()`.

**Note:** наша текущая реализация в `api.ts` (T1) — функционально эквивалентна, использует `authInFlight` вместо `refreshPromise`. ОК.

---

## 7. View mode persist

```typescript
const VIEW_MODE_KEY = 'bb_view_mode';
const DEFAULT: ViewMode = 'feed';   // новым крупные карточки понятнее

export function useViewMode() {
  const [viewMode, setVM] = useState<ViewMode>(() => {
    const saved = localStorage.getItem(VIEW_MODE_KEY);
    return (saved === 'feed' || saved === 'chats') ? saved : DEFAULT;
  });

  const setViewMode = (mode: ViewMode) => {
    localStorage.setItem(VIEW_MODE_KEY, mode);   // синхронно
    setVM(mode);
  };

  return { viewMode, setViewMode, toggleViewMode: () => setViewMode(viewMode === 'feed' ? 'chats' : 'feed') };
}
```

Context не нужен — один уровень prop drilling из `Thoughts.tsx` → `AppHeader` + `ThoughtCard.variant`.

---

## 8. Theme bootstrap

**Порядок в `main.tsx` синхронно до `createRoot`:**

```typescript
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready(); tg.expand();
  applyThemeParams(tg.themeParams);
  document.documentElement.setAttribute('data-tg-bridge', 'true');
  document.documentElement.setAttribute('data-theme', tg.colorScheme === 'dark' ? 'echo-dark' : 'echo');
} else {
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme', prefersDark ? 'echo-dark' : 'echo');
}
ReactDOM.createRoot(...).render(...);
```

**`applyThemeParams`:** маппит TG keys → CSS vars (`bg_color → --tg-theme-bg-color` и т.д.) согласно `tokens.css [data-tg-bridge]`.

**Listener `themeChanged`** в `useTheme` hook: `tg.onEvent('themeChanged', handler)` + cleanup `offEvent`. Расширить `TelegramWebApp` interface.

**Note:** T1+T2 в коде уже реализуют это в `lib/telegram.ts::applyTheme()`.

---

## 9. API-адаптер

**Место:** `lib/adapters.ts`. Не в hooks, не в `api.ts`. Тестируется независимо.

```typescript
export function bookmarkToThought(b: Bookmark, remindersMap = new Map()): Thought {
  return {
    /* ...поля... */
    kind: deriveKind(b),
    taskProgress: deriveTaskProgress(b),
    hasReminder: !!remindersMap.get(b.id),
    reminderAt: remindersMap.get(b.id)?.fireAt ?? null,
  };
}

function deriveKind(b: Bookmark): ThoughtKind {
  // Порядок важен — task_list приоритетнее url
  if (b.structured_data?.type === 'task_list') return 'task';
  if (b.content_type === 'voice') return 'voice';
  if (b.item_type === 'action') return 'action';
  if (b.item_type === 'thought') return 'idea';
  if (b.item_type === 'content') return 'article';
  if (b.url) return 'link';
  return 'other';
}

export function buildRemindersMap(reminders): Map<string, { fireAt: string }> {
  /* O(1) lookup по bookmark_id */
}
```

**В Thoughts.tsx:** `Promise.all([api.getBookmarks(), api.reminders.upcoming()])` → `buildRemindersMap` → `.map(bookmarkToThought)`.

---

## 10. Тестовая стратегия

**Стек:** vitest + RTL. Playwright defer.

| Файл | Что проверяем |
|---|---|
| `useLongPress.test.ts` | timer @500ms, cancel при move>10px, click suppression, cancel при pointerUp |
| `useViewMode.test.ts` | persist, toggle, default='feed', невалидное → default |
| `useTheme.test.ts` | isDark, listener update, desktop fallback |
| `adapters.test.ts` | deriveKind 7 веток (порядок!), taskProgress, иммутабельность |
| `ThoughtCard.test.tsx` | feed + chats рендер, ⭐ ⏰ badges |
| `BottomSheet.test.tsx` | isOpen, backdrop click |
| `IconType.test.tsx` | все 7 kinds без warnings |
| `FilterChips.test.tsx` | active, click, сброс |

Моки: `vi.mock('../lib/api')`, `vi.stubGlobal('Telegram', {...})`.

---

## 11. Обновлённый Build Order

**Пропуски найдены и встроены:**

| Что | Куда |
|---|---|
| Таб «Я» | Profile.tsx stub в T4 |
| `lib/adapters.ts` | T5, блокирует T6 |
| `lib/formatters.ts` | T2 |
| `SheetContext` | T3, блокирует T8 |
| Toast + EmptyState | T7 |
| IntersectionObserver | T7 явно |
| AbortController | T7 + ThoughtDetail |
| Backend B1+B2 | перед T7/T9 |

```
── Фаза 0: Backend (параллельно) ──
B1  models.py: ScheduledMessage.bookmark relationship
    api/reminders.py: selectinload + поля в ReminderResponse
B2  api/bookmarks.py: item_type query param

── Фаза 1: Фундамент ──
T1  HashRouter + theme + retry-on-401     ✅ DONE
T2  tokens.css + layout.css + formatters + useTheme  ✅ DONE (formatters defer)
T3  App.tsx + SheetContext + SheetHost + useViewMode  ✅ DONE (без SheetContext)

── Фаза 2: Навигация ──
T4  AppHeader + BottomNav + Profile stub + useReminderCount  ✅ DONE (counter stub)
T5  IconType + adapters + types + reminders API methods

── Фаза 3: Основной экран ──
T6  useLongPress + ThoughtMeta + ThoughtCardFeed/Chats/wrapper + ThoughtDetail
T7  Skeleton + EmptyState + Toast + FilterChips + useInfiniteThoughts + Thoughts.tsx

── Фаза 4: Действия ──
T8  BottomSheet + ActionSheet + wire-up
T9  RemindersSheet (requires B1)
T10 ReminderPickerSheet
T11 Spaces + SpaceDetail
T12 MoveToSpaceSheet
T13 QuickCreateSheet + FAB wire-up

── Фаза 5: ──
T14 Search cosmetics
```

---

## 12. Backend changes (no migrations)

### B1 — Reminders with bookmark relationship

**`backend/app/models.py`** в `ScheduledMessage`:
```python
bookmark: Mapped[Optional["Bookmark"]] = relationship("Bookmark", foreign_keys=[bookmark_id], lazy="noload")
```

**`backend/app/api/reminders.py`** в `list_upcoming`:
```python
.options(selectinload(ScheduledMessage.bookmark))
```

**`backend/app/schemas.py`** `ReminderResponse`:
```python
bookmark_title: str | None = None
bookmark_raw_text: str | None = None
```

### B2 — item_type filter

**`backend/app/api/bookmarks.py`** `list_bookmarks`:
```python
item_type: str | None = None,   # query param
...
if item_type is not None:
    stmt = stmt.where(Bookmark.item_type == item_type)
    count_stmt = count_stmt.where(Bookmark.item_type == item_type)
```

### Confirmed (no changes):
- `source="miniapp"` — String(20), 7 символов, OK
- PATCH bookmarks: `folder_id`, `is_favorite` уже есть
- `with_summary` — передавать явно в Search.tsx
- `/auth/telegram` idempotent

---

## 13. Открытые вопросы

1. **BottomNav 3 или 5?** Решено: 5 (текущая имплементация)
2. **`item_type` калибровка:** добавить `data-kind` атрибут на 2 недели для DevTools-проверки
3. **`hasReminder` через 2 запроса** — MVP. Phase 5: backend join (`pending_reminder_at`)
4. **Infinite vs virtualization:** обычный + IntersectionObserver. `virtua` если jank на Android при 50+
5. **Tag filter:** клиентский в MVP. Серверный в B2 при 500+
6. **Profile stub:** имя + счётчик. Полный PRD перед Phase 5
7. **AbortController:** обязательно в ThoughtDetail + useInfiniteThoughts
8. **TG SDK onEvent:** проверить версию `@telegram-apps/sdk`. Fallback `document.addEventListener('tg:themeChanged')`

---

*Следующий шаг: T5 → T6 → T7. Backend B1+B2 — параллельно перед T9.*
