# Model Card — CASCADE ETA & Delay-Propagation Model

> Auto-generated from `reports/metrics.json` (model v1.0.0, data seed 42). Do not edit by hand.

## Intended use
Decision *support* for logistics planners: final-ETA nowcasts with calibrated ranges, probability of
late delivery, stage-level explanations and advisory interventions for containerised ocean freight.

**Out of scope:** automated contractual penalties, re-booking without human review, air/rail-only moves,
lanes and ports absent from the training network (served with fallbacks and a `cold_start` flag).

## Model
* Physics-informed *operator rulebook* projection of every remaining stage (cut-offs, headways, berth-queue
  curve, customs calendars, rail timetables) **plus** LightGBM residual quantile models (P10/P50/P90),
  a monotone-constrained late classifier, per-stage increment models reconciled to the P50.
* Learned-correction trust (shrink) = **0.0**, classifier blend = **0.5**, both chosen on a temporal validation slice (never the test set).
* Conformalized quantile regression per checkpoint group; guardrails: quantile ordering, ETA ≥ as-of.

## Data
Synthetic structural causal simulator, 300 shipments, late rate 38%;
out-of-time test = latest ~20% of voyages (Q4 peak season, a deliberate distribution shift).

## Performance (out-of-time test)

| Metric | Value |
|---|---|
| MAE final delay — CASCADE | 24.5 h |
| MAE — B1 carry-forward / B2 propagation prior | 38.4 h / 34.8 h |
| Improvement vs B1 (95% CI) | 36% (29% – 44%) |
| P10–P90 coverage (target 80%) | 82% |
| P(late > 24 h): Brier / PR-AUC | 0.182 / 0.849 |
| Root-cause stage accuracy vs cause ledger | 42% |
| Propagation factor Spearman vs SCM truth | 0.46 |
| Advisor hours-saved Spearman vs SCM truth | 0.43 |
| Late shipments alerted ≥ 48 h ahead | 97% |

## Known weaknesses
* Highest error checkpoints: checkpoint 0 (MAE 53.3 h), checkpoint 1 (MAE 45.3 h), checkpoint 3 (MAE 42.7 h).
  Early checkpoints carry irreducible uncertainty (inspections, missed connections, weather).
* Coverage by group: at_port 84%, at_sea 78%, post_customs 89%, pre_departure 78%.
* Missing milestones: MAE 0% dropped → 24.2 h, 10% dropped → 24.4 h, 30% dropped → 28.6 h, 50% dropped → 32.4 h.
* Ablations (test MAE): no_propagation_features 35.1 h, no_priors 24.5 h, no_data_quality 24.5 h.
* Counterfactual what-ifs are model-based (associational); validated against true interventions only on
  synthetic data. Cost figures use illustrative tariffs.
* Synthetic-to-real gap: mechanisms are plausible, coefficients are not calibrated to a real operator.

## Ethical & operational considerations
Predictions inform humans; the customer-facing narrative omits internal blame and raw features. Every
response carries model version and degradation flags; the prediction ledger enables live accuracy audits.
