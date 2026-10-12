"""Expand shipments into as-of checkpoint rows (features + targets) for training/evaluation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cascade.domain.network import NETWORK
from cascade.domain.stages import (
    EVENT_INDEX,
    GROUP_OF_STAGE,
    PHYSICAL_GROUPS,
    STAGE_OF_EVENT,
    EventType,
    Stage,
    event_sequence,
)
from cascade.features.registry import FEATURE_NAMES
from cascade.features.snapshot import ShipmentView, build_snapshot
from cascade.sim.external import ExternalSeries

E = EventType
EVENT_OF_STAGE: dict[Stage, EventType] = {s: e for e, s in STAGE_OF_EVENT.items()}
MID_STAGE_EVENTS = (E.ARRIVE_TS, E.DEPART_TS, E.ARRIVE_DEST_PORT, E.DISCHARGED, E.CUSTOMS_CLEARED)
META_COLS = [
    "shipment_id",
    "voyage_id",
    "lane_id",
    "carrier",
    "dest",
    "hub",
    "as_of",
    "kind",
    "current_delay",
    "planned_delivered",
    "planned_departure",
    "floor_plan_remaining_h",
    "floor_elapsed_h",
    "carrier_plan_delay_h",  # carrier's current plan for delivery vs the original commitment
]
TARGET_COLS = ["y_total", "y_remaining", "y_late"] + [f"y_inc_{g.value}" for g in PHYSICAL_GROUPS]


def revisions_by_shipment(
    revisions: pd.DataFrame | None,
) -> dict[str, tuple[tuple[float, dict[EventType, float]], ...]]:
    if revisions is None or revisions.empty:
        return {}
    out: dict[str, tuple[tuple[float, dict[EventType, float]], ...]] = {}
    for sid, g in revisions.groupby("shipment_id"):
        out[str(sid)] = tuple(
            (
                float(r.effective_at.iloc[0]),
                {EventType(e): float(h) for e, h in zip(r.event, r.planned_h, strict=True)},
            )
            for _, r in g.groupby("revision", sort=True)
        )
    return out


def views_from_frames(
    shipments: pd.DataFrame, events: pd.DataFrame, revisions: pd.DataFrame | None = None
) -> dict[str, ShipmentView]:
    rep = events[events.reported]
    rep_map: dict[str, dict[EventType, float]] = {}
    avail_map: dict[str, dict[EventType, float]] = {}
    # older bundles have no availability column: reports were known at their stated time
    avail = rep.available_h if "available_h" in rep.columns else rep.reported_h
    for sid, ev, t, a in zip(rep.shipment_id, rep.event, rep.reported_h, avail, strict=True):
        rep_map.setdefault(sid, {})[EventType(ev)] = float(t)
        avail_map.setdefault(sid, {})[EventType(ev)] = float(a)
    init_map: dict[str, dict[EventType, float]] = {}
    fix_map: dict[str, dict[EventType, float]] = {}
    if "corrected_at" in rep.columns:
        fixed = rep[rep.corrected_at.notna()]
        for sid, ev, first, at in zip(
            fixed.shipment_id,
            fixed.event,
            fixed.initial_reported_h,
            fixed.corrected_at,
            strict=True,
        ):
            init_map.setdefault(sid, {})[EventType(ev)] = float(first)
            fix_map.setdefault(sid, {})[EventType(ev)] = float(at)
    rev_map = revisions_by_shipment(revisions)
    views = {}
    for r in shipments.itertuples(index=False):
        planned = {
            e: float(getattr(r, f"planned_{e.value}"))
            for e in EventType
            if not np.isnan(getattr(r, f"planned_{e.value}"))
        }
        views[r.shipment_id] = ShipmentView(
            shipment_id=r.shipment_id,
            lane_id=r.lane_id,
            carrier=r.carrier,
            commodity_risk=int(r.commodity_risk),
            docs_complete=bool(r.docs_complete),
            inland_mode=r.inland_mode,
            cargo_value_usd=float(r.cargo_value_usd),
            planned=planned,
            reported=rep_map.get(r.shipment_id, {}),
            carrier_edi_tier=int(r.carrier_edi_tier),
            available=avail_map.get(r.shipment_id, {}),
            initial=init_map.get(r.shipment_id, {}),
            corrected_at=fix_map.get(r.shipment_id, {}),
            revisions=rev_map.get(r.shipment_id, ()),
        )
    return views


def checkpoint_times(
    view: ShipmentView,
    actual: dict[EventType, float],
    rng: np.random.Generator,
    mid_stage: bool = True,
) -> list[tuple[float, str]]:
    seq = event_sequence(NETWORK.lanes[view.lane_id].has_transshipment)
    out = [(view.planned[E.GATE_IN_ORIGIN] - 72.0, "booked")]
    for e in seq[:-1]:
        if e in view.reported:  # a snapshot right after the report *arrives*
            out.append((view.known_at(e) + 1 / 60, "event"))
    if mid_stage:
        for i, e in enumerate(seq):
            if e in MID_STAGE_EVENTS and i > 0:
                t0, t1 = actual[seq[i - 1]], actual[e]
                if t1 - t0 > 2.0:
                    out.append((float(rng.uniform(t0 + 0.5, t1 - 0.5)), "mid"))
    return sorted(out)


def build_rows(
    shipments: pd.DataFrame,
    events: pd.DataFrame,
    ledger: pd.DataFrame,
    ext: ExternalSeries,
    seed: int = 0,
    mid_stage: bool = True,
    events_override: pd.DataFrame | None = None,
    revisions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One row per (shipment, checkpoint). Prior columns are left NaN (fold-specific)."""
    views = views_from_frames(
        shipments, events_override if events_override is not None else events, revisions
    )
    actual_all: dict[str, dict[EventType, float]] = {}
    for sid, ev, t in zip(events.shipment_id, events.event, events.actual_h, strict=True):
        actual_all.setdefault(sid, {})[EventType(ev)] = float(t)
    inc = ledger.groupby(["shipment_id", "stage"]).hours.sum()
    rng = np.random.default_rng(seed)
    rows = []
    for s in shipments.itertuples(index=False):
        view = views[s.shipment_id]
        stage_inc = inc.loc[s.shipment_id]
        for as_of, kind in checkpoint_times(view, actual_all[s.shipment_id], rng, mid_stage):
            snap = build_snapshot(view, as_of, ext)
            if snap.last_event == E.DELIVERED:
                # a late report arrived after delivery was confirmed: nothing left to predict
                continue
            last_idx = EVENT_INDEX[snap.last_event] if snap.last_event is not None else -1
            fut = {g: 0.0 for g in PHYSICAL_GROUPS}
            for stage_name, h in stage_inc.items():
                stage = Stage(stage_name)
                if EVENT_INDEX[EVENT_OF_STAGE[stage]] > last_idx:
                    fut[GROUP_OF_STAGE[stage]] += h
            row = {
                "shipment_id": s.shipment_id,
                "voyage_id": s.voyage_id,
                "lane_id": s.lane_id,
                "carrier": s.carrier,
                "dest": s.dest,
                "hub": s.hub,
                "as_of": snap.as_of,
                "kind": kind,
                "current_delay": snap.current_delay,
                "planned_delivered": snap.planned_delivered,
                "planned_departure": view.planned[E.DEPART_ORIGIN],
                "carrier_plan_delay_h": view.plan_at(as_of)[0][E.DELIVERED]
                - view.planned[E.DELIVERED],
                "floor_plan_remaining_h": float(snap.context["floor_plan_remaining_h"]),
                "floor_elapsed_h": float(snap.context["floor_elapsed_h"]),
                "y_total": s.total_delay_h,
                "y_remaining": s.total_delay_h - snap.current_delay,
                "y_late": float(s.is_late),
                **{f"y_inc_{g.value}": v for g, v in fut.items()},
            }
            row.update(snap.features)
            rows.append(row)
    df = pd.DataFrame(rows)
    return df[META_COLS + list(FEATURE_NAMES) + TARGET_COLS]
