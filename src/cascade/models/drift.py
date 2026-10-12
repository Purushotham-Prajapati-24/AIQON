"""Feature drift: Population Stability Index (PSI) against the training distribution.

The training reference (decile bins + a missing-value bin per key feature) is frozen in the
model bundle. Evaluation reports train -> test PSI (the out-of-time Q4 season is a deliberate
shift); the API reports live PSI over logged predictions. Rule of thumb: < 0.1 stable,
0.1-0.2 watch, > 0.2 drift.
"""

from __future__ import annotations

import math

import numpy as np

from cascade.features.registry import FEATURE_NAMES

DRIFT_FEATURES = (
    "current_delay_h",
    "rho_dest_fcst",
    "rho_hub_fcst",
    "weather_fcst_remaining",
    "overdue_h",
    "ts_buffer_remaining_h",
    "n_missing_past",
    "hours_since_last_event",
)
EPS = 1e-4


def _hist(values: np.ndarray, edges: list[float]) -> list[float]:
    v = np.asarray(values, float)
    nan = np.isnan(v)
    finite = v[~nan]
    counts = np.histogram(finite, bins=[-math.inf, *edges, math.inf])[0].astype(float)
    counts = np.append(counts, nan.sum())  # last bin = missing
    return list(counts / max(len(v), 1))


def reference(X: np.ndarray) -> dict[str, dict]:
    """Decile edges and bin shares of each drift feature on the training rows."""
    ref = {}
    for name in DRIFT_FEATURES:
        col = X[:, FEATURE_NAMES.index(name)]
        finite = col[~np.isnan(col)]
        edges = (
            sorted(set(np.quantile(finite, np.linspace(0.1, 0.9, 9)).tolist()))
            if len(finite)
            else []
        )
        ref[name] = {"edges": edges, "probs": _hist(col, edges)}
    return ref


def psi(ref: dict, values: np.ndarray) -> float:
    exp = np.asarray(ref["probs"], float) + EPS
    act = np.asarray(_hist(values, ref["edges"]), float) + EPS
    return float(np.sum((act - exp) * np.log(act / exp)))


def status(value: float) -> str:
    return "stable" if value < 0.1 else ("watch" if value < 0.2 else "drift")


def psi_table(ref: dict[str, dict], X: np.ndarray) -> dict[str, dict]:
    out = {}
    for name, r in ref.items():
        v = psi(r, X[:, FEATURE_NAMES.index(name)])
        out[name] = {"psi": v, "status": status(v)}
    return out
