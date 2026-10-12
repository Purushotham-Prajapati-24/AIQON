"""Guardrails that must hold for every prediction."""

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cascade.features.priors import apply_priors
from cascade.features.registry import FEATURE_NAMES


def _test_rows(trained, rows, splits):
    return apply_priors(rows[rows.shipment_id.isin(splits.test_ids)], trained.model.priors)


def test_quantiles_ordered_and_eta_not_in_past(trained, rows, splits):
    te = _test_rows(trained, rows, splits)
    pr = trained.model.predict(
        te[list(FEATURE_NAMES)].to_numpy(float),
        te.as_of.to_numpy(float),
        te.planned_delivered.to_numpy(float),
        te.min_remaining_h.to_numpy(float),
    )
    assert np.all(pr.delay_p10 <= pr.delay_p50 + 1e-9)
    assert np.all(pr.delay_p50 <= pr.delay_p90 + 1e-9)
    eta = te.planned_delivered.to_numpy(float) + pr.delay_p10
    assert np.all(eta >= te.as_of.to_numpy(float) - 1e-6)
    assert np.all((pr.p_late >= 0) & (pr.p_late <= 1))


def test_stage_forecast_reconciles_to_p50(trained, rows, splits):
    te = _test_rows(trained, rows, splits)
    pr = trained.model.predict(
        te[list(FEATURE_NAMES)].to_numpy(float),
        te.as_of.to_numpy(float),
        te.planned_delivered.to_numpy(float),
        te.min_remaining_h.to_numpy(float),
    )
    total = sum(pr.stage_forecast.values())
    cp = te.checkpoint.to_numpy()
    mask = cp < 9
    assert np.allclose(total[mask], pr.remaining_p50[mask], atol=1e-6)


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(data=st.data())
def test_waterfall_is_additive(engine, world, data):
    sid = data.draw(st.sampled_from(sorted(world.views)))
    cps = world.checkpoints(sid)
    cp = data.draw(st.sampled_from(cps))
    r = engine.predict(world.views[sid], cp["as_of"], explain=True, with_promise=False)
    parts = sum(w.hours for w in r.explanation.waterfall if w.kind != "total")
    assert parts == pytest.approx(r.delay_p50, abs=0.1)
    # narratives only quote numbers that exist in the explanation
    assert r.explanation.narratives["customer"]
    for banned in ("proj_inc", "rho_", "Carrier", "_h"):
        assert banned not in r.explanation.narratives["customer"]


def test_contributions_sum_to_raw_p50(trained, rows, splits):
    te = _test_rows(trained, rows, splits).head(50)
    X = te[list(FEATURE_NAMES)].to_numpy(float)
    c = trained.model.contributions(X)
    raw = trained.model.raw_quantiles(X)["q50"]
    assert np.allclose(c.sum(axis=1), raw, atol=1e-6)


def test_fallback_on_model_failure(engine, world, monkeypatch):
    sid = next(iter(world.views))
    v = world.views[sid]

    def boom(*a, **k):
        raise RuntimeError("corrupt booster")

    monkeypatch.setattr(engine.model, "predict", boom)
    r = engine.predict(v, world.checkpoints(sid)[1]["as_of"], explain=True)
    assert r.flags["degraded"] and "propagation_prior" in r.flags["reason"]
    assert r.delay_p10 <= r.delay_p50 <= r.delay_p90
