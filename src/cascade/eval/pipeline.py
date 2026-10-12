"""End-to-end pipeline: generate -> validate -> features -> split -> train -> evaluate -> gate -> publish."""

from __future__ import annotations

import json
import math
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from cascade.data.splits import make_splits
from cascade.data.validation import validate_all
from cascade.decision.cost import CostModel
from cascade.decision.engine import Engine, World, identity_errors
from cascade.domain.stages import EventType
from cascade.eval import figures
from cascade.eval.evaluate import make_context, run_all
from cascade.eval.model_card import write_model_card
from cascade.features.dataset import build_rows
from cascade.models.artifacts import Bundle, save_bundle
from cascade.models.train import TrainConfig, train
from cascade.sim.generator import SimConfig, generate

E = EventType
ROOT = Path(__file__).resolve().parents[3]


@dataclass
class PipelineConfig:
    seed: int = 42
    n_shipments: int = 300
    version: str = "1.2.0"
    fast: bool = False  # skip robustness + ablations
    publish: bool = True
    force: bool = False  # publish even if a hard gate fails (flagged in manifest)
    data_dir: Path = ROOT / "data"
    artifacts_dir: Path = ROOT / "artifacts"
    reports_dir: Path = ROOT / "reports"
    train: TrainConfig = field(default_factory=TrainConfig)
    sim_overrides: dict = field(default_factory=dict)  # SimConfig fields (sensitivity study)


HARD_GATES = {
    "mae_improvement_vs_B1": (">=", 0.15),
    "coverage_p10_p90_overall": ("between", (0.70, 0.90)),
    "brier_tau24": ("<=", 0.20),
    "attribution_lift_vs_lane_prior": (">=", 0.10),
    "identity_violations": ("<=", 0),
    "latency_p95_ms": ("<", 50.0),
}


# Informational: reported pass/fail, never blocks publishing.
INFO_GATES = {
    # λ = 0 makes CASCADE's P50 the rulebook plus a heuristic floor; the floor must not cost >1%
    "mae_ratio_cascade_vs_rulebook": ("<=", 1.01),
}


def targets(metrics: dict, head: dict, runtime_s: float) -> list[dict]:
    """Original PRD targets next to the revised gates, with an honest met / partly / unmet."""
    acc, dec = metrics["accuracy"], metrics["decision"]
    groups = {g: d["coverage"] for g, d in acc["coverage_detail"].items() if g != "overall"}
    in_band = [0.75 <= v <= 0.85 for v in groups.values()]

    def status(ok: bool, partly: bool = False) -> str:
        return "met" if ok else ("partly" if partly else "unmet")

    imp, pr_auc = head["mae_improvement_vs_B1"], head.get("pr_auc_tau24_at_arrival")
    rows = [
        (
            "G1",
            "MAE improvement vs carry-forward",
            ">= 25% (stretch 40%)",
            ">= 15%",
            imp,
            status(imp >= 0.25),
        ),
        (
            "G2",
            "PR-AUC P(late) at destination arrival",
            ">= 0.75 (stretch 0.85)",
            "-",
            pr_auc,
            status(pr_auc is not None and pr_auc >= 0.75),
        ),
        (
            "G2b",
            "Brier P(late > 24 h)",
            "<= 0.15",
            "<= 0.20",
            head["brier_tau24"],
            status(head["brier_tau24"] <= 0.15),
        ),
        (
            "G3",
            "P10-P90 coverage in every checkpoint group",
            "80% +/- 5 pp each",
            "70-90% overall",
            groups,
            status(all(in_band), partly=any(in_band)),
        ),
        (
            "G4",
            "Future-delay driver top-1 vs cause ledger",
            ">= 70% (stretch 80%)",
            "lift >= 10 pp vs lane history",
            head["attribution_top1"],
            status(head["attribution_top1"] >= 0.70),
        ),
        (
            "G5",
            "Latency p95 predict + explain (in-process)",
            "< 50 ms",
            "< 50 ms",
            head["latency_p95_ms"],
            status(head["latency_p95_ms"] < 50),
        ),
        (
            "G6a",
            "Late shipments alerted >= 48 h before planned delivery",
            ">= 70%",
            "-",
            head["alert_lead_ge_48h_share"],
            status(head["alert_lead_ge_48h_share"] >= 0.70),
        ),
        (
            "G6b",
            "Promise changes / raw P50 day changes",
            "<= 0.40",
            "hit rate + reversals (reported)",
            dec["promise_flip_ratio"],
            status(dec["promise_flip_ratio"] <= 0.40),
        ),
        ("G7", "One-command run time", "< 180 s", "-", runtime_s, status(runtime_s < 180)),
    ]
    return [
        {"id": i, "metric": m, "original_target": o, "revised_gate": r, "value": v, "status": s}
        for i, m, o, r, v, s in rows
    ]


def _check(op: str, val: float, thr) -> bool:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return False
    if op == ">=":
        return val >= thr
    if op == "<=":
        return val <= thr
    if op == "<":
        return val < thr
    return thr[0] <= val <= thr[1]


def headline(metrics: dict) -> dict:
    acc = metrics["accuracy"]
    return {
        "mae_cascade_h": acc["overall"]["cascade"]["mae"],
        "mae_B1_h": acc["overall"]["B1_carry_forward"]["mae"],
        "mae_B2_h": acc["overall"]["B2_propagation_prior"]["mae"],
        "mae_B3_carrier_plan_h": acc["overall"]["B3_carrier_plan"]["mae"],
        "mae_improvement_vs_B1": acc["improvement_vs_B1"],
        "mae_improvement_vs_B1_ci95": acc["bootstrap_vs_B1"]["improvement"],
        "mae_improvement_vs_B2": acc["improvement_vs_B2"],
        "mae_improvement_vs_B1_ci95_voyage": acc["bootstrap_voyage"]["vs_B1"]["improvement"],
        "mae_rulebook_h": acc["overall"]["physics_rulebook"]["mae"],
        "mae_improvement_vs_rulebook": acc["improvement_vs_rulebook"],
        "mae_improvement_vs_rulebook_ci95_voyage": acc["bootstrap_voyage"]["vs_rulebook"][
            "improvement"
        ],
        "mae_ratio_cascade_vs_rulebook": acc["overall"]["cascade"]["mae"]
        / acc["overall"]["physics_rulebook"]["mae"],
        "shrink": metrics["model_selection"]["shrink"],
        "n_test_voyages": acc["n_test_voyages"],
        "eta_floor_binding_share": acc["eta_floor"]["binding_share"],
        "coverage_p10_p90_overall": acc["coverage_p10_p90"]["overall"],
        "brier_tau24": acc["classification"]["tau_24"]["overall"]["brier"],
        "pr_auc_tau24": acc["classification"]["tau_24"]["overall"].get("pr_auc"),
        "pr_auc_tau24_at_arrival": acc["classification"]["tau_24"]
        .get("checkpoint_5", {})
        .get("pr_auc"),
        "attribution_top1": metrics["attribution_fidelity"]["accuracy"]["shap_top1"],
        "attribution_top2": metrics["attribution_fidelity"]["accuracy"]["shap_top2"],
        "attribution_top1_major": metrics["attribution_fidelity"]["accuracy"][
            "shap_top1_major_delays"
        ],
        "attribution_lift_vs_lane_prior": metrics["attribution_fidelity"]["accuracy"][
            "lift_vs_lane_prior"
        ],
        "propagation_spearman": metrics["propagation_fidelity"]["spearman"],
        "advisor_spearman": metrics["advisor_fidelity"].get("spearman"),
        "alert_lead_ge_48h_share": metrics["decision"]["alert_lead_ge_48h_share"],
        "promise_flip_ratio": metrics["decision"]["promise_flip_ratio"],
        "late_alert_false_positive_rate": metrics["decision"]["late_alert_false_positive_rate"],
        "alerts_per_100_shipment_days": metrics["decision"]["alerts_per_100_shipment_days"],
        "attribution_ambiguous_share": metrics["attribution_fidelity"]["ambiguity"][
            "share_margin_lt_6h"
        ],
        "promise_hit_rate": metrics["decision"]["promise_hit_rate"],
        "promise_reversals_per_shipment": metrics["decision"]["promise_reversals_per_shipment"],
        "raw_eta_reversals_per_shipment": metrics["decision"]["raw_eta_reversals_per_shipment"],
    }


def run(cfg: PipelineConfig, log=print) -> dict:
    t0 = time.time()
    data_dir = cfg.data_dir / f"seed{cfg.seed}"
    log(f"[1/7] generating {cfg.n_shipments} shipments (seed {cfg.seed})")
    sim = generate(SimConfig(seed=cfg.seed, n_shipments=cfg.n_shipments, **cfg.sim_overrides))
    validate_all(sim.shipments, sim.events, sim.ledger)
    sim.save(data_dir)

    log("[2/7] building as-of checkpoint rows")
    rows = build_rows(
        sim.shipments, sim.events, sim.ledger, sim.external, seed=cfg.seed, revisions=sim.revisions
    )
    splits = make_splits(sim.shipments, seed=cfg.seed)
    splits.save(data_dir / "splits.json")

    log(
        f"[3/7] training (train {len(splits.train_ids)} / test {len(splits.test_ids)} shipments, {len(rows)} rows)"
    )
    result = train(rows, sim.shipments, sim.ledger, splits, cfg.train, version=cfg.version)

    log("[4/7] evaluating on the out-of-time test set")
    test_s = sim.shipments[sim.shipments.shipment_id.isin(splits.test_ids)]
    test_e = sim.events[sim.events.shipment_id.isin(splits.test_ids)]
    test_r = (
        sim.revisions[sim.revisions.shipment_id.isin(splits.test_ids)]
        if not sim.revisions.empty
        else None
    )
    world = World.from_frames(test_s, test_e, revisions=test_r)
    engine = Engine(
        Bundle(result.model, {}, Path(".")),
        sim.external,
        CostModel.load(ROOT / "configs" / "costs.yaml"),
        world,
    )
    ctx = make_context(sim, splits, result, rows, engine)
    metrics = run_all(ctx, rows, cfg.train, fast=cfg.fast)

    log("[5/7] checking guardrails, latency and quality gates")
    metrics["checks"] = _runtime_checks(engine, world)
    head = headline(metrics) | {
        k: metrics["checks"][k] for k in ("latency_p95_ms", "identity_violations")
    }
    gates = {
        k: {"value": head.get(k), "rule": f"{op} {thr}", "pass": _check(op, head.get(k), thr)}
        for k, (op, thr) in HARD_GATES.items()
    }
    all_pass = all(g["pass"] for g in gates.values())
    info_gates = {
        k: {"value": head.get(k), "rule": f"{op} {thr}", "pass": _check(op, head.get(k), thr)}
        for k, (op, thr) in INFO_GATES.items()
    }
    metrics["headline"] = head
    metrics["gates"] = gates
    metrics["info_gates"] = info_gates
    metrics["meta"] = {
        "seed": cfg.seed,
        "n_shipments": cfg.n_shipments,
        "version": cfg.version,
        "late_rate": float(sim.shipments.is_late.mean()),
        "n_rows": int(len(rows)),
        "train_config": {k: v for k, v in asdict(cfg.train).items()},
        "runtime_s": round(time.time() - t0, 1),
        "world_now_h": world.now_h,
        "environment": _environment(),
    }
    metrics["targets"] = targets(metrics, head, metrics["meta"]["runtime_s"])

    log("[6/7] writing reports and figures")
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    example = _example(engine, world)
    metrics["example"] = example
    (cfg.reports_dir / "metrics.json").write_text(
        json.dumps(_finite(metrics), indent=1, default=_json_default)
    )
    figures.all_figures(metrics, cfg.reports_dir / "figures", example)
    if cfg.publish:  # the model card describes the published model only
        write_model_card(metrics, ROOT / "docs" / "ModelCard.md")

    if cfg.publish and (all_pass or cfg.force):
        log(f"[7/7] publishing bundle v{cfg.version} (gates {'PASS' if all_pass else 'FORCED'})")
        out = cfg.artifacts_dir / f"v{cfg.version}"
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        sim.external.save(out / "external.npz")
        world.save(out)
        (out / "insights.json").write_text(
            json.dumps(
                _finite(
                    {
                        "headline": head,
                        "accuracy": metrics["accuracy"],
                        "propagation": metrics["propagation_fidelity"],
                        "attribution": metrics["attribution_fidelity"],
                        "advisor": metrics["advisor_fidelity"],
                        "decision": metrics["decision"],
                        "group_importance": metrics["group_importance"],
                        "robustness": metrics.get("robustness"),
                        "ablations": metrics.get("ablations"),
                        "embargo": metrics.get("embargo"),
                        "gates": gates,
                        "info_gates": info_gates,
                        "targets": metrics["targets"],
                        "splits": metrics["splits"],
                        "slices": metrics["slices"],
                        "feed": metrics["feed"],
                        "drift": metrics["drift"],
                        "meta": metrics["meta"],
                    }
                ),
                indent=1,
                default=_json_default,
            )
        )
        save_bundle(
            result.model,
            out,
            {
                "metrics": head,
                "gates": gates,
                "gates_passed": all_pass,
                "data_seed": cfg.seed,
                "n_shipments": cfg.n_shipments,
            },
        )
    else:
        log("[7/7] NOT published: a hard quality gate failed (use --force to override)")
    for k, g in gates.items():
        log(
            f"   gate {k:<34} {round(g['value'], 4) if isinstance(g['value'], float) else g['value']!s:>10}  "
            f"{g['rule']:<22} {'PASS' if g['pass'] else 'FAIL'}"
        )
    for k, g in info_gates.items():
        log(f"   info {k:<34} {g['value']:.4f}  {g['rule']:<22} {'PASS' if g['pass'] else 'FAIL'}")
    for tg in metrics["targets"]:
        log(f"   target {tg['id']:<4} {tg['metric']:<52} {tg['status'].upper()}")
    return metrics


def _environment() -> dict:
    """Where the latency numbers were measured (they are hardware-dependent)."""
    import os
    import platform

    import lightgbm

    return {
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "lightgbm": lightgbm.__version__,
        "latency_method": "in-process Engine.predict(explain=True), sequential, single thread, "
        "200 repeats of one request after the evaluation warm-up; no HTTP",
    }


def _finite(o):
    """NaN / inf -> None, so every JSON we write is strict JSON (the API refuses NaN)."""
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_finite(v) for v in o]
    if isinstance(o, float | np.floating) and not math.isfinite(float(o)):
        return None
    return o


def _json_default(o):
    if isinstance(o, np.integer | np.floating):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def _runtime_checks(engine: Engine, world: World, n: int = 200) -> dict:
    """P50 identities on test checkpoints (tolerance 0.1 h) + single-request latency."""
    violations, checked, worst = 0, 0, {"a": 0.0, "b": 0.0, "c": 0.0}
    for sid in list(world.views)[:60]:
        v = world.views[sid]
        for cp in world.checkpoints(sid)[::2]:
            r = engine.predict(v, cp["as_of"], explain=True, with_promise=False)
            if r.p50_parts is None:  # fallback path: no model decomposition to check
                continue
            err = identity_errors(r)
            worst = {k: max(worst[k], err[k]) for k in worst}
            checked += 1
            if max(err.values()) > 0.1:
                violations += 1
    sid = next(iter(world.views))
    v = world.views[sid]
    t = world.checkpoints(sid)[2]["as_of"]
    lat = []
    for _ in range(n):
        s = time.perf_counter()
        engine.predict(v, t, explain=True, with_promise=False)
        lat.append((time.perf_counter() - s) * 1000)
    return {
        "identity_checked": checked,
        "identity_violations": violations,
        "identity_max_error_h": worst,
        "latency_p50_ms": float(np.percentile(lat, 50)),
        "latency_p95_ms": float(np.percentile(lat, 95)),
    }


def _example(engine: Engine, world: World) -> dict:
    """A worked example for the report: prefer a missed-connection shipment seen at the hub."""
    best, best_score = None, -1.0
    for v in world.views.values():
        if E.ARRIVE_TS not in v.reported:
            continue
        r = engine.predict(v, v.known_at(E.ARRIVE_TS) + 1 / 60, explain=True, with_promise=False)
        score = r.explanation.group_contrib.get("TRANSSHIPMENT", 0.0)
        if score > best_score:
            best, best_score = r, score
    if best is None:
        sid = next(iter(world.views))
        best = engine.predict(world.views[sid], world.now_h, explain=True, with_promise=False)
    return best.to_json(include_waterfall=True)
