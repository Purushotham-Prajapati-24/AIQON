import pytest
from hypothesis import given
from hypothesis import strategies as st

from cascade.decision.alerts import PredState, evaluate_alerts
from cascade.decision.cost import CostModel
from cascade.decision.promise import update_promise
from cascade.features.priors import fit_priors
from cascade.models.train import priors_oof


def test_cost_free_time_boundary_and_tiers():
    cm = CostModel()
    zero = cm.cost("DEHAM", 0.0, dwell_h=4 * 24, inland_extra_h=0, cargo_value_usd=0)
    assert zero["demurrage"] == 0 and zero["total"] == 0
    one = cm.cost("DEHAM", 0.0, dwell_h=5 * 24, inland_extra_h=0, cargo_value_usd=0)
    assert one["demurrage"] == pytest.approx(75)
    nine = cm.cost("DEHAM", 0.0, dwell_h=13 * 24, inland_extra_h=0, cargo_value_usd=0)
    assert nine["demurrage"] == pytest.approx(4 * 75 + 4 * 150 + 1 * 300)
    late = cm.cost("DEHAM", 30.0, dwell_h=0, inland_extra_h=0, cargo_value_usd=0)
    assert late["missed_appointment"] == 350


@given(st.floats(0, 5000), st.floats(0, 300), st.floats(0, 200))
def test_promise_is_stable_under_identical_inputs(p50, spread, width):
    a = update_promise(None, 0.0, p50, p50 + spread, width, "LATE")
    b = update_promise(a, 1.0, p50, p50 + spread, width, "LATE")
    assert b == a


def test_promise_moves_on_strong_evidence_only():
    a = update_promise(None, 0, 1000, 1010, 40, "AT_RISK")
    small = update_promise(a, 1, 1008, 1018, 40, "AT_RISK")
    assert small.promise_h == a.promise_h
    big = update_promise(a, 2, 1100, 1120, 40, "LATE")
    assert big.promise_h > a.promise_h and big.changes == 1


def test_alerts_fire_once_per_rule():
    s1 = PredState("S", 0, 5, 0.2, "ON_TRACK", 100, 0.0, 2, 1.0, 100)
    s2 = PredState("S", 1, 40, 0.8, "LATE", 148, 0.7, 2, 1.0, 100)
    first = evaluate_alerts(s1, s2, set())
    rules = {a.rule for a in first}
    assert {
        "TIER_ESCALATION_LATE",
        "P_LATE_JUMP",
        "MISSED_CONNECTION_LIKELY",
        "PROMISE_MOVED",
    } <= rules
    again = evaluate_alerts(s2, s2, rules)
    assert not again


def test_splits_are_out_of_time_and_voyage_grouped(sim, splits):
    s = sim.shipments.set_index("shipment_id")
    assert (
        s.loc[splits.test_ids].planned_DEPART_ORIGIN.min()
        >= s.loc[splits.train_ids].planned_DEPART_ORIGIN.min()
    )
    train_v, test_v = set(s.loc[splits.train_ids].voyage_id), set(s.loc[splits.test_ids].voyage_id)
    assert not train_v & test_v
    fold_of_voyage = {}
    for sid, k in splits.fold_of.items():
        v = s.loc[sid, "voyage_id"]
        assert fold_of_voyage.setdefault(v, k) == k


def test_priors_are_out_of_fold(sim, rows, splits):
    tr_rows = rows[rows.shipment_id.isin(splits.train_ids)]
    ships = sim.shipments[sim.shipments.shipment_id.isin(splits.train_ids)]
    with_p = priors_oof(tr_rows, ships, sim.ledger, splits.fold_of)
    sid = tr_rows.shipment_id.iloc[0]
    k = splits.fold_of[sid]
    others = ships[ships.shipment_id.map(splits.fold_of) != k]
    table = fit_priors(others, sim.ledger)
    lane = tr_rows.lane_id.iloc[0]
    assert with_p.prior_lane_mean_delay.iloc[0] == pytest.approx(
        table["prior_lane_mean_delay"].get(lane, table["prior_lane_mean_delay"]["__global__"])
    )


def test_advisor_states_validity_deadline_and_ranges(engine, world):
    """Every recommendation carries preconditions, assumptions, before/after and 3 validity flags."""
    from cascade.decision.advisor import SENSITIVITY_SHIFTS_H

    seen = 0
    for sid in sorted(world.views):
        v = world.views[sid]
        for cp in world.checkpoints(sid)[:3]:
            _, recs = engine.advise(v, cp["as_of"])
            for r in recs:
                seen += 1
                assert set(r.validity) == {
                    "mechanically_valid",
                    "operationally_feasible",
                    "economically_justified",
                }
                assert r.validity["economically_justified"] == (r.net_value_usd > 0)
                assert r.validity["operationally_feasible"] == (r.hours_to_deadline >= 0)
                assert r.feasible_reason and r.assumptions and r.deadline_event
                assert (
                    {"p10", "p50", "p90", "p_late"}
                    <= set(r.baseline)
                    <= set(r.scenario)
                    | {
                        "p10",
                        "p50",
                        "p90",
                        "p_late",
                    }
                )
                assert len(r.benefit_range_h) == 2 and r.benefit_range_h[0] <= r.benefit_range_h[1]
                assert r.benefit_range_h[0] - 1e-6 <= r.hours_saved <= r.benefit_range_h[1] + 1e-6
            # feasible actions are always ranked before infeasible ones
            flags = [r.validity["operationally_feasible"] for r in recs]
            assert flags == sorted(flags, reverse=True)
        if seen >= 20:
            break
    assert seen > 0 and len(SENSITIVITY_SHIFTS_H) == 3


def test_advisor_deadline_passes_once_cutoff_milestone_happened():
    from cascade.decision.advisor import Action, hours_to_deadline
    from cascade.domain.stages import EventType as Ev
    from cascade.features.snapshot import Snapshot, WhatIf

    a = Action("x", "x", "x", 1.0, WhatIf(), Ev.ARRIVE_DEST_PORT, 24.0)
    planned = {Ev.ARRIVE_DEST_PORT: 1000.0}
    snap = Snapshot({}, 900.0, 3, None, 10.0, 1200.0, {}, [], None, {Ev.ARRIVE_DEST_PORT: 10.0})
    assert hours_to_deadline(a, snap, planned) == pytest.approx(1000 + 10 - 900 - 24)
    late = Snapshot({}, 990.0, 3, None, 10.0, 1200.0, {}, [], None, {Ev.ARRIVE_DEST_PORT: 10.0})
    assert hours_to_deadline(a, late, planned) < 0  # too late to arrange the 24 h lead time
    done = Snapshot({}, 900.0, 6, None, 10.0, 1200.0, {Ev.ARRIVE_DEST_PORT: 1005.0}, [], None)
    assert hours_to_deadline(a, done, planned) == -float("inf")
