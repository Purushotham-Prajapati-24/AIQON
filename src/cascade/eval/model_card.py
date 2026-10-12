"""Generate docs/ModelCard.md from metrics.json (never hand-edited)."""

from __future__ import annotations

from pathlib import Path

STATUS_ICON = {"met": "✅ met", "partly": "🟡 partly", "unmet": "❌ unmet"}


def _f(x, pct: bool = False, nd: int = 1) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{x:.0%}" if pct else f"{x:.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def _target_value(t: dict) -> str:
    v = t["value"]
    if isinstance(v, dict):  # per-group coverage
        return " / ".join(f"{k} {_f(x, True)}" for k, x in v.items())
    if t["id"] in ("G1", "G4", "G6a"):
        return _f(v, True)
    if t["id"] == "G5":
        return f"{_f(v)} ms"
    if t["id"] == "G7":
        return f"{_f(v, nd=0)} s"
    return _f(v, nd=2 if t["id"] != "G2b" else 3)


def write_model_card(m: dict, path: Path) -> None:
    h, acc, meta = m["headline"], m["accuracy"], m["meta"]
    cov = acc["coverage_detail"]
    rob = m.get("robustness") or {}
    abl = m.get("ablations") or {}
    sel = m["model_selection"]
    att = m["attribution_fidelity"]
    dec = m["decision"]
    sp = m.get("splits", {})
    lam = sel["shrink"]
    weakest = sorted(
        ((int(k), v) for k, v in acc["by_checkpoint_mae"]["cascade"].items()), key=lambda kv: -kv[1]
    )[:3]
    source = (
        f"**The point forecast (P50) is the operator-rulebook projection** (learned weight λ = {lam}: "
        "the learned median correction did not beat the rulebook on temporal validation, so it is "
        "switched off). Learned models contribute the P10–P90 spread, P(late) and the stage forecasts."
        if lam == 0
        else f"The P50 is the operator-rulebook projection plus λ = {lam} × a learned residual correction."
    )
    lines = [
        "# Model Card — CASCADE ETA & Delay-Propagation Model",
        "",
        f"> Auto-generated from `reports/metrics.json` (model v{meta['version']}, data seed {meta['seed']}). Do not edit by hand.",
        "",
        "## Intended use",
        "Decision *support* for logistics planners: final-ETA nowcasts with empirically calibrated ranges,",
        "probability of late delivery, stage-level explanations and advisory interventions for",
        "containerised ocean freight (ocean lanes with a truck or rail final leg).",
        "",
        "**Out of scope:** automated contractual penalties, re-booking without human review, air or",
        "standalone rail moves, and lanes, carriers or ports outside the modelled network (the API rejects",
        "them with 422 rather than guessing).",
        "",
        "## Model",
        f"* {source}",
        "* Operator rulebook: physics-informed projection of every remaining stage (cut-offs, headways,",
        "  berth-queue curve, customs calendars, rail timetables) with coefficients deliberately different",
        "  from the simulator's. LightGBM residual quantile models (P10/P50/P90); a late classifier with",
        "  monotone constraints on registry-declared features (method `basic`); per-stage increment models",
        "  reconciled to the P50.",
        f"* λ = {lam} and the P(late) classifier blend = {sel['late_blend']} are chosen on a temporal",
        "  validation slice (the latest 20% of training voyages), never on the test set.",
        "* Drift-aware CQR per checkpoint group. Post-processing: quantile ordering, then a heuristic ETA",
        f"  floor (remaining stages take ≥ {acc['eta_floor']['frac']} × their planned time; it binds on "
        f"{_f(acc['eta_floor']['binding_share'], True)} of live test snapshots).",
        f"* Explanations: stage bars are labelled by source ({att.get('explainer_source', 'rulebook')}), and",
        "  every P50 satisfies realised + rulebook + learned + ordering + floor = P50 (tested).",
        "",
        "## Data",
        f"Synthetic structural causal simulator, {meta['n_shipments']} shipments, late rate {_f(meta['late_rate'], True)}.",
        "Milestone reports reach the system after a carrier-dependent latency; a snapshot only sees reports",
        "that had *arrived* by its as-of time.",
    ]
    if sp:
        lines.append(
            "Independent units: "
            + "; ".join(
                f"{k.replace('_', ' ')} {v['voyages']} voyages / {v['shipments']} shipments / "
                f"{v['snapshots']} snapshots"
                for k, v in sp.items()
            )
            + "."
        )
    lines += [
        "Out-of-time test = the latest voyages by departure (Q4 peak season, a deliberate distribution shift).",
        "",
        "## Original targets vs results",
        "",
        "| ID | Metric | Original target | Revised gate | Result | Status |",
        "|---|---|---|---|---|---|",
    ]
    for tg in m.get("targets", []):
        lines.append(
            f"| {tg['id']} | {tg['metric']} | {tg['original_target']} | {tg['revised_gate']} | "
            f"{_target_value(tg)} | {STATUS_ICON.get(tg['status'], tg['status'])} |"
        )
    ci_v = h.get("mae_improvement_vs_B1_ci95_voyage", h["mae_improvement_vs_B1_ci95"])
    lines += [
        "",
        "## Performance (out-of-time test)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| MAE final delay — CASCADE / operator rulebook alone | {_f(h['mae_cascade_h'])} h / {_f(h['mae_rulebook_h'])} h |",
        f"| MAE — B1 carry-forward / B2 propagation prior | {_f(h['mae_B1_h'])} h / {_f(h['mae_B2_h'])} h |",
        f"| Improvement vs B1 (95% CI, voyage bootstrap) | {_f(h['mae_improvement_vs_B1'], True)} ({_f(ci_v[0], True)} – {_f(ci_v[1], True)}) |",
        f"| P10–P90 empirical coverage (nominal 80%) | {_f(cov['overall']['coverage'], True)} (n = {cov['overall']['n_voyages']} voyages) |",
        f"| P(late > 24 h): Brier / PR-AUC | {_f(h['brier_tau24'], nd=3)} / {_f(h['pr_auc_tau24'], nd=3)} |",
        f"| Future-delay driver top-1 / top-2 vs cause ledger | {_f(h['attribution_top1'], True)} / {_f(h['attribution_top2'], True)} ({_f(att['ambiguity']['share_margin_lt_6h'], True)} of cases ambiguous: top-two true stages within 6 h) |",
        f"| Propagation factor Spearman vs SCM truth (δ = 12 h) | {_f(h['propagation_spearman'], nd=2)} |",
        f"| Advisor hours-saved Spearman vs SCM truth | {_f(h['advisor_spearman'], nd=2)} |",
        f"| LATE alerts: recall / precision / false-positive rate | {_f(dec['late_alert_recall'], True)} / {_f(dec['late_alert_precision'], True)} / {_f(dec['late_alert_false_positive_rate'], True)} |",
        f"| Alert burden | {_f(dec['alerts_per_100_shipment_days'])} alerts per 100 shipment-days |",
        f"| Latency p95 (in-process predict + explain) | {_f(h['latency_p95_ms'])} ms on {meta.get('environment', {}).get('processor', 'n/a')} |",
        "",
        "## Coverage evidence by checkpoint group",
        "",
        "| Group | Coverage | Width | Snapshots | Shipments | Voyages | 95% CI (voyage bootstrap) |",
        "|---|---|---|---|---|---|---|",
    ]
    for g, d in cov.items():
        lo, hi = d["ci95_voyage"]
        lines.append(
            f"| {g} | {_f(d['coverage'], True)} | {_f(d['width_h'])} h | {d['n_snapshots']} | "
            f"{d['n_shipments']} | {d['n_voyages']} | {_f(lo, True)} – {_f(hi, True)} |"
        )
    lines += [
        "",
        "## Known weaknesses",
        "* Highest error checkpoints: "
        + ", ".join(f"checkpoint {c} (MAE {v:.1f} h)" for c, v in weakest)
        + ". Early checkpoints carry irreducible uncertainty (inspections, missed connections, weather).",
    ]
    drops = rob
    if drops:
        lines.append(
            "* Missing milestones: MAE "
            + ", ".join(f"{float(k):.0%} dropped → {v['mae']:.1f} h" for k, v in drops.items())
            + "."
        )
    if m.get("embargo"):
        e = m["embargo"]
        lines.append(
            f"* Label-time embargo (drop {e['n_train_shipments_dropped']} training shipments delivered "
            f"after the first test departure): MAE {e['mae']:.1f} h, coverage {_f(e['coverage'], True)}."
        )
    if abl:
        lines.append(
            "* Ablations (test MAE): "
            + ", ".join(f"{k} {v['mae']:.1f} h" for k, v in abl.items())
            + f"; no ETA floor {acc['eta_floor']['mae_without_floor']:.1f} h."
        )
    lines += [
        "* Coverage is *empirical* held-out coverage, not a guarantee: the Q4 shift and voyage-correlated",
        "  snapshots break the exchangeability conformal guarantees need.",
        "* Counterfactual what-ifs are model-based (associational); validated against true interventions only on",
        "  synthetic data. Cost figures use illustrative tariffs.",
        "* Synthetic-to-real gap: mechanisms are plausible, coefficients are not calibrated to a real operator.",
        "  Schedules are never revised in the simulator (lateness is always vs the original plan).",
        "",
        "## Ethical & operational considerations",
        "Predictions inform humans; the customer-facing narrative omits internal blame and raw features. Every",
        "response carries the model version, explanation mode (rulebook / learned) and degradation flags. The",
        "prediction ledger is best-effort telemetry (bounded queue; overflow is dropped and counted).",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
