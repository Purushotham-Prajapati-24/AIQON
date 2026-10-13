"""CascadeModel: the trained ensemble used identically in evaluation, replay and serving."""

from __future__ import annotations

from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
from scipy.stats import norm

from cascade.domain.stages import (
    EVENT_INDEX,
    GROUP_OF_STAGE,
    PHYSICAL_GROUPS,
    STAGE_OF_EVENT,
    StageGroup,
    event_sequence,
)
from cascade.features.priors import PriorTable
from cascade.features.registry import FEATURE_NAMES
from cascade.models.baselines import PropagationPrior
from cascade.models.conformal import apply_offsets, group_offset

QUANTILES = {"q10": 0.1, "q50": 0.5, "q80": 0.8, "q90": 0.9}
BAND = ("q10", "q50", "q90")  # the published P10-P50-P90 range
P80_FROM_P50_P90 = 0.8416 / 1.2816  # normal approximation, used only without a q80 model
PHYS_COLS = (
    "proj_inc_origin_h",
    "proj_inc_ocean_h",
    "proj_inc_hub_h",
    "proj_inc_port_h",
    "proj_inc_customs_h",
    "proj_inc_inland_h",
)
PHYS_IDX = [FEATURE_NAMES.index(c) for c in PHYS_COLS]
CHECKPOINT_IDX = FEATURE_NAMES.index("checkpoint")
CURRENT_DELAY_IDX = FEATURE_NAMES.index("current_delay_h")
HAS_TS_IDX = FEATURE_NAMES.index("has_transshipment")


def quantile_implied_exceedance(
    p10: np.ndarray, p50: np.ndarray, p90: np.ndarray, thr: float
) -> np.ndarray:
    """P(D > thr) from a split-normal matched to the P10/P50/P90 delay quantiles."""
    lo = np.maximum((p50 - p10) / 1.2816, 1e-3)
    hi = np.maximum((p90 - p50) / 1.2816, 1e-3)
    z = np.where(thr < p50, (thr - p50) / lo, (thr - p50) / hi)
    return 1.0 - norm.cdf(z)


MIN_POOL = 150  # fewer training residuals at a checkpoint -> use the pooled distribution


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, float), 1e-4, 1.0 - 1e-4)
    return np.log(p / (1.0 - p))


def residual_pools(resid: np.ndarray, checkpoints: np.ndarray) -> dict[str, list[float]]:
    """Sorted training residuals (truth - rulebook) per checkpoint, plus a pooled fallback."""
    resid = np.round(np.asarray(resid, float), 2)
    cp = np.asarray(checkpoints).astype(int)
    pools = {"__global__": np.sort(resid).tolist()}
    for c in np.unique(cp):
        if (cp == c).sum() >= MIN_POOL:
            pools[str(int(c))] = np.sort(resid[cp == c]).tolist()
    return pools


def empirical_exceedance(
    pools: dict[str, list[float]] | dict[str, np.ndarray], checkpoints: np.ndarray, need: np.ndarray
) -> np.ndarray:
    """P(residual > need): the share of same-checkpoint training residuals above `need`."""
    need = np.asarray(need, float)
    cp = np.asarray(checkpoints).astype(int)
    out = np.empty(len(need))
    for c in np.unique(cp):
        m = cp == c
        pool = np.asarray(pools.get(str(int(c)), pools["__global__"]))
        out[m] = 1.0 - np.searchsorted(pool, need[m], side="right") / len(pool)
    return np.clip(out, 1e-4, 1.0 - 1e-4)


def stack_probability(coef: list[float], p_emp: np.ndarray, clf_raw: np.ndarray) -> np.ndarray:
    """Logistic stack: sigmoid(a + b * logit(empirical P(late)) + c * logit(classifier))."""
    z = coef[0] + coef[1] * logit(p_emp) + coef[2] * logit(clf_raw)
    return 1.0 / (1.0 + np.exp(-z))


def assemble_quantiles(
    base: np.ndarray, g: dict[str, np.ndarray], shrink: float, band_mode: str = "shifted"
) -> dict[str, np.ndarray]:
    """Remaining-delay quantiles from the rulebook base and the learned residual quantiles g.

    The P50 is always base + λ·g50. "shifted" (<= v1.2) moves the whole band with the shrunk
    median: base + λ·g50 + (g_k - g50). "direct" (v1.3) keeps the point forecast shrunk but
    takes the band from the learned quantiles themselves, base + g_k: with λ = 0 the shifted
    band subtracts the learned median and is mis-centred.
    """
    center = shrink * g["q50"]
    if band_mode == "direct":
        return {k: base + (center if k == "q50" else v) for k, v in g.items()}
    return {k: base + center + (v - g["q50"]) for k, v in g.items()}


def future_groups(checkpoint: int, has_ts: bool) -> list[StageGroup]:
    """Physical stage groups that still lie ahead at a checkpoint."""
    seq = event_sequence(has_ts)
    groups: list[StageGroup] = []
    for e in seq:
        if EVENT_INDEX[e] >= checkpoint:
            g = GROUP_OF_STAGE[STAGE_OF_EVENT[e]]
            if g not in groups:
                groups.append(g)
    return groups


@dataclass
class PredictionArrays:
    delay_p10: np.ndarray
    delay_p50: np.ndarray
    delay_p90: np.ndarray
    p_late: np.ndarray
    remaining_p50: np.ndarray
    stage_forecast: dict[StageGroup, np.ndarray] = field(default_factory=dict)
    # P50 provenance, computed explicitly (never as a remainder), all in delay hours:
    #   raw_p50 + ordering_adjust + floor_adjust + delivered_adjust == delay_p50
    raw_p50: np.ndarray | None = None  # current delay + rulebook + λ·learned correction
    ordering_adjust: np.ndarray | None = None  # effect of sorting the three quantiles
    floor_adjust: np.ndarray | None = None  # effect of the heuristic ETA floor
    delivered_adjust: np.ndarray | None = None  # delivered: replaced by the realised delay
    delay_p80: np.ndarray | None = None  # calibrated P80 (the customer promise quantile)
    p80_calibrated: bool = False  # False = normal approximation from P50/P90 (no q80 model)


@dataclass
class CascadeModel:
    boosters: dict[str, lgb.Booster]
    offsets: dict[str, float]
    iso_x: list[float]
    iso_y: list[float]
    priors: PriorTable
    fallback: PropagationPrior
    target_mode: str = "remaining"  # or "residual" (over the physics projection)
    late_threshold_h: float = 24.0
    stage_weights: dict[str, float] = field(default_factory=dict)
    shrink: float = 1.0  # trust in the learned correction, chosen on temporal validation
    late_blend: float = 0.5  # weight of the classifier vs the quantile-implied P(late)
    eta_floor_frac: float = 0.5  # heuristic: remaining stages take >= this share of planned time
    offsets80: dict[str, float] = field(default_factory=dict)  # one-sided conformal for P80
    late_alert_p: float = 0.0  # LATE alert needs P(late) >= this (chosen out-of-fold on training)
    drift_ref: dict[str, dict] = field(default_factory=dict)  # training reference for PSI
    # P(late) stack (v1.3): empirical residual distribution around the rulebook + classifier.
    # Empty -> the <= v1.2 blend of the isotonic classifier and the quantile-implied probability.
    resid_pools: dict[str, list[float]] = field(default_factory=dict)
    late_stack: list[float] = field(default_factory=list)
    band_mode: str = (
        "shifted"  # P10/P80/P90: "direct" learned quantiles (v1.3) | "shifted" (<= v1.2)
    )
    version: str = "dev"
    # residual pools as arrays, built once (not an init field: `replace` never copies a stale one)
    _pool_arrays: dict[str, np.ndarray] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def pool_arrays(self) -> dict[str, np.ndarray]:
        if not self._pool_arrays and self.resid_pools:
            self._pool_arrays = {k: np.asarray(v, float) for k, v in self.resid_pools.items()}
        return self._pool_arrays

    # ---- core ---------------------------------------------------------------------------
    def _base(self, X: np.ndarray) -> np.ndarray:
        if self.target_mode == "residual":
            return X[:, PHYS_IDX].sum(axis=1)
        return np.zeros(len(X))

    def raw_quantiles(self, X: np.ndarray) -> dict[str, np.ndarray]:
        """Remaining-delay quantiles before conformal widening and guardrails."""
        base = self._base(X)
        g = {k: self.boosters[k].predict(X, num_threads=1) for k in QUANTILES if k in self.boosters}
        return assemble_quantiles(base, g, self.shrink, self.band_mode)

    def min_remaining_h(self, plan_remaining: np.ndarray, elapsed: np.ndarray) -> np.ndarray:
        """Heuristic floor on the time still needed (not a physical bound; see AsBuilt §1)."""
        return np.maximum(
            0.0,
            self.eta_floor_frac * np.asarray(plan_remaining, float) - np.asarray(elapsed, float),
        )

    def predict(
        self,
        X: np.ndarray,
        as_of: np.ndarray,
        planned_delivered: np.ndarray,
        floor_parts: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> PredictionArrays:
        """floor_parts = (planned time left after the last reported milestone, time elapsed since)."""
        X = np.asarray(X, dtype=float)
        r = self.raw_quantiles(X)
        cp = X[:, CHECKPOINT_IDX]
        cur = X[:, CURRENT_DELAY_IDX]
        lo, hi = apply_offsets(r["q10"], r["q90"], cp, self.offsets)
        raw_p50 = r["q50"] + cur
        q = np.sort(np.vstack([lo, r["q50"], hi]), axis=0) + cur
        ordered_p50 = q[1].copy()
        # ETA >= as_of + a heuristic minimum remaining time
        floor = np.asarray(as_of, float) - np.asarray(planned_delivered, float)
        if floor_parts is not None:
            floor = floor + self.min_remaining_h(*floor_parts)
        delivered = cp >= 9
        floor = np.where(delivered, -np.inf, floor)
        q = np.maximum(q, floor)
        floored_p50 = q[1].copy()
        q[:, delivered] = cur[delivered]  # delivered: the realised delay, no uncertainty
        # P80 for the customer promise: a trained q80 with its own one-sided conformal offset,
        # kept inside [P50, P90] so the published quantiles stay ordered
        if "q80" in r and self.offsets80:
            p80 = r["q80"] + group_offset(cp, self.offsets80) + cur
            calibrated = True
        else:
            p80 = q[1] + P80_FROM_P50_P90 * np.maximum(q[2] - q[1], 0.0)
            calibrated = False
        p80 = np.clip(p80, q[1], q[2])
        p80[delivered] = cur[delivered]
        raw = self.boosters["clf"].predict(X, num_threads=1)
        if self.late_stack and self.resid_pools:
            need = self.late_threshold_h - cur - X[:, PHYS_IDX].sum(axis=1)
            p_emp = empirical_exceedance(self.pool_arrays(), cp, need)
            p_late = stack_probability(self.late_stack, p_emp, np.asarray(raw, float))
        else:
            p_clf = np.interp(raw, self.iso_x, self.iso_y) if self.iso_x else raw
            p_q = quantile_implied_exceedance(q[0], q[1], q[2], self.late_threshold_h)
            p_late = self.late_blend * p_clf + (1.0 - self.late_blend) * p_q
        p_late = np.where(delivered, (cur > self.late_threshold_h).astype(float), p_late)
        stage = self._stage_forecast(X, q[1] - cur, cp)
        return PredictionArrays(
            q[0],
            q[1],
            q[2],
            np.clip(p_late, 0.0, 1.0),
            q[1] - cur,
            stage,
            raw_p50=raw_p50,
            ordering_adjust=ordered_p50 - raw_p50,
            floor_adjust=floored_p50 - ordered_p50,
            delivered_adjust=q[1] - floored_p50,
            delay_p80=p80,
            p80_calibrated=calibrated,
        )

    def _stage_forecast(
        self, X: np.ndarray, remaining: np.ndarray, cp: np.ndarray
    ) -> dict[StageGroup, np.ndarray]:
        """Per-group increments reconciled so they sum exactly to the P50 remaining delay."""
        if not all(f"stage_{g.value}" in self.boosters for g in PHYSICAL_GROUPS):
            return {}
        preds = {
            g: self.boosters[f"stage_{g.value}"].predict(X, num_threads=1) for g in PHYSICAL_GROUPS
        }
        out = {g: np.zeros(len(X)) for g in PHYSICAL_GROUPS}
        for i in range(len(X)):
            fut = future_groups(int(cp[i]), bool(X[i, HAS_TS_IDX]))
            if not fut:
                continue
            vals = np.array([preds[g][i] for g in fut])
            w = np.array([self.stage_weights.get(g.value, 1.0) for g in fut])
            vals = vals + w / w.sum() * (remaining[i] - vals.sum())
            for g, v in zip(fut, vals, strict=True):
                out[g][i] = v
        return out

    def rulebook_contributions(self, X: np.ndarray) -> np.ndarray:
        """The operator-rulebook part of the raw P50 remaining delay: [n, n_features + 1]."""
        X = np.asarray(X, dtype=float)
        c = np.zeros((len(X), X.shape[1] + 1))
        if self.target_mode == "residual":
            c[:, PHYS_IDX] = X[:, PHYS_IDX]
        return c

    def learned_contributions(self, X: np.ndarray) -> np.ndarray:
        """λ x exact TreeSHAP of the learned median (last column = bias): [n, n_features + 1].

        All zeros when λ = 0: the learned correction then does not move the P50 at all.
        """
        X = np.asarray(X, dtype=float)
        if self.shrink == 0.0:
            return np.zeros((len(X), X.shape[1] + 1))
        return self.shrink * self.boosters["q50"].predict(X, pred_contrib=True, num_threads=1)

    def contributions(self, X: np.ndarray) -> np.ndarray:
        """Rulebook + learned contributions; sums exactly to the raw P50 remaining delay."""
        return self.rulebook_contributions(X) + self.learned_contributions(X)

    @property
    def explanation_mode(self) -> str:
        """What the P50 forecast bars are: the rulebook, rulebook + learned correction, or learned."""
        if self.target_mode != "residual":
            return "learned"
        return "rulebook" if self.shrink == 0.0 else "rulebook+learned"
