"""Alert rules over consecutive predictions (deduplicated, each with a narrative)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

TIER_RANK = {"ON_TRACK": 0, "AT_RISK": 1, "LATE": 2}


@dataclass(frozen=True)
class PredState:
    shipment_id: str
    as_of: float
    delay_p50: float
    p_late: float
    tier: str
    promise_h: float | None
    p_miss: float
    checkpoint: int
    hours_since_last_event: float
    expected_gap_h: float  # planned duration of the stage currently in progress
    narrative: str = ""
    data_quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlertEvent:
    """An alert explains what changed, on which evidence, and what to do next."""

    alert_id: str
    shipment_id: str
    rule: str
    severity: str  # info | warn | critical
    created_at: float
    message: str
    reason_code: str = ""
    evidence_ts: float = 0.0  # as-of of the prediction that triggered the alert
    previous_risk: str | None = None
    new_risk: str = ""
    previous_p_late: float | None = None
    new_p_late: float = 0.0
    recommended_next_step: str = ""
    data_quality_flags: tuple[str, ...] = ()


NEXT_STEP = {
    "TIER_ESCALATION_LATE": "Open the shipment, confirm the revised date with the carrier and "
    "review the recommended actions; inform the consignee.",
    "TIER_ESCALATION_AT_RISK": "Watch the next milestone; no customer communication yet.",
    "PROMISE_MOVED": "Send the customer the new promise date.",
    "P_LATE_JUMP": "Check what changed in the narrative and the recommended actions.",
    "SILENT_SHIPMENT": "Ask the carrier for a status update: the ETA may rest on stale data.",
    "MISSED_CONNECTION_LIKELY": "Check the next sailing from the hub; consider priority loading.",
}


def _aid(sid: str, rule: str, t: float) -> str:
    return hashlib.sha1(f"{sid}|{rule}|{t:.3f}".encode()).hexdigest()[:12]


def evaluate_alerts(
    prev: PredState | None, cur: PredState, open_rules: set[str]
) -> list[AlertEvent]:
    """Rules fire on transitions; one open alert per (shipment, rule) except promise moves."""
    out: list[AlertEvent] = []

    def fire(rule: str, sev: str, msg: str, dedupe: bool = True) -> None:
        if dedupe and rule in open_rules:
            return
        out.append(
            AlertEvent(
                _aid(cur.shipment_id, rule, cur.as_of),
                cur.shipment_id,
                rule,
                sev,
                cur.as_of,
                f"{msg} {cur.narrative}".strip(),
                reason_code=rule,
                evidence_ts=cur.as_of,
                previous_risk=prev.tier if prev else None,
                new_risk=cur.tier,
                previous_p_late=prev.p_late if prev else None,
                new_p_late=cur.p_late,
                recommended_next_step=NEXT_STEP.get(rule, ""),
                data_quality_flags=cur.data_quality_flags,
            )
        )

    prev_rank = TIER_RANK[prev.tier] if prev else 0
    if TIER_RANK[cur.tier] > prev_rank:
        rule = "TIER_ESCALATION_LATE" if cur.tier == "LATE" else "TIER_ESCALATION_AT_RISK"
        fire(
            rule,
            "critical" if cur.tier == "LATE" else "warn",
            f"Risk tier escalated to {cur.tier}.",
        )
    if (
        prev
        and prev.promise_h is not None
        and cur.promise_h is not None
        and cur.promise_h != prev.promise_h
    ):
        fire(
            "PROMISE_MOVED",
            "warn",
            f"Promise date moved by {(cur.promise_h - prev.promise_h) / 24:+.0f} day(s).",
            dedupe=False,
        )
    if prev and cur.p_late - prev.p_late >= 0.20:
        fire(
            "P_LATE_JUMP",
            "warn",
            f"Probability of lateness jumped {prev.p_late:.0%} → {cur.p_late:.0%}.",
        )
    if (
        cur.hours_since_last_event == cur.hours_since_last_event
        and cur.expected_gap_h > 0
        and cur.hours_since_last_event > max(24.0, 1.5 * cur.expected_gap_h)
    ):
        fire(
            "SILENT_SHIPMENT",
            "warn",
            f"No milestone for {cur.hours_since_last_event:.0f} h "
            f"(stage normally takes {cur.expected_gap_h:.0f} h).",
        )
    if cur.checkpoint <= 3 and cur.p_miss > 0.6:
        fire(
            "MISSED_CONNECTION_LIKELY",
            "critical",
            f"Transshipment connection at risk ({cur.p_miss:.0%}).",
        )
    return out
