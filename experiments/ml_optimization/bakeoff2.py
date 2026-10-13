"""Phase 3 — round 2 on the cleaned features: calibration, robust shrinkage, tree variants, stacking.

A candidate returns either one prediction or {variant: prediction} (cheap sweeps).
Run via runner.py:  seq 101 120 | xargs -P 14 -I{} python runner.py run bakeoff2 r2 {} [cands]
"""

from __future__ import annotations

import time
import warnings

import numpy as np
from scipy import sparse
from scipy.optimize import linprog

from bakeoff import DRIFTY, PHYS, M, cp_onehot, design_linear, lgb_fit, recency_w, summarise
from common import FEATS, NUMERIC, World, load_world, score

warnings.filterwarnings("ignore")
LAMS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0)
REG = dict(n=200, lr=0.03, leaves=7, depth=3, min_leaf=60, ff=0.6, l2=10.0)
__all__ = ["summarise"]


# ---------------------------------------------------------------------------------------------
# median regression as a linear program (sklearn's linear models are blocked on this machine)
# ---------------------------------------------------------------------------------------------
def qr_lp(X, y, tau=0.5, l1=0.0, pen=None, w=None):
    """min sum w_i * rho_tau(y_i - x_i b) + l1 * sum pen_j |b_j|   (HiGHS)."""
    n, p = X.shape
    w = np.ones(n) if w is None else np.asarray(w, float)
    pen = np.ones(p) if pen is None else np.asarray(pen, float)
    c = np.concatenate([l1 * pen, l1 * pen, tau * w, (1 - tau) * w])
    eye = sparse.identity(n, format="csr")
    Xs = sparse.csr_matrix(X)
    A = sparse.hstack([Xs, -Xs, eye, -eye], format="csr")
    r = linprog(c, A_eq=A, b_eq=y, bounds=(0, None), method="highs")
    if r.status != 0:
        raise RuntimeError(r.message)
    return r.x[:p] - r.x[p:2 * p]


def grp4(df):
    g = df.checkpoint.to_numpy(int)
    return np.stack([g <= 1, (g >= 2) & (g <= 4), (g >= 5) & (g <= 6), g >= 7], 1).astype(float)


def calib_design(df):
    G = grp4(df)
    P = df[PHYS].to_numpy(float)
    return np.hstack([G, *(P * G[:, [k]] for k in range(G.shape[1]))])


# ---------------------------------------------------------------------------------------------
# out-of-fold machinery (voyage-grouped folds of the *training* rows)
# ---------------------------------------------------------------------------------------------
def oof_and_test(w: World, fit_predict):
    """fit_predict(train_df, pred_df) -> correction. Returns (oof, test)."""
    oof = np.zeros(len(w.train))
    for k in np.unique(w.fold):
        m = w.fold == k
        oof[m] = fit_predict(w.train[~m], w.train[m])
    return oof, fit_predict(w.train, w.test)


def mae_rows(pred, df):
    return np.abs(pred - df.y_remaining.to_numpy(float))


def pick_lambda(oof_corr, df, grid=LAMS, by_group=False):
    base = df.rulebook.to_numpy(float)
    if not by_group:
        curve = {lam: mae_rows(base + lam * oof_corr, df).mean() for lam in grid}
        return min(curve, key=lambda k: (round(curve[k], 6), k))
    G = grp4(df).argmax(1)
    out = {}
    for g in range(4):
        m = G == g
        curve = {lam: mae_rows(base[m] + lam * oof_corr[m], df[m]).mean() for lam in grid}
        out[g] = min(curve, key=lambda k: (round(curve[k], 6), k))
    return out


# ---------------------------------------------------------------------------------------------
# base learners (fit on a train frame, predict the correction on another frame)
# ---------------------------------------------------------------------------------------------
def fp_lgb_resid(feats=FEATS, weight=None, **kw):
    def f(tr, te):
        params = {**REG, **kw}
        wt = recency_w(tr) if weight == "recency" else None
        b = lgb_fit(M(tr, feats), tr.resid.to_numpy(), feats, w=wt, **params)
        return b.predict(M(te, feats))
    return f


def fp_calib(l1=0.0):
    def f(tr, te):
        Xtr = calib_design(tr)
        if l1 == 0.0:
            b = qr_lp(Xtr, tr.y_remaining.to_numpy())
            return calib_design(te) @ b - te.rulebook.to_numpy()
        pen = np.r_[np.zeros(4), np.ones(Xtr.shape[1] - 4)]  # shrink toward the rulebook
        b = qr_lp(Xtr, tr.resid.to_numpy(), l1=l1, pen=pen)
        return calib_design(te) @ b
    return f


def fp_linear_lasso(l1):
    def f(tr, te):
        Xtr, Xte = design_linear(tr, te, NUMERIC)
        Xtr, Xte = np.hstack([cp_onehot(tr), Xtr]), np.hstack([cp_onehot(te), Xte])
        pen = np.r_[np.zeros(9), np.ones(Xtr.shape[1] - 9)]
        return Xte @ qr_lp(Xtr, tr.resid.to_numpy(), l1=l1, pen=pen)
    return f


def fp_cp_shift(tr, te):
    med = tr.groupby("checkpoint").resid.median()
    return te.checkpoint.map(med).fillna(0.0).to_numpy(float)


# ---------------------------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------------------------
def c_rulebook(w):
    return w.test.rulebook.to_numpy(float)


def _lam_family(w, fp, name):
    """Fixed-λ sweep + λ picked by 5-fold voyage CV (global and per journey phase)."""
    oof, corr = oof_and_test(w, fp)
    base = w.test.rulebook.to_numpy(float)
    out = {f"{name}@{lam}": base + lam * corr for lam in LAMS}
    out[f"{name}@cv"] = base + pick_lambda(oof, w.train) * corr
    lg = pick_lambda(oof, w.train, by_group=True)
    G = grp4(w.test).argmax(1)
    out[f"{name}@cvgrp"] = base + np.array([lg[g] for g in G]) * corr
    return out


def c_lgb_reg(w):
    return _lam_family(w, fp_lgb_resid(), "lgb_reg")


def c_lgb_reg_recency(w):
    return _lam_family(w, fp_lgb_resid(weight="recency"), "lgb_rec")


def c_lgb_nodrift(w):
    return _lam_family(w, fp_lgb_resid(feats=[f for f in FEATS if f not in DRIFTY]), "lgb_nodrift")


def c_lgb_linear_tree(w):  # LightGBM forbids L1/quantile with linear trees: use L2 on the residual
    return _lam_family(w, fp_lgb_resid(obj="regression", extra={"linear_tree": True,
                                                                "linear_lambda": 10.0}), "lgb_lt")


def c_lgb_rf(w):
    return _lam_family(w, fp_lgb_resid(n=300, leaves=31, depth=8, min_leaf=40, ff=0.5, bf=0.632,
                                       extra={"boosting": "rf"}), "lgb_rf")


def c_lgb_et(w):
    return _lam_family(w, fp_lgb_resid(n=400, lr=0.02, extra={"extra_trees": True}), "lgb_et")


def c_calib(w):
    out = {}
    base = w.test.rulebook.to_numpy(float)
    for l1 in (0.0, 30.0, 100.0, 300.0):
        oof, corr = oof_and_test(w, fp_calib(l1))
        out[f"calib_l1={l1}"] = base + corr
        out[f"calib_l1={l1}@cv"] = base + pick_lambda(oof, w.train) * corr
    return out


def c_lasso(w):
    out = {}
    base = w.test.rulebook.to_numpy(float)
    for l1 in (30.0, 100.0, 300.0, 1000.0):
        oof, corr = oof_and_test(w, fp_linear_lasso(l1))
        out[f"lasso_l1={l1}"] = base + corr
        out[f"lasso_l1={l1}@cv"] = base + pick_lambda(oof, w.train) * corr
    return out


def c_cp_shift(w):
    return w.test.rulebook.to_numpy(float) + fp_cp_shift(w.train, w.test)


STACK_WEIGHTS: dict = {}


def c_stack(w):
    """OOF corrections of several learners merged by a median-regression meta-learner."""
    learners = {"lgb": fp_lgb_resid(),
                "lgb_nodrift": fp_lgb_resid(feats=[f for f in FEATS if f not in DRIFTY]),
                "calib": fp_calib(100.0), "lasso": fp_linear_lasso(300.0), "cp": fp_cp_shift}
    O, T = [], []
    for fp in learners.values():
        o, t = oof_and_test(w, fp)
        O.append(o)
        T.append(t)
    O, T = np.column_stack(O), np.column_stack(T)
    base_te = w.test.rulebook.to_numpy()
    out = {"stack_qr": base_te + T @ qr_lp(O, w.train.resid.to_numpy())}
    # convex weights (incl. a weight on 'no correction'), solved as an LP
    n, k = O.shape
    c = np.r_[np.zeros(k + 1), 0.5 * np.ones(n), 0.5 * np.ones(n)]
    A_eq = sparse.hstack([sparse.csr_matrix(np.c_[O, np.zeros(n)]), sparse.identity(n),
                          -sparse.identity(n)], format="csr")
    A_sum = sparse.csr_matrix(np.r_[np.ones(k + 1), np.zeros(2 * n)][None, :])
    r = linprog(c, A_eq=sparse.vstack([A_eq, A_sum]), b_eq=np.r_[w.train.resid.to_numpy(), 1.0],
                bounds=(0, None), method="highs")
    out["stack_convex"] = base_te + T @ r.x[:k]
    out["avg_all"] = base_te + T.mean(1)
    out["avg_all@0.5"] = base_te + 0.5 * T.mean(1)
    STACK_WEIGHTS[w.seed] = dict(zip([*learners, "none"], np.round(r.x[:k + 1], 3)))
    return out


CANDIDATES = {k[2:]: v for k, v in dict(globals()).items() if k.startswith("c_")}


def run_world(args):
    seed, names = args
    w = load_world(seed)
    out, extra = {}, {}
    for n in names:
        t = time.time()
        try:
            pred = CANDIDATES[n](w)
            preds = pred if isinstance(pred, dict) else {n: pred}
            dt = (time.time() - t) / len(preds)
            for k, p in preds.items():
                out[k] = score(p, w.test) | {"sec": dt}
        except Exception as e:  # noqa: BLE001
            out[n] = {"error": repr(e)[:200]}
    if seed in STACK_WEIGHTS:
        extra["stack_weights"] = {k: float(v) for k, v in STACK_WEIGHTS[seed].items()}
    return seed, out, extra
