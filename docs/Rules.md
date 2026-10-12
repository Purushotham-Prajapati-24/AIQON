# Rules — CASCADE Engineering, ML & Collaboration Rules

> **As-built note:** implementation details that changed during the build are recorded in [`AsBuilt.md`](AsBuilt.md); where this page and the code disagree, AsBuilt.md is authoritative.
>
> **Review reconciliation (2026-10-13):** an external review was verified claim by claim against the code in [`ReviewVerification.md`](ReviewVerification.md); statements that described the *plan* rather than the build were corrected in place (marked *as built*). Follow-up work is in [`ImprovementPlan.md`](ImprovementPlan.md).

> Non-negotiable rules for everyone (humans and AI assistants) contributing to CASCADE.
> **MUST** = enforced by CI or review. **SHOULD** = strong default; deviations need a one-line justification in the PR.

---

## 1. The Ten Golden Rules

1. **No leakage, ever.** A feature at as-of time *t* MUST use only information available at *t*. All features go through `build_snapshot()`; nothing bypasses it.
2. **One definition of truth.** ETA, delay, stage increment and late are defined only in `domain/delay.py`. Never re-implement them.
3. **Same code offline and online.** Training, evaluation, replay and serving MUST call the same feature and decision functions.
4. **No prediction without uncertainty and a reason.** Every user-facing ETA shows P10–P90 and at least one driver.
5. **Beat the baseline or don't ship.** A model change MUST beat B1 and the current published version on the frozen test split (see §5.4 gates).
6. **Reproducible by seed.** Same seed + config + code ⇒ identical data, metrics and artifacts.
7. **UTC everywhere, hours as the unit.** Timezone-aware datetimes only; convert to local time only for calendar logic and display.
8. **Fail soft, flag loudly.** Degrade to the fallback chain and set `flags.degraded=true`. Never return a 500 for valid input, and never fail silently.
9. **Interfaces are contracts.** Changing a public interface (`domain/`, API schema, artifact manifest) requires an ADR note + version bump + owner approval.
10. **State assumptions explicitly.** Every simulator parameter and modelling assumption is documented in config comments and in the report.

---

## 2. Code Standards

| Topic | Rule |
|---|---|
| Style | `ruff format` + `ruff check` clean (MUST). Line length 100 |
| Types | Type hints on all public functions (MUST). `mypy --strict` on `domain/`, `features/`, `serving/`, `decision/` |
| Naming | `snake_case` functions/vars, `PascalCase` classes, `UPPER_SNAKE` constants. Units in names: `delay_h`, `dist_km`, `cost_usd`, `rho` (0–1) |
| Functions | Pure where possible; ≤ 50 lines SHOULD; no hidden global state except the explicitly loaded `InferencePipeline` |
| Randomness | Only via an injected `np.random.Generator`. **Never** `np.random.seed` or global `random` |
| Datetimes | `pd.Timestamp(tz="UTC")` / `datetime` with `tzinfo`. Naive datetimes are rejected at boundaries (MUST) |
| Config | No magic numbers in code. Parameters live in `configs/*.yaml` with a comment on meaning and unit |
| Errors | Raise domain exceptions (`CascadeError` subclasses); map them to RFC 7807 in `serving/problems.py` only |
| Logging | `structlog` only, JSON, with `request_id` and `model_version`. No `print` in `src/` (ruff rule `T20`) |
| Comments | Explain *why*, not *what*. Every simulator mechanic has a one-line real-world rationale |
| Dependencies | Add only via `uv add`; justify any new runtime dependency in the PR description |
| Imports | Respect the layer order in `.importlinter` (MUST): `domain ← sim, data ← features ← models ← explain ← decision ← eval / serving`. `app/` never imports `cascade.*` except `api_client` types |

---

## 3. Data Rules

1. Raw generated data is **immutable**. `data/raw/<run_id>/` is never edited, only regenerated.
2. Every data read/write passes the **in-house validator** `data/validation.py` (MUST). *As built: CSV/JSON/NPZ; parquet is blocked on the build machine, and Pandera was dropped.*
3. **Invariants asserted on generation:** `Σ ledger hours = total_delay_h` (±1 min); actual timestamps monotone per shipment; `DELIVERED` always present; structural absence ≠ missing.
4. Missingness is **typed**: `structural | mcar | mnar`. Features MUST NOT treat structural absence as NaN.
5. **Splits:** out-of-time test = last 20% by planned departure, frozen per seed in `data/splits/<seed>.json`. CV MUST group by `voyage_id` (as built: greedy voyage→fold assignment), and the test cut MUST keep whole voyages. **The independent unit is the voyage**: report voyage counts per split, and bootstrap CIs SHOULD resample voyages. **Nobody looks at test metrics while tuning.** The test split is evaluated only by `cascade evaluate` on a candidate run.
6. Priors / target encodings are fit **inside each fold** only (MUST); a test verifies OOF construction.
7. External factors for future dates MUST be the noisy *forecast* version, never the realized series.
8. No real personal or company data in the repo. Synthetic only, unless a public dataset's license is recorded in `data/README.md`.

---

## 4. ML Rules

### 4.1 Modelling
- Start with baselines B0/B1/B2. Every new model is reported **next to** them, never alone.
- Every feature MUST be registered in `features/registry.py` with `family`, `stage_group`, `monotone`, `dtype` and a description. Unregistered columns fail the pipeline.
- Monotone constraints are set from **domain knowledge** (registry), not tuned away.
- Prefer simple models: a new model family needs ≥ 5% MAE improvement *with bootstrap CI not crossing 0* to justify its complexity.
- Hyperparameter search, if any, is bounded and seeded (*as built: none; only λ and the P(late) blend are selected on the temporal slice*).

### 4.2 Explainability
- Stage contributions MUST sum (with the base value) to the P50 prediction within 0.1 h, asserted in tests.
- Narratives come from templates only. Any number in a narrative MUST come from the `Explanation` object (test: regex numbers ⊆ facts).
- Every explanation change MUST report **attribution fidelity** before and after.
- Customer-audience text MUST NOT contain carrier/terminal blame or raw feature names.
- Every explanation component MUST be labelled by its source: **observed** (facts), **rulebook** (mechanistic projection), **learned** (ML correction, with its λ), **guardrail** (floor, ordering). A rulebook number MUST NOT be presented as a model contribution.
- No causal claim ("X caused the delay") may rest on feature importance alone. Causal wording is reserved for simulator ledger ground truth or explicit, labelled what-if scenarios.
- Report original targets next to revised gates, with met/unmet status. Never replace a missed target silently.

### 4.3 Evaluation
- Report metrics **by checkpoint**, not just overall.
- Report 95% bootstrap CIs (shipment-level) for headline metrics.
- Report at least these slices: direct vs transshipment, peak vs off-peak, EDI tier.
- Negative results go in the report too (e.g., "stage-chain did not beat global at pre-departure").

### 4.4 Publication gates (`cascade publish`)
| Gate | Hard threshold |
|---|---|
| MAE improvement vs B1 | ≥ 15% |
| P10–P90 coverage (test) | 70–90% |
| Brier (late, τ=24h) | ≤ 0.20 (the PRD target ≤ 0.15 is reported separately as met/unmet) |
| Attribution lift vs lane-history explainer | ≥ 10 pp |
| Waterfall additivity violations | 0 (bookkeeping check; real identity tests: ImprovementPlan P0-2) |
| Latency p95 `/v1/predict` | < 50 ms |
| Regression vs current published | no headline metric worse by > 5% |

---

## 5. API & Serving Rules

1. All routes are versioned under `/v1`. Breaking changes ⇒ `/v2`; additive fields are allowed in v1.
2. Request and response models are Pydantic v2 with examples (they appear in `/docs`).
3. Every response carries `model_version`, `flags`, and headers `X-Request-ID`, `X-Model-Version`, `Server-Timing`.
4. Hot-path rule: **no disk, network or DB I/O inside `/v1/predict`**. Ledger writes are queued asynchronously.
5. Timeouts: internal inference budget 30 ms, then fallback. Webhook calls: 2 s timeout, 3 retries with exponential backoff + jitter.
6. Input limits: ≤ 50 events per shipment, ≤ 1,000 shipments per batch, body ≤ 2 MB.
7. Readiness (`/ready`) is true only after the artifact is loaded, verified (checksums + feature hash) and warmed up.
8. Secrets (API keys, webhook HMAC secret) come from env vars only. `.env` is gitignored, and `.env.example` is committed.

---

## 6. UX Rules

1. Answer first: ETA, range, risk and main driver are visible without scrolling.
2. Colours: Okabe–Ito palette from `app/theme.py` only. **Never colour alone**: pair with icon/text (● ▲ ■).
3. Realized = solid, forecast = hatched, uncertainty = light band, consistently on every chart.
4. Plain language: "Expected", "Likely range", "Main driver". Never "AI thinks", never raw feature names outside the analyst view.
5. Every number has a unit; durations ≥ 48 h are shown in days with 1 decimal.
6. Empty, loading and error states are designed. Degraded predictions show a visible "Reduced confidence" chip with the reason.
7. Every page loads in < 2 s with demo data; interactions < 1 s.

---

## 7. Testing Rules

| Test type | Location | Minimum |
|---|---|---|
| Unit | `tests/unit/` | All `domain/`, `features/`, `decision/` functions; coverage ≥ 85% on these, ≥ 75% overall |
| Property (Hypothesis) | `tests/property/` | No-leakage, `Σ Δ = D`, quantile monotonicity, waterfall additivity, promise hysteresis never flips on unchanged input |
| Integration | `tests/integration/` | `cascade all --n 120` end-to-end in CI (< 90 s) |
| Contract | `tests/contract/` | OpenAPI snapshot diff + schemathesis fuzz: no 5xx |
| Performance | `tests/perf/` | p95 latency assertion for predict (single + batch) |
| Golden | `tests/golden/` | 5 fixed shipments → stored predictions/narratives; diffs require explicit approval |

A bug fix MUST include a test that fails before the fix.

---

## 8. Git & Collaboration Workflow

### 8.1 Branching & commits
- Trunk-based: `main` is always green and releasable. Short-lived branches: `feat/<area>-<desc>`, `fix/...`, `exp/...` (experiments never merge without a results note).
- **Conventional Commits:** `feat(features): add customs_weekend_risk`, `fix(serving): clamp quantiles below overdue bound`.
- PRs ≤ 400 changed lines SHOULD; one concern per PR.

### 8.2 Ownership (CODEOWNERS)

| Path | Owner workstream |
|---|---|
| `src/cascade/domain/`, `docs/Design.md §1` | ML lead (approval required for any change) |
| `src/cascade/sim/`, `data/` | A — Data |
| `features/`, `models/`, `explain/`, `eval/` | B — ML |
| `serving/`, `decision/`, `docker/`, `.github/` | C — Platform |
| `app/`, `report/`, `docs/` UX sections | D — UX & Report |

### 8.3 Pull request checklist (template)
- [ ] Linked ticket ID from `ImplementationPlan.md`
- [ ] Tests added/updated; CI green (lint, types, tests, import-linter)
- [ ] If features/models changed: metrics diff table (vs `main`) attached from `reports/metrics.json`
- [ ] If an interface changed: ADR note + version bump
- [ ] Docs updated (README / relevant `docs/*.md`)
- [ ] No secrets, no data files, no notebook outputs committed

### 8.4 Definition of Done
A ticket is done when the code is merged, tests pass, docs are updated, the acceptance criteria in `ImplementationPlan.md` are demonstrably met, and (for ML changes) the metrics are recorded in the run log.

### 8.5 Communication cadence (3-day sprint)
- Stand-ups at the start of each day and at mid-day (10 min): yesterday / today / blockers / gate status.
- **Interface freeze** at the end of Day 0. Changes after that need agreement from all affected owners.
- **Gate reviews** at the end of each day (see `Phases.md`). A failed gate triggers the pre-agreed cut list.

---

## 9. Security & Responsible AI

- Dependency audit (`uv pip audit` or `pip-audit`) in CI; no known-critical CVEs.
- Containers run as non-root with a read-only artifacts volume.
- The model card documents intended use (decision *support*), out-of-scope use (automated contractual penalties), known weak slices and synthetic-data limitations.
- Advisor outputs are labelled **advisory**. No automatic execution of actions.
- Cost figures are labelled **illustrative** unless configured with real tariffs.

---

## 10. Rules for AI Coding Assistants

1. Read `docs/Design.md` §1–§5 before touching features or models.
2. Never generate features outside `features/registry.py`, and never compute a feature from the target or future events.
3. Never weaken a test or a quality gate to make CI pass. Fix the cause or escalate.
4. Keep diffs minimal and scoped to the ticket. Don't reformat unrelated files.
5. When uncertain about a domain behavior, add a config parameter with a documented default rather than hard-coding it.
