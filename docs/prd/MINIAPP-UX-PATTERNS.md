# Mini App UX & Accessibility Patterns

**Источник:** `MINIAPP-REDESIGN.md` + WCAG 2.2 AA + Telegram Mini App constraints
**Автор:** a11y-architect agent
**Дата:** 2026-05-15
**Аудитория:** «впадлу делать заметки» → метрика успеха = ощущение лёгкости

---

## 1. Главный экран «Мысли»

### Скролл — virtualization + infinite scroll
- 49 сегодня → 500+ через год. **Pagination отбрасываем** — ломает «обзор накопленного».
- **Infinite scroll** батчами 20-30. Trigger — `IntersectionObserver` на «последнюю-минус-5» карточку.
- **Virtualization** (`react-window`/`virtua`) включать при N > 100. До этого обычный рендер. Fixed-size virtualization.
- **Сохранение скролл-позиции** при возврате из карточки (`sessionStorage` по route).

### Фильтры — sticky chip-row с auto-hide
- Один ряд chips высота 36–40px: `Все · ⭐ · 🔗 · 📄 · 🎤 · 💡 · # Теги →`
- Теги (десятки) — кнопка `# Теги` открывает bottom-sheet с multi-select.
- **Auto-hide при скролле вниз, return при скролле вверх**.
- Активный — filled+bold, неактивный — outlined.

### Поиск — отдельный таб
- Inline search-bar на главном НЕ нужен (90% — обзор).
- **Icon-button 🔍 (44x44)** в шапке справа — переход в таб «Поиск» с авто-фокусом.

### Pull-to-refresh — нет
- Mini App driven ботом → PTR создаёт false affordance.
- **Silent refresh** при `viewportChanged` + `visibilitychange`. Toast «+2 новые мысли» если есть новое.

---

## 2. Карточка — typography + spacing

### Typography (4 ступени)

| Элемент | Size | Weight | Color | Роль |
|---|---|---|---|---|
| Title | 15px | 600 | `--tg-text` | Primary, прыгает в глаз |
| Summary | 14px | 400 | `--tg-text` @ 70% | Secondary |
| Tags | 12px | 500 | `--tg-hint` | Tertiary monochrome |
| Date | 11px | 400 | `--tg-hint` @ 80% | Metadata |

Только title в фокусе — остальное растворяется.

### Spacing (база 4px)
- Между карточками: **8px**
- Padding: **12px вертикаль / 14px горизонталь**
- Title → summary: **2px** (читаются как один блок)
- Summary → tags: **6px**
- Высота карточки: **~88px** с summary, **64px** без

### Иерархия
**Прыгает:** title (contrast 7:1), ⭐ (yellow #FFB800), ⏰ reminder-tint (мягкий blue фон если ≤7 дней).
**Отступает:** summary, tags, date — greyscale. Иконка типа outline (lucide) 18px `--tg-hint`.

### Контраст (WCAG 2.2)
- Title: ≥ 7:1 (AAA)
- Summary: ≥ 4.5:1 (AA)
- Tags 12px: ≥ 4.5:1 — не светлее `#8E8E93` на белом

---

## 3. Long-press — Quick Actions

### Кастомный bottom-sheet (не native context menu)
- Native TG context menu не управляется → нельзя «В пространство → выбрать».
- **Решение:** slide-up sheet с 4 actions: 🗑 Удалить · ⭐ Избранное · ▦ В пространство · ⏰ Напомнить.
- Trigger: `touchstart` + 500ms timer + cancel при `touchmove >10px` или `touchend`. `HapticFeedback.impactOccurred('medium')` как сигнал.
- Close: swipe-down + tap outside + backdrop `rgba(0,0,0,0.4)`.

### Discoverability — fallback ОБЯЗАТЕЛЕН
- Long-press как единственный = **антипаттерн** (60% mobile-web юзеров не знают жест).
- **«⋯» icon справа на карточке** (24x24 visual, 44x44 hit). Тап → тот же sheet.
- Опционально: swipe-actions left=delete / right=star для продвинутых.
- **Первый запуск:** одноразовый coach-mark «Долгий тап = быстрые действия», dismiss-X, флаг в `localStorage`.

---

## 4. FAB «+»

### Позиция и размер
- **56x56**, `bottom: 80px`, `right: 16px`.
- Список: `padding-bottom: 96px` → последняя карточка видна.
- Тень: `0 4px 12px rgba(0,0,0,0.15)`, цвет = `--tg-button`.

### Поведение — inline bottom-sheet (40% высоты)
- `<textarea>` auto-grow, max 8 строк → scroll.
- Ряд: `📎 файл` (disabled MVP) · `🎤 голос` (disabled, tooltip «есть в боте»).
- **Telegram MainButton** «Сохранить» — нативный, неперекрываемый клавиатурой, theme-aware.

### Клавиатура
- Auto-focus textarea → keyboard сразу.
- Sheet height через `Telegram.WebApp.viewportStableHeight`, не `innerHeight`.

---

## 5. Колокольчик 🔔

### Положение в шапке
```
[Logo · "Мысли"]   ········   [🔍] [🔔] [⋮]
```
- 🔔 — второй справа, 44x44 hit, icon 24x24.

### Counter
- Red dot верх-право, 16x16, цифра 11px white. Show if N > 0.
- N > 9 → `9+`. N > 99 → `99+`.
- Появление: scale 0→1, 200ms ease-out, один раз при mount.

### Тап → bottom-sheet (60% высоты, не отдельный экран)
- Группы: «Сегодня · Завтра · На неделе».
- Тап на reminder = переход в карточку (sheet закрывается).
- Возврат одним свайпом, не теряет скролл «Мыслей».

---

## 6. Empty + Loading states

### Loading — skeleton, не spinner
- **Список:** 5–6 skeleton-карточек точно 88px, shimmer 1.5s.
- **Detail:** skeleton повторяет layout (title + 3 summary lines + tag row).
- **Spinner ТОЛЬКО** для inline-операций 300–800ms (save thought) — 16px в MainButton.

### Empty copy

| Контекст | Copy |
|---|---|
| Новый юзер, пусто | **«Пока пусто.»**<br>«Отправьте что-нибудь боту — ссылку, мысль, голосовое. Появится здесь.» |
| Фильтр = 0 | **«Ничего не нашлось.»**<br>«Попробуйте сбросить фильтры.» + кнопка «Сбросить» |
| Поиск пустой ввод | **«О чём подумать?»** placeholder |
| Поиск 0 результатов | **«Ничего похожего нет.»**<br>«Попробуйте другие слова или поищите по тегу.» |
| Пространства пусты | **«Пространства появятся сами.»**<br>«Когда накопится 10+ мыслей, бот предложит сгруппировать.» |

**Tone:** короткие фразы, точка в конце, без восклицаний/эмодзи. Один outline-icon 48px над текстом допустим.

---

## 7. Accessibility essentials

### Реально важно
1. **Контрасты** — tags никогда ниже **4.5:1**, UI-границы **3:1**.
2. **Touch targets ≥ 44x44** (Apple/TG строже WCAG). Spacing между ≥ 8px.
3. **Focus visible** — `:focus-visible` outline 2px `--tg-link`, offset 2px.
4. **`prefers-reduced-motion`** — отключать shimmer, scale-tap, slide-up (заменить на opacity-fade).
5. **Семантика:** `<button>` для действий, `<a>` для нав, `role="list"` + `role="listitem"`, `aria-label` на icon-only.
6. **Live regions:** toast — `role="status" aria-live="polite"`. Delete — `aria-live="assertive"` с Undo.
7. **Theme params:** `var(--tg-theme-text-color)` — не хардкодить цвета.

### TG WebView грабли (НЕ делать)
- ❌ `100vh` (включает зону под bottomNav). Использовать `Telegram.WebApp.viewportStableHeight`.
- ❌ Кастомная «назад» в шапке — есть нативный TG BackButton.
- ❌ `position: fixed` без `env(safe-area-inset-bottom)` (FAB прилипает к home-indicator).
- ❌ Tap-area меньше визуала — миссы 30%+.

---

## 8. Три паттерна для «лёгкости»

### Паттерн 1 — Воздух между, плотность внутри
8px между карточками (обзор быстрый), но title + summary внутри почти слипаются (2px) → читаются как **один блок**. Глаз скользит, не «парсит». Противоположность Notion с 16px+ между всем.

### Паттерн 2 — Один акцент, остальное greyscale
Из всей карточки **один** цветной элемент: либо ⭐ (yellow), либо ⏰ (blue tint). Никогда оба. Иконки/теги/дата — grey. Интерфейс не «кричит».

### Паттерн 3 — Микро-моушн, никакого «большого»
- Tap feedback: scale 0.97 80ms + haptic `light`.
- Sheet open: **200ms ease-out**, не 400ms.
- Toast slide-in 150ms, out 100ms.
- ❌ Stagger-анимации появления карточек (+400-800ms perceived wait).
- ❌ Parallax / scroll-driven (ломает 60fps на Android).

---

## Чек-лист «обязательно сделать»

1. Title 15px/600 @ 7:1, summary 14px/400 @ 70%, tags 12px/500 grey, date 11px grey.
2. Touch targets **44x44** для FAB, 🔔, 🔍, ⋮, chips. Зазор ≥ 8px.
3. Long-press 500ms + haptic `medium` → bottom-sheet с 4 actions **+ «⋯» fallback** на карточке.
4. FAB 56x56 / bottom 80 / right 16, список `padding-bottom: 96px`. Tap → sheet с textarea + Telegram MainButton.
5. Skeleton-loaders 88px, shimmer 1.5s. Spinner только inline в MainButton.
6. Биндить `Telegram.WebApp.BackButton`. Использовать `viewportStableHeight`.
7. `aria-label` на icon-only. `role="status" aria-live="polite"` для toast.
8. `prefers-reduced-motion` — отключать shimmer/slide-up.

## Чек-лист «не делать»

1. Цветные бейджи типов на карточке.
2. Pull-to-refresh для бот-driven контента.
3. Inline search bar на главном — 🔍 icon в шапке достаточно.
4. Spinner на загрузку списка — skeleton всегда.
5. Кастомная back-кнопка в шапке — есть нативная.
