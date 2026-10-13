"""Full-pipeline A/B on DEV seeds (decision metrics need the engine replay; no publishing).

Run before merging with upstream v1.2.0: the "v12_f1" arm (plain-F1 alert threshold) used a
switch that no longer exists, since upstream adopted the same actionable-F1 objective.

  python ab_pipeline.py run <config> <seed>      python ab_pipeline.py summary
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from cascade.eval.pipeline import PipelineConfig, run
from cascade.models.train import TrainConfig
from common import CACHE

CONFIGS = {
    "v11": TrainConfig(shrink_rule="temporal", late_model="blend", band="shifted"),
    "v12": TrainConfig(),
}
KEYS = ["mae_cascade_h", "mae_rulebook_h", "coverage_p10_p90_overall", "brier_tau24",
        "pr_auc_tau24", "alert_lead_ge_48h_share", "late_alert_false_positive_rate",
        "alerts_per_100_shipment_days", "promise_hit_rate", "promise_flip_ratio",
        "latency_p95_ms"]
OUT = CACHE / "ab"

if __name__ == "__main__":
    if sys.argv[1] == "run":
        name, seed = sys.argv[2], int(sys.argv[3])
        d = OUT / name / str(seed)
        m = run(PipelineConfig(seed=seed, fast=True, publish=False, train=CONFIGS[name],
                               data_dir=OUT / "data" / name, reports_dir=d), log=lambda *_: None)
        h = m["headline"] | {"runtime_s": m["meta"]["runtime_s"],
                             "late_alert_p": m["model_selection"]["late_alert_p"]}
        (d / "headline.json").write_text(json.dumps(h, default=float))
        print(name, seed, "done", flush=True)
    else:
        rows = {}
        for f in OUT.glob("*/*/headline.json"):
            rows[(f.parent.parent.name, int(f.parent.name))] = json.loads(f.read_text())
        df = pd.DataFrame(rows).T
        df.index.names = ["config", "seed"]
        cols = KEYS + ["late_alert_p", "runtime_s"]
        pd.set_option("display.width", 220)
        print(df[cols].astype(float).groupby(level=0).mean().T.round(3).to_string())
        print("seeds per config:", df.groupby(level=0).size().to_dict())
        _ = np
