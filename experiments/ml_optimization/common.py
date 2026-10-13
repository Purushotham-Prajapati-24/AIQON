"""Shared helpers: load cached worlds, attach leakage-safe priors, score predictions."""

from __future__ import annotations

import os
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from cascade.features.priors import apply_priors, fit_priors
from cascade.features.registry import CATEGORICAL, FEATURE_NAMES
from cascade.models.predictor import PHYS_COLS
from cascade.models.train import priors_oof

CACHE = Path(__file__).parent / os.environ.get("CACHE_NAME", "cache")
DEV_SEEDS = list(range(101, 121))
HOLDOUT_SEEDS = [7, 11, 23, 42, 99]
FEATS = list(FEATURE_NAMES)
NUMERIC = [f for f in FEATS if f not in CATEGORICAL]


@dataclass
class World:
    seed: int
    train: pd.DataFrame  # training rows, priors out-of-fold (as in production training)
    test: pd.DataFrame  # out-of-time test rows, priors fit on all training shipments
    fold: np.ndarray  # voyage-grouped CV fold of each training row
    ships: pd.DataFrame
    ledger: pd.DataFrame
    splits: object


def load_world(seed: int) -> World:
    with (CACHE / f"world_{seed}.pkl").open("rb") as f:
        d = pickle.load(f)
    rows, ships, ledger, sp = d["rows"], d["shipments"], d["ledger"], d["splits"]
    tr_rows = rows[rows.shipment_id.isin(sp.train_ids)].copy()
    tr_ships = ships[ships.shipment_id.isin(sp.train_ids)]
    train = priors_oof(tr_rows, tr_ships, ledger, sp.fold_of)
    test = apply_priors(rows[rows.shipment_id.isin(sp.test_ids)], fit_priors(tr_ships, ledger))
    for df in (train, test):
        df["rulebook"] = df[list(PHYS_COLS)].sum(axis=1)
        df["resid"] = df.y_remaining - df.rulebook
    fold = train.shipment_id.map(sp.fold_of).to_numpy()
    return World(seed, train.reset_index(drop=True), test.reset_index(drop=True), fold, ships,
                 ledger, sp)


def score(pred_remaining: np.ndarray, df: pd.DataFrame) -> dict[str, float]:
    """Point accuracy of a remaining-delay P50 on final delay (same as the production metric)."""
    cur = df.current_delay_h.to_numpy(float)
    D = df.y_total.to_numpy(float)
    live = df.checkpoint.to_numpy(int) < 9
    err = cur + pred_remaining - D
    return {
        "mae": float(np.abs(err).mean()),
        "mae_live": float(np.abs(err[live]).mean()),
        "rmse": float(np.sqrt((err**2).mean())),
        "bias": float(err.mean()),
    }
