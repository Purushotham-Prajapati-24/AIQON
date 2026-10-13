# Web Audit: CASCADE Front-ends (senior web review, 2026-10-13)

> **Scope.** This audit covers the React dashboard (`dashboard/`, the flagship UI), its integration with the FastAPI service, and how both are presented in the repo.
> **Method.**
> - Live browser testing at 1280, 1091 and 375 px, in dark and light themes, with keyboard only, in recorded-run mode, and with the API killed mid-session.
> - Network and console inspection, plus DOM measurements: overflow, contrast and label collisions.
> - A line-by-line static review of all ~3,500 lines.
> - A production build and bundle analysis.
>
> **Result.** Every High and Medium finding is fixed and verified. The remaining items are listed in §4 with owners.

---

## 1. Scorecard: before → after

| Dimension | Before | After | How it was verified |
|---|---|---|---|
| **Resilience** | No error boundary; a failed first fetch left skeletons forever. Killing the API left the badge on "Live" while sections failed or showed "All quiet." | One boundary per section. Every fetch has loading, empty and error states, and every error has *Try again*. If the API dies mid-session, the app switches to the recorded run and says so. | Killed the API mid-session, then opened another shipment: it loaded from the recording, and the badge and footer read *Recorded run · API offline*. |
| **API calls on first load** | ~105 | **25** | Performance resource timing, live mode |
| **Initial JavaScript** | 1 chunk, 571 kB (190 kB gzipped); the world atlas was inlined | 9 chunks. Initial ≈ 142 kB gzipped; sections are lazy; the atlas is a 21 kB-gzipped fetched asset | `vite build` output and transfer sizes |
| **Minimum text contrast** | Light 3.04:1, dark 4.03:1 | **Light 4.64:1, dark 4.68:1** (WCAG AA ≥ 4.5) | Computed for every text token on bg, bg-2 and bg-3 |
| **Colour-only encoding** | Map risk dots used colour only (amber 2.6:1) | Circle (on time), triangle (at risk) and square (late), with a legend | Visual check plus the legend |
| **Screen readers** | Counters read "0" until scrolled into view; headings read "0 of 0"; per-frame announcements flooded aria-live | Final values are always exposed. Loading headings say "loading…". There is one calm live summary. | DOM accessible-text audit of all `h2`s |
| **Keyboard** | Replay tabs did not move focus; milestone chips were all tab stops | Tabs and radiogroup use roving focus, arrow keys and Home/End; there is a skip link and a focus ring | Real keyboard events |
| **Mobile** | Section links hidden below 768 px; route caption overflowed by 10 px | Opaque section menu (Escape closes it and focus returns); no horizontal overflow | 375 px, `scrollWidth == clientWidth` |
| **Chart legibility** | Convergence axis labels collided ("BOOKEDCONTAINER INSAILED"); map labels overlapped | Adaptive full, short or alternate labels; tuned map label offsets | Bounding-box overlap check: 0 overlaps |
| **First paint** | Dark flash for light-theme users; display font swapped in late | Theme set before paint; critical fonts preloaded at build time | Built `index.html` has 3 `preload` links |
| **Share and install** | No social or install metadata | Open Graph and Twitter card (1200×630), manifest, apple-touch-icon, theme-color per colour scheme, `noscript`, print styles | `index.html`, `public/` |
| **CI** | Dashboard never type-checked or built in CI | One `dashboard` job: `npm ci`, `npm run build`, the snapshot-matches-published-model check, then the Playwright + axe suite | `.github/workflows/ci.yml` |

---

## 2. What was already strong (kept)

- **Editorial visual system.** Big Shoulders and IBM Plex type, one signal colour that means *late*, solid = happened and hatched = predicted, and hairline rules instead of boxy cards. It reads as a product, not a template.
- **Honest data story.** The hero numbers come from the API, never hard-coded. The Proof section shows baselines, coverage, attribution and propagation against the simulator's ground truth, plus a written "Honest limits" block.
- **Offline-capable by design.** A recorded run of the real model makes the site work as a static deployment.
- **Motion with restraint.** `MotionConfig reducedMotion="user"` plus a CSS reduced-motion override.
- **Whole repo, current state.** 81 Python tests pass (incl. JWT sign-in and the committed-bundle check), `ruff` is clean, and the published model passes its quality gates. There is also a 3-page report, Docker images (dashboard on nginx :8080) and CI.

---

## 3. Fixed in this pass

| Sev | Finding | Fix | Files |
|---|---|---|---|
| High | No error boundary; one bad lookup white-screened the app | `SectionBoundary` around every section; unknown port codes are guarded | `components/ui.tsx`, `App.tsx`, `components/FleetMap.tsx` |
| High | The first `world()` fetch had no catch, so skeletons stayed forever | Page-level error with retry | `lib/store.tsx`, `App.tsx` |
| High | Source decided once; an API outage was never noticed | `pick()` falls back to the recorded run on network errors, timeouts and 5xx and notifies subscribers; 4xx is still surfaced. A warming API (503) gets about 8 s before the fallback. | `lib/api.ts`, `lib/store.tsx`, `components/Nav.tsx`, `components/Footer.tsx` |
| High | Alerts showed "All quiet." on error; Hero and Proof had endless skeletons | Explicit error and empty states with *Try again* | `sections/*.tsx`, `hooks/useAsync.ts` (`retry`) |
| High | Light-theme contrast failures | Tokens re-tuned; all ≥ 4.6:1 | `index.css` |
| High | One 571 kB bundle and about 105 requests on load | `React.lazy` sections, atlas as a fetched asset, a shared replay cache, a debounced fleet clock | `App.tsx`, `lib/api.ts`, `components/FleetMap.tsx`, `sections/Fleet.tsx` |
| Med | What-if showed the previous shipment's numbers | Panel keyed by shipment | `sections/Fix.tsx` |
| Med | "−0 hours", "−0.0 days", "+-0.5" | `signed()` / `delayParts()` never put a sign on zero | `lib/format.ts`, Hero, Fix, Shipment |
| Med | An action that adds time showed "−X" in green | The sign follows the real effect; neutral colour when time isn't saved | `sections/Shipment.tsx` |
| Med | Counters read 0 for assistive tech and in print | `sr-only` final value; `beforeprint` completes the count | `components/ui.tsx` |
| Med | Replay tabs and chips weren't keyboard-correct | Roving focus, arrows, Home/End; chips became a radiogroup | `sections/Hero.tsx`, `sections/Shipment.tsx` |
| Med | aria-live flooded by animated counters | One concise `sr-only` live summary | `sections/Fix.tsx` |
| Med | Selecting a shipment collapsed the page to a 640 px skeleton | Stale-while-loading: the previous detail stays, dimmed and `aria-busy` | `sections/Shipment.tsx` |
| Med | Theme flash; fixed `theme-color` | Pre-paint script; per-scheme meta updated on toggle | `index.html`, `lib/store.tsx` |
| Med | No mobile navigation | Section menu with `aria-expanded`, Escape to close, focus return | `components/Nav.tsx` |
| Med | Alerts regex-parsed message strings | Uses the structured `previous_p_late`, `new_p_late` and `recommended_next_step`; shows a "Next ·" step; "+21 more" became a working *Show all* | `sections/Alerts.tsx`, `lib/types.ts` |
| Med | Proof axis collisions; hard-coded chart limits and alt text | Adaptive labels; scales and alt text derived from the data; real `h3` headings | `sections/Proof.tsx` |
| Med | `tsconfig.tsbuildinfo` tracked and rewritten on every build | Build info moved to `node_modules/.tmp` and ignored | `tsconfig.json`, `.gitignore` |
| Low | Times not labelled UTC; footer year hard-coded | `dateTime()` adds "UTC"; `dayLong(…, withYear)` | `lib/format.ts`, `components/Footer.tsx` |
| Low | Unstyled native select (no chevron); copy button hid "Copied" | CSS chevron; announced status text | `index.css`, `sections/Shipment.tsx` |
| Low | Snapshot script read a different env var than the app | Accepts `VITE_API_URL` or `CASCADE_API_URL`; `VITE_SOURCE=snapshot` for static builds | `scripts/snapshot.mjs`, `lib/api.ts` |
| Low | Package version 1.0.0 vs model v1.1.0; README out of date | Version 1.1.0; README documents scripts, sources, fallback and the quality bar | `package.json`, `dashboard/README.md` |
| Low | README led with the Streamlit app | Dashboard hero screenshot first; quick start launches the dashboard; Streamlit positioned as the analyst console | `README.md`, `docs/screenshots/00_dashboard_*.png` |

### 3a. Reconciled with `main` (PRs #5, #7, #10, #11)

Main gained JWT sign-in with four demo accounts, a same-origin `/api` proxy (Vite and nginx), the v1.2.0 republish and structured alert wording while this pass was in progress. The two lines of work were merged, not overwritten:

| Area | Result |
|---|---|
| Sign-in | Main's `Login` screen and session replace the earlier role picker. The resilience layer still wraps it (error boundary, page-level retry), and the world loads only once signed in. |
| Data layer | Each request carries `credentials: "include"` and handles 401 → sign-in with *"Your session ended"*. It also keeps the live → recorded fallback, the 20 s live timeout, the 503 warm-up probe and typed HTTP errors. A 401 is never treated as an outage. |
| Nav | Main's avatar sign-out button (with retry on failure) sits next to the source badge, mobile section menu and rAF scroll-spy. It is 40 px tall on touch. |
| Alerts | Main's wording, plus percentages clamped to 1–99% so a model probability never reads as certain, and the error state, *Show all* and *Next ·* step. |
| Build | Main's `/api` proxy, plus the critical-font preload and absolute `og:image` plugins. |
| CI | The two `dashboard` jobs both branches added (a duplicate YAML key; one would silently replace the other) are now one job. |
| Recording | Main's v1.2.0 recording, unchanged and byte-identical to the live API. The only addition is `drift.json`, so the drift check also works offline. |

---

## 4. Remaining work (prioritised)

| Pri | Item | Why it matters | Owner / status |
|---|---|---|---|
| P1 | ~~Front-end automated tests~~ | **Done.** `dashboard/e2e/` holds 10 Playwright tests. They cover: sign-in (one key opens that person's section; sign-out returns); a wrong password gives an announced error; an expired session (401) returns to sign-in; render with real numbers; keyboard replay; API outage → recording; 375 px overflow and menu; and axe WCAG 2.2 AA on the sign-in screen and the app in dark and light. 30/30 pass with `--repeat-each=3`. They run in CI (`dashboard` job, Chromium) and locally with `PW_CHANNEL=msedge npm run test:e2e`. The axe scans found and fixed 3 real defects: invalid ARIA on radio chips, low-contrast chip counts (`opacity-60`, 2.8–3.9:1) and status-badge inks (4.4:1). | ✅ |
| P1 | ~~Show the v1.2 backend features~~ | **Done.** The Shipment section shows a dates strip: original commitment, the carrier's current plan with its revision count, CASCADE's P50 and the promise, labelled *calibrated P80*. Proof shows a live drift check (PSI per input, in plain language). The recording is main's v1.2.0 run (62 shipments) plus `drift.json`, and the e2e suite passes on it. | ✅ |
| P1 | ~~Absolute `og:image`~~ | **Done in code.** Build with `VITE_SITE_URL=https://your.domain`: `og:image` becomes absolute, and `og:url` and a canonical link are added. Verified both ways in the built `index.html`. | ✅ (set the variable when deploying) |
| P1 | ~~Untrack `tsconfig.tsbuildinfo`~~ | **Done.** Removed from the git index (the local file stays); the change lands with your next commit. | ✅ |
| P2 | Pause the infinite map and chart dash animations when off-screen. | Idle CPU on background tabs. | Web |
| P2 | Validate API responses at runtime (e.g. zod) and add ESLint with `react-hooks` rules. | Catches contract drift between the API and the UI. | Web |
| P2 | Add structured alert fields server-side (`hours_silent`, `promise_shift_days`, `p_miss`). | Three alert types still read numbers out of message text. | Backend |
| P2 | Compute disruption impacts lazily (on hover or click) instead of 4 POSTs on load. | Load on the API. | Web |
| P2 | ~~Production API hardening~~ | **Mostly done on main.** JWT in an httpOnly cookie, `CASCADE_AUTH=required`, a sign-in throttle, an allow-list via `CASCADE_CORS_ORIGINS`, and same-origin `/api`. Left: a general per-client rate limit on data routes. | Backend |
| P3 | ~~`GET /v1/auth/me` answered 401 when nobody was signed in~~ | **Done.** It now returns `200 {user: null}` when no credentials are sent, so the sign-in screen no longer logs a failed request. An invalid, tampered or expired token is still a 401. | ✅ |
| P3 | Re-audit the Streamlit console, and consider retiring the views it duplicates. | It wasn't re-audited in this pass (its earlier issues were fixed in v1.1). | Web |

---

## 5. Reproduce the checks

```bash
cd dashboard && npm run build
```

```bash
cd dashboard && npm run preview
```

```bash
python -m pytest -q
```

```bash
cd dashboard && PW_CHANNEL=msedge npm run test:e2e
```

To repeat the browser checks:
1. Open http://localhost:4173 and sign in with a demo account (press 1–4).
2. Toggle the theme.
3. Resize to 375 px.
4. Tab through the page.
5. Stop the API and pick another shipment: the badge should switch to *Recorded run · API offline*.
