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
    # reported timestamps carry up to 0.75 h jitter vs the ledger's true timeline
    assert (inc - rows.y_remaining).abs().max() < 1.6
    assert (rows.y_total - rows.current_delay_h - rows.y_remaining).abs().max() < 1e-9


def test_checkpoint_is_last_observed_event(sim):
    views = views_from_frames(sim.shipments, sim.events)
    v = next(iter(views.values()))
    for e, t in v.reported.items():
        snap = build_snapshot(v, t + 0.01, sim.external)
        assert snap.checkpoint >= EVENT_INDEX[e] + 1
