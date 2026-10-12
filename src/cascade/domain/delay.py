"""Single source of truth for ETA / delay arithmetic.

All times are float hours since ``EPOCH`` (UTC). Positive delay = late.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from cascade.domain.stages import STAGE_OF_EVENT, EventType, Stage, event_sequence

EPOCH = datetime(2025, 1, 1, tzinfo=UTC)  # a Wednesday
EPOCH_WEEKDAY = 2  # Monday = 0

DEFAULT_LATE_THRESHOLD_H = 24.0


def to_hours(ts: datetime) -> float:
    if ts.tzinfo is None:
        raise ValueError("naive datetime: all timestamps must be timezone-aware")
    return (ts - EPOCH).total_seconds() / 3600.0


def to_datetime(hours: float) -> datetime:
    return EPOCH + timedelta(hours=float(hours))


def event_delays(
    planned: Mapping[EventType, float], actual: Mapping[EventType, float]
) -> dict[EventType, float]:
    """delay(e) = actual(e) - planned(e) for every event present in both."""
    return {e: actual[e] - planned[e] for e in actual if e in planned}


def stage_increments(
    planned: Mapping[EventType, float],
    actual: Mapping[EventType, float],
    has_transshipment: bool,
) -> dict[Stage, float]:
    """Delta_k = delay(e_k) - delay(e_{k-1}); requires a complete actual timeline."""
    seq = event_sequence(has_transshipment)
    out: dict[Stage, float] = {}
    prev = 0.0
    for e in seq:
        d = actual[e] - planned[e]
        out[STAGE_OF_EVENT[e]] = d - prev
        prev = d
    return out


def total_delay(planned: Mapping[EventType, float], actual: Mapping[EventType, float]) -> float:
    return actual[EventType.DELIVERED] - planned[EventType.DELIVERED]


def eta_hours(planned_delivered: float, current_delay: float, remaining_delay: float) -> float:
    """ETA = planned(DELIVERED) + delay observed so far + predicted remaining delay."""
    return planned_delivered + current_delay + remaining_delay


def risk_tier(delay_h: float, late_threshold_h: float = DEFAULT_LATE_THRESHOLD_H) -> str:
    if delay_h > late_threshold_h:
        return "LATE"
    if delay_h > 6.0:
        return "AT_RISK"
    return "ON_TRACK"
