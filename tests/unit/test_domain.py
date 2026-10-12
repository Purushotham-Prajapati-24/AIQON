from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cascade.domain.delay import (
    EPOCH,
    eta_hours,
    risk_tier,
    stage_increments,
    to_datetime,
    to_hours,
    total_delay,
)
from cascade.domain.network import (
    PORTS,
    customs_release,
    local_parts,
    next_open_slot,
    next_rail_departure,
    queue_wait_h,
    receiving_slot,
)
from cascade.domain.stages import EventType, event_sequence

E = EventType


def _hours(y, m, d, hh=0, mm=0):
    return to_hours(datetime(y, m, d, hh, mm, tzinfo=UTC))


@given(
    has_ts=st.booleans(),
    planned_gaps=st.lists(st.floats(1, 500), min_size=9, max_size=9),
    actual_gaps=st.lists(st.floats(0.5, 700), min_size=9, max_size=9),
)
def test_increments_sum_to_total_delay(has_ts, planned_gaps, actual_gaps):
    seq = event_sequence(has_ts)
    p, a, tp, ta = {}, {}, 0.0, 0.0
    for e, gp, ga in zip(seq, planned_gaps, actual_gaps, strict=False):
        tp += gp
        ta += ga
        p[e], a[e] = tp, ta
    inc = stage_increments(p, a, has_ts)
    assert sum(inc.values()) == pytest.approx(total_delay(p, a), abs=1e-6)
    assert len(inc) == len(seq)


def test_eta_identity_and_tiers():
    assert eta_hours(100.0, 5.0, 7.0) == 112.0
    assert risk_tier(30) == "LATE" and risk_tier(10) == "AT_RISK" and risk_tier(2) == "ON_TRACK"


def test_time_roundtrip_and_naive_rejected():
    assert to_datetime(to_hours(EPOCH)) == EPOCH
    with pytest.raises(ValueError):
        to_hours(datetime(2025, 1, 1))


def test_customs_weekend_shift_friday_evening():
    deham = PORTS["DEHAM"]  # UTC+1, no weekend customs
    fri_19_local = _hours(2025, 3, 7, 18)  # 19:00 local
    release = customs_release(fri_19_local, deham)
    day, wd, hour = local_parts(release, deham.tz)
    assert wd == 0 and hour == pytest.approx(8.0)  # Monday 08:00 local
    assert release - fri_19_local == pytest.approx(61.0)


def test_customs_holiday_and_weekend_port():
    deham = PORTS["DEHAM"]
    before_easter = _hours(2025, 4, 17, 20)  # Thu evening before Good Friday holiday
    release = customs_release(before_easter, deham)
    assert local_parts(release, deham.tz)[1] == 1  # Tuesday (Fri + Mon are holidays)
    rtm = PORTS["NLRTM"]  # weekend customs available
    sat_noon = _hours(2025, 3, 8, 11)
    assert customs_release(sat_noon, rtm) == pytest.approx(sat_noon)


def test_receiving_window_and_rail():
    p = PORTS["BEANR"]
    sun = _hours(2025, 3, 9, 12)
    assert local_parts(receiving_slot(sun, p), p.tz)[1] == 0  # Monday
    t = _hours(2025, 3, 10, 19)  # 20:00 local, cut-off 18:00 for the 22:00 train
    dep = next_rail_departure(t, p)
    assert local_parts(dep, p.tz)[2] == pytest.approx(22.0)
    assert dep - t > 24  # next day's train


def test_next_open_slot_inside_window_is_identity():
    t = _hours(2025, 3, 11, 10)
    assert next_open_slot(t, 0, 8, 18, frozenset(range(5))) == t


def test_queue_wait_is_convex():
    w = [queue_wait_h(r, 4.0) for r in (0.6, 0.7, 0.8, 0.9)]
    assert all(b > a for a, b in zip(w, w[1:], strict=False))
    assert (w[3] - w[2]) > (w[1] - w[0])
