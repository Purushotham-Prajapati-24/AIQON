"""Phase 5 — P10/P90 interval bake-off on DEV worlds: coverage, width, Winkler interval score.

Run via runner.py:  seq 101 120 | xargs -P 10 -I{} python runner.py run interval_bakeoff iv {} all
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd

from bakeoff import M, lgb_fit
from cascade.domain.stages import CHECKPOINT_GROUP
from cascade.models.conformal import apply_offsets, cqr_offsets
from common import FEATS, load_world

warnings.filterwarnings("ignore")
ALPHA = 0.2
REG = dict(n=200, lr=0.03, leaves=7, depth=3, min_leaf=60, ff=0.6, l2=10.0)
CANDIDATES = {"all": None}


def interval_score(lo, hi, y, a=ALPHA):
    return (hi - lo) + (2 / a) * (lo - y) * (y < lo) + (2 / a) * (y - hi) * (y > hi)


def emp_quantiles(tr, te, qs=(0.1, 0.9), key="checkpoint", min_n=150):
    """Rulebook + empirical residual quantiles of the same checkpoint (split-conformal-like)."""
    r_tr = tr.resid.to_numpy()
    out = np.zeros((len(qs), len(te)))
    k_tr, k_te = tr[key].to_numpy(), te[key].to_numpy()
    for k in np.unique(k_te):
        pool = r_tr[k_tr == k]
        pool = pool if len(pool) >= min_n else r_tr
        n = len(pool)
        for i, q in enumerate(qs):  # finite-sample conformal level
            hi = q > 0.5
            lvl = (min(math.ceil((n + 1) * q) / n, 1.0) if hi
                   else max(math.floor((n + 1) * q) / n, 0.0))
            out[i, k_te == k] = np.quantile(pool, lvl, method="higher" if hi else "lower")
    return te.rulebook.to_numpy() + out


def gbm_q(tr, te, a):
    b = lgb_fit(M(tr, FEATS), tr.resid.to_numpy(), FEATS, alpha=a, **REG)
    return te.rulebook.to_numpy() + b.predict(M(te, FEATS))


def run_world(args):
    seed, _ = args
    w = load_world(seed)
    tr, te = w.train, w.test
    y = te.y_remaining.to_numpy()
    P = {"emp_cp": tuple(emp_quantiles(tr, te))}
    key = lambda d: d.checkpoint.astype(str) + "_" + d.has_transshipment.astype(str)  # noqa
    P["emp_cp_x_ts"] = tuple(emp_quantiles(tr.assign(cpg=key(tr)), te.assign(cpg=key(te)),
                                           key="cpg"))
    oof_lo, oof_hi = np.zeros(len(tr)), np.zeros(len(tr))
    for k in np.unique(w.fold):
        m = w.fold == k
        oof_lo[m], oof_hi[m] = gbm_q(tr[~m], tr[m], 0.1), gbm_q(tr[~m], tr[m], 0.9)
    off = cqr_offsets(tr.y_remaining.to_numpy(), oof_lo, oof_hi, tr.checkpoint.to_numpy(), ALPHA)
    g_lo, g_hi = gbm_q(tr, te, 0.1), gbm_q(tr, te, 0.9)
    P["gbm_q_cqr"] = apply_offsets(g_lo, g_hi, te.checkpoint.to_numpy(), off)
    P["gbm_q_raw"] = (g_lo, g_hi)
    P["avg(emp_cp,gbm_cqr)"] = tuple((np.array(P["emp_cp"]) + np.array(P["gbm_q_cqr"])) / 2)
    grp = np.array([CHECKPOINT_GROUP[int(c)] for c in te.checkpoint])
    out = {}
    for k, (lo, hi) in P.items():
        cov = (lo <= y) & (y <= hi)
        out[k] = {"coverage": float(cov.mean()), "width": float((hi - lo).mean()),
                  "iscore": float(interval_score(lo, hi, y).mean()),
                  "worst_group_cov_gap": float(max(abs(cov[grp == g].mean() - 0.8)
                                                   for g in np.unique(grp)))}
    return seed, out, {}


def summarise(res):
    df = pd.concat({s: pd.DataFrame(o).T for s, o in res.items()})
    return df.groupby(level=1).agg(["mean", "std"]).sort_values(("iscore", "mean"))
