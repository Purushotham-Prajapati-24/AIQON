"""Paired v1.1 vs v1.2 comparison of the real production pipeline over the DEV worlds, plus an
offline replay of λ-selection rules (each rule sees only training-side curves; we read off the
test MAE the chosen λ would have produced).

Usage: python compare_prod.py [tag] [new_config]
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import prod_ref
from common import CACHE

tag = sys.argv[1] if len(sys.argv) > 1 else "prod"
new = sys.argv[2] if len(sys.argv) > 2 else "v12b"
res = {int(p.stem): json.loads(p.read_text())["res"] for p in (CACHE / tag).glob("*.json")}
res = {s: o for s, o in res.items() if new in o}
pd.set_option("display.width", 200)
print(f"{len(res)} worlds\n", prod_ref.summarise(res).round(3).to_string(), "\n")


def scalars(d):
    return {m: v for m, v in d.items() if not isinstance(v, dict)}


df = pd.concat({s: pd.DataFrame({k: scalars(d) for k, d in o.items()}).T
                for s, o in res.items()}).astype(float)
v11, v12 = df.xs("v11", level=1), df.xs(new, level=1)
lines = [f"paired: v11 vs {new}"]
for m in ["mae", "brier", "pr_auc", "roc_auc", "iscore", "coverage", "width"]:
    d = (v12[m] - v11[m]) / v11[m]
    lines.append(f"{m:<9} v1.1 {v11[m].mean():8.3f}  v1.2 {v12[m].mean():8.3f}  "
                 f"rel {100 * d.mean():+6.2f}% ± {100 * d.std(ddof=1) / np.sqrt(len(d)):.2f}%  "
                 f"better in {int(((v12[m] - v11[m]) * (1 if m in ('pr_auc', 'roc_auc') else -1) > 1e-12).sum())}/{len(d)}")
for k, v in (("v1.1", v11), (new, v12)):
    lines.append(f"{k} MAE gain vs rulebook {100 * (1 - v.mae / v.mae_rulebook).mean():+.2f}%  "
                 f"lambda {v.shrink.round(2).tolist()}")


# ---- offline λ-rule replay on the new config ---------------------------------------------------
def pick(curve: dict, margin=0.0):
    lam = min(curve, key=lambda k: (round(curve[k], 4), float(k)))
    return lam if curve[lam] <= curve["0.0"] * (1 - margin) else "0.0"


def rel(c):
    return {k: v / c["0.0"] for k, v in c.items()}


rules = {}
for s, o in res.items():
    r = o[new]
    t = {k: v for k, v in r["lam_temporal"].items() if k in r["lam_test"]}
    f = {k: v for k, v in r["lam_oof"].items() if k in r["lam_test"]}
    comb = {k: 0.5 * (rel(t)[k] + rel(f)[k]) for k in t}
    chosen = {"zero": "0.0", "temporal": pick(t), "oof": pick(f), "combined": pick(comb),
              "combined_m1%": pick(comb, 0.01), "both_improve_1%": (
                  pick(comb) if rel(t)[pick(comb)] <= 0.99 and rel(f)[pick(comb)] <= 0.99
                  else "0.0"),
              "oracle(test)": min(r["lam_test"], key=lambda k: r["lam_test"][k]["mae"])}
    rules[s] = {k: r["lam_test"][lam]["mae"] for k, lam in chosen.items()}
R = pd.DataFrame(rules).T
lines.append("\nλ-rule replay (test MAE, mean over worlds; lower is better):")
for k in R.columns:
    d = (R[k] - R["zero"]) / R["zero"]
    lines.append(f"  {k:<16} {R[k].mean():7.3f}   vs λ=0 {100 * d.mean():+5.2f}% "
                 f"± {100 * d.std(ddof=1) / np.sqrt(len(d)):.2f}%   worse in {(d > 1e-9).sum()}")
print("\n".join(lines))
Path(CACHE / f"{tag}_{new}_summary.txt").write_text("\n".join(lines), encoding="utf-8")
