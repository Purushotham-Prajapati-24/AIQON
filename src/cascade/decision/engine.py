"""Engine: snapshot -> model -> guardrails -> explanation -> decision layer, with a fallback chain.

The same engine backs the API, the replay evaluation and (through the API) the UI. Promise ETA
and alerts are derived by *replaying* a shipment's own milestones up to ``as_of``, so they are
deterministic and stateless: any instance gives the same answer for the same question.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from cascade.decision.advisor import Recommendation, candidate_actions, rank_actions
from cascade.decision.alerts import AlertEvent, PredState, evaluate_alerts
from cascade.decision.cost import CostModel
from cascade.decision.promise import PromiseState, update_promise
from cascade.decision.scenarios import Scenario
from cascade.domain.delay import risk_tier, to_datetime
from cascade.domain.network import NETWORK
from cascade.domain.stages import (
    EVENT_INDEX,
    PHYSICAL_GROUPS,
    Checkpoint,
    EventType,
    StageGroup,
    event_sequence,
)
from cascade.explain.explainer import Explanation, build_explanation
from cascade.features.dataset import views_from_frames
from cascade.features.registry import FEATURE_NAMES
from cascade.features.snapshot import ShipmentView, Snapshot, WhatIf, build_snapshot
from cascade.models.artifacts import Bundle
from cascade.models.predictor import PredictionArrays
from cascade.sim.external import ExternalSeries

E = EventType


@dataclass
class Result:
    shipment_id: str
    lane_id: str
    model_version: str
    as_of: float
    checkpoint: str
    planned_delivered: float
    delay_observed: float
    delay_p10: float
    delay_p50: float
    delay_p90: float
    p_late: float
    risk_tier: str
    stage_forecast: dict[str, float]
    flags: dict
    cost_usd: dict[str, float] = field(default_factory=dict)
    promise: dict | None = None
    explanation: Explanation | None = None
    snapshot: Snapshot | None = None
    timing_ms: dict[str, float] = field(default_factory=dict)

    @property
    def eta_p50(self) -> float:
        return self.planned_delivered + self.delay_p50

    def to_json(
        self, audience: str = "ops", include_waterfall: bool = True, top_k: int = 5
    ) -> dict:
        iso = lambda h: to_datetime(h).isoformat().replace("+00:00", "Z")  # noqa: E731
        out = {
            "shipment_id": self.shipment_id,
            "lane_id": self.lane_id,
            "model_version": self.model_version,
            "as_of": iso(self.as_of),
            "checkpoint": self.checkpoint,
            "planned_delivery": iso(self.planned_delivered),
            "eta": {
                "p10": iso(self.planned_delivered + self.delay_p10),
                "p50": iso(self.eta_p50),
                "p90": iso(self.planned_delivered + self.delay_p90),
            },
            "delay_hours": {
                "observed": round(self.delay_observed, 2),
                "p10": round(self.delay_p10, 2),
                "p50": round(self.delay_p50, 2),
                "p90": round(self.delay_p90, 2),
            },
            "p_late": round(self.p_late, 4),
            "risk_tier": self.risk_tier,
            "stage_forecast_hours": {k: round(v, 2) for k, v in self.stage_forecast.items()},
            "cost_usd": {k: round(v, 0) for k, v in self.cost_usd.items()},
            "promise": self.promise,
            "flags": self.flags,
            "timing_ms": {k: round(v, 3) for k, v in self.timing_ms.items()},
        }
        if self.explanation is not None:
            ex = self.explanation
            if audience == "customer":
                out["narrative"] = ex.narratives.get("customer", "")
            else:
                out["narrative"] = ex.narratives.get(audience, ex.narratives.get("ops", ""))
                out["drivers"] = [asdict(d) for d in ex.drivers[:top_k]]
                out["root_cause_group"] = ex.root_cause_group
                if include_waterfall:
                    out["waterfall"] = [asdict(w) for w in ex.waterfall]
                if audience == "analyst":
                    out["group_contributions_h"] = {
                        k: round(v, 3) for k, v in ex.group_contrib.items()
                    }
                    out["feature_contributions_h"] = {
                        k: round(v, 3) for k, v in ex.feature_contrib.items()
                    }
                    out["base_h"] = round(ex.base_h, 3)
        return out


class Engine:
    def __init__(
        self,
        bundle: Bundle,
        ext: ExternalSeries,
        cost_model: CostModel | None = None,
        world: World | None = None,
    ):
        self.bundle = bundle
        self.model = bundle.model
        self.ext = ext
        self.cost_model = cost_model or CostModel()
        self.world = world

    # ---- core prediction ---------------------------------------------------------------
    def _priors(self, view: ShipmentView) -> dict[str, float]:
        from cascade.features.priors import lookup

        lane = NETWORK.lanes[view.lane_id]
        return lookup(self.model.priors, view.lane_id, view.carrier, lane.dest, lane.hub or "NONE")

    def snapshots(
        self,
        items: list[tuple[ShipmentView, float]],
        whatif: WhatIf | None = None,
        ext: ExternalSeries | None = None,
    ) -> list[Snapshot]:
        return [build_snapshot(v, t, ext or self.ext, self._priors(v), whatif) for v, t in items]

    def _arrays(self, snaps: list[Snapshot]) -> tuple[np.ndarray, PredictionArrays]:
        X = np.array([[s.features[n] for n in FEATURE_NAMES] for s in snaps], dtype=float)
        pr = self.model.predict(
            X,
            np.array([s.as_of for s in snaps]),
            np.array([s.planned_delivered for s in snaps]),
            np.array([float(s.context.get("min_remaining_h", 0.0)) for s in snaps]),
        )
        return X, pr

    def predict_many(
        self,
        items: list[tuple[ShipmentView, float]],
        whatif: WhatIf | None = None,
        ext: ExternalSeries | None = None,
        explain: bool = False,
        with_cost: bool = True,
        with_promise: bool = False,
    ) -> list[Result]:
        t0 = time.perf_counter()
        snaps = self.snapshots(items, whatif, ext)
        t1 = time.perf_counter()
        results: list[Result] = []
        try:
            X, pr = self._arrays(snaps)
            if not np.all(np.isfinite([pr.delay_p10, pr.delay_p50, pr.delay_p90, pr.p_late])):
                raise FloatingPointError("non-finite prediction")
            degraded = None
        except Exception as exc:
            X, pr, degraded = None, None, f"model_error: {type(exc).__name__}"
        t2 = time.perf_counter()
        for i, ((view, _), snap) in enumerate(zip(items, snaps, strict=True)):
            if pr is not None:
                res = self._result(view, snap, pr, i)
            else:
                res = self._fallback(view, snap, degraded or "model_error")
            if explain and X is not None and pr is not None:
                te = time.perf_counter()
                contrib = self.model.contributions(X[i : i + 1])[0]
                res.explanation = build_explanation(
                    snap,
                    contrib,
                    res.delay_p10,
                    res.delay_p50,
                    res.delay_p90,
                    res.p_late,
                    view.planned,
                    view.lane_id,
                    view.shipment_id,
                    self.model.late_threshold_h,
                    flags=res.flags,
                )
                res.timing_ms["explain"] = (time.perf_counter() - te) * 1000
            if with_cost:
                res.cost_usd = self.cost(view, res)
            res.timing_ms.update(
                features=(t1 - t0) * 1000 / len(items), inference=(t2 - t1) * 1000 / len(items)
            )
            results.append(res)
        if with_promise:
            for res, (view, t) in zip(results, items, strict=True):
                promise, _ = self.replay_decisions(view, t)
                res.promise = promise
        return results

    def predict(
        self,
        view: ShipmentView,
        as_of: float,
        whatif: WhatIf | None = None,
        explain: bool = True,
        ext: ExternalSeries | None = None,
        with_promise: bool = True,
    ) -> Result:
        t0 = time.perf_counter()
        res = self.predict_many(
            [(view, as_of)], whatif, ext, explain=explain, with_promise=with_promise
        )[0]
        res.timing_ms["total"] = (time.perf_counter() - t0) * 1000
        return res

    def _result(self, view: ShipmentView, snap: Snapshot, pr: PredictionArrays, i: int) -> Result:
        p10, p50, p90 = float(pr.delay_p10[i]), float(pr.delay_p50[i]), float(pr.delay_p90[i])
        stage = (
            {g.value: float(pr.stage_forecast[g][i]) for g in PHYSICAL_GROUPS}
            if pr.stage_forecast
            else {}
        )
        flags = {
            "degraded": False,
            "reason": None,
            "cold_start": False,
            "missing_events": [e.value for e in snap.missing_events],
            "out_of_distribution": bool(abs(p50) > 30 * 24),
        }
        return Result(
            view.shipment_id,
            view.lane_id,
            self.model.version,
            snap.as_of,
            Checkpoint(snap.checkpoint).name,
            snap.planned_delivered,
            snap.current_delay,
            p10,
            p50,
            p90,
            float(pr.p_late[i]),
            risk_tier(p50, self.model.late_threshold_h),
            stage,
            flags,
            snapshot=snap,
        )

    def _fallback(self, view: ShipmentView, snap: Snapshot, reason: str) -> Result:
        """Fallback 1: propagation prior; fallback 2: carry-forward (unknown lane)."""
        try:
            rem = self.model.fallback.predict_one(view.lane_id, snap.checkpoint, snap.current_delay)
            source = "propagation_prior"
        except Exception:
            rem, source = 0.0, "carry_forward"
        p50 = snap.current_delay + rem
        width = max(24.0, abs(rem))
        flags = {
            "degraded": True,
            "reason": f"{reason}; served {source}",
            "cold_start": False,
            "missing_events": [e.value for e in snap.missing_events],
            "out_of_distribution": False,
        }
        p_late = 1.0 / (1.0 + math.exp(-(p50 - self.model.late_threshold_h) / 12.0))
        return Result(
            view.shipment_id,
            view.lane_id,
            self.model.version,
            snap.as_of,
            Checkpoint(snap.checkpoint).name,
            snap.planned_delivered,
            snap.current_delay,
            p50 - width,
            p50,
            p50 + width,
            p_late,
            risk_tier(p50, self.model.late_threshold_h),
            {},
            flags,
            snapshot=snap,
        )

    # ---- decision layer ------------------------------------------------------------------
    def cost(self, view: ShipmentView, res: Result) -> dict[str, float]:
        lane = NETWORK.lanes[view.lane_id]
        p = view.planned
        planned_dwell = p[E.GATE_OUT] - p[E.DISCHARGED]
        sf = res.stage_forecast or {}
        dwell_extra = (
            sf.get("CUSTOMS", 0.0) + 0.5 * sf.get("INLAND", 0.0) + 0.5 * sf.get("PORT", 0.0)
        )
        inland_extra = 0.5 * sf.get("INLAND", 0.0)
        rem50 = res.delay_p50 - res.delay_observed
        out: dict[str, float] = {}
        for q, d in (("p10", res.delay_p10), ("p50", res.delay_p50), ("p90", res.delay_p90)):
            scale = (d - res.delay_observed) / rem50 if abs(rem50) > 1e-6 else 1.0
            scale = max(scale, 0.0)
            c = self.cost_model.cost(
                lane.dest,
                d,
                planned_dwell + scale * max(dwell_extra, 0.0),
                scale * inland_extra,
                view.cargo_value_usd,
            )
            out[q] = c["total"]
            if q == "p50":
                out.update({f"p50_{k}": v for k, v in c.items() if k != "total"})
        return out

    def checkpoint_times(self, view: ShipmentView, as_of: float) -> list[float]:
        seq = event_sequence(NETWORK.lanes[view.lane_id].has_transshipment)
        times = [view.planned[E.GATE_IN_ORIGIN] - 72.0]
        times += [
            view.reported[e] + 1 / 60
            for e in seq[:-1]
            if e in view.reported and view.reported[e] < as_of
        ]
        times = [t for t in times if t <= as_of]
        if not times or times[-1] < as_of:
            times.append(as_of)
        return times

    def replay_decisions(
        self, view: ShipmentView, as_of: float
    ) -> tuple[dict | None, list[AlertEvent]]:
        """Fold the decision rules over the shipment's own history up to as_of."""
        times = self.checkpoint_times(view, as_of)
        results = self.predict_many([(view, t) for t in times], explain=False, with_cost=False)
        promise: PromiseState | None = None
        prev: PredState | None = None
        open_rules: set[str] = set()
        alerts: list[AlertEvent] = []
        seq = event_sequence(NETWORK.lanes[view.lane_id].has_transshipment)
        for r in results:
            eta50 = r.planned_delivered + r.delay_p50
            promise = update_promise(
                promise,
                r.as_of,
                eta50,
                r.planned_delivered + r.delay_p90,
                r.delay_p90 - r.delay_p10,
                r.risk_tier,
            )
            snap = r.snapshot
            gap = 0.0
            if snap and snap.next_event is not None and snap.last_event is not None:
                gap = view.planned[snap.next_event] - view.planned[snap.last_event]
            cur = PredState(
                view.shipment_id,
                r.as_of,
                r.delay_p50,
                r.p_late,
                r.risk_tier,
                promise.promise_h,
                float(snap.context.get("p_miss", 0.0)) if snap else 0.0,
                snap.checkpoint if snap else 0,
                snap.features.get("hours_since_last_event", math.nan) if snap else math.nan,
                gap,
                narrative="",
            )
            new = evaluate_alerts(prev, cur, open_rules)
            alerts.extend(new)
            open_rules |= {a.rule for a in new}
            prev = cur
        del seq
        p = None
        if promise is not None:
            p = {
                "promise_date": to_datetime(promise.promise_h - 1e-6).date().isoformat(),
                "promise_h": promise.promise_h,
                "set_at": to_datetime(promise.set_at).isoformat(),
                "reason": promise.reason,
                "changes": promise.changes,
            }
        return p, alerts

    def advise(
        self, view: ShipmentView, as_of: float, top_k: int = 5
    ) -> tuple[Result, list[Recommendation]]:
        base = self.predict(view, as_of, explain=True, with_promise=False)
        snap = base.snapshot
        assert snap is not None
        actions = candidate_actions(snap, view.docs_complete, view.inland_mode, view.lane_id)

        def evaluate(wi: WhatIf | None) -> tuple[float, float, float]:
            r = base if wi is None else self.predict_many([(view, as_of)], whatif=wi)[0]
            return r.delay_p50, r.p_late, r.cost_usd.get("p50", 0.0)

        return base, rank_actions(actions, evaluate, top_k)

    def scenario_impact(self, scenario: Scenario, items: list[tuple[ShipmentView, float]]) -> dict:
        ext2 = scenario.apply(self.ext)
        base = self.predict_many(items, explain=False)
        alt = self.predict_many(items, ext=ext2, explain=False)
        rows = []
        for b, a, (v, _) in zip(base, alt, items, strict=True):
            rows.append(
                {
                    "shipment_id": v.shipment_id,
                    "lane_id": v.lane_id,
                    "delta_p50_h": a.delay_p50 - b.delay_p50,
                    "p_late_before": b.p_late,
                    "p_late_after": a.p_late,
                    "tier_before": b.risk_tier,
                    "tier_after": a.risk_tier,
                    "delta_cost_usd": a.cost_usd.get("p50", 0) - b.cost_usd.get("p50", 0),
                }
            )
        df = pd.DataFrame(rows)
        affected = df[df.delta_p50_h.abs() > 1.0].sort_values("delta_p50_h", ascending=False)
        return {
            "scenario": asdict(scenario),
            "n_shipments": len(df),
            "n_affected": int(len(affected)),
            "delta_late_count": int(
                (df.tier_after == "LATE").sum() - (df.tier_before == "LATE").sum()
            ),
            "delta_expected_late": float(df.p_late_after.sum() - df.p_late_before.sum()),
            "delta_cost_usd": float(df.delta_cost_usd.sum()),
            "affected": affected.head(50).round(3).to_dict(orient="records"),
        }


# ---- demo world ------------------------------------------------------------------------------
@dataclass
class World:
    """Unseen (test) shipments the demo operates on, with a 'now' that leaves many in transit."""

    shipments: pd.DataFrame
    events: pd.DataFrame
    views: dict[str, ShipmentView]
    actual_delivered: dict[str, float]
    total_delay: dict[str, float]
    now_h: float

    @classmethod
    def from_frames(
        cls, shipments: pd.DataFrame, events: pd.DataFrame, now_h: float | None = None
    ) -> World:
        views = views_from_frames(shipments, events)
        gi = events[events.event == E.GATE_IN_ORIGIN.value].set_index("shipment_id").actual_h
        dl = events[events.event == E.DELIVERED.value].set_index("shipment_id").actual_h
        if now_h is None:
            grid = np.linspace(gi.min(), dl.max(), 200)
            active = [((gi <= t) & (dl > t)).sum() for t in grid]
            now_h = float(grid[int(np.argmax(active))])
        return cls(
            shipments,
            events,
            views,
            dl.to_dict(),
            shipments.set_index("shipment_id").total_delay_h.to_dict(),
            now_h,
        )

    @classmethod
    def load(cls, root: Path) -> World:
        shipments = pd.read_csv(root / "world_shipments.csv")
        events = pd.read_csv(root / "world_events.csv")
        now = float((root / "world_now.txt").read_text())
        return cls.from_frames(shipments, events, now)

    def save(self, root: Path) -> None:
        self.shipments.to_csv(root / "world_shipments.csv", index=False)
        self.events.to_csv(root / "world_events.csv", index=False)
        (root / "world_now.txt").write_text(f"{self.now_h:.4f}")

    def status(self, sid: str, t: float) -> str:
        v = self.views[sid]
        if t >= self.actual_delivered[sid]:
            return "DELIVERED"
        first = min(v.reported.values()) if v.reported else math.inf
        return "IN_TRANSIT" if t >= first else "BOOKED"

    def view_as_of(self, sid: str, t: float) -> ShipmentView:
        """The view an operator would have at time t (only milestones reported by then)."""
        v = self.views[sid]
        rep = {e: ts for e, ts in v.reported.items() if ts <= t}
        return ShipmentView(
            v.shipment_id,
            v.lane_id,
            v.carrier,
            v.commodity_risk,
            v.docs_complete,
            v.inland_mode,
            v.cargo_value_usd,
            v.planned,
            rep,
            v.carrier_edi_tier,
        )

    def checkpoints(self, sid: str) -> list[dict]:
        v = self.views[sid]
        seq = event_sequence(NETWORK.lanes[v.lane_id].has_transshipment)
        out = [{"label": "Booked", "as_of": v.planned[E.GATE_IN_ORIGIN] - 72.0}]
        for e in seq:
            if e in v.reported:
                label = e.value.replace("_", " ").title()
                out.append(
                    {"label": f"After {label}", "as_of": v.reported[e] + 1 / 60, "event": e.value}
                )
        return sorted(
            out,
            key=lambda d: (
                d["as_of"],
                EVENT_INDEX.get(EventType(d["event"]), 0) if "event" in d else -1,
            ),
        )


def group_label(g: str) -> str:
    from cascade.domain.stages import GROUP_LABEL

    return GROUP_LABEL[StageGroup(g)]
