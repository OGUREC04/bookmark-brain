# BookmarkBrain — Design System

> **Status:** v1, working draft. Three identity directions in parallel for the user to react to. Tokens, components, and UI kits are wired so direction-swap is a single attribute flip.

## What this product is
**BookmarkBrain** (working name — alternatives below) is an AI-powered second-memory tool. A Telegram bot catches forwarded messages, links, notes; AI auto-tags, summarizes, and surfaces relevant past saves proactively. Search lives across a bot, a Telegram Mini App, and a native iOS app (Expo / React Native — single codebase for the latter two).

**UX north star:** as fast as Telegram Saved Messages — capture in one tap, AI runs in the background, zero clicks by default. Anything that adds friction is an antipattern.

**Differentiation:** proactivity. Не «склад со ссылками», а напоминалка: «ты сохранял про X — вот связанное, что забыл».

## Sources used
- Brief pasted into the project chat (no codebase, no Figma attached). The user explicitly invited 2–3 directions, not a single final.
- Bot handle reference: `@N0teeBot`
- Mood references mentioned by the user: **Sana AI**, **Sana Education**, **Claude.ai** (palette + serif accents)

> No production codebase or Figma file was provided. Components in `ui_kits/` are mocked from the brief, **not** lifted from real code. When you have either, please attach so we can swap in the real visual vocabulary.

## Three directions on the table

| | A · **Заметка** | B · **Эхо** | C · **Mycel** |
|---|---|---|---|
| **Mood** | Paper + ink, warmest | Quiet, ambient, mossy | Connected memory, bolder |
| **Accent** | Terracotta `#C8643C` | Muted ochre `#8A6E3F` | Wine `#7A2E3F` + honey `#C49454` |
| **Surface** | `#FAF6F0` cream | `#F4F2EC` warm-gray | `#F6F0E4` deeper cream |
| **Type** | Inter + Source Serif 4 | IBM Plex Sans + Mono | Manrope + Fraunces |
| **Closest to brief?** | Most "Claude-like" | Most "Sana-like" | Most differentiated |

Switch direction with `data-theme="zametka" | "echo" | "mycel"` (and `*-dark` for dark mode) on `<body>`. All tokens swap; components don't change.

## Naming options
| Name | Pitch |
|---|---|
| **Заметка** | Кириллица-first; humble, paper-feel; works as Telegram username `@zametka_bot`. |
| **Эхо** | Что вернулось из прошлого — ровно то, что делает AI. Короче, проще, дороже звучит. |
| **Mycel** | Латиница; mycelium = подземная связная память. Технологичнее, более "AI-нативно". |
| **Полка** | Личная полка для всего, что ты сохранил. RU-only вибы. |
| **Recall** | Английский, конкретный глагол; описывает proactive surface. |
| **Otklik / Отклик** | Близко к Эхо, но активнее (response, not reflection). |
| **N0tee** *(текущее)* | Если хочется сохранить рабочее имя — не обыгрываем "brain", фокус на "note". |

## Repository index
- `colors_and_type.css` — all three theme tokens + shared spacing/radii/elevation/motion + Telegram theming bridge
- `assets/` — logos (square + wordmark) for each direction
- `preview/` — design-system cards (palettes, type, components, AI suggestion, search, etc.)
- `ui_kits/telegram_bot/` — bot chat with clean-chat patterns + proactive message
- `ui_kits/mini_app/` — Mini App / iOS feed, card, search, suggestion (theme-switchable)
- `tokens.json` — design tokens, ready to import into Expo
- `SKILL.md` — agent skill descriptor (works in Claude Code)

## Content fundamentals (copy & tone)

**Голос:** ты пишешь сам себе. Бот — невидимый помощник, не PR-менеджер. Никаких "Привет! 👋 Я твой умный ассистент…". Тон **тёплый, краткий, на «ты»**.

**Кейсинг:** **Sentence case** везде в UI. Заголовки на кириллице — без капса, без Title Case. CAPS — только для tiny eyebrow-меток (`BRAIN SUGGESTS`, статусы), и тогда `letter-spacing: .08em`.

**Микрокопия — примеры:**
- ✅ «Сохранено · #34» (краткое подтверждение, в edit статуса)
- ✅ «Ты сохранял про *X* — вот связанное, что забыл»
- ✅ «3 закладки на эту тему — собрать в коллекцию?»
- ✅ «Не открывал 30 дней — в архив?»
- ❌ «🎉 Отлично! Я успешно сохранил твою закладку и проанализировал её содержимое!»

**Эмодзи:** только в **bot status line** (🔗→🤖→📊→🏷→✅) — там они визуальная грамматика прогресса. Везде ещё — нет. Тег без эмодзи, кнопка без эмодзи, заголовок без эмодзи.

**AI-инициатива:** всегда в формате *наблюдение → лёгкий вопрос*. Не приказ, не восклицание. Финальная строка в proactive-сообщении: «Это редкое сообщение. Можно отключить.»

**RU/EN:** RU primary. UI пережит длинные русские слова — все строки тестируем на «Уведомления о просроченных задачах».

## Visual foundations

**Surface philosophy:** paper, not glass. Warm off-whites with a subtle paper-grain feel (no neon, no glassmorphism, no pure `#FFF`/`#000`). Borders are thin and warm-tinted (`var(--border-1)` is hairline; `--border-2` is card edge). Dividers preferred over heavy section breaks.

**Color usage:**
- `--bg-page` — page background (cream)
- `--bg-surface` — cards, inputs (slightly lighter than page)
- `--bg-surface-elev` — modals, popovers (white)
- `--bg-sunken` — subtle wells (search facets, kbd hint)
- One brand accent **only** for primary CTA, AI markers, and active states. Tags use a **separate warm-leaning palette** (8 stops) so they never compete with the accent.

**Typography:** sans for UI; serif/display for **accents only** — section titles, summary previews, italic AI reasoning. Following Claude's pattern: serif as a deliberate seasoning, not a vibe.

**Imagery vibe:** none in v1. If we add later → warm, low-contrast, slightly grainy. No stock corporate photography, no AI-generated abstract art.

**Backgrounds:** flat fills. **No gradients** outside of `border-image` micro-effects. **No textures** except an optional very-subtle paper grain on dark mode (`<10%` opacity noise). **No full-bleed images** in v1.

**Borders & cards:** `1px solid var(--border-1)` + `border-radius: 12px` is the bookmark card. `16px` for AI suggestions (the slightly softer corner reads as "advice, not directive"). No left-color-accent borders (anti-pattern flagged in brief).

**Shadows:** warm + soft. `--shadow-1` is hairline, `--shadow-2` is card hover, `--shadow-3` is modal lift. Always tinted brown (`rgba(60,40,25,...)`), never pure black — gives the paper feel.

**Animation:** all motion `cubic-bezier(0.2, 0.8, 0.2, 1)` (`--ease-out`). Durations 120/200/320ms. Bookmarks fade-in-up 4px on appearance. **No bounces.** **No long animations.** Subtle and instant — supports the "as fast as Saved Messages" mandate. AI processing: a *single* gently pulsing dot, not a spinner.

**Hover states:** lift shadow 1→2 + 1px translate-up on cards. **Touch:** invert (1px translate-down) — nothing scales. Buttons: hover darkens primary 8%, press darkens 16%.

**Borders/blur:** Frosted blur on bottom tab bar only (`backdrop-filter: blur(20px)` + `var(--bg-surface)/0.85`). Everywhere else opaque.

**Layout:** 4px grid, 16px gutters in mobile, 24–32px in desktop. Lists never go below 8px row gap (chat density). Cards never above 16px internal padding.

**Corner radii:** xs 4 (chips), sm 8 (inputs), md 12 (cards), lg 16 (AI suggestion), xl 24 (sheets).

## Iconography

**Library:** **Lucide** (1.5px stroke, 24px box). Reasons: open license, full coverage of our entity vocabulary, clean line style that pairs with paper surfaces, has React + RN bindings (`lucide-react`, `lucide-react-native` — same set across Mini App and iOS).

**Usage rules:**
- Always 1.5px stroke (not 2 — too heavy for our type weight).
- 16/20/24px sizes only.
- Color = `currentColor` always; tinted via the parent `color` prop.
- Filled variants only for *active states* (selected tab, favorited bookmark) — never as the default.

**Substitution flag:** No icon font from a real codebase to copy in. Lucide is the agent's pick. If the user already has a favorite (Heroicons, Phosphor, custom set), we'll swap.

**Emoji policy:** confined to bot status line (🔗 🤖 📊 🏷 ✅) and the brief's UX expectation. Nowhere else in UI.

**Logo:** SVGs in `assets/`. v1 marks are simple geometric placeholders to communicate the *direction*, not finals. Per direction A/B/C: square 64px master + horizontal wordmark.

## Tokens
See `tokens.json`. CSS vars in `colors_and_type.css` are the source of truth; tokens.json mirrors them for Expo / RN consumption.

## Caveats / open questions
1. **No real codebase or Figma was attached** — components are designed from the brief, not lifted. To get pixel parity, attach repo or Figma.
2. **Logos are direction-defining placeholders.** Ready to do proper marks (multiple variants per direction, light/dark/mono, App Store icon set) once you pick a direction.
3. **Fonts are Google Fonts** (Inter, Source Serif 4, IBM Plex, Manrope, Fraunces). All have Cyrillic but Fraunces' Cyrillic is more limited — flagged for Mycel direction.
4. **Iconography is Lucide via assumption.** If you prefer a different family, easy to swap.
5. **Telegram bot card** is mocked in HTML/React — not a real bot screenshot. The pattern (status emoji line, edit-in-place, inline buttons, proactive template) is what matters.
