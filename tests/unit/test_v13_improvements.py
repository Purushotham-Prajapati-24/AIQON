"""v1.3: silence-is-a-reporting-gap cleaning, combined λ selection and the P(late) stack."""

from dataclasses import replace

import numpy as np

from cascade.domain.network import NETWORK
from cascade.domain.stages import EventType
from cascade.features.priors import apply_priors
from cascade.features.registry import FEATURE_NAMES
from cascade.features.snapshot import HUB_MAX_EXTRA_HOLD_H, MAX_PLAUSIBLE_HOLD_H
from cascade.models.artifacts import latest_bundle_dir, load_bundle
from cascade.models.predictor import empirical_exceedance, residual_pools, stack_probability
from cascade.models.train import combine_shrink

E = EventType


def test_hub_silence_beyond_one_headway_is_a_reporting_gap(rows):
    # checkpoint 3 = last seen arriving at the hub. A missed connection waits one headway; any
    # longer silence is a missing DEPART_TS report, never weeks of phantom hub delay.
    at_hub = rows[rows.checkpoint == 3]
    assert len(at_hub)
    headway = at_hub.lane_id.map(lambda lane: NETWORK.lanes[lane].headway_h)
    assert (at_hub.overdue_h <= headway + HUB_MAX_EXTRA_HOLD_H + 1e-9).all()
    assert (at_hub.proj_inc_hub_h <= headway + at_hub.overdue_h + 24.0).all()


def test_overdue_never_exceeds_the_plausible_hold(rows):
    # checkpoint 2 on a hub lane: the next milestone is the hub arrival
    sea = rows[(rows.checkpoint == 2) & (rows.has_transshipment == 1)]
    assert (sea.overdue_h <= MAX_PLAUSIBLE_HOLD_H[E.ARRIVE_TS] + 1e-9).all()


def test_empirical_exceedance_counts_residuals_above_need():
    rng = np.random.default_rng(0)
    resid = rng.normal(0, 20, 2000)
    cp = rng.integers(0, 4, 2000)  # ~500 per checkpoint: all above MIN_POOL
    pools = residual_pools(resid, cp)
    need = rng.normal(0, 20, 50)
    cps = rng.integers(0, 4, 50)
    got = empirical_exceedance(pools, cps, need)
    r = np.round(resid, 2)
    want = np.array([(r[cp == c] > n).mean() for c, n in zip(cps, need, strict=True)])
    assert np.allclose(got, np.clip(want, 1e-4, 1 - 1e-4))
    # a checkpoint with too few residuals falls back to the pooled distribution
    sparse = empirical_exceedance(pools, np.array([7]), np.array([0.0]))
    assert np.isclose(sparse[0], (r > 0).mean())


def test_combined_lambda_needs_both_validation_views():
    flat = {0.0: 10.0, 0.5: 10.0, 1.0: 10.0}
    better = {0.0: 10.0, 0.5: 9.0, 1.0: 9.5}
    worse = {0.0: 10.0, 0.5: 11.5, 1.0: 13.0}
    assert combine_shrink(better, better) == 0.5
    assert combine_shrink(better, worse) == 0.0  # temporal gain, OOF loss: stay on the rulebook
    assert combine_shrink(flat, flat) == 0.0  # ties go to the smaller (safer) λ
    marginal = {0.0: 10.0, 0.5: 9.95, 1.0: 9.97}  # a 0.5% "gain" is noise: keep the rulebook
    assert combine_shrink(marginal, marginal) == 0.0


def test_late_stack_is_trained_and_survives_the_bundle(trained, rows, splits, bundle_dir):
    m = trained.model
    assert len(m.late_stack) == 3 and m.resid_pools
    assert m.late_stack[1] > 0  # more empirical evidence of lateness -> higher P(late)
    loaded = load_bundle(latest_bundle_dir(bundle_dir)).model
    assert loaded.late_stack == m.late_stack and loaded.resid_pools == m.resid_pools
    te = apply_priors(rows[rows.shipment_id.isin(splits.test_ids)], m.priors)
    X = te[list(FEATURE_NAMES)].to_numpy(float)
    args = (te.as_of.to_numpy(float), te.planned_delivered.to_numpy(float))
    assert np.allclose(m.predict(X, *args).p_late, loaded.predict(X, *args).p_late)


def test_old_bundle_without_stack_falls_back_to_the_blend(trained, rows, splits):
    m = trained.model
    old = replace(m, late_stack=[], resid_pools={})
    te = apply_priors(rows[rows.shipment_id.isin(splits.test_ids)], m.priors)
    X = te[list(FEATURE_NAMES)].to_numpy(float)
    args = (te.as_of.to_numpy(float), te.planned_delivered.to_numpy(float))
    p_old, p_new = old.predict(X, *args).p_late, m.predict(X, *args).p_late
    assert np.all((p_old >= 0) & (p_old <= 1)) and not np.allclose(p_old, p_new)


def test_stack_probability_is_monotone_in_both_inputs():
    coef = [-0.3, 0.5, 0.2]
    p = np.linspace(0.01, 0.99, 25)
    a = stack_probability(coef, p, np.full_like(p, 0.4))
    b = stack_probability(coef, np.full_like(p, 0.4), p)
    assert np.all(np.diff(a) > 0) and np.all(np.diff(b) > 0)


def test_direct_band_does_not_move_with_lambda(trained, rows, splits):
    # v1.3: λ shrinks only the point forecast; the P10/P90 band comes from the learned quantiles
    m = trained.model
    assert m.band_mode == "direct"
    te = apply_priors(rows[rows.shipment_id.isin(splits.test_ids)], m.priors)
    X = te[list(FEATURE_NAMES)].to_numpy(float)
    lo, hi = replace(m, shrink=0.0).raw_quantiles(X), replace(m, shrink=1.0).raw_quantiles(X)
    assert np.allclose(lo["q10"], hi["q10"]) and np.allclose(lo["q90"], hi["q90"])
    assert not np.allclose(lo["q50"], hi["q50"])
    shifted = replace(m, band_mode="shifted", shrink=0.0).raw_quantiles(X)
    assert np.allclose(shifted["q90"] - shifted["q50"], lo["q90"] - hi["q50"])
