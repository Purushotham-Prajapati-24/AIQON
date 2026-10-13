"""Phase 4 — P(late > 24 h) bake-off on DEV worlds (Brier, PR-AUC, ROC-AUC, ECE on test).

Run via runner.py:  seq 101 120 | xargs -P 10 -I{} python runner.py run cls_bakeoff cls {} all
"""

from __future__ import annotations

import warnings
import zlib

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, roc_auc_score

from bakeoff import M, lgb_fit
from cascade.features.registry import FEATURE_NAMES, monotone_vector
from common import FEATS, World, load_world

warnings.filterwarnings("ignore")
THR = 24.0
CANDIDATES = {"all": None}


def emp_p_late(tr: pd.DataFrame, te: pd.DataFrame, by="checkpoint", min_n=150):
    """P(D > 24) = share of training residuals r (same checkpoint) with cur + rulebook + r > 24."""
    r_tr = tr.y_remaining.to_numpy() - tr.rulebook.to_numpy()
    need = THR - te.current_delay_h.to_numpy() - te.rulebook.to_numpy()
    out = np.empty(len(te))
    keys_tr, keys_te = tr[by].to_numpy(), te[by].to_numpy()
    all_sorted = np.sort(r_tr)
    for k in np.unique(keys_te):
        m = keys_te == k
        pool = np.sort(r_tr[keys_tr == k])
        if len(pool) < min_n:
            pool = all_sorted
        out[m] = 1.0 - np.searchsorted(pool, need[m], side="right") / len(pool)
    return np.clip(out, 1e-4, 1 - 1e-4)


def fit_clf(tr, te, extra_tr=None, extra_te=None, reg=False):
    Xtr, Xte = M(tr, FEATS), M(te, FEATS)
    names = list(FEATS)
    if extra_tr is not None:
        Xtr, Xte = np.c_[Xtr, extra_tr], np.c_[Xte, extra_te]
        names = names + ["x_extra"]
    kw = dict(n=300, lr=0.04, leaves=15, depth=5, min_leaf=20, ff=0.8, l2=1.0)
    if reg:
        kw = dict(n=250, lr=0.03, leaves=7, depth=3, min_leaf=60, ff=0.6, l2=10.0)
    mono = monotone_vector() + [1] * (len(names) - len(FEATURE_NAMES))
    extra = {"monotone_constraints": mono, "monotone_constraints_method": "basic"}
    b = lgb_fit(Xtr, tr.y_late.to_numpy(float), names, obj="binary", extra=extra, **kw)
    return b.predict(Xte)


def oof(w: World, fn):
    o = np.zeros(len(w.train))
    for k in np.unique(w.fold):
        m = w.fold == k
        o[m] = fn(w.train[~m], w.train[m])
    return o, fn(w.train, w.test)


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def fit_logreg(Z, y, l2=1.0):
    Z1 = np.c_[np.ones(len(Z)), Z]

    def f(b):
        z = Z1 @ b
        return np.sum(np.logaddexp(0, z) - y * z) + l2 * np.sum(b[1:] ** 2)

    def g(b):
        p = 1 / (1 + np.exp(-(Z1 @ b)))
        return Z1.T @ (p - y) + 2 * l2 * np.r_[0, b[1:]]

    return minimize(f, np.zeros(Z1.shape[1]), jac=g, method="L-BFGS-B").x


def emp_oof_inside(a):
    """Empirical P(late) for training rows, out-of-fold inside the given frame."""
    folds = a.voyage_id.map(lambda s: zlib.crc32(s.encode()) % 5).to_numpy()
    o = np.zeros(len(a))
    for k in range(5):
        m = folds == k
        o[m] = emp_p_late(a[~m], a[m])
    return o


def ece(y, p, bins=10):
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    return float(sum(abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).mean()
                     for b in range(bins) if (idx == b).any()))


def run_world(args):
    seed, _ = args
    w = load_world(seed)
    tr, te = w.train, w.test
    y_tr, y_te = tr.y_late.to_numpy(float), te.y_late.to_numpy(float)
    iso = lambda o, t: IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(  # noqa
        o, y_tr).predict(t)
    P = {}
    o_gbm, t_gbm = oof(w, fit_clf)
    P["gbm_iso (v1.1-like)"] = iso(o_gbm, t_gbm)
    P["gbm_raw"] = t_gbm
    o_gr, t_gr = oof(w, lambda a, b: fit_clf(a, b, reg=True))
    P["gbm_reg_iso"] = iso(o_gr, t_gr)
    o_emp, t_emp = oof(w, emp_p_late)
    P["emp_rulebook_cp"] = t_emp
    P["emp_rulebook_global"] = emp_p_late(tr, te, by="kind", min_n=10**9)
    o_st, t_st = oof(w, lambda a, b: fit_clf(a, b, logit(emp_oof_inside(a)),
                                              logit(emp_p_late(a, b))))
    P["gbm+emp_feat_iso"] = iso(o_st, t_st)
    b = fit_logreg(np.c_[logit(o_emp), logit(o_gbm)], y_tr)
    z = np.c_[np.ones(len(te)), logit(t_emp), logit(t_gbm)] @ b
    P["logit_stack(emp,gbm)"] = 1 / (1 + np.exp(-z))
    P["avg(emp,gbm_iso)"] = 0.5 * (t_emp + P["gbm_iso (v1.1-like)"])
    # phase-specific stack: coefficients per checkpoint group (pre-departure / sea / port / post)

    def phase_design(df, le, lg):
        c = df.checkpoint.to_numpy(int)
        G = np.stack([(c >= 2) & (c <= 4), (c >= 5) & (c <= 6), c >= 7], 1).astype(float)
        return np.c_[le, lg, G, G * le[:, None], G * lg[:, None]]

    for l2 in (1.0, 10.0):
        bg = fit_logreg(phase_design(tr, logit(o_emp), logit(o_gbm)), y_tr, l2=l2)
        zg = np.c_[np.ones(len(te)), phase_design(te, logit(t_emp), logit(t_gbm))] @ bg
        P[f"logit_stack_phase(l2={l2})"] = 1 / (1 + np.exp(-zg))
    out = {k: {"brier": float(np.mean((p - y_te) ** 2)),
               "pr_auc": float(average_precision_score(y_te, p)),
               "roc_auc": float(roc_auc_score(y_te, p)), "ece": ece(y_te, p)}
           for k, p in P.items()}
    return seed, out, {"stack_coef": [float(v) for v in b]}


def summarise(res, ref="gbm_iso (v1.1-like)"):
    df = pd.concat({s: pd.DataFrame(o).T for s, o in res.items()})
    summ = df.groupby(level=1).agg(["mean", "std"])
    r = df.xs(ref, level=1).brier
    summ[("brier_wins", "")] = pd.Series(
        {k: int((df.xs(k, level=1).brier < r - 1e-12).sum()) for k in summ.index})
    return summ.sort_values(("brier", "mean"))
