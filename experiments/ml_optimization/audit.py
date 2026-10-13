"""Phase 1 — data audit + error diagnostics on the DEV worlds only (holdout never inspected).

Prints: missingness, near-constant features, duplicates, target distributions, the "outlier"
analysis, rulebook bias by checkpoint, component calibration, collinearity, train/test shift,
where rulebook error lives (checkpoint x snapshot kind), and overdue-milestone failure buckets.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import DEV_SEEDS, FEATS, NUMERIC, load_world

pd.set_option("display.width", 220)
worlds = [load_world(s) for s in DEV_SEEDS]
tr = pd.concat([w.train.assign(seed=w.seed) for w in worlds], ignore_index=True)
te = pd.concat([w.test.assign(seed=w.seed) for w in worlds], ignore_index=True)
print(f"pooled dev: {len(tr)} train rows, {len(te)} test rows, late rate {tr.y_late.mean():.2f}\n")

print("== missingness (train) ==")
na = tr[FEATS].isna().mean().sort_values(ascending=False)
print(na[na > 0].round(3).to_string(), "\n")

print("== near-constant numeric features (top value share > 0.95) ==")
for f in NUMERIC:
    top = tr[f].value_counts(normalize=True, dropna=False).iloc[0]
    if top > 0.95:
        print(f"  {f:<32} {top:.3f}")

dup = tr.duplicated(subset=FEATS + ["seed"]).sum()
print(f"\n== exact duplicate feature rows (train): {dup} ({dup / len(tr):.1%})\n")

print("== target distributions ==")
for col in ["y_total", "y_remaining", "resid"]:
    x = tr[col]
    q = x.quantile([0.01, 0.5, 0.99])
    print(f"  {col:<12} mean {x.mean():7.1f} sd {x.std():6.1f} skew {x.skew():5.2f} "
          f"kurt {x.kurt():6.1f} | q01 {q[0.01]:7.1f} q50 {q[0.5]:6.1f} q99 {q[0.99]:7.1f}")
print(f"  share |resid| < 1 h (rulebook exactly right): {(tr.resid.abs() < 1).mean():.2f}")

print("\n== 'outliers' by a textbook 5*MAD rule on the residual ==")
r = tr.resid
mad = (r - r.median()).abs().median()
out = (r - r.median()).abs() > 5 * 1.4826 * mad
print(f"  MAD {mad:.2f} h -> {out.mean():.1%} of rows flagged (zero-inflated residual: these are"
      f" real inspections / missed connections, so rows are NOT deleted)")

print("\n== rulebook vs carry-forward by checkpoint x snapshot kind (train) ==")
tr["ae_rule"], tr["ae_carry"] = tr.resid.abs(), tr.y_remaining.abs()
g = tr.groupby(["checkpoint", "kind"])
print(pd.DataFrame({"n": g.size(), "rule_mae": g.ae_rule.mean(), "carry_mae": g.ae_carry.mean(),
                    "err_share": g.ae_rule.sum() / tr.ae_rule.sum()}).round(2).to_string())

print("\n== overdue next milestone: rulebook vs carry by checkpoint x EDI tier (train) ==")
od = tr[tr.overdue_h > 0]
g = od.groupby(["checkpoint", "carrier_edi_tier"])
print(pd.DataFrame({"n": g.size(), "rule_mae": g.ae_rule.mean(), "carry_mae": g.ae_carry.mean(),
                    "median_resid": g.resid.median()}).round(1).to_string())

print("\n== rulebook component vs its own future stage increment ==")
pairs = {"proj_inc_origin_h": "y_inc_ORIGIN", "proj_inc_ocean_h": "y_inc_OCEAN",
         "proj_inc_hub_h": "y_inc_TRANSSHIPMENT", "proj_inc_port_h": "y_inc_PORT",
         "proj_inc_customs_h": "y_inc_CUSTOMS", "proj_inc_inland_h": "y_inc_INLAND"}
for p, y in pairs.items():
    a, b = tr[p], tr[y]
    print(f"  {p:<22} corr {a.corr(b):5.2f}  slope {np.polyfit(a, b, 1)[0]:5.2f}  "
          f"mean proj {a.mean():6.1f} vs truth {b.mean():6.1f}")

print("\n== collinear numeric pairs (|r| > 0.95) ==")
c = tr[NUMERIC].corr().abs()
for i, j in zip(*np.triu_indices_from(c, 1)):
    if c.iat[i, j] > 0.95:
        print(f"  {c.index[i]:<30} {c.columns[j]:<30} {c.iat[i, j]:.3f}")

print("\n== train -> test shift (standardised mean difference, top 8) ==")
smd = ((te[NUMERIC].mean() - tr[NUMERIC].mean()) / tr[NUMERIC].std().replace(0, np.nan)).abs()
print(smd.sort_values(ascending=False).head(8).round(3).to_string())
