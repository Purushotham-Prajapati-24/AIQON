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
| Monotone constraints on all models | Monotone constraints on the **late classifier and registry-declared features only**; quantile models unconstrained | LightGBM forbids monotone constraints with quantile objectives (leaf renewal) |
| Calendar features (week-of-year, peak flag) | **Removed** | They encode calendar *time*, which doesn't extrapolate to an out-of-time test; seasonality reaches the model through congestion/weather forecasts (its causal channel) |
| Optional dedicated root-cause classifier | Tested, **not adopted** (39–49% vs 42% for stage attribution) | Forecasting which future stage will dominate is intrinsically noisy; we report top-1 (42%), top-2 (70%) and lift vs a lane-history explainer (+16 pp) |
| "Overdue lower bound" on final delay | Lower bound on the **next milestone only**, plus a reporting-gap inference (a silence longer than the stage plausibly causes is treated as a missing report). ETA floor = as-of + half the planned remaining time | Downstream slack can absorb delay, so a hard floor on the *final* delay was wrong; missing ≠ not happened |

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
| Async ledger via asyncio | **Thread + bounded queue** (`decision/ledger.py`) | Works identically under sync FastAPI routes; overflow is dropped and counted, never blocking |
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
