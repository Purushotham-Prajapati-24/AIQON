# Phases — CASCADE Delivery Roadmap (72 hours)

> **As-built note:** implementation details that changed during the build are recorded in [`AsBuilt.md`](AsBuilt.md); where this page and the code disagree, AsBuilt.md is authoritative.
>
> **Review reconciliation (2026-10-13):** an external review was verified claim by claim against the code in [`ReviewVerification.md`](ReviewVerification.md); statements that described the *plan* rather than the build were corrected in place (marked *as built*). Follow-up work is in [`ImprovementPlan.md`](ImprovementPlan.md).

> Phase goals, deliverables, exit gates, cut lists and the demo/report plan.
> Ticket-level breakdown with acceptance criteria and estimates: [`ImplementationPlan.md`](ImplementationPlan.md).

---

## 1. Strategy

- **Vertical slice first, then deepen.** By the end of Day 1 a thin end-to-end path exists (simulate → baseline → evaluate). Every later hour improves a working system instead of integrating at the last minute.
- **Gate-driven.** Each phase ends with measurable exit criteria. If a gate fails, apply the cut list. Never slip the deadline.
- **Parallel workstreams** with interfaces frozen in Phase 0:
  **A** Data/Simulator · **B** ML (features, models, explain, eval) · **C** Platform (API, decision layer, CI/Docker) · **D** UX & Report.
- **Solo mode** (one engineer): follow the *critical path* (§8) and treat P1 items as stretch in the listed order.

```mermaid
gantt
    title CASCADE — 72h plan (team mode)
    dateFormat  YYYY-MM-DD HH:mm
    axisFormat  %a %H:%M
    section Phase 0 · Foundations
    Contracts, skeleton, CI           :p0, 2026-10-13 09:00, 3h
    section Phase 1 · Data & Truth (Day 1)
    Simulator + ledger (A)            :a1, after p0, 7h
    Snapshot builder + leakage tests (B) :b1, after p0, 6h
    Baselines + eval harness (B)      :b2, after b1, 4h
    API skeleton + fallback (C)       :c1, after p0, 5h
    UI shell + theme (D)              :d1, after p0, 5h
    Gate 1                            :milestone, g1, 2026-10-13 22:00, 0h
    section Phase 2 · Intelligence (Day 2)
    Feature families (B)              :b3, 2026-10-14 09:00, 5h
    GBM quantiles + CQR + classifier (B) :b4, after b3, 4h
    Explain: stage SHAP, waterfall, narrative (B) :b5, after b4, 4h
    Decision layer: promise, cost, alerts, ledger (C) :c2, 2026-10-14 09:00, 8h
    Shipment Detail + Fleet pages (D) :d2, 2026-10-14 09:00, 9h
    Gate 2                            :milestone, g2, 2026-10-14 22:00, 0h
    section Phase 3 · Product & Proof (Day 3)
    Advisor + scenarios (B/C)         :c3, 2026-10-15 09:00, 5h
    Insights, propagation, fidelity (B) :b6, 2026-10-15 09:00, 5h
    Hardening, perf, Docker (C)       :c4, after c3, 4h
    Report + model card (D/B)         :d3, 2026-10-15 11:00, 7h
    Demo recording                    :d4, 2026-10-15 18:00, 2h
    Gate 3 · Submission               :milestone, g3, 2026-10-15 20:00, 0h
```

---

## 2. Phase 0 — Foundations & Contracts (Day 1 morning, first 3 hours)

**Goal:** Everyone can work in parallel without blocking each other.

| Deliverable | Owner |
|---|---|
| Repo skeleton (TechStack §4 layout), `pyproject.toml`, `uv.lock`, pre-commit, ruff/mypy config, `.importlinter` | C |
| `domain/stages.py`, `domain/delay.py` (+ tests for `Σ Δ = D`), `domain/schemas.py` (Pydantic: `Shipment`, `Event`, `PredictRequest`, `Prediction`, `Explanation`) | B (ML lead) |
| Schemas (*as built: in-house validator, not Pandera*) for `shipments`, `events`, `cause_ledger`, `external_daily` | A |
| `FeatureRow` + `FEATURE_REGISTRY` skeleton; `Predictor` protocol; artifact `manifest.json` schema | B |
| OpenAPI v1 stubs returning fixture responses (unblocks UI) | C |
| GitHub Actions: lint → types → tests | C |
| Typer CLI skeleton with `generate/train/evaluate/publish/serve/report/all` | C |

**Exit Gate 0 (interface freeze):**
- [ ] `uv sync && uv run pytest` green on a clean clone (Windows + Linux CI).
- [ ] `/v1/predict` stub returns a schema-valid fixture; the UI can render against it.
- [ ] All workstream owners sign off on the `domain/` and API schemas.

---

## 3. Phase 1 — Data, Definitions & Ground Truth (Day 1, after Phase 0)

**Goal:** Realistic data with a known truth, plus an honest scoreboard.

| Deliverable | Owner | Notes |
|---|---|---|
| Port network, lanes, carriers (`sim/network.py`) | A | 15 ports, ~14 lanes, 5 carriers |
| External series: congestion (seasonal + AR(1)), weather (storm episodes) | A | As-of forecast generator with horizon-scaled noise |
| Stage mechanics + cause ledger | A | Recovery, missed connection, berth queue + window miss, customs calendar, rail cut-off, receiving windows |
| Missingness (structural / MCAR / MNAR) | A | Typed |
| Generator CLI → CSV/JSON/NPZ (*as built*) + validation + invariants | A | `cascade generate --n 300 --seed 42` |
| EDA notebook: delay distributions, increments by stage, cause mix | A/D | Feeds report §Data |
| Snapshot expansion + leakage property tests | B | The anti-leakage core |
| Splits (out-of-time + GroupKFold by voyage), frozen | B | |
| Baselines B0/B1/B2 + evaluation harness (MAE by checkpoint, PR-AUC, Brier, bootstrap CIs) | B | First **ETA convergence curve** |
| API: real pipeline wiring with B2 baseline as model, fallback chain, RFC 7807 errors, middleware | C | |
| UI shell: theme, navigation, API client, Fleet table on stub data | D | |

**Exit Gate 1 (end of Day 1):**
- [ ] 300 shipments generated; all schema and invariant checks pass; generation < 10 s.
- [ ] Cause-ledger sums match total delay for 100% of shipments.
- [ ] Late rate between 25% and 45% (realistic, non-trivial class balance). Missed-connection share of late shipments is 10–25%.
- [ ] Leakage property tests pass.
- [ ] Baseline scoreboard (B0/B1/B2 by checkpoint) in `reports/metrics.json`.
- [ ] API serves B2 predictions end-to-end; UI fleet table shows them.

**Cut list if Gate 1 is at risk:** drop mid-stage checkpoints (keep event checkpoints only) · drop the MNAR terminal-congestion missingness · use a single hub.

---

## 4. Phase 2 — Intelligence: Features, Models, Explanations (Day 2)

**Goal:** Beat the baselines with calibrated uncertainty and explanations we can prove.

| Deliverable | Owner |
|---|---|
| Feature families: plan, progress, **propagation** ★, external, OOF priors, data-quality | B |
| LightGBM quantile models (P10/P50/P90) (*as built: no monotone constraints on quantiles; residual over the operator rulebook, λ chosen on temporal validation*) | B |
| Late classifier + isotonic calibration | B |
| CQR conformal offsets per checkpoint group | B |
| Stage-grouped contributions (`pred_contrib`), waterfall, narrative templates (ops/customer/analyst) | B |
| Attribution-fidelity evaluator vs ledger | B |
| Artifact publish with manifest + quality gates; API loads the real model | B/C |
| Decision layer: Promise ETA, cost-of-delay, alert rules, SQLite ledger (*as built: background thread, best-effort*) | C |
| UI: Shipment Detail hero page (ETA card, Gantt timeline with time-travel, waterfall, drivers, narrative copy button), Fleet KPIs + risk table | D |

**Exit Gate 2 (end of Day 2):**
- [x] MAE ≥ 25% better than B1 overall (≥ 15% hard floor), with bootstrap CI. *v1.0: 36% (CI 29–44%), 5 seeds 28% ± 5%; attributable to the rulebook (λ = 0)*
- [ ] Coverage of P10–P90 within 80% ± 5 pp per checkpoint group. *v1.0: 78 / 78 / 84 / 89%: post-customs above the band (partly met)*
- [x] PR-AUC (late) ≥ 0.75 at the destination-arrival checkpoint. *v1.0: 0.90*
- [ ] Attribution fidelity top-1 ≥ 70% (60% hard floor), beating the route-prior explainer. *v1.0: **not met**, 42% top-1 (70% top-2). It beats the lane-history explainer by +16 pp on seed 42 and +9 ± 7 pp over 5 seeds.*
- [x] Waterfall additivity: 0 violations on the test set. *A bookkeeping check only (the guardrail row is the remainder); see ReviewVerification §4.3*
- [x] `/v1/predict` p95 < 50 ms (pytest-benchmark). *v1.0: 8.5 ms in-process (HTTP/concurrency not measured)*
- [x] Shipment Detail page works end-to-end with time-travel.

**Cut list if Gate 2 is at risk:** skip the stage-chain + reconciliation (the timeline uses SHAP group shares of P50 instead) · skip Optuna · ship analyst/customer narratives later.

---

## 5. Phase 3 — Product, Proof & Polish (Day 3)

**Goal:** Turn a good model into a convincing product and a clear submission.

| Deliverable | Owner |
|---|---|
| Intervention Advisor (`/v1/advise`) + advisor fidelity vs true SCM interventions | B/C |
| Disruption Impact Radar (`/v1/scenarios/impact`) + 3 presets | C |
| Propagation matrix (model vs SCM truth) + insights endpoint | B |
| Decision metrics replay: alert lead time, promise flip & hit rate | B |
| Robustness study (dropout 10/30/50%), ablations, learning curve, 5-seed stability | B |
| UI pages: What-If & Scenario Lab, Alerts Inbox, Model & Network Insights, Data Feed Health | D |
| Hardening: schemathesis fuzz, golden tests, locust run, Dockerfiles + compose, `/metrics` | C |
| Model card (auto-generated), README (quick start, architecture GIF/diagram, results table) | B/D |
| **Technical report (2–3 pages PDF)** | D/B |
| **Demo video (≤ 5 min)** | D |

**Exit Gate 3 (submission readiness, Day 3 evening):**
- [ ] `docker compose up` on a clean machine → UI at :8501 and API docs at :8000/docs within 2 minutes.
- [ ] `uv run cascade all --seed 42` reproduces `metrics.json` exactly.
- [ ] CI green, including perf and contract tests.
- [ ] Report is ≤ 3 pages and covers approach, assumptions, ground truth, results with CIs, limitations.
- [ ] Demo ≤ 5:00, follows the script below.
- [ ] Repo link, PDF and demo uploaded; submission email drafted for the candidate to send.

**Cut list if Gate 3 is at risk (in order):** Data Feed Health page → Scenario presets beyond one → schemathesis → learning curve beyond n=1k → Prometheus metrics. **Never cut:** report, README run instructions, baselines comparison, explanation fidelity.

---

## 6. Phase 4 — Post-Submission Roadmap (Productisation)

| Horizon | Item |
|---|---|
| Next 2 weeks | Public/real data adapter (port-call or AIS-derived milestones) behind the `DataSource` interface; recalibrate the simulator against it |
| Next month | Survival/AFT model for censored in-transit shipments; drift monitoring (PSI) with retrain triggers; Postgres ledger |
| Next quarter | Event-driven scoring (Kafka → scorer → ETA store → SSE push); port-network graph features / GNN embeddings; multi-modal stage graphs (air, rail) |
| Research | Causal effect estimation for interventions on real data (double ML) to replace associational counterfactuals |

---

## 7. Report & Demo Plan

### 7.1 Technical report outline (2–3 pages)

1. **Problem framing & definitions** (¼ p): stage graph, ETA/delay/increment definitions, late threshold.
2. **Data** (½ p): SCM mechanics table, how delays were introduced, ground-truth & cause ledger, missingness types, assumptions.
3. **Approach** (¾ p): as-of snapshots, propagation features, Prior + Residual Booster, CQR, explanations (stage SHAP, waterfall, counterfactuals), decision layer in brief.
4. **Results** (¾ p): baseline vs model table with CIs; ETA convergence curve; coverage; attribution & propagation fidelity; one worked example (waterfall + narrative); alert lead time.
5. **Limitations & next steps** (¼ p): synthetic-to-real gap, associational counterfactuals, small n, roadmap.

### 7.2 Demo script (≤ 5:00)

| Time | Scene | Message |
|---|---|---|
| 0:00–0:30 | Title + one-line problem | "ETAs are not static; delays cascade. CASCADE predicts, quantifies, explains *and* advises." |
| 0:30–1:15 | Fleet Overview | Ranked by P(late); KPIs; route map with amplifying hubs |
| 1:15–2:30 | Shipment Detail + **time-travel** | Scrub from booking → Singapore arrival: ETA jumps by +7 days with a widened band; the waterfall blames the transshipment (buffer −7 h). Copy the narrative |
| 2:30–3:15 | Advisor + cost | "Re-book on alt. carrier saves 5.2 days / $2.9k"; Promise ETA vs raw ETA stability |
| 3:15–3:50 | Scenario Lab | "Singapore congestion +15% for 5 days → +9 late shipments, +$31k expected cost" |
| 3:50–4:40 | Insights | Convergence curve vs baselines, coverage, **attribution fidelity 7x%**, propagation matrix model vs truth |
| 4:40–5:00 | Architecture & reliability | One diagram: < 50 ms, fallback chain, one-command run |

---

## 8. Critical Path (Solo Mode Priority Order)

If one person builds CASCADE alone, execute strictly in this order and stop adding scope by Day 3 noon:

1. Domain definitions + snapshot builder + leakage tests
2. Simulator with the 4 core mechanics (recovery, missed connection, berth queue × lateness, customs calendar) + ledger
3. Baselines + evaluation harness + convergence curve
4. Propagation features + LightGBM quantiles + CQR + classifier
5. Stage-grouped contributions + waterfall + narrative + attribution fidelity
6. FastAPI `/v1/predict` with fallback + Streamlit Shipment Detail with time-travel
7. Report + README + demo ← **minimum complete submission (target: Day 3 noon)**
8. Promise ETA + cost-of-delay + alerts replay metrics
9. Advisor + scenario radar
10. Docker, perf, contract tests, remaining UI pages
