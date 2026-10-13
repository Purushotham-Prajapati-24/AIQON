"""v1.1 vs v1.2 on the 5 canonical HOLDOUT seeds (paired) and the 7 sensitivity worlds."""

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
KEYS = [
    ("mae_cascade_h", -1), ("mae_improvement_vs_B1", 1), ("mae_rulebook_h", -1),
    ("coverage_p10_p90_overall", 0), ("brier_tau24", -1), ("pr_auc_tau24", 1),
    ("pr_auc_tau24_at_arrival", 1), ("alert_lead_ge_48h_share", 1),
    ("late_alert_false_positive_rate", -1), ("alerts_per_100_shipment_days", -1),
    ("promise_hit_rate", 1), ("promise_flip_ratio", -1), ("attribution_top1", 1),
]


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


lines = []
a, b = load(HERE / "seeds_v110.json"), load(ROOT / "reports" / "seeds.json")
ra = {int(r["seed"]) if "seed" in r else i: r for i, r in enumerate(a["runs"])}
rb = {int(r["seed"]) if "seed" in r else i: r for i, r in enumerate(b["runs"])}
lines.append(f"HOLDOUT seeds {a['seeds']}  (mean ± sd over seeds; paired better-count)")
for k, sign in KEYS:
    va = np.array([ra[s][k] for s in sorted(ra)], float)
    vb = np.array([rb[s][k] for s in sorted(rb)], float)
    better = int(((vb - va) * sign > 1e-12).sum()) if sign else "-"
    lines.append(f"  {k:<32} v1.1 {va.mean():8.3f} ± {va.std(ddof=1):6.3f}   "
                 f"v1.2 {vb.mean():8.3f} ± {vb.std(ddof=1):6.3f}   better in {better}/{len(va)}")

sa, sb = load(HERE / "sensitivity_v110.json"), load(ROOT / "reports" / "sensitivity.json")
lines.append("\nSENSITIVITY worlds (changed simulator mechanics), seed 42")
for name in sb["results"]:
    ha, hb = sa["results"].get(name, {}), sb["results"][name]
    ha, hb = ha.get("headline", ha), hb.get("headline", hb)
    lines.append(f"  {name:<30} MAE {ha.get('mae_cascade_h', float('nan')):6.2f} -> "
                 f"{hb.get('mae_cascade_h', float('nan')):6.2f}   Brier "
                 f"{ha.get('brier_tau24', float('nan')):.3f} -> {hb.get('brier_tau24', float('nan')):.3f}"
                 f"   cov {ha.get('coverage_p10_p90_overall', float('nan')):.2f} -> "
                 f"{hb.get('coverage_p10_p90_overall', float('nan')):.2f}")
print("\n".join(lines))
(HERE / "holdout_summary.txt").write_text("\n".join(lines), encoding="utf-8")
