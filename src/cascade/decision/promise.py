"""Promise ETA: a customer-facing committed date that moves only on strong evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass

P80_FROM_P50_P90 = 0.8416 / 1.2816  # normal-quantile ratio: P80 = P50 + 0.657 (P90 - P50)
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
    eta_p90_h: float,
    width_h: float,
    tier: str,
) -> PromiseState:
    p80 = eta_p50_h + P80_FROM_P50_P90 * max(eta_p90_h - eta_p50_h, 0.0)
    candidate = promise_day_end(p80)
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
