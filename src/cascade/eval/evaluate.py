"""Frozen-split evaluation of a trained CASCADE model.

Everything here is computed on the out-of-time test shipments only. Where the simulator knows
the truth (cause ledger, structural equations) we *measure* explanation, propagation and
advisor fidelity instead of merely displaying them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from cascade.data.splits import Splits
from cascade.decision.engine import Engine, World
from cascade.domain.network import NETWORK
from cascade.domain.stages import CHECKPOINT_GROUP, PHYSICAL_GROUPS, EventType
from cascade.explain.explainer import group_sums, predicted_root_group
from cascade.features.dataset import build_rows
from cascade.features.priors import apply_priors
from cascade.features.registry import FEATURE_NAMES
from cascade.features.snapshot import WhatIf
from cascade.models.baselines import b0_schedule, b1_carry_forward
from cascade.models.predictor import PHYS_COLS, CascadeModel, future_groups
from cascade.models.train import TrainConfig, TrainResult, train
from cascade.sim.generator import SimOutput, resimulate
from cascade.sim.mechanics import Intervention

E = EventType
PROP_EVENTS = (E.DEPART_ORIGIN, E.ARRIVE_TS, E.ARRIVE_DEST_PORT, E.DISCHARGED)


def point(err: np.ndarray) -> dict[str, float]:
    a = np.abs(err)
    return {
        "mae": float(a.mean()),
        "rmse": float(np.sqrt((err**2).mean())),
        "medae": float(np.median(a)),
        "p90ae": float(np.quantile(a, 0.9)),
        "bias": float(err.mean()),
        "n": int(len(err)),
    }


def bootstrap(
    cluster_ids: np.ndarray,
    err_model: np.ndarray,
    err_base: np.ndarray,
    n: int = 1000,
    seed: int = 0,
) -> dict[str, list[float]]:
    """Cluster bootstrap: all rows of a cluster (shipment or voyage) are resampled together.

    Voyages are the independent unit (co-loaded shipments share vessel delays), so the voyage
    bootstrap is the honest CI; the shipment bootstrap is kept for comparison.
    """
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"s": cluster_ids, "m": np.abs(err_model), "b": np.abs(err_base)})
    g = df.groupby("s").agg(m_sum=("m", "sum"), b_sum=("b", "sum"), k=("m", "size"))
    arr = g.to_numpy(float)
    mae_m, mae_b, imp = [], [], []
    for _ in range(n):
        idx = rng.integers(0, len(arr), len(arr))
        s = arr[idx].sum(axis=0)
        mm, mb = s[0] / s[2], s[1] / s[2]
        mae_m.append(mm)
        mae_b.append(mb)
        imp.append(1 - mm / mb)
    q = lambda x: [float(np.quantile(x, 0.025)), float(np.quantile(x, 0.975))]  # noqa: E731
    return {
        "mae_model": q(mae_m),
        "mae_baseline": q(mae_b),
        "improvement": q(imp),
        "n_clusters": int(len(arr)),
    }


def cluster_rate_ci(
    cluster_ids: np.ndarray, hits: np.ndarray, n: int = 1000, seed: int = 0
) -> list[float]:
    """95% CI of a rate (e.g. coverage) resampling whole clusters (voyages)."""
    rng = np.random.default_rng(seed)
    g = (
        pd.DataFrame({"c": cluster_ids, "h": hits.astype(float)})
        .groupby("c")
        .h.agg(["sum", "size"])
    )
    arr = g.to_numpy(float)
    if len(arr) < 2:
        return [math.nan, math.nan]
    rates = []
    for _ in range(n):
        s = arr[rng.integers(0, len(arr), len(arr))].sum(axis=0)
        rates.append(s[0] / s[1])
    return [float(np.quantile(rates, 0.025)), float(np.quantile(rates, 0.975))]


def split_counts(ctx: EvalContext, rows: pd.DataFrame) -> dict:
    """Independent units per split: voyages (the real unit), shipments and snapshot rows."""
    from cascade.data.splits import make_splits

    ships = ctx.sim.shipments
    tr_ships = ships[ships.shipment_id.isin(ctx.splits.train_ids)]
    inner = make_splits(tr_ships, test_frac=0.2, n_folds=5)

    def count(ids) -> dict:
        ids = set(ids)
        s = ships[ships.shipment_id.isin(ids)]
        return {
            "voyages": int(s.voyage_id.nunique()),
            "shipments": int(len(s)),
            "snapshots": int(rows.shipment_id.isin(ids).sum()),
        }

    return {
        "train": count(ctx.splits.train_ids),
        "selection_slice": count(inner.test_ids),  # latest 20% of training voyages (λ, blend, CQR)
        "test": count(ctx.splits.test_ids),
    }


@dataclass
class EvalContext:
    sim: SimOutput
    splits: Splits
    result: TrainResult
    test_rows: pd.DataFrame  # with priors applied
    engine: Engine


def make_context(
    sim: SimOutput, splits: Splits, result: TrainResult, rows: pd.DataFrame, engine: Engine
) -> EvalContext:
    test = apply_priors(rows[rows.shipment_id.isin(splits.test_ids)], result.model.priors)
    return EvalContext(sim, splits, result, test, engine)


def _predict_rows(model: CascadeModel, rows: pd.DataFrame):
    X = rows[list(FEATURE_NAMES)].to_numpy(float)
    return X, model.predict(
        X,
        rows.as_of.to_numpy(float),
        rows.planned_delivered.to_numpy(float),
        (rows.floor_plan_remaining_h.to_numpy(float), rows.floor_elapsed_h.to_numpy(float)),
    )


# ---- accuracy / calibration -------------------------------------------------------------------
def accuracy_metrics(ctx: EvalContext) -> dict:
    m, te = ctx.result.model, ctx.test_rows
    X, pr = _predict_rows(m, te)
    D = te.y_total.to_numpy(float)
    cur = te.current_delay_h.to_numpy(float)
    preds = {
        "cascade": pr.delay_p50,
        "B0_schedule": cur + b0_schedule(te),
        "B1_carry_forward": cur + b1_carry_forward(te),
        "B2_propagation_prior": cur + m.fallback.predict(te),
        "physics_rulebook": cur + te[list(PHYS_COLS)].sum(axis=1).to_numpy(float),
    }
    overall = {k: point(v - D) for k, v in preds.items()}
    cp = te.checkpoint.to_numpy(int)
    by_cp = {
        k: {int(c): point(v[cp == c] - D[cp == c])["mae"] for c in np.unique(cp)}
        for k, v in preds.items()
    }
    sids, vids = te.shipment_id.to_numpy(), te.voyage_id.to_numpy()
    err = {k: v - D for k, v in preds.items()}
    ci = bootstrap(sids, err["cascade"], err["B1_carry_forward"])
    ci_b2 = bootstrap(sids, err["cascade"], err["B2_propagation_prior"])
    ci_voy = {
        "vs_B1": bootstrap(vids, err["cascade"], err["B1_carry_forward"]),
        "vs_B2": bootstrap(vids, err["cascade"], err["B2_propagation_prior"]),
        "vs_rulebook": bootstrap(vids, err["cascade"], err["physics_rulebook"]),
    }
    imp_b1 = 1 - overall["cascade"]["mae"] / overall["B1_carry_forward"]["mae"]
    imp_b2 = 1 - overall["cascade"]["mae"] / overall["B2_propagation_prior"]["mae"]
    imp_rule = 1 - overall["cascade"]["mae"] / overall["physics_rulebook"]["mae"]

    # intervals
    inside = (pr.delay_p10 <= D) & (pr.delay_p90 >= D)
    grp = np.array([CHECKPOINT_GROUP[int(c)] for c in cp])
    coverage = {
        "overall": float(inside.mean()),
        **{g: float(inside[grp == g].mean()) for g in np.unique(grp)},
    }
    width = {
        "overall": float((pr.delay_p90 - pr.delay_p10).mean()),
        **{g: float((pr.delay_p90 - pr.delay_p10)[grp == g].mean()) for g in np.unique(grp)},
    }
    # coverage evidence per group: counts in independent units and a voyage-bootstrap CI
    coverage_detail = {}
    for g in ["overall", *np.unique(grp)]:
        mask = np.ones(len(te), bool) if g == "overall" else grp == g
        coverage_detail[str(g)] = {
            "coverage": float(inside[mask].mean()),
            "width_h": float((pr.delay_p90 - pr.delay_p10)[mask].mean()),
            "n_snapshots": int(mask.sum()),
            "n_shipments": int(pd.unique(sids[mask]).size),
            "n_voyages": int(pd.unique(vids[mask]).size),
            "ci95_voyage": cluster_rate_ci(vids[mask], inside[mask]),
        }

    # the heuristic ETA floor: how often it binds and what it does (no retraining needed)
    live = cp < 9
    no_floor = replace(m, eta_floor_frac=0.0).predict(
        X,
        te.as_of.to_numpy(float),
        te.planned_delivered.to_numpy(float),
        (te.floor_plan_remaining_h.to_numpy(float), te.floor_elapsed_h.to_numpy(float)),
    )
    eta_floor = {
        "frac": m.eta_floor_frac,
        "binding_share": float((np.abs(pr.floor_adjust[live]) > 0.05).mean()),
        "mean_adjust_h": float(pr.floor_adjust[live].mean()),
        "mae_without_floor": float(np.abs(no_floor.delay_p50 - D).mean()),
        "coverage_without_floor": float(
            ((no_floor.delay_p10 <= D) & (no_floor.delay_p90 >= D)).mean()
        ),
    }

    # classification
    cls = {}
    for tau in (24.0, 48.0):
        y = (tau < D).astype(int)
        if tau == m.late_threshold_h:
            p = pr.p_late
        else:
            from cascade.models.predictor import quantile_implied_exceedance

            p = quantile_implied_exceedance(pr.delay_p10, pr.delay_p50, pr.delay_p90, tau)
        entry = {"overall": _cls(y, p)}
        for c in (2, 5):
            mask = cp == c
            if mask.sum() > 5 and 0 < y[mask].mean() < 1:
                entry[f"checkpoint_{c}"] = _cls(y[mask], p[mask])
        cls[f"tau_{int(tau)}"] = entry
    rel = _reliability(te.y_late.to_numpy(int), pr.p_late)
    return {
        "overall": overall,
        "by_checkpoint_mae": by_cp,
        "bootstrap_vs_B1": ci,
        "bootstrap_vs_B2": ci_b2,
        "bootstrap_voyage": ci_voy,
        "improvement_vs_B1": imp_b1,
        "improvement_vs_B2": imp_b2,
        "improvement_vs_rulebook": imp_rule,
        "coverage_p10_p90": coverage,
        "coverage_detail": coverage_detail,
        "interval_width_h": width,
        "eta_floor": eta_floor,
        "classification": cls,
        "reliability": rel,
        "n_test_rows": int(len(te)),
        "n_test_shipments": int(te.shipment_id.nunique()),
        "n_test_voyages": int(te.voyage_id.nunique()),
    }


def _cls(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    out = {"brier": float(brier_score_loss(y, p)), "base_rate": float(y.mean()), "n": int(len(y))}
    if 0 < y.mean() < 1:
        out["pr_auc"] = float(average_precision_score(y, p))
        out["roc_auc"] = float(roc_auc_score(y, p))
    return out


def _reliability(y: np.ndarray, p: np.ndarray, bins: int = 8) -> dict:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    out = {"bin_mean_pred": [], "bin_frac_pos": [], "bin_n": []}
    ece = 0.0
    for b in range(bins):
        mask = idx == b
        if mask.sum():
            out["bin_mean_pred"].append(float(p[mask].mean()))
            out["bin_frac_pos"].append(float(y[mask].mean()))
            out["bin_n"].append(int(mask.sum()))
            ece += mask.mean() * abs(p[mask].mean() - y[mask].mean())
    out["ece"] = float(ece)
    return out


# ---- explanation fidelity -----------------------------------------------------------------------
def attribution_fidelity(ctx: EvalContext, min_h: float = 6.0) -> dict:
    """Does the explanation name the stage that *actually* adds the most future delay?

    Ground truth = future stage group with the largest realised increment (cause ledger), at
    pre-arrival checkpoints with a significant (> min_h) future delay. "shap_*" keys score the
    explanation's stage ranking: at λ = 0 that is the operator rulebook's projection (see
    `explainer_source`). Ambiguous cases (top-two true stages within 6 / 12 h) are reported.
    """
    m, te = ctx.result.model, ctx.test_rows
    mask = te.checkpoint.to_numpy(int) <= 4
    rows = te[mask]
    X, pr = _predict_rows(m, rows)
    contrib = m.contributions(X)
    inc_cols = [f"y_inc_{g.value}" for g in PHYSICAL_GROUPS]
    # lane-prior explainer: most frequent true root group per (lane, checkpoint) in training rows
    tr = ctx.result.train_rows
    tr_true = _true_roots(tr, inc_cols, min_h)
    lane_mode = (
        pd.DataFrame({"lane": tr.lane_id.values, "cp": tr.checkpoint.values, "t": tr_true})
        .query("t != 'NONE'")
        .groupby(["lane", "cp"])
        .t.agg(lambda s: s.value_counts().index[0])
        .to_dict()
    )
    rng = np.random.default_rng(0)
    true = _true_roots(rows, inc_cols, min_h)
    recs = []
    for i in range(len(rows)):
        if true[i] == "NONE":
            continue
        cp, has_ts = int(rows.checkpoint.iloc[i]), bool(rows.has_transshipment.iloc[i])
        fut = [g.value for g in future_groups(cp, has_ts)]
        sums = group_sums(contrib[i])
        ranked = sorted(fut, key=lambda g: -sums[_sg(g)])
        shap_top = predicted_root_group(contrib[i], cp, has_ts, remaining_p50=1e9)
        stage_top = (
            max(fut, key=lambda g: pr.stage_forecast[_sg(g)][i]) if pr.stage_forecast else shap_top
        )
        major = float(rows[[f"y_inc_{true[i]}"]].iloc[i, 0]) > 24.0
        inc = np.sort(rows[[f"y_inc_{g}" for g in fut]].iloc[i].to_numpy(float))[::-1]
        margin = float(inc[0] - inc[1]) if len(inc) > 1 else math.inf
        recs.append(
            {
                "true": true[i],
                "checkpoint": cp,
                "margin_h": margin,
                "major": major,
                "shap_top1": shap_top == true[i],
                "shap_top2": true[i] in ranked[:2],
                "stage_forecast_top1": stage_top == true[i],
                "lane_prior_top1": lane_mode.get((rows.lane_id.iloc[i], cp), "NONE") == true[i],
                "random_top1": fut[int(rng.integers(len(fut)))] == true[i],
                "shap_pred": shap_top,
            }
        )
    df = pd.DataFrame(recs)
    acc = {
        c: float(df[c].mean())
        for c in ["shap_top1", "shap_top2", "stage_forecast_top1", "lane_prior_top1", "random_top1"]
    }
    acc["shap_top1_major_delays"] = (
        float(df[df.major].shap_top1.mean()) if df.major.any() else math.nan
    )
    acc["lift_vs_lane_prior"] = acc["shap_top1"] - acc["lane_prior_top1"]
    clear = df[df.margin_h >= 6.0]
    acc["shap_top1_unambiguous"] = float(clear.shap_top1.mean()) if len(clear) else math.nan
    # rows = true group, columns = predicted group
    confusion = pd.crosstab(df.true, df.shap_pred)
    return {
        "n": int(len(df)),
        "n_major": int(df.major.sum()),
        "n_shipments": int(rows.shipment_id[[t != "NONE" for t in true]].nunique()),
        "explainer_source": m.explanation_mode,  # what "shap_*" ranks: rulebook at λ = 0
        "accuracy": acc,
        "ambiguity": {
            "share_margin_lt_6h": float((df.margin_h < 6.0).mean()),
            "share_margin_lt_12h": float((df.margin_h < 12.0).mean()),
            "n_unambiguous": int(len(clear)),
        },
        "by_checkpoint": {
            int(c): {
                "n": int(len(g)),
                "top1": float(g.shap_top1.mean()),
                "top2": float(g.shap_top2.mean()),
                "lane_prior_top1": float(g.lane_prior_top1.mean()),
            }
            for c, g in df.groupby("checkpoint")
        },
        "true_root_distribution": df.true.value_counts().to_dict(),
        "confusion_true_rows": {
            str(tr): {str(pc): int(n) for pc, n in r.items()} for tr, r in confusion.iterrows()
        },
    }


def _sg(name: str):
    from cascade.domain.stages import StageGroup

    return StageGroup(name)


def _true_roots(rows: pd.DataFrame, inc_cols: list[str], min_h: float) -> np.ndarray:
    vals = rows[inc_cols].to_numpy(float)
    best = vals.argmax(axis=1)
    names = np.array([c.replace("y_inc_", "") for c in inc_cols])
    return np.where(vals.max(axis=1) > min_h, names[best], "NONE")


# ---- propagation & advisor fidelity ------------------------------------------------------------
PROP_DELTAS = (1.0, 6.0, 12.0, 24.0)


def propagation_fidelity(
    ctx: EvalContext, deltas: tuple[float, ...] = PROP_DELTAS, max_ship: int = 80
) -> dict:
    """Model propagation factor (dP50 / d delay at stage i) vs the SCM's true factor.

    Logistics is discontinuous (a missed sailing costs a whole headway), so Φ is measured for
    several shock sizes and split by whether the shipment was near the hub connection cut-off.
    """
    eng, sim = ctx.engine, ctx.sim
    views = eng.world.views if eng.world else {}
    recs = []
    for sid in ctx.splits.test_ids[:max_ship]:
        v = views.get(sid)
        if v is None:
            continue
        base_true = resimulate(sim, sid).actual[E.DELIVERED]
        for e in PROP_EVENTS:
            if e not in v.reported:
                continue
            t = v.known_at(e) + 1 / 60
            r0 = eng.predict_many([(v, t)], with_cost=False)[0]
            buffer = float(r0.snapshot.context.get("buffer_rem", 500.0)) if r0.snapshot else 500.0
            condition = (
                "no_pending_connection"
                if buffer >= 400
                else ("near_cutoff" if buffer < 6.0 else "comfortable_buffer")
            )
            for d in deltas:
                r1 = eng.predict_many([(v, t)], whatif=WhatIf(delay_shift_h=d), with_cost=False)[0]
                alt = resimulate(sim, sid, Intervention(inject={e: d})).actual[E.DELIVERED]
                recs.append(
                    {
                        "shipment_id": sid,
                        "event": e.value,
                        "lane_id": v.lane_id,
                        "delta_h": d,
                        "condition": condition,
                        "phi_hat": (r1.delay_p50 - r0.delay_p50) / d,
                        "phi_true": (alt - base_true) / d,
                    }
                )
    df = pd.DataFrame(recs)
    if df.empty:
        return {"n": 0}

    def summary(g: pd.DataFrame) -> dict:
        return {
            "n": int(len(g)),
            "spearman": float(spearmanr(g.phi_hat, g.phi_true).statistic)
            if len(g) > 3 and g.phi_hat.nunique() > 1 and g.phi_true.nunique() > 1
            else math.nan,
            "mae": float((g.phi_hat - g.phi_true).abs().mean()),
            "phi_true_median": float(g.phi_true.median()),
            "phi_true_iqr": [float(g.phi_true.quantile(0.25)), float(g.phi_true.quantile(0.75))],
            "phi_hat_median": float(g.phi_hat.median()),
        }

    ref = df[df.delta_h == 12.0]  # the headline shock size (kept for continuity)
    agg = ref.groupby(["lane_id", "event"])
    matrix = agg[["phi_hat", "phi_true"]].mean().round(3).join(agg.size().rename("n")).reset_index()
    return {
        "delta_h": 12.0,
        "n": int(len(ref)),
        "spearman": summary(ref)["spearman"],
        "mae": summary(ref)["mae"],
        "by_event": ref.groupby("event")[["phi_hat", "phi_true"]]
        .mean()
        .round(3)
        .to_dict(orient="index"),
        "by_delta": {str(d): summary(g) for d, g in df.groupby("delta_h")},
        "by_condition": {c: summary(g) for c, g in ref.groupby("condition")},
        "by_condition_delta": {
            f"{c}|{d}": summary(g) for (c, d), g in df.groupby(["condition", "delta_h"])
        },
        "matrix": matrix.to_dict(orient="records"),
    }


ACTION_TO_SCM = {
    "prefile_docs": lambda lane: Intervention(docs_complete=True),
    "priority_berth": lambda lane: Intervention(dest_rho=NETWORK.ports[lane.dest].base_util),
    "hub_priority": lambda lane: Intervention(hub_priority=True),
    "weekend_customs": lambda lane: Intervention(customs_weekend=True),
    "rail_to_truck": lambda lane: Intervention(inland_mode="truck"),
}


def advisor_fidelity(ctx: EvalContext, max_ship: int = 62) -> dict:
    """Model-estimated hours saved per action vs hours saved by the true SCM intervention."""
    eng, sim = ctx.engine, ctx.sim
    recs = []
    for sid in ctx.splits.test_ids[:max_ship]:
        v = eng.world.views[sid]
        dep = E.DEPART_ORIGIN
        t = (v.known_at(dep) if dep in v.reported else v.planned[dep]) + 1 / 60
        base, recs_model = eng.advise(v, t, top_k=10)
        truth0 = resimulate(sim, sid).actual[E.DELIVERED]
        lane = NETWORK.lanes[v.lane_id]
        for r in recs_model:
            alt = resimulate(sim, sid, ACTION_TO_SCM[r.action_id](lane)).actual[E.DELIVERED]
            recs.append(
                {
                    "shipment_id": sid,
                    "action": r.action_id,
                    "model_hours_saved": r.hours_saved,
                    "true_hours_saved": truth0 - alt,
                }
            )
    df = pd.DataFrame(recs)
    if df.empty:
        return {"n": 0}
    rho = (
        spearmanr(df.model_hours_saved, df.true_hours_saved).statistic if len(df) > 3 else math.nan
    )
    sign = float(((df.model_hours_saved > 1) == (df.true_hours_saved > 1)).mean())
    return {
        "n": int(len(df)),
        "spearman": float(rho),
        "sign_agreement": sign,
        "by_action": df.groupby("action")[["model_hours_saved", "true_hours_saved"]]
        .mean()
        .round(2)
        .to_dict(orient="index"),
    }


# ---- decision metrics (replay) ----------------------------------------------------------------
def decision_metrics(ctx: EvalContext) -> dict:
    eng = ctx.engine
    w = eng.world
    rows = []
    for sid in ctx.splits.test_ids:
        v = w.views[sid]
        end = w.actual_delivered[sid] - 1 / 60
        times = eng.checkpoint_times(v, end)
        res = eng.predict_many([(v, t) for t in times], with_cost=False)
        raw_days = [math.floor((r.planned_delivered + r.delay_p50) / 24) for r in res]
        raw_changes = int(sum(1 for a, b in zip(raw_days, raw_days[1:], strict=False) if a != b))
        raw_rev = _reversals(raw_days)
        promise, alerts = eng.replay_decisions(v, end)
        # promise in effect at each checkpoint: re-fold incrementally
        from cascade.decision.promise import update_promise

        ps, hits, prom_days = None, [], []
        for r in res:
            ps = update_promise(
                ps,
                r.as_of,
                r.planned_delivered + r.delay_p50,
                r.planned_delivered + r.delay_p90,
                r.delay_p90 - r.delay_p10,
                r.risk_tier,
            )
            hits.append(w.actual_delivered[sid] <= ps.promise_h)
            prom_days.append(ps.promise_h)
        late = w.total_delay[sid] > eng.model.late_threshold_h
        late_alerts = [a for a in alerts if a.rule == "TIER_ESCALATION_LATE"]
        first_late = min((a.created_at for a in late_alerts), default=math.nan)
        start = v.planned[E.GATE_IN_ORIGIN] - 72.0  # replay starts at booking
        active_days = max(w.actual_delivered[sid] - start, 1.0) / 24.0
        rows.append(
            {
                "shipment_id": sid,
                "late": late,
                "raw_changes": raw_changes,
                "raw_reversals": raw_rev,
                "promise_reversals": _reversals(prom_days),
                "promise_changes": promise["changes"] if promise else 0,
                "promise_hit_rate": float(np.mean(hits)),
                "has_late_alert": bool(late_alerts),
                "lead_h": v.planned[E.DELIVERED] - first_late if late_alerts else math.nan,
                "lead_to_actual_h": w.actual_delivered[sid] - first_late
                if late_alerts
                else math.nan,
                "n_alerts": len(alerts),
                "active_days": active_days,
            }
        )
    df = pd.DataFrame(rows)
    late = df[df.late]
    return {
        "promise_changes_per_shipment": float(df.promise_changes.mean()),
        "raw_eta_day_changes_per_shipment": float(df.raw_changes.mean()),
        "promise_flip_ratio": float(df.promise_changes.sum() / max(df.raw_changes.sum(), 1)),
        "promise_hit_rate": float(df.promise_hit_rate.mean()),
        "raw_eta_reversals_per_shipment": float(df.raw_reversals.mean()),
        "promise_reversals_per_shipment": float(df.promise_reversals.mean()),
        "late_alert_recall": float(late.has_late_alert.mean()) if len(late) else math.nan,
        "late_alert_precision": float(df[df.has_late_alert].late.mean())
        if df.has_late_alert.any()
        else math.nan,
        "alert_lead_ge_48h_share": float((late.lead_h >= 48).mean()) if len(late) else math.nan,
        "median_alert_lead_h": float(late.lead_h.median()) if len(late) else math.nan,
        "alerts_per_shipment": float(df.n_alerts.mean()),
        # alert burden and false alarms (what an ops team actually experiences)
        "late_alert_false_positive_rate": float(df[~df.late].has_late_alert.mean())
        if (~df.late).any()
        else math.nan,
        "alerts_per_100_shipment_days": float(100 * df.n_alerts.sum() / df.active_days.sum()),
        "late_alerts_per_100_shipment_days": float(
            100 * df.has_late_alert.sum() / df.active_days.sum()
        ),
        # lead time measured to the *actual* delivery (not the planned date), with its spread
        "lead_to_actual_h_p10_p50_p90": [
            float(late.lead_to_actual_h.quantile(q)) for q in (0.1, 0.5, 0.9)
        ]
        if late.has_late_alert.any()
        else [math.nan] * 3,
        "lead_to_planned_h_p10_p50_p90": [float(late.lead_h.quantile(q)) for q in (0.1, 0.5, 0.9)]
        if late.has_late_alert.any()
        else [math.nan] * 3,
        "n_late": int(len(late)),
        "n_on_time": int((~df.late).sum()),
        "note": "LATE alert = first TIER_ESCALATION_LATE in a replay from booking; thresholds are "
        "fixed rules (not tuned on validation).",
    }


def _reversals(xs: list[float]) -> int:
    """Direction flips (later -> earlier -> later) — the flip-flopping customers hate."""
    deltas = [b - a for a, b in zip(xs, xs[1:], strict=False) if b != a]
    return int(sum(1 for a, b in zip(deltas, deltas[1:], strict=False) if (a > 0) != (b > 0)))


# ---- robustness, ablations, importance --------------------------------------------------------
def robustness(ctx: EvalContext, rates=(0.0, 0.1, 0.3, 0.5), seed: int = 0) -> dict:
    sim, m = ctx.sim, ctx.result.model
    test_s = sim.shipments[sim.shipments.shipment_id.isin(ctx.splits.test_ids)]
    test_e = sim.events[sim.events.shipment_id.isin(ctx.splits.test_ids)]
    out = {}
    for r in rates:
        rng = np.random.default_rng(seed)
        ev = test_e.copy()
        drop = (ev.event != E.DELIVERED.value) & ev.reported & (rng.random(len(ev)) < r)
        ev.loc[drop, "reported"] = False
        ev.loc[drop, "reported_h"] = np.nan
        if "available_h" in ev.columns:
            ev.loc[drop, "available_h"] = np.nan
        rows = build_rows(test_s, test_e, sim.ledger, sim.external, seed=1, events_override=ev)
        rows = apply_priors(rows, m.priors)
        _, pr = _predict_rows(m, rows)
        D = rows.y_total.to_numpy(float)
        out[str(r)] = {
            "mae": float(np.abs(pr.delay_p50 - D).mean()),
            "mae_B1": float(np.abs(rows.current_delay_h.to_numpy(float) - D).mean()),
            "coverage": float(((pr.delay_p10 <= D) & (pr.delay_p90 >= D)).mean()),
        }
    return out


ABLATIONS = {
    "no_propagation_features": tuple(
        n
        for n in FEATURE_NAMES
        if n.startswith("proj_inc")
        or n
        in (
            "ts_buffer_remaining_h",
            "p_miss_connection_prior",
            "queue_excess_h",
            "berth_window_miss_risk",
            "congestion_x_lateness",
            "customs_calendar_shift_h",
            "customs_weekend_risk",
            "rail_alignment_h",
            "remaining_absorption_h",
            "projected_hub_arrival_delay_h",
            "projected_arrival_delay_h",
        )
    ),
    "no_priors": tuple(n for n in FEATURE_NAMES if n.startswith("prior_")),
    "no_data_quality": (
        "carrier_edi_tier",
        "n_missing_past",
        "completeness_ratio",
        "hours_since_last_event",
    ),
}


def ablations(ctx: EvalContext, rows: pd.DataFrame, base_cfg: TrainConfig) -> dict:
    out = {"full": ctx.result}
    res = {}
    for name, feats in ABLATIONS.items():
        mode = "remaining" if name == "no_propagation_features" else base_cfg.target_mode
        cfg = TrainConfig(
            **{
                **base_cfg.__dict__,
                "exclude_features": feats,
                "target_mode": mode,
                "stage_models": False,
            }
        )
        r = train(rows, ctx.sim.shipments, ctx.sim.ledger, ctx.splits, cfg)
        te = apply_priors(rows[rows.shipment_id.isin(ctx.splits.test_ids)], r.model.priors)
        X = te[list(FEATURE_NAMES)].to_numpy(float).copy()
        for f in feats:
            X[:, FEATURE_NAMES.index(f)] = np.nan
        pr = r.model.predict(
            X,
            te.as_of.to_numpy(float),
            te.planned_delivered.to_numpy(float),
            (te.floor_plan_remaining_h.to_numpy(float), te.floor_elapsed_h.to_numpy(float)),
        )
        D = te.y_total.to_numpy(float)
        res[name] = {
            "mae": float(np.abs(pr.delay_p50 - D).mean()),
            "coverage": float(((pr.delay_p10 <= D) & (pr.delay_p90 >= D)).mean()),
        }
    del out
    return res


def embargo_check(ctx: EvalContext, rows: pd.DataFrame, base_cfg: TrainConfig) -> dict:
    """Retrain without training shipments delivered after the first test departure.

    The test cut is by departure, so some training labels are only realised after test
    shipments have started: a live system would not have known them yet.
    """
    from cascade.data.splits import Splits

    ships = ctx.sim.shipments.set_index("shipment_id")
    cutoff = float(ships.loc[ctx.splits.test_ids, "planned_DEPART_ORIGIN"].min())
    keep = [s for s in ctx.splits.train_ids if ships.at[s, "actual_DELIVERED"] <= cutoff]
    emb = Splits(
        keep, ctx.splits.test_ids, {s: ctx.splits.fold_of[s] for s in keep}, ctx.splits.n_folds
    )
    r = train(rows, ctx.sim.shipments, ctx.sim.ledger, emb, base_cfg)
    te = apply_priors(rows[rows.shipment_id.isin(ctx.splits.test_ids)], r.model.priors)
    _, pr = _predict_rows(r.model, te)
    D = te.y_total.to_numpy(float)
    return {
        "cutoff_h": cutoff,
        "n_train_shipments_dropped": int(len(ctx.splits.train_ids) - len(keep)),
        "n_train_shipments_kept": int(len(keep)),
        "mae": float(np.abs(pr.delay_p50 - D).mean()),
        "coverage": float(((pr.delay_p10 <= D) & (pr.delay_p90 >= D)).mean()),
        "shrink": r.model.shrink,
    }


def group_importance(ctx: EvalContext) -> dict[str, float]:
    X, _ = _predict_rows(ctx.result.model, ctx.test_rows)
    c = ctx.result.model.contributions(X)
    sums = np.array([[v for v in group_sums(row).values()] for row in c])
    from cascade.domain.stages import StageGroup

    return {g.value: float(np.abs(sums[:, i]).mean()) for i, g in enumerate(StageGroup)}


def run_all(ctx: EvalContext, rows: pd.DataFrame, cfg: TrainConfig, fast: bool = False) -> dict:
    out = {
        "accuracy": accuracy_metrics(ctx),
        "attribution_fidelity": attribution_fidelity(ctx),
        "propagation_fidelity": propagation_fidelity(ctx),
        "advisor_fidelity": advisor_fidelity(ctx),
        "decision": decision_metrics(ctx),
        "group_importance": group_importance(ctx),
        "model_selection": {
            "shrink": ctx.result.model.shrink,
            "late_blend": ctx.result.model.late_blend,
            **{k: {str(kk): vv for kk, vv in v.items()} for k, v in ctx.result.selection.items()},
        },
    }
    out["splits"] = split_counts(ctx, rows)
    if not fast:
        out["robustness"] = robustness(ctx)
        out["embargo"] = embargo_check(ctx, rows, cfg)
        out["ablations"] = ablations(ctx, rows, cfg)
    return out


__all__ = ["EvalContext", "World", "make_context", "run_all"]
