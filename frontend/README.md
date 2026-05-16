# BookmarkBrain — Mini App (frontend)

Telegram Mini App для BookmarkBrain. React 18 + TypeScript + Vite 6.
Открывается ботом `@bookmarkbrain_dev_bot` (dev) через ngrok.

> Для нового разработчика: прочитай этот файл целиком перед правками —
> здесь зафиксированы 4 неочевидных архитектурных решения, которые легко
> сломать по незнанию.

---

## TL;DR архитектура

```
main.tsx              bootstrap: тема (locked light), затем <App/>
  └─ App.tsx          STATE-DRIVEN оболочка (без роутера):
                       tab | searchOpen | detail | sheet | toast
                       оркестрирует экраны, шиты, BackButton, мутации
       ├─ screens/*    экран = «провод» между DS-компонентами и API
       │   └─ components/ds/*   1:1 порт залоченного дизайн-системы
       └─ lib/*        api · adapters · types · formatters · telegram
```

Слои строго однонаправленные: `screens → ds → (нет)`, `screens → lib → api`.
`components/ds/*` НИКОГДА не импортирует `lib/` или `screens/` — только
примитивные пропсы. `lib/adapters.ts` — единственный шов backend↔UI.

---

## 4 решения, которые нельзя ломать по незнанию

### 1. Навигация — state-driven, роутера НЕТ (намеренно)

`react-router` удалён. Навигация = `useState` в `App.tsx`
(`tab`, `searchOpen`, `detail`, `sheet`). Причина: Telegram WebView плохо
живёт с history API на iOS; DS — это один «кадр» + bottom-sheets, а не
многостраничный сайт. Telegram `BackButton` подключён вручную в `App.tsx`
(закрывает sheet → detail → search по приоритету).

**Не добавляй `<Routes>`/`<Link>`.** Новый экран = новая ветка в
state-машине `App.tsx` + (если нужен оверлей) разновидность `Sheet`.

### 2. `components/ds/*` — залоченный 1:1 порт ДС

Источник истины: `docs/design-system-miniapp/` (хэндоф-эталон, есть
HTML-холст `BookmarkBrain Mini App.html`). Эти компоненты портированы
**один-в-один**, со **встроенными inline-стилями** — это НАМЕРЕННО, а не
техдолг. CSS-переменные берутся из `src/styles/tokens.css` (вендорный
файл ДС).

**Не рефактори inline-стили в CSS-классы. Не «причёсывай» эти файлы.**
Меняешь визуал → сначала меняешь эталон в `docs/design-system-miniapp/`,
потом переносишь сюда. Каждый файл в шапке указывает свой источник.

`DetailScreen.tsx` — единственный экран без артборда в ДС (его там нет);
собран из ДС-токенов/атомов, помечен соответствующим комментарием.

### 3. Бренд залочен (sage), тема Telegram НЕ инжектится

ДС — фиксированная «бумажно-тёплая» светлая тема, акцент sage `#7A9C7A`.
`lib/telegram.ts → applyTheme()` жёстко ставит `data-theme="echo"`,
светлую схему, и **не пробрасывает** `--tg-theme-*`. Тёмная тема и
Telegram-мост удалены: их синий `button_color` несколько раз ломал бренд
в синий, а тёмный фон убивал перф на `backdrop-filter`.

**Не возвращай tg-theme bridge.** Если бренд снова синий — грузится
старый бандл из кэша Telegram (полностью закрой Mini App, не refresh).

### 4. Adapter — единственный шов backend↔UI

Бэкенд отдаёт `Bookmark` (см. `lib/api.ts`). UI-компоненты НЕ знают про
`Bookmark`. Всё преобразование — в `lib/adapters.ts`:

| Функция | Назначение |
|---|---|
| `deriveKind` / `deriveTaskProgress` | визуальный тип (порядок проверок важен — см. комментарий) |
| `bookmarkToChatRow` | `Bookmark` → пропсы `ChatRow` (chat-вид) |
| `bookmarkToCard` | `Bookmark` → пропсы `BookmarkCard` (cards-вид) |
| `bookmarkToThought` | legacy UI-модель (проверь, не мёртвая ли) |
| `matchesFilter` | фильтр-чипы (все/★/задачи/голос) |
| `targetOf` / `groupReminders` | контекст ActionSheet / группировка RemindersSheet |
| `hostOf` | `https://www.x.com/a` → `x.com` |

**Маппинг не размазывать по экранам.** Новое поле бэка → правка только
здесь.

---

## Структура

```
src/
  main.tsx                bootstrap (тема → render)
  App.tsx                 state-driven shell + оркестрация шитов/мутаций
  screens/
    Mysli.tsx             лента: header+bell+counter, SearchBar,
                           ViewToggle chat/cards, FilterChips,
                           SuggestionPager (демо-данные), реальный API
    SearchScreen.tsx      /search + AI-summary + результаты
    SpacesScreen.tsx      /folders грид 2 кол.
    MeScreen.tsx          /users/me профиль + статы + настройки
    DetailScreen.tsx      открытая заметка (нет в ДС — из токенов)
  components/ds/           ЗАЛОЧЕННЫЙ 1:1 порт ДС (inline-стили намеренны)
    Nav · Sheets · ChatRow · BookmarkCard · SuggestionPager
    atoms · icons
  lib/
    api.ts                fetch + JWT (retry-on-401, AuthExpiredError)
    adapters.ts           ЕДИНСТВЕННЫЙ шов Bookmark→UI
    types.ts formatters.ts tagPalette.ts telegram.ts
  styles/
    tokens.css            вендорный файл ДС (НЕ редактировать вручную)
    layout.css            анимации/keyframes приложения
```

## Взаимодействия

- **Открыть заметку:** тап по карточке/строке → `App.detail` → `DetailScreen`.
- **Действия:** иконка «⋯» на строке/карточке (НЕ long-press —
  `onContextMenu` не работает на тач) → `ActionSheet` → reminder/star/
  move/delete. Мутации идут через `runAction()` (единая обработка ошибок:
  успех/ошибка → haptic, шит не зависает молча).
- **«В разработке»:** действия без бэка вызывают `comingSoon()` → toast.
  Полный список — bd `bookmark-brain-ntn` (UI cleanup перед след. фазой).

## Запуск

Стек поднимается из корня репозитория — см. `.claude/STARTUP.md`
(6 сервисов: docker postgres+redis, backend, worker, bot, vite, ngrok).
Фронт отдельно: `npm run dev` (Vite :3000). Прод-сборка: `npm run build`
(`tsc` строгий + vite). `tsc` падает на любой ошибке типов — это gate.

## Известный техдолг

См. bd `bookmark-brain-ntn`. Крупное: рекомендованный рефактор —
вынести повторяющиеся `runAction(async () => { await api…; closeSheet();
reload(); })` в `App.tsx` в хук `useSheetActions(closeSheet, reload)`
(точка роста файла; полноценный SheetContext НЕ нужен — union достаточно
для MVP).
