"""Train the real production pipeline per DEV world under several TrainConfigs and score test.

Run via runner.py:  seq 101 120 | xargs -P 7 -I{} python runner.py run prod_ref <tag> {} v11 v12
"""

from __future__ import annotations

import time
import warnings

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from cascade.domain.stages import CHECKPOINT_GROUP
from cascade.models.train import TrainConfig, train
from common import FEATS, load_world

warnings.filterwarnings("ignore")
CONFIGS = {
    "v11": TrainConfig(seed=0, shrink_rule="temporal", late_model="blend"),
    "v12": TrainConfig(seed=0, band="shifted"),  # first v1.2 draft (band moved with λ)
    "v12b": TrainConfig(seed=0),  # + band from the learned quantiles ("direct")
    "v12_temporal_lam": TrainConfig(seed=0, shrink_rule="temporal", band="shifted"),
    "v12_blend": TrainConfig(seed=0, late_model="blend", band="shifted"),
}
CANDIDATES = CONFIGS


def interval_score(lo, hi, y, a=0.2):
    return (hi - lo) + (2 / a) * (lo - y) * (y < lo) + (2 / a) * (y - hi) * (y > hi)


LAM_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


def lam_curve(model, te):
    """Test MAE at every λ (same boosters): lets any λ-selection rule be replayed offline."""
    from dataclasses import replace

    out = {}
    for lam in LAM_GRID:
        r = evaluate(replace(model, shrink=lam), te, curve=False)
        out[str(lam)] = {"mae": r["mae"], "iscore": r["iscore"]}
    return out


def evaluate(model, te, curve=True):
    pr = model.predict(te[FEATS].to_numpy(float), te.as_of.to_numpy(float),
                       te.planned_delivered.to_numpy(float),
                       (te.floor_plan_remaining_h.to_numpy(float),
                        te.floor_elapsed_h.to_numpy(float)))
    D = te.y_total.to_numpy(float)
    y = te.y_late.to_numpy(float)
    inside = (pr.delay_p10 <= D) & (D <= pr.delay_p90)
    grp = np.array([CHECKPOINT_GROUP[int(c)] for c in te.checkpoint])
    rule = te.current_delay_h.to_numpy() + te.rulebook.to_numpy()
    return {
        "mae": float(np.abs(pr.delay_p50 - D).mean()),
        "mae_rulebook": float(np.abs(rule - D).mean()),
        "brier": float(np.mean((pr.p_late - y) ** 2)),
        "pr_auc": float(average_precision_score(y, pr.p_late)),
        "roc_auc": float(roc_auc_score(y, pr.p_late)),
        "coverage": float(inside.mean()),
        "width": float((pr.delay_p90 - pr.delay_p10).mean()),
        "iscore": float(interval_score(pr.delay_p10, pr.delay_p90, D).mean()),
        "worst_group_cov_gap": float(max(abs(inside[grp == g].mean() - 0.8)
                                         for g in np.unique(grp))),
        "p80_cov": float((pr.delay_p80 >= D).mean()),
        "shrink": float(model.shrink),
        "late_alert_p": float(model.late_alert_p),
    }


def run_world(args):
    seed, names = args
    w = load_world(seed)
    rows = pd.concat([w.train, w.test])[w.train.columns.drop(["rulebook", "resid"])]
    out = {}
    for n in names:
        t = time.time()
        res = train(rows, w.ships, w.ledger, w.splits, CONFIGS[n])
        out[n] = evaluate(res.model, w.test) | {"sec": time.time() - t}
        out[n]["lam_test"] = lam_curve(res.model, w.test)
        out[n]["lam_temporal"] = {str(k): v for k, v in res.selection["shrink_mae"].items()}
        out[n]["lam_oof"] = {str(k): v for k, v in res.selection.get("shrink_mae_oof", {}).items()}
    return seed, out, {}


def summarise(res, ref="v11"):
    scalar = lambda o: {k: {m: v for m, v in d.items() if not isinstance(v, dict)}  # noqa: E731
                        for k, d in o.items()}
    df = pd.concat({s: pd.DataFrame(scalar(o)).T for s, o in res.items()}).astype(float)
    summ = df.groupby(level=1).mean()
    for m, better in (("mae", -1), ("brier", -1), ("iscore", -1), ("pr_auc", 1)):
        r = df.xs(ref, level=1)[m]
        summ[f"{m}_wins"] = [int(((df.xs(k, level=1)[m] - r) * better > 1e-12).sum())
                             for k in summ.index]
    return summ.T
