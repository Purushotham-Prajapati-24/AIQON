# Model Card — CASCADE ETA & Delay-Propagation Model

> Auto-generated from `reports/metrics.json` (model v1.3.0, data seed 42). Do not edit by hand.

## Intended use
Decision *support* for logistics planners: final-ETA nowcasts with empirically calibrated ranges,
probability of late delivery, stage-level explanations and advisory interventions for
containerised ocean freight (ocean lanes with a truck or rail final leg).

**Out of scope:** automated contractual penalties, re-booking without human review, air or
standalone rail moves, and lanes, carriers or ports outside the modelled network (the API rejects
them with 422 rather than guessing).

## Model
* **The point forecast (P50) is the operator-rulebook projection** (learned weight λ = 0.0: the learned median correction did not beat the rulebook on temporal validation, so it is switched off). Learned models contribute the P10–P90 spread, P(late) and the stage forecasts.
* Operator rulebook: physics-informed projection of every remaining stage (cut-offs, headways,
  berth-queue curve, customs calendars, rail timetables) with coefficients deliberately different
  from the simulator's. LightGBM residual quantile models (P10/P50/P90); a late classifier with
  monotone constraints on registry-declared features (method `basic`); per-stage increment models
  reconciled to the P50.
* λ = 0.0 is chosen on two validation views of the training data, never the test set: the
  temporal slice (latest 20% of training voyages) and voyage-grouped out-of-fold predictions
  (temporal slice alone would pick λ = 0.0).
* P(late): a logistic stack of the empirical residual distribution around the rulebook (per checkpoint) and the classifier, fit on voyage-grouped out-of-fold predictions (coefficients [-0.206, 0.387, 0.418]).
* P10/P80/P90 come from the learned residual quantiles directly (v1.3); λ shrinks only the
  point forecast, so with λ = 0 the band is no longer shifted by the unused learned median.
* Data cleaning: a silent milestone counts as overdue only within a short grace window;
  longer silence is treated as a missing EDI report (see experiments/ml_optimization).
* Drift-aware CQR per checkpoint group. Post-processing: quantile ordering, then a heuristic ETA
  floor (remaining stages take ≥ 0.5 × their planned time; it binds on 1% of live test snapshots).
* Explanations: stage bars are labelled by source (rulebook), and
  every P50 satisfies realised + rulebook + learned + ordering + floor = P50 (tested).

## Data
Synthetic structural causal simulator, 300 shipments, late rate 38%.
Milestone reports reach the system after a carrier-dependent latency; a snapshot only sees reports
that had *arrived* by its as-of time.
Independent units: train 83 voyages / 238 shipments / 2665 snapshots; selection slice 18 voyages / 50 shipments / 585 snapshots; test 20 voyages / 62 shipments / 725 snapshots.
Out-of-time test = the latest voyages by departure (Q4 peak season, a deliberate distribution shift).

## Original targets vs results

| ID | Metric | Original target | Revised gate | Result | Status |
|---|---|---|---|---|---|
| G1 | MAE improvement vs carry-forward | >= 25% (stretch 40%) | >= 15% | 37% | ✅ met |
| G2 | PR-AUC P(late) at destination arrival | >= 0.75 (stretch 0.85) | - | 0.93 | ✅ met |
| G2b | Brier P(late > 24 h) | <= 0.15 | <= 0.20 | 0.179 | ❌ unmet |
| G3 | P10-P90 coverage in every checkpoint group | 80% +/- 5 pp each | 70-90% overall | at_port 81% / at_sea 79% / post_customs 96% / pre_departure 77% | 🟡 partly |
| G4 | Future-delay driver top-1 vs cause ledger | >= 70% (stretch 80%) | lift >= 10 pp vs lane history | 42% | ❌ unmet |
| G5 | Latency p95 predict + explain (in-process) | < 50 ms | < 50 ms | 6.3 ms | ✅ met |
| G6a | Late shipments alerted >= 48 h before planned delivery | >= 70% | - | 61% | ❌ unmet |
| G6b | Promise changes / raw P50 day changes | <= 0.40 | hit rate + reversals (reported) | 0.85 | ❌ unmet |
| G7 | One-command run time | < 180 s | - | 197 s | ❌ unmet |

## Performance (out-of-time test)

| Metric | Value |
|---|---|
| MAE final delay — CASCADE / operator rulebook alone | 24.2 h / 24.2 h |
| MAE — B1 carry-forward / B2 propagation prior | 38.6 h / 35.0 h |
| Improvement vs B1 (95% CI, voyage bootstrap) | 37% (25% – 49%) |
| P10–P90 empirical coverage (nominal 80%) | 82% (n = 20 voyages) |
| P(late > 24 h): Brier / PR-AUC | 0.179 / 0.871 |
| Future-delay driver top-1 / top-2 vs cause ledger | 42% / 69% (25% of cases ambiguous: top-two true stages within 6 h) |
| Propagation factor Spearman vs SCM truth (δ = 12 h) | 0.47 |
| Advisor hours-saved Spearman vs SCM truth | 0.45 |
| LATE alerts: recall / precision / false-positive rate | 100% / 84% / 19% |
| Alert burden | 9.7 alerts per 100 shipment-days |
| Latency p95 (in-process predict + explain) | 6.3 ms on Intel64 Family 6 Model 183 Stepping 1, GenuineIntel |

## Coverage evidence by checkpoint group

| Group | Coverage | Width | Snapshots | Shipments | Voyages | 95% CI (voyage bootstrap) |
|---|---|---|---|---|---|---|
| overall | 82% | 86.6 h | 725 | 62 | 20 | 75% – 89% |
| at_port | 81% | 52.1 h | 214 | 60 | 20 | 71% – 90% |
| at_sea | 79% | 114.2 h | 273 | 57 | 20 | 71% – 88% |
| post_customs | 96% | 11.2 h | 106 | 60 | 20 | 93% – 99% |
| pre_departure | 77% | 145.6 h | 132 | 62 | 20 | 61% – 91% |

## Error slices (where the model works poorly)

Slices with fewer than 5 test voyages are suppressed.

| Slice | Group | MAE (h) | B1 MAE (h) | Coverage | Brier | Voyages / shipments / snapshots |
|---|---|---|---|---|---|---|
| horizon | >504 h | 41.2 | 55.2 | 76% | 0.300 | 20 / 61 / 319 |
| horizon | 168-504 h | 29.1 | 42.5 | 85% | 0.116 | 20 / 44 / 61 |
| horizon | <48 h | 6.0 | 20.6 | 87% | 0.041 | 20 / 60 / 193 |
| horizon | 48-168 h | 9.7 | 25.0 | 87% | 0.125 | 19 / 55 / 152 |
| route | transshipment | 28.3 | 45.3 | 79% | 0.195 | 16 / 45 / 575 |
| route | direct | — | — | — | — | 4 / 17 / 150 (suppressed) |
| edi tier | tier 1 | 29.8 | 47.5 | 76% | 0.227 | 9 / 32 / 401 |
| edi tier | tier 2 | 9.1 | 17.1 | 96% | 0.163 | 5 / 13 / 160 |
| edi tier | tier 3 | 25.2 | 37.9 | 83% | 0.077 | 6 / 17 / 164 |
| dest congestion | busy (70-85%) | 26.5 | 35.4 | 82% | 0.213 | 20 / 62 / 509 |
| dest congestion | normal (<=70%) | 23.2 | 26.5 | 83% | 0.105 | 11 / 24 / 65 |
| dest congestion | congested (>85%) | 17.0 | 54.6 | 83% | 0.096 | 11 / 27 / 151 |
| missing events | none | 28.6 | 42.0 | 81% | 0.223 | 20 / 62 / 503 |
| missing events | some missing | 14.2 | 30.8 | 85% | 0.079 | 17 / 36 / 222 |

## Known weaknesses
* Highest error checkpoints: checkpoint 0 (MAE 52.5 h), checkpoint 1 (MAE 46.5 h), checkpoint 3 (MAE 38.3 h). Early checkpoints carry irreducible uncertainty (inspections, missed connections, weather).
* Missing milestones: MAE 0% dropped → 24.2 h, 10% dropped → 23.6 h, 30% dropped → 25.1 h, 50% dropped → 26.4 h.
* Label-time embargo (drop 28 training shipments delivered after the first test departure): MAE 24.3 h, coverage 74%.
* Ablations (test MAE): no_propagation_features 33.9 h, no_priors 24.2 h, no_data_quality 24.2 h; no ETA floor 24.2 h.
* Coverage is *empirical* held-out coverage, not a guarantee: the Q4 shift and voyage-correlated
  snapshots break the exchangeability conformal guarantees need.
* Counterfactual what-ifs are model-based (associational); validated against true interventions only on
  synthetic data. Cost figures use illustrative tariffs.
* Synthetic-to-real gap: mechanisms are plausible, coefficients are not calibrated to a real operator.
  Schedules are never revised in the simulator (lateness is always vs the original plan).

## Ethical & operational considerations
Predictions inform humans; the customer-facing narrative omits internal blame and raw features. Every
response carries the model version, explanation mode (rulebook / learned) and degradation flags. The
prediction ledger is best-effort telemetry (bounded queue; overflow is dropped and counted).
