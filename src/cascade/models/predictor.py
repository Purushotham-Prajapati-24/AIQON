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
from cascade.models.conformal import apply_offsets

QUANTILES = {"q10": 0.1, "q50": 0.5, "q90": 0.9}
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
    version: str = "dev"

    # ---- core ---------------------------------------------------------------------------
    def _base(self, X: np.ndarray) -> np.ndarray:
        if self.target_mode == "residual":
            return X[:, PHYS_IDX].sum(axis=1)
        return np.zeros(len(X))

    def raw_quantiles(self, X: np.ndarray) -> dict[str, np.ndarray]:
        """Remaining-delay quantiles before conformal widening and guardrails."""
        base = self._base(X)
        g = {k: self.boosters[k].predict(X, num_threads=1) for k in QUANTILES}
        center = self.shrink * g["q50"]
        return {k: base + center + (g[k] - g["q50"]) for k in QUANTILES}

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
        raw = self.boosters["clf"].predict(X, num_threads=1)
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
