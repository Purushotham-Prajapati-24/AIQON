"""Baselines every model must beat (reported on the same frozen split).

B0 schedule        : remaining = -current_delay  (ETA = plan)
B1 carry-forward   : remaining = 0               (current delay persists)
B2 propagation prior: remaining = median_remaining(lane, checkpoint) + (phi_cp - 1) * current_delay
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


def b0_schedule(rows: pd.DataFrame) -> np.ndarray:
    return -rows.current_delay_h.to_numpy(float)


def b1_carry_forward(rows: pd.DataFrame) -> np.ndarray:
    return np.zeros(len(rows))


@dataclass
class PropagationPrior:
    """B2: a transparent, learned-from-data propagation heuristic (also the API fallback)."""

    median_by_lane_cp: dict[str, float] = field(default_factory=dict)
    median_by_cp: dict[int, float] = field(default_factory=dict)
    phi_by_cp: dict[int, float] = field(default_factory=dict)

    @staticmethod
    def _key(lane: str, cp: int) -> str:
        return f"{lane}|{cp}"

    def fit(self, rows: pd.DataFrame) -> PropagationPrior:
        cp = rows.checkpoint.astype(int)
        self.median_by_cp = {
            int(k): float(v) for k, v in rows.groupby(cp).y_remaining.median().items()
        }
        g = rows.groupby([rows.lane_id, cp]).y_remaining
        med, cnt = g.median(), g.size()
        for (lane, c), m in med.items():
            # shrink thin cells toward the checkpoint median
            w = cnt[(lane, c)] / (cnt[(lane, c)] + 10.0)
            self.median_by_lane_cp[self._key(lane, int(c))] = float(
                w * m + (1 - w) * self.median_by_cp[int(c)]
            )
        for c, grp in rows.groupby(cp):
            base = np.array([self._median(lane, int(c)) for lane in grp.lane_id])
            x = grp.current_delay_h.to_numpy(float)
            y = grp.y_remaining.to_numpy(float) - base
            phi_minus_1 = float((x * y).sum() / max((x * x).sum(), 1e-6))
            self.phi_by_cp[int(c)] = float(np.clip(1.0 + phi_minus_1, 0.0, 3.0))
        return self

    def _median(self, lane: str, cp: int) -> float:
        return self.median_by_lane_cp.get(self._key(lane, cp), self.median_by_cp.get(cp, 0.0))

    def predict_one(self, lane: str, cp: int, current_delay: float) -> float:
        return self._median(lane, cp) + (self.phi_by_cp.get(cp, 1.0) - 1.0) * current_delay

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        return np.array(
            [
                self.predict_one(lane, int(c), float(d))
                for lane, c, d in zip(
                    rows.lane_id, rows.checkpoint, rows.current_delay_h, strict=True
                )
            ]
        )

    def to_dict(self) -> dict:
        return {
            "median_by_lane_cp": self.median_by_lane_cp,
            "median_by_cp": {str(k): v for k, v in self.median_by_cp.items()},
            "phi_by_cp": {str(k): v for k, v in self.phi_by_cp.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> PropagationPrior:
        return cls(
            d["median_by_lane_cp"],
            {int(k): v for k, v in d["median_by_cp"].items()},
            {int(k): v for k, v in d["phi_by_cp"].items()},
        )
