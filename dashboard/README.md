# CASCADE Dashboard

A React control room for the CASCADE ETA model. It shows when each shipment will really arrive, how sure the model is, which stage is to blame, and what to do about it.

React 19 · Vite 8 · Tailwind CSS 4 (`@tailwindcss/vite`) · Motion · d3 (geo, scale, shape) · lucide icons.

## Run it

```bash
# 1. Start the model API (repo root)
python -m cascade.cli serve         # or: python -m uvicorn cascade.serving.app:app --port 8000

# 2. Start the dashboard
cd dashboard
npm install
npm run dev                         # http://localhost:5173
```

| Script | What it does |
|---|---|
| `npm run dev` | Dev server with hot reload on http://localhost:5173 (proxies `/api` to the API) |
| `npm run typecheck` | TypeScript only (`tsc -b`) |
| `npm run build` | Type-check + production build → `dist/` (sections are code-split; critical fonts are preloaded) |
| `npm run preview` | Serve the production build on http://localhost:4173 |
| `npm run test:e2e` | Builds, then runs the Playwright + axe end-to-end tests against the recorded run (desktop and mobile). First time: `npx playwright install chromium`, or reuse an installed browser with `PW_CHANNEL=msedge` (or `chrome`) |
| `npm run snapshot` | Re-record `public/snapshot/` from a running API (after retraining) |

## Where the numbers come from

The dashboard talks to the API through `/api`, which Vite proxies to `http://127.0.0.1:8000` (set `CASCADE_API_TARGET` to change it). Same origin means the session cookie is first-party. At startup it checks `/api/ready`:

- **Live model:** if the API answers, every number comes from it. A server that is still warming up (HTTP 503) is given a few seconds.
- **Recorded run:** if the API is down, it reads `public/snapshot/`. These are real API responses recorded from model v1.2.0, so it still runs as a static site.
- **API lost mid-session:** if the live API stops answering (network error, timeout or 5xx), the dashboard switches to the recorded run for the rest of the session. The badge then reads *Recorded run · API offline*, and the footer says the same. A client error (4xx) is shown as an error and never hidden by the fallback; a 401 ends the session and returns to sign-in.

To call another API origin directly, build with `VITE_API_URL=http://host:port` and add the dashboard's origin to the API's `CASCADE_CORS_ORIGINS`. Force a source with `?source=live` or `?source=snapshot`, or pin a static deployment with `VITE_SOURCE=snapshot`.

| Setting | Effect |
|---|---|
| `VITE_API_URL=http://host:port` | API address used by the app and by `npm run snapshot` (`CASCADE_API_URL` also works for the script) |
| `VITE_SOURCE=snapshot` | Build a static deployment that never probes for an API |
| `?source=live` / `?source=snapshot` | Force a source for one visit |

## Sign in

The dashboard opens on a sign-in screen. Click a demo account (or press 1–4), or use the form with username `priya`, `marco`, `lena` or `reviewer` and password `cascade-demo`.

| Account | Opens on | "Why" wording |
|---|---|---|
| Priya Raman · Ops planner | 01 Fleet | planner |
| Marco Bianchi · Customer support | 02 Shipment | customer |
| Lena Fischer · Network analyst | 05 Proof | planner |
| Aiqon Reviewer | Hero replay | customer |

The API sets the session as a signed JWT in an httpOnly cookie, so a reload keeps you signed in and the top-right button signs out. If the session ends (it expired, or the API runs with `CASCADE_AUTH=required` and the cookie is gone), the dashboard returns to sign-in and says so. A deep link such as `/#alerts` opens that section after sign-in. When the API isn't running, sign-in is simulated in the browser and the screen says "Offline preview".

## What's on the page

| Section | Question it answers |
|---|---|
| Hero | Replay of SHP-000174: late at the hub, much later at the door. Play or step through milestones and watch the delay cascade stage by stage. |
| 01 Fleet | How many shipments will be late, where they are, and which to look at first. The clock replays the last 3 weeks. |
| 02 Shipment | Expected delay, chance late, arrival, cost, the delay by stage, the reason in plain words, and the best action. |
| 03 Fix | What-if for one shipment, and which shipments a storm or port surge would hit. |
| 04 Alerts | What changed this week, in plain words, with the recommended next step. |
| 05 Proof | Error vs simple rules, ranges that held, right-cause rate, where delay grows, and honest limits. |

## Quality bar

- **Resilience.** Each section sits behind its own error boundary, so one failure never blanks the page. Every fetch has a loading, an empty and an error state, and the error state has *Try again*. Stale responses never overwrite newer ones.
- **Accessibility (WCAG 2.2 AA intent).**
  - Status always uses an icon or shape plus a label: map markers are circles, triangles and squares, never colour alone.
  - Text tokens meet 4.5:1 contrast in both themes.
  - There is a skip link, and every control has a visible focus ring.
  - The replay tabs and milestone pickers work with the arrow keys and Home/End.
  - Animated counters expose their final value to screen readers and print.
  - Charts have data-driven text alternatives, and `prefers-reduced-motion` is respected.
- **Performance.**
  - Sections below the hero load as separate chunks.
  - The world atlas is a lazily fetched asset, not part of the JS bundle.
  - Only the Latin and Greek font subsets ship, and the critical faces are preloaded.
  - The fleet clock is debounced.
  - The hero and shipment replays share one request cache, which keeps first load to about 25 API calls.
- **Polish.**
  - Dark and light themes are applied before first paint, so there's no flash of the wrong theme.
  - There's a mobile section menu, plus Open Graph and Twitter cards, a web manifest, an apple-touch-icon and print styles.
  - Times are UTC and labelled as such.

## Design notes

- One signal colour, orange, means *late* and nothing else.
- Solid areas mean *already happened*; hatched areas mean *predicted*.
- Type: Big Shoulders Display (port-signage headlines and numbers) with IBM Plex Sans and Mono. Fonts are self-hosted via Fontsource.
- Dark and light themes, `prefers-reduced-motion` respected, keyboard navigable (arrow keys scrub the replay).

In Docker, `docker/Dockerfile.dashboard` builds the app and serves it with nginx on port 8080, proxying `/api` to the API (`docker compose -f docker/compose.yaml up --build`, from the repo root). CI type-checks and builds the dashboard and runs the Playwright + axe suite on every push and checks that the recorded snapshot matches the published model version.
