"""Phase 2 — round-1 model bake-off on DEV worlds + shared modelling helpers.

Every candidate is a function (world) -> predicted P50 *remaining* delay on that world's
out-of-time test rows, trained on that world's training rows only. We report the mean test MAE
over 20 independent worlds, paired against the operator rulebook.

Run via runner.py:  seq 101 120 | xargs -P 14 -I{} python runner.py run bakeoff r1 {}
(sklearn's linear/tree modules are blocked by Application Control on this machine, so linear
and forest models live in bakeoff2.py as LP / LightGBM implementations.)
"""

from __future__ import annotations

import time
import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd

from cascade.features.registry import CATEGORICAL
from cascade.models.predictor import PHYS_COLS
from common import FEATS, World, load_world, score

warnings.filterwarnings("ignore")
PHYS = list(PHYS_COLS)
CAT = list(CATEGORICAL)
DRIFTY = ["rho_origin", "rho_hub_fcst", "rho_dest_fcst", "weather_fcst_remaining", "storm_flag"]


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def lgb_fit(X, y, feats, obj="quantile", alpha=0.5, n=300, lr=0.04, leaves=15, depth=5,
            min_leaf=20, ff=0.8, bf=0.8, l2=1.0, w=None, seed=0, extra=None):
    p = dict(objective=obj, learning_rate=lr, num_leaves=leaves, max_depth=depth,
             min_data_in_leaf=min_leaf, feature_fraction=ff, bagging_fraction=bf,
             bagging_freq=1, lambda_l2=l2, seed=seed, deterministic=True, force_row_wise=True,
             num_threads=1, verbosity=-1, min_data_per_group=20, cat_smooth=10.0)
    if obj == "quantile":
        p["alpha"] = alpha
    if extra:
        p.update(extra)
    cats = [c for c in CAT if c in feats]
    ds = lgb.Dataset(X, y, weight=w, feature_name=feats, categorical_feature=cats,
                     free_raw_data=False)
    return lgb.train(p, ds, num_boost_round=n)


def M(df, feats):
    return df[feats].to_numpy(float)


def design_linear(tr: pd.DataFrame, te: pd.DataFrame, feats: list[str]):
    """Standardised numeric matrix with NaN indicators + median impute (fit on train only)."""
    Xtr, Xte = tr[feats].copy(), te[feats].copy()
    for f in feats:
        if Xtr[f].isna().any() or Xte[f].isna().any():
            Xtr[f + "_na"], Xte[f + "_na"] = Xtr[f].isna() * 1.0, Xte[f].isna() * 1.0
            med = Xtr[f].median()
            Xtr[f], Xte[f] = Xtr[f].fillna(med), Xte[f].fillna(med)
    mu, sd = Xtr.mean(), Xtr.std().replace(0, 1.0)
    return ((Xtr - mu) / sd).to_numpy(float), ((Xte - mu) / sd).to_numpy(float)


def cp_onehot(df):
    cp = df.checkpoint.astype(int).clip(0, 8).to_numpy()
    return np.eye(9)[cp]


def recency_w(tr: pd.DataFrame, half_life_frac=0.5):
    """Exponential weight on planned departure: the latest training voyages count more."""
    t = tr.planned_departure.to_numpy(float)
    span = t.max() - t.min() + 1e-9
    return 0.5 ** ((t.max() - t) / (half_life_frac * span))


# ---------------------------------------------------------------------------------------------
# candidates: each returns predicted remaining delay for w.test
# ---------------------------------------------------------------------------------------------
def c_carry(w):
    return np.zeros(len(w.test))


def c_rulebook(w):
    return w.test.rulebook.to_numpy(float)


def c_production(w):
    """The v1.1 shipped recipe end to end (temporal λ selection, CQR...), incl. ETA floor."""
    from cascade.models.train import TrainConfig, train

    rows = pd.concat([w.train, w.test])[w.train.columns.drop(["rulebook", "resid"])]
    res = train(rows, w.ships, w.ledger, w.splits,
                TrainConfig(seed=0, shrink_rule="temporal", late_model="blend"))
    te = w.test
    pr = res.model.predict(M(te, FEATS), te.as_of.to_numpy(float),
                           te.planned_delivered.to_numpy(float),
                           (te.floor_plan_remaining_h.to_numpy(float),
                            te.floor_elapsed_h.to_numpy(float)))
    return pr.delay_p50 - te.current_delay_h.to_numpy(float)


def c_lgb_resid_full(w):  # production booster, trusted fully (λ = 1)
    b = lgb_fit(M(w.train, FEATS), w.train.resid.to_numpy(), FEATS)
    return w.test.rulebook.to_numpy() + b.predict(M(w.test, FEATS))


def c_lgb_remaining(w):  # learn remaining delay directly, rulebook only as features
    b = lgb_fit(M(w.train, FEATS), w.train.y_remaining.to_numpy(), FEATS)
    return b.predict(M(w.test, FEATS))


def c_lgb_resid_reg(w):  # heavily regularised residual GBM
    b = lgb_fit(M(w.train, FEATS), w.train.resid.to_numpy(), FEATS, n=200, lr=0.03, leaves=7,
                depth=3, min_leaf=60, ff=0.6, l2=10.0)
    return w.test.rulebook.to_numpy() + b.predict(M(w.test, FEATS))


def c_lgb_resid_nodrift(w):  # residual GBM without drifting raw external levels
    f = [x for x in FEATS if x not in DRIFTY]
    b = lgb_fit(M(w.train, f), w.train.resid.to_numpy(), f, n=200, lr=0.03, leaves=7, depth=3,
                min_leaf=60, ff=0.6, l2=10.0)
    return w.test.rulebook.to_numpy() + b.predict(M(w.test, f))


def c_lgb_resid_huber(w):
    b = lgb_fit(M(w.train, FEATS), w.train.resid.to_numpy(), FEATS, obj="huber", n=200,
                lr=0.03, leaves=7, depth=3, min_leaf=60, ff=0.6, l2=10.0, extra={"alpha": 5.0})
    return w.test.rulebook.to_numpy() + b.predict(M(w.test, FEATS))


CANDIDATES = {k[2:]: v for k, v in dict(globals()).items() if k.startswith("c_")}


def run_world(args):
    seed, names = args
    w: World = load_world(seed)
    out = {}
    for n in names:
        t = time.time()
        try:
            out[n] = score(CANDIDATES[n](w), w.test) | {"sec": time.time() - t}
        except Exception as e:  # noqa: BLE001
            out[n] = {"error": repr(e)[:200]}
    return seed, out, {}


def summarise(res: dict, ref="rulebook") -> pd.DataFrame:
    names = list(next(iter(res.values())).keys())
    rows = []
    for n in names:
        ok = [s for s in res if "mae" in res[s].get(n, {})]
        if not ok:
            rows.append({"model": n, "err": str(next(iter(res.values()))[n])[:80]})
            continue
        m = np.array([res[s][n]["mae"] for s in ok])
        r = np.array([res[s][ref]["mae"] for s in ok])
        rel = 1 - m / r
        rows.append({"model": n, "mae": m.mean(), "impr%": 100 * rel.mean(),
                     "se%": 100 * rel.std(ddof=1) / np.sqrt(len(rel)),
                     "wins": f"{int((m < r - 1e-9).sum())}/{len(m)}",
                     "mae_live": np.mean([res[s][n]["mae_live"] for s in ok]),
                     "bias": np.mean([res[s][n]["bias"] for s in ok]),
                     "sec": np.mean([res[s][n]["sec"] for s in ok])})
    return pd.DataFrame(rows).sort_values("mae").set_index("model")
