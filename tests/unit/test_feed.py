"""Message feeds and schedule versions: duplicates, corrections, disorder and re-plans."""

from dataclasses import replace

import numpy as np
import pandas as pd

from cascade.domain.feed import collapse_messages, plan_at
from cascade.domain.stages import EventType
from cascade.features.dataset import views_from_frames
from cascade.features.snapshot import build_snapshot

E = EventType


def _vec(snap):
    return np.array([snap.features[n] for n in snap.features], dtype=float)


def test_collapse_is_idempotent_and_latest_version_wins():
    log = pd.DataFrame(
        [
            ("S1", "ARRIVE_TS", 100.0, 102.0),  # first (wrong) message
            ("S1", "ARRIVE_TS", 100.0, 103.0),  # duplicate
            ("S1", "ARRIVE_TS", 95.0, 130.0),  # correction, arrives later
            ("S1", "DEPART_TS", 140.0, 141.0),
        ],
        columns=["shipment_id", "event", "stated_h", "recorded_at"],
    )
    a = collapse_messages(log)
    noisy = pd.concat([log, log.iloc[[0, 3]]]).sample(frac=1.0, random_state=3)  # dupes + disorder
    b = collapse_messages(noisy)
    cols = [
        "shipment_id",
        "event",
        "first_stated_h",
        "first_recorded_at",
        "stated_h",
        "recorded_at",
    ]
    assert a[cols].equals(b[cols])
    row = a[a.event == "ARRIVE_TS"].iloc[0]
    assert row.first_stated_h == 100.0 and row.first_recorded_at == 102.0
    assert row.stated_h == 95.0 and row.recorded_at == 130.0 and row.corrected


def test_simulated_feed_has_duplicates_and_corrections(sim):
    ev = sim.events[sim.events.reported]
    assert (ev.corrected_at.notna()).any() and (ev.n_messages > 1).any()
    assert (
        ev.available_h >= ev.actual_h - 1e-9
    ).all()  # the first message never precedes the event
    fixed = ev[ev.corrected_at.notna()]
    assert (fixed.corrected_at > fixed.available_h).all()  # a correction always comes later


def _corrected_case(sim):
    views = views_from_frames(sim.shipments, sim.events, sim.revisions)
    for v in views.values():
        for e, at in v.corrected_at.items():
            if abs(v.initial[e] - v.reported[e]) > 1.0:
                return v, e, (v.known_at(e) + at) / 2
    raise AssertionError("no corrected milestones simulated")


def test_correction_is_invisible_until_it_arrives(sim):
    v, e, t = _corrected_case(sim)
    assert v.known_by(t)[e] == v.initial[e]  # the wrong first value is what was known at t
    base = _vec(build_snapshot(v, t, sim.external))
    rep = dict(v.reported)
    rep[e] += 3.0  # change the (future) corrected value: nothing at t may move
    assert np.array_equal(
        base, _vec(build_snapshot(replace(v, reported=rep), t, sim.external)), equal_nan=True
    )
    later = v.corrected_at[e] + 0.1
    assert v.known_by(later)[e] == v.reported[e]  # once the correction arrived, it wins


def test_future_schedule_revisions_are_invisible(sim):
    views = views_from_frames(sim.shipments, sim.events, sim.revisions)
    v = next(v for v in views.values() if len(v.revisions) >= 2)
    t = (v.revisions[0][0] + v.revisions[1][0]) / 2
    plan, n = v.plan_at(t)
    assert n == 1
    shifted = tuple(
        (eff, {k: h + 500 for k, h in upd.items()}) if eff > t else (eff, upd)
        for eff, upd in v.revisions
    )
    plan2, _ = replace(v, revisions=shifted).plan_at(t)
    assert plan == plan2
    assert plan_at(v.planned, (), t) == (v.planned, 0)  # no revisions: the original commitment


def test_lateness_is_measured_against_the_original_commitment(sim, rows):
    total = sim.shipments.set_index("shipment_id").total_delay_h
    orig = sim.shipments.set_index("shipment_id").planned_DELIVERED
    actual = sim.events[sim.events.event == "DELIVERED"].set_index("shipment_id").actual_h
    assert np.allclose((actual - orig).reindex(total.index), total)
    assert np.allclose(rows.y_total.to_numpy(), rows.shipment_id.map(total).to_numpy())
