# BookmarkBrain Mini App — design brief (для DS-тулзы)

> **Цель:** сгенерировать hifi-референс экранов Mini App, объединяющих
> **locked DS v1** (визуальный язык) с **нашей продуктовой IA**
> (фильтры, reminders, FAB, наполнение). Ниже — что отрисовать.
> Источник визуала: уже существующий `design_handoff/` (foundations +
> reference_app). Не менять токены/палитру/типографику — только
> скомпоновать наши экраны в этом языке.

## Бренд-инварианты (НЕ менять)
- Sage `#7A9C7A` — единственный акцент (locked, не адаптировать под Telegram-тему).
- Фон — `--backdrop-gradient` (cream+sage+apricot+blush), page-level.
- Onest (UI) · Lora italic (AI summary/preview/empty/callout) · JetBrains Mono (время/счётчики/src).
- Liquid-glass (2 силы), shadow-glass, радиусы DS, motion DS (translateY не scale, пульс не спиннер).
- Иконки slim-line 1.4–1.5, editorial-глифы Lora-italic. **Эмодзи запрещены.**

---

## ЭКРАН 1 — «Мысли» (главный, бывш. DS «лента»)

Структура сверху вниз (порядок и стиль — из DS `Feed.jsx`, наполнение — наше):

1. **Шапка:** `Мысли` (Onest 32/500, -0.035em, sentence-case) + sage italic «·» (Lora). Справа — mono-счётчик всего закладок (как DS «347»).
2. **Search-bar** (DS `Atoms.jsx SearchBar`, strong-glass pill, Lora-italic placeholder «найти в памяти…», slim-line лупа + voice-иконка). **Тап → экран поиска** (таб «Поиск» из нав убран — вход в поиск только отсюда).
3. **Ряд управления:**
   - Слева: **chat/cards toggle** (DS `ViewToggle` — glass-pill сегмент, наш default = `chat`).
   - Справа: mono-caps «СЕГОДНЯ» (как DS).
4. **Фильтр-чипы (НАША IA, DS-стиль):** pill-чипы `Все · ⭐ · Задачи · Голос`. Активный — sage-pill (как DS active tab); неактивный — glass/transparent. Под рядом управления, горизонтальный скролл, sticky.
5. **Reminders-колокольчик (НАША IA):** DS-стиль pill `[clock-glyph · N]` в sage-tint. Место — в шапке справа рядом со счётчиком ИЛИ в ряду управления. Тап → RemindersSheet.
6. **AI-suggestion pager (ЗАГЛУШКА, демо-данные):** DS `SuggestionPager` (eyebrow «ПОДСКАЗКИ» mono-caps, dots-пагинация, горизонтальный snap, карточки 86% ширины, sage-halo, Lora-italic заголовок, source-chips Perplexity-стиль, footer mono + 34px arrow). Показывать только в `chat`-режиме, dismissable. Демо-карточки как в DS reference (3 шт.).
7. **Контент:**
   - **chat-режим** (default): `ChatRow` список (avatar 46 gradient по тону / brain ✦ / task-outline / archive-dashed; name Onest 14.5/500; time mono 11; preview Lora-italic 13.5 + mono `src`-префикс; trailing badge sage-pill / ★ glyph / pulse / ✓; unread 3×22 sage-bar; hairline 0.5px между; **DaySeparator** pill «вчера»/«сегодня» sunken-glass).
   - **cards-режим:** `BookmarkCard` список (strong-glass r18 p16/18; title Onest 15.5/500; summary Lora-italic 14; task progress-bar; meta mono 10.5 url·dot·time·ai-pulse·★; tag-chips 8-stop).
8. **Состояния:** loading — статичные glass-плейсхолдеры + sage-pulse (НЕ shimmer/spinner). Empty — Lora-italic глиф 72px opacity .55 (`¶` пусто / `∅` фильтр-0) + Onest 17/500 head + Lora-italic copy.

---

## ЭКРАН 2 — Поиск (открывается из search-bar)

DS `Screens.jsx` SearchView: тот же strong-glass search-bar (фокус — sage-ring), под ним — состояние:
- Пустой ввод: глиф `?` + «о чём подумать?».
- Есть результаты: `ChatRow`/`BookmarkCard` (тот же режим что в ленте) + AI-summary блок (Lora-italic, sage-tint, с source-chips). 0 результатов: глиф `∅`.
- Назад — нативный Telegram BackButton (без кастомной кнопки в шапке).

---

## ЭКРАН 3 — Пространства (наш таб, бывш. DS «теги»)

Наша IA: пространства (папки + будущие Smart Spaces, Phase 5). DS-стиль:
- Шапка `Пространства` (Onest 32/500 + sage «·»).
- Grid 2 кол.: glass-плитки (light glass r22), внутри: editorial-глиф/иконка типа, имя Onest 500, mono-счётчик закладок. «+ создать» — glass-плитка с `+` глифом.
- Пусто: глиф `¶` + «пространства появятся сами».

---

## ЭКРАН 4 — Я (профиль/настройки)

DS `Screens.jsx` MeView-стиль: аватар (gradient-letter 64), имя Onest, mono-счётчик «N закладок». Список настроек glass-плитками (тихий режим, таймзона, тема). Минимум, без эмодзи.

---

## НАВИГАЦИЯ — bottom (наша IA, DS-стиль, FAB центр)

DS `MiniApp.jsx BottomTab` контейнер (frosted-pill r999, blur28 sat180, border white .7, shadow DS, плавающий, отступ снизу ДОСТАТОЧНЫЙ — не прилипать к краю, +safe-area). **«Поиск» убран** (вход в поиск из search-bar). Ячейки:
`Мысли · [+ FAB центр] · Пространства · Я` (3 таба + центральный FAB).
- Idle-таб: **только иконка**, `--fg-3`, transparent.
- Active-таб: **sage-pill** (sage bg + white + подпись), padding 8/16, DS shadow.
- FAB центр: sage primary круг 46, DS shadow, translateY на press.

---

## SHEETS (T8–T13, DS-стиль) — отрисовать анатомию

Все — DS `BottomSheet` (overlay `--bg-overlay`, slide-up 320ms ease-out, handle-bar, radius xl 28, strong-glass, swipe-down dismiss):
- **ActionSheet** (long-press карточки): 4 строки-glyph действия — Удалить (danger) / ⭐ Избранное / В пространство / ⏰ Напомнить. + «⋯» fallback на карточке.
- **RemindersSheet** (колокольчик): группы «Сегодня/Завтра/На неделе», строки = ChatRow-lite + snooze/cancel (glass/ghost кнопки DS).
- **ReminderPickerSheet:** быстрые слоты (сегодня 18:00 / завтра 9:00 / +неделя / custom) — pill-кнопки DS.
- **MoveToSpaceSheet:** список пространств glass-строками + «создать».
- **QuickCreateSheet** (FAB+): textarea auto-grow (Lora-italic placeholder), Telegram MainButton «Сохранить», disabled-иконки 📎/🎤 (есть в боте).

---

## Что НЕ рисовать
- Эмодзи где-либо (только slim-line SVG / editorial-глифы).
- Холодные цвета, чистый #000/#fff, spinner/progress-bar, scale-press, левый цветной бордер карточки, Title Case, UPPERCASE на h1–h3.
- iOS-frame (это контекст-харнесс, не часть UI).

## Выход от тулзы
Hifi-референс (HTML/JSX как в существующем reference_app) экранов 1–4 + nav + 5 sheets, в DS-языке, с нашей IA. Пришлёшь → реализую 1:1 в React.
