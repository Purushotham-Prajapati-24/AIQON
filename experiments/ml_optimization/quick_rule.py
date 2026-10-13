"""Rulebook-only MAE on DEV worlds (train + test splits) for a cache — cheap cleaning checks."""

import os

import numpy as np

from common import DEV_SEEDS, load_world

te, tr = [], []
for s in DEV_SEEDS:
    w = load_world(s)
    te.append(w.test.resid.abs().mean())
    tr.append(w.train.resid.abs().mean())
print(f"{os.environ.get('CACHE_NAME', 'cache'):<12} rulebook test MAE {np.mean(te):6.3f}"
      f"   train MAE {np.mean(tr):6.3f}")
