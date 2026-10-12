"""Intervention Advisor: rank a fixed, auditable action menu by counterfactual value.

Each action maps to an explicit snapshot override (``WhatIf``); its value is estimated with the
same model. Advisory only — model counterfactuals are associational, so on synthetic data the
advisor is validated against true SCM interventions (advisor fidelity).

Every recommendation states three separate validity checks, because an action can be
mechanically sensible yet impossible to arrange in time, or possible but not worth its cost:
* mechanically_valid     — the scenario forecast is internally consistent (ordered, not in the past),
* operationally_feasible — the stage has not passed and there is still time to arrange it
                           before its cut-off milestone (projected, with a booking lead time),
* economically_justified — the delay cost it avoids exceeds what it costs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from cascade.domain.network import NETWORK
from cascade.domain.stages import EVENT_INDEX, EventType
from cascade.features.snapshot import Snapshot, WhatIf

E = EventType

# re-score each action as if the shipment ran this much later than currently expected
SENSITIVITY_SHIFTS_H = (0.0, 6.0, 12.0)


@dataclass(frozen=True)
class Action:
    action_id: str
    label: str
    description: str
    cost_usd: float
    whatif: WhatIf
    deadline_event: EventType  # must be arranged before this milestone happens
    lead_time_h: float  # time needed to arrange it before that milestone
    assumptions: tuple[str, ...] = ()


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
    feasible_reason: str  # the preconditions that make the action applicable now
    assumptions: list[str] = field(default_factory=list)
    limitations: str = (
        "Model-based (associational) estimate; availability, price and the operator's response "
        "are not verified."
    )
    baseline: dict[str, float] = field(default_factory=dict)  # p10/p50/p90 delay h, p_late
    scenario: dict[str, float] = field(default_factory=dict)
    deadline_event: str = ""
    hours_to_deadline: float = 0.0  # projected time left before the cut-off, minus lead time
    benefit_range_h: list[float] = field(default_factory=list)  # min/max over sensitivity shifts
    validity: dict[str, bool] = field(default_factory=dict)


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
                    "Complete and pre-lodge the customs declaration before the vessel arrives.",
                    60.0,
                    WhatIf(docs_complete=True),
                    E.ARRIVE_DEST_PORT,
                    24.0,
                    ("complete documents remove the incomplete-docs inspection risk",),
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
                    E.ARRIVE_DEST_PORT,
                    48.0,
                    (f"berth wait falls to {dest.name}'s normal (uncongested) level",),
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
                    E.DEPART_TS,
                    24.0,
                    ("priority handling shortens hub handling enough to make the connection",),
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
                    E.CUSTOMS_CLEARED,
                    12.0,
                    ("the customs office accepts an out-of-hours slot for this shipment",),
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
                    E.GATE_OUT,
                    12.0,
                    ("a truck and a delivery appointment are available at the quoted rate",),
                ),
                "rail leg not yet started",
            )
        )
    return out


def hours_to_deadline(a: Action, snap: Snapshot, planned: dict[EventType, float] | None) -> float:
    """Projected time left to arrange the action before its cut-off milestone (minus lead time)."""
    if planned is None or a.deadline_event not in planned:
        return float("inf")
    if a.deadline_event in snap.observed:  # the cut-off milestone already happened
        return -float("inf")
    t_deadline = planned[a.deadline_event] + snap.projected_delay.get(
        a.deadline_event, snap.current_delay
    )
    return t_deadline - snap.as_of - a.lead_time_h


def rank_actions(
    actions: list[tuple[Action, str]],
    evaluate: Callable[[WhatIf | None], tuple[float, float, float]],
    top_k: int = 5,
    snap: Snapshot | None = None,
    planned: dict[EventType, float] | None = None,
    detail: Callable[[WhatIf | None], dict[str, float]] | None = None,
) -> list[Recommendation]:
    """`evaluate(whatif)` -> (delay_p50_h, p_late, expected_cost_usd); `detail(whatif)` ->
    {p10, p50, p90, p_late, eta_ok} for the before/after comparison and validity checks."""
    base_delay, _, base_cost = evaluate(None)
    base_detail = detail(None) if detail else {}
    recs = []
    for a, why in actions:
        d, p, c = evaluate(a.whatif)
        usd_saved = base_cost - c
        net = usd_saved - a.cost_usd
        scen = detail(a.whatif) if detail else {}
        benefits = []
        if detail:
            for s in SENSITIVITY_SHIFTS_H:
                b = base_delay if s == 0 else detail(WhatIf(delay_shift_h=s))["p50"]
                benefits.append(
                    b - (d if s == 0 else detail(replace(a.whatif, delay_shift_h=s))["p50"])
                )
        slack = hours_to_deadline(a, snap, planned) if snap is not None else float("inf")
        mech = bool(scen.get("eta_ok", True)) and (
            scen.get("p10", 0.0) <= scen.get("p50", 0.0) <= scen.get("p90", 0.0)
        )
        recs.append(
            Recommendation(
                a.action_id,
                a.label,
                a.description,
                base_delay - d,
                usd_saved,
                a.cost_usd,
                net,
                p,
                why,
                assumptions=[*a.assumptions, "all other conditions held fixed"],
                baseline={k: v for k, v in base_detail.items() if k != "eta_ok"},
                scenario={k: v for k, v in scen.items() if k != "eta_ok"},
                deadline_event=a.deadline_event.value,
                hours_to_deadline=float(min(slack, 1e6)),
                benefit_range_h=[float(min(benefits)), float(max(benefits))] if benefits else [],
                validity={
                    "mechanically_valid": mech,
                    "operationally_feasible": slack >= 0,
                    "economically_justified": net > 0,
                },
            )
        )
    # feasible actions first, then by net value and hours saved
    recs.sort(
        key=lambda r: (not r.validity["operationally_feasible"], -r.net_value_usd, -r.hours_saved)
    )
    return recs[:top_k]
