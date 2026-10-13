# CASCADE Dashboard

A React control room for the CASCADE ETA model. It shows when each shipment will really arrive, how sure the model is, which stage is to blame, and what to do about it.

React 19 · Vite 8 · Tailwind CSS 4 (`@tailwindcss/vite`) · Motion · d3 (geo, scale, shape) · lucide icons.

## Run it

```bash
# 1. Start the model API (repo root)
cascade serve                       # or: python -m uvicorn cascade.serving.app:app --port 8000

# 2. Start the dashboard
cd dashboard
npm install
npm run dev                         # http://localhost:5173
```

The dashboard talks to the API through `/api`, which Vite proxies to `http://127.0.0.1:8000` (set `CASCADE_API_TARGET` to change it). Same origin means the session cookie is first-party. At startup it checks `/api/ready`:

- **Live model:** if the API answers, every number comes from it.
- **Recorded run:** if the API is down, it reads `public/snapshot/`. These are real API responses recorded from model v1.2.0, so it still runs as a static site.

To call another API origin directly, build with `VITE_API_URL=http://host:port` and add the dashboard's origin to the API's `CASCADE_CORS_ORIGINS`. Force a source with `?source=live` or `?source=snapshot`.

To re-record the snapshot after retraining (with the API running): `npm run snapshot`.

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
| Hero | Replay of SHP-000174: 46 h late at the hub, 10 days late at the door. Drag or play through milestones and watch the delay cascade stage by stage. |
| 01 Fleet | How many shipments will be late, where they are, and which to look at first. The clock replays the last 3 weeks. |
| 02 Shipment | Expected delay, chance late, arrival, cost, the delay by stage, the reason in plain words, and the best action. |
| 03 Fix | What-if for one shipment, and which shipments a storm or port surge would hit. |
| 04 Alerts | What changed this week, in plain words. |
| 05 Proof | Error vs simple rules, ranges that held, right-cause rate, where delay grows, and honest limits. |

## Design notes

- One signal colour, orange, means *late* and nothing else. Status always shows an icon and a label, never colour alone. Status colours were checked for colour-blind separation.
- Solid areas mean *already happened*; hatched areas mean *predicted*.
- Type: Big Shoulders Display (port-signage headlines and numbers) with IBM Plex Sans and Mono. Fonts are self-hosted via Fontsource.
- Dark and light themes, `prefers-reduced-motion` respected, keyboard navigable (arrow keys scrub the replay).

```bash
npm run build      # type-check + production build → dist/
npm run preview    # serve the build
```

In Docker, `docker/Dockerfile.dashboard` builds the app and serves it with nginx on port 8080, proxying `/api` to the API (`docker compose -f docker/compose.yaml up --build`, from the repo root). CI type-checks and builds the dashboard on every push and checks that the recorded snapshot matches the published model version.
