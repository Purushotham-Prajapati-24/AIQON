# CASCADE: 5-Minute Demo Script

> Target length **4:45** (hard limit 5:00). Six scenes, following `docs/Phases.md` §7.2.
> All numbers below were read from the running app (model v1.1.0, world "now" = Sat 08 Nov 2025 07:32 UTC). If you retrain, re-check them before recording.

## Before you record (checklist)

- [ ] **Start the API and UI 2 minutes early** so caches are warm:
  `.\.venv\Scripts\python.exe -m uvicorn cascade.serving.app:app --port 8000`
  `$env:CASCADE_API_URL="http://127.0.0.1:8000"; .\.venv\Scripts\python.exe -m streamlit run app/Home.py`
  (or `docker compose -f docker/compose.yaml up --build`)
- [ ] **Pre-warm:** click through every page once (Home → Shipment Detail → What If → Alerts → Model Insights), then go back to Home.
- [ ] **Browser:** a fresh window with only the app tab, zoom 100%, light theme, and the Streamlit "Deploy" menu left alone. Hide bookmarks (Ctrl+Shift+B).
- [ ] **Screen:** 1920×1080, Windows display scaling 100% or 125%. Close Slack, Teams, mail and anything else that pops up. Turn on Focus assist / Do Not Disturb.
- [ ] **OBS:** Display Capture (or Window Capture of the browser), canvas and output 1920×1080, 30 fps, MP4. Mic level peaking around −12 dB; test 10 s first and play it back.
- [ ] **Second monitor or printout** with this script. Have `docs/Architecture.md` or the README diagram open in a second tab for scene 6.
- [ ] Do one full dry run with a timer. If you run over, cut the lines marked *(optional)*.

---

## Scene 1 · 0:00–0:25 · The problem (Home page, no clicks)

**Screen:** Home, "CASCADE Control Tower".

**Say:**
> "An ETA isn't a single number that stays put. A ship that's two days late can miss its connection at the hub and end up a week late. CASCADE predicts the final ETA with a range, gives the probability of being late, explains **which stage** is driving the delay, and suggests what to do about it. Everything you'll see is checked against a simulator that knows the true cause of every hour of delay."

## Scene 2 · 0:25–1:05 · Fleet overview

**Clicks:**
1. Point at the KPI row: **48 active · 23 late · 8 at risk · about $11.4k expected delay cost**.
2. Point at the table "Shipments ranked by risk": the top two rows are **SHP-000178** (Ho Chi Minh City → Singapore → Antwerp, P(late) 98%) and **SHP-000174** (Shanghai → Tanjung Pelepas → Rotterdam, P(late) 98%, P50 +240 h).
3. Scroll down to **Network risk map** for two seconds, then scroll back up.

**Say:**
> "This is the control tower. Every active shipment gets an ETA range, a probability of being more than 24 hours late, and the stage where the most delay is still expected. It's sorted by risk, so a planner starts at the top. The slider at the top is operating time: the whole fleet can be replayed as of any moment."

## Scene 3 · 1:05–2:25 · Shipment detail + time-travel (the key moment)

**Clicks:**
1. Sidebar → **Shipment Detail**. In the **Shipment** box pick **SHP-000174**. Point at the 🔎 **Evidence** line (last report, how old it is, feed quality, what the forecast rests on).
2. Drag the **⏪ Time-travel** slider all the way left to **Booked · 26 Sep**.
   - Card shows expected delay **+2.0 d**, P(late) about **48%**. The main driver is already **Transshipment**.
3. Move one notch right to **After Arrive Ts · 10 Oct** (the report reached CASCADE about two hours after the event): the vessel reached Tanjung Pelepas **46 h late**.
   - Expected delay jumps to **+7.0 d**, P(late) **82%**.
   - Scroll to **Delay waterfall**: the hatched **Transshipment** bar is about **+126 h**. The narrative says "projected to reach Tanjung Pelepas after the connection cut-off (buffer short by 36 h)".
4. Move one more notch to **After Depart Ts · 18 Oct**: the hub departure confirms the missed connection (actual departure a week after plan). Expected delay **+8.0 d**, P(late) **95%**.
5. Drag the slider to the far right, **Now · 08 Nov** (the slider only offers milestones reported by "now"): expected **+10.0 d**, range +6.2 … +12.1 d. Main driver is now **Destination port: Rotterdam berth utilisation 93%**, and the promise date is **2025-11-16**.
6. Click the **Customer** radio button for one second to show the plain-language version, then go back to **Ops planner**.

**Say:**
> "Here's the cascade. At booking, CASCADE expects two days late, and it already flags the transshipment as the risk. The vessel then reaches Tanjung Pelepas 46 hours late. The model projects that it will miss the connection cut-off by 36 hours, which means waiting for the next sailing. The forecast jumps from two days to seven, and the waterfall puts the blame exactly there. Later, as the ship heads for Rotterdam, the main risk moves to the destination port, where berths are 93% utilised. Each bar is an exact, additive contribution, and the bars add up to the forecast. The same explanation can be written for the planner, for the customer, or for an analyst."

## Scene 4 · 2:25–3:15 · Advisor + cost

**Clicks:**
1. In the **Shipment** box, pick **SHP-000245**.
2. Scroll to **Recommended actions**. The top action is ✅ **Book overtime / weekend customs clearance: saves 2.0 d, $490 avoided for $250 (net +$240); P(late) after: 17%** (44% before). Point at the three ticks under it: ✓ consistent ✓ feasible in time ✓ pays off. Berth priority shows ✗ pays off.
3. Scroll back up to point at **Promise date** and **Expected delay cost** on the card. *(optional)*

**Say:**
> "Predictions are only useful if someone can act on them. For this shipment, the advisor checks a fixed menu of actions. Booking weekend customs clearance saves about two days: it costs 250 dollars and avoids 490 in delay costs, and it cuts the late probability from 44% to 17%. Every action says whether it is still possible in time and whether it pays for itself, and which assumptions it rests on. The customer gets a *promise date* that has hysteresis, so it doesn't flip every time the raw ETA wobbles. The promise held in 89% of cases, with fewer reversals than the raw ETA."

## Scene 5 · 3:15–3:50 · Disruption radar

**Clicks:**
1. Sidebar → **What If and Scenarios** → tab **Fleet disruption radar**.
2. Preset disruption → **Indian Ocean cyclone for 4 days** → **Run impact analysis**.
3. Result: **3 shipments affected, +2 late, +$1,007 expected cost**. Two go **On track → Late** (SHP-000062, SHP-000008).

**Say:**
> "The same engine works at fleet level. If a cyclone hits the Indian Ocean for four days, which shipments care? Only three are on affected legs, and two of them flip from on-track to late, about a thousand dollars of expected cost. Ops gets a short list instead of an alarm about everything."

## Scene 6 · 3:50–4:45 · Insights + architecture

**Clicks:**
1. Sidebar → **Model Insights**. Point at the KPI row: **MAE −36% vs carry-forward (95% CI 29–44%) · coverage 80% · PR-AUC 0.86 · future-delay driver 42% top-1 / 69% top-2 · p95 1.7 ms**.
2. Tab **Explanation fidelity**: point at the bars (CASCADE top-2 vs lane-history vs random) and the **Advisor fidelity** line (Spearman 0.43, 72% direction agreement).
3. Tab **Delay propagation**: the Φ heatmap. *(optional)*
4. Switch to the README tab → architecture diagram.

**Say:**
> "Does it work? On a later, out-of-time test season, ETA error is 36% lower than carry-forward. Across five simulator seeds, the average is 27%, which is the fairer number. The 80% ranges cover 80% of outcomes. And because the simulator records the true cause of every hour of delay, we can *score* the explanations: the stage named as the main future driver is the true one 42% of the time, 69% in the top two, against 26% for a lane-history guess, and a quarter of cases are genuinely ambiguous. That's the weakest claim, and the report says so. One honest finding: most of the accuracy comes from an operator-rulebook projection. The learned correction didn't beat it on validation, so the pipeline switched it off, and the screen says so: every bar is labelled rulebook, learned or observed. The ML adds calibrated probabilities and ranges instead. The model card lists the targets we missed.
>
> Architecture: one command runs simulate, train, evaluate and publish behind quality gates. The API answers in about 2 milliseconds and falls back to a propagation prior if anything fails. Code, report and Docker setup are in the repo. Thank you."

---

## Timing summary

| Scene | Start | End | Length |
|---|---|---|---|
| 1 Problem | 0:00 | 0:25 | 0:25 |
| 2 Fleet | 0:25 | 1:05 | 0:40 |
| 3 Shipment + time-travel | 1:05 | 2:25 | 1:20 |
| 4 Advisor + cost | 2:25 | 3:15 | 0:50 |
| 5 Disruption radar | 3:15 | 3:50 | 0:35 |
| 6 Insights + architecture | 3:50 | 4:45 | 0:55 |
| Buffer | | | 0:15 |

## If something goes wrong while recording

- **The page shows an error box:** the API isn't running or is still loading. Check `http://127.0.0.1:8000/ready` and wait for `"ready": true`.
- **The numbers differ from this script:** the bundle was retrained. Read the new values off the screen. The story (booking → missed connection → jump) holds for SHP-000174 as long as `cascade all` uses seed 42.
- **Running long:** drop the *(optional)* items and the Customer-audience toggle.

## Alternative: recording with the React dashboard

The same story works in `dashboard/` (`npm run dev`, http://localhost:5173), with fewer clicks:

| Scene | React dashboard |
|---|---|
| 1 Problem | Entry screen: "What do you need today?". Pick **First look** (key 4). The hero replays SHP-000174 by itself: +2.0 → +7.0 → +8.0 → +10.0 days |
| 2 Fleet | **01 Fleet**: "23 of 48 shipments will be late", the map, then drag the **Fleet on** slider back three weeks and return |
| 3 Shipment | Click a row in **Worst first**. **02 Shipment** opens it; step through the replay chips and switch **For the customer / For the planner** |
| 4 Advisor + cost | **What to do** on the same section, and the **Delay cost** split |
| 5 Disruption | **03 Fix** → **If this happens**; each event shows how many shipments it hits |
| 6 Insights | **05 Proof**, then the README architecture diagram |

To start on the entry screen again, use the role button in the top bar. To skip it, open a deep link such as `/#fleet`.

