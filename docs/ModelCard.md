# Model Card — CASCADE ETA & Delay-Propagation Model

> Auto-generated from `reports/metrics.json` (model v1.2.0, data seed 42). Do not edit by hand.

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
* λ = 0.0 and the P(late) classifier blend = 0.5 are chosen on a temporal
  validation slice (the latest 20% of training voyages), never on the test set.
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
| G2 | PR-AUC P(late) at destination arrival | >= 0.75 (stretch 0.85) | - | 0.89 | ✅ met |
| G2b | Brier P(late > 24 h) | <= 0.15 | <= 0.20 | 0.185 | ❌ unmet |
| G3 | P10-P90 coverage in every checkpoint group | 80% +/- 5 pp each | 70-90% overall | at_port 84% / at_sea 74% / post_customs 91% / pre_departure 82% | 🟡 partly |
| G4 | Future-delay driver top-1 vs cause ledger | >= 70% (stretch 80%) | lift >= 10 pp vs lane history | 42% | ❌ unmet |
| G5 | Latency p95 predict + explain (in-process) | < 50 ms | < 50 ms | 2.4 ms | ✅ met |
| G6a | Late shipments alerted >= 48 h before planned delivery | >= 70% | - | 32% | ❌ unmet |
| G6b | Promise changes / raw P50 day changes | <= 0.40 | hit rate + reversals (reported) | 0.92 | ❌ unmet |
| G7 | One-command run time | < 180 s | - | 60 s | ✅ met |

## Performance (out-of-time test)

| Metric | Value |
|---|---|
| MAE final delay — CASCADE / operator rulebook alone | 24.5 h / 24.5 h |
| MAE — B1 carry-forward / B2 propagation prior | 38.6 h / 35.0 h |
| Improvement vs B1 (95% CI, voyage bootstrap) | 37% (25% – 48%) |
| P10–P90 empirical coverage (nominal 80%) | 81% (n = 20 voyages) |
| P(late > 24 h): Brier / PR-AUC | 0.185 / 0.848 |
| Future-delay driver top-1 / top-2 vs cause ledger | 42% / 68% (25% of cases ambiguous: top-two true stages within 6 h) |
| Propagation factor Spearman vs SCM truth (δ = 12 h) | 0.47 |
| Advisor hours-saved Spearman vs SCM truth | 0.45 |
| LATE alerts: recall / precision / false-positive rate | 100% / 86% / 16% |
| Alert burden | 10.6 alerts per 100 shipment-days |
| Latency p95 (in-process predict + explain) | 2.4 ms on x86_64 |

## Coverage evidence by checkpoint group

| Group | Coverage | Width | Snapshots | Shipments | Voyages | 95% CI (voyage bootstrap) |
|---|---|---|---|---|---|---|
| overall | 81% | 83.0 h | 725 | 62 | 20 | 74% – 87% |
| at_port | 84% | 54.7 h | 214 | 60 | 20 | 72% – 94% |
| at_sea | 74% | 93.8 h | 273 | 57 | 20 | 66% – 83% |
| post_customs | 91% | 11.3 h | 106 | 60 | 20 | 84% – 96% |
| pre_departure | 82% | 164.0 h | 132 | 62 | 20 | 67% – 94% |

## Error slices (where the model works poorly)

Slices with fewer than 5 test voyages are suppressed.

| Slice | Group | MAE (h) | B1 MAE (h) | Coverage | Brier | Voyages / shipments / snapshots |
|---|---|---|---|---|---|---|
| horizon | >504 h | 40.9 | 55.2 | 74% | 0.276 | 20 / 61 / 319 |
| horizon | 168-504 h | 31.9 | 42.5 | 80% | 0.151 | 20 / 44 / 61 |
| horizon | <48 h | 6.3 | 20.6 | 85% | 0.068 | 20 / 60 / 193 |
| horizon | 48-168 h | 10.2 | 25.0 | 88% | 0.154 | 19 / 55 / 152 |
| route | transshipment | 28.5 | 45.3 | 77% | 0.193 | 16 / 45 / 575 |
| route | direct | — | — | — | — | 4 / 17 / 150 (suppressed) |
| edi tier | tier 1 | 29.5 | 47.5 | 75% | 0.226 | 9 / 32 / 401 |
| edi tier | tier 2 | 10.6 | 17.1 | 91% | 0.163 | 5 / 13 / 160 |
| edi tier | tier 3 | 25.7 | 37.9 | 85% | 0.103 | 6 / 17 / 164 |
| dest congestion | busy (70-85%) | 26.5 | 35.4 | 79% | 0.212 | 20 / 62 / 508 |
| dest congestion | normal (<=70%) | 27.0 | 26.5 | 85% | 0.113 | 12 / 25 / 66 |
| dest congestion | congested (>85%) | 16.6 | 54.6 | 83% | 0.123 | 11 / 27 / 151 |
| missing events | none | 28.5 | 42.0 | 78% | 0.224 | 20 / 62 / 503 |
| missing events | some missing | 15.4 | 30.8 | 86% | 0.095 | 17 / 36 / 222 |

## Known weaknesses
* Highest error checkpoints: checkpoint 0 (MAE 52.5 h), checkpoint 1 (MAE 45.0 h), checkpoint 3 (MAE 40.5 h). Early checkpoints carry irreducible uncertainty (inspections, missed connections, weather).
* Missing milestones: MAE 0% dropped → 24.1 h, 10% dropped → 24.4 h, 30% dropped → 28.6 h, 50% dropped → 32.3 h.
* Label-time embargo (drop 28 training shipments delivered after the first test departure): MAE 24.5 h, coverage 78%.
* Ablations (test MAE): no_propagation_features 34.5 h, no_priors 24.5 h, no_data_quality 24.5 h; no ETA floor 24.5 h.
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
