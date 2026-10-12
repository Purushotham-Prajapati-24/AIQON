"""Leakage contract: a snapshot at as_of must not change when anything *after* as_of changes."""

from dataclasses import replace

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cascade.domain.stages import EVENT_INDEX, EventType
from cascade.features.dataset import views_from_frames
from cascade.features.snapshot import build_snapshot


@settings(
    max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(data=st.data())
def test_future_milestones_never_leak(sim, data):
    views = views_from_frames(sim.shipments, sim.events)
    sid = data.draw(st.sampled_from(sorted(views)))
    v = views[sid]
    times = sorted(v.reported.values())
    if len(times) < 3:
        return
    k = data.draw(st.integers(1, len(times) - 2))
    as_of = times[k] + 0.5
    base = build_snapshot(v, as_of, sim.external)
    # perturb every milestone reported after as_of (later, earlier-but-still-future, or removed)
    future = [e for e, t in v.reported.items() if t > as_of]
    shift = data.draw(st.floats(0.1, 300.0))
    drop = data.draw(st.booleans())
    rep = dict(v.reported)
    for e in future:
        if drop and e != EventType.DELIVERED:
            rep.pop(e)
        else:
            rep[e] = rep[e] + shift
    pert = build_snapshot(replace(v, reported=rep), as_of, sim.external)
    a = np.array([base.features[n] for n in base.features], dtype=float)
    b = np.array([pert.features[n] for n in pert.features], dtype=float)
    assert np.array_equal(a, b, equal_nan=True)


def test_rows_targets_are_consistent(rows):
    inc = rows[[c for c in rows.columns if c.startswith("y_inc_")]].sum(axis=1)
    # the current delay is what was *known*: stated times carry up to 0.75 h jitter, and a first
    # message can be up to 8 h wrong until its correction arrives (simulated feed corrections)
    gap = (inc - rows.y_remaining).abs()
    assert gap.max() < 0.75 * 2 + 8.0 + 0.1
    assert (gap < 1.6).mean() > 0.95  # only snapshots with a pending correction exceed jitter
    assert (rows.y_total - rows.current_delay_h - rows.y_remaining).abs().max() < 1e-9


def test_checkpoint_is_last_observed_event(sim):
    views = views_from_frames(sim.shipments, sim.events)
    v = next(iter(views.values()))
    for e in v.reported:
        snap = build_snapshot(v, v.known_at(e) + 0.01, sim.external)  # once the report arrived
        assert snap.checkpoint >= EVENT_INDEX[e] + 1


def _feature_vector(snap):
    return np.array([snap.features[n] for n in snap.features], dtype=float)


def _late_report_case(sim):
    """A shipment with a milestone that happened before t but whose report arrives after t."""
    views = views_from_frames(sim.shipments, sim.events)
    for v in views.values():
        for e in sorted(v.reported, key=lambda x: EVENT_INDEX[x]):
            if e == EventType.DELIVERED:
                continue
            ev_t, arrive = v.reported[e], v.known_at(e)
            if arrive - ev_t > 1.0:  # a report that lagged the event by more than an hour
                return v, e, (ev_t + arrive) / 2
    raise AssertionError("simulator produced no lagged reports")


def test_late_report_is_invisible_until_it_arrives(sim):
    """Event at t-x, report at t+y: the row at t must not change however the report is timed."""
    v, e, t = _late_report_case(sim)
    base = _feature_vector(build_snapshot(v, t, sim.external))
    for later in (0.1, 5.0, 500.0):  # the report arrives later still: nothing at t may change
        av = dict(v.available)
        av[e] = t + later
        pert = build_snapshot(replace(v, available=av), t, sim.external)
        assert np.array_equal(base, _feature_vector(pert), equal_nan=True)


def test_report_arriving_before_t_is_used(sim):
    """Moving the same report's arrival to before t makes it visible, so the row may change."""
    v, e, t = _late_report_case(sim)
    base = build_snapshot(v, t, sim.external)
    av = dict(v.available)
    av[e] = v.reported[e]  # report arrives the moment it happened
    seen = build_snapshot(replace(v, available=av), t, sim.external)
    assert seen.checkpoint > base.checkpoint
    assert not np.array_equal(_feature_vector(base), _feature_vector(seen), equal_nan=True)


def test_reports_never_precede_their_event(sim):
    rep = sim.events[sim.events.reported]
    assert (rep.available_h >= rep.actual_h - 1e-9).all()
    assert (rep.available_h >= rep.reported_h - 1e-9).all()
