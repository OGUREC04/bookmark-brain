# Mini App ↔ Design System v1 — интеграция и коррекция плана

**Дата:** 2026-05-16
**Источник DS:** `docs/design-system/` (скопирован из handoff, hifi-locked v1)
**Статус:** требует решений пользователя по 3 конфликтам (см. конец)

---

## 0. Проверка: архитектура и документирование (ответ на вопрос 1)

| Проверка | Состояние |
|---|---|
| Ветка | `miniapp-redesign` от `origin/main` (PR #12 merged) ✅ |
| Backend B1+B2 | Уже в `origin/main` (подобраны другим чатом в PR #12) ✅ |
| import-linter / ruff (только `bot/`) | Не затронуты — `frontend/` не трогаю ✅ |
| `AGENTS.md` контракты | Соблюдены (frontend вне scope bot-контрактов) ✅ |
| Документирование | Beads `x3j oe8 94s 8g1 awz 7rt 0u7` + `MINIAPP-*.md` в `docs/prd/` (конвенция `docs/README.md`) ✅ |
| Сборка | `npm run build` зелёный, tsc чисто ✅ |

**Вывод:** архитектура верная, работа документируется. Стэш применён через `apply` (не `pop`) — цел до подтверждения.

---

## 1. Что нового в DS относительно текущей реализации T1-T7

DS = `docs/design-system/` (README + foundations + 13 references + reference_app). `foundations/colors_and_type.css` → теперь `frontend/src/styles/tokens.css` (568 строк, locked).

### 1.1 Совпадает (не трогаем)
- Brand Sage `#7A9C7A` ✅
- UI font Onest ✅
- Surfaces `--bg-page #F5F1EB` / `--bg-surface #FAF7F1` ✅
- HashRouter, retry-401, theme bridge `[data-tg-bridge]` ✅
- Liquid-glass bottom-nav (концепция) ✅
- Card + Chat-row двойной режим ✅

### 1.2 Расхождения — НУЖНА ПЕРЕДЕЛКА T1-T7

| # | DS требует | Сейчас в коде | Файл на правку |
|---|---|---|---|
| D1 | **Lora italic** display-font для AI summary / empty-state / callouts | Убрал display-font в T2 | `tokens.css`✅(уже), компоненты |
| D2 | **JetBrains Mono** для timestamps/counters/hex | `ui-monospace` | `tokens.css`✅(уже), карточки |
| D3 | **НЕТ `scale()` на press → `translateY(1px)`** | `.thought-card:active { scale(0.98) }` | `styles/cards.css` |
| D4 | **НЕТ spinner/shimmer-skeleton → одна sage-точка пульс 1.6s** | `Skeleton.tsx` shimmer | `Skeleton.tsx`, `layout.css` |
| D5 | **`--backdrop-gradient`** page-level (sage+apricot+blush+cream) | нет | `App.tsx` shell, `layout.css` |
| D6 | **`--shadow-glass`** + 2 рецепта glass (light/strong) | упрощённый glass на nav | `cards.css`, `layout.css` |
| D7 | Иконки stroke **1.4–1.5** (Lucide перештрихован) | Lucide 1.75–1.9 | `IconType.tsx`, все иконки |
| D8 | **Editorial-глифы** `∅ ✦ ★ ¶` Lora-italic-as-icon (empty-state, AI) | Lucide Inbox для empty | `EmptyState.tsx`, glyph-компонент |
| D9 | Tag-палитра **8 стопов** точные bg/fg (sage/ochre/slate/plum/clay/moss/rose/taupe) | 5 произвольных | `cards.css`, tag-рендер |
| D10 | Card padding `16 18`, radius `18`, **strong glass** на карточке | border + shadow-1 | `cards.css` |
| D11 | Chat-row: avatar **46px**, hairline `0.5px`, **chat-row = DEFAULT** | avatar 48px, feed default | `ThoughtCardChats.tsx`, `useViewMode` default |
| D12 | Кнопки — все **pill** (999), 5 вариантов (primary/glass/ghost/danger/ai) | минимальный .btn | `layout.css` + Button-компонент |
| D13 | Search field — strong-glass pill, **Lora-italic placeholder** | legacy `.search-input` | T14 |

### 1.3 Новые компоненты (НЕ в T1-T14)

| Компонент | Reference | Куда в плане |
|---|---|---|
| **AI suggestion pager** (горизонтальный snap-карусель + source-chips) | `09-ai-suggestion.html` `SuggestionCard.jsx` | НОВЫЙ T15 (Phase 6 surfacing — можно отложить) |
| **AI status SVG-rows** (glass-плитки, sage-done) | `10-ai-status.html` | НОВЫЙ T16 (нужно для UX обработки) |
| **Glyph** (editorial italic-as-icon) | `12-icons.html` | подкомпонент, в D8 |
| **GlassTile / Pulse / SearchBar / EmptyState atoms** | `Atoms.jsx` | в T8/T14 |
| **Backdrop gradient shell** | `13-brand-light.html` | в D5 |
| **Day separator** в chat-row («вчера» pill) | `08-bookmark-card.html` | T6.1 доработка |
| **Unread bar** (3×22 sage) | `08` | опционально |

---

## 2. Конфликты — РЕШЕНО (2026-05-16)

- **C1 → 5 табов с центральным FAB** (Мысли/Поиск/+/Простр./Я). Отклонение от DS-навигации сознательное; остальное DS. «Простр.» остаётся (Spaces = Phase 5 stub, не Tags).
- **C2 → chat-row default.** `useViewMode` default `chats`.
- **C3 → Skeleton без shimmer + sage-пульс.** Layout-плейсхолдеры статичные, AI-процессинг = пульс-точка `Pulse.tsx`.

### Исходная формулировка конфликтов (для истории)

### C1 — Навигация: 4 таба (DS) vs 5 (моя реализация)

- **DS reference_app:** `лента · поиск · теги · я` (4 таба). Active = sage-bg + label; idle = icon-only. **Нет центральной FAB в баре.** FAB — отдельный «cluster» (Pinterest-стек 44px кругов во frosted-pill).
- **Моя T4:** `Мысли · Поиск · +FAB · Простр. · Я` (5, тёмный FAB по центру).
- **Раньше юзер устно выбирал** 5 с центральным FAB. DS (locked) говорит 4 + отдельный FAB-cluster.
- **Вопрос:** следуем DS (4 таба + FAB-cluster) или оставляем 5 с центральным FAB?
- Также: «теги» вместо «Пространства» — Spaces (Phase 5) уходит, таб становится **Теги**. T11 (SpacesPage) → **TagsPage**.

### C2 — Default режим: chat-row (DS) vs feed (моя реализация)

- DS: «reference_app uses chat-row as **default**». Карточный режим — переключатель.
- Моя `useViewMode`: default `feed`.
- **Вопрос:** менять дефолт на `chats`?

### C3 — Loading: пульс-точка (DS) vs skeleton (моя реализация)

- DS: «**No spinners. No progress bars.** Single 8px sage dot pulsing 1.6s».
- Моя T7: `SkeletonFeed/SkeletonChats` с shimmer.
- Трактовка: skeleton как layout-плейсхолдер ≠ spinner, но DS явно против shimmer. Варианты: (а) полностью на пульс-точку, (б) skeleton без shimmer + пульс-точка для AI-процессинга, (в) оставить skeleton.
- **Вопрос:** какой вариант?

---

## 3. Скорректированный план

### Фаза R (Rework T1-T7 под locked DS) — перед T8

| ID | Задача | Beads |
|---|---|---|
| R1 | tokens.css = DS source of truth (✅ сделано) + удалить дубль-vars из styles.css | новый |
| R2 | Шрифты: Lora + JetBrains Mono в index.html `<link>`, font-display/mono в компоненты | новый |
| R3 | D3+D6: `translateY(1px)` вместо scale, `--shadow-glass`, 2 glass-рецепта | новый |
| R4 | D5: `--backdrop-gradient` на app-shell | новый |
| R5 | D7+D8: иконки 1.4-1.5 + Glyph-компонент (editorial italic) + EmptyState на глифах | новый |
| R6 | D9: tag-палитра 8 стопов | новый |
| R7 | D10+D11: карточка strong-glass 16/18/r18, chat-row avatar 46 + hairline + day-separator | новый |
| R8 | D4+C3: loading по решению C3 | новый |
| R9 | C1: навигация по решению (4/5 табов), C2: default режим | новый |

### Далее — T8-T14 как было (с учётом DS-токенов):
- T8 BottomSheet+ActionSheet, T9 RemindersSheet, T10 ReminderPicker, T11→**TagsPage** (вместо Spaces), T12 MoveTo (→Tags?), T13 QuickCreate (FAB-cluster по DS), T14 Search (strong-glass pill)

### Отложено (Phase 6+):
- T15 AI suggestion pager (proactive surfacing — Phase 6)
- T16 AI status rows (нужно при обработке — оценить приоритет)
- SMART-SPACES-MVP (Phase 5, отдельно)

---

## 4. Изменения в архитектуре (MINIAPP-ARCHITECTURE.md)

- `lib/types.ts`: добавить `font-display`/`mono` роли неактуально (CSS-only) — без изменений типов
- Новый компонент `components/ui/Glyph.tsx` (editorial italic-as-icon)
- Новый `components/ui/Pulse.tsx` (sage pulsing dot — замена spinner)
- Новый `components/ui/GlassTile.tsx` (light/strong glass wrapper)
- `IconType.tsx`: stroke 1.4-1.5, переэкспорт под DS icon-set
- Tag-палитра вынести в `lib/tagPalette.ts` (8 стопов, hash name→stop)
- `useViewMode` default — по решению C2
- BottomNav — по решению C1 (4 vs 5)
- `docs/design-system/` — reference, не билдить; `tokens.css`/`tokens.json` — единственное что импортируется в код

---

## 5. Что НЕ менять (подтверждено DS)
- HashRouter, retry-401, theme bridge, in-flight auth dedup
- adapters.ts / formatters.ts / types.ts логика
- ThoughtsPage data-flow (Promise.all bookmarks+upcoming)
- Backend (B1+B2 в main, контракты сошлись)
