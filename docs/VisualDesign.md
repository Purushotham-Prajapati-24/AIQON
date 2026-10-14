# Visual Design — CASCADE Dashboard

> **Status (2026-10-13):** concept and as-built record for the React dashboard in `dashboard/`. Items marked **Shipped** are in the code on this branch and were verified in a browser (§9). Items marked **Deferred** are recommendations with the reason they are not built yet.
>
> **Scope:** the visual system, components, layout, interaction and accessibility of the dashboard. Model behaviour, API and data are out of scope (see [`Design.md`](Design.md) and [`Architecture.md`](Architecture.md)).

---

## 0. Premise

**A chart room for people who move freight: dark, exact and calm, with one signal colour reserved for lateness and the evidence always next to the claim.**

"Premium" here means three things, in this order:

1. **Precision.** Tabular numerals, a strict type hierarchy, hairline rules and measured contrast. Nothing is approximate.
2. **Depth through restraint.** A small set of layered surfaces, film grain and nautical contours on the two cinematic screens (sign-in and hero), and plain, quiet operational screens.
3. **A few signature interactions done perfectly.** The delay-cascade replay, the ⌘K command palette, the pointer spotlight, numbers that roll to their new value, and focus that always lands where the user expects.

The trap to avoid is mistaking effects for quality. An ops planner scanning 48 shipments at 8 a.m. is slowed down by particle fields, aurora backgrounds and cursor trails. Effects are allowed only where the user is watching, not working.

---

## 1. Research findings

### Method and evidence quality

The five reference platforms were researched on 2026-10-13. The build container could not resolve the reference domains (`getaddrinfo ENOTFOUND` for sanity.io, ui.shadcn.com, reactbits.dev and 21st.dev), so findings come from web search over official documentation and secondary sources. Each claim below is graded:

- **Official:** confirmed on the vendor's own docs or site.
- **Secondary:** from mirrors, directories or community write-ups. Check before relying on exact prop names.

### Summary by platform

| Platform | What it is | What we take | What we reject | Evidence |
|---|---|---|---|---|
| **Sanity UI** | React component library for Sanity Studio. Design-token theming with strict TypeScript typing. One shipped theme (`studioTheme`); custom themes via `ThemeProvider` / `buildTheme()`. | **Semantic tones** (primary, positive, caution, critical) as the vocabulary for status colour. **Accessibility as a design constraint, not a retrofit**: focus rings are themed and treated as useful to everyone, and Dialog and MenuButton follow WAI-ARIA patterns. | Its Studio look and its layout primitives (`Box`, `Flex`, `Stack`, `Grid`). Tailwind already covers layout here, and a second primitive layer would duplicate it. | Official (motivation, theme docs); Secondary (tone list via a docs mirror; version history) |
| **shadcn/ui** | Open-code components copied into your repo; Tailwind v4 with `@theme` / `@theme inline` and CSS variables. Ships Command, Sidebar, Sonner, Chart and more. | **Token discipline**: one CSS variable per role, mapped into Tailwind with `@theme inline`. This dashboard already did this, which confirms the approach. **Command (⌘K)**: shadcn's is a styled wrapper around `cmdk`. **Sidebar as its own token family** (`--sidebar-*`). **Sonner** for toasts (Deferred, §7). | Adopting the kit wholesale. The default shadcn look can feel generic, and Radix as a runtime dependency is not needed for the four overlays this app has. | Official (Tailwind v4 page, Command docs); Secondary (token names, sidebar tokens) |
| **React Bits** | Free collection of animated React components: text animations, animations, components and backgrounds. Most are CSS-only. Some backgrounds (Particles, Plasma) use WebGL. | **CountUp-style numbers** (the existing `Ticker`). The **spotlight card** pattern, implemented the cheap way: pointer position written to CSS variables, no React state. | WebGL backgrounds (Aurora, Plasma, Particles): GPU cost on long-lived ops tabs, distraction, and no information. Cursor trails and click sparks: noise in a work tool. | Secondary (catalogue size varies 60–110+ across snapshots; the WebGL note comes from a 2026 guide) |
| **21st.dev** | Community registry of shadcn-compatible React + Tailwind components, installed with `npx shadcn@latest add "https://21st.dev/r/…"`. | A **sourcing channel** for well-known patterns (spotlight cards, heroes, pricing), always restyled to our tokens (checklist in §8.3). | Using it as a design direction. Pulling components unedited gives a collage of other people's visual languages. | Secondary |
| **Magic MCP (21st.dev)** | An MCP server, in beta, that generates components from a `/ui <description>` prompt using the 21st.dev library. Needs an API key. | A **prototyping aid** for exploring layouts quickly. | Production use without review. Generated code arrives with its own colours and spacing, and it is beta. Any output must pass the same checklist as hand-written code. | Secondary |


### What the research changes

1. **Keep the existing token architecture.** CSS variables mapped through `@theme inline` is what shadcn now recommends for Tailwind v4, and it was already in place. Extend it; don't replace it.
2. **Name status colours by meaning.** `critical / caution / positive` are now aliases for `late / risk / ok`, so new components speak the same language as Sanity UI and shadcn-derived code.
3. **Add a command palette.** It is the single most valuable pattern from this list for a data product: every shipment, port and section is one keystroke away.
4. **Use motion components selectively.** Take CountUp and spotlight; reject backgrounds and cursor effects (§0).

---

## 2. Component set

| Component | Role | Pattern source | Status | File |
|---|---|---|---|---|
| **Sidebar rail** | Primary navigation. Collapses to icons, becomes a drawer below 1024 px. Holds search, sections, Start tag, tips, theme and sign-out. | shadcn Sidebar | Shipped | `components/Nav.tsx` |
| **Command palette** | ⌘K / Ctrl K / `/`. Jump to a section, open any shipment by ID, port or lane, or run an action (theme, tips, sign out). | shadcn Command (`cmdk` behaviour), built in-house | **Shipped (new)** | `components/CommandPalette.tsx` |
| **Search trigger** | Field-styled button at the top of the sidebar that shows its shortcut; a magnifier icon on the mobile bar. | shadcn docs header | **Shipped (new)** | `components/Nav.tsx` |
| **Section head** | Index, kicker, two-line masked headline, aside, How-to strip. | Existing | Shipped | `components/ui.tsx` |
| **How-to strip** | Steps for the section; hideable everywhere. | Existing | Shipped | `components/ui.tsx`, `lib/guide.ts` |
| **Tier badge** | Status = icon + label + colour, never colour alone. | Sanity UI tones | Shipped | `components/ui.tsx` |
| **Ticker** | Numbers roll to their new value; static under reduced motion. | React Bits CountUp | Shipped | `components/ui.tsx` |
| **Spotlight rows** | A soft radial light follows the pointer across interactive rows (Fleet list, Alerts, Fix events and affected shipments). | React Bits Spotlight Card (CSS-variable variant) | **Shipped (new)** | `index.css` `[data-spotlight]`, `App.tsx` `Spotlight` |
| **Skeleton** | Slow shimmer sweep; static under reduced motion; shaped like the content it replaces (prevents layout shift). | shadcn Skeleton, restyled | **Shipped (upgraded)** | `components/ui.tsx`, `.shimmer` |
| **Overlay surface** | Raised fill, inner top highlight, soft shadow. Used for the palette; for future popovers and menus. | Sanity UI Card elevation, adapted | **Shipped (new)** | `.surface-overlay` |
| **Kbd** | Keyboard hint chip. | shadcn Kbd | **Shipped (new)** | `.kbd` |
| **Charts** | Cascade step chart, fleet map, waterfall, gauge: hand-built d3 + SVG. | — | Shipped | `components/*` |
| **Toast** | Confirm off-screen results (copied, signed out, couldn't reach API). | shadcn Sonner | Deferred (§7) | — |
| **Tooltip primitive** | One accessible tooltip for chart points and icon buttons (today: native `title` plus hand-rolled map tooltip). | shadcn Tooltip / Radix | Deferred (§7) | — |

---

## 3. Visual system

All values are CSS variables in `dashboard/src/index.css`, mapped into Tailwind with `@theme inline`. Components use the Tailwind names (`bg-bg-2`, `text-fg-3`, `text-late`, `bg-raised`, `text-critical`…) and never raw hex.

### 3.1 Colour

One signal colour (`--late`) is reserved for lateness and never used as decoration. Status always ships with an icon and a label.

| Role | Token | Dark | Light | Contrast on bg / bg-2 / bg-3 / overlay (dark · light) |
|---|---|---|---|---|
| Page | `--bg` | `#0a0f12` | `#f3f0e8` | — |
| Panel, sidebar | `--bg-2` | `#0f161a` | `#faf8f3` | — |
| Active row, inset | `--bg-3` | `#162027` | `#e8e3d7` | — |
| Raised (cards) | `--raised` | `#121a1f` | `#fbfaf6` | — |
| Overlay (palette, menus) | `--overlay` | `#141d23` | `#fdfcf9` | — |
| Primary text | `--fg` | `#eaf0ee` | `#0e1418` | 16.7 / 15.8 / 14.3 / 14.8 · 16.3 / 17.5 / 14.5 / 18.1 |
| Secondary text | `--fg-2` | `#a6b3b8` | `#47545a` | 9.0 / 8.5 / 7.7 / 7.9 · 6.9 / 7.4 / 6.1 / 7.6 |
| Tertiary text, labels | `--fg-3` | `#7d8e96` | `#5a666c` | 5.7 / 5.4 / 4.9 / 5.0 · 5.2 / 5.6 / 4.6 / 5.8 |
| **Critical** (late) | `--late` → `critical` | `#ff5a1f` | `#b23608` | 6.2 / 5.9 / 5.3 / 5.5 · 5.4 / 5.8 / 4.8 / 6.0 |
| **Caution** (at risk) | `--risk` / `--risk-ink` → `caution` | `#f2b33d` | `#845a00` (text) | 10.4 / 9.8 / 8.9 / 9.2 · 5.4 / 5.7 / 4.8 / 5.9 |
| **Positive** (on time) | `--ok` → `positive` | `#3cc99f` | `#0b6b4c` | 9.2 / 8.7 / 7.9 / 8.2 · 5.7 / 6.1 / 5.1 / 6.4 |
| Information, focus ring | `--sea` | `#6cb4e0` | `#1d6a9e` | 8.5 / 8.0 / 7.3 / 7.5 · 5.1 / 5.5 / 4.5 / 5.7 |
| Washes | `--late-wash`, `--sea-wash` | 12% tints | 10% tints | Backgrounds only |
| Scrim | `--scrim` | 72% near-black | 35% grey | Behind modals |

Every text colour meets **4.5:1 on every surface it is used on**, in both themes (computed with the WCAG formula and confirmed by axe, §9). Light theme uses separate, darker "ink" values for status text, because the dark-theme hues fail on cream.

### 3.2 Typography

Three families, each with one job. All are self-hosted via `@fontsource`.

| Role | Family | Use | Size |
|---|---|---|---|
| Display | Big Shoulders Display 700/800 | Headlines, big numbers (`.num`, tabular) | Hero `clamp(2.9rem, 7.1cw, 6.75rem)`; section `clamp(2.75rem, 6cw, 5.5rem)`; numbers 2–4.75rem |
| Text | IBM Plex Sans 400/500/600 | Sentences, explanations, list content | Base `1.0625rem / 1.6`; large lead `1.2–1.45rem` |
| Data and labels | IBM Plex Mono 400/500 | IDs, dates, units, eyebrows, chips | `0.75–0.95rem`, eyebrows uppercase, tracking `0.14–0.18em` |

Rules:
- `cw` is 1% of the **content column**, not the viewport (`--cw`), so headlines scale with the space beside the sidebar.
- Minimum text size is 12px (`0.75rem`). The only exception is map port labels (10.5px), which would collide if larger; the list below the map carries the same data.
- Headings use `text-wrap: balance`; paragraphs and list items use `text-wrap: pretty` (**Shipped**).
- Numbers are always tabular, so columns and rolling counters don't jitter.

### 3.3 Spacing and layout

- **Content column:** `.shell` is `max-width 1440px` with gutters of 16 / 32 / 48 px at mobile / `sm` / `lg`.
- **Sidebar:** `--rail` is 15rem expanded and 4.5rem collapsed. Content is offset by `--rail-offset`, which is 0 below 1024 px.
- **Rhythm:** a 4px base. Sections are separated by 96–128px of top space (`pt-24 md:pt-32`). Inside a section, blocks sit 40–80px apart; rows use 20px vertical padding.
- **Grid:** 12 columns from `lg`. Typical splits are 8/4 (headline/aside), 4/8 (figures/map), 5/7 (controls/result) and 6/6 (why/what to do).
- **Rules over boxes:** sections are divided by hairlines (`--line`), not cards. Boxes are kept for overlays and for things the user manipulates.

### 3.4 Elevation

| Level | Surface | Treatment | Used by |
|---|---|---|---|
| 0 | `--bg` | Flat | Page |
| 1 | `--bg-2` | Flat, hairline border | Sidebar, selected row, panels |
| 2 | `--raised` | `--shadow-1` | Reserved for cards that float over content (Deferred) |
| 3 | `--overlay` | `.surface-overlay`: inset 1px top highlight (`--highlight`), `--shadow-2` | Command palette; future menus and popovers |
| Scrim | `--scrim` + 3px blur | — | Behind palette and drawer |

In dark theme, surfaces get **lighter** as they rise. Shadows only separate layers; they never create the sense of height on their own.

### 3.5 Motion and on-scroll

| Token | Value | Use |
|---|---|---|
| `--dur-fast` | 140ms | Hover, press, colour changes |
| `--dur-base` | 260ms | Opening overlays, toggles, sidebar collapse |
| `--dur-slow` | 600ms | Reveals, number rolls, chart transitions |
| `--ease-out` | `cubic-bezier(0.16, 1, 0.3, 1)` | Everything that enters or moves |

- **Enter slower than exit.** For example, the palette enters in 280ms and leaves in 120ms.
- **On scroll:**
  - Section headlines slide up from behind a mask (`MaskLines`).
  - Figures fade up once (`Reveal`).
  - Counters roll when first seen (`Ticker`).
  - The sidebar's right edge doubles as a scroll-progress line.
  - Nothing is scroll-jacked or pinned.
- **Meaningful motion only.** The delay-cascade replay is the one piece of storytelling motion. It autoplays once when visible and has a pause button.
- **Reduced motion:** `MotionConfig reducedMotion="user"`, plus a global CSS override, turns animation off. Counters show final values and the shimmer is static.

### 3.6 Texture

- **Film grain** (`.grain`): an inline SVG `feTurbulence` tile at 5–6% opacity with `overlay` blend. It appears only on the sign-in screen and the hero, the two places a user watches rather than works. It costs one static background image, with no animation.
- **Nautical contours**: the existing hero and sign-in background, drifting gently with the pointer and static under reduced motion. On sign-in it is pinned to the viewport height so font loading can't move it (layout shift).

---

## 4. Layout and page templates

### 4.1 Application shell (≥1024 px)

```
┌──────────────┬──────────────────────────────────────────────────────────┐
│ ⌁ CASCADE  ◧ │                                                          │
├──────────────┤   01 ── FLEET                                 FLEET ON    │
│ ⌕ Search ⌘K  │   23 OF 48 SHIPMENTS                          SAT, 8 NOV  │
│              │   WILL BE LATE.                               ●──────○    │
│ ▷ Replay     │   ┌ How to use  1 …  2 …  3 …        Hide tips ┐         │
│ ◍ Fleet START│   └─────────────────────────────────────────────┘         │
│ ▣ Shipment   │   ─────────────────────────────────────────────────────── │
│ ⚒ Fix        │   [Late 23 ]  ┌──────────────── map ────────────────┐     │
│ ◔ Alerts     │   [Risk  8 ]  │                                      │     │
│ ⛉ Proof      │   [On   17 ]  └──────────────────────────────────────┘     │
│              │   WORST FIRST                 [All][Late][Risk] Sort ▾   │
│              │   01 SHP-000174 ⚠ LATE  98%  ━━●━━  Arrival port  $957 ↗ │
├──────────────┤   02 …                                                    │
│ PR Priya ⇥ 💡☀│                                                          │
└──────────────┴──────────────────────────────────────────────────────────┘
  15rem rail        content column (shell, max 1440px, 12-col grid)
```

### 4.2 Section template

```
eyebrow:   0N ── KICKER
headline:  LINE ONE (fg)                         aside: control or one-line context
           LINE TWO (fg-3)
how-to:    ┌ HOW TO USE  1 step  2 step  3 step   Hide tips ┐
rule ───────────────────────────────────────────────────────
body:      figures (4 cols) │ visual (8 cols)
           list / table with hairline rows, spotlight on hover
```

### 4.3 Shipment detail

```
02 ── SHIPMENT
SHP-000174                                         Open shipment [ select ▾ ]
SHANGHAI → ROTTERDAM
[← Back to Worst first list]        (only when opened from a list)
REPLAY [Booked][Hub arrival][Left hub][Now]          ⚠ LATE · 2 not reported
┌ Expected delay ┬ Chance late ┬ Arrives ┬ Delay cost ┐
cascade chart (step line, hatched forecast, cause band)
WHY (narrative + waterfall)        │  WHAT TO DO (ranked actions, best move)
```

### 4.4 Command palette

```
              ┌──────────────────────────────────────────────┐
              │ ⌕ rotter                                 Esc │
              ├──────────────────────────────────────────────┤
              │ SHIPMENTS                                    │
              │ ▣ SHP-000174  Shanghai → … → Rotterdam · 98% ↵│  ← active (aria-activedescendant)
              │ ▣ SHP-000171  Shanghai → … → Rotterdam · 83%  │
              │ GO TO   ▷ Replay  ◍ Fleet …                   │
              │ ACTIONS ☀ Switch to light theme · 💡 tips · ⇥ │
              ├──────────────────────────────────────────────┤
              │ ↑↓ move   ↵ open                  Ctrl K toggle│
              └──────────────────────────────────────────────┘
```

### 4.5 Below 1024 px

A 64px top bar with menu, wordmark and search. The sidebar becomes a modal drawer (`min(18rem, 85vw)`). Grids collapse to one column; figures go two-up. On touch screens, chips, sliders and links have targets of at least 44px (`@media (pointer: coarse)`).

---

## 5. Interaction patterns and micro-interactions

| Pattern | Behaviour | Status |
|---|---|---|
| **⌘K / Ctrl K / `/`** | Opens the palette from anywhere (`/` is ignored while typing in a field). Arrows, Home/End and PgUp/PgDn move; Enter runs; Esc closes; Tab stays in the input. The empty state suggests an ID format. Focus returns to the opener. | Shipped |
| **Open a shipment** | From the list, map, alerts, scenario results or palette: smooth scroll, then focus moves to the Shipment heading. From a list, a **Back to …** button returns scroll and focus to the exact row. | Shipped |
| **Counts as filters** | Late / At risk / On time counts filter the Worst first list and scroll to it; pressing again clears. | Shipped |
| **Spotlight** | A 260px radial light follows the pointer on interactive rows. Pointer-fine devices only, no re-renders. | Shipped |
| **Numbers** | Roll to their new value when data changes (time slider, what-if, replay). | Shipped |
| **Copy** | Copy explanation shows "Copied". The result is announced to screen readers; a failure is shown in text. | Shipped |
| **Sidebar** | The active section gets a sliding marker (shared layout animation). Collapse state is remembered. The scroll-progress line is on the rail edge. | Shipped |
| **Loading** | Skeletons with the same shape as the content, using a slow shimmer. | Shipped |
| **Toast** | Off-screen confirmations (signed out, API reconnected). | Deferred |
| **Row quick actions** | Hover or focus reveals "open in Fix" and "copy reason" on Fleet rows. | Deferred: needs an action-to-what-if mapping from the API |

---

## 6. Accessibility

The target is WCAG 2.2 AA, verified with axe-core 4.10 in Chromium (§9).

- **Contrast:** every text token is at least 4.5:1 on every surface it sits on, in both themes (§3.1). Status is never conveyed by colour alone: badges carry an icon and a label, and alerts carry a visible severity word.
- **Keyboard:**
  - Everything is reachable by Tab.
  - The skip link goes to Fleet.
  - Focus is visible as a 2px `--sea` outline with offset.
  - Programmatic focus targets (section headings after a jump) suppress the ring, because it would only frame a heading.
  - Replay milestones use roving focus with arrows and Home/End.
- **Command palette:** WAI-ARIA combobox pattern.
  - `role="combobox"` input with `aria-controls`, `aria-activedescendant` and `aria-autocomplete="list"`.
  - `role="listbox"` containing labelled `role="group"`s of `role="option"`.
  - The result count is announced through a polite live region.
  - It is a modal dialog with scroll lock, and focus is restored on close.
- **Drawer:** `role="dialog"` with `aria-modal`, focus trap, Esc to close, scroll lock and focus restored. It closes automatically when the viewport grows past the rail breakpoint.
- **Live regions:** a single summary sentence is announced, never animating numbers (Fix, palette, copy).
- **Touch:** targets are at least 44px on coarse pointers and at least 24px everywhere (WCAG 2.5.8).
- **Motion:** respects `prefers-reduced-motion` everywhere. The replay can be paused and autoplays only once.
- **Decoration:** grain, contours, spotlight and the progress line are `aria-hidden` or pseudo-elements and never carry information.

---

## 7. Deferred, with reasons

| Item | Why not now | Trigger to build |
|---|---|---|
| **Toasts (Sonner pattern)** | Today's confirmations are inline and in view (Copied, Retry sign-out). A toast system without off-screen events would only add motion. | When background events exist, such as live alert push or an API reconnect |
| **Shared tooltip primitive** | The map tooltip and native `title`s work. A Radix tooltip adds a dependency for little gain. | When charts get keyboard-reachable data points |
| **Row quick actions → Fix** | Needs the advisor's `action_id` mapped to what-if parameters, which the API doesn't expose. | API change |
| **Raised cards (`--raised`)** | The layout uses rules, not cards. The token exists for future floating panels. | Saved views or a comparison panel |
| **Code-splitting** | The app ships as one 610 kB chunk (202 kB gzipped; Vite warns above 500 kB). The map topology is only 55 kB of that, so a split would need to lazy-load below-the-fold sections (Fix, Proof). That is a measurable change, not a guess, so it waits for a profile. | If time to interactive on 4G exceeds 3s |
| **Self-hosted font preload** | Sign-in shows a small reflow as Big Shoulders swaps in (CLS 0.05 on a 390px phone, under the 0.1 threshold). Preloading fontsource assets means moving away from CSS imports. | If sign-in CLS matters for a public page |

---

## 8. Implementation guidance

### 8.1 Stack alignment

React 19, Vite 8, Tailwind CSS 4 (`@tailwindcss/vite`, CSS-first config), Motion 14, d3 (geo, scale, shape), lucide-react, `@fontsource`.

The design system lives in two places only:
- **`src/index.css`**: tokens (`:root`, `[data-theme=light]`), the `@theme inline` mapping, component classes (`.shell`, `.eyebrow`, `.chip`, `.kbd`, `.surface-overlay`, `.shimmer`, `.grain`, `[data-spotlight]`).
- **`src/components/ui.tsx`**: shared React primitives (`SectionHead`, `HowTo`, `TierBadge`, `Ticker`, `MaskLines`, `Reveal`, `Skeleton`, `RangeStrip`, `ErrorNote`).

### 8.2 Decisions and trade-offs

| Decision | Alternative considered | Why |
|---|---|---|
| Build the palette in-house (256 lines) | `cmdk` via shadcn Command | cmdk brings Radix Dialog and its own styling surface. The app needs one palette with ~60 items, so substring ranking is enough. Cost: we own the ARIA, which is verified with axe and a scripted keyboard test. Revisit if items exceed ~1,000 or fuzzy matching is needed. |
| Spotlight via one delegated `pointermove` writing CSS variables | Per-component React state (as in most React Bits / 21st.dev copies) | Zero re-renders, one listener for every row, no effect on touch devices. |
| Keep hairline layout; overlays get elevation | Card-everything (typical shadcn dashboard) | Dense data reads better on rules. Cards around every figure make a dashboard look templated. |
| Grain + contours on two screens only | Animated WebGL background (React Bits Aurora/Plasma) | Same sense of depth for about 1 KB and no GPU cost. Ops screens stay calm. |
| Semantic tone aliases on existing colours | New palette | Keeps the brand. New code can say `text-critical` without knowing that "late" is the critical tone. |

### 8.3 Adding a component from shadcn, 21st.dev or Magic MCP

1. Install or generate it into a scratch file, never straight into `components/`.
2. Replace every colour with tokens (`bg-bg-2`, `text-fg-3`, `border-line`, `text-critical`…). There should be no hex values and no `zinc-*` or `slate-*`.
3. Replace radii with ours (4px controls, 8px overlays) and type with ours (Plex Sans text, Plex Mono labels, Big Shoulders numbers).
4. Remove decorative motion. Keep motion that explains a change, and map it to `--dur-*` and `--ease-out`.
5. Check both themes, keyboard-only use, a 390px viewport and `prefers-reduced-motion`.
6. Run the audit in §9. It must stay at 0 axe violations and phone CLS ≤ 0.1.

### 8.4 Performance budget

- JS bundle: ≤ 210 kB gzipped (now 201.7 kB; this round's palette, spotlight and tokens added 2.9 kB).
- CLS ≤ 0.1 on phone (now 0.06) and ≤ 0.05 on desktop (now 0.03).
- No animation on the main thread while idle. The replay stops at "Today" and the shimmer runs only while loading.

---

## 9. Verification (as built)

Run with axe-core 4.10.3 (rules `wcag2a`, `wcag2aa`, `wcag21aa`, `wcag22aa`, `best-practice`) and Playwright on Chromium. Recorded snapshot mode, signed in as the ops planner, scrolled through the whole page.

| Check | 1440×900 dark | 1440×900 light | 390×844 dark | 390×844 light |
|---|---|---|---|---|
| axe violations: sign-in | 0 | 0 | 0 | 0 |
| axe violations: dashboard | 0 | 0 | 0 | 0 |
| axe violations: command palette open | 0 | 0 | 0 | — |
| Cumulative layout shift | 0.026 | 0.026 | 0.060 | 0.058 |
| Targets < 24px | 0 | 0 | 0 | 0 |
| Targets < 44px (touch) | n/a (mouse) | n/a (mouse) | 0 | 0 |

The palette was also exercised by script on all three configurations:
- ⌘K focuses the combobox.
- Typing "rotter" ranks the Rotterdam shipments.
- ↓ ↵ opens the second result.
- The dialog closes and focus lands on the Shipment heading.

---

## 10. Sources

- Sanity UI: [Why Sanity UI? (motivation)](https://www.sanity.io/ui/docs/motivation) · [Sanity UI](https://sanity.io/ui) · [Theme docs](https://www.sanity.io/ui/docs/theme) · [Studio theming (mirror)](https://www.mintlify.com/sanity-io/sanity/guides/theming) · [Sanity UI blog](https://sanity.io/blog/streamline-your-studio-development-with-sanity-ui)
- shadcn/ui: [Tailwind v4](https://ui.shadcn.com/docs/tailwind-v4) · [Command](https://ui.shadcn.com/docs/components/radix/command) · [Registry directory](https://ui.shadcn.com/docs/directory)
- React Bits: [pkgpulse guide (2026)](https://www.pkgpulse.com/guides/react-bits-animated-components-2026) · [React Bits Official](https://reactbits.dev/)

- Spotlight pattern: [21st.dev: React spotlight effect components](https://21st.dev/blog/react-spotlight-effect-components) · [Cruip: spotlight card with Tailwind](https://cruip.com/how-to-create-a-spotlight-card-hover-effect-with-tailwind-css/)
- 21st.dev and Magic MCP: [Vercel community: 21st.dev registry](https://community.vercel.com/t/registry-for-all-shadcn-ui-like-components-by-the-community/3271) · [Magic MCP guide (2026)](https://mcp.directory/blog/21st-dev-magic-mcp-complete-guide-2026) · [Magic MCP on playbooks.com](https://playbooks.com/mcp/21stdev-magic-ui-generator)
