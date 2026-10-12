# Tech Stack — CASCADE

> **As-built note:** implementation details that changed during the build are recorded in [`AsBuilt.md`](AsBuilt.md); where this page and the code disagree, AsBuilt.md is authoritative.
>
> **Review reconciliation (2026-10-13):** an external review was verified claim by claim against the code in [`ReviewVerification.md`](ReviewVerification.md); statements that described the *plan* rather than the build were corrected in place (marked *as built*). Follow-up work is in [`ImprovementPlan.md`](ImprovementPlan.md).

> Every choice is justified against the drivers: **small data, explainability, low latency, reliability, 3-day delivery, many contributors.**
> Exact versions are pinned in `uv.lock` at project init; the minimums below are the versions the design was validated against.

---

## 1. Summary

| Layer | Choice | Min version | Why this (and not that) |
|---|---|---|---|
| Language | **Python** | 3.12 | Best ML ecosystem; 3.12 is faster than 3.11 and widely supported by all deps |
| Env & packaging | **uv** + `pyproject.toml` (hatchling) | 0.4 | 10–100× faster installs than pip/poetry, lockfile, cross-platform (Windows reviewers) |
| Dataframes | **pandas** | 2.2 | Team familiarity; CSV/JSON/NPZ IO (parquet DLLs are policy-blocked on the build machine). *Polars* reserved for scale |
| Numerics | **NumPy**, **SciPy** | 1.26 / 1.13 | Simulator distributions, vectorised features |
| Data validation | **In-house validator** (`data/validation.py`) | — | Schema + invariants at every IO boundary (Pandera dropped: see AsBuilt.md) |
| Gradient boosting | **LightGBM** | 4.3 (4.7.0 installed) | Native quantile objective, categorical support, fast exact TreeSHAP (`pred_contrib`), sub-ms inference. Monotone constraints on the **late classifier only**: 4.7 rejects them for leaf-renewing objectives (quantile, L1) |
| ML utilities | **scikit-learn** | 1.5 | Isotonic calibration, metrics (voyage-grouped folds are built in `data/splits.py`, not with `GroupKFold`) |
| Explainability | **LightGBM `pred_contrib`** (exact TreeSHAP in C++) | — | *As built:* `shap` is **not** a dependency. Contributions are summed by stage group and added to the rulebook's per-stage projection. At λ = 0 the forecast bars are the rulebook alone (AsBuilt §6) |
| Conformal | **In-house CQR** (~60 LOC) | — | Transparent and dependency-free; MAPIE considered but unnecessary |
| Tuning | **None in v1.0** | — | *As built:* library defaults + temporal-validation selection of λ and the P(late) blend. Optuna was dropped to avoid overfitting a 238-shipment training set |
| API | **FastAPI** + **uvicorn[standard]** | 0.111 / 0.30 | Async, OpenAPI docs for free, Pydantic v2 integration |
| Schemas/config | **Pydantic v2** + **pydantic-settings** | 2.7 / 2.3 | Rust-core validation speed; one schema language for API + config |
| Serialisation | **orjson** | 3.10 | Fastest JSON for responses; native datetime/NumPy support |
| Ledger store | **SQLite (WAL)** via `sqlite3` / **aiosqlite** | stdlib / 0.20 | Zero-ops persistence for predictions/alerts/promises; swappable for Postgres |
| HTTP client (UI) | **httpx** | 0.27 | Sync + async, timeouts, used in tests too |
| UI | **Streamlit** + **Plotly** | 1.36 / 5.22 | Interactive control tower in hours; Plotly for Gantt, waterfall, geo arcs, heatmaps |
| CLI | **Typer** | 0.12 | `cascade generate/train/evaluate/serve/...`, cross-platform (no Make dependency on Windows) |
| Logging | **structlog** (JSON) | 24.1 | Structured logs with `request_id`, model version, timings |
| Metrics (P1) | **prometheus-fastapi-instrumentator** | 7.0 | `/metrics` endpoint: latency histograms, degraded counter |
| Testing | **pytest**, **hypothesis**, **pytest-cov**, **pytest-benchmark** | 8 / 6.100 / 5 / 4 | Unit, property (leakage, invariants), coverage, micro-benchmarks |
| API contract tests | **schemathesis** (P1) | 3.30 | Fuzzes the OpenAPI schema → no 500s on valid input |
| Load testing | **locust** | 2.29 | p95 under concurrency |
| Lint/format | **ruff** (lint + format) | 0.5 | One fast tool replaces black/isort/flake8 |
| Types | **mypy** (strict on `domain/`, `features/`, `serving/`) | 1.10 | Catches contract drift between modules |
| Architecture lint | **import-linter** | 2.0 | Enforces the module dependency direction |
| Hooks | **pre-commit** | 3.7 | ruff, mypy, end-of-file, large-file guard, nbstripout |
| CI | **GitHub Actions** | — | Lint → type → test → `cascade all --n 120` smoke → quality gates → perf |
| Containers | **Docker** (multi-stage, `python:3.12-slim`) + **Compose** | 24 / v2 | One-command run; non-root; healthchecks |
| Report | **Typst** (or Pandoc → PDF) | 0.11 | Fast, reproducible 2–3 page PDF from Markdown-like source; figures from `reports/figures` |
| Demo video | OBS Studio | — | ≤ 5 min screen recording |

---

## 2. Key Decisions in Detail

### 2.1 LightGBM over XGBoost / CatBoost / Deep Learning
- **Quantile objective + native categoricals + monotone constraints** in one library. *As built:* the constraints apply to the late classifier only (quantile/L1 objectives renew leaf outputs and 4.7 rejects them). With `feature_fraction < 1`, LightGBM silently downgrades the `advanced` method to `basic`.
- `pred_contrib=True` returns exact TreeSHAP values **inside the booster** (C++), with no Python SHAP overhead on the hot path. This is the single biggest latency lever.
- CatBoost has excellent categorical handling but slower inference and a heavier dependency. XGBoost is a fine alternative and is kept for the P2 `survival:aft` model.
- Deep models (TabNet, Transformers, GNN) are data-starved at around 3k rows and harder to explain (ADR-002).

### 2.2 FastAPI + in-process model (no model server)
- Triton, TorchServe and BentoML add a network hop and ops overhead for a few-MB tree model. In-process inference is the lowest-latency option.
- Workers: `uvicorn --workers N` (N = cores). LightGBM `num_threads=1` per call avoids oversubscription.

### 2.3 Streamlit over React/Next.js
- Builds a 6-page control tower in under a day with one language.
- The UI consumes **only the public API** (httpx), so the React swap path stays clean (ADR-007).
- Custom touches: `st.columns` KPI tiles, Plotly hatched bars (`marker.pattern`), time-travel `st.select_slider`, `st.cache_data` keyed by model version.

### 2.4 SQLite for the ledger
- Ships with Python and needs no service. WAL mode allows concurrent reads during writes.
- Accessed only through `LedgerRepository`, so Postgres/Timescale is a drop-in for scale.

### 2.5 No LLM in the core path
- Deterministic templates are faster (< 1 ms), testable and can't hallucinate numbers (ADR-005).
- **Optional P2:** an LLM "rephrase" step (Claude Sonnet via the Anthropic API) behind a feature flag, constrained to rewrite *given* facts, with a post-check that every number in the output appears in the input facts.

---

## 3. Rejected / Deferred Options

| Option | Status | Reason |
|---|---|---|
| Kafka / event streaming | Deferred (P2) | Request/response + batch is enough for the brief; the event-driven design is documented |
| Postgres / Redis | Deferred | SQLite + in-memory priors are enough; interfaces are ready |
| MLflow / W&B | Deferred | `manifest.json` + `metrics.json` give versioning and lineage with zero infra. MLflow is a drop-in if the team grows |
| Polars | Deferred | Not needed for 300 shipments; planned for 100k+ |
| Airflow / Prefect | Rejected for v1 | The Typer CLI pipeline is deterministic and fast (< 3 min); orchestration is overhead here |
| Kubernetes | Rejected for v1 | Compose suffices; the stateless API is k8s-ready (healthchecks, env config) |
| Jupyter as source of truth | Rejected | Notebooks only for EDA (`notebooks/`, outputs stripped). All logic lives in the package |

---

## 4. Project Layout

```
cascade-eta/
├── pyproject.toml · uv.lock · README.md · .pre-commit-config.yaml · .importlinter
├── configs/                 sim.yaml · train.yaml · serve.yaml · costs.yaml · alerts.yaml
├── src/cascade/
│   ├── domain/              stages.py · delay.py · schemas.py · ports.py
│   ├── sim/                 network.py · external.py · mechanics.py · missingness.py · generator.py · ledger.py
│   ├── data/                io.py · validation.py · splits.py
│   ├── features/            snapshot.py · registry.py · priors.py · families/{plan,progress,propagation,external,quality}.py
│   ├── models/              baselines.py · gbm.py · classifier.py · conformal.py · stage_chain.py · reconcile.py · artifacts.py · pipeline.py
│   ├── explain/             contributions.py · stage_groups.py · waterfall.py · counterfactual.py · propagation.py · narrative.py
│   ├── decision/            promise.py · alerts.py · cost.py · advisor.py · scenarios.py · ledger.py
│   ├── eval/                metrics.py · backtest.py · attribution_fidelity.py · decision_metrics.py · robustness.py · figures.py · model_card.py
│   ├── serving/             app.py · routes/ · schemas.py · service.py · fallback.py · middleware.py · problems.py
│   ├── config.py · logging.py · cli.py
├── app/                     Home.py · pages/{1_Fleet,2_Shipment,3_WhatIf_Scenarios,4_Alerts,5_Insights,6_Data_Health}.py · components/ · theme.py · api_client.py
├── tests/                   unit/ · property/ · integration/ · contract/ · perf/ · conftest.py
├── notebooks/               01_eda.ipynb (outputs stripped)
├── report/                  report.typ · figures/ (generated)
├── docker/                  Dockerfile.api · Dockerfile.ui · compose.yaml
├── .github/workflows/       ci.yml
├── docs/                    (this folder)
├── data/ artifacts/ reports/   (gitignored, generated)
```

---

## 5. Developer Commands

```bash
uv sync --all-extras
```

```bash
uv run cascade all --seed 42
```

```bash
uv run cascade serve --version latest
```

```bash
uv run streamlit run app/Home.py
```

```bash
uv run pytest -q --cov=cascade
```

```bash
docker compose -f docker/compose.yaml up --build
```
