"""Generate docs/ModelCard.md from metrics.json (never hand-edited)."""

from __future__ import annotations

from pathlib import Path


def _f(x, pct: bool = False, nd: int = 1) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{x:.0%}" if pct else f"{x:.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def write_model_card(m: dict, path: Path) -> None:
    h, acc, meta = m["headline"], m["accuracy"], m["meta"]
    cov = acc["coverage_p10_p90"]
    rob = m.get("robustness") or {}
    abl = m.get("ablations") or {}
    weakest = sorted(
        ((int(k), v) for k, v in acc["by_checkpoint_mae"]["cascade"].items()), key=lambda kv: -kv[1]
    )[:3]
    lines = [
        "# Model Card — CASCADE ETA & Delay-Propagation Model",
        "",
        f"> Auto-generated from `reports/metrics.json` (model v{meta['version']}, data seed {meta['seed']}). Do not edit by hand.",
        "",
        "## Intended use",
        "Decision *support* for logistics planners: final-ETA nowcasts with calibrated ranges, probability of",
        "late delivery, stage-level explanations and advisory interventions for containerised ocean freight.",
        "",
        "**Out of scope:** automated contractual penalties, re-booking without human review, air/rail-only moves,",
        "lanes and ports absent from the training network (served with fallbacks and a `cold_start` flag).",
        "",
        "## Model",
        "* Physics-informed *operator rulebook* projection of every remaining stage (cut-offs, headways, berth-queue",
        "  curve, customs calendars, rail timetables) **plus** LightGBM residual quantile models (P10/P50/P90),",
        "  a monotone-constrained late classifier, per-stage increment models reconciled to the P50.",
        f"* Learned-correction trust (shrink) = **{m['model_selection']['shrink']}**, classifier blend = "
        f"**{m['model_selection']['late_blend']}**, both chosen on a temporal validation slice (never the test set).",
        "* Conformalized quantile regression per checkpoint group; guardrails: quantile ordering, ETA ≥ as-of.",
        "",
        "## Data",
        f"Synthetic structural causal simulator, {meta['n_shipments']} shipments, late rate {_f(meta['late_rate'], True)};",
        "out-of-time test = latest ~20% of voyages (Q4 peak season, a deliberate distribution shift).",
        "",
        "## Performance (out-of-time test)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| MAE final delay — CASCADE | {_f(h['mae_cascade_h'])} h |",
        f"| MAE — B1 carry-forward / B2 propagation prior | {_f(h['mae_B1_h'])} h / {_f(h['mae_B2_h'])} h |",
        f"| Improvement vs B1 (95% CI) | {_f(h['mae_improvement_vs_B1'], True)} ({_f(h['mae_improvement_vs_B1_ci95'][0], True)} – {_f(h['mae_improvement_vs_B1_ci95'][1], True)}) |",
        f"| P10–P90 coverage (target 80%) | {_f(cov['overall'], True)} |",
        f"| P(late > 24 h): Brier / PR-AUC | {_f(h['brier_tau24'], nd=3)} / {_f(h['pr_auc_tau24'], nd=3)} |",
        f"| Root-cause stage accuracy vs cause ledger | {_f(h['attribution_top1'], True)} |",
        f"| Propagation factor Spearman vs SCM truth | {_f(h['propagation_spearman'], nd=2)} |",
        f"| Advisor hours-saved Spearman vs SCM truth | {_f(h['advisor_spearman'], nd=2)} |",
        f"| Late shipments alerted ≥ 48 h ahead | {_f(h['alert_lead_ge_48h_share'], True)} |",
        "",
        "## Known weaknesses",
        "* Highest error checkpoints: "
        + ", ".join(f"checkpoint {c} (MAE {v:.1f} h)" for c, v in weakest)
        + ".",
        "  Early checkpoints carry irreducible uncertainty (inspections, missed connections, weather).",
        "* Coverage by group: "
        + ", ".join(f"{k} {_f(v, True)}" for k, v in cov.items() if k != "overall")
        + ".",
    ]
    if rob:
        lines.append(
            "* Missing milestones: MAE "
            + ", ".join(f"{float(k):.0%} dropped → {v['mae']:.1f} h" for k, v in rob.items())
            + "."
        )
    if abl:
        lines.append(
            "* Ablations (test MAE): "
            + ", ".join(f"{k} {v['mae']:.1f} h" for k, v in abl.items())
            + "."
        )
    lines += [
        "* Counterfactual what-ifs are model-based (associational); validated against true interventions only on",
        "  synthetic data. Cost figures use illustrative tariffs.",
        "* Synthetic-to-real gap: mechanisms are plausible, coefficients are not calibrated to a real operator.",
        "",
        "## Ethical & operational considerations",
        "Predictions inform humans; the customer-facing narrative omits internal blame and raw features. Every",
        "response carries model version and degradation flags; the prediction ledger enables live accuracy audits.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
