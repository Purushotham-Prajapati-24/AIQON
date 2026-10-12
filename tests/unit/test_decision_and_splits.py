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
