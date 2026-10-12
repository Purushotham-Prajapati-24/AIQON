"""Turn a prediction into stage-level explanations a planner can act on.

Three lenses tell one consistent story:
* realized  — delay already accumulated per completed stage (facts from milestones),
* forecast  — exact additive contributions to the P50 remaining delay, summed by stage group,
* narrative — deterministic templates filled only with numbers from the two lenses above.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from cascade.domain.network import NETWORK
from cascade.domain.stages import (
    GROUP_LABEL,
    PHYSICAL_GROUPS,
    STAGE_LABEL,
    STAGE_OF_EVENT,
    EventType,
    StageGroup,
    event_sequence,
)
from cascade.features.registry import BY_NAME, FEATURE_NAMES
from cascade.features.snapshot import Snapshot
from cascade.models.predictor import future_groups

GROUP_IDX = np.array([list(StageGroup).index(BY_NAME[n].group) for n in FEATURE_NAMES])
ALL_GROUPS = list(StageGroup)


@dataclass
class Driver:
    group: str
    label: str
    contribution_h: float
    top_feature: str
    value: float
    phrase: str


@dataclass
class WaterfallItem:
    label: str
    hours: float
    kind: str  # planned | realized | baseline | forecast | guardrail | total


@dataclass
class Explanation:
    drivers: list[Driver]
    group_contrib: dict[str, float]
    base_h: float
    waterfall: list[WaterfallItem]
    root_cause_group: str
    narratives: dict[str, str] = field(default_factory=dict)
    feature_contrib: dict[str, float] = field(default_factory=dict)


def group_sums(contrib_row: np.ndarray) -> dict[StageGroup, float]:
    sums = np.zeros(len(ALL_GROUPS))
    np.add.at(sums, GROUP_IDX, contrib_row[:-1])
    return {g: float(sums[i]) for i, g in enumerate(ALL_GROUPS)}


def predicted_root_group(
    contrib_row: np.ndarray, checkpoint: int, has_ts: bool, remaining_p50: float, min_h: float = 6.0
) -> str:
    """Future physical stage group with the largest positive contribution (NONE if on track)."""
    if remaining_p50 < min_h:
        return "NONE"
    sums = group_sums(contrib_row)
    fut = [g for g in future_groups(checkpoint, has_ts) if g in PHYSICAL_GROUPS]
    if not fut:
        return "NONE"
    best = max(fut, key=lambda g: sums[g])
    return best.value if sums[best] > 0 else "NONE"


# ---- realized lens ----------------------------------------------------------------------
def realized_items(
    snap: Snapshot, lane_id: str, planned: dict[EventType, float]
) -> list[WaterfallItem]:
    seq = event_sequence(NETWORK.lanes[lane_id].has_transshipment)
    items: list[WaterfallItem] = []
    prev_delay, pending = 0.0, []
    for e in seq:
        if snap.last_event is None or seq.index(e) > seq.index(snap.last_event):
            break
        pending.append(e)
        if e in snap.observed:
            d = snap.observed[e] - planned[e]
            if len(pending) == 1:
                label = STAGE_LABEL[STAGE_OF_EVENT[e]]
            else:
                label = f"{STAGE_LABEL[STAGE_OF_EVENT[pending[0]]]} → {STAGE_LABEL[STAGE_OF_EVENT[e]]} (milestones missing)"
            items.append(WaterfallItem(label, d - prev_delay, "realized"))
            prev_delay, pending = d, []
    return items


# ---- phrases ----------------------------------------------------------------------------
def _pct(x: float) -> str:
    return f"{x:.0%}"


def phrase_for(feature: str, value: float, snap: Snapshot) -> str:
    c = snap.context
    hub, dest, origin = c.get("hub", ""), c.get("dest", ""), c.get("origin", "")
    hub_n = NETWORK.ports[hub].name if hub else "the hub"
    dest_n = NETWORK.ports[dest].name if dest else "destination"
    origin_n = NETWORK.ports[origin].name if origin else "origin"
    f = snap.features
    if feature in (
        "ts_buffer_remaining_h",
        "p_miss_connection_prior",
        "proj_inc_hub_h",
        "projected_hub_arrival_delay_h",
        "planned_ts_buffer_h",
        "rho_hub_fcst",
        "prior_hub_miss_rate",
        "hub_code",
        "headway_h",
        "has_transshipment",
    ):
        b = float(c.get("buffer_rem", 500.0))
        if b < 0:
            return f"projected to reach {hub_n} after the connection cut-off (buffer short by {-b:.0f} h)"
        if b < 400:
            return f"only {b:.0f} h of connection buffer left at {hub_n} ({_pct(float(c.get('p_miss', 0)))} miss risk)"
        return f"transshipment at {hub_n}"
    if feature in (
        "proj_inc_port_h",
        "queue_excess_h",
        "rho_dest_fcst",
        "congestion_x_lateness",
        "berth_window_miss_risk",
        "prior_dest_port_inc",
        "dest_code",
    ):
        rho = float(c.get("rho_dest", np.nan))
        arr = float(c.get("arr_delay", 0.0))
        s = f"{dest_n} berth utilisation forecast at {_pct(rho)}"
        if arr > 12:
            s += f"; arriving {arr:.0f} h late risks losing the berth window"
        return s
    if feature in (
        "proj_inc_customs_h",
        "customs_calendar_shift_h",
        "customs_weekend_risk",
        "holidays_in_customs_window",
        "prior_dest_customs_inc",
    ):
        if float(c.get("cal_shift", 0.0)) > 6:
            return f"customs release projected to fall outside office hours / on a non-working day at {dest_n}"
        return f"customs clearance at {dest_n}"
    if feature in ("inspection_prob_prior", "commodity_risk", "docs_complete"):
        p = f.get("inspection_prob_prior", 0.0)
        docs = "incomplete documents" if f.get("docs_complete", 1.0) < 0.5 else "cargo risk class"
        return f"customs inspection risk {_pct(p)} ({docs})"
    if feature in (
        "proj_inc_ocean_h",
        "weather_fcst_remaining",
        "storm_flag",
        "remaining_absorption_h",
        "projected_arrival_delay_h",
        "delay_velocity_h_per_day",
    ):
        return f"weather along the remaining sea route (severity {f.get('weather_fcst_remaining', 0):.2f})"
    if feature == "overdue_h":
        nxt = (
            snap.next_event.value.replace("_", " ").lower() if snap.next_event else "next milestone"
        )
        return f"{nxt} is {value:.0f} h overdue"
    if feature in ("proj_inc_origin_h", "rho_origin", "carrier_code", "prior_carrier_origin_inc"):
        return f"departure from {origin_n} (congestion {_pct(f.get('rho_origin', 0))}, carrier punctuality history)"
    if feature in ("proj_inc_inland_h", "rail_alignment_h", "inland_rail"):
        if c.get("mode") == "rail" and f.get("rail_alignment_h", 0) > 6:
            return f"projected to miss the block-train cut-off at {dest_n} (+{f['rail_alignment_h']:.0f} h)"
        return "inland leg and consignee receiving window"
    if feature == "current_delay_h":
        return f"delay already accumulated ({snap.current_delay:+.0f} h) and how it propagates"
    if feature in (
        "n_missing_past",
        "completeness_ratio",
        "carrier_edi_tier",
        "hours_since_last_event",
    ):
        return f"{int(f.get('n_missing_past', 0))} milestone(s) missing from the carrier feed"
    if feature in ("prior_lane_mean_delay", "lane_code"):
        return "this lane's delay history"
    return feature.replace("_", " ")


def build_explanation(
    snap: Snapshot,
    contrib_row: np.ndarray,
    delay_p10: float,
    delay_p50: float,
    delay_p90: float,
    p_late: float,
    planned: dict[EventType, float],
    lane_id: str,
    shipment_id: str,
    late_threshold_h: float = 24.0,
    top_k: int = 5,
    flags: dict | None = None,
) -> Explanation:
    flags = flags or {}
    sums = group_sums(contrib_row)
    base = float(contrib_row[-1])
    fc = {n: float(v) for n, v in zip(FEATURE_NAMES, contrib_row[:-1], strict=True)}

    drivers: list[Driver] = []
    for g in sorted(ALL_GROUPS, key=lambda g: -abs(sums[g])):
        if abs(sums[g]) < 0.5:
            continue
        idx = [i for i, n in enumerate(FEATURE_NAMES) if BY_NAME[n].group == g]
        sign = 1.0 if sums[g] >= 0 else -1.0
        top = max(
            idx, key=lambda i: contrib_row[i] * sign
        )  # feature pushing hardest in the group's direction
        name = FEATURE_NAMES[top]
        drivers.append(
            Driver(
                g.value,
                GROUP_LABEL[g],
                sums[g],
                name,
                float(snap.features[name]),
                phrase_for(name, float(snap.features[name]), snap),
            )
        )
    drivers = drivers[:top_k]

    # waterfall: realized stages, typical remaining (bias), forecast groups, guardrail -> total
    wf = realized_items(snap, lane_id, planned)
    wf.append(WaterfallItem("Typical remaining delay", base, "baseline"))
    for g in sorted(ALL_GROUPS, key=lambda g: -abs(sums[g])):
        if abs(sums[g]) >= 0.05:
            wf.append(WaterfallItem(GROUP_LABEL[g], sums[g], "forecast"))
    raw = snap.current_delay + base + sum(sums.values())
    if abs(delay_p50 - raw) > 0.05:
        wf.append(WaterfallItem("Consistency guardrail", delay_p50 - raw, "guardrail"))
    wf.append(WaterfallItem("Expected total delay (P50)", delay_p50, "total"))

    has_ts = bool(snap.features["has_transshipment"])
    root = predicted_root_group(
        contrib_row, snap.checkpoint, has_ts, delay_p50 - snap.current_delay
    )
    exp = Explanation(
        drivers, {g.value: v for g, v in sums.items()}, base, wf, root, feature_contrib=fc
    )
    exp.narratives = render_narratives(
        exp, snap, shipment_id, delay_p10, delay_p50, delay_p90, p_late, late_threshold_h, flags
    )
    return exp


# ---- narratives -------------------------------------------------------------------------
def fmt_duration(h: float) -> str:
    a = abs(h)
    return f"{a / 24:.1f} days" if a >= 48 else f"{a:.0f} h"


def _late_word(h: float) -> str:
    if h > 1:
        return f"{fmt_duration(h)} late"
    if h < -1:
        return f"{fmt_duration(h)} early"
    return "on time"


ACTION_HINTS = {
    "TRANSSHIPMENT": "Check the next sailing from the hub and consider re-booking or priority loading.",
    "PORT": "Ask the terminal about berth priority; pre-book drayage for the expected discharge time.",
    "CUSTOMS": "Pre-file customs documents and request weekend/overtime clearance if available.",
    "OCEAN": "Monitor vessel progress; inform the consignee of the revised window.",
    "ORIGIN": "Confirm vessel departure with the carrier; consider an alternative sailing.",
    "INLAND": "Secure an earlier rail slot or switch to truck for the final leg.",
}


def render_narratives(
    exp: Explanation,
    snap: Snapshot,
    sid: str,
    p10: float,
    p50: float,
    p90: float,
    p_late: float,
    tau: float,
    flags: dict,
) -> dict[str, str]:
    if snap.checkpoint >= 9:  # delivered: report facts, not forecasts
        realized = [w for w in exp.waterfall if w.kind == "realized"]
        worst = max(realized, key=lambda w: w.hours) if realized else None
        why = (
            f" Largest contribution: {worst.label} ({worst.hours:+.0f} h)."
            if worst and worst.hours > 1
            else ""
        )
        txt = f"{sid} was delivered {_late_word(snap.current_delay)}.{why}"
        return {
            "ops": txt,
            "customer": f"Your shipment was delivered {_late_word(snap.current_delay)}.",
            "analyst": txt,
        }
    phys = [
        d
        for d in exp.drivers
        if d.group in {g.value for g in PHYSICAL_GROUPS} and d.contribution_h > 0
    ]
    head = (
        f"{sid} is expected {_late_word(p50)} (likely {fmt_duration(p10)}–{fmt_duration(p90)} "
        f"{'late' if p10 >= 0 else 'vs plan'}); {p_late:.0%} chance of more than {tau:.0f} h late."
    )
    width = p90 - p10
    if flags.get("degraded"):
        conf = "Confidence is low: a fallback estimate was used."
    elif snap.missing_events:
        conf = (
            f"Confidence is reduced: {len(snap.missing_events)} milestone(s) missing from the feed."
        )
    elif width > 96:
        conf = "Confidence is medium: wide range because several uncertain stages remain."
    else:
        conf = "Confidence is high."
    ops = [head]
    if snap.current_delay > 1:
        ops.append(f"Already {fmt_duration(snap.current_delay)} behind plan.")
    if phys:
        ops.append(
            f"Main driver: {phys[0].label} — {phys[0].phrase} (+{phys[0].contribution_h:.0f} h)."
        )
        if len(phys) > 1:
            ops.append(
                f"Also contributing: {phys[1].label} — {phys[1].phrase} (+{phys[1].contribution_h:.0f} h)."
            )
        ops.append(f"Suggested action: {ACTION_HINTS.get(phys[0].group, 'Monitor closely.')}")
    ops.append(conf)
    neutral = {
        "TRANSSHIPMENT": "a vessel connection delay in transit",
        "PORT": "congestion at the destination port",
        "CUSTOMS": "customs processing time",
        "OCEAN": "conditions at sea",
        "ORIGIN": "a later departure from origin",
        "INLAND": "final-mile scheduling",
    }
    if p50 > 6 and phys:
        cust = f"Your shipment is now expected about {fmt_duration(p50)} later than planned due to {neutral.get(phys[0].group, 'operational delays')}."
    elif p50 > 6:
        cust = f"Your shipment is now expected about {fmt_duration(p50)} later than planned."
    else:
        cust = "Your shipment is on track for the planned delivery window."
    top_feats = sorted(exp.feature_contrib.items(), key=lambda kv: -abs(kv[1]))[:5]
    analyst = (
        f"P50 total delay {p50:.1f} h = current {snap.current_delay:.1f} h + base {exp.base_h:.1f} h + "
        + ", ".join(
            f"{k} {v:+.1f}"
            for k, v in sorted(exp.group_contrib.items(), key=lambda kv: -abs(kv[1]))
            if abs(v) >= 0.5
        )
        + ". Top features: "
        + ", ".join(f"{k}={snap.features[k]:.2f} ({v:+.1f} h)" for k, v in top_feats)
        + "."
    )
    return {"ops": " ".join(ops), "customer": cust, "analyst": analyst}
