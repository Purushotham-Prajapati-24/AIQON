"""Simulate independent worlds and cache their as-of snapshot rows + splits.

DEV worlds (seeds 101..120) are used for every modelling decision.
HOLDOUT worlds (the canonical seeds 7, 11, 23, 42, 99) are touched once, at the end.

Usage: python build_worlds.py          (env: CACHE_NAME, DEV_ONLY=1, HOLD_PATCH=...)
"""

from __future__ import annotations

import os
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

CACHE = Path(__file__).parent / os.environ.get("CACHE_NAME", "cache")
DEV_SEEDS = list(range(101, 121))
HOLDOUT_SEEDS = [7, 11, 23, 42, 99]


def _patch_holds() -> None:
    """Experiment-only override, e.g. HOLD_PATCH="ARRIVE_TS=24,ARRIVE_DEST_PORT=36"."""
    spec = os.environ.get("HOLD_PATCH")
    if not spec:
        return
    from cascade.domain.stages import EventType
    from cascade.features import snapshot

    for kv in spec.split(","):
        k, v = kv.split("=")
        if k == "HUB_EXTRA":
            snapshot.HUB_MAX_EXTRA_HOLD_H = float(v)
        else:
            snapshot.MAX_PLAUSIBLE_HOLD_H[EventType[k]] = float(v)


def build(seed: int) -> str:
    _patch_holds()
    from cascade.data.splits import make_splits
    from cascade.data.validation import validate_all
    from cascade.features.dataset import build_rows
    from cascade.sim.generator import SimConfig, generate

    out = CACHE / f"world_{seed}.pkl"
    if out.exists():
        return f"{seed}: cached"
    sim = generate(SimConfig(seed=seed, n_shipments=300))
    validate_all(sim.shipments, sim.events, sim.ledger)
    rows = build_rows(
        sim.shipments, sim.events, sim.ledger, sim.external, seed=seed, revisions=sim.revisions
    )
    splits = make_splits(sim.shipments, seed=seed)
    with out.open("wb") as f:
        pickle.dump(
            {"seed": seed, "rows": rows, "shipments": sim.shipments, "ledger": sim.ledger,
             "splits": splits},
            f,
        )
    return f"{seed}: {len(rows)} rows, {len(splits.test_ids)} test shipments"


if __name__ == "__main__":
    CACHE.mkdir(exist_ok=True)
    seeds = DEV_SEEDS if os.environ.get("DEV_ONLY") else DEV_SEEDS + HOLDOUT_SEEDS
    with ProcessPoolExecutor(max_workers=8) as ex:
        for msg in ex.map(build, seeds):
            print(msg, flush=True)
    sys.exit(0)
