# Improvement Plan v1.1 — "Trust every ETA"

> **Source:** the external review, verified against the code in [`ReviewVerification.md`](ReviewVerification.md) (claim numbers like `§4.3` refer to that page).
> **Goal of v1.1:** no new features. Make every number, explanation and claim **true, labelled and testable**: what was known at prediction time, how much of the ETA comes from observed facts vs the operator rulebook vs learned corrections, how uncertainty was measured, and whether an action is feasible.
> **Owners:** **C1** = core code (`src/`, `app/`, `tests/`, `configs/`, `eval/model_card.py`) · **C2** = docs, report, README, screenshots, demo · **YOU** = decisions and recording.
> The C1 work is packaged as a ready-to-paste prompt in `claude1.md` (repo root, gitignored).

## Status — v1.1.0 implemented (2026-10-13)

The P0 tickets were implemented (by C2, at the user's request), along with most of P1 and two P2 items. Bundle `artifacts/v1.1.0`, tests 57/57, all hard gates pass. Results: [`ModelCard.md`](ModelCard.md) (generated) and [`AsBuilt.md`](AsBuilt.md) §8.

| Ticket | Status | Notes |
|---|---|---|
| P0-1 Explanation labels | ✅ | Waterfall kinds `realized / rulebook / learned / ordering / floor / delivered / total`. The response carries `explanation.mode` and `shrink`. Drivers carry `source`. The analyst narrative states λ |
| P0-2 Real identities | ✅ | `identity_errors()` (a, b, c) on 261 checkpoints, max error ≈ 1e-10 h; a negative test proves the check can fail |
| P0-3 Rulebook baseline | ✅ | Headline, voyage CI, per-seed values and info gate `mae_ratio_cascade_vs_rulebook ≤ 1.01` |
| P0-4 Targets vs results | ✅ | `metrics.targets`, generated into the model card. Unmet: G2b Brier, G4 top-1, G6b flip ratio; partly met: G3 |
| P0-5 Information time | ✅ | `available_h = max(actual, reported) + latency` (lognormal by EDI tier, separate RNG stream). API `reported_at`. The reviewer's two leakage tests pass. Post-delivery snapshots are dropped |
| P0-6 ETA floor | ✅ | `eta_floor_min_remaining_frac` in config; applied on the fallback path too; binding share and a no-floor ablation are reported (it binds on < 1% of snapshots) |
| P0-7 Small fixes | ✅ | P(late) blend selected with the deployed isotonic classifier; confusion matrix re-oriented; `cold_start` flag and claim removed; monotone method `basic` + an audit test; ledger documented as best-effort and reports `durable`; compose ledger is file-backed |
| P0-8 Docs | ✅ | This page, ReviewVerification, AsBuilt |
| P1-1 Independence-aware evaluation | ✅ | Split counts in voyages; voyage-cluster bootstrap; coverage with n and a voyage CI; attribution ambiguity, per-checkpoint and unambiguous accuracy |
| P1-2 Embargo | ✅ | `metrics.embargo` (retrain without labels realised after the first test departure) |
| P1-3 `data_quality` object | ✅ | On every prediction; an Evidence row on Shipment Detail. Forecast age is not modelled (forecasts are issued at the as-of time) |
| P1-4 Alerts | 🟡 | Contract fields (reason, evidence time, previous → new risk and P(late), next step, data-quality flags), FPR, burden and lead-time distribution to the actual delivery are done. **Not done:** thresholds tuned on validation (they are still fixed rules), and a duplicates-suppressed count |
| P1-5 Advisor | ✅ | Deadline milestone + lead time, three validity flags, assumptions, baseline vs scenario, benefit range over +0 / +6 / +12 h; feasible actions ranked first |
| P1-6 Propagation | ✅ | δ ∈ {1, 6, 12, 24} h, near-cut-off vs comfortable buffer, n per cell (cells are captioned, not greyed out) |
| P1-7 Promise P80 | ❌ | Still a normal approximation; documented as such (Design §11.1) |
| P1-8 Error slices | ❌ | Only by checkpoint, checkpoint group, missingness rate and attribution ambiguity |
| P2-1 / P2-2 Schedule revisions, duplicate/corrected messages | ❌ | Design only (below) |
| P2-3 Simulator sensitivity | ✅ | `cascade sensitivity` → `reports/sensitivity.json` (7 variants) |
| P2-4 Latency methodology | 🟡 | Environment and method are recorded in `metrics.meta.environment`; HTTP/concurrency figures are not published |
| P2-5 / P2-6 Durable ledger, per-row batch fallback | 🟡 / ❌ | The compose ledger is file-backed; PSI and per-row batch fallback are not done |

## 0. Principles for this round

1. **Report, don't rescue.** If a fix makes a metric worse, publish the worse number. Original targets stay visible next to revised gates.
2. **Label every component by its source:** *observed* (facts), *rulebook* (mechanistic projection), *learned* (ML correction, with its λ), *guardrail* (post-processing). Never present a rulebook number as a model contribution.
3. **The unit of independence is the voyage.** Counts, CIs and claims are stated in voyages and shipments, not snapshots.
4. **Generated numbers only.** Results reach README, report and model card from `metrics.json` and `seeds.json`; nothing is hand-typed.
5. **Keep the scope small.** No LLM, no new model families, no new dashboard pages (the review agrees).

---

## 1. Priority 0 — trust the prediction (do first; ≈ 1 day of C1 work)

### P0-1 · Label explanations honestly when λ = 0 (`§4.1, 4.2, 4.4`) — **C1**, 3 h
- **Change:** `explain/explainer.py`, `models/predictor.py`, `app/ui.py`, `app/pages/1_Shipment_Detail.py`, `eval/model_card.py`.
  - Split `contributions()` into `rulebook_by_group` (sum of `proj_inc_*` per stage group) and `learned_by_group` (λ × SHAP per group).
  - Waterfall kinds become `realized | rulebook | learned | floor | ordering | total`. Drop the learned bias row ("Typical remaining delay") when λ = 0. Otherwise label it "Learned correction: baseline".
  - Split today's single "Consistency guardrail" into **ETA floor** and **quantile ordering**.
  - Add `explanation.mode` = `"rulebook"` (λ = 0) or `"rulebook+learned"`, plus `explanation.shrink = λ` to the API response.
  - UI caption: "◦ rulebook projection by stage (operator mechanics) · ◆ learned correction (λ = …)". Analyst narrative states λ and the split.
  - The drivers' `top_feature` at λ = 0 must name the rulebook mechanism (e.g. "projected missed connection"), not a `proj_inc_*` column.
- **Accept:**
  1. A test at λ = 0 asserts that no waterfall item has kind `learned` and that `explanation.mode == "rulebook"`.
  2. A test at λ = 0.5 (forced) asserts that learned items exist and are scaled by 0.5.
  3. `/v1/predict` returns `mode` and `shrink`.
  4. A screenshot of the waterfall shows the new legend.

### P0-2 · Replace the tautological additivity test with real identities (`§4.3`) — **C1**, 1.5 h
- **Change:** `tests/property/test_model_invariants.py`, `eval/evaluate.py`.
- **Identities (hours, P50):**
  - (a) `realized + rulebook + learned == raw P50 delay` (before floor and sort), tolerance 0.1 h.
  - (b) `raw P50 + floor_adjust + ordering_adjust == final P50`, where each adjustment is computed explicitly, not as a remainder.
  - (c) `planned_delivery + final P50 delay == ETA_P50` (timestamp identity).
- **Metrics:** replace `waterfall_additivity_violations` with `identity_violations` (a + b + c) **plus** `floor_binding_share` and `mean_floor_adjust_h`.
- **Accept:** a deliberately broken contribution (monkeypatched) makes the test fail. The new keys are in `metrics.json` and the model card.

### P0-3 · Make the rulebook a first-class baseline and gate (`§5.8, 4.1`) — **C1**, 1.5 h
- **Change:** `eval/evaluate.py`, `eval/pipeline.py` (gates), `cli.py seeds`, `eval/model_card.py`.
- **Add:**
  - `headline.mae_rulebook_h`, `headline.mae_improvement_vs_rulebook` (with a bootstrap CI), `headline.shrink`.
  - The same in every `seeds.json` run.
  - New **informational** gate `learned_not_worse_than_rulebook` (CASCADE MAE ≤ rulebook MAE × 1.01). Report pass/fail; do not block publishing on it.
  - Model card sentence, generated: "The point forecast is the operator-rulebook projection (λ = 0.0); learned models contribute P(late), interval width and stage forecasts."
- **Accept:** the README/report results table (C2, via `build_report.py`) shows a rulebook column for seed 42 and the 5-seed mean ± sd.

### P0-4 · Original targets vs results, generated (`§5.1, 5.5, 5.9`) — **C1**, 1.5 h
- **Change:** `eval/pipeline.py`, `eval/model_card.py`. Add `metrics.json.targets` with one entry per PRD goal: `{id, metric, original_target, revised_gate, value, status: met|unmet|partly}`.

  | ID | Metric | Original target |
  |---|---|---|
  | G1 | MAE vs B1 | ≥ 25% / 40% |
  | G2 | PR-AUC at arrival | ≥ 0.75 |
  | G2b | Brier | ≤ 0.15 |
  | G3 | Coverage per checkpoint group | 80 ± 5 pp |
  | G4 | Root-cause top-1 | ≥ 70% |
  | G5 | Latency p95 | < 50 ms |
  | G6a | ≥ 48 h alert lead share | ≥ 70% |
  | G6b | Promise flip ratio | ≤ 0.40 |
  | G7 | One-command runtime | < 3 min |

- **Accept:** the model card has a "Targets vs results" table. On seed 42 it shows **unmet** for G2b (0.182), G4 (42%), G6b (0.83), and **partly** for G3 (post-customs 89%).

### P0-5 · Information-time contract, minimal fix (`§1.1, 1.2, 1.4`) — **C1**, 2 h
- **Change:** `sim/generator.py`, `features/dataset.py`, `tests/property/test_no_leakage.py`, `configs/sim.yaml`.
  - Keep `actual_h` (occurrence) and **rename** `reported_h` to `available_h`, with `available_h = actual_h + latency`, `latency ≥ 0` (replacing symmetric jitter). Latency is lognormal by carrier EDI tier: tier 1 median 0.5 h, tier 2 2 h, tier 3 6 h, configurable. The delay is computed from `actual_h`; availability is filtered on `available_h ≤ as_of`.
  - Training checkpoints are placed at `available_h + 1 min`. Mid-stage samples must not use unavailable actuals.
  - **API compatibility:** `observed` keeps meaning "event time". Add an optional `reported_at` per event; default it to the event time.
- **Accept:** the reviewer's test, verbatim:
  - (1) A report with `available_h > t` for an event with `actual_h < t` leaves the row at `t` bit-identical.
  - (2) Moving `available_h` to `≤ t` changes the features.
  - (3) No `available_h < actual_h` anywhere (validation invariant).
  - Re-run and **publish the new metrics, even if worse.**

### P0-6 · ETA floor: name it, measure it, apply it consistently (`§3.3, 3.4`) — **C1**, 1.5 h
- **Change:** `features/snapshot.py`, `configs/train.yaml`, `decision/engine.py` (fallback path), `eval/evaluate.py`.
  - Move `0.5` to config as `eta_floor_min_remaining_frac`.
  - Apply the same floor on the fallback path.
  - Ablate it: floor on vs off → MAE, coverage, `floor_binding_share`. Add a test that the floor holds for the final quantiles.
- **Accept:** `metrics.json.ablations.no_eta_floor` exists, and the AsBuilt formula matches the code (already corrected in the docs).

### P0-7 · Small honesty and correctness fixes (`§2.6, 5.4, 7.1, 7.8`) — **C1**, 1.5 h
- **P(late) blend:** select the blend weight with the **same isotonic classifier** that is deployed.
- **Confusion matrix:** fix the orientation (`crosstab(pred, true)` keyed by true) and rename it `confusion_true_rows`.
- **`cold_start`:** either compute it (lane, port or carrier unseen in training priors → back-off + `cold_start = true`) or delete the flag *and* the model-card claim. Recommended: **delete the claim**, keep the 422 for unknown lanes, and say so.
- **Monotone constraints:** set `monotone_constraints_method = "basic"` explicitly (LightGBM silently downgrades `advanced` when `feature_fraction < 1`). Either add the promised monotonicity audit test (classifier P(late) non-decreasing in `current_delay_h`) or remove the comment that claims it.
- **Ledger:** docstring says "best-effort telemetry". Docker compose sets `CASCADE_LEDGER=/tmp/ledger.sqlite`, and `/v1/monitoring/accuracy` returns `dropped` and `durable: bool`.
- **Accept:** each fix has a unit test or an assertion; `ruff`, `mypy`, `lint-imports` and pytest are green.

### P0-8 · Docs reconciliation — **C2**, ✅ done 2026-10-13
- Planned-vs-built wording fixed in PRD, Architecture, Design, Rules, TechStack and Phases. AsBuilt is corrected and extended with the target-status table and the λ = 0 consequences. This plan and `ReviewVerification.md` are added.
- **Remaining for C2 after C1 lands:** rebuild the report and README table, retake the waterfall and insights screenshots, and update the demo script (see §4).

---

## 2. Priority 1 — make it operationally valuable (≈ 1–1.5 days)

### P1-1 · Evaluation that respects independence (`§2.4, 2.5, 5.2, 6.2`) — **C1**, 3 h
- Record split counts: `meta.splits = {train|selection|test: {shipments, voyages, snapshots}}`.
- **Voyage-cluster bootstrap** for the MAE improvement CIs (keep the shipment bootstrap as a secondary figure).
- Coverage table with **n snapshots and n voyages** per group, plus a voyage-bootstrap CI on coverage.
- Attribution:
  - report the **ambiguity share** (top-1/top-2 margin < 6 h and < 12 h);
  - report accuracy **per checkpoint** and **excluding ambiguous cases**;
  - also report the `stage_forecast_top1` explainer as an alternative;
  - rename the metric to **"future-stage driver accuracy vs ledger"**.
- **Accept:** these keys exist in `metrics.json`, the report shows n beside every subgroup number, and the CIs widen as expected.

### P1-2 · Label-time embargo (`§2.7`) — **C1**, 1.5 h
- Option `--embargo`: drop training shipments delivered after the first test departure, and also apply this inside the temporal selection slice. Report both "standard" and "embargoed" MAE.
- **Accept:** `metrics.json.robustness.embargo` exists. The report states the difference.

### P1-3 · Structured `data_quality` in every prediction (`§7.1`) — **C1**, 2.5 h
- `data_quality = {last_milestone, last_milestone_age_h, next_expected, next_overdue_h, missing_events, missing_critical (bool), reporting_gap_inferred (bool), source_tier (EDI tier), forecast_issued_at, forecast_age_h, mode: model|propagation_prior|carry_forward, notes[]}`.
- Separate **operational uncertainty** (interval width with perfect data) from **data uncertainty** (flag-driven): expose `confidence.reason` ∈ {`horizon`, `missing_data`, `stale_data`, `fallback`}.
- UI: a small "Evidence" chip row on Shipment Detail.
- **Accept:** a schema test, plus an example in the README API section (C2).

### P1-4 · Alerts as a measured decision tool (`§5.6, 7.2`) — **C1**, 3 h
- **Contract:** `AlertEvent + {reason_code, evidence_ts, previous_risk, new_risk, previous_p_late, new_p_late, recommended_next_step, data_quality_flags}`. Fill `narrative`. Write alerts to the ledger table, or remove the unused tables.
- **Thresholds:** the tier, P(late)-jump and missed-connection thresholds are selected on the **temporal validation slice** (maximise F1 subject to burden ≤ X alerts/100 shipments/day), then frozen for test.
- **Metrics:**
  - precision, recall and **false-positive rate**;
  - alerts per 100 active shipments per day;
  - lead-time distribution (P10, median, P90), measured to the **actual** delivery and to the first time the shipment became late;
  - duplicates suppressed;
  - share of alerts with a feasible action.
- **Accept:** a `decision.alerts` block in `metrics.json` and a model-card row. The UI Alerts page shows reason, evidence time and previous → new risk.

### P1-5 · Advisor with validity, assumptions and uncertainty (`§7.3`) — **C1**, 3 h
- **Per recommendation:**
  - `preconditions`, `assumptions[]`, `limitations`;
  - `baseline {p50, p10, p90, p_late}` and `scenario {…}`;
  - `validity {mechanically_valid, operationally_feasible, economically_justified}`;
  - `benefit_range_h` from re-scoring under 3 sensitivity variants (± external forecast error, ± 6 h timing).
- **Cut-off/deadline feasibility:** customs docs must be filed before arrival; priority berth before discharge; rail → truck before gate-out.
- **UI:** show the three validity ticks. ✅ only when all three hold (today's UI already separates "saves time" ⏱️ from "pays off" ✅).
- **Accept:** unit tests for each validity condition. Advisor fidelity is still reported.

### P1-6 · Richer propagation analysis (`§7.4`) — **C1**, 2.5 h
- δ ∈ {1, 6, 12, 24} h. Condition on `buffer_to_cutoff` (< 6 h "near cut-off" vs ≥ 6 h "comfortable"). Report the median, IQR and n per (lane-group × stage × condition), and the Spearman per δ.
- Insights heatmap shows n per cell; cells with n < 5 are greyed out.
- Fix the docs' δ (the model view in code uses δ = 12 h).
- **Accept:** `propagation_fidelity.by_delta` and `.by_condition` exist. The report shows one small figure: Φ vs δ for the near-cut-off and comfortable conditions.

### P1-7 · Promise date: calibrate or relabel P80 (`§6.4`) — **C1**, 2 h
- **Option A (recommended):** train a q80 residual model, CQR-calibrate it like q10/q90, and use it for the promise. Report P80 coverage and the promise hit rate.
- **Option B:** keep the interpolation, but call it "P80 (normal approximation)" and report empirical P80 coverage.
- Either way, the risk tier source is documented (P50 delay), or switched to P(late) to match the PRD (decision for **YOU**; the default is to document).
- **Accept:** `decision.p80_coverage` exists, and the PRD/Design wording matches.

### P1-8 · Error slices (`§7.7`) — **C1**, 2 h
- MAE, coverage and Brier by **horizon bucket** (remaining planned hours: < 48, 48–168, 168–504, > 504), direct vs transshipment, lane group, carrier EDI tier, destination-congestion regime, and missing-events present or absent. Always show n (voyages/shipments). Suppress groups with fewer than 5 voyages.
- **Accept:** `accuracy.slices` exists. The report gets one small table (horizon × CASCADE vs B1), and the UI Insights accuracy tab gets a horizon chart.

---

## 3. Priority 2 — path to a real product (only if time remains)

| ID | Item | Owner | Notes |
|---|---|---|---|
| P2-1 | **Schedule revisions:** committed vs operational ETA (`§1.5`) | C1 | The simulator emits schedule versions (e.g. a carrier re-plan after a missed connection) with `effective_at`. Snapshots use the version known at `as_of`. Targets: `delay_vs_original_commitment_h` (SLA, unchanged) and `delay_vs_current_plan_h`. Design is documented now; implementation is optional. |
| P2-2 | Reporting **duplicates / corrections / reordering** (`§1.3`) | C1 | Extends P0-5. Ingestion keeps the latest version by `recorded_at`; tests for idempotency. |
| P2-3 | **Simulator sensitivity** (`§7.5`) | C1 | `cascade sensitivity`: vary headway (×0.5/×2), queue severity w0 (±50%), recovery κ (0 / 0.5), reporting latency (×3). Report MAE vs B1/rulebook and coverage per variant. |
| P2-4 | **HTTP-level latency under concurrency** (`§5.7`) | C2 | Run the Locust profile (single worker, 10/50 users) and report p50/p95 per endpoint with the hardware. The in-process figure stays the gate. |
| P2-5 | Durable ledger + drift (PSI) | C1 | SQLite file default, an at-least-once writer, and PSI on key features. |
| P2-6 | Fallback correctness (`§C9`) | C1 | Per-row degradation in batch (not whole batch); make carry-forward reachable and tested; apply the floor. |
| P2-7 | Calibrate mechanics to public data | YOU/C1 | E.g. public port-call dwell distributions, if allowed. Cite sources. |

---

## 4. Order of work and regeneration

```
P0-5 information-time ─┐
P0-6 floor config ─────┤
P0-7 small fixes ──────┼─► P0-1 explanation labels ─► P0-2 identities ─► P0-3 rulebook gate ─► P0-4 targets table
                       │
                       └─► (re-run `cascade all` + `cascade seeds`) ─► C2: build_report.py, screenshots, README, demo
P1-1 … P1-8 in any order after P0; re-run once at the end.
```

**Regeneration checklist (after C1 finishes):**
1. C1: `cascade all --force` and `cascade seeds`; pytest, ruff, mypy, lint-imports green.
2. C2: `python report/build_report.py` (≤ 3 pages, rewrite the §3 "Explanations" bullet to the rulebook/learned split, add the targets-vs-results table); retake screenshots 03–05, 09–11; update `DemoScript.md` (the waterfall legend changes); refresh the README results table.
3. YOU: review the unmet targets, then commit and push. CI must be green.

## 5. Definition of done for v1.1

- [ ] No UI, report or doc text calls a rulebook number a "model contribution".
- [ ] Identity tests (a)–(c) pass, and a broken contribution makes them fail.
- [ ] `metrics.json` includes rulebook MAE, λ, split counts (voyages), targets-vs-results, alert burden/FPR, coverage n, and attribution ambiguity.
- [ ] Reports never become available before their event; the late-report leakage test passes.
- [ ] Model card is generated with original targets, revised gates and status. No `cold_start` or "guarantee" claims.
- [ ] Report is ≤ 3 pages, every number generated, and the unmet targets visible.
