"""Tune the 'silence = reporting gap' caps of the snapshot cleaner by coordinate descent.

Selection uses the pooled TRAIN-split rulebook MAE of the 20 DEV worlds; test MAE is only
reported. Holdout worlds are never touched. The starting point is the v1.1 constants.
"""

from __future__ import annotations

import json
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

os.environ.setdefault("OMP_NUM_THREADS", "1")

from common import CACHE, DEV_SEEDS  # noqa: E402

GRID = (0.0, 6.0, 12.0, 24.0, 48.0, 72.0, 120.0, math.inf)
HUB_GRID = (0.0, 12.0, 24.0, 48.0, 84.0)
_SIMS: dict = {}


def evaluate(args):
    seed, spec = args
    from cascade.data.splits import make_splits
    from cascade.domain.stages import EventType
    from cascade.features import snapshot
    from cascade.features.dataset import build_rows
    from cascade.models.predictor import PHYS_COLS
    from cascade.sim.generator import SimConfig, generate

    for k, v in spec.items():
        if k == "HUB_EXTRA":
            snapshot.HUB_MAX_EXTRA_HOLD_H = v
        else:
            snapshot.MAX_PLAUSIBLE_HOLD_H[EventType[k]] = v
    if seed not in _SIMS:
        sim = generate(SimConfig(seed=seed, n_shipments=300))
        _SIMS[seed] = (sim, make_splits(sim.shipments, seed=seed))
    sim, sp = _SIMS[seed]
    rows = build_rows(sim.shipments, sim.events, sim.ledger, sim.external, seed=seed,
                      revisions=sim.revisions)
    err = (rows.y_remaining - rows[list(PHYS_COLS)].sum(axis=1)).abs()
    tr = rows.shipment_id.isin(sp.train_ids)
    return float(err[tr].sum()), int(tr.sum()), float(err[~tr].sum()), int((~tr).sum())


def score(ex, spec):
    out = list(ex.map(evaluate, [(s, spec) for s in DEV_SEEDS]))
    tr = sum(o[0] for o in out) / sum(o[1] for o in out)
    te = sum(o[2] for o in out) / sum(o[3] for o in out)
    return tr, te


if __name__ == "__main__":
    t0 = time.time()
    spec = {"GATE_IN_ORIGIN": 48.0, "DEPART_ORIGIN": 48.0, "ARRIVE_TS": 72.0,
            "ARRIVE_DEST_PORT": 72.0, "DISCHARGED": 120.0, "CUSTOMS_CLEARED": 120.0,
            "GATE_OUT": 72.0, "DELIVERED": 72.0, "HUB_EXTRA": 24.0}
    log = []
    ex = ProcessPoolExecutor(max_workers=10)
    base_tr, base_te = score(ex, spec)
    print(f"start  train {base_tr:.3f}  test {base_te:.3f}", flush=True)
    best_tr = base_tr
    for rnd in range(2):
        changed = False
        for key in spec:
            grid = HUB_GRID if key == "HUB_EXTRA" else GRID
            curve = {}
            for v in grid:
                trial = {**spec, key: v}
                for _ in range(3):
                    try:
                        curve[v] = score(ex, trial)
                        break
                    except BrokenProcessPool:
                        ex = ProcessPoolExecutor(max_workers=10)
            pick = min(curve, key=lambda v: (round(curve[v][0], 4), -v if v != math.inf else -1e9))
            if curve[pick][0] < best_tr - 1e-4 and pick != spec[key]:
                spec[key], best_tr, changed = pick, curve[pick][0], True
            log.append({"round": rnd, "key": key, "curve": {str(k): v for k, v in curve.items()},
                        "pick": spec[key]})
            print(f"r{rnd} {key:<17} -> {spec[key]:>5}   " + "  ".join(
                f"{k}:{v[0]:.2f}/{v[1]:.2f}" for k, v in curve.items()), flush=True)
        if not changed:
            break
    tr, te = score(ex, spec)
    print(f"final  train {tr:.3f} (start {base_tr:.3f})  test {te:.3f} (start {base_te:.3f})")
    print("spec:", spec)
    (CACHE.parent / "sweep_holds.json").write_text(json.dumps(
        {"spec": {k: (None if v == math.inf else v) for k, v in spec.items()}, "log": log,
         "start": [base_tr, base_te], "final": [tr, te]}, indent=1, default=str))
    print(f"{time.time() - t0:.0f}s")
