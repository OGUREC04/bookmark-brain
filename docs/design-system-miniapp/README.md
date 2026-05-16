# Handoff · BookmarkBrain Mini App

Что это, как это собрано, и как из этого сделать прод-код в Expo / React Native.

---

## TL;DR — что отправить Claude Code

Скачай эту папку как zip и закинь её в Claude Code (или подключи как контекст). Скажи ему:

> Реализуй экраны и шторки 1:1 в нашем Expo / React Native + Telegram WebApp проекте. Возьми токены из `tokens.json` и `ds/colors_and_type.css`, поведение и анатомию — из `BRIEF.md`, верстку и состояния — из HTML-референса `BookmarkBrain Mini App.html` (открой его в браузере, чтобы увидеть 13 артбордов). JSX-компоненты в `app/` и `ds/` — **референс**, не код для копи-пасты; перепиши их на твою кодовую базу (NativeWind / styled-components / RN StyleSheet — что у тебя в проекте). Liquid-glass на native — `expo-blur` (`BlurView intensity={32} tint="light"`), на web — `backdrop-filter: blur()`.

---

## 1. Что в этой папке

```
design_handoff_miniapp/
├── README.md                       ← ты тут
├── BRIEF.md                        ← исходный продуктовый бриф (IA, копирайт, состояния)
├── tokens.json                     ← дизайн-токены (цвета/шрифты/радиусы/тени) для Expo
├── BookmarkBrain Mini App.html     ← открой в браузере → весь референс на одном холсте
├── design-canvas.jsx               ← скаффолд холста (можно игнорить в проде)
├── ds/                             ← фундамент DS — токены + базовые компоненты-референсы
│   ├── colors_and_type.css         ← CSS-vars (источник правды для web)
│   ├── ios-frame.jsx               ← рамка iPhone (только для презентации, не часть UI)
│   ├── Atoms.jsx                   ← Icons, Glyph, TagChip, SearchBar, EmptyState, GlassTile
│   ├── ChatRow.jsx                 ← плотная строка списка для chat-mode
│   ├── BookmarkCard.jsx            ← карточка закладки для cards-mode
│   └── SuggestionCard.jsx          ← AI-suggestion + SuggestionPager (гориз. snap)
└── app/                            ← наша IA, надстройка над ds/
    ├── Mysli.jsx                   ← Экран 1 «Мысли»: chips, bell, suggestion pager, list/cards
    ├── Search.jsx                  ← Экран 2: search + AI-summary + результаты
    ├── Spaces.jsx                  ← Экран 3: grid 2 кол. + «создать»
    ├── Me.jsx                      ← Экран 4: профиль + 3 группы настроек
    ├── Sheets.jsx                  ← 5 шторок: Action, Reminders, ReminderPicker, MoveToSpace, QuickCreate
    ├── Nav.jsx                     ← BottomNav (3 таба + центральный FAB)
    ├── Icons.jsx                   ← дополненный набор Lucide-style иконок
    ├── PhoneFrame.jsx              ← обёртка-хост (status bar spacer + nav)
    └── Canvas.jsx                  ← раскладка холста (13 артбордов)
```

---

## 2. О природе этих файлов

**Эти HTML/JSX файлы — дизайн-референс, не прод-код.**

Они нарисованы на React + plain inline styles ради максимальной скорости и редактируемости в браузере. В прод-коде ты будешь использовать:

- **Mini App (web)** — твой текущий React + Telegram WebApp SDK + любая ваша система стилей (CSS modules, vanilla-extract, styled-components, NativeWind для unified). CSS vars из `ds/colors_and_type.css` копируй прямо.
- **iOS (Expo / React Native)** — те же React-компоненты по форме, но `View`/`Text` вместо `div`/`span`, `StyleSheet.create` или NativeWind вместо inline styles, `expo-blur` вместо `backdrop-filter`, `react-native-svg` для иконок.

Логика, иерархия компонентов и анатомия экранов **переносятся 1:1**. Только примитивы меняются.

---

## 3. Fidelity

**High-fidelity (hifi).** Все размеры, отступы, цвета, типографика, состояния — финальные. Воспроизводи pixel-perfect. Единственные плейсхолдеры:

- Аватарка профиля в `Me.jsx` — латинская буква в градиентном круге, замени на реальную из Telegram WebApp `initData.user`.
- `seedBookmarks` / `seedSpaces` / реминдеры — это демо-данные. Структура полей — как в `ds/BookmarkCard.jsx` (`{id, title, summary, url, tags, time, ai_status, is_favorite, content_type, task_progress}`).

---

## 4. Информационная архитектура — отличия от DS reference

DS-референс (`ds/`) показывает 4 экрана: лента / поиск / теги / я. Наша IA:

| DS reference | Наша IA | Что отличается |
|---|---|---|
| «лента» | **«мысли»** | + sticky `FilterChipsRow` (Все · ★ · Задачи · Голос); + `ReminderBell` (sage pill с countʼом) в шапке справа; `SuggestionPager` остаётся, показывается **только в chat-mode** и **только при `filter === 'all'`**, dismissable. |
| таб «поиск» | **убран** | Вход в поиск — тап по `SearchBar` в шапке Мыслей. |
| «теги» | **«пространства»** | Не плоский список, а grid 2 кол. с glyph-плитками. Smart Spaces (Phase 5) — те же плитки + AI-маркер. |
| «я» | «я» | Профиль + статы + 3 группы настроек (приватность / вид / данные). Без эмодзи. |
| BottomTab (4 равные ячейки) | **BottomNav (3 таба + центральный FAB)** | FAB — sage primary круг 54px, всегда по центру, открывает `QuickCreateSheet`. Idle-таб = только иконка; active = sage-pill с подписью. |

---

## 5. Экраны — поэкранно

### Экран 1 — «Мысли» (главный)  ·  `app/Mysli.jsx`

**Назначение:** домашний лента-экран. Поток всего, что сохранено, плюс AI-подсказки сверху и быстрые фильтры.

**Структура сверху вниз:**

1. **Header** (`padding: 0 16px; margin-bottom: 14px`):
   - `h1` «мысли» · Onest 32 / 500 / -0.035em / lh 1, sentence-case, рядом sage italic «·» (Lora 500, -0.01em)
   - справа в group (`gap: 8px`): `ReminderBell` (sage-tint pill, clock-icon + mono count), затем mono-counter `347` (JetBrains Mono 11, color `--fg-3`, letter-spacing .06em)
2. **SearchBar** (`SearchBar` из `ds/Atoms.jsx`) — strong glass pill, Lora-italic placeholder «найти в памяти…», slim-line `search` + `voice` иконки 18px. Тап → переход на экран 2.
3. **ViewToggle + день**: слева glass-pill сегмент `chat / cards` (default `chat`), справа mono-caps `сегодня` (10px, .12em).
4. **`FilterChipsRow`** — **sticky** (`position: sticky; top: 0; z-index: 4`), горизонтальный скролл (`overflow-x: auto`), фон `linear-gradient(180deg, rgba(247,243,233,.92), rgba(247,243,233,0))` + `backdrop-filter: blur(8px)`. Чипы:
   - `все` (text)
   - `★` (только глиф, Lora italic 13px)
   - `задачи` (text)
   - `голос` (text)
   - Active: bg = `--brand-primary`, fg = `--fg-on-brand`, без border. Idle: rgba(255,252,246,.55) glass, border rgba(255,255,255,.6).
5. **`SuggestionPager`** (из `ds/SuggestionCard.jsx`) — eyebrow mono-caps `подсказки`, dots-пагинация. Карточки 86% ширины, gap 10px, snap-x mandatory. **Только в chat-mode + filter=all**, dismissable (× в правом верхнем).
6. **Контент списка** — в зависимости от toggle:
   - **chat-mode** → `<FilteredChatView>` из `app/Mysli.jsx`. Рендерит массив строк через `<ChatRow>` + `<DaySeparator>`. Структура строки см. ниже.
   - **cards-mode** → `<FilteredCardsView>` через `<BookmarkCard>` (16px gutter).

**Чип-фильтрация** — в `FilteredChatView` каждая строка имеет `types: string[]`, фильтр оставляет тех, у кого `types.includes(filter)` (или `kind === 'sep'`). Если результат пустой → `<EmptyState glyph="∅" head="ничего по этому фильтру" copy="сбрось чипы">`.

**ChatRow анатомия** (`ds/ChatRow.jsx`):
- 10px вертикальный паддинг, 16px горизонтальный, gap 12
- Avatar 46px (gradient + letter / brain `✦` / task outline + check icon / archive dashed + archive icon / generic icon)
- Body: верхняя строка `name Onest 14.5/500/-0.01em` (truncate) + `time JetBrains Mono 11 / .04em` (или `--brand-primary` если `timeNow`)
- Нижняя строка: preview Lora-italic 13.5 (с inline `<b>` highlights в Onest 500), опциональный mono `src` префикс 11px (.04em) перед preview, опциональный check-iconик для done, hairline bottom-border `0.5px var(--border-1)` (кроме последней)
- Trailing: `badge` (sage pill mono 11) / `★` (Lora italic 15) / `Pulse` (8px sage пульсация — НЕ спиннер)
- Unread → `3×22 sage-bar` слева

**BookmarkCard анатомия** (`ds/BookmarkCard.jsx`):
- Glass tile: `rgba(255,252,246,.72)` + `blur(20px) saturate(160%)` + border `rgba(255,255,255,.6)` + radius 18 + padding 16/18 + shadow `--shadow-glass`
- Hover: `translateY(-1px)` + усиленная тень
- Title Onest 15.5/500/-0.02em/lh 1.25
- Summary Lora-italic 14/lh 1.4
- Task progress: mono 10.5 «1/3 готово» + дедлайн справа + 3px sage progress bar
- Meta row: mono 10.5 / .06em — url (Onest 500) · dot · time · опциональный `ai…` с amber Pulse · опциональный ★
- Tags: `TagChip` 8-stop палитра, размер `sm`

**Состояния:**
- Loading: статичные glass-плейсхолдеры + sage `Pulse`. **Никакого shimmer и спиннеров.**
- Empty (нет данных): `<EmptyState glyph="¶" head="…" copy="…">`
- Empty (фильтр пуст): `<EmptyState glyph="∅" …>`

### Экран 2 — Поиск  ·  `app/Search.jsx`

- Сверху: круглая glass-кнопка-back 36px (для web; в native — `Telegram.WebApp.BackButton`) + h2 «поиск» Onest 22.
- `SearchBar` в focused-состоянии (sage-ring `0 0 0 4px rgba(122,156,122,.18)` + border `--brand-primary`).
- При непустом query: ряд **FacetPill** (все · ai · статьи · за неделю) с активным sage-pill.
- AI-summary блок (только если есть результаты): sage-tint linear-gradient, eyebrow mono-caps `✦ ОТВЕТ ПО СОХРАНЁННОМУ`, ответ Lora-italic 14.5, source-chips ниже (Perplexity-стиль — letter avatar + mono domain в glass-pill).
- Результаты: `<SearchResult>` — карточка вроде BookmarkCard, но с подсветкой `<mark>` (`bg: --brand-primary-tint, color: --brand-primary-press, radius 5`).
- Empty: glyph `?` для пустого ввода, `∅` для нулевого результата.

### Экран 3 — Пространства  ·  `app/Spaces.jsx`

- Header: «пространства» + sage «·», под ним Lora-italic подсказка `N пространств · AI собирает похожее само`.
- `display: grid; grid-template-columns: 1fr 1fr; gap: 10px`.
- **SpaceTile** 130px min-height, radius 22, glass:
  - **icon plate** 38×38 r12 — градиент по `tone` (sage/honey/slate/plum/clay/moss), внутри либо `Glyph` (Lora italic), либо иконка (mic для голосовых, task для задач)
  - Body внизу: имя Onest 14.5/500 + опциональный mono-caps `AI` бэйдж (sage-tint pill 9px) для Smart Spaces, mono `N закладок` 10.5/.06em
- **CreateSpaceTile** — dashed border, glass-plate с `+`, Lora-italic подпись `или дай AI собрать`.

### Экран 4 — Я  ·  `app/Me.jsx`

- Header: «я» + sage «·»
- **Profile card** glass r22 — 60px sage gradient круг (буква Lora italic), справа `@username` Onest 16 + mono `347 закладок · с янв 2024`
- **Stats row** — `grid 3`, каждая ячейка glass r16: число Lora italic 28 в `--brand-primary`, mono-caps подпись
- **3 SettingsGroup** — каждая с mono-caps eyebrow (`приватность / вид / данные`), glass r22, ряды 14px паддинг + `var(--border-1)` divider, правая колонка mono 11 (значения) или Onest 14 «→» (actions). Последний row `выйти` — `danger: true` → color `--semantic-error`.

### Нав  ·  `app/Nav.jsx`

- Floating pill, `position: absolute; left: 14; right: 14; bottom: 24`
- `background: rgba(255,252,246,.75)` + `backdrop-filter: blur(28px) saturate(180%)` + border `rgba(255,255,255,.7)` + radius 999
- 3 таба (`мысли / пространства / я`):
  - Idle: только иконка 18px sw 1.6, color `--fg-3`, background transparent
  - Active: sage-pill (bg `--brand-primary`, fg `--fg-on-brand`), padding 8/14, иконка + подпись Onest 12.5/500
- **FAB** — отдельный круг 54px справа от pill (в реальной верстке это абсолютно позиционированный круг внутри той же flex-строки). Sage primary, `+` иконка sw 2. На press `translateY(1px)`.

### Шторки (Sheets)  ·  `app/Sheets.jsx`

Все — `<BottomSheet>` обёртка:
- Overlay: `rgba(28,22,18,.32)` + `blur(2px)`, click → dismiss
- Sheet: `rgba(255,252,246,.92)` + `blur(32px) saturate(160%)`, radius top 28, slide-up animation `320ms var(--ease-out)`
- Handle bar: 38×4 r999 `--border-strong`, центр, top padding 6+10

| Sheet | Триггер | Содержимое |
|---|---|---|
| `ActionSheet` | long-press на BookmarkCard / ChatRow | mini-context (что трогаем) + 4 строки: напомнить (clock) · в избранное (★) · в пространство (folder) · удалить (trash, danger). Иконка-плитка 34×34 r10 sand-tint, заголовок Onest 15/500, опциональный subtitle Lora-italic 12.5. |
| `RemindersSheet` | тап по `ReminderBell` | `SheetTitle "напоминания"` + 3 группы (сегодня/завтра/на неделе) с mono-caps лейблами в sage. ReminderRow = ChatRow-lite (avatar 38 + name + sage mono time + Lora-italic preview), trailing 2 ghost-кнопки (snooze clock + cancel ×). |
| `ReminderPickerSheet` | из ActionSheet → «напомнить» | mini-context + 5 radio-style строк (сегодня вечером · завтра утром · на выходные · через неделю · выбрать дату…). Активная: sage-tint bg, sage radio с check-glyph. Снизу — emulated `TelegramMainButton`. |
| `MoveToSpaceSheet` | из ActionSheet → «в пространство» | Список пространств (32×32 sage gradient plate + glyph, имя Onest 14.5, mono count, ✓ для выбранного, sage-tint bg для активной). Dashed-кнопка `создать пространство` внизу. |
| `QuickCreateSheet` | тап по FAB | SheetTitle «новая мысль» + glass textarea с Lora-italic placeholder + пульсирующий sage-курсор. Ниже disabled-кнопки 📎/🎤 (есть в боте, не в Mini App) и `TelegramMainButton "сохранить"` (disabled пока пусто). |

---

## 6. Дизайн-токены

См. `tokens.json` (плоский) и `ds/colors_and_type.css` (CSS vars, источник правды). Бренд = direction **`echo`** (sage-anchored). Здесь только то, что реально используется в этих экранах:

### Цвета
```
brand-primary:        #7A9C7A  (sage — единственный акцент)
brand-primary-press:  #5C7A5C
brand-primary-tint:   rgba(122,156,122,.14)
fg-on-brand:          #FFFFFF
fg-1:                 #1F1B17  (primary text)
fg-2:                 #4A4239  (secondary)
fg-3:                 #7C7167  (tertiary, metadata)
fg-4:                 #B8AE9E  (quaternary, separators)
bg-page:              cream (см. backdrop-gradient ниже)
border-1:             rgba(60,40,25,.06)  (hairline)
border-2:             rgba(60,40,25,.10)
border-strong:        #C9C0AC
backdrop-gradient:    paper cream + sage + apricot + blush радиальные (см. CSS)
ai-suggest-fg:        #4A6648  (sage darker, для eyebrow mono-caps)
```

Tag palette (только для `TagChip`, не для акцентов):
```
1 sage   #E2EDE2 / #2F4A2F     5 clay   #EFD8D2 / #8A2A20
2 ochre  #F4E6CC / #7A5828     6 moss   #E0E5C8 / #4A5A2A
3 slate  #D8E2EA / #3D5A6E     7 rose   #F4D8DC / #8A2A35
4 plum   #E5D8E8 / #5C3D6E     8 taupe  #E0DED8 / #56544C
```

Avatar gradients (используются в ChatRow + SpaceTile + SourceChip):
```
sage:  linear-gradient(135deg, #8FA888, #4A6648)
honey: linear-gradient(135deg, #DAC8B0, #B8946A)
slate: linear-gradient(135deg, #9BB0BE, #4F6A7A)
plum:  linear-gradient(135deg, #B5A8C0, #6E5A80)
clay:  linear-gradient(135deg, #D9907F, #A04934)
moss:  linear-gradient(135deg, #B0C28E, #6E8444)
```

### Типографика

| Роль | Шрифт | Размер / вес / трекинг |
|---|---|---|
| UI primary | **Onest** | 500 default; 14.5 для list name; 15.5 для card title; 32/-0.035em для h1 |
| Display / accent | **Lora italic** | 400/500; 13.5–14 для previews; 18–22 для suggestion headline; 28+ для editorial-glyph числа |
| Mono | **JetBrains Mono** | 10–11 для time / count / src-prefix / mono-caps eyebrow (с `.06em` или `.12em`) |

Все три — Google Fonts (см. `ds/colors_and_type.css`). На native — через `expo-font` или `@expo-google-fonts/onest`, `/lora`, `/jetbrains-mono`.

**Правила:** sentence-case везде. CAPS — только в mono eyebrow labels (10–11px, .08–.14em letter-spacing). **Никакого Title Case**. **Никаких эмодзи в UI** (только в bot status line, которой нет в Mini App).

### Радиусы / spacing / тени

```
radius-xs:   6   (тэги)
radius-sm:   10  (inputs, мелкие чипы)
radius-md:   16  (карточки)
radius-lg:   22  (AI suggestions, space tiles)
radius-xl:   28  (sheets, hero tiles)
radius-pill: 999

space-1..16: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64

shadow-glass: 0 1px 0 rgba(255,255,255,.6) inset,
              0 -1px 0 rgba(0,0,0,.04) inset,
              0 10px 30px rgba(60,40,25,.08)
shadow-pop:   0 24px 60px rgba(60,40,25,.14), 0 8px 20px rgba(60,40,25,.06)
```

### Анимация

```
ease-out:   cubic-bezier(0.2, 0.8, 0.2, 1)   ← все переходы
dur-fast:   120ms    (chip / button state)
dur-base:   220ms    (hover, view-toggle)
dur-slow:   320ms    (sheet slide-up)
```

- **Без bounces, без scale, без spinner-кругов.** Press → `translateY(1px)`. Hover → `translateY(-1px)` + усиление тени.
- AI-обработка → `Pulse` (sage кружок, opacity 1→.35→1, 1.6s loop).

---

## 7. Liquid Glass — рецепт

Везде один и тот же recipe:

**Web / Mini App:**
```css
background: rgba(255, 252, 246, 0.72);
backdrop-filter: blur(20px) saturate(160%);
-webkit-backdrop-filter: blur(20px) saturate(160%);
border: 1px solid rgba(255, 255, 255, 0.6);
box-shadow: 0 1px 0 rgba(255,255,255,.6) inset,
            0 -1px 0 rgba(0,0,0,.04) inset,
            0 10px 30px rgba(60,40,25,.08);
```

Сила blur'а:
- **regular**: 20px / saturate 140% / opacity 0.55 (default карточки)
- **strong**: 32px / saturate 160% / opacity 0.72–0.92 (search bar, sheets, top-level cards)

**React Native:**
```jsx
import { BlurView } from 'expo-blur';

<BlurView intensity={32} tint="light" style={{ borderRadius: 18, overflow: 'hidden' }}>
  <View style={{ backgroundColor: 'rgba(255,252,246,0.55)' }}>
    {children}
  </View>
</BlurView>
```
- `intensity` ≈ blur px / 1.2 (т.е. 24 для regular, 38 для strong)
- На Android `expo-blur` работает хуже — fallback на solid `rgba(255,252,246,0.92)`.

---

## 8. Иконки

**Library:** Lucide (1.5px stroke, 24px box).
- Web: `lucide-react`
- Native: `lucide-react-native` (тот же API)

Кастомные пути в `ds/Atoms.jsx` (`Icons`) и `app/Icons.jsx` (`ExtraIcons`) — реальные Lucide-эквиваленты:

| Наш ключ | Lucide |
|---|---|
| `search` / `feed` / `cards` | `Search` / `List` / `Columns2` |
| `task` | `CheckSquare` |
| `archive` | `Archive` |
| `mic` / `voice` | `Mic` |
| `bell` / `clock` | `Bell` / `Clock` |
| `folder` | `Folder` |
| `trash` | `Trash2` |
| `plus` / `arrow` / `back` / `close` | `Plus` / `ArrowRight` / `ArrowLeft` / `X` |
| `user` | `User` |
| `paperclip` / `send` | `Paperclip` / `Send` |
| `thoughts` | `MessageCircle` (для таба «мысли») |
| `spaces` | `LayoutGrid` |

Filled-варианты — **только для active states** (selected tab, favorited bookmark). Default — outline.

**Editorial glyphs** — это не иконки, а Lora-italic символы: `✦ ★ ¶ ∅ ? § ℘ ∞` — рендерь их через `<Text style={{ fontFamily: 'Lora-Italic', fontStyle: 'italic' }}>{ch}</Text>` (см. `Glyph` в Atoms).

---

## 9. Состояние и данные

```ts
type Bookmark = {
  id: string;
  title: string;
  summary?: string | null;
  url: string;
  time: string;             // pre-formatted ('14:32' | 'вчера' | '11 мес')
  tags?: { name: string; color: 1|2|3|4|5|6|7|8 }[];
  ai_status: 'processing' | 'completed';
  is_favorite?: boolean;
  content_type?: 'task' | 'voice' | 'link';
  task_progress?: { done: number; total: number };
};

type Space = {
  id: string;
  name: string;
  count: number;
  glyph?: string;           // editorial glyph для иконки
  icon?: 'voice' | 'task';  // или Lucide-иконка
  tone: 'sage'|'honey'|'slate'|'plum'|'clay'|'moss';
  smart?: boolean;          // Phase 5 AI Smart Space
};

type Reminder = {
  id: string;
  bookmark_id: string;
  due_at: string;           // ISO
  group: 'today' | 'tomorrow' | 'week';
};
```

Все данные приходят от бэка/бота. Mini App запрашивает по тапу на таб; иконки тегов и тонов — детерминированный хеш name → color на бэке.

---

## 10. Чек-лист «что НЕ делать» (из брифа)

- ❌ Эмодзи в UI (только в bot status line, её здесь нет)
- ❌ Холодные цвета, чистый #000 / #fff
- ❌ Spinner / progress-bar в loading-состояниях
- ❌ `scale()` на press, длинные анимации, bounce
- ❌ Левый цветной бордер карточки
- ❌ Title Case / UPPERCASE на h1–h3
- ❌ iOS-frame в проде (он только в `BookmarkBrain Mini App.html` для презентации)
- ❌ Spinners — везде `Pulse` (один пульсирующий sage кружок)

---

## 11. Если что-то не сходится

Открой `BookmarkBrain Mini App.html` в браузере — это **источник правды для верстки**. Все 13 артбордов на одном холсте; можно фокус-режимом раскрывать каждый на полный экран, замерять, копировать стили из DevTools.

Если возникает вопрос «как должно вести себя X» — пиши в проектный чат, мы решим вместе и обновим этот хэндофф.
