# As-Built Notes — What Changed Between Plan and Implementation (and Why)

> The planning docs (PRD, Architecture, Design, TechStack, Rules, Phases, ImplementationPlan) were written before the build. This page records every deliberate deviation, so reviewers can trust that the docs and the code agree.
> Numbers quoted here come from `reports/metrics.json` (seed 42, out-of-time test).

## 1. Modelling

| Planned | Built | Why |
|---|---|---|
| LightGBM quantile models on *remaining delay* | **Residual** quantile models on top of a physics-informed **operator-rulebook projection** of every remaining stage (`features/snapshot.py`) | A mechanistic prior generalises out-of-time; ML learns the corrections and the uncertainty. Ablation: removing the propagation/projection features worsens MAE from 24.5 h to 35.1 h |
| — | The rulebook uses **coefficients deliberately different from the simulator's truth** (e.g. weather 1.2 vs 1.6 h/day, berth-window penalty 0.5 vs 0.8) | Avoids circular evaluation: the model must not "know the simulator" |
| — | **Temporal-validation shrinkage**: the learned median correction is blended with strength λ ∈ {0, .25, .5, .75, 1}, chosen on the latest 20% of *training* voyages | On this data the learned median correction did not beat the rulebook out-of-time, so **λ = 0** was selected automatically. ML still adds calibrated P(late), conformal intervals and stage forecasts. Reported honestly rather than hidden |
| Late classifier + isotonic | Classifier + isotonic **blended** with the quantile-implied P(late); blend weight chosen on temporal validation (0.5) | Classifier base rates drift under the Q4 peak; the quantile-implied probability follows the physics |
| CQR offsets from out-of-fold scores | **Drift-aware CQR**: offset = max(OOF offset, temporal-slice offset) per checkpoint group | OOF-only offsets under-covered pre-departure (63%) under the seasonal shift; now 78% (overall 82%) |
| Monotone constraints on all models | Monotone constraints on the **late classifier and registry-declared features only**; quantile models unconstrained | The installed LightGBM **4.7.0** rejects monotone constraints for objectives that renew leaf outputs (quantile, L1), with the fatal error `Cannot use monotone_constraints in … objective`. No test pins this behaviour. Two further facts: the classifier's `proj_inc_*` (rulebook) features are left unconstrained, and because `feature_fraction = 0.8`, LightGBM silently downgrades the `advanced` constraint method to `basic`. The "quantile models are audited for monotonicity" comment in `train.py` has no matching test (ImprovementPlan P0-7) |
| Calendar features (week-of-year, peak flag) | **Removed** | They encode calendar *time*, which doesn't extrapolate to an out-of-time test; seasonality reaches the model through congestion/weather forecasts (its causal channel) |
| Optional dedicated root-cause classifier | Tested, **not adopted** (39–49% vs 42% for stage attribution) | Forecasting which future stage will dominate is intrinsically noisy; we report top-1 (42%), top-2 (70%) and lift vs a lane-history explainer (+16 pp) |
| "Overdue lower bound" on final delay | Lower bound on the **next milestone only**, plus a reporting-gap inference (a silence longer than the stage plausibly causes is treated as a missing report). ETA floor (heuristic, hard-coded 0.5): **ETA ≥ max(as_of, t_last + 0.5 × (planned_DELIVERED − planned_last))**, where t_last is the last reported event. *Corrected 2026-10-13: this row previously said "as-of + half the planned remaining time", which only coincides at the booked checkpoint. Its binding rate and effect on coverage are not measured yet (ImprovementPlan P0-6)* | Downstream slack can absorb delay, so a hard floor on the *final* delay was wrong; missing ≠ not happened |

## 2. Evaluation & gates

| Planned gate | Built gate | Why |
|---|---|---|
| Attribution top-1 ≥ 60% | **Lift vs lane-history explainer ≥ 10 pp** (achieved +16 pp; top-1 42%, top-2 70%, random 16%) | An absolute threshold was arbitrary; beating a strong naive explainer is the meaningful test |
| Promise flip rate ≤ 40% of raw P50 changes | Reported as **promise hit rate (87%)** and **reversals per shipment (0.61 vs 0.79 raw)** | Most raw ETA-day changes are large, genuine moves that *should* update the promise; hysteresis removes noise flips, not real news |
| Coverage 75–85% hard | 70–90% hard, 80% ± 5 pp target (achieved 81.5%) | Small test set (62 shipments); CIs reported |
| — | Added: **propagation fidelity** (model Φ vs SCM-resimulated Φ, Spearman 0.46) and **advisor fidelity** (hours saved vs true interventions, Spearman 0.43, 72% direction agreement) | Unique to having a structural causal simulator |

## 3. Engineering

| Planned | Built | Why |
|---|---|---|
| Parquet + Pandera | **CSV/JSON/NPZ** + an in-house validator (`data/validation.py`) | On the build machine, an Application Control policy blocks pyarrow's parquet DLL; Pandera added nothing the invariant checks don't cover |
| `shap` TreeExplainer | LightGBM **`pred_contrib`** (exact TreeSHAP in C++) | Same values, no extra dependency, under 2 ms p95 including explanations |
| Optuna tuning | Not used | Defaults + temporal-validation selection were sufficient; avoids overfitting a 238-shipment training set |
| Engine in `serving/` | Engine in **`decision/engine.py`** | Evaluation replays decisions with the same engine; the import-linter layer contract forbids `eval → serving` |
| Async ledger via asyncio | **Thread + bounded queue** (`decision/ledger.py`) | Works identically under sync FastAPI routes; overflow is dropped and counted, never blocking. **Best-effort telemetry, not an audit log:** the default store is `:memory:` (set `CASCADE_LEDGER` to a file for durability), `close()` may lose queued rows, and only `predictions` and `actuals` are written (the `alerts`/`promises` tables are unused) |
| Promise/alerts stored as state | **Derived by replaying the shipment's own milestones** up to as-of | Stateless and deterministic: any replica gives the same answer, and time-travel just works |
| Single shipment-level parquet "world" | Bundle ships `external.npz`, `world_*.csv`, `insights.json` | The API is self-contained: clone → serve, no training needed |

## 4. UI

The six pages were built as designed (Fleet, Shipment detail with time-travel, What-if & Scenario radar, Alerts, Insights, Data health). Additions: an audience switch (ops / customer / analyst), a copy-ready narrative, and an API "reproduce this prediction" snippet.

## 5. Stability across simulator seeds (`cascade seeds`, 5 seeds × 300 shipments)

| Metric | Mean ± sd |
|---|---|
| MAE improvement vs B1 carry-forward | 28% ± 6% (seed 42: 36%, the best case) |
| MAE improvement vs B2 propagation prior | 23% ± 6% |
| P10–P90 coverage | 80% ± 3% |
| Brier / PR-AUC P(late > 24 h) | 0.16 ± 0.02 / 0.87 ± 0.02 (0.92 after arrival) |
| Root-cause top-1 / top-2 | 47% ± 4% / 68% ± 3% |
| Attribution lift vs lane-history explainer | +9 ± 7 pp: the 10 pp gate is **not** met on every seed |
| Propagation-factor Spearman vs truth | 0.35 ± 0.06 |
| Late shipments alerted ≥ 48 h ahead | 87% ± 11% |

Read: accuracy, calibration and coverage are robust across seeds. The root-cause attribution beats naive explainers on average but its margin over a lane-history explainer is seed-dependent, and this is the weakest claim in the project.

## 6. What λ = 0 means (found while verifying the external review, 2026-10-13)

Temporal validation selected **λ = 0** for the learned median correction (validation MAE 24.64 h at λ = 0, rising monotonically to 26.00 h at λ = 1). This has consequences beyond the point forecast, and the v1.0 UI, report and model card did not state them:

| Component | What it actually is at λ = 0 |
|---|---|
| P50 delay / ETA | The operator-rulebook projection + current delay, then the heuristic ETA floor. On the test set the rulebook alone is **24.447 h** MAE vs CASCADE **24.500 h**: the floor costs 0.05 h, and the ML adds nothing to the median |
| P10 / P90 | Learned spread (q10/q90 − q50 residual models) around the rulebook P50, widened by drift-aware CQR. **Learned** |
| P(late) | 0.5 × isotonic classifier + 0.5 × quantile-implied probability. **Learned** (half) |
| Stage forecast (`stage_forecast_hours`, cost, fleet "main stage") | Per-stage L1 models reconciled to the P50. **Learned** |
| Waterfall "forecast" bars, drivers, `root_cause_group` | `proj_inc_*` per stage group, i.e. **the rulebook**. SHAP terms are multiplied by λ and vanish. The "Typical remaining delay" bar is 0 h |
| "Root-cause accuracy 42%" | Accuracy of the **rulebook's** largest projected future stage. The learned stage-forecast explainer scores 44.7% |
| "0 / 261 additivity violations" | Bookkeeping: the "Consistency guardrail" row is defined as the remainder, so it cannot fail |

None of this invalidates the results. A mechanistic prior that the learner cannot beat out-of-time is a legitimate, and honest, finding. But it must be **labelled**. ImprovementPlan P0-1 to P0-3 make the UI, API, report and model card say so, and add real identity tests.

## 7. Original targets vs results (v1.0, seed 42; 5-seed mean ± sd in brackets)

The revised gates in §2 are reasonable, but the original PRD targets must stay visible. Hand-maintained here until ImprovementPlan P0-4 generates this table into the model card.

| PRD goal | Original target | Result | Status |
|---|---|---|---|
| G1 MAE vs carry-forward | ≥ 25% (stretch 40%) | 36% (28% ± 5%) | ✅ met · stretch ❌ · driven by the rulebook |
| G2 PR-AUC at arrival | ≥ 0.75 (stretch 0.85) | 0.90 | ✅ |
| G2 Brier | ≤ 0.15 | 0.182 (0.163 ± 0.019; 1 of 5 seeds ≤ 0.15) | ❌ |
| G3 Coverage per checkpoint group | 80% ± 5 pp | 78 / 78 / 84 / 89% (n = 129 / 270 / 219 / 108 snapshots) | 🟡 partly (post-customs over) |
| G4 Root-cause top-1 | ≥ 70% (stretch 80%) | 42% (47% ± 4%); top-2 70% | ❌ |
| G5 Latency p95 | < 50 ms | 8.5 ms in-process | ✅ (HTTP not measured) |
| G6 Alert lead ≥ 48 h | ≥ 70% of late shipments | 97% (87% ± 11%) | ✅ (measured to *planned* delivery; replay starts at booking) |
| G6 Promise flip ratio | ≤ 0.40 of raw P50 changes | 0.83 | ❌ (replaced by hit rate 87%, reversals 0.61 vs 0.79) |
| G7 One command | < 3 min | about 1 min | ✅ |

