"""Guardrails that must hold for every prediction."""

from dataclasses import replace
from pathlib import Path

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cascade.decision.cost import CostModel
from cascade.decision.engine import Engine, identity_errors
from cascade.features.priors import apply_priors
from cascade.features.registry import FEATURE_NAMES
from cascade.models.artifacts import Bundle


def _test_rows(trained, rows, splits):
    return apply_priors(rows[rows.shipment_id.isin(splits.test_ids)], trained.model.priors)


def test_quantiles_ordered_and_eta_not_in_past(trained, rows, splits):
    te = _test_rows(trained, rows, splits)
    pr = trained.model.predict(
        te[list(FEATURE_NAMES)].to_numpy(float),
        te.as_of.to_numpy(float),
        te.planned_delivered.to_numpy(float),
        (te.floor_plan_remaining_h.to_numpy(float), te.floor_elapsed_h.to_numpy(float)),
    )
    assert np.all(pr.delay_p10 <= pr.delay_p50 + 1e-9)
    assert np.all(pr.delay_p50 <= pr.delay_p90 + 1e-9)
    eta = te.planned_delivered.to_numpy(float) + pr.delay_p10
    # in transit, the ETA is never in the past. (With reporting latency, a late GATE_OUT report
    # can arrive after delivery is confirmed: that checkpoint is delivered, ETA = actual.)
    live = te.checkpoint.to_numpy() < 9
    assert np.all(eta[live] >= te.as_of.to_numpy(float)[live] - 1e-6)
    assert np.all((pr.p_late >= 0) & (pr.p_late <= 1))


def test_stage_forecast_reconciles_to_p50(trained, rows, splits):
    te = _test_rows(trained, rows, splits)
    pr = trained.model.predict(
        te[list(FEATURE_NAMES)].to_numpy(float),
        te.as_of.to_numpy(float),
        te.planned_delivered.to_numpy(float),
        (te.floor_plan_remaining_h.to_numpy(float), te.floor_elapsed_h.to_numpy(float)),
    )
    total = sum(pr.stage_forecast.values())
    cp = te.checkpoint.to_numpy()
    mask = cp < 9
    assert np.allclose(total[mask], pr.remaining_p50[mask], atol=1e-6)


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(data=st.data())
def test_p50_identities_hold(engine, world, data):
    """Realised + rulebook + learned = raw P50; raw + explicit adjustments = P50; API ETA agrees."""
    sid = data.draw(st.sampled_from(sorted(world.views)))
    cp = data.draw(st.sampled_from(world.checkpoints(sid)))
    r = engine.predict(world.views[sid], cp["as_of"], explain=True, with_promise=False)
    err = identity_errors(r)
    assert max(err.values()) <= 0.1, err
    assert r.explanation.mode == engine.model.explanation_mode
    # no row is a balancing remainder any more
    assert {w.kind for w in r.explanation.waterfall} <= {
        "realized",
        "rulebook",
        "learned",
        "ordering",
        "floor",
        "delivered",
        "total",
    }
    # narratives only quote numbers that exist in the explanation
    assert r.explanation.narratives["customer"]
    for banned in ("proj_inc", "rho_", "Carrier", "_h"):
        assert banned not in r.explanation.narratives["customer"]


def test_identities_detect_a_broken_contribution(engine, world, monkeypatch):
    """The identity check must be able to fail (unlike a remainder-based 'guardrail' row)."""
    sid = sorted(world.views)[0]
    cp = world.checkpoints(sid)[1]
    real = engine.model.rulebook_contributions

    def broken(X):
        c = real(X)
        c[:, 0] += 5.0  # a contribution that does not reach the prediction
        return c

    monkeypatch.setattr(engine.model, "rulebook_contributions", broken)
    r = engine.predict(world.views[sid], cp["as_of"], explain=True, with_promise=False)
    assert identity_errors(r)["a"] > 4.9


def _engine_with_shrink(engine, lam):
    m = replace(engine.model, shrink=lam)
    return Engine(Bundle(m, {}, Path(".")), engine.ext, CostModel(), engine.world)


def test_rulebook_mode_shows_no_learned_items(engine, world):
    eng = _engine_with_shrink(engine, 0.0)
    for sid in sorted(world.views)[:15]:
        for cp in world.checkpoints(sid)[:4]:
            r = eng.predict(world.views[sid], cp["as_of"], explain=True, with_promise=False)
            assert r.explanation.mode == "rulebook"
            assert not [w for w in r.explanation.waterfall if w.kind == "learned"]
            assert "λ = 0" in r.explanation.narratives["analyst"]


def test_learned_items_scale_with_lambda(engine, trained, rows, splits):
    X = _test_rows(trained, rows, splits).head(40)[list(FEATURE_NAMES)].to_numpy(float)
    half = replace(trained.model, shrink=0.5).learned_contributions(X)
    full = replace(trained.model, shrink=1.0).learned_contributions(X)
    assert np.abs(full).sum() > 0
    assert np.allclose(half, 0.5 * full)
    eng = _engine_with_shrink(engine, 0.5)
    sid = sorted(eng.world.views)[0]
    r = eng.predict(eng.world.views[sid], eng.world.checkpoints(sid)[2]["as_of"], explain=True)
    assert r.explanation.mode == "rulebook+learned"
    assert max(identity_errors(r).values()) <= 0.1


def test_eta_floor_holds_on_final_quantiles(trained, rows, splits):
    te = _test_rows(trained, rows, splits)
    parts = (te.floor_plan_remaining_h.to_numpy(float), te.floor_elapsed_h.to_numpy(float))
    pr = trained.model.predict(
        te[list(FEATURE_NAMES)].to_numpy(float),
        te.as_of.to_numpy(float),
        te.planned_delivered.to_numpy(float),
        parts,
    )
    live = te.checkpoint.to_numpy() < 9
    floor = te.as_of.to_numpy(float) - te.planned_delivered.to_numpy(float)
    floor = floor + trained.model.min_remaining_h(*parts)
    assert np.all(pr.delay_p10[live] >= floor[live] - 1e-6)
    no_floor = replace(trained.model, eta_floor_frac=0.0).predict(
        te[list(FEATURE_NAMES)].to_numpy(float),
        te.as_of.to_numpy(float),
        te.planned_delivered.to_numpy(float),
        parts,
    )
    assert np.all(no_floor.delay_p50 <= pr.delay_p50 + 1e-9)  # the floor only ever raises


def test_late_classifier_is_monotone_where_declared(trained, rows, splits):
    """Monotonicity audit for the constrained classifier (raw score, before isotonic)."""
    X = _test_rows(trained, rows, splits).head(30)[list(FEATURE_NAMES)].to_numpy(float)
    clf = trained.model.boosters["clf"]
    for name in ("overdue_h", "congestion_x_lateness", "p_miss_connection_prior"):
        j = FEATURE_NAMES.index(name)
        grid = np.linspace(np.nanmin(X[:, j]), np.nanmax(X[:, j]) + 1.0, 12)
        for row in X:
            Z = np.repeat(row[None, :], len(grid), axis=0)
            Z[:, j] = grid
            s = clf.predict(Z)
            assert np.all(np.diff(s) >= -1e-9), name


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
    assert r.p50_parts is None  # no model decomposition on the fallback path
    assert r.planned_delivered + r.delay_p10 >= r.as_of - 1e-6  # ETA never in the past
