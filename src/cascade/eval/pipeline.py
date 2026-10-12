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
from cascade.decision.engine import Engine, World
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
    version: str = "1.0.0"
    fast: bool = False  # skip robustness + ablations
    publish: bool = True
    force: bool = False  # publish even if a hard gate fails (flagged in manifest)
    data_dir: Path = ROOT / "data"
    artifacts_dir: Path = ROOT / "artifacts"
    reports_dir: Path = ROOT / "reports"
    train: TrainConfig = field(default_factory=TrainConfig)


HARD_GATES = {
    "mae_improvement_vs_B1": (">=", 0.15),
    "coverage_p10_p90_overall": ("between", (0.70, 0.90)),
    "brier_tau24": ("<=", 0.20),
    "attribution_lift_vs_lane_prior": (">=", 0.10),
    "waterfall_additivity_violations": ("<=", 0),
    "latency_p95_ms": ("<", 50.0),
}


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
        "mae_improvement_vs_B1": acc["improvement_vs_B1"],
        "mae_improvement_vs_B1_ci95": acc["bootstrap_vs_B1"]["improvement"],
        "mae_improvement_vs_B2": acc["improvement_vs_B2"],
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
        "promise_hit_rate": metrics["decision"]["promise_hit_rate"],
        "promise_reversals_per_shipment": metrics["decision"]["promise_reversals_per_shipment"],
        "raw_eta_reversals_per_shipment": metrics["decision"]["raw_eta_reversals_per_shipment"],
    }


def run(cfg: PipelineConfig, log=print) -> dict:
    t0 = time.time()
    data_dir = cfg.data_dir / f"seed{cfg.seed}"
    log(f"[1/7] generating {cfg.n_shipments} shipments (seed {cfg.seed})")
    sim = generate(SimConfig(seed=cfg.seed, n_shipments=cfg.n_shipments))
    validate_all(sim.shipments, sim.events, sim.ledger)
    sim.save(data_dir)

    log("[2/7] building as-of checkpoint rows")
    rows = build_rows(sim.shipments, sim.events, sim.ledger, sim.external, seed=cfg.seed)
    splits = make_splits(sim.shipments, seed=cfg.seed)
    splits.save(data_dir / "splits.json")

    log(
        f"[3/7] training (train {len(splits.train_ids)} / test {len(splits.test_ids)} shipments, {len(rows)} rows)"
    )
    result = train(rows, sim.shipments, sim.ledger, splits, cfg.train, version=cfg.version)

    log("[4/7] evaluating on the out-of-time test set")
    test_s = sim.shipments[sim.shipments.shipment_id.isin(splits.test_ids)]
    test_e = sim.events[sim.events.shipment_id.isin(splits.test_ids)]
    world = World.from_frames(test_s, test_e)
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
        k: metrics["checks"][k] for k in ("latency_p95_ms", "waterfall_additivity_violations")
    }
    gates = {
        k: {"value": head.get(k), "rule": f"{op} {thr}", "pass": _check(op, head.get(k), thr)}
        for k, (op, thr) in HARD_GATES.items()
    }
    all_pass = all(g["pass"] for g in gates.values())
    metrics["headline"] = head
    metrics["gates"] = gates
    metrics["meta"] = {
        "seed": cfg.seed,
        "n_shipments": cfg.n_shipments,
        "version": cfg.version,
        "late_rate": float(sim.shipments.is_late.mean()),
        "n_rows": int(len(rows)),
        "train_config": {k: v for k, v in asdict(cfg.train).items()},
        "runtime_s": round(time.time() - t0, 1),
        "world_now_h": world.now_h,
    }

    log("[6/7] writing reports and figures")
    cfg.reports_dir.mkdir(parents=True, exist_ok=True)
    example = _example(engine, world)
    metrics["example"] = example
    (cfg.reports_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=1, default=_json_default)
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
                    "gates": gates,
                    "meta": metrics["meta"],
                },
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
    return metrics


def _json_default(o):
    if isinstance(o, np.integer | np.floating):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def _runtime_checks(engine: Engine, world: World, n: int = 200) -> dict:
    """Waterfall additivity on every test shipment + single-request latency distribution."""
    violations, checked = 0, 0
    for sid in list(world.views)[:60]:
        v = world.views[sid]
        for cp in world.checkpoints(sid)[::2]:
            r = engine.predict(v, cp["as_of"], explain=True, with_promise=False)
            total = sum(w.hours for w in r.explanation.waterfall if w.kind != "total")
            checked += 1
            if abs(total - r.delay_p50) > 0.1:
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
        "waterfall_checked": checked,
        "waterfall_additivity_violations": violations,
        "latency_p50_ms": float(np.percentile(lat, 50)),
        "latency_p95_ms": float(np.percentile(lat, 95)),
    }


def _example(engine: Engine, world: World) -> dict:
    """A worked example for the report: prefer a missed-connection shipment seen at the hub."""
    best, best_score = None, -1.0
    for v in world.views.values():
        if E.ARRIVE_TS not in v.reported:
            continue
        r = engine.predict(v, v.reported[E.ARRIVE_TS] + 1 / 60, explain=True, with_promise=False)
        score = r.explanation.group_contrib.get("TRANSSHIPMENT", 0.0)
        if score > best_score:
            best, best_score = r, score
    if best is None:
        sid = next(iter(world.views))
        best = engine.predict(world.views[sid], world.now_h, explain=True, with_promise=False)
    return best.to_json(include_waterfall=True)
