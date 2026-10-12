"""Milestone message feeds and schedule versions: what a monitoring system actually receives.

A carrier/terminal feed is a *log of messages*, not a table of truths:
* a milestone can be reported more than once (duplicates),
* a first message can carry a wrong time that a later message corrects,
* messages arrive out of order.

``collapse_messages`` turns such a log into one row per (shipment, event), keeping the first
version (what was known first, and when) and the latest version by ``recorded_at``
(corrections win). It is idempotent: duplicated or reordered logs collapse to the same rows.

Schedule revisions are versioned the same way: a revision becomes known at ``effective_at``,
and ``plan_at`` returns the plan version in force at a given time. Lateness is always measured
against the *original* commitment; the current plan is reported alongside, never instead.
"""

from __future__ import annotations

import pandas as pd

from cascade.domain.stages import EventType

MESSAGE_COLUMNS = ("shipment_id", "event", "stated_h", "recorded_at")


def collapse_messages(messages: pd.DataFrame) -> pd.DataFrame:
    """One row per (shipment_id, event) from a message log (duplicates / corrections / disorder).

    Returns columns: shipment_id, event, first_stated_h, first_recorded_at, stated_h,
    recorded_at, n_messages, corrected (latest stated time differs from the first one).
    """
    if messages.empty:
        return pd.DataFrame(
            columns=[
                "shipment_id",
                "event",
                "first_stated_h",
                "first_recorded_at",
                "stated_h",
                "recorded_at",
                "n_messages",
                "corrected",
            ]
        )
    m = messages.loc[:, list(MESSAGE_COLUMNS)].sort_values(
        ["shipment_id", "event", "recorded_at", "stated_h"], kind="stable"
    )
    g = m.groupby(["shipment_id", "event"], sort=True)
    out = pd.DataFrame(
        {
            "first_stated_h": g.stated_h.first(),
            "first_recorded_at": g.recorded_at.first(),
            "stated_h": g.stated_h.last(),
            "recorded_at": g.recorded_at.last(),
            "n_messages": g.size(),
        }
    ).reset_index()
    out["corrected"] = (out.stated_h - out.first_stated_h).abs() > 1e-9
    return out


def plan_at(
    original: dict[EventType, float],
    revisions: tuple[tuple[float, dict[EventType, float]], ...],
    t: float,
) -> tuple[dict[EventType, float], int]:
    """The schedule version in force at time t, and how many revisions were known by then.

    ``revisions`` = ((effective_at, {event: planned_h, ...}), ...), each revision giving the
    carrier's new plan for the events it re-times. Later revisions override earlier ones.
    """
    plan = dict(original)
    known = 0
    for eff, upd in sorted(revisions, key=lambda r: r[0]):
        if eff > t:
            break
        plan.update(upd)
        known += 1
    return plan, known
