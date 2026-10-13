# ML optimisation study (released as v1.3.0)

> Developed as "v1.2" against v1.1.0. Meanwhile upstream published its own v1.2.0 (same code
> outputs as v1.1 plus an actionable-F1 alert threshold, the same idea as section 6), so this work
> was rebased on it and released as **v1.3.0**. Tables below say v1.1 → v1.2 for the study itself;
> the release comparison against upstream v1.2.0 is at the end (`vs_upstream_v120.txt`).

Goal: clean the data properly, try a wide range of models, keep only what measurably helps
**out-of-time**, and avoid overfitting a 20-voyage test set.

## Protocol (why the numbers can be trusted)

| Set | Worlds | Used for |
|---|---|---|
| **Dev** | 20 fresh simulator seeds (101–120), each with its own out-of-time test split (~20 voyages / ~700 snapshots) → ~400 test voyages in total | every modelling and cleaning decision |
| **Holdout** | the 5 canonical seeds (7, 11, 23, 42, 99) | touched once, at the end (`cascade seeds`) |

* Inside a world, nothing ever sees that world's test split: priors are out-of-fold, λ / P(late)
  stack / conformal offsets are fit on voyage-grouped out-of-fold predictions or the temporal slice.
* Cleaning parameters were selected on the **training** split of the dev worlds (test only reported).
* Every comparison is paired per world and reported as mean ± standard error with a win count.

## Scripts

| Script | What it does |
|---|---|
| `build_worlds.py` | simulate + cache snapshot rows/splits for dev and holdout worlds |
| `audit.py` | data audit and error diagnostics (dev only); outputs in `audit_*_cleaning.txt` |
| `sweep_holds.py` | coordinate descent over the "silence = missing report" caps (train-split selection) |
| `bakeoff.py`, `bakeoff2.py` | P50 point-forecast bake-offs (GBMs, RF, ExtraTrees, linear-leaf trees, LP median / lasso regression, calibrated rulebook, λ selection, stacking) |
| `cls_bakeoff.py` | P(late) bake-off (isotonic GBM, empirical residual distribution, stacks) |
| `interval_bakeoff.py` | P10–P90 bake-off (Winkler interval score) |
| `prod_ref.py` | trains the real production pipeline per world under v1.1 / v1.2 / ablation configs |
| `runner.py` | per-world process runner + summaries (`python runner.py summary <module> <tag>`) |

Environment notes: sklearn's tree/linear modules are blocked by Windows Application Control on
the development machine, so linear models are solved as linear programs (scipy HiGHS) and
forests use LightGBM's `rf` / `extra_trees` modes. Run everything with `PYTHONUTF8=1`.

## Findings

### 1. Data audit and cleaning: the biggest single win, with no rows deleted

* Clean at row level: no duplicates; the only NaNs (`hours_since_last_event`, 9%) are structural
  (no milestone yet at booking) and are kept as information.
* "Outliers": the residual (truth − rulebook) is zero-inflated (49% exactly right) with quantised
  ±24 h jumps (kurtosis 37). A textbook 5×MAD rule flags **40% of rows**; they are real customs
  inspections and missed connections, so deleting them would delete the signal.
* The real data-quality problem was **missing EDI messages read as lateness**. With 6–31% of
  milestone reports missing, the snapshot builder treated silence as "still waiting":
  * at the hub it had **no cap at all**, so a missing hub-departure report became up to ~550 h of
    phantom hub delay (rulebook MAE 302 h vs 43 h for carry-forward on those rows);
  * for vessel arrivals / discharge / gate-out, 72–120 h caps let silence cascade into
    projected missed connections (median residual −8 to −24 h).
* Fix (in `features/snapshot.py`): silence past one headway at the hub, or past a 12 h grace
  window for ocean arrivals, discharge and gate-out (24 h at origin departure), is a reporting
  gap. The caps were chosen by coordinate descent on the **training** split (`sweep_holds.py`).

| Rulebook MAE on 20 dev worlds | train | test |
|---|---|---|
| v1.1 features | 19.00 h | 21.54 h |
| + hub cap (one headway) | 17.63 h | 20.10 h (better in **20/20** worlds) |
| + tuned grace windows (v1.2) | **17.18 h** | **19.68 h** (−8.6%) |

### 2. Point forecast (P50): the cleaned rulebook is already at the ceiling

Every learned correction was tried on top of the cleaned rulebook, each with λ fixed or picked
by voyage-grouped CV (global and per journey phase): LightGBM (quantile / Huber / L1, with heavy
regularisation, recency weights, without drifting external features), LightGBM random forest,
ExtraTrees and linear-leaf trees, L1-penalised linear median regression (LP), a per-component
calibrated rulebook (LP), per-checkpoint median shifts, and stacking (median-regression and
convex-weight meta-learners over all of them). **Best: +0.09% ± 0.20%, i.e. zero.** Even an
oracle that picks λ on the test set gains only 0.64%. The residual is mostly irreducible
(random inspections, missed slots) at the median.

λ selection matters: v1.1's temporal-slice rule picked λ > 0 in 9/20 worlds and cost +1.8% MAE.
v1.2 averages the temporal slice and the out-of-fold curve and requires a ≥1% gain, which
replays to exactly λ = 0 in all 20 worlds (`compare_prod.py`).

### 3. P(late): stacking two complementary models

| Model (20 dev worlds, out-of-time) | Brier | PR-AUC | ROC-AUC |
|---|---|---|---|
| GBM + isotonic | 0.177 | 0.776 | 0.809 |
| empirical residual distribution around the rulebook | 0.153 | 0.836 | 0.858 |
| **logistic stack (empirical + GBM)**, shipped | **0.147** | **0.852** | **0.866** |
| phase-specific stack (9 more coefficients) | 0.147 | 0.853 | 0.865 (not worth the extra parameters) |

### 4. Intervals: decouple the band from λ

v1.1 built P10/P90 as `rulebook + λ·g50 + (g_k − g50)`; with λ ≈ 0 that subtracts the unused
learned median and mis-centres the band. v1.2 uses `rulebook + g_k` (then the same drift-aware
conformal calibration): **interval score −4.5% ± 1.1% (better in 18/20), 4.8% narrower at the
same 80% coverage.**

### 5. Production pipeline, v1.1 vs v1.2, paired on 20 dev worlds (`prod_ref.py`)

| | v1.1 | v1.2 | change |
|---|---|---|---|
| MAE | 19.98 h | **19.66 h** | −1.6% (on top of the cleaning) |
| Brier | 0.154 | **0.147** | −4.6% ± 1.2% (17/20) |
| PR-AUC | 0.838 | **0.852** | +1.7% (16/20) |
| interval score | 123.8 | **117.9** | −4.5% (18/20) |

### 6. LATE alerts: tune for the lead-time goal

The sharper P(late) moved the F1-tuned alert threshold to 0.9: precision went up but alerts came
later (≥48 h lead fell). v1.2 tunes the threshold for F1 with *timely* recall (alerted ≥ 48 h
before planned delivery, the product goal G6a) and takes the strictest threshold within 0.01 of
the best. On 6 dev worlds (full pipeline, `ab_pipeline.py`): alerted ≥48 h ahead **53% → 73%**,
alerts per 100 shipment-days 9.1 → 8.4, promise flip ratio 0.85 → 0.80; **cost:** late-alert
false-positive rate 14% → 24%. This is a deliberate trade-off toward earlier warnings.

### 7. Holdout confirmation

The 5 canonical seeds were run once, after every decision above was frozen (`cascade seeds`;
`compare_holdout.py` → `holdout_summary.txt`). Mean ± sd over seeds, v1.1 → v1.2:

| Metric | v1.1 | v1.2 | better in |
|---|---|---|---|
| ETA MAE | 26.10 ± 4.53 h | **23.94 ± 3.55 h** (−8.3%) | **5/5** |
| MAE improvement vs carry-forward | 27.5% ± 6.4% | **33.6% ± 3.6%** | 5/5 |
| Brier P(late > 24 h) | 0.166 | **0.155** | 4/5 |
| PR-AUC P(late) | 0.867 | **0.884** | 5/5 |
| P10–P90 coverage (target 80%) | 81.2% | 81.4% | – |
| Late-alert false-positive rate | 42.0% | **26.3%** | 5/5 |
| Promise hit rate | 86.6% | **90.7%** | 5/5 |
| Root-cause top-1 vs cause ledger | 46.9% | **49.3%** | 5/5 |
| Late shipments alerted ≥ 48 h ahead | 86.3% | 71.1% | 0/5 |

The gains replicate out-of-sample and the seed-to-seed spread shrinks. The alert trade-off went the
other way from the dev worlds here (fewer false alarms, somewhat later alerts); it still meets the
≥ 70% goal but with little margin, and it is the first thing to revisit.

**Sensitivity** (7 worlds whose mechanics differ from the rulebook's assumptions, seed 42): MAE
better or equal in 5/7 (reporting latency ×3: 25.9 → 24.5 h), Brier better in 5/7, coverage up in
5/7. Worse when connection headways double (MAE +1.2%, Brier 0.179 → 0.202) or hub congestion
doubles (MAE +1.8%): the hub cap trusts the network's headway, so it needs accurate schedules.

### What did not work (and is not shipped)

* Any learned correction to the P50 (see 2): kept switchable, but off unless it clears a 1% gain.
* Deleting "outlier" rows, winsorising, recency weighting, dropping drifting features,
  phase-specific P(late) coefficients: no out-of-time gain.

### Next steps worth trying

* Vessel-level milestones shared across co-loaded shipments (new information, not a new model):
  most remaining error sits in silent/missing reports.
* Make the hub cap use the carrier's published schedule rather than the static network headway.
* A cost-weighted alert objective (value of lead time vs cost of a false alarm) instead of F1.


### 8. Release comparison: upstream v1.2.0 → v1.3.0 (5 holdout seeds)

| Metric | v1.2.0 | v1.3.0 | better in |
|---|---|---|---|
| ETA MAE | 26.09 h | **23.94 h** | 5/5 |
| MAE improvement vs carry-forward | 27.7% | **33.6%** | 5/5 |
| Brier P(late) | 0.165 | **0.155** | 4/5 |
| PR-AUC P(late) | 0.868 | **0.884** | 5/5 |
| Alerted ≥ 48 h ahead | 59.9% | **71.1%** | 3/5 |
| Late-alert false-positive rate | 25.0% | 26.3% | 2/5 |
| Root-cause top-1 | 47.0% | **49.3%** | 5/5 |
