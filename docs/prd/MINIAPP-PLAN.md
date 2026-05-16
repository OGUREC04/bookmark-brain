# Mini App Redesign — Implementation Plan

> ⚠️ **2026-05-16: вставлена Фаза R (rework T1-T7 под locked DS v1)** перед T8.
> Детали и 3 конфликта — `MINIAPP-DS-INTEGRATION.md`. T11 Spaces → **TagsPage**.

**Источник брифа:** `MINIAPP-REDESIGN.md` + DS `docs/design-system/`
**Автор:** planner agent + curator · ревизия 2026-05-16
**Дата:** 2026-05-15

---

## Цель MVP

Переделать Mini App под новую ментальную модель «Мысли/Пространства» с шапкой-колокольчиком (reminders), FAB-«+» и long-press меню. Достаточно для запуска на 5–10 живых юзерах: основной список читается, избранное фильтруется, reminders видны и снимаются из app, можно создать текстовую мысль.

---

## Декомпозиция (T1–T14)

| ID  | Название                              | Зависимости | Estimate |
|-----|---------------------------------------|-------------|----------|
| T1  | HashRouter + theme bootstrap + JWT refresh on 401 | —          | 2ч       |
| T2  | Дизайн-токены + themeParams → CSS vars (light/dark) | T1         | 2ч       |
| T3  | Каркас Layout: Header (logo, 🔔, ⋮), Outlet, BottomNav 3-таба | T1, T2     | 2ч       |
| T4  | Новый BottomNav: Мысли / Поиск / Пространства | T3         | 1ч       |
| T5  | IconType компонент (lucide-react: Link/Article/Voice/Task/Idea/Action) | T2         | 1,5ч     |
| T6  | ThoughtCard (новый дизайн карточки: иконка, title, summary, теги мелкие, ⭐, дата, ⏰-бейдж) | T5         | 3ч       |
| T7  | ThoughtsPage: список + фильтр-чипы (Все / ⭐ / по типу) + skeleton + empty | T6, API     | 3ч       |
| T8  | Long-press menu (ActionSheet): Удалить / Избранное / В пространство / Напомнить | T6         | 3ч       |
| T9  | RemindersSheet (колокольчик): список upcoming + history, snooze/cancel | T3, API     | 4ч       |
| T10 | ReminderPickerSheet (today / завтра / неделя / custom datetime) — переиспользуется в T8 | T9         | 2,5ч     |
| T11 | SpacesPage (рефактор Folders): grid с emoji + counter + создать | T3         | 2ч       |
| T12 | MoveToSpaceSheet (bottom-sheet для T8) | T11         | 1,5ч     |
| T13 | FAB «+» + QuickCreateSheet (текстовый ввод → POST bookmark) | T3, API     | 3ч       |
| T14 | SearchPage cosmetics (новая шапка, skeleton, copy «Мысли») | T3          | 1,5ч     |

**Итого ~32ч.** При AI-pair tempo ×5 — ~1.5 рабочих дня.

---

## Порядок / критический путь

- **Фаза 1 — фундамент (T1→T2→T3→T4):** без него ничего не рендерится в новом стиле. Параллелить нельзя.
- **Фаза 2 — основной экран (T5→T6→T7):** даёт «видимый прогресс».
- **Фаза 3 — действия (T8, T10, T12, T13):** T8 блокируется T10 и T12 (sheet-пикеры). T13 независим.
- **Фаза 4 — reminders (T9, T10):** параллельно с Фазой 2 после API-gap закрыт.
- **Фаза 5 — Spaces + Search (T11, T14):** в конце.

---

## Архитектурные решения

- **Роутер:** HashRouter в `src/main.tsx`. Telegram WebView надёжнее с `#`.
- **State:** `useState` + лёгкий Context для invalidate после mutate. Без React Query/Zustand (KISS, YAGNI).
- **Theme:** `applyTheme(themeParams)` при init + слушатель `themeChanged`. CSS vars `--bb-*`.
- **Auth refresh:** в `lib/api.ts` оборачиваем `request()`. 401 → обнуляем токен → повтор `getToken()` → повтор запроса (один раз). Если 401 второй раз — full-screen CTA «Перезапусти Mini App из бота».
- **Long-press:** свой `useLongPress(onLongPress, {delay: 500})` на pointer events + `HapticFeedback.impactOccurred('medium')`.
- **Sheets:** один общий `BottomSheet` (overlay + slide-up + dismiss). Переиспользуется в T8/T9/T10/T12/T13.
- **Иконки:** `lucide-react` (~5KB tree-shaken). Никаких эмодзи в карточке.
- **Cache-busting:** Vite hash + `Cache-Control: no-cache` в index.html.

---

## Переиспользуем как есть (минимальные правки)

- `lib/api.ts` — расширяем (`reminders.*`, `createBookmark`).
- `lib/telegram.ts` — добавим `themeParams` listener и `HapticFeedback` wrappers.
- `components/SearchBar.tsx`, `SearchSummary.tsx`, `TaskListView.tsx` — без изменений.
- `pages/BookmarkDetail.tsx` → переименуется в `ThoughtDetail.tsx`, контент остаётся; добавится «⏰ Напомнить».
- `pages/Search.tsx` — копия + skeleton.
- Backend `bookmarks.py`, `folders.py`, `reminders.py` — переиспользуем.

---

## Переписываем полностью

- `main.tsx` — BrowserRouter → HashRouter, theme bootstrap.
- `App.tsx` — новый Layout с Header + Outlet + FAB + BottomNav.
- `components/BottomNav.tsx` — 3 новые вкладки, иконки lucide.
- `components/BookmarkCard.tsx` → `ThoughtCard.tsx` — новый layout, IconType, приглушённые теги, ⭐, ⏰-бейдж, long-press hook.
- `pages/BookmarkList.tsx` → `pages/Thoughts.tsx` — фильтр-чипы, skeleton, новый empty-state.
- `pages/Folders.tsx` → `pages/Spaces.tsx` — новый grid, новая копия.
- `styles.css` — переписать с нуля поверх дизайн-токенов из T2.

---

## Новые компоненты

- `components/AppHeader.tsx` — лого, 🔔 c counter-badge, ⋮ меню
- `components/BottomSheet.tsx` — generic shell
- `components/RemindersSheet.tsx` — список upcoming + history, snooze/cancel
- `components/ReminderPickerSheet.tsx` — quick-выбор времени
- `components/MoveToSpaceSheet.tsx`
- `components/Fab.tsx`
- `components/QuickCreateSheet.tsx` — textarea + Save
- `components/ThoughtCard.tsx`
- `components/IconType.tsx` — маппинг `item_type/content_type` → lucide icon
- `components/FilterChips.tsx`
- `components/Skeleton.tsx`
- `hooks/useLongPress.ts`
- `hooks/useTheme.ts`

---

## API gap (что добавить в backend)

1. **GET `/api/v1/reminders/upcoming`** — добавить eager-load `bookmark` (избегаем N+1). Расширить `ReminderResponse.bookmark_title: str | None`.
2. **GET `/api/v1/reminders/count`** (новый) — `{ pending: int }` для badge на колокольчике. Альтернатива: считать в upcoming.
3. **POST `/api/v1/bookmarks/`** — подтвердить что `source='miniapp'` валиден в enum. Если нет — расширить.
4. **GET `/api/v1/bookmarks/?is_favorite=true&item_type=task_list`** — `item_type` filter отсутствует. Добавить параметр.
5. **GET `/api/v1/bookmarks/?tag=...`** — для фильтр-чипов (опционально, можно клиент-side в MVP).
6. **PATCH `/api/v1/bookmarks/{id}`** — поддерживает `folder_id`, `is_favorite` ✅
7. **Auth refresh:** убедиться что `/auth/telegram` идемпотентен по тому же initData.

**Не нужно:** новых таблиц, миграций. snooze = PATCH `/reminders/{id}`, cancel = DELETE.

---

## Риски + митигации

- **R1: initData протух (>24ч)** → 401 на любом запросе. **Митигация:** `request()` ловит 401 один раз, передёргивает токен. Повтор 401 → CTA «Перезапусти из бота».
- **R2: WebView кеширование** → Vite hash + `Cache-Control: no-cache` + явное «hard close» в README.
- **R3: themeParams flash** → читать `Telegram.WebApp.themeParams` синхронно в `main.tsx` до `createRoot`.
- **R4: Long-press конфликт с iOS** → `user-select: none`, `-webkit-touch-callout: none`, `touch-action: pan-y`. Тест на iOS.
- **R5: FAB перекрывает последнюю карточку** → `padding-bottom: 96px` + safe-area inset.
- **R6: N+1 при reminders** → см. API gap #1.
- **R7: Drift копии «Закладки» → «Мысли»** — меняем только UI app, bot copy остаётся.
- **R8: Snooze UX неоднозначен** → две явные кнопки «Отложить (+1ч / +1д / завтра)» и «Отменить».
- **R9: lucide-react bundle** → именованные импорты, tree-shaking.
- **R10: Long-press + tap fire** → в `useLongPress` гасить click если сработал long-press.

---

## Out of scope MVP

- Голосовой ввод (есть в боте)
- Drag-and-drop
- Графики/аналитика
- Smart Spaces полноценные (Phase 5)
- Bulk actions
- Связи между мыслями (Phase 6)
- iOS native
- Markdown editor (только rendering)
- Onboarding-туториал (empty state CTA хватит)
- Подсветка stale-избранного (review-пинг от бота позже)
- Swipe-actions (под вопросом — решит a11y-architect)
