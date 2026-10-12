"""Simulator-parameter sensitivity: do CASCADE's conclusions survive wrong assumptions?

Seeds only vary random draws. Here the simulator's *truth* is changed (berth penalty, speed
recovery, weather impact, hub slow-down, timetable headways, reporting latency) while the
operator rulebook keeps its own fixed coefficients — so the model is evaluated on worlds whose
mechanics differ from what it was designed around. Each variant is a fresh generate -> train
-> evaluate run (fast mode, nothing published).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from cascade.domain.network import LANES
from cascade.sim import mechanics

VARIANTS: dict[str, dict] = {
    "baseline": {},
    "berth_window_penalty_x2": {"mech": {"BERTH_LAMBDA": 1.6}},
    "no_speed_recovery": {"mech": {"RECOVERY_KAPPA": 0.0}},
    "weather_impact_x1.5": {"mech": {"WEATHER_H_PER_DAY": 2.4}},
    "hub_congestion_slowdown_x2": {"mech": {"HUB_GAMMA": 2.4}},
    "connection_headway_x2": {"headway_x": 2.0},
    "reporting_latency_x3": {
        "sim": {
            "latency_median_tier1_h": 1.5,
            "latency_median_tier2_h": 6.0,
            "latency_median_tier3_h": 18.0,
        }
    },
}

KEYS = (
    "mae_cascade_h",
    "mae_rulebook_h",
    "mae_B1_h",
    "mae_improvement_vs_B1",
    "mae_ratio_cascade_vs_rulebook",
    "coverage_p10_p90_overall",
    "brier_tau24",
    "attribution_top1",
    "shrink",
)


@contextmanager
def patched(variant: dict) -> Iterator[None]:
    """Temporarily change simulator constants / lane headways (restored afterwards)."""
    saved_mech = {k: getattr(mechanics, k) for k in variant.get("mech", {})}
    saved_lanes = dict(LANES)
    try:
        for k, v in variant.get("mech", {}).items():
            setattr(mechanics, k, v)
        if "headway_x" in variant:
            for lid, lane in saved_lanes.items():
                LANES[lid] = replace(lane, headway_h=lane.headway_h * variant["headway_x"])
        yield
    finally:
        for k, v in saved_mech.items():
            setattr(mechanics, k, v)
        LANES.clear()
        LANES.update(saved_lanes)


def run_sensitivity(seed: int, n: int, reports_dir: Path, log=print) -> dict:
    from cascade.eval.pipeline import PipelineConfig, run

    out: dict[str, dict] = {}
    for name, variant in VARIANTS.items():
        cfg = PipelineConfig(
            seed=seed,
            n_shipments=n,
            fast=True,
            publish=False,
            reports_dir=reports_dir / "sensitivity" / name,
            sim_overrides=variant.get("sim", {}),
        )
        with patched(variant):
            head = run(cfg, log=lambda *_: None)["headline"]
        out[name] = {k: head.get(k) for k in KEYS}
        log(
            f"{name:<28} MAE {head['mae_cascade_h']:.1f} h (rulebook {head['mae_rulebook_h']:.1f}, "
            f"B1 {head['mae_B1_h']:.1f}) - vs B1 {head['mae_improvement_vs_B1']:.0%} - "
            f"coverage {head['coverage_p10_p90_overall']:.0%} - lambda {head['shrink']}"
        )
    result = {"seed": seed, "n_shipments": n, "variants": VARIANTS, "results": out}
    (reports_dir / "sensitivity.json").write_text(json.dumps(result, indent=1, default=str))
    return result
