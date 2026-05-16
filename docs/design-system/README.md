# BookmarkBrain · Design System Handoff

> **Status:** v1 locked direction (echo-sage + liquid glass + Onest/Lora). Implement these designs in your codebase using the codebase's framework — these HTML files are visual references, not code to copy directly.

## What this is

**BookmarkBrain** — an AI-powered second-memory tool. Capture flow lives in a Telegram bot; consumption lives in a **Telegram Mini App** and a native **iOS app** (Expo / React Native). AI auto-tags, summarizes, and surfaces relevant past saves proactively.

**UX north star:** as fast as Telegram Saved Messages — capture in one tap, AI runs in the background, zero clicks by default.

## About the design files

The HTML files in `references/` and `reference_app/` are **design prototypes built in HTML/CSS/React-Babel for fast iteration**. They show the intended look, feel, motion, and interaction patterns. **Recreate them in the target codebase's framework** (React for Mini App, Expo / React Native for iOS) using the codebase's existing component patterns. Lift values verbatim — not markup.

## Fidelity

**High-fidelity (hifi).** Colors, type scale, spacing, radii, shadows, and component anatomy are final. Copy exact hex values, `rgba()` strings, and pixel measurements. Motion timing / easing is locked.

## The locked direction

After exploration, the brand landed on:

| | |
|---|---|
| **Mood** | Liquid glass · editorial · paper-warm |
| **Brand color** | Sage `#7A9C7A` (the single accent — primary CTA, AI markers, active states) |
| **UI font** | **Onest** (Cyrillic-first grotesque, Google Fonts) |
| **Display font** | **Lora italic** (Cyrillic-native serif — for AI voice, summaries, empty-state, callouts) |
| **Mono** | **JetBrains Mono** (timestamps, kbd, hex, counters) |
| **Surface language** | Frosted glass tiles on `--backdrop-gradient` (sage + apricot + blush + cream) |

**References inspired the direction:** Sana AI (editorial italic), Telegram (chat density, link previews), Pinterest (masonry, FAB clusters), Replika (liquid glass on warm gradient), Perplexity (AI source chips), Matter / Blinkist (horizontal pager pattern).

## Repository layout

```
design_handoff/
├── README.md                       ← you are here
├── foundations/
│   ├── colors_and_type.css         ← single source of truth
│   ├── tokens.json                 ← same values, JSON for Expo/RN import
│   ├── logo.svg                    ← square mark, italic «э»
│   └── L6a-serif-italic.svg        ← legacy mark variant
├── references/
│   ├── 01-palette.html
│   ├── 02-typography.html
│   ├── 03-color-roles.html
│   ├── 04-tags.html
│   ├── 05-radii-elevation.html
│   ├── 06-spacing.html
│   ├── 07-buttons.html
│   ├── 08-bookmark-card.html       ← card view + chat-row view
│   ├── 09-ai-suggestion.html
│   ├── 10-ai-status.html           ← icon-only, NO emoji
│   ├── 11-search.html
│   ├── 12-icons.html               ← editorial glyphs + slim line system
│   ├── 13-brand-light.html         ← signature backdrop gradient
│   ├── logo.html
│   └── _card.css                   ← shared chrome for reference pages
└── reference_app/                  ← full Mini App / iOS prototype
    ├── index.html
    ├── MiniApp.jsx
    ├── Feed.jsx
    ├── ChatRow.jsx                 ← telegram-style row
    ├── BookmarkCard.jsx            ← detailed card variant
    ├── SuggestionCard.jsx          ← AI pager (header + horizontal snap)
    ├── Screens.jsx                 ← Search, Tags, Me
    ├── Atoms.jsx                   ← Icons, Glyph, TagChip, Pulse, GlassTile, SearchBar, EmptyState
    └── ios-frame.jsx               ← device chrome (visual context only — drop on real implementation)
```

## Design tokens

### Brand color (single accent)
```
--brand-primary:        #7A9C7A   /* sage — primary CTA, AI marker, active state */
--brand-primary-hover:  #688A68
--brand-primary-press:  #547654
--brand-primary-tint:   #E2EDE2   /* soft tint — AI suggestion bg, selection highlight */
```

### Surfaces (warm paper)
```
--bg-page:         #F5F1EB   /* page bg */
--bg-surface:      #FAF7F1   /* cards, inputs */
--bg-surface-elev: #FFFCF6   /* modals, popovers */
--bg-sunken:       #EAE3CF   /* wells, sunken backgrounds */
```

### Ink (warm off-black)
```
--fg-1: #2C2825   /* primary text, headings */
--fg-2: #6B645B   /* body, secondary */
--fg-3: #9A938A   /* metadata, hint */
--fg-4: #C5BFB4   /* placeholder, disabled */
--fg-on-brand: #FFFFFF
```

### AI (soft sage cast)
```
--ai-suggest-bg:     #ECF2EC
--ai-suggest-border: #CFDFCF
--ai-suggest-fg:     #2F4A2F
--ai-processing:     #7A9C7A   /* pulsing dot during AI work */
```

### Semantic
```
--success: #5A8A56
--warn:    #C49454
--error:   #B5483A
--info:    #5A7A8A
```

### Tag palette (8 stops, sage-anchored warm — never competes with brand)

| # | name | bg | fg |
|---|---|---|---|
| 1 | sage  | `#E2EDE2` | `#2F4A2F` |
| 2 | ochre | `#F4E6CC` | `#7A5828` |
| 3 | slate | `#D8E2EA` | `#3D5A6E` |
| 4 | plum  | `#E5D8E8` | `#5C3D6E` |
| 5 | clay  | `#EFD8D2` | `#8A2A20` |
| 6 | moss  | `#E0E5C8` | `#4A5A2A` |
| 7 | rose  | `#F4D8DC` | `#8A2A35` |
| 8 | taupe | `#E0DED8` | `#56544C` |

### Spacing (4px base)
```
1=4 · 2=8 · 3=12 · 4=16 · 5=20 · 6=24 · 8=32 · 10=40 · 12=48 · 16=64
```
- Mobile gutter: 16. Desktop: 24–32.
- Chat row gap: never below 8. Inside card padding: never above 16.

### Radii (liquid-glass scale — bigger and softer than Material/HIG defaults)
```
xs:  6   /* chips, tags */
sm:  10  /* inputs, small cards */
md:  16  /* bookmark card */
lg:  22  /* AI suggestion */
xl:  28  /* bottom sheets, hero tiles */
2xl: 36  /* huge marketing tiles */
pill: 999 /* buttons, search field, badges */
```

### Shadows (warm-tinted brown, never pure black)
```
--shadow-1:     0 1px 2px rgba(60,40,25,0.04), 0 1px 1px rgba(60,40,25,0.03)
--shadow-2:     0 4px 14px rgba(60,40,25,0.05), 0 1px 3px rgba(60,40,25,0.04)
--shadow-3:     0 14px 40px rgba(60,40,25,0.08), 0 4px 10px rgba(60,40,25,0.04)
--shadow-pop:   0 24px 60px rgba(60,40,25,0.14), 0 8px 20px rgba(60,40,25,0.06)
--shadow-glass: 0 1px 0 rgba(255,255,255,0.6) inset,
                0 -1px 0 rgba(0,0,0,0.04) inset,
                0 10px 30px rgba(60,40,25,0.08)
```

### Brand light — signature backdrop gradient

Reusable as page background, hero block, modal backdrop, marketing canvas. **Always layered as light source** — never inside a card, never inverted.

```css
--backdrop-gradient:
  radial-gradient(80% 60% at 12% 0%,   rgba(218,234,218,0.55) 0%, transparent 60%),  /* sage    */
  radial-gradient(70% 60% at 100% 12%, rgba(252,220,194,0.55) 0%, transparent 55%),  /* apricot */
  radial-gradient(60% 50% at 60% 100%, rgba(248,226,218,0.45) 0%, transparent 60%),  /* blush   */
  linear-gradient(180deg, #F5F1EB 0%, #F0EBE2 100%);                                 /* cream   */
```

### Liquid glass recipe

The signature surface treatment. Two strengths:

```css
/* light glass — tiles, list backgrounds */
background: rgba(255,252,246, 0.55);
backdrop-filter: blur(20px) saturate(140%);
border: 1px solid rgba(255,255,255,0.6);
box-shadow: var(--shadow-glass);

/* strong glass — search field, bottom tab bar, bookmark card */
background: rgba(255,252,246, 0.72);
backdrop-filter: blur(32px) saturate(160%);
border: 1px solid rgba(255,255,255,0.6);
box-shadow: var(--shadow-glass);
```

**iOS / RN:** use `expo-blur` `<BlurView intensity={50–80} tint="light">` for the same effect; tint via overlay with the same `rgba(255,252,246, 0.55)` and border.

### Motion
```
--ease-out:    cubic-bezier(0.2, 0.8, 0.2, 1)   /* default for everything */
--ease-in-out: cubic-bezier(0.4, 0, 0.2, 1)
--dur-fast:    120ms   /* tooltip, micro */
--dur-base:    200ms   /* default — hover, color */
--dur-slow:    320ms   /* sheets, transitions */
```
- Hover on card: `shadow-1 → shadow-2` + `translateY(-1px)`.
- Touch / press: `translateY(+1px)`. **No `scale()`**.
- AI processing: a single 8px sage dot pulsing 1.6s. **No spinners. No progress bars.**

## Typography

### Stack
```
font-ui:      "Onest", -apple-system, system-ui, sans-serif
font-display: "Lora", Georgia, serif
font-mono:    "JetBrains Mono", ui-monospace, monospace
```

Onest and Lora are Google Fonts. Both have **native Cyrillic** — that's why they were picked. Don't substitute with Inter / Source Serif 4 unless you self-host equivalents with Cyrillic.

### Scale (mobile-tight)

| role | size | weight | letter-spacing | line-height | family |
|---|---|---|---|---|---|
| display | 56 | 500 | −0.04em | 0.98 | Onest |
| h1 | 36 | 500 | −0.035em | 1.08 | Onest |
| h2 | 24 | 500 | −0.025em | 1.15 | Onest |
| h3 | 20 | 500 | −0.02em | 1.25 | Onest |
| h4 | 18 | 500 | −0.015em | 1.3 | Onest |
| body | 16 | 400 | −0.005em | 1.55 | Onest |
| body-sm | 15 | 400 | −0.005em | 1.5 | Onest |
| small | 13 | 400 | −0.003em | 1.45 | Onest |
| caps | 11 | 500 | 0.12em UPPERCASE | 1.4 | Onest *(eyebrows, status tabs)* |
| mono | 11–12 | 500 | 0.06em | 1.4 | JetBrains Mono *(timestamps, hex, counters)* |
| accent (italic) | 14–22 | 500 | 0 | 1.3–1.5 | **Lora italic** |
| callout (italic) | 32–36 | 500 | −0.005em | 1.1 | **Lora italic** |

### Rules
- **Sentence case** everywhere. No Title Case, no UPPERCASE on h1–h3.
- **Lora italic = AI voice, summary, empty-state, quote, callout.** Never UI labels. Never buttons.
- Weight 600 only for primary CTA and active tabs. Body always 400, headings 500.
- Caps live only in mono eyebrow and status pills.

## Iconography — editorial system

Two layers — `references/12-icons.html` is the canon.

### Editorial glyphs · italic-as-icon
Typographic glyphs rendered in Lora italic at large size. Used for emotion, state, content moments — empty-state, AI markers, navigation, dividers.

```
∅  empty            ✦  ai · spark        ★  favorite
¶  note             §  section           #  tag
@  mention          №  id                →  next
←  back             ↗  open external     ↺  recall · undo
«»  quote           —  divider            +  add
×  close · dismiss
```

Apply as: `font-family: var(--font-display); font-style: italic; font-weight: 500; color: var(--brand-primary);` Size 14–72 depending on context. Empty-state hero is 64–72 at 0.55 opacity.

### Slim line icons · custom 1.4-stroke SVG
For actions, objects, navigation. Custom shapes drawn to pair with Lora's organic feel — see `references/12-icons.html` for the set. Pulled from Lucide as a starting point, then re-stroked to 1.4 (Lucide default 2 is too heavy for Onest's weight).

```
bookmark · search · tag · archive · filter · collection
task · deadline · link · chart · brain · chat · plus · arrow
```

**Rules:**
- Stroke **1.4** at 22px, **1.5** at 14–20px.
- Color = `currentColor`. Tint via parent.
- Filled — only for active state. Never mix filled + stroke in one row.
- 16 / 20 / 24 / 32 sizes only.

### Critical: no emoji

**Emoji are forbidden anywhere in UI.** The 10-ai-status reference shows the canonical replacement — SVG icons in glass tiles with sage tint. This applies to:
- AI status lines (no 🤖 🔗 📊 — use SVG)
- Empty states (no 😔 — use `∅` glyph)
- Buttons (no 🔍 — use slim-line search)
- Notifications, badges, anywhere

## Components

Each component is documented in its reference HTML file. Below is the implementation summary — exact values come from the reference + tokens.

### Bookmark — two display modes

The product has **one bookmark source, two display modes** the user can toggle:

#### Mode 1 — Card (`references/08-bookmark-card.html`)
Liquid-glass tile. Title (Onest 500, 15.5px). AI summary in italic Lora 14. Source / time / favorite in mono caps 11. Tags row at bottom.

```
padding: 16px 18px
radius: 18px
background: rgba(255,252,246, 0.72) + blur(20) saturate(160)
border: 1px solid rgba(255,255,255,0.6)
shadow: shadow-glass
hover: translateY(-1px), shadow-3
```

Variants: article (default), task (with progress bar), Telegram link-preview (with left sage 3px accent + 64px thumbnail), Pinterest masonry (full-bleed gradient thumbnails, 3:4 / 3:5 aspect), archived (opacity 0.65, no shadow).

#### Mode 2 — Chat row (`references/08-bookmark-card.html` → "Chat view" section, reference_app uses this as default)

Telegram-style dense row. Avatar 46px + name + time + italic preview + badge/star/pulsing-dot.

```
padding: 10px 16px (no card wrapper — rows sit on backdrop directly)
gap: 12px
border-bottom: 0.5px solid var(--border-1)  (hairline between rows, except last)
```

Avatar variants:
- `letter` — gradient circle (sage / honey / slate / plum / clay / moss tones)
- `brain` — white circle with Lora italic `✦` glyph at 24px
- `task` — sage outline + checkbox icon
- `archive` — dashed `--border-strong`, faded color

Preview line: `<src>` mono prefix (gray) + italic Lora preview text. Trailing: badge (sage pill with count) / `★` glyph / pulsing 7px dot / `✓` for done.

Unread indicator: 3×22 sage bar absolute-positioned left of avatar.

Day separator: pill-shape `04 12 padding`, sunken bg `rgba(234,227,207,0.7)` + blur(8), mono caps 10 «вчера», centered.

### AI suggestion pager (`references/09-ai-suggestion.html` + `reference_app/SuggestionCard.jsx`)

The hero AI pattern. **Section header + horizontal snap-scroll**, like Houzz / Riot / Perplexity feed sections.

**Section header**
- Eyebrow «подсказки» in Onest UI caps 11 (`color: var(--ai-suggest-fg)`, letter-spacing .12em)
- Dots pagination right: active = pill 14×5, others = circle 5×5, gap 5
- No close button on header

**Carousel**
- Cards 86% width (`minWidth: 280, maxWidth: 340`)
- Gap 10, `scroll-snap-type: x mandatory`, `scroll-snap-align: start`
- `scroll-padding-left: 16` to align with rail
- Next card peeks ~14% on the right → swipe affordance is visible

**Card anatomy**
- Background: linear-gradient(160deg, `rgba(226,237,226,0.88)` → `rgba(207,223,207,0.75)`) + blur 20 saturate 160
- Border `1px solid rgba(207,223,207,0.7)`, radius 22, padding `18 18 16`
- Sage halo: absolute 220×220 radial-gradient `rgba(122,156,122,0.18)` at top-right `-50% / -25%`
- Headline: italic Lora 500 / 19px / line-height 1.25 / letter-spacing −0.005em
- **Source chips** below headline — see anatomy below
- Footer: mono caps 10.5 meta on left («3 ссылки» / «recall» / «связать?») + 34px arrow button right

**Source chip** (Perplexity pattern)
```
display: inline-flex; gap: 6; padding: 3 10 3 3;
borderRadius: 999;
background: rgba(255,252,246, 0.7) + blur(10)
border: 1px solid rgba(255,255,255,0.65)
```
Contents: 18px gradient mini-avatar with letter + mono 10.5 domain. Show up to 3 chips, then `+N` pill.

### Buttons (`references/07-buttons.html`)

All buttons are **pill** (`border-radius: 999`).

- **Primary** — sage bg, white text, padding `11 20`, font 13.5/500. Shadow `0 1px 0 rgba(255,255,255,0.2) inset, 0 4px 12px rgba(122,156,122,0.25)`.
- **Glass** (secondary) — `rgba(255,252,246, 0.7)` + blur(16) + glass border + glass shadow.
- **Ghost** — transparent, `--fg-2`, hover `rgba(255,252,246, 0.5)`.
- **Danger** — transparent, `#B5483A`, hover `rgba(181,72,58,0.08)`.
- **AI** — `--ai-suggest-bg` + `--ai-suggest-fg`, leading Lora-italic `✦` 16px in sage.
- **Icon-only** — 40px circle, glass treatment. Solid variant: sage bg.
- **FAB cluster** — Pinterest-style vertical stack of 44px circles inside a frosted pill container. Primary FAB on top in sage.

### Search field (`references/11-search.html`)

Telegram-style pill. Strong glass treatment.

```
padding: 13px 18px
borderRadius: 999
background: rgba(255,252,246, 0.72) + blur(20) saturate(160)
border: 1px solid rgba(255,255,255,0.6) [unfocused]
       1px solid var(--brand-primary) [focused]
```

Focused state: add `box-shadow: 0 0 0 4px rgba(122,156,122,0.18)` outer ring.

Placeholder is Lora italic 15 in `--fg-3`.

Leading icon: slim-line magnifier 18 in `--fg-3`. Trailing: voice icon idle / `×` clear when has-value.

### Empty states (`references/11-search.html`, `12-icons.html`)

Hero Lora-italic glyph at 64–72px / opacity 0.55 / sage color. Below: Onest 17/500 head + Lora-italic 14 copy in `--fg-3`. Centered. Padding 36–48 vertical.

Glyph choice:
- `∅` — search returned nothing
- `?` — pre-query state, prompt for input
- `★` — empty favorites
- `¶` — empty notes / collection

### AI status (`references/10-ai-status.html`)

Bot progress as **SVG icon rows in glass tiles**. Each step: 28px icon container + text + mono timestamp. Done state turns the row sage (`#E2EDE2 bg + #CFDFCF border`).

The icons (in order, all SVG, never emoji):
1. **Link** — paperclip / external-arrow
2. **Brain** (animated rotate) — dashed circle with center dot
3. **Chart** — bar chart icon
4. **Tag** — tag icon with dot
5. **Check** — bold checkmark, sage bg circle

Badges: mono pills with leading 6px dot. `pending` (gray, static), `processing` (ochre `#F4E6CC` bg + sage pulsing dot), `completed` (sage), `failed` (clay).

### Bottom tab bar (`reference_app/MiniApp.jsx`)

Floating frosted pill, **not** an edge-attached bar.

```
position: absolute; left: 12; right: 12; bottom: 24;
borderRadius: 999;
background: rgba(255,252,246, 0.7) + blur(28) saturate(180)
border: 1px solid rgba(255,255,255,0.7)
shadow: glass + 0 16px 40px rgba(60,40,25,0.12)
padding: 8
```

Tab states:
- **Idle** — icon-only, `--fg-3`, transparent bg, 12 padding.
- **Active** — sage bg + white text + label visible, `8 16` padding, primary shadow.

Tabs: лента (feed) / поиск (search) / теги (tags) / я (me).

## Anti-patterns / what NOT to do

Pulled from extensive iteration. These will get flagged:

- ❌ **Emoji in UI.** Anywhere. Period. Use SVG icons or editorial glyphs.
- ❌ **Pure `#000` / `#FFF`.** Use `--fg-1` / `--bg-surface-elev`.
- ❌ **Cold gradients.** No purple, no cobalt, no neon. Stay in cream + sage + apricot + blush.
- ❌ **Left-color-accent borders on cards** (e.g. blue 4px left border). Use background tint instead.
- ❌ **Heavy 2px-stroke icons.** Use 1.4–1.5 stroke. Lucide-default 2 is too heavy.
- ❌ **Spinners / progress bars.** Use the single sage pulsing dot.
- ❌ **`scale()` on press.** Use `translateY(1px)` instead.
- ❌ **UPPERCASE on h1–h3.** Only on mono eyebrow / status caps.
- ❌ **Title Case.** Sentence-case only.
- ❌ **Drop-shadow with pure black.** Always warm-tinted `rgba(60,40,25,…)`.
- ❌ **Layered backdrop-gradient inside a card.** Brand light is page-level only.
- ❌ **Generic stock photography.** Use real user content (link previews, masonry from saved pins) or skip imagery.
- ❌ **Long sentences in italic.** Lora italic at >2 lines becomes hard to read. Keep ≤32ch.

## Content & tone

**Voice:** the user writing to themselves. Bot is invisible assistant, not a PR voice. **No** «Привет! 👋 Я твой умный ассистент…». Тёплый, краткий, на «ты».

**Casing:** Sentence case в UI. Кириллические заголовки — без капса.

**Microcopy examples (good):**
- ✅ «Сохранено · #34»
- ✅ «Ты сохранял про *X* — вот связанное»
- ✅ «3 закладки на эту тему — собрать в коллекцию?»
- ✅ «Не открывал 30 дней — в архив?»
- ❌ «🎉 Отлично! Я успешно сохранил…»

**AI initiative:** наблюдение → лёгкий вопрос. Не приказ, не восклицание.

## Implementation notes (React / RN)

### Mini App (web)
- React 18+ with Vite or Next.
- Pull CSS variables from `colors_and_type.css` — keep this file as your `tokens.css`.
- Use `backdrop-filter` directly. Safari 17+ supports it; fall back to opaque `--bg-surface` for older browsers.
- Onest + Lora via `<link>` to Google Fonts, or self-host woff2.
- Telegram theme bridge — already handled by `[data-tg-bridge="true"]` rules in `colors_and_type.css`.

### iOS (Expo / React Native)
- Use **`expo-blur`** for liquid glass. `<BlurView intensity={60} tint="light">` ≈ blur(20). For strong tiles use `intensity={85}`.
- Tokens in `tokens.json` — write a thin TS layer that exposes them as `theme.color.brand.primary`, `theme.radius.lg`, etc.
- Fonts: `expo-font` loading Onest + Lora.
- **Don't** use NativeWind unless your team prefers it — direct StyleSheet is faster to keep in sync with tokens.
- For the chat list view, `FlashList` with `estimatedItemSize={76}` is ideal.
- The signature backdrop gradient: layer 3 `<LinearGradient>` + 3 `<View>` with radial-ish gradient hacks. Or use a single PNG export at 2× / 3× — gradient is static, baking it is fine.

### What's NOT pixel-perfect
- The `ios-frame.jsx` in `reference_app/` is a **visual harness** to show the design inside an iPhone. Don't reimplement it — use real iOS chrome / Telegram Mini App SDK.
- The `BookmarkCard.jsx` and `ChatRow.jsx` use inline styles for speed of iteration. Translate to your StyleSheet / styled-components / Tailwind setup — values stay identical.

## Assets

- `foundations/logo.svg` — square mark. Italic «э» (Lora) in sage on cream.
- `foundations/L6a-serif-italic.svg` — legacy mark variant. Keep for now, ask before deleting.
- No raster images, no stock photography in v1. Pinterest tiles in `08-bookmark-card.html` use CSS linear-gradients as thumbnail placeholders — in production, lift the actual image from the saved URL.

## Open questions for the dev

1. **Telegram Mini App SDK** — which version? The status bar / safe areas treatment depends on it.
2. **iOS minimum** — iOS 15+? `backdrop-filter` / `expo-blur` work fine from 13+ but liquid glass really sings on 16+.
3. **Icon export format** — keep slim-line SVG inline, or generate an icon font? My recommendation: inline SVG components.
4. **Telegram bot UI** — there's a `ui_kits/telegram_bot/` in the source project that's *not* in this handoff (focused this package on the apps). Ask if you need it.
5. **Dark mode** — partially scaffolded in `colors_and_type.css` (`[data-theme="echo-dark"]`) but not refined. Will need a second pass once light mode ships.

## How to read the references

Each `references/NN-name.html` is a single page documenting one part of the system. Open them locally — they reference `../foundations/colors_and_type.css` and the shared `_card.css`. Update the relative paths if you move them.

The `reference_app/` is a working React prototype — open `index.html` in a browser and you'll see all four screens with tab navigation, including the chat-list / cards toggle on the feed.
