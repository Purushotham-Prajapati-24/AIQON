"""As-of snapshot builder — the only entry point from raw shipment state to model features.

Leakage contract: a snapshot at ``as_of`` depends only on the plan, milestones *reported at or
before* ``as_of``, realized external values up to ``as_of`` and *forecasts* beyond it.

Besides plain progress features, the builder runs a physics-informed projection of every
remaining stage (expected recovery at sea, connection buffer at the hub, Kingman berth queue,
customs office hours, rail cut-offs, receiving windows). The projected increments become
stage-specific features, so the learned model corrects a mechanistic prior instead of
starting from scratch, and its explanations stay attributable to stages.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from cascade.domain.network import (
    BERTH_WINDOW_TOL_H,
    CARRIER_CODES,
    HUB_CODES,
    HUB_CUTOFF_H,
    HUB_HANDLING_H,
    LANE_IDS,
    LAST_MILE_H,
    NETWORK,
    PORT_CODES,
    RAIL_TRANSIT_H,
    TRUCK_PICKUP_PLAN_H,
    TRUCK_SPEED_KMH,
    Network,
    customs_release,
    local_parts,
    next_rail_departure,
    queue_wait_h,
    receiving_slot,
)
from cascade.domain.stages import (
    EVENT_INDEX,
    GROUP_OF_STAGE,
    STAGE_OF_EVENT,
    EventType,
    StageGroup,
    checkpoint_after,
    event_sequence,
)
from cascade.sim.external import ExternalSeries
from cascade.sim.mechanics import weather_allowance_h

# ---- operator rulebook ----------------------------------------------------------------------
# The projection knows the *structure* an operator knows (schedules, cut-offs, headways, office
# hours, rail timetables, receiving windows, the shape of berth queues) but only rough
# rule-of-thumb *coefficients*. They deliberately differ from the simulator's true parameters
# (truth in sim/mechanics.py) so the learned model has real calibration work to do and the
# evaluation is not circular.
OP_WEATHER_H_PER_DAY = 1.2  # truth 1.6
OP_RECOVERY_KAPPA = 0.35  # truth 0.25
OP_RECOVERY_CAP_H = 24.0  # truth 18
OP_ORIGIN_CONG_H = 40.0  # truth 60
OP_ORIGIN_CONG_THRESHOLD = 0.80  # truth 0.78
OP_BERTH_LAMBDA = 0.5  # truth 0.8
OP_HUB_GAMMA = 0.8  # truth 1.2
OP_INSPECTION_EXTRA_H = 24.0  # truth mean 36
OP_CONNECTING_VESSEL_H = 4.0  # truth mean 6 x factor


def op_inspection_probability(commodity_risk: int, docs_complete: bool) -> float:
    """Rule of thumb: 5% base, +10pp per risk class, +20pp if documents are incomplete."""
    return min(0.05 + 0.10 * commodity_risk + (0.0 if docs_complete else 0.20), 0.9)


def op_hub_handling_h(rho_hub: float, priority: bool = False) -> float:
    if priority:
        return HUB_HANDLING_H
    return HUB_HANDLING_H * (1.0 + OP_HUB_GAMMA * max(0.0, rho_hub - 0.6) / 0.4)


def op_recovery_cap_h(leg_days: float) -> float:
    return min(OP_RECOVERY_CAP_H, 1.0 * leg_days)


E = EventType
NO_CONNECTION = 500.0  # sentinel: direct route or connection already resolved ("infinite" buffer)
# Silence longer than this past a milestone's due time is treated as a missing EDI report, not
# a hold-up (v1.3: tuned by coordinate descent on the training split of 20 development worlds;
# with 6-31% of reports missing, a short grace window beats reading silence as lateness for
# vessel arrivals, discharge and gate-out). See experiments/ml_optimization/README.md.
MAX_PLAUSIBLE_HOLD_H = {
    E.GATE_IN_ORIGIN: 48.0,
    E.DEPART_ORIGIN: 24.0,
    E.ARRIVE_TS: 12.0,
    E.ARRIVE_DEST_PORT: 12.0,
    E.DISCHARGED: 12.0,
    E.CUSTOMS_CLEARED: 120.0,
    E.GATE_OUT: 12.0,
    E.DELIVERED: 72.0,
}
# A missed connection waits for the next sailing: silence past one headway at the hub is a
# missing DEPART_TS report (only 2 of 6,000 simulated shipments ever miss twice).
HUB_MAX_EXTRA_HOLD_H = 0.0
_LANE_IDX = {k: i for i, k in enumerate(LANE_IDS)}
_CARRIER_IDX = {k: i for i, k in enumerate(CARRIER_CODES)}
_PORT_IDX = {k: i for i, k in enumerate(PORT_CODES)}
_HUB_IDX = {k: i for i, k in enumerate(HUB_CODES)}
_GROUP_FEATURE = {
    StageGroup.ORIGIN: "proj_inc_origin_h",
    StageGroup.OCEAN: "proj_inc_ocean_h",
    StageGroup.TRANSSHIPMENT: "proj_inc_hub_h",
    StageGroup.PORT: "proj_inc_port_h",
    StageGroup.CUSTOMS: "proj_inc_customs_h",
    StageGroup.INLAND: "proj_inc_inland_h",
}


@dataclass(frozen=True)
class ShipmentView:
    """What an operator knows about a shipment: static attributes, plan, reported milestones."""

    shipment_id: str
    lane_id: str
    carrier: str
    commodity_risk: int
    docs_complete: bool
    inland_mode: str
    cargo_value_usd: float
    planned: dict[EventType, float]
    reported: dict[EventType, float]  # event time as stated in the milestone message
    carrier_edi_tier: int = 2
    # When CASCADE could first know each report (>= the event itself). Missing entry = the
    # report was available as soon as its stated event time (live API payloads).
    available: dict[EventType, float] = field(default_factory=dict)
    # Feed corrections: the first message's (wrong) time, and when the correction arrived.
    initial: dict[EventType, float] = field(default_factory=dict)
    corrected_at: dict[EventType, float] = field(default_factory=dict)
    # Carrier schedule versions: ((effective_at, {event: planned_h}), ...). `planned` stays the
    # original commitment that lateness is measured against.
    revisions: tuple[tuple[float, dict[EventType, float]], ...] = ()

    def known_at(self, e: EventType) -> float:
        return self.available.get(e, self.reported[e])

    def known_by(self, t: float) -> dict[EventType, float]:
        """Milestones whose message had arrived by t, with the time *as known at t*: the first
        (possibly wrong) value until its correction arrives."""
        out = {}
        for e, ts in self.reported.items():
            if self.known_at(e) > t:
                continue
            fixed = self.corrected_at.get(e)
            out[e] = (
                self.initial[e] if fixed is not None and fixed > t and e in self.initial else ts
            )
        return out

    def plan_at(self, t: float) -> tuple[dict[EventType, float], int]:
        """The carrier's plan in force at t and how many revisions were known by then."""
        from cascade.domain.feed import plan_at

        return plan_at(self.planned, self.revisions, t)


@dataclass(frozen=True)
class WhatIf:
    """Counterfactual overrides applied at snapshot time (advisor / what-if / sensitivity)."""

    dest_rho: float | None = None
    hub_priority: bool = False
    customs_weekend: bool | None = None
    docs_complete: bool | None = None
    inland_mode: str | None = None
    delay_shift_h: float = 0.0  # shift the last observed milestone (propagation sensitivity)

    def is_empty(self) -> bool:
        return self == WhatIf()


@dataclass
class Snapshot:
    features: dict[str, float]
    as_of: float
    checkpoint: int
    last_event: EventType | None
    current_delay: float
    planned_delivered: float
    observed: dict[EventType, float]
    missing_events: list[EventType]
    next_event: EventType | None
    projected_delay: dict[EventType, float] = field(default_factory=dict)
    projected_group_inc: dict[StageGroup, float] = field(default_factory=dict)
    context: dict[str, float | str] = field(default_factory=dict)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(x, 50.0), -50.0)))


def build_snapshot(
    view: ShipmentView,
    as_of: float,
    ext: ExternalSeries,
    priors: dict[str, float] | None = None,
    whatif: WhatIf | None = None,
    net: Network = NETWORK,
) -> Snapshot:
    wi = whatif or WhatIf()
    lane = net.lanes[view.lane_id]
    dest = net.ports[lane.dest]
    if wi.customs_weekend is not None:
        dest = replace(dest, customs_weekend=wi.customs_weekend)
    origin = net.ports[lane.origin]
    seq = event_sequence(lane.has_transshipment)
    p = view.planned
    docs = view.docs_complete if wi.docs_complete is None else wi.docs_complete
    mode = wi.inland_mode or view.inland_mode

    # information cut-off: a milestone counts only once its report has *arrived* (not merely
    # happened) by as_of; its delay still uses the stated event time
    obs = {e: t for e, t in view.known_by(as_of).items() if e in p}
    last = max(obs, key=lambda e: EVENT_INDEX[e]) if obs else None
    if last is not None and wi.delay_shift_h:
        obs[last] += wi.delay_shift_h
        as_of += wi.delay_shift_h
    pos = seq.index(last) if last is not None else -1
    cur = obs[last] - p[last] if last is not None else 0.0
    missing = [e for e in seq[: pos + 1] if e not in obs]
    next_ev = seq[pos + 1] if pos + 1 < len(seq) else None

    obs_sorted = sorted(obs, key=lambda e: EVENT_INDEX[e])
    delays = [obs[e] - p[e] for e in obs_sorted]
    velocity = 0.0
    if len(obs_sorted) >= 2:
        dt = obs[obs_sorted[-1]] - obs[obs_sorted[-2]]
        if dt > 1.0:
            velocity = (delays[-1] - delays[-2]) / (dt / 24.0)
    overdue = max(0.0, as_of - (p[next_ev] + cur)) if next_ev is not None else 0.0
    # If even the milestone *after* next is already due, the silence is more likely a reporting
    # gap than a real hold-up: do not treat the next milestone as overdue.
    after_next = seq[pos + 2] if pos + 2 < len(seq) else None
    reporting_gap = after_next is not None and as_of > p[after_next] + cur + 12.0
    # A hold-up longer than a stage plausibly causes is also more likely a reporting gap
    # (except at the hub, where a missed connection genuinely means days of waiting).
    if next_ev is not None and overdue > MAX_PLAUSIBLE_HOLD_H.get(next_ev, math.inf):
        reporting_gap = True
    # At the hub a missed connection waits for the next sailing (one headway); silence beyond
    # that is a missing DEPART_TS report while the vessel is already on the second leg.
    if next_ev == E.DEPART_TS and overdue > lane.headway_h + HUB_MAX_EXTRA_HOLD_H:
        reporting_gap = True
    if reporting_gap:
        overdue = 0.0

    # ---- physics-informed projection of every remaining stage ---------------------------
    proj: dict[EventType, float] = {}
    group_inc: dict[StageGroup, float] = {g: 0.0 for g in _GROUP_FEATURE}
    ctx: dict[str, float | str] = {}
    d_prev = cur
    rho_origin = ext.rho_forecast(origin.code, p[E.DEPART_ORIGIN], as_of)
    rho_hub = 0.0
    hub_arr_delay = 0.0
    buffer_rem = NO_CONNECTION
    p_miss = 0.0
    arr_delay = (
        cur
        if last is not None and EVENT_INDEX[last] >= EVENT_INDEX[E.ARRIVE_DEST_PORT]
        else math.nan
    )
    rho_dest = math.nan
    queue_excess = berth_risk = cong_x_late = 0.0
    cal_shift = 0.0
    rail_align = 0.0
    wx_num = wx_den = 0.0
    absorption = 0.0
    if lane.has_transshipment and E.ARRIVE_TS in obs:
        hub_arr_delay = obs[E.ARRIVE_TS] - p[E.ARRIVE_TS]
        rho_hub = ext.rho_forecast(lane.hub or "", obs[E.ARRIVE_TS], as_of)

    for e in seq[pos + 1 :]:
        if e == E.GATE_IN_ORIGIN:
            d = d_prev
        elif e == E.DEPART_ORIGIN:
            wx_o = ext.weather_forecast_mean(origin.region, p[e] - 24, p[e] + 24, as_of)
            d = OP_ORIGIN_CONG_H * max(0.0, rho_origin - OP_ORIGIN_CONG_THRESHOLD) + (
                12.0 if wx_o > 0.55 else 0.0
            )
        elif e in (E.ARRIVE_TS, E.ARRIVE_DEST_PORT):
            first_leg = e == E.ARRIVE_TS or not lane.has_transshipment
            days = lane.leg1_days if first_leg else lane.leg2_days
            region = lane.leg1_region if first_leg else lane.leg2_region
            dep_ev = E.DEPART_ORIGIN if first_leg else E.DEPART_TS
            t_dep = p[dep_ev] + d_prev
            wx = ext.weather_forecast_mean(region, t_dep, t_dep + days * 24, as_of)
            weather_h = OP_WEATHER_H_PER_DAY * wx * days - weather_allowance_h(days)
            rec = min(OP_RECOVERY_KAPPA * max(d_prev + weather_h, 0.0), op_recovery_cap_h(days))
            d = d_prev + weather_h - rec
            wx_num += wx * days
            wx_den += days
            absorption += op_recovery_cap_h(days)
            if e == E.ARRIVE_TS:
                hub_arr_delay = max(d, as_of - p[e])
        elif e == E.DEPART_TS:
            hub_arr_delay = d_prev
            rho_hub = ext.rho_forecast(lane.hub or "", p[E.ARRIVE_TS] + d_prev, as_of)
            handling = op_hub_handling_h(rho_hub, wi.hub_priority)
            # a late connecting vessel also extends the cut-off
            buffer_rem = (p[E.DEPART_TS] + OP_CONNECTING_VESSEL_H - HUB_CUTOFF_H) - (
                p[E.ARRIVE_TS] + d_prev + handling
            )
            p_miss = _sigmoid(-buffer_rem / 6.0)
            d = p_miss * lane.headway_h + OP_CONNECTING_VESSEL_H
        elif e == E.DISCHARGED:
            arr_delay = d_prev
            rho_dest = (
                wi.dest_rho
                if wi.dest_rho is not None
                else ext.rho_forecast(dest.code, p[E.ARRIVE_DEST_PORT] + d_prev, as_of)
            )
            w = queue_wait_h(rho_dest, dest.w0_h)
            queue_excess = w - queue_wait_h(dest.base_util, dest.w0_h)
            berth_risk = _sigmoid((d_prev - BERTH_WINDOW_TOL_H) / 3.0)
            cong_x_late = rho_dest * max(d_prev, 0.0)
            d = (
                d_prev
                + queue_excess
                + berth_risk * w * OP_BERTH_LAMBDA * rho_dest
                + 10.0 * max(0.0, rho_dest - 0.8)
            )
        elif e == E.CUSTOMS_CLEARED:
            ready = (
                p[E.DISCHARGED]
                + d_prev
                + dest.customs_base_h
                + op_inspection_probability(view.commodity_risk, docs) * OP_INSPECTION_EXTRA_H
            )
            release = customs_release(ready, dest)
            planned_shift = p[E.CUSTOMS_CLEARED] - (p[E.DISCHARGED] + dest.customs_base_h)
            cal_shift = (release - ready) - planned_shift
            d = release - p[e]
        elif e == E.GATE_OUT:
            t_clear = p[E.CUSTOMS_CLEARED] + d_prev
            if mode == "rail":
                go = next_rail_departure(t_clear, dest)
            else:
                rho_t = ext.rho_forecast(dest.code, t_clear, as_of)
                go = t_clear + TRUCK_PICKUP_PLAN_H + 15.0 * max(0.0, rho_t - 0.8)
            d = go - p[e]
            rail_align = d - d_prev if mode == "rail" else 0.0
        else:  # DELIVERED
            travel = (
                RAIL_TRANSIT_H + LAST_MILE_H if mode == "rail" else lane.inland_km / TRUCK_SPEED_KMH
            )
            d = receiving_slot(p[E.GATE_OUT] + d_prev + travel, dest) - p[e]
        if e == next_ev and not reporting_gap:
            d = max(d, as_of - p[e])  # the next milestone has not happened yet: lower bound
        proj[e] = d
        group_inc[GROUP_OF_STAGE[STAGE_OF_EVENT[e]]] += d - d_prev
        d_prev = d

    if math.isnan(rho_dest):
        t_arr = obs.get(
            E.ARRIVE_DEST_PORT,
            p[E.ARRIVE_DEST_PORT] + (arr_delay if not math.isnan(arr_delay) else cur),
        )
        rho_dest = (
            wi.dest_rho if wi.dest_rho is not None else ext.rho_forecast(dest.code, t_arr, as_of)
        )
    if math.isnan(arr_delay):
        arr_delay = proj.get(E.ARRIVE_DEST_PORT, cur)

    # ---- plan / context features -----------------------------------------------------
    if lane.has_transshipment:
        planned_buffer = p[E.DEPART_TS] - HUB_CUTOFF_H - p[E.ARRIVE_TS] - HUB_HANDLING_H
    else:
        planned_buffer = NO_CONNECTION
    d0, _, _ = local_parts(p[E.DISCHARGED], dest.tz)
    d1, _, _ = local_parts(p[E.CUSTOMS_CLEARED], dest.tz)
    holidays = sum(1 for h in dest.holiday_days if d0 - 1 <= h <= d1 + 3)

    f: dict[str, float] = {
        "lane_code": float(_LANE_IDX[view.lane_id]),
        "carrier_code": float(_CARRIER_IDX.get(view.carrier, -1)),
        "dest_code": float(_PORT_IDX[lane.dest]),
        "hub_code": float(_HUB_IDX[lane.hub or "NONE"]),
        "has_transshipment": float(lane.has_transshipment),
        "inland_rail": float(mode == "rail"),
        "commodity_risk": float(view.commodity_risk),
        "docs_complete": float(docs),
        "inspection_prob_prior": op_inspection_probability(view.commodity_risk, docs),
        "planned_transit_h": p[E.DELIVERED] - p[E.GATE_IN_ORIGIN],
        "planned_ts_buffer_h": planned_buffer,
        "headway_h": lane.headway_h if lane.has_transshipment else 0.0,
        "holidays_in_customs_window": float(holidays),
        "checkpoint": float(checkpoint_after(last)),
        "current_delay_h": cur,
        "delay_velocity_h_per_day": velocity,
        "frac_plan_elapsed": float(
            np.clip(
                (as_of - p[E.GATE_IN_ORIGIN]) / (p[E.DELIVERED] - p[E.GATE_IN_ORIGIN]), -0.2, 1.5
            )
        ),
        "hours_since_last_event": as_of - obs[last] if last is not None else math.nan,
        "overdue_h": overdue,
        "remaining_planned_h": max(p[E.DELIVERED] - as_of, 0.0),
        "projected_hub_arrival_delay_h": hub_arr_delay,
        "ts_buffer_remaining_h": buffer_rem,
        "p_miss_connection_prior": p_miss,
        "projected_arrival_delay_h": arr_delay,
        "queue_excess_h": queue_excess,
        "berth_window_miss_risk": berth_risk,
        "congestion_x_lateness": cong_x_late,
        "customs_calendar_shift_h": cal_shift,
        "customs_weekend_risk": float(cal_shift > 6.0),
        "rail_alignment_h": rail_align,
        "remaining_absorption_h": absorption,
        "rho_origin": rho_origin,
        "rho_hub_fcst": rho_hub,
        "rho_dest_fcst": rho_dest,
        "weather_fcst_remaining": wx_num / wx_den if wx_den else 0.0,
        "storm_flag": float(wx_den > 0 and wx_num / wx_den > 0.5),
        "carrier_edi_tier": float(view.carrier_edi_tier),
        "n_missing_past": float(len(missing)),
        "completeness_ratio": len(obs) / (pos + 1) if pos >= 0 else 1.0,
    }
    for g, name in _GROUP_FEATURE.items():
        f[name] = group_inc[g]
    pr = priors or {}
    for name in (
        "prior_lane_mean_delay",
        "prior_carrier_origin_inc",
        "prior_dest_port_inc",
        "prior_dest_customs_inc",
        "prior_hub_miss_rate",
    ):
        f[name] = pr.get(name, math.nan)

    # inputs of the heuristic ETA floor (the model applies its configured fraction):
    # planned time left after the last reported milestone, and time elapsed since it
    t_last = obs[last] if last is not None else min(as_of, p[E.GATE_IN_ORIGIN])
    p_last = p[last] if last is not None else p[E.GATE_IN_ORIGIN]
    ctx.update(
        floor_plan_remaining_h=max(0.0, p[E.DELIVERED] - p_last),
        floor_elapsed_h=max(as_of - t_last, 0.0),
        reporting_gap=float(reporting_gap),  # silence treated as a missing report, not a hold-up
    )
    ctx.update(
        hub=lane.hub or "",
        dest=lane.dest,
        origin=lane.origin,
        mode=mode,
        rho_dest=rho_dest,
        rho_hub=rho_hub,
        buffer_rem=buffer_rem,
        p_miss=p_miss,
        cal_shift=cal_shift,
        arr_delay=arr_delay,
    )
    return Snapshot(
        features=f,
        as_of=as_of,
        checkpoint=int(checkpoint_after(last)),
        last_event=last,
        current_delay=cur,
        planned_delivered=p[E.DELIVERED],
        observed=obs,
        missing_events=missing,
        next_event=next_ev,
        projected_delay=proj,
        projected_group_inc=group_inc,
        context=ctx,
    )
