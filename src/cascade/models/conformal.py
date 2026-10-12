"""Conformalized Quantile Regression (CQR), calibrated separately per checkpoint group."""

from __future__ import annotations

import math

import numpy as np

from cascade.domain.stages import CHECKPOINT_GROUP


def cqr_offsets(
    y: np.ndarray,
    q_lo: np.ndarray,
    q_hi: np.ndarray,
    checkpoints: np.ndarray,
    alpha: float = 0.2,
    min_group: int = 40,
) -> dict[str, float]:
    """Q_g = conformal quantile of max(q_lo - y, y - q_hi) within each checkpoint group."""
    scores = np.maximum(q_lo - y, y - q_hi)
    groups = np.array([CHECKPOINT_GROUP[int(c)] for c in checkpoints])
    out: dict[str, float] = {"__global__": _conformal_quantile(scores, alpha)}
    for g in np.unique(groups):
        s = scores[groups == g]
        out[str(g)] = _conformal_quantile(s, alpha) if len(s) >= min_group else out["__global__"]
    return out


def upper_offsets(
    y: np.ndarray, q: np.ndarray, checkpoints: np.ndarray, level: float = 0.8, min_group: int = 40
) -> dict[str, float]:
    """One-sided conformal offset per checkpoint group so that P(y <= q + offset) >= level."""
    scores = y - q
    groups = np.array([CHECKPOINT_GROUP[int(c)] for c in checkpoints])
    out: dict[str, float] = {"__global__": _conformal_quantile(scores, 1.0 - level)}
    for g in np.unique(groups):
        s = scores[groups == g]
        out[str(g)] = (
            _conformal_quantile(s, 1.0 - level) if len(s) >= min_group else out["__global__"]
        )
    return out


def group_offset(checkpoints: np.ndarray, offsets: dict[str, float]) -> np.ndarray:
    return np.array(
        [offsets.get(CHECKPOINT_GROUP[int(c)], offsets["__global__"]) for c in checkpoints]
    )


def _conformal_quantile(scores: np.ndarray, alpha: float) -> float:
    n = len(scores)
    if n == 0:
        return 0.0
    level = min(math.ceil((n + 1) * (1 - alpha)) / n, 1.0)
    return float(np.quantile(scores, level, method="higher"))


def apply_offsets(
    q_lo: np.ndarray, q_hi: np.ndarray, checkpoints: np.ndarray, offsets: dict[str, float]
):
    off = np.array(
        [offsets.get(CHECKPOINT_GROUP[int(c)], offsets["__global__"]) for c in checkpoints]
    )
    return q_lo - off, q_hi + off
