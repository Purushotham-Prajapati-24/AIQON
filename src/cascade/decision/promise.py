"""Promise ETA: a customer-facing committed date that moves only on strong evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass

MIN_MOVE_H = 12.0
WIDTH_FRACTION = 0.25


@dataclass(frozen=True)
class PromiseState:
    promise_h: float  # end of the promised UTC day, hours since EPOCH
    set_at: float
    p50_at_set: float
    tier_at_set: str
    reason: str
    changes: int = 0


def promise_day_end(eta_h: float) -> float:
    return (math.floor(eta_h / 24.0) + 1.0) * 24.0


def update_promise(
    prev: PromiseState | None,
    as_of: float,
    eta_p50_h: float,
    eta_p80_h: float,
    width_h: float,
    tier: str,
) -> PromiseState:
    """eta_p80_h: the calibrated P80 ETA (the model's one-sided conformal 80% quantile)."""
    candidate = promise_day_end(eta_p80_h)
    if prev is None:
        return PromiseState(candidate, as_of, eta_p50_h, tier, "initial promise")
    threshold = max(MIN_MOVE_H, WIDTH_FRACTION * width_h)
    moved = abs(eta_p50_h - prev.p50_at_set) > threshold
    tier_changed = tier != prev.tier_at_set
    if (moved or tier_changed) and candidate != prev.promise_h:
        reason = (
            "risk tier changed"
            if tier_changed and not moved
            else f"ETA moved {eta_p50_h - prev.p50_at_set:+.0f} h"
        )
        return PromiseState(candidate, as_of, eta_p50_h, tier, reason, prev.changes + 1)
    return prev
