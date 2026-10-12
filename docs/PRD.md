# PRD — CASCADE: Stage-Aware Shipment ETA & Delay-Propagation Engine

> **As-built note:** implementation details that changed during the build are recorded in [`AsBuilt.md`](AsBuilt.md); where this page and the code disagree, AsBuilt.md is authoritative.
>
> **Review reconciliation (2026-10-13):** an external review was verified claim by claim against the code in [`ReviewVerification.md`](ReviewVerification.md); statements that described the *plan* rather than the build were corrected in place (marked *as built*). Follow-up work is in [`ImprovementPlan.md`](ImprovementPlan.md).

> **C**ausal-**A**ware **S**tage-**C**hained **A**rrival & **D**elay **E**stimator
> Aiqon AI Internship Take-Home · Status: **Approved for build** · Timebox: **3 days**
> Owners: ML (modeling, eval) · Data (simulator, features) · Backend (API) · UX (control tower, report)

---

## 1. Problem Statement

Logistics planners receive a single, static ETA when a shipment is booked. When a vessel leaves late, a port is congested, or customs holds a container, that delay **propagates** downstream. Sometimes slack absorbs it. Sometimes it is **amplified**: a missed transshipment connection costs a full weekly sailing, or a Friday-evening customs release waits until Monday. Planners find out late, they get no confidence range, and they can't see *which stage* is the root cause, so they can't act (re-book, expedite customs, warn the consignee).

Aiqon needs a system that (1) predicts final ETA, (2) quantifies the likelihood and magnitude of delay, and (3) explains which stages and factors drive that delay. It must capture the **relationships between stages**, not treat each stage independently.

**Cost of not solving it:** reactive firefighting, missed downstream appointments (warehouse slots, trucking), detention and demurrage charges, and lost customer trust from ETAs that stay wrong long after the evidence changed.

---

## 2. Product Vision

> *"At any moment in a shipment's life, tell me when it will really arrive, how sure we are, and which stage is to blame, in under 50 ms."*

CASCADE treats a shipment as a **chain of stages** connected by **buffers** (slack). The ETA is a **living estimate** that updates at every stage event (nowcasting). Each prediction comes with:

- a **calibrated range** (P10 / P50 / P90) with checked coverage,
- a **probability of being late** (above an SLA threshold),
- a **delay waterfall** that splits the expected delay into *realized* delay (already happened) and *forecast* delay (still to come) per stage,
- a **plain-language root-cause narrative**, and
- a **what-if** answer ("if Rotterdam congestion normalises, ETA improves by 14 h").

---

## 3. What Makes This Solution Different

Many candidates will submit "LightGBM + SHAP on a flat table". CASCADE goes further in ways the brief explicitly rewards ("relationships between stages", "real-world logistics behavior", "explain predictions"):

| # | Differentiator | Why it matters to the evaluator |
|---|---|---|
| D1 | **Causal-mechanics simulator** (structural causal model) with real logistics behavior: berth queues that grow non-linearly with utilization, missed-connection *weekly-sailing jumps*, weekend/holiday customs closures, rail/truck cut-offs, slack absorption, structural vs. reporting missingness | "Reflects real-world logistics behavior rather than purely abstract modeling" |
| D2 | **Ground-truth cause ledger.** Every simulated minute of delay is tagged with its stage and cause, so we can **score our explanations** (Attribution Fidelity: top-1 root-cause accuracy) and not just display them | Turns explainability from a claim into a measured result |
| D3 | **As-of snapshot learning (nowcasting).** Each shipment produces one training row per checkpoint, using only the information known at that time. One model serves pre-departure through last mile, and its **ETA convergence curve** shows error falling as stages complete | Captures propagation, handles missing intermediate data |
| D4 | **Propagation-aware features.** Remaining connection buffer, missed-connection probability, congestion × lateness interaction, calendar projection (will customs-ready land on a weekend?), overdue lower bound | "Strong solutions construct features that capture interactions between stages" |
| D5 | **Reconciled stage forecasts.** Per-stage increment models are reconciled so they sum to a stronger global model, which gives a timeline that is both accurate and internally consistent | Stage-level timeline + accurate total |
| D6 | **Conformalized quantiles (CQR)**, calibrated per checkpoint, with **empirically measured** held-out coverage (*as built: no formal guarantee is claimed: conformal guarantees need exchangeability, which the Q4 shift and voyage-correlated snapshots break*) | Trustworthy uncertainty, not decorative bands |
| D7 | **Delay Propagation Matrix.** Counterfactual "+1 h at stage i → Δ final delay" gives each route an amplification (>1) or absorption (<1) factor | An actionable system-level insight that goes beyond a single prediction |
| D8 | **Control-tower UX with time-travel replay.** Scrub a shipment's history and watch the ETA, the confidence band and the blame move | A demo that lands in less than 5 minutes |
| D9 | **Decision layer** (§3A): Promise ETA, alerts, cost-of-delay, intervention advisor, disruption radar, prediction ledger | Moves "beyond isolated predictions" to **actionable insights**, exactly as the brief's closing note asks |
| D10 | **Degradation chain.** model → lane propagation prior → carry-forward. The API never fails silently and always flags `degraded` | Production reliability mindset |

---

## 3A. Beyond the Brief — Product Capabilities a Real ETA Product Needs

The brief asks for *predict → quantify → explain*. Real control towers fail on what comes **after** the prediction: noisy ETAs that customers stop trusting, alerts nobody sees, explanations without a recommended action, and no proof the model is still right next month. CASCADE adds a thin, high-leverage **decision layer** on top of the same model. Every item reuses existing components (the what-if engine, the snapshot builder, the artifact store), so each costs hours, not days.

| # | Capability | The real problem it solves | How (reuses) | Priority |
|---|---|---|---|---|
| V1 | **Promise ETA with hysteresis** | Raw ETAs jitter with every milestone. Customers get "Apr 9… Apr 11… Apr 10" and lose trust. Planners need one *committed* date that only moves when the evidence is strong | Customer-facing date = P80 rounded up to a day, updated only if the new P50 moves > max(12 h, 25% of interval width) **or** the risk tier changes. *As built: P80 is a normal-approximation interpolation `P50 + 0.657·(P90 − P50)`, not a trained quantile; the tier comes from the P50 delay; the change count and reason are returned in the response, but the `promises` table is not yet written (ImprovementPlan P1-7)* | **P1** |
| V2 | **ETA-change alerts with reasons** | Dashboards are pull-based, so planners miss the shipment that just went bad | Rule engine on consecutive predictions: tier change, Promise-ETA move, P(late) jump > 20 pp, **silent shipment** (no milestone for > 1.5× the expected stage time). Each alert is an `AlertEvent` with the narrative attached. Delivered via in-app inbox + webhook stub | **P1** |
| V3 | **Cost-of-delay estimate** | "+200 h" doesn't drive action; "$4,180 of demurrage + a missed DC slot" does | Configurable cost model per port/lane: free-time days, demurrage/detention $/day, missed-appointment penalty, inventory carrying cost. Applied to the P10/P50/P90 delays → **expected cost and range** | **P1** |
| V4 | **Intervention Advisor** (what-if, ranked) | Explanations say *why*, and planners also need *what to do* | A fixed, auditable action menu (pre-file customs docs, book priority berth/fast lane, switch rail→truck, re-book next sailing, notify consignee). Each action maps to a counterfactual input change, and its **hours saved + $ saved** come from the what-if engine. Ranked by net value. *Advisory only, not an optimiser* | **P1** |
| V5 | **Disruption Impact Radar** (fleet-level what-if) | "Singapore congestion +15% for 5 days. Which of my 214 shipments care, and by how much?" | A scenario is applied to the external series and all active shipments are re-scored in batch (vectorised, < 1 s for 1k). Output: affected shipments, Δ late count, Δ expected cost, ranked list | **P1** |
| V6 | **Prediction ledger & live accuracy** | Without a record of what was predicted, nobody can prove the ETA is good or notice when it degrades | Append-only log of every prediction `(shipment, as_of, version, quantiles, p_late)`, joined to actuals on delivery. Gives rolling MAE by checkpoint, coverage, **per-lane trust score** shown next to each ETA, and a drift check (PSI) on key features. *As built: best-effort telemetry: a bounded queue drained by a background thread, overflow dropped and counted, default store `:memory:` (not durable); PSI not implemented* | **P1** (log) / **P2** (drift alerting) |
| V7 | **Data-feed health monitor** | Milestone feeds break silently (carrier EDI gaps), and predictions quietly degrade | Per-carrier/terminal completeness and latency over time; missing-event heatmap; shipments whose confidence dropped *because* of missing data are labelled as such | **P1** |
| V8 | **Audience-aware explanations** | Ops needs stage detail; a customer needs one polite sentence; an analyst needs the features | One explanation object rendered three ways: `ops` (stage + action), `customer` (Promise ETA + plain reason, no internal blame), `analyst` (SHAP features). `?audience=` query param | **P1** |
| V9 | **Model card + data sheet** | Responsible deployment: what the model is for, where it fails, how the data was made | `docs/ModelCard.md` generated from `metrics.json` (intended use, slices with weakest performance, known limitations, simulator assumptions) | **P1** |

**Why these and not others:** each one closes a gap between *a correct prediction* and *a better operational decision* (trust, timeliness, action, money, accountability). Each is built on components that already exist, and each is demo-able in under 30 seconds. Explicitly **not** added: chatbots, route optimisation, LLM agents. They are flashy, but they don't make a 300-shipment ETA product more trustworthy.

---

## 4. Users & Personas

| Persona | Context | Primary need |
|---|---|---|
| **Priya, Ops Planner** (primary) | Manages around 200 active containers across Asia–Europe lanes | Which shipments will be late, by how much, and why. Ranked so she acts on the worst first |
| **Marco, Customer Success** | Answers "where is my order?" | A defensible ETA with a range and a one-sentence reason he can paste to a customer |
| **Lena, Network Analyst** | Optimizes carriers, routes and hubs | Which hubs and stages *amplify* delay; route-level propagation factors |
| **Dev, Platform Engineer** | Integrates ETA into a TMS | Low-latency, versioned, documented API with stable contracts and fallbacks |
| **Aiqon Reviewer** | Evaluates the submission | Clear problem framing, sound features, appropriate approach, explanations that can be checked, reproducibility |

In the React dashboard these personas are the four choices on the entry screen (Ops planner, Customer support, Network analyst, First look). Each choice opens the page where that person's question is answered; see Design.md §10.5.

---

## 5. Goals (measurable)

| ID | Goal | Target (success / stretch) | Measured by |
|---|---|---|---|
| G1 | Accurate final ETA | Overall MAE ≥ **25% / 40%** better than the *carry-forward-delay* baseline on the out-of-time test set | `eval/backtest.py` |
| G2 | Earlier warning of lateness | PR-AUC for `late (>24h)` ≥ **0.75 / 0.85** at the *destination-arrival* checkpoint; Brier ≤ 0.15 | `eval/metrics.py` |
| G3 | Trustworthy uncertainty | P10–P90 empirical coverage within **80% ± 5 pp** at every checkpoint | conformal report |
| G4 | Explanations that are right | Top-1 root-cause stage accuracy ≥ **70% / 80%** vs. the simulator's cause ledger (future stages, pre-arrival checkpoints) | `eval/attribution_fidelity.py` |
| G5 | Low latency | `/v1/predict` (with top-5 drivers) **p95 < 50 ms / 20 ms** on a laptop CPU; batch of 1,000 < 1 s | `tests/perf` + `locust` |
| G6 | Actionable early warning | **Alert lead time:** ≥ 70% of late shipments flagged LATE ≥ 48 h before planned delivery; Promise ETA flip rate ≤ 40% of raw P50 | `eval/decision_metrics.py` |
| G7 | Reproducible | `generate → train → evaluate → serve` in **one command**, under 3 minutes, bit-identical metrics for a fixed seed | CI job |

**Status at v1.0.0** (seed 42 out-of-time test; 5-seed mean ± sd in brackets; numbers from `reports/metrics.json` / `seeds.json`; a generated version of this table is ImprovementPlan P0-4):

| ID | Status | Result | Note |
|---|---|---|---|
| G1 | ✅ success target met · stretch not met | −36% MAE vs B1 (−28% ± 5%) | Attributable to the **operator rulebook**: λ = 0, and the rulebook alone scores 24.45 h vs CASCADE 24.50 h |
| G2 | 🟡 PR-AUC met · Brier not met | PR-AUC 0.90 at arrival; Brier 0.182 (0.163 ± 0.019) vs ≤ 0.15 | Gate loosened to ≤ 0.20 (AsBuilt §2) |
| G3 | 🟡 partly | 82% overall; groups 78 / 78 / 84 / 89% | Post-customs is above the 80 ± 5 band; empirical coverage, not a guarantee |
| G4 | ❌ not met | top-1 42%, top-2 70% (47% ± 4%) | Replaced by "lift vs lane-history ≥ 10 pp": +16 pp on seed 42, **+9 ± 7 pp** over seeds (not met on every seed) |
| G5 | ✅ met (in-process) | p95 8.5 ms predict + explain | HTTP/concurrency not yet measured (ImprovementPlan P2-4) |
| G6 | 🟡 lead met · flip ratio not met | 97% of late shipments alerted ≥ 48 h ahead; promise flip ratio 0.83 vs ≤ 0.40 | Lead measured to *planned* delivery; replaced by hit rate (87%) and reversals (0.61 vs 0.79 raw) |
| G7 | ✅ met (runtime) | about 1 min end to end | Bit-identical rerun not yet verified in CI |

**User goals:** Priya ranks at-risk shipments in under 10 seconds. Marco gets a copy-ready explanation. Lena sees amplifying hubs.
**Business goals:** shows Aiqon a credible, extensible foundation for an ETA product, and shows that the candidate understands the domain.

---

## 6. Non-Goals (v1)

| Non-goal | Rationale |
|---|---|
| Live AIS/vessel-position ingestion | Out of the 3-day scope. The architecture keeps a `DataSource` interface so it can be added later (P2) |
| Deep learning (GNN / Transformers) | 300 shipments is too little data for them. Trees with monotone constraints are more accurate and more interpretable here (see ADR-002) |
| Route optimisation / automatic re-booking | We *rank a fixed menu of interventions* by counterfactual value (V4), but we don't search the routing space or execute bookings |
| Multi-tenant auth, RBAC, billing | Not assessed. The API key is a placeholder middleware |
| LLM-generated explanations by default | Hallucination risk and latency. Explanations are deterministic templates; an LLM narrative is an optional P2 toggle |
| Real-time streaming infra (Kafka) | Event-driven *design* is documented, but v1 uses request/response + batch scoring |

---

## 7. Core Definitions (the contract every module follows)

| Term | Definition |
|---|---|
| **Event** `e_k` | A timestamped milestone: `GATE_IN_ORIGIN, DEPART_ORIGIN, ARRIVE_TS, DEPART_TS, ARRIVE_DEST_PORT, DISCHARGED, CUSTOMS_CLEARED, GATE_OUT, DELIVERED` (TS = transshipment, optional) |
| **Stage** `s_k` | The segment between consecutive events, e.g. `OCEAN_LEG_1`, `TRANSSHIP_DWELL`, `BERTH_AND_DISCHARGE`, `CUSTOMS`, `INLAND` |
| **Event delay** | `delay(e_k) = actual(e_k) − planned(e_k)` in hours (positive = late) |
| **Stage increment** | `Δ_k = delay(e_k) − delay(e_{k−1})`, the delay *added* (Δ>0) or *absorbed* (Δ<0) by stage k |
| **Total delay** | `D = delay(DELIVERED) = Σ Δ_k`. The first increment is `Δ_0 = delay(GATE_IN_ORIGIN) − 0` (booked to stage `PRE_CARRIAGE`), so the sum telescopes from **zero** and equals D exactly, even when gate-in is late |
| **ETA** | `ETA = planned(DELIVERED) + D̂`, where D̂ is predicted as **remaining delay**: `D̂ = delay_observed_so_far + R̂` |
| **Late** | `D > τ`, with τ = 24 h by default (configurable). Risk tiers: *On track* (< 6 h), *At risk* (6–24 h), *Late* (> 24 h) |
| **Checkpoint** | The "as-of" time of a prediction: right after an event, or mid-stage (to learn "overdue" behavior) |
| **Overdue bound** | If the *next* event's planned time has passed with no report, the projected delay of **that milestone** is ≥ `as_of − planned(next)`, unless a reporting gap is inferred (silence longer than the stage plausibly holds). It is **not** a bound on final delay: downstream slack, recovery or a caught connection can absorb it. Final ETAs only get a heuristic floor (see AsBuilt §1) |
| **Root cause** (ground truth) | The stage, and its cause tag, with the largest positive Δ in the simulator's cause ledger. Three outputs must not be conflated: (1) the largest **realised** increment (an observed fact), (2) the predicted **future-delay driver** (scored against the ledger's *future-stage* increments at pre-arrival checkpoints), (3) the **estimated intervention effect** (a model-based what-if) |

---

## 8. User Stories (prioritized)

**Ops Planner (Priya)**
1. As an ops planner, I want a fleet list ranked by probability of being late so I can act on the worst shipments first.
2. As an ops planner, I want each ETA shown with a P10–P90 range so I know how much to trust it before rebooking a truck.
3. As an ops planner, I want to see which stage is driving a delay (e.g., "missed connection at Singapore") so I can take the right action.
4. As an ops planner, I want the ETA to update automatically when a new milestone arrives so I'm not working from stale plans.
5. As an ops planner, when milestones are missing I want the system to still predict and tell me the confidence is lower, not crash or silently guess.

**Customer Success (Marco)**
6. As a CS agent, I want a one-sentence plain-language reason for a delay so I can answer customers quickly and consistently.

**Network Analyst (Lena)**
7. As a network analyst, I want per-route/hub propagation factors so I can see where delays get amplified vs. absorbed.
8. As a network analyst, I want what-if analysis (e.g., congestion normalises) so I can quantify the value of interventions.

**Platform Engineer (Dev)**
9. As a platform engineer, I want a versioned, documented, low-latency API with clear error codes so I can integrate safely.
10. As a platform engineer, I want the service to degrade to a heuristic with a `degraded` flag instead of returning 500s.

**Edge cases:** a shipment not yet departed (no actuals); a direct route (no transshipment events, which is *structurally* missing); an event timestamp earlier than the previous event (bad data → 422 with a clear message); an unknown port/carrier (falls back to global priors, flagged `cold_start`); an already-delivered shipment (returns actuals, prediction = realized).

---

## 9. Requirements

### P0 — Must-have

| ID | Requirement | Acceptance criteria |
|---|---|---|
| R1 | **Synthetic data generator** with stage mechanics, external factors, missingness and a cause ledger | Given `seed` and `n=300`, when `cascade generate` runs, then `shipments`, `events` and `cause_ledger` files are produced (*as built: CSV/JSON/NPZ, since parquet is blocked on the build machine*), pass the in-house validator (`data/validation.py`), and the ledger sums exactly to each shipment's total delay (±1 min) |
| R2 | **ETA & delay definitions** implemented once in `domain/` and reused everywhere | Unit tests prove `Σ Δ_k == D` and `ETA == planned + D` for every shipment |
| R3 | **As-of snapshot builder** with leakage guard | Property test: no feature at checkpoint *t* changes when any event after *t* is perturbed |
| R4 | **Baselines**: schedule, carry-forward, propagation-prior | Reported on the same frozen test split as the models |
| R5 | **Main model**: LightGBM quantile (P10/P50/P90) on remaining delay (*as built: residual quantiles on top of the operator-rulebook projection, learned median blended with λ chosen on temporal validation; λ = 0 on seed 42, so the P50 is the rulebook*) + calibrated late classifier | Beats B1 by G1 target; quantiles never cross (enforced) |
| R6 | **Conformal calibration** per checkpoint group | Coverage within G3 on hold-out |
| R7 | **Explanations**: stage-grouped contributions, delay waterfall, narrative (*as built: forecast bars = rulebook stage projection + λ × TreeSHAP of the residual model; at λ = 0 they are the rulebook alone and must be labelled so (ImprovementPlan P0-1)*) | Each `/predict` returns top-5 drivers + waterfall whose parts sum to D̂ (±0.1 h) |
| R8 | **Evaluation harness**: MAE/RMSE/P90-AE by checkpoint, PR-AUC/Brier, coverage, attribution fidelity, shipment-bootstrap CIs | `cascade evaluate` writes `reports/metrics.json` + figures |
| R9 | **FastAPI service**: `/v1/predict`, `/v1/predict/batch`, `/v1/explain`, `/v1/whatif`, `/health`, `/ready`, `/v1/model` | OpenAPI documented; contract tests pass; p95 within G5 |
| R10 | **Control-tower UI**: fleet view, shipment detail (timeline + waterfall + narrative), model insights | Loads under 2 s; every prediction shows range + drivers |
| R11 | **Technical report** (2–3 pages PDF) + README with one-command run | Covers approach, assumptions, ground-truth construction, results, limitations |

### P1 — Nice-to-have

| ID | Requirement | Acceptance criteria |
|---|---|---|
| R12 | **Stage-chained increment models + reconciliation** for the forecast timeline | Reconciled stage forecasts sum to the global P50; per-stage MAE reported |
| R13 | **Delay Propagation Matrix** (counterfactual sensitivities per route) | Heatmap in UI + report; amplification at transshipment hubs reproduced |
| R14 | **Time-travel replay** slider in the UI | Scrubbing re-predicts at each checkpoint in < 200 ms |
| R15 | **What-if simulator** (congestion, weather, upstream delay) | Returns ΔETA with range |
| R16 | **Robustness study**: random event dropout of 10/30/50% | Degradation curve in report |
| R17 | Docker Compose (`api` + `ui`), GitHub Actions CI | `docker compose up` works on a clean machine |
| R18 | Demo video ≤ 5 min | Script in `Phases.md` |

### P1 — Decision layer (Beyond the brief, see §3A)

| ID | Requirement | Acceptance criteria |
|---|---|---|
| R19 | **Promise ETA** with hysteresis (V1) | Replaying any test shipment checkpoint by checkpoint: Promise ETA changes ≤ 40% as often as the raw P50 date, while its on-time hit rate (actual ≤ promise) stays ≥ 78% |
| R20 | **Alerts** (V2): tier change, promise move, P(late) jump, silent shipment | Replay of the test set produces alerts; ≥ 70% of eventually-late shipments get a LATE alert ≥ 48 h before planned delivery (*alert lead time*); each alert carries a narrative |
| R21 | **Cost-of-delay** (V3) | `/v1/predict` returns `cost_usd: {p10,p50,p90}` from `configs/costs.yaml`; unit-tested free-time logic |
| R22 | **Intervention Advisor** (V4) | `/v1/advise` returns ≤ 5 feasible actions ranked by net $ saved; infeasible actions (e.g. rail→truck when already trucking) are excluded; p95 < 150 ms |
| R23 | **Disruption Impact Radar** (V5) | `/v1/scenarios/impact` re-scores ≤ 1,000 active shipments in < 1 s and returns Δ late count, Δ cost, affected list |
| R24 | **Prediction ledger** (V6) | Every predict call is appended (SQLite via a background thread, off the hot path; *best-effort*: overflow dropped and counted); `/v1/monitoring/accuracy` returns rolling MAE & coverage by checkpoint and a per-lane trust score |
| R25 | **Feed-health view** (V7) and **audience-aware narratives** (V8) | UI page shows completeness by carrier/terminal; `audience=customer` output contains no internal stage blame or raw features |
| R26 | **Model card** (V9) | Generated from `metrics.json` by `cascade report` |

### P2 — Future (design must not block)

Real AIS/port-call data adapter · survival/AFT model for censored in-transit shipments · GNN over the port network · online learning and drift monitoring (PSI) · LLM narrative with grounding · event-stream ingestion (Kafka) · multi-modal (air/rail) stage graphs.

---

## 10. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Latency** | p50 < 10 ms, p95 < 50 ms for single predict + top-5 drivers; full explain (all SHAP + waterfall) p95 < 80 ms; cold start < 3 s |
| **Throughput** | ≥ 500 req/s per worker for predict without full explain (target, verified by load test) |
| **Reliability** | No unhandled 500s on valid schema input; fallback chain; deterministic output per model version; `/ready` false until the model is loaded and warmed up |
| **Correctness** | Quantile monotonicity; next-milestone overdue bound inside the projection; heuristic ETA floor; waterfall identities (realised + rulebook + learned + floor + ordering = P50); waterfall sums to prediction |
| **Reproducibility** | Seeded end-to-end; artifact manifest with data hash, config hash, git SHA, metrics |
| **Observability** | Structured JSON logs with `request_id`, model version, latency; Prometheus metrics endpoint (P1) |
| **Security** | No secrets in repo; input size limits; API-key middleware stub; dependency audit in CI |
| **Accessibility** | Colour-blind-safe palette (Okabe–Ito), never colour-only encoding, keyboard-navigable UI |
| **Portability** | Runs on Windows/macOS/Linux with `uv`; Docker optional |

---

## 11. Success Metrics

**Leading (visible on day 3):** all P0 acceptance criteria green · G1–G7 met on the frozen test set · demo walkthrough under 5 minutes · reviewer can run the project in 1 command.

**Lagging (if productionised):** ETA MAE at destination-arrival checkpoint over 30 days of live traffic · % of late shipments flagged ≥ 48 h before planned delivery · planner time-to-action · reduction in detention/demurrage charges · drift alerts per month.

---

## 12. Assumptions (stated explicitly, as the brief requires)

1. Synthetic data is the primary source. Its parameters are grounded in public, qualitative knowledge of container shipping (weekly liner services, hub transshipment, non-linear port queuing, weekend customs). We claim *plausibility of mechanisms*, not calibration to a specific real lane.
2. **300 shipments** is the reference dataset, per the brief's 100–300 range. A `--n 5000` run is used *only* for a learning-curve sensitivity analysis.
3. Times are UTC internally. Calendar effects (weekends/holidays) use the port's local time zone.
4. External factors (congestion, weather) are known **as-of** the checkpoint, as noisy forecasts for future stages and realised values for past stages, to avoid leakage.
5. Ocean freight only (FCL containers) in v1; the stage graph is configurable.
6. The late threshold τ = 24 h reflects common delivery-window SLAs; all metrics are also reported at τ = 48 h.

---

## 13. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Simulator too easy → inflated metrics | Reviewer distrust | Add irreducible noise, MNAR missingness, unobserved confounder (vessel reliability latent); report baselines; publish generator config |
| Leakage through snapshots of the same shipment | Over-optimistic results | voyage-grouped folds (`voyage_id`, so whole shipments and their co-loaded peers stay together) + voyage-cut out-of-time test; leakage property tests |
| Small data → unstable models | High variance | Strong priors (smoothed target encoding), monotone constraints, shallow trees, bootstrap CIs, multi-seed runs |
| Scope creep in 3 days | Missed deliverables | P0/P1/P2 discipline; phase gates in `Phases.md`; cut list pre-agreed |
| SHAP too slow for latency budget | Missed G5 | TreeSHAP on a ≤ 300-tree model; top-k only on `/predict`; full SHAP on `/explain` |

---

## 14. Open Questions

| Question | Owner | Blocking? |
|---|---|---|
| Does Aiqon prefer a specific late threshold (24 h vs 48 h vs %-of-transit)? | Stakeholder | No (configurable, both reported) |
| Is a public dataset (e.g., Kaggle supply-chain) desirable *in addition* to synthetic? | Stakeholder | No (adapter interface ready; stretch) |
| Report format preference (PDF from Typst vs Google Doc export)? | Stakeholder | No |

---

## 15. Timeline

Hard deadline: **72 hours** from start. Phases and gates are in [`Phases.md`](Phases.md); the ticket-level plan is in [`ImplementationPlan.md`](ImplementationPlan.md).

| Day | Theme | Gate |
|---|---|---|
| Day 0 (first 2 h) | Contracts, skeleton, CI | Interfaces frozen |
| Day 1 | Simulator, definitions, baselines, eval harness | Baseline scoreboard on frozen split |
| Day 2 | Features, models, calibration, explanations | Beats baselines, coverage & fidelity measured |
| Day 3 | API, UI, report, demo, hardening | One-command run, report PDF, demo |
