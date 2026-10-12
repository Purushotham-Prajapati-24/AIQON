"""Generate a synthetic shipment dataset with a ground-truth cause ledger."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from cascade.domain.delay import DEFAULT_LATE_THRESHOLD_H
from cascade.domain.network import NETWORK, Network
from cascade.domain.stages import EVENT_INDEX, GROUP_OF_STAGE, EventType, event_sequence
from cascade.sim.external import ExternalSeries, generate_external
from cascade.sim.mechanics import (
    Draws,
    Intervention,
    Outcome,
    ShipmentSpec,
    plan_shipment,
    propagate,
    sample_draws,
)

E = EventType


@dataclass
class SimConfig:
    seed: int = 42
    n_shipments: int = 300
    first_week: int = 1
    last_week: int = 44
    late_threshold_h: float = DEFAULT_LATE_THRESHOLD_H
    mcar_rate: float = 0.06
    edi_tier2_rate: float = 0.08
    edi_tier3_rate: float = 0.25
    discharge_congestion_rate: float = 0.15
    jitter_h: float = 0.75  # error in the event time *stated* in a milestone message
    mean_shipments_per_voyage: float = 2.0
    max_connection_slack_h: float = 54.0
    # reporting latency: a milestone message reaches CASCADE some time after the event happened.
    # Lognormal, median by carrier EDI tier (1 = good feed); DELIVERED (proof of delivery) is
    # treated as known on arrival. Drawn from a separate RNG stream so the physics is unchanged.
    latency_median_tier1_h: float = 0.5
    latency_median_tier2_h: float = 2.0
    latency_median_tier3_h: float = 6.0
    latency_sigma: float = 0.8


@dataclass
class SimOutput:
    shipments: pd.DataFrame
    events: pd.DataFrame
    ledger: pd.DataFrame
    draws: pd.DataFrame
    external: ExternalSeries
    config: SimConfig = field(default_factory=SimConfig)

    def save(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        # CSV (not parquet): portable and works where native parquet DLLs are policy-blocked
        self.shipments.to_csv(out_dir / "shipments.csv", index=False)
        self.events.to_csv(out_dir / "events.csv", index=False)
        self.ledger.to_csv(out_dir / "cause_ledger.csv", index=False)
        self.draws.to_csv(out_dir / "draws.csv", index=False)
        self.external.save(out_dir / "external.npz")
        (out_dir / "sim_config.json").write_text(json.dumps(asdict(self.config), indent=2))

    @classmethod
    def load(cls, out_dir: Path) -> SimOutput:
        cfg = SimConfig(**json.loads((out_dir / "sim_config.json").read_text()))
        return cls(
            shipments=pd.read_csv(out_dir / "shipments.csv"),
            events=pd.read_csv(out_dir / "events.csv"),
            ledger=pd.read_csv(out_dir / "cause_ledger.csv"),
            draws=pd.read_csv(out_dir / "draws.csv"),
            external=ExternalSeries.load(out_dir / "external.npz"),
            config=cfg,
        )


def spec_from_row(row: pd.Series | dict) -> ShipmentSpec:
    r = dict(row)
    planned = {
        e: float(r[f"planned_{e.value}"])
        for e in EventType
        if pd.notna(r.get(f"planned_{e.value}"))
    }
    return ShipmentSpec(
        shipment_id=r["shipment_id"],
        voyage_id=r["voyage_id"],
        lane_id=r["lane_id"],
        carrier=r["carrier"],
        commodity_risk=int(r["commodity_risk"]),
        docs_complete=bool(r["docs_complete"]),
        inland_mode=r["inland_mode"],
        cargo_value_usd=float(r["cargo_value_usd"]),
        planned=planned,
    )


def draws_from_row(row: pd.Series | dict) -> Draws:
    r = dict(row)
    return Draws(**{k: float(r[k]) for k in Draws.__dataclass_fields__})


def resimulate(
    sim: SimOutput,
    shipment_id: str,
    iv: Intervention | None = None,
    external: ExternalSeries | None = None,
) -> Outcome:
    """Re-run the SCM for one shipment with identical exogenous noise (true counterfactual)."""
    srow = sim.shipments.loc[sim.shipments.shipment_id == shipment_id].iloc[0]
    drow = sim.draws.loc[sim.draws.shipment_id == shipment_id].iloc[0]
    return propagate(
        spec_from_row(srow), draws_from_row(drow), external or sim.external, NETWORK, iv
    )


def generate(cfg: SimConfig, net: Network = NETWORK) -> SimOutput:
    rng = np.random.default_rng(cfg.seed)
    ext = generate_external(rng)
    lanes = list(net.lanes.values())
    carriers = list(net.carriers.values())

    ship_rows, event_rows, ledger_rows, draw_rows = [], [], [], []
    n_done, v = 0, 0
    used: set[tuple[str, int]] = set()
    while n_done < cfg.n_shipments:
        lane = lanes[int(rng.integers(len(lanes)))]
        week = int(rng.integers(cfg.first_week, cfg.last_week + 1))
        if (lane.lane_id, week) in used:
            continue
        used.add((lane.lane_id, week))
        v += 1
        carrier = carriers[int(rng.integers(len(carriers)))]
        origin = net.ports[lane.origin]
        # weekly sailing: lane weekday at 16:00 origin-local
        day = week * 7 + ((lane.sailing_weekday - 2) % 7)
        p_dep = day * 24.0 + 16.0 - origin.tz
        dep_base = float(rng.gamma(1.5, carrier.departure_scale_h))
        connection_slack = float(rng.uniform(0.0, cfg.max_connection_slack_h))
        k = min(1 + int(rng.poisson(cfg.mean_shipments_per_voyage)), 6, cfg.n_shipments - n_done)
        for _ in range(k):
            n_done += 1
            sid = f"SHP-{n_done:06d}"
            planned = plan_shipment(
                lane, net, p_dep, float(rng.uniform(48, 96)), lane.inland_mode, connection_slack
            )
            spec = ShipmentSpec(
                shipment_id=sid,
                voyage_id=f"VOY-{v:05d}",
                lane_id=lane.lane_id,
                carrier=carrier.code,
                commodity_risk=int(rng.choice(3, p=[0.55, 0.30, 0.15])),
                docs_complete=bool(rng.random() < 0.85),
                inland_mode=lane.inland_mode,
                cargo_value_usd=float(np.round(rng.lognormal(np.log(60000), 0.6), -2)),
                planned=planned,
            )
            draws = sample_draws(rng, carrier.departure_scale_h, dep_base)
            out = propagate(spec, draws, ext, net)
            _collect(
                cfg,
                rng,
                ext,
                net,
                spec,
                draws,
                out,
                carrier.edi_tier,
                ship_rows,
                event_rows,
                ledger_rows,
                draw_rows,
            )

    shipments = pd.DataFrame(ship_rows)
    shipments = shipments.sort_values("planned_DEPART_ORIGIN", kind="stable").reset_index(drop=True)
    events = add_reporting_latency(pd.DataFrame(event_rows), shipments, cfg)
    return SimOutput(
        shipments=shipments,
        events=events,
        ledger=pd.DataFrame(ledger_rows),
        draws=pd.DataFrame(draw_rows),
        external=ext,
        config=cfg,
    )


def add_reporting_latency(
    events: pd.DataFrame, shipments: pd.DataFrame, cfg: SimConfig
) -> pd.DataFrame:
    """available_h = when the milestone message reached CASCADE (never before the event)."""
    lat_rng = np.random.default_rng([cfg.seed, 0x1A7E])  # independent of the physics stream
    tier = events.shipment_id.map(shipments.set_index("shipment_id").carrier_edi_tier)
    median = tier.map(
        {
            1: cfg.latency_median_tier1_h,
            2: cfg.latency_median_tier2_h,
            3: cfg.latency_median_tier3_h,
        }
    ).to_numpy(float)
    latency = median * np.exp(cfg.latency_sigma * lat_rng.standard_normal(len(events)))
    latency[(events.event == E.DELIVERED.value).to_numpy()] = 0.0
    sent = np.maximum(events.actual_h.to_numpy(float), events.reported_h.to_numpy(float))
    out = events.copy()
    out["available_h"] = np.where(out.reported.to_numpy(bool), sent + latency, np.nan)
    return out


def _collect(
    cfg, rng, ext, net, spec, draws, out, edi_tier, ship_rows, event_rows, ledger_rows, draw_rows
):
    lane = net.lanes[spec.lane_id]
    seq = event_sequence(lane.has_transshipment)
    total = out.actual[E.DELIVERED] - spec.planned[E.DELIVERED]

    # root cause = stage with the largest positive increment (ground truth for explanations)
    stage_inc: dict[str, float] = {}
    for stage, _cause, h in out.ledger:
        stage_inc[stage.value] = stage_inc.get(stage.value, 0.0) + h
    top_stage = max(stage_inc, key=lambda s: stage_inc[s])
    causes = [(c, h) for s, c, h in out.ledger if s.value == top_stage]
    top_cause = max(causes, key=lambda x: x[1])[0] if causes else "none"
    significant = stage_inc[top_stage] > 6.0

    row = {
        "shipment_id": spec.shipment_id,
        "voyage_id": spec.voyage_id,
        "lane_id": spec.lane_id,
        "origin": lane.origin,
        "hub": lane.hub or "NONE",
        "dest": lane.dest,
        "has_transshipment": lane.has_transshipment,
        "carrier": spec.carrier,
        "carrier_edi_tier": edi_tier,
        "commodity_risk": spec.commodity_risk,
        "docs_complete": spec.docs_complete,
        "inland_mode": spec.inland_mode,
        "cargo_value_usd": spec.cargo_value_usd,
    }
    for e in EventType:
        row[f"planned_{e.value}"] = spec.planned.get(e, np.nan)
    row.update(
        actual_DELIVERED=out.actual[E.DELIVERED],
        total_delay_h=total,
        is_late=total > cfg.late_threshold_h,
        rolled=out.rolled,
        missed_connections=out.missed_connections,
        root_cause_stage=top_stage if significant else "NONE",
        root_cause_group=GROUP_OF_STAGE[
            next(s for s, _, _ in out.ledger if s.value == top_stage)
        ].value
        if significant
        else "NONE",
        root_cause=top_cause if significant else "none",
    )
    ship_rows.append(row)

    # reporting: typed missingness + jitter (DELIVERED always reported exactly)
    prev_rep = -np.inf
    rho_d = ext.rho(lane.dest, out.actual[E.ARRIVE_DEST_PORT])
    for e in seq:
        p_miss = 0.0
        if e != E.DELIVERED:
            p_miss = (
                cfg.mcar_rate + {1: 0.0, 2: cfg.edi_tier2_rate, 3: cfg.edi_tier3_rate}[edi_tier]
            )
            if e == E.DISCHARGED and rho_d > 0.85:
                p_miss += cfg.discharge_congestion_rate
        reported = bool(rng.random() >= p_miss)
        jitter = 0.0 if e == E.DELIVERED else float(rng.uniform(-cfg.jitter_h, cfg.jitter_h))
        rep_t = max(out.actual[e] + jitter, prev_rep + 0.1) if reported else np.nan
        if reported:
            prev_rep = rep_t
        event_rows.append(
            {
                "shipment_id": spec.shipment_id,
                "event": e.value,
                "seq": EVENT_INDEX[e],
                "planned_h": spec.planned[e],
                "actual_h": out.actual[e],
                "reported": reported,
                "reported_h": rep_t,
            }
        )
    for stage, cause, h in out.ledger:
        ledger_rows.append(
            {
                "shipment_id": spec.shipment_id,
                "stage": stage.value,
                "group": GROUP_OF_STAGE[stage].value,
                "cause": cause,
                "hours": h,
            }
        )
    draw_rows.append(
        {
            "shipment_id": spec.shipment_id,
            **{k: getattr(draws, k) for k in Draws.__dataclass_fields__},
        }
    )
