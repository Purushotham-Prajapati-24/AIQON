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

The dashboard checks `http://127.0.0.1:8000/ready` at startup:

- **Live model:** if the API answers, every number comes from it.
- **Recorded run:** if the API is down, it reads `public/snapshot/`. These are real API responses recorded from model v1.1.0, so it still runs as a static site.

Override the API address with `VITE_API_URL=http://host:port`. Force a source with `?source=live` or `?source=snapshot`.

To re-record the snapshot after retraining (with the API running): `npm run snapshot`.

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
