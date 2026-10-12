"""Leakage-safe splits: out-of-time test + GroupKFold by voyage (shared vessels never straddle folds)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class Splits:
    train_ids: list[str]
    test_ids: list[str]
    fold_of: dict[str, int]  # training shipment -> CV fold
    n_folds: int

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self)))

    @classmethod
    def load(cls, path: Path) -> Splits:
        return cls(**json.loads(path.read_text()))


def make_splits(
    shipments: pd.DataFrame, test_frac: float = 0.2, n_folds: int = 5, seed: int = 0
) -> Splits:
    s = shipments.sort_values(["planned_DEPART_ORIGIN", "shipment_id"])
    # cut on voyage boundaries so a vessel is entirely in train or test
    voyages = s.drop_duplicates("voyage_id")[["voyage_id", "planned_DEPART_ORIGIN"]]
    n_test_target = int(round(test_frac * len(s)))
    counts = s.groupby("voyage_id").size()
    test_voy: list[str] = []
    n = 0
    for v in voyages.voyage_id.iloc[::-1]:
        if n >= n_test_target:
            break
        test_voy.append(v)
        n += int(counts[v])
    is_test = s.voyage_id.isin(test_voy)
    train = s[~is_test]
    rng = np.random.default_rng(seed)
    train_voy = np.array(sorted(train.voyage_id.unique()), dtype=object)
    rng.shuffle(train_voy)
    # balanced greedy assignment of voyages to folds by shipment count
    loads = [0] * n_folds
    fold_of_voy = {}
    for v in sorted(train_voy, key=lambda v: -int(counts[v])):
        k = int(np.argmin(loads))
        fold_of_voy[v] = k
        loads[k] += int(counts[v])
    fold_of = {
        sid: fold_of_voy[v] for sid, v in zip(train.shipment_id, train.voyage_id, strict=True)
    }
    return Splits(train.shipment_id.tolist(), s[is_test].shipment_id.tolist(), fold_of, n_folds)
