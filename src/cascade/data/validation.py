"""Schema + invariant validation for simulator outputs.

A light, dependency-free stand-in for Pandera (whose native deps are policy-blocked on some
Windows machines). Every check raises ``DataValidationError`` with an actionable message.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cascade.domain.network import CARRIER_CODES, LANE_IDS
from cascade.domain.stages import EventType


class DataValidationError(ValueError):
    pass


SHIPMENT_COLUMNS = {
    "shipment_id": "object",
    "voyage_id": "object",
    "lane_id": "object",
    "carrier": "object",
    "commodity_risk": "int",
    "docs_complete": "bool",
    "inland_mode": "object",
    "total_delay_h": "float",
    "is_late": "bool",
}


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise DataValidationError(msg)


def validate_shipments(df: pd.DataFrame) -> None:
    missing = set(SHIPMENT_COLUMNS) - set(df.columns)
    _require(not missing, f"shipments: missing columns {sorted(missing)}")
    _require(df.shipment_id.is_unique, "shipments: shipment_id must be unique")
    _require(df.lane_id.isin(LANE_IDS).all(), "shipments: unknown lane_id")
    _require(df.carrier.isin(CARRIER_CODES).all(), "shipments: unknown carrier")
    _require(df.commodity_risk.between(0, 2).all(), "shipments: commodity_risk must be in {0,1,2}")
    _require(
        df.inland_mode.isin(["truck", "rail"]).all(), "shipments: inland_mode must be truck|rail"
    )
    _require(df.total_delay_h.notna().all(), "shipments: total_delay_h has NaN")
    for e in EventType:
        col = f"planned_{e.value}"
        _require(col in df.columns, f"shipments: missing {col}")


def validate_events(events: pd.DataFrame, shipments: pd.DataFrame) -> None:
    _require(events.shipment_id.isin(shipments.shipment_id).all(), "events: orphan shipment_id")
    delivered = events[events.event == EventType.DELIVERED.value]
    _require(delivered.reported.all(), "events: DELIVERED must always be reported (ground truth)")
    if "available_h" in events.columns:  # information-time contract
        rep = events[events.reported]
        _require(
            bool((rep.available_h >= rep.actual_h - 1e-9).all()),
            "events: a report became available before its event happened",
        )
        _require(
            bool((rep.available_h >= rep.reported_h - 1e-9).all()),
            "events: a report became available before its stated event time",
        )
    for sid, g in events.sort_values(["shipment_id", "seq"]).groupby("shipment_id"):
        _require(
            bool(np.all(np.diff(g.actual_h.values) >= -1e-9)),
            f"events: non-monotone actuals for {sid}",
        )
        rep = g.reported_h.dropna().values
        _require(bool(np.all(np.diff(rep) > 0)), f"events: non-monotone reported times for {sid}")


def validate_ledger(ledger: pd.DataFrame, shipments: pd.DataFrame, tol_h: float = 1 / 60) -> None:
    sums = ledger.groupby("shipment_id").hours.sum().reindex(shipments.shipment_id)
    err = sums.values - shipments.total_delay_h.values
    _require(
        bool(np.all(np.abs(err) <= tol_h)),
        f"ledger: cause ledger does not sum to total delay (max err {np.abs(err).max():.4f}h)",
    )


def validate_all(shipments: pd.DataFrame, events: pd.DataFrame, ledger: pd.DataFrame) -> None:
    validate_shipments(shipments)
    validate_events(events, shipments)
    validate_ledger(ledger, shipments)
