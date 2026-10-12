"""Structural equations of the shipment SCM.

``plan_shipment`` builds the planned timeline; ``propagate`` turns a plan plus exogenous noise
(``Draws``) into actual timestamps and a *cause ledger*. Because all randomness lives in
``Draws``, re-running ``propagate`` with an ``Intervention`` answers true counterfactual
questions ("what if this vessel had left 6h later?"), which is how explanation and advisor
fidelity are measured.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from cascade.domain.network import (
    BERTH_WINDOW_TOL_H,
    HUB_CUTOFF_H,
    HUB_HANDLING_H,
    HUB_MIN_SLACK_H,
    LAST_MILE_H,
    RAIL_TRANSIT_H,
    TRUCK_PICKUP_PLAN_H,
    TRUCK_SPEED_KMH,
    Lane,
    Network,
    Port,
    customs_release,
    next_rail_departure,
    queue_wait_h,
    receiving_slot,
)
from cascade.domain.stages import STAGE_OF_EVENT, EventType, Stage, event_sequence
from cascade.sim.external import ExternalSeries

E = EventType

# --- mechanism constants (documented assumptions, see docs/Design.md §2.2) ---------------
WEATHER_H_PER_DAY = 1.6  # hours lost per sea-day per unit weather severity
WEATHER_ALLOWANCE = 0.15  # typical severity already priced into schedules
RECOVERY_KAPPA = 0.25  # share of incoming delay a vessel can recover by speeding up
RECOVERY_CAP_H = 18.0
ORIGIN_CONG_H = 60.0  # departure delay per unit utilisation above threshold
ORIGIN_CONG_THRESHOLD = 0.78
HUB_GAMMA = 1.2  # handling slow-down at a congested hub
BERTH_LAMBDA = 0.8  # extra queue multiplier after losing the berth window
CARGO_CUTOFF_H = 24.0
ROLL_HEADWAY_H = 168.0


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def inspection_probability(commodity_risk: int, docs_complete: bool) -> float:
    return sigmoid(-2.6 + 0.9 * commodity_risk + 1.4 * (0 if docs_complete else 1))


def weather_allowance_h(leg_days: float) -> float:
    return WEATHER_H_PER_DAY * WEATHER_ALLOWANCE * leg_days


def hub_handling_h(rho_hub: float, priority: bool = False) -> float:
    if priority:
        return HUB_HANDLING_H
    return HUB_HANDLING_H * (1.0 + HUB_GAMMA * max(0.0, rho_hub - 0.6) / 0.4)


def recovery_cap_h(leg_days: float) -> float:
    return min(RECOVERY_CAP_H, 0.8 * leg_days)


def hub_schedule_anchor(lane: Lane) -> float:
    """Deterministic phase of the connecting service at the hub (hours)."""
    return float(sum(ord(c) for c in lane.lane_id) % int(lane.headway_h))


def planned_pickup_and_delivery(
    t_cleared: float, port: Port, lane: Lane, mode: str
) -> tuple[float, float]:
    if mode == "rail":
        go = next_rail_departure(t_cleared, port)
        travel = RAIL_TRANSIT_H + LAST_MILE_H
    else:
        go = t_cleared + TRUCK_PICKUP_PLAN_H
        travel = lane.inland_km / TRUCK_SPEED_KMH
    return go, receiving_slot(go + travel, port)


@dataclass(frozen=True)
class ShipmentSpec:
    shipment_id: str
    voyage_id: str
    lane_id: str
    carrier: str
    commodity_risk: int
    docs_complete: bool
    inland_mode: str
    cargo_value_usd: float
    planned: dict[EventType, float]


@dataclass(frozen=True)
class Draws:
    """Exogenous noise (the U-variables of the SCM)."""

    gate_in_late: float
    dep_base: float  # voyage-shared Gamma(1.5, carrier scale)
    dep_base_rolled: float
    dep_storm: float
    ocean1: float
    ocean2: float
    hub_vessel: float
    hub_vessel2: float
    hub_ln: float
    discharge_ln: float
    customs_ln: float
    insp_u: float
    insp_extra: float
    pickup_ln: float
    road_ln: float
    rail_noise: float


@dataclass
class Intervention:
    inject: dict[EventType, float] = field(default_factory=dict)  # extra hours at an event
    docs_complete: bool | None = None
    inland_mode: str | None = None
    dest_rho: float | None = None  # berth utilisation at arrival
    hub_priority: bool = False
    customs_weekend: bool | None = None


@dataclass
class Outcome:
    actual: dict[EventType, float]
    ledger: list[tuple[Stage, str, float]]  # (stage, cause, hours)
    rolled: bool = False
    missed_connections: int = 0


def plan_shipment(
    lane: Lane,
    net: Network,
    p_dep: float,
    gate_in_lead_h: float,
    mode: str,
    connection_slack_h: float = 12.0,
) -> dict[EventType, float]:
    o, d = net.ports[lane.origin], net.ports[lane.dest]
    p: dict[EventType, float] = {E.GATE_IN_ORIGIN: p_dep - gate_in_lead_h, E.DEPART_ORIGIN: p_dep}
    if lane.hub:
        p[E.ARRIVE_TS] = p_dep + lane.leg1_days * 24 + weather_allowance_h(lane.leg1_days)
        # network design: the connecting rotation leaves MIN_SLACK + a voyage-specific slack
        p[E.DEPART_TS] = (
            p[E.ARRIVE_TS] + HUB_HANDLING_H + HUB_CUTOFF_H + HUB_MIN_SLACK_H + connection_slack_h
        )
        last_dep, last_days = p[E.DEPART_TS], lane.leg2_days
    else:
        last_dep, last_days = p_dep, lane.leg1_days
    p[E.ARRIVE_DEST_PORT] = last_dep + last_days * 24 + weather_allowance_h(last_days)
    p[E.DISCHARGED] = p[E.ARRIVE_DEST_PORT] + queue_wait_h(d.base_util, d.w0_h) + d.discharge_h
    p[E.CUSTOMS_CLEARED] = customs_release(
        p[E.DISCHARGED] + d.customs_base_h, d
    )  # calendar-aware plan
    p[E.GATE_OUT], p[E.DELIVERED] = planned_pickup_and_delivery(p[E.CUSTOMS_CLEARED], d, lane, mode)
    del o
    return p


def _ocean_leg(
    t_dep: float, delay_in: float, days: float, region: str, noise: float, ext: ExternalSeries
) -> tuple[float, dict[str, float]]:
    wx = ext.weather_mean(region, t_dep, t_dep + days * 24)
    weather_h = WEATHER_H_PER_DAY * wx * days
    sail_noise = noise * (2.0 + 0.12 * days)
    recovery = min(
        RECOVERY_KAPPA * max(delay_in + weather_h - weather_allowance_h(days), 0.0),
        recovery_cap_h(days),
    )
    duration = days * 24 + weather_h + sail_noise - recovery
    comps = {
        "weather": weather_h - weather_allowance_h(days),
        "speed_recovery": -recovery,
        "sailing_variance": sail_noise,
    }
    return t_dep + duration, comps


def propagate(
    spec: ShipmentSpec,
    draws: Draws,
    ext: ExternalSeries,
    net: Network,
    iv: Intervention | None = None,
) -> Outcome:
    iv = iv or Intervention()
    lane = net.lanes[spec.lane_id]
    o, d = net.ports[lane.origin], net.ports[lane.dest]
    p = spec.planned
    a: dict[EventType, float] = {}
    comps: dict[EventType, dict[str, float]] = {}
    inj = iv.inject

    def delay(e: EventType) -> float:
        return a[e] - p[e]

    # 1) pre-carriage: shipper delivers the box to the origin terminal
    a[E.GATE_IN_ORIGIN] = p[E.GATE_IN_ORIGIN] + draws.gate_in_late + inj.get(E.GATE_IN_ORIGIN, 0.0)
    comps[E.GATE_IN_ORIGIN] = {"shipper_late": draws.gate_in_late}

    # 2) vessel departure (voyage-shared delay) and cargo cut-off / rolling
    rho_o = ext.rho(o.code, p[E.DEPART_ORIGIN])
    cong = ORIGIN_CONG_H * max(0.0, rho_o - ORIGIN_CONG_THRESHOLD)
    wx_o = ext.weather_mean(o.region, p[E.DEPART_ORIGIN] - 24, p[E.DEPART_ORIGIN] + 24)
    storm = draws.dep_storm if wx_o > 0.55 else 0.0
    vd = draws.dep_base + cong + storm
    rolled = a[E.GATE_IN_ORIGIN] > p[E.DEPART_ORIGIN] + vd - CARGO_CUTOFF_H
    gi_delay = delay(E.GATE_IN_ORIGIN)
    if rolled:
        a[E.DEPART_ORIGIN] = p[E.DEPART_ORIGIN] + ROLL_HEADWAY_H + draws.dep_base_rolled
        comps[E.DEPART_ORIGIN] = {
            "rolled_cargo": ROLL_HEADWAY_H,
            "carrier_late_departure": draws.dep_base_rolled,
            "slack_absorption": -gi_delay,
        }
    else:
        a[E.DEPART_ORIGIN] = p[E.DEPART_ORIGIN] + vd
        comps[E.DEPART_ORIGIN] = {
            "carrier_late_departure": draws.dep_base,
            "origin_congestion": cong,
            "weather": storm,
            "slack_absorption": -gi_delay,
        }
    a[E.DEPART_ORIGIN] += inj.get(E.DEPART_ORIGIN, 0.0)

    # 3) first ocean leg
    missed = 0
    if lane.hub:
        hub = net.ports[lane.hub]
        a[E.ARRIVE_TS], comps[E.ARRIVE_TS] = _ocean_leg(
            a[E.DEPART_ORIGIN],
            delay(E.DEPART_ORIGIN),
            lane.leg1_days,
            lane.leg1_region,
            draws.ocean1,
            ext,
        )
        a[E.ARRIVE_TS] += inj.get(E.ARRIVE_TS, 0.0)

        # 4) transshipment: make the connection or wait for the next sailing
        rho_h = ext.rho(hub.code, a[E.ARRIVE_TS])
        vessel_factor = 1.0 + 2.0 * max(0.0, rho_h - 0.7)
        cv = draws.hub_vessel * vessel_factor
        handling = hub_handling_h(rho_h, iv.hub_priority) * math.exp(0.2 * draws.hub_ln)
        ready = a[E.ARRIVE_TS] + handling
        cutoff = p[E.DEPART_TS] + cv - HUB_CUTOFF_H
        arr_delay = delay(E.ARRIVE_TS)
        if ready <= cutoff:
            a[E.DEPART_TS] = p[E.DEPART_TS] + cv
            comps[E.DEPART_TS] = {"connecting_vessel_delay": cv, "slack_absorption": -arr_delay}
        else:
            missed = math.ceil((ready - cutoff) / lane.headway_h)
            cv2 = draws.hub_vessel2 * vessel_factor
            a[E.DEPART_TS] = p[E.DEPART_TS] + missed * lane.headway_h + cv2
            base_ready = a[E.ARRIVE_TS] + HUB_HANDLING_H * math.exp(0.2 * draws.hub_ln)
            cause = (
                "missed_connection_hub_congestion" if base_ready <= cutoff else "missed_connection"
            )
            comps[E.DEPART_TS] = {
                cause: missed * lane.headway_h,
                "connecting_vessel_delay": cv2,
                "slack_absorption": -arr_delay,
            }
        a[E.DEPART_TS] += inj.get(E.DEPART_TS, 0.0)
        last_dep, last_days, last_region, last_noise = (
            E.DEPART_TS,
            lane.leg2_days,
            lane.leg2_region,
            draws.ocean2,
        )
    else:
        last_dep, last_days, last_region, last_noise = (
            E.DEPART_ORIGIN,
            lane.leg1_days,
            lane.leg1_region,
            draws.ocean1,
        )

    # 5) final ocean leg
    a[E.ARRIVE_DEST_PORT], comps[E.ARRIVE_DEST_PORT] = _ocean_leg(
        a[last_dep], delay(last_dep), last_days, last_region, last_noise, ext
    )
    a[E.ARRIVE_DEST_PORT] += inj.get(E.ARRIVE_DEST_PORT, 0.0)

    # 6) berth queue (non-linear in utilisation) x lateness (lost berth window)
    arr_delay = delay(E.ARRIVE_DEST_PORT)
    rho_d = iv.dest_rho if iv.dest_rho is not None else ext.rho(d.code, a[E.ARRIVE_DEST_PORT])
    w = queue_wait_h(rho_d, d.w0_h)
    w_plan = queue_wait_h(d.base_util, d.w0_h)
    extra = w * BERTH_LAMBDA * rho_d if arr_delay > BERTH_WINDOW_TOL_H else 0.0
    discharge = (
        d.discharge_h * math.exp(0.25 * draws.discharge_ln) * (1 + 0.5 * max(0.0, rho_d - 0.8))
    )
    a[E.DISCHARGED] = a[E.ARRIVE_DEST_PORT] + w + extra + discharge + inj.get(E.DISCHARGED, 0.0)
    comps[E.DISCHARGED] = {
        "berth_queue": w - w_plan,
        "berth_window_miss": extra,
        "discharge_variance": discharge - d.discharge_h,
    }

    # 7) customs: variance + risk-driven inspection + office-hours calendar
    docs = spec.docs_complete if iv.docs_complete is None else iv.docs_complete
    proc = d.customs_base_h * math.exp(0.3 * draws.customs_ln)
    insp = (
        draws.insp_extra
        if draws.insp_u < inspection_probability(spec.commodity_risk, docs)
        else 0.0
    )
    ready_c = a[E.DISCHARGED] + proc + insp
    port_c = d if iv.customs_weekend is None else _with_weekend(d, iv.customs_weekend)
    release = customs_release(ready_c, port_c)
    a[E.CUSTOMS_CLEARED] = release + inj.get(E.CUSTOMS_CLEARED, 0.0)
    planned_shift = p[E.CUSTOMS_CLEARED] - (p[E.DISCHARGED] + d.customs_base_h)
    comps[E.CUSTOMS_CLEARED] = {
        "customs_variance": proc - d.customs_base_h,
        "customs_inspection": insp,
        "weekend_holiday_closure": (release - ready_c) - planned_shift,
    }

    # 8) pickup and 9) inland delivery with consignee receiving windows
    mode = iv.inland_mode or spec.inland_mode
    rho_t = ext.rho(d.code, a[E.CUSTOMS_CLEARED])
    if mode == "rail":
        a[E.GATE_OUT] = next_rail_departure(a[E.CUSTOMS_CLEARED], d)
        travel = RAIL_TRANSIT_H + 3.0 * draws.rail_noise + LAST_MILE_H
        travel_plan = RAIL_TRANSIT_H + LAST_MILE_H
    else:
        pick_var = TRUCK_PICKUP_PLAN_H * (math.exp(0.35 * draws.pickup_ln) - 1.0)
        pick_cong = 15.0 * max(0.0, rho_t - 0.8)
        a[E.GATE_OUT] = a[E.CUSTOMS_CLEARED] + TRUCK_PICKUP_PLAN_H + pick_var + pick_cong
        travel_plan = lane.inland_km / TRUCK_SPEED_KMH
        travel = travel_plan * math.exp(0.12 * draws.road_ln)
    a[E.GATE_OUT] += inj.get(E.GATE_OUT, 0.0)
    pick_delta = delay(E.GATE_OUT) - delay(E.CUSTOMS_CLEARED)
    if mode == "rail" and mode == spec.inland_mode:
        comps[E.GATE_OUT] = {
            ("missed_rail_cutoff" if pick_delta > 0 else "slack_absorption"): pick_delta
        }
    elif mode == "truck" and mode == spec.inland_mode:
        comps[E.GATE_OUT] = {"pickup_variance": pick_var, "terminal_congestion": pick_cong}
    else:
        comps[E.GATE_OUT] = {"mode_change": pick_delta}

    arrive = a[E.GATE_OUT] + travel
    a[E.DELIVERED] = receiving_slot(arrive, d) + inj.get(E.DELIVERED, 0.0)
    p_travel_end = p[E.GATE_OUT] + (
        RAIL_TRANSIT_H + LAST_MILE_H
        if spec.inland_mode == "rail"
        else lane.inland_km / TRUCK_SPEED_KMH
    )
    comps[E.DELIVERED] = {
        "road_rail_variance": travel - travel_plan,
        "receiving_window": (a[E.DELIVERED] - arrive) - (p[E.DELIVERED] - p_travel_end),
    }
    if mode != spec.inland_mode:
        comps[E.DELIVERED]["mode_change"] = travel_plan - (p_travel_end - p[E.GATE_OUT])

    # ---- assemble an exact ledger: components + injected + residual == stage increment
    ledger: list[tuple[Stage, str, float]] = []
    prev = 0.0
    for e in event_sequence(lane.has_transshipment):
        inc = delay(e) - prev
        prev = delay(e)
        named = {k: v for k, v in comps[e].items() if abs(v) > 1e-9}
        if inj.get(e):
            named["injected"] = inj[e]
        resid = inc - sum(named.values())
        if abs(resid) > 1e-6:
            named["other"] = resid
        stage = STAGE_OF_EVENT[e]
        ledger.extend((stage, k, v) for k, v in named.items())
    return Outcome(actual=a, ledger=ledger, rolled=rolled, missed_connections=missed)


def _with_weekend(port: Port, weekend: bool) -> Port:
    from dataclasses import replace

    return replace(port, customs_weekend=weekend)


def sample_draws(rng: np.random.Generator, carrier_scale: float, dep_base: float) -> Draws:
    late = rng.exponential(10.0) if rng.random() < 0.12 else rng.normal(0.0, 1.5)
    return Draws(
        gate_in_late=float(late),
        dep_base=dep_base,
        dep_base_rolled=float(rng.gamma(1.5, carrier_scale)),
        dep_storm=float(rng.uniform(8, 30)),
        ocean1=float(rng.standard_normal()),
        ocean2=float(rng.standard_normal()),
        hub_vessel=float(rng.gamma(1.5, 4.0)),
        hub_vessel2=float(rng.gamma(1.5, 4.0)),
        hub_ln=float(rng.standard_normal()),
        discharge_ln=float(rng.standard_normal()),
        customs_ln=float(rng.standard_normal()),
        insp_u=float(rng.random()),
        insp_extra=float(rng.gamma(2.0, 18.0)),
        pickup_ln=float(rng.standard_normal()),
        road_ln=float(rng.standard_normal()),
        rail_noise=float(rng.standard_normal()),
    )
