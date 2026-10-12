# External Review — Claim-by-Claim Verification

> **What this is.** An external reviewer (ChatGPT) read the ten documentation files, **not the code**, and produced a design/ML review. Every technical claim was checked against the code (`src/`, `app/`, `tests/`) and the results files (`reports/metrics.json`, `reports/seeds.json`, model v1.0.0, seed 42) on 2026-10-13. Line references are `src/cascade/…` unless stated.
> **Verdicts:** ✅ **Confirmed** (the code has the problem) · 🟡 **Partly** (real, but narrower or different than stated) · ❌ **Not confirmed** (the code already handles it, or the claim rests on a stale or wrong doc) · ➕ **New** (found during verification; the reviewer could not see it).
> The resulting work is planned in [`ImprovementPlan.md`](ImprovementPlan.md).

> **Resolution (v1.1.0, 2026-10-13):** the verdicts below describe **v1.0.0**. The fixes are tracked in [`ImprovementPlan.md`](ImprovementPlan.md) → *Status*, with results in [`AsBuilt.md`](AsBuilt.md) §8. In v1.1:
> - information time (§1.1–1.4), explanation honesty and real identities (§4), split and evidence reporting (§2.4–2.7, §5.2, §6.2), alert burden (§5.6), advisor validity (§7.3), propagation by shock size (§7.4), `data_quality` (§7.1) and parameter sensitivity (§7.5) are **fixed**;
> - schedule revisions (§1.5), calibrated P80 (§6.4), error slices (§7.7) and validation-tuned alert thresholds remain **open** and are documented.

## Bottom line

The review is **mostly right, and in its most important point it understates the problem.** The verification found:

1. **On seed 42 the ML does not move the P50 at all.** Temporal validation chose λ = 0 for the learned median correction (validation MAE 24.64 h at λ = 0, rising to 26.00 h at λ = 1). So the CASCADE P50 *is* the operator-rulebook projection plus the ETA floor. On the test set the **rulebook alone is slightly better** (MAE 24.447 h vs CASCADE 24.500 h). The headline "36% better than carry-forward" is a **rulebook** result. No gate compares CASCADE with the rulebook.
2. **Because λ = 0, the "SHAP" explanation is the rulebook.** `contributions()` multiplies every learned SHAP term by λ (`models/predictor.py:150-156`). The waterfall's forecast bars and the "root-cause" ranking are therefore the rulebook's per-stage projections (`proj_inc_*`), but the UI, report and docs label them "exact, additive model contributions". The "Typical remaining delay" bar is always 0 h. The additivity test cannot fail, because a residual "guardrail" row absorbs any difference.
3. **Several original targets are unmet** and are currently presented only through revised gates: Brier 0.182 vs ≤ 0.15, root-cause top-1 42% vs ≥ 70%, promise flip ratio 0.83 vs ≤ 0.40, and post-customs coverage 89% vs 80 ± 5.
4. **The planning docs still describe the planned system** (Parquet/Pandera, `GroupKFold(shipment_id)`, an asyncio ledger, monotone quantile models, a "coverage guarantee", old gates). This page and the doc edits made alongside it fix those.

Three review points are **not confirmed**: the delay identity is anchored correctly; the root README is a full quick start (the reviewer saw `docs/README.md`, the docs index); and latency *is* measured and reported. A fourth is only partly right: a rulebook-only baseline exists, but only in the report and not as a gate.

---

## 1. Data availability and time semantics (review §2.1–2.2)

| # | Review claim | Verdict | Evidence | What the code actually does |
|---|---|---|---|---|
| 1.1 | Events lack a "when we learned it" timestamp | 🟡 Partly | `sim/generator.py:235-261`, `features/dataset.py:42-46`, `features/snapshot.py:122,180,186` | A `reported_h` column exists, but it is **occurrence time ± U(−0.75, +0.75) h** jitter. One number serves as both "when it happened" (the delay calculation) and "when we knew" (the `t ≤ as_of` filter). There is no reporting latency and no ingest time. |
| 1.2 | Snapshots use `actual + 1 min`, so events are "known" at occurrence | 🟡 Partly | `features/dataset.py:69-86` | The training checkpoint is `reported_h + 1 min`, so events become known within about 45 min of occurrence. Negative jitter can make a report **precede the physical event** (up to 0.75 h). Mid-stage samples are placed using *true* actual times. |
| 1.3 | No delayed, duplicated, reordered or corrected messages | ✅ Confirmed | `sim/generator.py:238-250`, `data/validation.py:63-64`, `serving/schemas.py:52-57` | Only a present/missing Bernoulli per event (MCAR 6% + EDI-tier MNAR 0/8/25% + congestion-MNAR on discharge). Missing is permanent. Reports are strictly ordered, and the API rejects disorder. |
| 1.4 | Leakage test would not catch late-arriving reports | ✅ Confirmed (➕ sharper) | `tests/property/test_no_leakage.py:17-41` | The test perturbs reports timestamped after `as_of`. Because `reported_h` *is* the truth, the scenario the reviewer asks for (a report available after `t` for an event that happened before `t`) cannot even be expressed. |
| 1.5 | No schedule revisions; no committed vs operational ETA | ✅ Confirmed | `sim/mechanics.py:144-170`, `sim/generator.py:79-83,143-145` | One plan per shipment, never revised. `late = D > 24 h` is measured against the **original** plan, which is the correct SLA baseline. The customer "promise" is derived from predictions, not a schedule version. |

## 2. Validation design (review §2.3)

| # | Review claim | Verdict | Evidence | What the code actually does |
|---|---|---|---|---|
| 2.1 | Grouping is inconsistent (shipment vs voyage) | 🟡 Docs only | `data/splits.py:31-58`, `models/train.py:119-134,203-213` | **The code is consistent and voyage-grouped everywhere:** a greedy voyage→fold assignment for OOF predictions and priors (5 folds of 16–17 voyages), voyage-cut CQR, and a voyage-cut test split. Only the *docs* disagree (`Architecture.md`, `PRD.md` said `shipment_id`). Fixed in the docs. |
| 2.2 | Split must be assigned before snapshot expansion | ❌ Not confirmed | `data/splits.py:31-43`, `models/train.py:201-202` | Rows are split by `shipment_id`, and train/test voyage overlap is 0. Seed 42: train 238 shipments / 83 voyages / 2,671 snapshots; test 62 / 20 / 726. |
| 2.3 | No separate calibration set | ✅ Confirmed (by design) | `models/train.py:148-190,229-235`, `models/conformal.py:15-30` | The CQR offset = max(OOF offset, offset on the latest 20% of training voyages), per checkpoint group. λ and the P(late) blend are chosen on that same temporal slice (50 shipments / 18 voyages), with selection models fit on the earlier 80%. The final model is then refit on 100% of training. |
| 2.4 | Bootstrap treats snapshots as independent | 🟡 Partly | `eval/evaluate.py:49-70` | The bootstrap resamples **shipments** (all of a shipment's snapshots together), not snapshots. But voyages correlate shipments, and the test set has only **20 voyages**, so the CIs are probably too narrow. |
| 2.5 | Independent-unit counts not reported | ✅ Confirmed | `eval/evaluate.py:165-166` | `metrics.json` records only test rows (726) and shipments (62). There are no voyage or train counts. |
| ➕ 2.6 | — | **New** | `models/train.py` (selection vs final) | The P(late) blend weight is selected using the **raw** classifier, but the final model blends the **isotonic** classifier. Selection and deployment differ. |
| ➕ 2.7 | — | **New** | `data/splits.py` | The test cut is by *departure*. Some training shipments are delivered (their labels realised) **after** the first test departures. A live system at that moment would not yet know those labels. An embargo is needed for a strictly causal out-of-time estimate. |

## 3. Delay math, bounds and guardrails (review §2.4)

| # | Review claim | Verdict | Evidence | What the code actually does |
|---|---|---|---|---|
| 3.1 | Σ Δ_k = d_n − d_0, so it is only correct if d_0 = 0 | ❌ Not confirmed | `domain/delay.py:44-48`, `sim/mechanics.py:373-376` | Both start from `prev = 0`, so the first increment is d_0 itself (stage `PRE_CARRIAGE`, its own ledger entry, cause `shipper_late`). Σ Δ = d_n = D **exactly**. d_0 ≠ 0 in general (gate-in lateness), which is precisely why it is included. Tested in `tests/unit/test_domain.py:34-48`. Only the docs needed the precondition stated. |
| 3.2 | "Final delay ≥ now − planned(next)" is not a valid bound | 🟡 Docs only | `features/snapshot.py:197-207,309-310` | The code applies it to the **next milestone only**, inside the rulebook projection, not as an output clamp. It is skipped when a reporting gap is inferred (e.g. overdue > 48–120 h depending on the event). PRD/Design wording was stale. Fixed. |
| 3.3 | ETA floor `as_of + 0.5 × planned remaining` is a heuristic | ✅ Confirmed (➕ docs had the formula wrong) | `features/snapshot.py:392-396`, `models/predictor.py:111-120` | The actual rule is **ETA ≥ max(as_of, t_last + 0.5 × (planned_DELIVERED − planned_last))**. The 0.5 is a hard-coded literal. No test, ablation or metric measures how often it binds or what it does to coverage. The fallback path does not apply it. |
| 3.4 | Post-processing must be tested | 🟡 Partly | `tests/property/test_model_invariants.py:16-28,49-67` | Quantile order and `ETA ≥ as_of` are tested. The floor is not. Coverage **is** measured on the final post-processed output (good). |

## 4. What the explanation explains (review §2.5)

| # | Review claim | Verdict | Evidence | What the code actually does |
|---|---|---|---|---|
| 4.1 | SHAP of a residual model does not explain the combined prediction | ✅ Confirmed, and **worse than stated** | `models/predictor.py:87-97,150-156`, `explain/explainer.py:237-246`, `reports/metrics.json` `model_selection.shrink = 0.0` | `contributions()` = λ × SHAP(q50 residual) + the rulebook `proj_inc_*` per stage. **At λ = 0 the forecast bars are exactly the rulebook projection.** Nothing in the waterfall, narrative, UI caption or report says so ("◦ forecast contributions by stage (exact, additive)"). The learned correction is never shown separately. |
| 4.2 | The waterfall needs realised / projection / learned / uncertainty components | ✅ Confirmed | `explain/explainer.py:82-100,237-246` | Realised bars exist (per observed milestone). "Typical remaining delay" = λ × SHAP bias = **0.0 h at λ = 0**, shown anyway with a misleading label. A "Consistency guardrail" row absorbs the ETA floor and the quantile sort. |
| 4.3 | The additivity identity must be testable | ✅ Confirmed (➕ the current test is a tautology) | `tests/property/test_model_invariants.py:49-55` | The test sums the waterfall rows to P50, but the guardrail row is *defined* as the remainder, so it **can never fail**. The real identities exist elsewhere: `test_contributions_sum_to_raw_p50` and `test_stage_forecast_reconciles_to_p50`. The `0 / 261 additivity violations` headline therefore proves bookkeeping, not fidelity. |
| 4.4 | Drivers / root cause are computed from what? | ➕ New detail | `explain/explainer.py:61-78`, `decision/engine.py:188` | Drivers and `root_cause_group` come from `contributions()`, i.e. the rulebook at λ = 0. The reconciled **stage-forecast models**, a genuinely learned component, feed `stage_forecast_hours`, cost and the fleet's main stage, and are slightly *better* at root cause (top-1 44.7% vs 42.4%). |

## 5. Root-cause claims and acceptance criteria (review §2.6, §2.8)

| # | Review claim | Verdict | Evidence |
|---|---|---|---|
| 5.1 | 42% top-1 misses the original 70% target | ✅ Confirmed | PRD G4 (≥ 70% / 80%) vs `metrics.json` 0.424. The replacement gate (lift ≥ 10 pp vs lane history) passes on seed 42 (+16 pp) but the 5-seed mean is **+9 ± 7 pp**, so it does not pass on every seed. |
| 5.2 | Label definition must be explicit | 🟡 Partly | `features/dataset.py:112-116`, `eval/evaluate.py:195-262` | The label is the argmax of the **net** future-stage ledger increments (stages after the last reported event). It is counted only if above 6 h, at checkpoints ≤ 4. This is well-defined, but **ambiguity is not reported**: of 347 scored snapshots, **25%** have a top-1/top-2 margin under 6 h and **50%** under 12 h. Results are pooled across checkpoints, and units are correlated snapshots. |
| 5.3 | "Root cause" conflates three concepts | ✅ Confirmed | — | Realised largest increment, predicted future driver, and intervention effect are all called "root cause" or "driver" in UI and docs. |
| ➕ 5.4 | — | **New** | `eval/evaluate.py:253` | `confusion_true_vs_shap` is transposed: the outer keys are the *predicted* group. |
| 5.5 | Brier 0.182 misses the PRD's 0.15 | ✅ Confirmed | Seed 42 = 0.182, 5 seeds = 0.163 ± 0.019 (only seed 7 < 0.15). The gate was loosened to ≤ 0.20. |
| 5.6 | Alert lead time needs precision, FP and burden | 🟡 Partly | `eval/evaluate.py:373-434` | Recall (1.0), precision (0.795), ≥ 48 h share (0.968), median lead (814 h) and alerts per shipment (3.37) **are** reported. Missing: FPR, alerts per 100 shipments per day, lower lead percentiles, dedup counts. ➕ Lead time is measured to **planned** delivery from a replay starting at booking − 72 h, which inflates it. Thresholds are hard-coded, not chosen on validation. |
| 5.7 | Latency has no measured benchmark | ❌ Not confirmed | `eval/pipeline.py:223-247`, `tests/perf/test_latency.py` | p50 7.2 ms / p95 8.5 ms (`checks`) and a perf test with a 50 ms budget exist. 🟡 Scope is narrow: in-process, sequential, one repeated request, no HTTP or concurrency. The Locust profile exists, but its results are not reported. |
| 5.8 | Need a rulebook-only comparison | 🟡 Exists, not used | `eval/evaluate.py:105-111` | The rulebook MAE is in `metrics.json` and report Table 2, but not in the headline, gates, model card or `seeds.json` (per-seed λ and rulebook MAE are not recorded). |
| ➕ 5.9 | — | **New** | `metrics.json` `decision.promise_flip_ratio` = 0.83 | The PRD requires promise changes ≤ 40% of raw P50 changes. AsBuilt replaced this with hit rate and reversals, so the unmet original target is not shown anywhere. |

## 6. Uncertainty claims (review §2.7)

| # | Review claim | Verdict | Evidence |
|---|---|---|---|
| 6.1 | Coverage "guarantee" wording is too strong | ✅ Confirmed (docs only) | `PRD.md` D6 said "with a coverage guarantee on the hold-out". No generated text says "guarantee". Fixed to "empirical held-out coverage". |
| 6.2 | Report width and counts with coverage | 🟡 Partly | `eval/evaluate.py:126-135` | Coverage **and** mean width are reported per group (pre-departure 77.5% / 158 h, at sea 78.1% / 114 h, at port 84.5% / 54 h, post-customs 88.9% / 13 h). **Group n is not reported** (129 / 270 / 219 / 108 snapshots). There is no voyage-clustered CI. |
| 6.3 | Evaluate the post-processed output | ❌ Already done | `models/predictor.py:99-127` | Coverage is measured on the final output (offsets → sort → floor → delivered override). |
| 6.4 | P80 cannot come from P50 and P90 | ✅ Confirmed | `decision/promise.py:8-10,35-49` | `P80 = P50 + 0.657 × (P90 − P50)`: a normal approximation applied to conformal-widened bands. The promise hit rate (87.3%) is measured, but P80 itself is not calibrated. ➕ The risk tier comes from P50 delay, not from P(late) as the PRD says. |
| 6.5 | Metric CI vs prediction interval vs scenario sensitivity | 🟡 Wording | — | The report and README keep them apart. The PRD's "Trustworthy uncertainty" did not. |

## 7. Product additions (review §3)

| # | Review suggestion | Verdict | Evidence |
|---|---|---|---|
| 7.1 | Structured `data_quality` in the response | ✅ Missing | `decision/engine.py:238-244,271-277` | Only `flags {degraded, reason, cold_start, missing_events, out_of_distribution}`. ➕ `cold_start` is **hard-coded False**, yet the model card says cold-start lanes are "served with fallbacks and a `cold_start` flag". In fact unknown lanes are rejected with 422. There is no milestone age, forecast age or source reliability. Missing events become visible only once a later event arrives. |
| 7.2 | Alert explanation contract | ✅ Missing | `decision/alerts.py:26-33` | `AlertEvent` has `alert_id, shipment_id, rule, severity, created_at, message`. There is no reason, evidence timestamp, previous/new risk, next step or data-quality flag. `narrative` is always `""`. The `alerts`/`promises` ledger tables are never written. |
| 7.3 | Advisor validity, assumptions and uncertainty | 🟡 Partly | `decision/advisor.py:29-150` | The advisor has a `feasible_reason`, stage-based feasibility and a 5-action menu with costs. It has no assumptions field, no scenario interval or P(late)-before per action, no cut-off/deadline checks and no sensitivity across scenarios. Validity is not split into mechanical / operational / economic. |
| 7.4 | Propagation Φ across δ sizes and conditions | ✅ Confirmed | `eval/evaluate.py:279-322` | A single δ = 12 h, a mean matrix with no counts, and no "near cut-off" vs "comfortable buffer" split. Some cells are negative (Φ_true = −1.94). The docs said δ = 6 h for the model view. |
| 7.5 | Simulator parameter sensitivity | ✅ Missing | `cli.py:61-90` | Seeds vary only the RNG (and skip robustness and ablations in `fast` mode). |
| 7.6 | Ledger interaction-allocation policy | 🟡 Partly | `sim/mechanics.py:253-384` | The policy is deterministic (each interaction is booked wholly to one tag: berth congestion × lateness → `berth_window_miss`; a hub miss → `missed_connection[_hub_congestion]`; a late weekend arrival → `weekend_holiday_closure`; remainder → `other`) but it is undocumented. Now documented in `Design.md` §2.2. |
| 7.7 | Slices by horizon, route type, lane, carrier, data quality | ✅ Mostly missing | `eval/evaluate.py:113-152` | Only by checkpoint and by missingness rate. |
| 7.8 | Ledger is best-effort | ✅ Confirmed | `decision/ledger.py:38-88`, `serving/app.py:75` | A bounded `queue.Queue(10_000)` with drop-and-count and a daemon thread. The default DB is **`:memory:`** (not durable), and `close()` can lose queued rows. Now documented as best-effort telemetry. |
| 7.9 | Transport scope | ✅ Confirmed | `domain/network.py` | Ocean lanes only. Rail and truck appear only as the inland final leg. There is no air. Wording clarified. |

## 8. Documentation consistency (review "P0 — documentation problem")

| Location | Claim | Verdict | Action taken on 2026-10-13 |
|---|---|---|---|
| PRD R1/R2, Architecture §4.1/§6.3, Design §3, Rules §3, Phases | Parquet + Pandera | ✅ | Rewritten to CSV/JSON/NPZ + `data/validation.py` |
| Architecture §4.1, PRD risks, ADR | `GroupKFold(shipment_id)` | ✅ | Rewritten to voyage-grouped folds + voyage-cut test |
| TechStack §1 | `shap` dependency, Optuna | ✅ | `shap` is not a dependency (LightGBM `pred_contrib` only); Optuna not used |
| Design §6.2, Phases P2, TechStack | Monotone quantile models | ✅ | Constraints apply to the late classifier only. ➕ With `feature_fraction = 0.8`, LightGBM silently downgrades the `advanced` method to `basic`, and the rulebook features are unconstrained. The code comment promises a "monotonicity audit" that **does not exist**. |
| AsBuilt "LightGBM forbids monotone + quantile" | Too broad | 🟡 | The installed **4.7.0** binary does contain the fatal error `Cannot use monotone_constraints in %s objective` for objectives that renew leaf output (quantile/L1). The claim holds for this version, but no test pins it. Reworded to cite version and message. |
| Architecture §4.3, Design §11.6 | asyncio ledger | ✅ | Thread + bounded queue, best-effort, in-memory by default |
| PRD G2/G4, Phases Gate 2 | Original targets vs results | ✅ | Status column added (met / unmet / revised) in PRD and AsBuilt |
| README | "Only a docs index" | ❌ | The reviewer saw `docs/README.md`. The root `README.md` already has the quick start, results, Docker and tests. |

---

## 9. What the review got wrong or overstated

- **d₀ anchoring (§2.4):** already correct in code and tests; only the docs needed the precondition stated.
- **README:** the full quick start exists at the repo root.
- **Latency:** measured (p95 8.5 ms in-process). What is missing is HTTP/concurrency figures, not a benchmark.
- **Rulebook-only comparison:** exists (report Table 2); the gap is that it is not a headline or gate.
- **Snapshot/split leakage across voyages:** the code is voyage-safe; only the docs were inconsistent.
- **Coverage on post-processed output:** already the case.

## 10. What the review missed

- λ = 0 makes the P50, the waterfall *and* the root-cause metric all rulebook outputs, and the rulebook alone beats CASCADE by 0.05 h MAE (4.1, 5.8).
- The waterfall additivity test is a tautology (4.3).
- Reports can precede the event they describe (1.2).
- `cold_start` is hard-coded and the model card's cold-start claim is false (7.1).
- Selection/deployment mismatch in the P(late) blend (2.6), and the label-time embargo (2.7).
- The transposed confusion matrix (5.4), the unmet promise flip-ratio target (5.9), and the non-durable in-memory ledger (7.8).
