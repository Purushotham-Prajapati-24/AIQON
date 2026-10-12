"""Intervention Advisor: rank a fixed, auditable action menu by counterfactual value.

Each action maps to an explicit snapshot override (``WhatIf``); its value is estimated with the
same model. Advisory only — model counterfactuals are associational, so on synthetic data the
advisor is validated against true SCM interventions (advisor fidelity).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from cascade.domain.network import NETWORK
from cascade.domain.stages import EVENT_INDEX, EventType
from cascade.features.snapshot import Snapshot, WhatIf

E = EventType


@dataclass(frozen=True)
class Action:
    action_id: str
    label: str
    description: str
    cost_usd: float
    whatif: WhatIf


@dataclass
class Recommendation:
    action_id: str
    label: str
    description: str
    hours_saved: float
    usd_saved: float
    action_cost_usd: float
    net_value_usd: float
    p_late_after: float
    feasible_reason: str


def candidate_actions(
    snap: Snapshot, docs_complete: bool, inland_mode: str, lane_id: str
) -> list[tuple[Action, str]]:
    lane = NETWORK.lanes[lane_id]
    dest = NETWORK.ports[lane.dest]
    cp = snap.checkpoint  # index of next unobserved event
    out: list[tuple[Action, str]] = []
    if not docs_complete and cp <= EVENT_INDEX[E.DISCHARGED]:
        out.append(
            (
                Action(
                    "prefile_docs",
                    "Pre-file customs documents",
                    "Complete and pre-lodge the customs declaration before discharge.",
                    60.0,
                    WhatIf(docs_complete=True),
                ),
                "documents incomplete; customs not started",
            )
        )
    if cp <= EVENT_INDEX[E.DISCHARGED]:
        out.append(
            (
                Action(
                    "priority_berth",
                    "Request berth priority / fast lane",
                    f"Book a priority berthing window at {dest.name}.",
                    900.0,
                    WhatIf(dest_rho=dest.base_util),
                ),
                "vessel not yet discharged",
            )
        )
    if (
        lane.has_transshipment
        and cp <= EVENT_INDEX[E.ARRIVE_TS] + 1
        and float(snap.context.get("p_miss", 0.0)) > 0.2
    ):
        out.append(
            (
                Action(
                    "hub_priority",
                    "Priority transshipment handling",
                    f"Pay for guaranteed priority loading at {NETWORK.ports[lane.hub or ''].name}.",
                    450.0,
                    WhatIf(hub_priority=True),
                ),
                "connection not yet made and at risk",
            )
        )
    if (
        not dest.customs_weekend
        and cp <= EVENT_INDEX[E.CUSTOMS_CLEARED]
        and snap.features.get("customs_calendar_shift_h", 0) > 6
    ):
        out.append(
            (
                Action(
                    "weekend_customs",
                    "Book overtime / weekend customs clearance",
                    "Request out-of-hours clearance to avoid the weekend/holiday wait.",
                    250.0,
                    WhatIf(customs_weekend=True),
                ),
                "release projected in a non-working slot",
            )
        )
    if inland_mode == "rail" and cp <= EVENT_INDEX[E.GATE_OUT]:
        out.append(
            (
                Action(
                    "rail_to_truck",
                    "Switch final leg from rail to truck",
                    "Book a truck instead of the next block train.",
                    400.0,
                    WhatIf(inland_mode="truck"),
                ),
                "rail leg not yet started",
            )
        )
    return out


def rank_actions(
    actions: list[tuple[Action, str]],
    evaluate: Callable[[WhatIf | None], tuple[float, float, float]],
    top_k: int = 5,
) -> list[Recommendation]:
    """`evaluate(whatif)` -> (delay_p50_h, p_late, expected_cost_usd)."""
    base_delay, _, base_cost = evaluate(None)
    recs = []
    for a, why in actions:
        d, p, c = evaluate(a.whatif)
        usd_saved = base_cost - c
        recs.append(
            Recommendation(
                a.action_id,
                a.label,
                a.description,
                base_delay - d,
                usd_saved,
                a.cost_usd,
                usd_saved - a.cost_usd,
                p,
                why,
            )
        )
    recs.sort(key=lambda r: (-r.net_value_usd, -r.hours_saved))
    return recs[:top_k]
