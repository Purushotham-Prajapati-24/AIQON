"""Smoothed historical priors (target encodings) — always fit on training folds only."""

from __future__ import annotations

import math

import pandas as pd

SMOOTHING_M = 10.0  # pseudo-count pulling small groups toward the global mean

PRIOR_KEYS = {
    "prior_lane_mean_delay": "lane_id",
    "prior_carrier_origin_inc": "carrier",
    "prior_dest_port_inc": "dest",
    "prior_dest_customs_inc": "dest",
    "prior_hub_miss_rate": "hub",
}

PriorTable = dict[str, dict[str, float]]  # feature -> {key: value, "__global__": value}


def _smoothed(values: pd.Series, keys: pd.Series) -> dict[str, float]:
    g = float(values.mean()) if len(values) else 0.0
    stats = (
        pd.DataFrame({"k": keys.values, "v": values.values}).groupby("k")["v"].agg(["sum", "count"])
    )
    out = {
        str(k): float((r["sum"] + SMOOTHING_M * g) / (r["count"] + SMOOTHING_M))
        for k, r in stats.iterrows()
    }
    out["__global__"] = g
    return out


def fit_priors(shipments: pd.DataFrame, ledger: pd.DataFrame) -> PriorTable:
    inc = ledger[ledger.shipment_id.isin(shipments.shipment_id)].pivot_table(
        index="shipment_id", columns="group", values="hours", aggfunc="sum", fill_value=0.0
    )
    s = shipments.set_index("shipment_id")
    inc = inc.reindex(s.index).fillna(0.0)
    hub_s = s[s.hub != "NONE"]
    table: PriorTable = {
        "prior_lane_mean_delay": _smoothed(s.total_delay_h, s.lane_id),
        "prior_carrier_origin_inc": _smoothed(inc.get("ORIGIN", 0.0 * s.total_delay_h), s.carrier),
        "prior_dest_port_inc": _smoothed(inc.get("PORT", 0.0 * s.total_delay_h), s.dest),
        "prior_dest_customs_inc": _smoothed(inc.get("CUSTOMS", 0.0 * s.total_delay_h), s.dest),
        "prior_hub_miss_rate": _smoothed((hub_s.missed_connections > 0).astype(float), hub_s.hub),
    }
    table["prior_hub_miss_rate"]["NONE"] = 0.0
    return table


def lookup(table: PriorTable, lane_id: str, carrier: str, dest: str, hub: str) -> dict[str, float]:
    keys = {"lane_id": lane_id, "carrier": carrier, "dest": dest, "hub": hub}
    out = {}
    for feat, key in PRIOR_KEYS.items():
        t = table.get(feat, {})
        out[feat] = t.get(keys[key], t.get("__global__", math.nan))
    return out


def apply_priors(rows: pd.DataFrame, table: PriorTable) -> pd.DataFrame:
    """Vectorised prior lookup for a frame with lane_id / carrier / dest / hub columns."""
    rows = rows.copy()
    for feat, key in PRIOR_KEYS.items():
        t = table[feat]
        rows[feat] = rows[key].map(t).fillna(t["__global__"]).astype(float)
    return rows
