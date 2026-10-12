import numpy as np
import pytest

from cascade.data.validation import DataValidationError, validate_all, validate_ledger
from cascade.domain.network import NETWORK
from cascade.domain.stages import EventType
from cascade.sim.generator import SimConfig, generate, resimulate
from cascade.sim.mechanics import Draws, Intervention, ShipmentSpec, plan_shipment, propagate

E = EventType


def _draws(**kw) -> Draws:
    base = {k: 0.0 for k in Draws.__dataclass_fields__}
    base.update(insp_u=0.99, insp_extra=36.0)
    base.update(kw)
    return Draws(**base)


def _spec(lane_id: str, slack: float = 12.0, docs=True, risk=0) -> ShipmentSpec:
    lane = NETWORK.lanes[lane_id]
    p_dep = 60 * 24.0 + 16.0 - NETWORK.ports[lane.origin].tz
    return ShipmentSpec(
        "T1",
        "V1",
        lane_id,
        "C1",
        risk,
        docs,
        lane.inland_mode,
        50000.0,
        plan_shipment(lane, NETWORK, p_dep, 72.0, lane.inland_mode, slack),
    )


def test_generation_is_valid_deterministic_and_realistic(sim):
    validate_all(sim.shipments, sim.events, sim.ledger)
    again = generate(SimConfig(seed=3, n_shipments=120))
    assert np.allclose(sim.shipments.total_delay_h, again.shipments.total_delay_h)
    assert 0.2 <= sim.shipments.is_late.mean() <= 0.6


def test_ledger_is_exact(sim):
    sums = sim.ledger.groupby("shipment_id").hours.sum().reindex(sim.shipments.shipment_id)
    assert np.abs(sums.values - sim.shipments.total_delay_h.values).max() < 1e-6


def test_ledger_validation_catches_corruption(sim):
    bad = sim.ledger.copy()
    bad.loc[bad.index[0], "hours"] += 5
    with pytest.raises(DataValidationError):
        validate_ledger(bad, sim.shipments)


def test_structural_absence_is_not_missingness(sim):
    direct = sim.shipments[~sim.shipments.has_transshipment].shipment_id
    ev = sim.events[sim.events.shipment_id.isin(direct)]
    assert not ev.event.isin(["ARRIVE_TS", "DEPART_TS"]).any()
    assert sim.events[sim.events.event == "DELIVERED"].reported.all()


def test_missed_connection_waits_one_headway():
    ext = generate(SimConfig(seed=1, n_shipments=5)).external
    spec = _spec("CNSHA-SGSIN-NLRTM", slack=30.0)
    on_time = propagate(spec, _draws(), ext, NETWORK)
    late = propagate(spec, _draws(), ext, NETWORK, Intervention(inject={E.DEPART_ORIGIN: 90.0}))
    assert on_time.missed_connections == 0
    assert late.missed_connections >= 1
    assert any(c.startswith("missed_connection") for _, c, _ in late.ledger)
    gain = late.actual[E.DEPART_TS] - on_time.actual[E.DEPART_TS]
    assert gain == pytest.approx(84.0, abs=30.0)  # bi-weekly hub service (+/- vessel delay)


def test_slack_absorbs_small_upstream_delay():
    ext = generate(SimConfig(seed=1, n_shipments=5)).external
    spec = _spec("CNSHA-SGSIN-NLRTM", slack=50.0)
    a = propagate(spec, _draws(), ext, NETWORK)
    b = propagate(spec, _draws(), ext, NETWORK, Intervention(inject={E.ARRIVE_TS: 10.0}))
    assert b.actual[E.DELIVERED] == pytest.approx(a.actual[E.DELIVERED])  # buffer absorbs


def test_inspection_depends_on_documents():
    ext = generate(SimConfig(seed=1, n_shipments=5)).external
    spec = _spec("KRPUS-USLAX", docs=False, risk=2)
    d = _draws(insp_u=0.4)
    bad_docs = propagate(spec, d, ext, NETWORK)
    good_docs = propagate(spec, d, ext, NETWORK, Intervention(docs_complete=True))
    assert any(c == "customs_inspection" for _, c, _ in bad_docs.ledger)
    assert not any(c == "customs_inspection" for _, c, _ in good_docs.ledger)
    # office hours / receiving windows may absorb the saving downstream, but clearance is never later
    assert good_docs.actual[E.CUSTOMS_CLEARED] <= bad_docs.actual[E.CUSTOMS_CLEARED]


def test_resimulate_without_intervention_reproduces_truth(sim):
    sid = sim.shipments.shipment_id.iloc[0]
    out = resimulate(sim, sid)
    truth = sim.shipments.set_index("shipment_id").loc[sid, "total_delay_h"]
    planned = sim.shipments.set_index("shipment_id").loc[sid, "planned_DELIVERED"]
    assert out.actual[E.DELIVERED] - planned == pytest.approx(truth)
