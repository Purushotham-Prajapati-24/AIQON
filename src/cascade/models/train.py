"""Training orchestration: nested out-of-fold priors, cross-fitting, CQR, isotonic, final fit."""

from __future__ import annotations

from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from cascade.data.splits import Splits, make_splits
from cascade.domain.stages import PHYSICAL_GROUPS
from cascade.features.priors import apply_priors, fit_priors
from cascade.features.registry import CATEGORICAL, FEATURE_NAMES, monotone_vector
from cascade.models.baselines import PropagationPrior
from cascade.models.conformal import cqr_offsets, upper_offsets
from cascade.models.drift import reference as drift_reference
from cascade.models.predictor import (
    BAND,
    PHYS_COLS,
    QUANTILES,
    CascadeModel,
    quantile_implied_exceedance,
)


@dataclass
class TrainConfig:
    target_mode: str = "residual"
    n_estimators: int = 300
    learning_rate: float = 0.04
    num_leaves: int = 15
    max_depth: int = 5
    min_data_in_leaf: int = 20
    feature_fraction: float = 0.8
    bagging_fraction: float = 0.8
    lambda_l2: float = 1.0
    monotone: bool = True
    stage_models: bool = True
    late_threshold_h: float = 24.0
    alpha: float = 0.2  # 1 - nominal interval coverage (P10-P90)
    eta_floor_min_remaining_frac: float = 0.5  # heuristic ETA floor (0 = only ETA >= as_of)
    seed: int = 0
    exclude_features: tuple[str, ...] = field(default_factory=tuple)


def _params(
    cfg: TrainConfig, objective: str, alpha: float | None = None, monotone: bool = True
) -> dict:
    p = {
        "objective": objective,
        "learning_rate": cfg.learning_rate,
        "num_leaves": cfg.num_leaves,
        "max_depth": cfg.max_depth,
        "min_data_in_leaf": cfg.min_data_in_leaf,
        "feature_fraction": cfg.feature_fraction,
        "bagging_fraction": cfg.bagging_fraction,
        "bagging_freq": 1,
        "lambda_l2": cfg.lambda_l2,
        "min_data_per_group": 20,
        "cat_smooth": 10.0,
        "seed": cfg.seed,
        "deterministic": True,
        "force_row_wise": True,
        "num_threads": 4,
        "verbosity": -1,
    }
    if alpha is not None:
        p["alpha"] = alpha
    if monotone and cfg.monotone:
        mono = monotone_vector()
        if cfg.target_mode == "residual":  # physics already in the base: leave its residual free
            mono = [0 if n in PHYS_COLS else m for n, m in zip(FEATURE_NAMES, mono, strict=True)]
        p["monotone_constraints"] = mono
        # "advanced" is silently downgraded to "basic" when feature_fraction < 1: say so explicitly
        p["monotone_constraints_method"] = "basic"
    return p


def _X(rows: pd.DataFrame, cfg: TrainConfig) -> np.ndarray:
    X = rows[list(FEATURE_NAMES)].to_numpy(float).copy()
    for (
        name
    ) in cfg.exclude_features:  # ablations: neutralise a feature without changing the contract
        X[:, FEATURE_NAMES.index(name)] = np.nan
    return X


def _fit(X: np.ndarray, y: np.ndarray, params: dict, n: int) -> lgb.Booster:
    ds = lgb.Dataset(
        X,
        y,
        feature_name=list(FEATURE_NAMES),
        categorical_feature=list(CATEGORICAL),
        free_raw_data=False,
    )
    return lgb.train(params, ds, num_boost_round=n)


def _targets(rows: pd.DataFrame, cfg: TrainConfig) -> np.ndarray:
    y = rows.y_remaining.to_numpy(float)
    if cfg.target_mode == "residual":
        y = y - rows[list(PHYS_COLS)].sum(axis=1).to_numpy(float)
    return y


def fit_boosters(rows: pd.DataFrame, cfg: TrainConfig) -> dict[str, lgb.Booster]:
    X, y = _X(rows, cfg), _targets(rows, cfg)
    # LightGBM 4.x rejects monotone constraints for objectives that renew leaf outputs
    # (quantile, L1), so the constraints apply to the late classifier only; its monotonicity is
    # checked in tests/property/test_model_invariants.py. Quantile models are unconstrained.
    b = {
        k: _fit(X, y, _params(cfg, "quantile", a, monotone=False), cfg.n_estimators)
        for k, a in QUANTILES.items()
    }
    b["clf"] = _fit(X, rows.y_late.to_numpy(float), _params(cfg, "binary"), cfg.n_estimators)
    if cfg.stage_models:
        for g in PHYSICAL_GROUPS:
            b[f"stage_{g.value}"] = _fit(
                X,
                rows[f"y_inc_{g.value}"].to_numpy(float),
                _params(cfg, "regression_l1", monotone=False),
                cfg.n_estimators // 2,
            )
    return b


def priors_oof(
    rows: pd.DataFrame,
    shipments: pd.DataFrame,
    ledger: pd.DataFrame,
    fold_of: dict[str, int],
    exclude: set[int] | None = None,
) -> pd.DataFrame:
    """Each row gets priors fit on shipments from other folds (and never from `exclude`)."""
    exclude = exclude or set()
    folds = rows.shipment_id.map(fold_of)
    ship_fold = shipments.shipment_id.map(fold_of)
    parts = []
    for j in sorted(folds.unique()):
        table = fit_priors(shipments[~ship_fold.isin({j} | exclude)], ledger)
        parts.append(apply_priors(rows[folds == j], table))
    return pd.concat(parts).loc[rows.index]


SHRINK_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


@dataclass
class TrainResult:
    model: CascadeModel
    oof: pd.DataFrame  # out-of-fold predictions on training rows
    train_rows: pd.DataFrame  # training rows with OOF priors
    selection: dict = field(default_factory=dict)  # temporal-validation curves


def select_on_temporal_validation(
    rows: pd.DataFrame, ships: pd.DataFrame, ledger: pd.DataFrame, cfg: TrainConfig
) -> tuple[float, float, dict]:
    """Choose (shrink, late_blend) on a *temporal* validation slice of the training data.

    The latest 20% of training voyages play "the future"; models fit on the earlier 80% are
    blended with the physics prior at several strengths (median) and the classifier is blended
    with the quantile-implied probability (P(late)). Test data is never touched.
    """
    inner = make_splits(ships, test_frac=0.2, n_folds=5, seed=cfg.seed)
    ships_tr = ships[ships.shipment_id.isin(inner.train_ids)]
    tr = priors_oof(rows[rows.shipment_id.isin(inner.train_ids)], ships_tr, ledger, inner.fold_of)
    va = apply_priors(rows[rows.shipment_id.isin(inner.test_ids)], fit_priors(ships_tr, ledger))
    Xt, Xv, yt = _X(tr, cfg), _X(va, cfg), _targets(tr, cfg)
    g = {
        k: _fit(Xt, yt, _params(cfg, "quantile", a, monotone=False), cfg.n_estimators).predict(Xv)
        for k, a in QUANTILES.items()
    }
    # select the blend with the classifier *as deployed*: isotonic-calibrated on out-of-fold scores
    yl = tr.y_late.to_numpy(float)
    clf_params = _params(cfg, "binary")
    fold_tr = tr.shipment_id.map(inner.fold_of).to_numpy()
    clf_oof = np.zeros(len(tr))
    for k in range(inner.n_folds):
        m = fold_tr == k
        if m.any() and (~m).any():
            clf_oof[m] = _fit(Xt[~m], yl[~m], clf_params, cfg.n_estimators).predict(Xt[m])
    iso_sel = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(clf_oof, yl)
    clf = iso_sel.predict(_fit(Xt, yl, clf_params, cfg.n_estimators).predict(Xv))
    cur = va.current_delay_h.to_numpy(float)
    base = cur + (
        va[list(PHYS_COLS)].sum(axis=1).to_numpy(float) if cfg.target_mode == "residual" else 0.0
    )
    y, y_late = va.y_total.to_numpy(float), va.y_late.to_numpy(float)
    grid = SHRINK_GRID if cfg.target_mode == "residual" else (1.0,)
    curve = {lam: float(np.abs(base + lam * g["q50"] - y).mean()) for lam in grid}
    shrink = min(curve, key=lambda k: (round(curve[k], 6), -k))
    q = np.sort(np.vstack([base + shrink * g["q50"] + (g[k] - g["q50"]) for k in BAND]), axis=0)
    q80 = base + shrink * g["q50"] + (g["q80"] - g["q50"])
    p_q = quantile_implied_exceedance(q[0], q[1], q[2], cfg.late_threshold_h)
    brier = {w: float(np.mean((w * clf + (1 - w) * p_q - y_late) ** 2)) for w in (0.0, 0.5, 1.0)}
    blend = min(brier, key=lambda k: brier[k])
    # drift-aware conformal: offsets that would have covered the *later* period
    rem = y - cur
    temporal_offsets = cqr_offsets(
        rem, q[0] - cur, q[2] - cur, va.checkpoint.to_numpy(), cfg.alpha, min_group=25
    )
    temporal_offsets80 = upper_offsets(
        rem, q80 - cur, va.checkpoint.to_numpy(), 1.0 - cfg.alpha / 2.0, min_group=25
    )
    return (
        shrink,
        blend,
        {
            "shrink_mae": curve,
            "late_blend_brier": brier,
            "temporal_offsets": temporal_offsets,
            "temporal_offsets80": temporal_offsets80,
        },
    )


ALERT_P_GRID = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9)
ACTIONABLE_LEAD_H = (
    48.0  # PRD G6: a LATE alert is useful only if it fires >= 48 h before planned delivery
)


def select_late_alert_threshold(
    rows: pd.DataFrame, oof: pd.DataFrame, iso, late_blend: float, cfg: TrainConfig
) -> tuple[float, dict]:
    """Pick the P(late) threshold for the LATE alert on voyage-grouped out-of-fold predictions.

    Replays the rule "first snapshot with P50 delay > tau and P(late) >= theta" per training
    shipment and maximises shipment-level *actionable* F1 for 'eventually late': precision counts
    every alert, but a late shipment only counts as caught if its first LATE alert fired at least
    ``ACTIONABLE_LEAD_H`` before planned delivery. Plain F1 rewarded a high threshold that alerted
    reliably but too late to act (issue #6). Test data is never used.
    """
    cur = rows.current_delay_h.to_numpy(float)
    q = np.sort(np.vstack([oof[k].to_numpy(float) for k in BAND]), axis=0) + cur
    p_clf = iso.predict(oof.clf_raw.to_numpy(float))
    p_q = quantile_implied_exceedance(q[0], q[1], q[2], cfg.late_threshold_h)
    p_late = late_blend * p_clf + (1.0 - late_blend) * p_q
    df = pd.DataFrame(
        {
            "sid": rows.shipment_id.to_numpy(),
            "t": rows.as_of.to_numpy(float),
            "plan_end": rows.planned_delivered.to_numpy(float),
            "tier_late": q[1] > cfg.late_threshold_h,
            "p": p_late,
            "late": rows.y_late.to_numpy(int),
        }
    ).sort_values(["sid", "t"])
    truth = df.groupby("sid").late.max()
    plan_end = df.groupby("sid").plan_end.first()
    n_late = max(int((truth == 1).sum()), 1)
    curve: dict[str, dict[str, float]] = {}
    for th in ALERT_P_GRID:
        first = df[df.tier_late & (df.p >= th)].groupby("sid").t.min().reindex(truth.index)
        alerted = first.notna()
        timely = alerted & ((plan_end - first) >= ACTIONABLE_LEAD_H)
        tp = int((alerted & (truth == 1)).sum())
        tp_timely = int((timely & (truth == 1)).sum())
        prec = tp / max(int(alerted.sum()), 1)
        rec = tp / n_late
        rec_timely = tp_timely / n_late
        f1 = 2 * prec * rec_timely / max(prec + rec_timely, 1e-9)
        fpr = int((alerted & (truth == 0)).sum()) / max(int((truth == 0).sum()), 1)
        curve[str(th)] = {
            "precision": prec,
            "recall": rec,
            "recall_ge_48h": rec_timely,
            "f1_actionable": f1,
            "fpr": fpr,
        }
    best = max(ALERT_P_GRID, key=lambda th: (round(curve[str(th)]["f1_actionable"], 4), th))
    return float(best), curve


def train(
    rows: pd.DataFrame,
    shipments: pd.DataFrame,
    ledger: pd.DataFrame,
    splits: Splits,
    cfg: TrainConfig,
    version: str = "dev",
) -> TrainResult:
    rows = rows[rows.shipment_id.isin(splits.train_ids)].copy()
    ships = shipments[shipments.shipment_id.isin(splits.train_ids)]
    fold = rows.shipment_id.map(splits.fold_of).to_numpy()
    shrink, late_blend, curve = select_on_temporal_validation(rows, ships, ledger, cfg)

    # ---- cross-fitting with nested priors (feeds CQR, isotonic, stage weights) --------
    oof = pd.DataFrame(index=rows.index)
    for k in range(splits.n_folds):
        tr = priors_oof(rows[fold != k], ships, ledger, splits.fold_of, exclude={k})
        va = apply_priors(
            rows[fold == k], fit_priors(ships[ships.shipment_id.map(splits.fold_of) != k], ledger)
        )
        b = fit_boosters(tr, cfg)
        Xv = _X(va, cfg)
        base = (
            va[list(PHYS_COLS)].sum(axis=1).to_numpy(float)
            if cfg.target_mode == "residual"
            else 0.0
        )
        g = {name: b[name].predict(Xv) for name in QUANTILES}
        lam = shrink if cfg.target_mode == "residual" else 1.0
        for name in QUANTILES:
            oof.loc[va.index, name] = base + lam * g["q50"] + (g[name] - g["q50"])
        oof.loc[va.index, "clf_raw"] = b["clf"].predict(Xv)
        if cfg.stage_models:
            for grp in PHYSICAL_GROUPS:
                oof.loc[va.index, f"stage_{grp.value}"] = b[f"stage_{grp.value}"].predict(Xv)

    y = rows.y_remaining.to_numpy(float)
    oof_offsets = cqr_offsets(
        y, oof.q10.to_numpy(), oof.q90.to_numpy(), rows.checkpoint.to_numpy(), cfg.alpha
    )
    # conservative under drift: never narrower than what the temporal slice required
    tmp = curve.get("temporal_offsets", {})
    offsets = {g: max(v, tmp.get(g, tmp.get("__global__", v))) for g, v in oof_offsets.items()}
    curve["oof_offsets"] = oof_offsets
    # calibrated P80 (customer promise): one-sided, drift-aware the same way
    oof80 = upper_offsets(y, oof.q80.to_numpy(), rows.checkpoint.to_numpy(), 1.0 - cfg.alpha / 2.0)
    tmp80 = curve.get("temporal_offsets80", {})
    offsets80 = {g: max(v, tmp80.get(g, tmp80.get("__global__", v))) for g, v in oof80.items()}
    curve["oof_offsets80"] = oof80
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(
        oof.clf_raw, rows.y_late
    )
    late_alert_p, alert_curve = select_late_alert_threshold(rows, oof, iso, late_blend, cfg)
    curve["late_alert_threshold"] = alert_curve
    stage_w = {}
    if cfg.stage_models:
        for grp in PHYSICAL_GROUPS:
            err = (rows[f"y_inc_{grp.value}"] - oof[f"stage_{grp.value}"]).abs().mean()
            stage_w[grp.value] = float(max(err, 0.5))

    # ---- final fit on all training rows (OOF priors), inference priors from all training
    train_rows = priors_oof(rows, ships, ledger, splits.fold_of)
    boosters = fit_boosters(train_rows, cfg)
    model = CascadeModel(
        boosters=boosters,
        offsets=offsets,
        iso_x=[float(v) for v in iso.X_thresholds_],
        iso_y=[float(v) for v in iso.y_thresholds_],
        priors=fit_priors(ships, ledger),
        fallback=PropagationPrior().fit(train_rows),
        target_mode=cfg.target_mode,
        late_threshold_h=cfg.late_threshold_h,
        stage_weights=stage_w,
        shrink=shrink,
        late_blend=late_blend,
        eta_floor_frac=cfg.eta_floor_min_remaining_frac,
        offsets80=offsets80,
        late_alert_p=late_alert_p,
        drift_ref=drift_reference(_X(train_rows, cfg)),
        version=version,
    )
    oof["y_remaining"] = y
    oof["checkpoint"] = rows.checkpoint.to_numpy()
    oof["y_late"] = rows.y_late.to_numpy()
    return TrainResult(model=model, oof=oof, train_rows=train_rows, selection=curve)
