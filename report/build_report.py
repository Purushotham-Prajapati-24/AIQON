"""Build the CASCADE technical report (2-3 pages, A4) from the evaluation outputs.

Every number in the report is read from ``reports/metrics.json`` (seed-42 run),
``reports/seeds.json`` (5-seed stability study) or ``configs/sim.yaml`` (simulator assumptions).
Nothing is hand-typed. Re-run this script after every ``cascade all``.

    python report/build_report.py              # HTML + PDF (headless Edge) + README results table
    python report/build_report.py --no-pdf     # HTML only
    python report/build_report.py --author "Jane Doe"
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
OUT_DIR = ROOT / "report"
HTML_OUT = OUT_DIR / "report.html"
PDF_OUT = OUT_DIR / "CASCADE_Technical_Report.pdf"
MAX_PAGES = 3  # the Aiqon brief asks for a 2–3 page report
README = ROOT / "README.md"
# Any Chromium-based browser can print the PDF. Checked in order; $CASCADE_PDF_BROWSER wins.
BROWSER_PATHS = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
]
BROWSER_COMMANDS = [
    "msedge",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
]

CHECKPOINT_LABEL = {
    "0": "Booked",
    "1": "Gate-in",
    "2": "Departed",
    "3": "At hub",
    "4": "Left hub",
    "5": "Arrived",
    "6": "Discharged",
    "7": "Cleared",
    "8": "Gate-out",
}
GROUP_LABEL = {
    "pre_departure": "Pre-departure",
    "at_sea": "At sea",
    "at_port": "At port",
    "post_customs": "Post-customs",
    "overall": "Overall",
}
EVENT_LABEL = {
    "DEPART_ORIGIN": "Origin departure",
    "ARRIVE_TS": "Hub arrival",
    "ARRIVE_DEST_PORT": "Destination arrival",
    "DISCHARGED": "Discharge",
}
ACTION_LABEL = {
    "hub_priority": "Hub priority loading",
    "prefile_docs": "Pre-file customs docs",
    "priority_berth": "Priority berth",
    "rail_to_truck": "Rail → truck",
    "weekend_customs": "Weekend customs",
}


# ---- formatting helpers ------------------------------------------------------------------------
def pct(x: float, d: int = 0) -> str:
    return f"{100 * x:.{d}f}%"


def pp(x: float, d: int = 0) -> str:
    return f"{100 * x:+.{d}f} pp"


def hrs(x: float, d: int = 1) -> str:
    return f"{x:.{d}f} h"


def num(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}"


def ms(x: float) -> str:
    return f"{x:.1f} ms"


def days(h: float) -> str:
    return f"{h / 24:.1f} days"


def esc(s: str) -> str:
    return html.escape(str(s))


def mean_sd(seeds: dict, key: str, fmt, sd_fmt=None) -> str:
    s = seeds["summary"][key]
    return f"{fmt(s['mean'])} ± {(sd_fmt or fmt)(s['sd'])}"


def lift(x: float) -> str:
    return f"{100 * x:+.0f} pp"


def lift_sd(x: float) -> str:
    return f"{100 * x:.0f} pp"


# Okabe-Ito
BLUE, VERMILLION, GREY = "#0072B2", "#D55E00", "#999999"


def waterfall_figure(example: dict, out: Path) -> Path:
    """Compact, print-legible waterfall drawn from metrics.example.waterfall (same numbers as the
    pipeline's reports/figures/waterfall_example.png, shorter labels for a half-page column)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # a 0 h learned-baseline row (λ = 0) carries no information; drop it
    steps = [
        s
        for s in example["waterfall"]
        if not (s["kind"] == "baseline" and abs(float(s["hours"])) < 0.05)
    ]
    labels, lefts, widths, colors, hatches = [], [], [], [], []
    run = 0.0
    for s in steps:
        hrs_ = float(s["hours"])
        kind = s["kind"]
        if kind == "realized":
            label = "Realised so far"
            if "missing" in s["label"]:
                label += " (gaps)"
        else:
            label = s["label"]
        if kind == "total":
            lefts.append(0.0)
            widths.append(hrs_)
        else:
            lefts.append(run if hrs_ >= 0 else run + hrs_)
            widths.append(abs(hrs_))
            run += hrs_
        labels.append(label)
        colors.append(
            {"realized": VERMILLION, "baseline": GREY, "total": "#1a1a1a"}.get(kind, BLUE)
        )
        hatches.append("///" if kind == "forecast" else "")
    fig, ax = plt.subplots(figsize=(3.9, 0.32 * len(steps) + 0.3), dpi=220)
    y = range(len(steps))[::-1]
    for yi, x0, w, c, hh, s in zip(y, lefts, widths, colors, hatches, steps, strict=True):
        ax.barh(
            yi, max(w, 0.6), left=x0, color=c, hatch=hh, edgecolor="white" if hh else c, height=0.7
        )
        ax.text(x0 + max(w, 0.6) + 2, yi, f"{float(s['hours']):+.0f} h", va="center", fontsize=6.5)
    ax.set_yticks(list(y), labels, fontsize=7)
    ax.tick_params(axis="x", labelsize=6.5)
    ax.set_xlabel("Hours vs plan (solid = realised, hatched = forecast)", fontsize=6.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", color="#e5e5e5", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(lefts[i] + widths[i] for i in range(len(steps))) * 1.15)
    fig.tight_layout(pad=0.3)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out


def load_inputs() -> tuple[dict, dict | None, dict]:
    metrics = json.loads((REPORTS / "metrics.json").read_text(encoding="utf-8"))
    seeds_path = REPORTS / "seeds.json"
    seeds = json.loads(seeds_path.read_text(encoding="utf-8")) if seeds_path.exists() else None
    sim = yaml.safe_load((ROOT / "configs" / "sim.yaml").read_text(encoding="utf-8")) or {}
    return metrics, seeds, sim


# ---- README results table ----------------------------------------------------------------------
def results_markdown(m: dict, seeds: dict | None) -> str:
    h, a = m["headline"], m["accuracy"]
    ci = h.get("mae_improvement_vs_B1_ci95_voyage", h["mae_improvement_vs_B1_ci95"])
    seed_col = seeds is not None
    rows = [
        (
            "ETA error (MAE, final delay)",
            f"{hrs(h['mae_cascade_h'])} vs {hrs(h['mae_B1_h'])} carry-forward",
            mean_sd(seeds, "mae_cascade_h", hrs) if seed_col else "",
        ),
        (
            "MAE improvement vs carry-forward (B1)",
            f"**{pct(h['mae_improvement_vs_B1'])}** (95% CI {pct(ci[0])}–{pct(ci[1])}, by voyage)",
            mean_sd(seeds, "mae_improvement_vs_B1", pct) if seed_col else "",
        ),
        (
            "MAE improvement vs propagation prior (B2)",
            pct(h["mae_improvement_vs_B2"]),
            mean_sd(seeds, "mae_improvement_vs_B2", pct) if seed_col else "",
        ),
        (
            # λ = 0 makes the P50 the rulebook; show it so the gain is attributed honestly.
            "MAE of the operator rulebook alone (no ML) · learned weight λ",
            f"{hrs(a['overall']['physics_rulebook']['mae'])} · λ = {m['model_selection']['shrink']}",
            (
                f"{mean_sd(seeds, 'mae_rulebook_h', hrs)} · λ = "
                + "/".join(f"{r.get('shrink', '?')}" for r in seeds["runs"])
            )
            if seed_col and "mae_rulebook_h" in seeds["summary"]
            else "",
        ),
        (
            "P10–P90 interval coverage (target 80%)",
            pct(h["coverage_p10_p90_overall"]),
            mean_sd(seeds, "coverage_p10_p90_overall", pct) if seed_col else "",
        ),
        (
            "P(late > 24 h): Brier · PR-AUC",
            f"{num(h['brier_tau24'], 3)} · {num(h['pr_auc_tau24'])}",
            f"{mean_sd(seeds, 'brier_tau24', lambda x: num(x, 3))} · {mean_sd(seeds, 'pr_auc_tau24', num)}"
            if seed_col
            else "",
        ),
        (
            "Future-delay driver (rulebook stage projection at λ = 0) vs cause ledger: top-1 · top-2",
            f"{pct(h['attribution_top1'])} · {pct(h['attribution_top2'])}",
            f"{mean_sd(seeds, 'attribution_top1', pct)} · {mean_sd(seeds, 'attribution_top2', pct)}"
            if seed_col
            else "",
        ),
        (
            "Root-cause lift vs lane-history explainer",
            pp(h["attribution_lift_vs_lane_prior"]),
            mean_sd(seeds, "attribution_lift_vs_lane_prior", lift, lift_sd) if seed_col else "",
        ),
        (
            "Propagation factor vs re-simulated truth (Spearman)",
            num(h["propagation_spearman"]),
            mean_sd(seeds, "propagation_spearman", num) if seed_col else "",
        ),
        (
            "P50 identity violations (observed + rulebook + learned + adjustments = P50)",
            f"{h['identity_violations']} / {m['checks']['identity_checked']}",
            "",
        ),
        (
            "Latency p95 (predict + explain)",
            ms(h["latency_p95_ms"]),
            mean_sd(seeds, "latency_p95_ms", ms) if seed_col else "",
        ),
    ]
    head = (
        f"| Metric (out-of-time test, {a.get('n_test_voyages', '?')} voyages / "
        f"{a['n_test_shipments']} shipments / {a['n_test_rows']} "
        f"snapshots) | Seed {m['meta']['seed']} | "
        + (f"{len(seeds['runs'])}-seed mean ± sd |" if seed_col else "|")
    )
    sep = "|---|---|" + ("---|" if seed_col else "")
    body = "\n".join(f"| {r[0]} | {r[1]} |" + (f" {r[2]} |" if seed_col else "") for r in rows)
    note = (
        "\n\n<sub>Generated by `report/build_report.py` from `reports/metrics.json`"
        + (" and `reports/seeds.json`" if seed_col else "")
        + f" (model v{m['meta']['version']}). Do not edit by hand.</sub>"
    )
    return f"{head}\n{sep}\n{body}{note}"


def update_readme(m: dict, seeds: dict | None) -> bool:
    if not README.exists():
        return False
    text = README.read_text(encoding="utf-8")
    start, end = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
    if start not in text or end not in text:
        return False
    new = re.sub(
        re.escape(start) + r".*?" + re.escape(end),
        lambda _: f"{start}\n{results_markdown(m, seeds)}\n{end}",
        text,
        flags=re.S,
    )
    if new != text:
        README.write_text(new, encoding="utf-8")
    return True


# ---- HTML report -------------------------------------------------------------------------------
CSS = """
@page { size: A4; margin: 10mm 12mm 9mm 12mm; }
:root { --blue:#0072B2; --orange:#E69F00; --green:#009E73; --verm:#D55E00; --sky:#56B4E9;
        --ink:#1a1a1a; --muted:#555; --rule:#d0d0d0; --band:#eef5fb; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: Arial, "Liberation Sans", "Helvetica Neue", Helvetica, sans-serif; font-size: 10pt;
       line-height: 1.23; color: var(--ink); margin: 0; background: #fff; }
h1 { font-size: 15.5pt; margin: 0 0 1mm; color: var(--blue); letter-spacing: -0.2px; }
.sub { color: var(--muted); font-size: 9pt; margin-bottom: 2.5mm; }
h2 { font-size: 11.5pt; margin: 2.6mm 0 1.1mm; color: var(--blue);
     border-bottom: 1.2px solid var(--blue); padding-bottom: 0.6mm; break-after: avoid; }
h3 { font-size: 10pt; margin: 2mm 0 0.8mm; break-after: avoid; }
p { margin: 0 0 1.3mm; text-align: justify; hyphens: auto; }
ul { margin: 0 0 1.5mm; padding-left: 4.5mm; }
li { margin: 0 0 0.6mm; }
code, .mono { font-family: Consolas, "Liberation Mono", Menlo, monospace; font-size: 9pt; }
.tldr { background: var(--band); border-left: 3px solid var(--blue); padding: 1.8mm 2.6mm;
        margin: 0 0 2mm; }
.tldr p { margin: 0; }
.defs { display: grid; grid-template-columns: auto 1fr; column-gap: 3mm; row-gap: 0.4mm;
        font-size: 9.4pt; margin: 1mm 0 1.6mm; padding: 1.4mm 2.6mm; border: 1px solid var(--rule); }
.defs .mono { white-space: nowrap; }
table { border-collapse: collapse; width: 100%; font-size: 8.7pt; margin: 0.6mm 0 1.4mm;
        break-inside: avoid; }
th, td { padding: 0.55mm 1.4mm; border-bottom: 1px solid var(--rule); text-align: left;
         vertical-align: top; }
th { background: #f3f3f3; font-weight: 600; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr.hl td { background: var(--band); font-weight: 600; }
caption { caption-side: top; text-align: left; font-weight: 600; font-size: 9pt;
          padding-bottom: 0.6mm; }
.two { display: grid; grid-template-columns: 1fr 1fr; column-gap: 4mm; align-items: start; }
.two > * { min-width: 0; }
figure { margin: 1mm 0 2mm; break-inside: avoid; text-align: center; }
figure img { max-width: 100%; }
figcaption { font-size: 8.6pt; color: var(--muted); text-align: left; margin-top: 0.6mm; }
.quote { font-size: 9.2pt; border-left: 3px solid var(--orange); padding: 1.2mm 2.4mm;
         background: #fff8ec; margin: 1mm 0 1.8mm; }
.pass { color: var(--green); font-weight: 600; }
.warn { color: var(--verm); font-weight: 600; }
.small { font-size: 8.6pt; color: var(--muted); }
.pb { break-before: page; }
"""


def build_html(m: dict, seeds: dict | None, sim: dict, author: str) -> str:
    a, h, meta = m["accuracy"], m["headline"], m["meta"]
    ov = a["overall"]
    cls24 = a["classification"]["tau_24"]
    att = m["attribution_fidelity"]
    prop = m["propagation_fidelity"]
    adv = m["advisor_fidelity"]
    dec = m["decision"]
    lead_seeds = ((seeds or {}).get("summary") or {}).get("alert_lead_ge_48h_share")
    seed_lead = (
        f" ({pct(lead_seeds['mean'])} ± {pct(lead_seeds['sd'])} over seeds)"
        if isinstance(lead_seeds, dict)
        else ""
    )
    sel = m["model_selection"]
    ex = m["example"]
    chk = m["checks"]
    tc = meta["train_config"]
    bv = a.get("bootstrap_voyage", {})
    ci_b1 = bv.get("vs_B1", a["bootstrap_vs_B1"])["improvement"]
    ci_b2 = bv.get("vs_B2", a["bootstrap_vs_B2"])["improvement"]
    ci_rule = bv.get("vs_rulebook", {}).get("improvement", [float("nan")] * 2)
    env = m["meta"].get("environment", {})
    missed = [tg for tg in m.get("targets", []) if tg["status"] != "met"]
    sens_txt = ""
    sens_path = REPORTS / "sensitivity.json"
    if sens_path.exists():  # worlds whose mechanics differ from the rulebook's assumptions
        res = json.loads(sens_path.read_text(encoding="utf-8"))["results"]
        alt = {k: v for k, v in res.items() if k != "baseline"}
        if alt:
            imp = [v["mae_improvement_vs_B1"] for v in alt.values()]
            ratio = [v["mae_ratio_cascade_vs_rulebook"] for v in alt.values()]
            cov = [v["coverage_p10_p90_overall"] for v in alt.values()]
            sens_txt = (
                f" <b>Wrong-assumption sensitivity</b> ({len(alt)} worlds with changed simulator "
                f"mechanics): gain vs carry-forward {pct(min(imp))}–{pct(max(imp))}, CASCADE/rulebook "
                f"MAE ratio "
                f"{num(min(ratio))}–{num(max(ratio))}, coverage {pct(min(cov))}–{pct(max(cov))}."
            )
            best = min(alt.items(), key=lambda kv: kv[1]["mae_ratio_cascade_vs_rulebook"])
            if best[1]["mae_ratio_cascade_vs_rulebook"] < 0.95:
                b = best[1]
                sens_txt += (
                    f" Where the rulebook is wrong (<i>{best[0].replace('_', ' ')}</i>) "
                    f"validation picks λ = {b['shrink']}: {hrs(b['mae_cascade_h'])} vs "
                    f"{hrs(b['mae_rulebook_h'])}."
                )
    late_h = sim.get("late_threshold_h", tc.get("late_threshold_h"))
    nominal = 1 - tc["alpha"]
    fig = (REPORTS / "figures").as_uri()

    # Table 1: baselines
    models = [
        ("B0_schedule", "B0 Schedule (assume on plan)"),
        ("B1_carry_forward", "B1 Carry-forward (current delay persists)"),
        ("B2_propagation_prior", "B2 Propagation prior (lane-level)"),
        ("physics_rulebook", "Operator rulebook projection (no ML)"),
        ("cascade", "CASCADE (rulebook + residual GBM, P50)"),
    ]
    t1 = "".join(
        f"<tr{' class="hl"' if k == 'cascade' else ''}><td>{esc(lbl)}</td>"
        f"<td class=n>{num(ov[k]['mae'], 1)}</td><td class=n>{num(ov[k]['rmse'], 1)}</td>"
        f"<td class=n>{num(ov[k]['medae'], 1)}</td><td class=n>{num(ov[k]['p90ae'], 1)}</td>"
        f"<td class=n>{num(ov[k]['bias'], 1)}</td></tr>"
        for k, lbl in models
    )

    cov = a["coverage_p10_p90"]
    width = a["interval_width_h"]
    t_cov = "".join(
        f"<tr{' class="hl"' if g == 'overall' else ''}><td>{GROUP_LABEL.get(g, g)}</td>"
        f"<td class=n>{pct(cov[g])}</td><td class=n>{days(width[g]) if width[g] >= 48 else hrs(width[g], 0)}</td></tr>"
        for g in ["pre_departure", "at_sea", "at_port", "post_customs", "overall"]
    )

    t_prop = "".join(
        f"<tr><td>{EVENT_LABEL.get(ev, ev)}</td><td class=n>{num(v['phi_hat'])}</td>"
        f"<td class=n>{num(v['phi_true'])}</td></tr>"
        for ev, v in prop["by_event"].items()
    )
    t_adv = "".join(
        f"<tr><td>{ACTION_LABEL.get(k, k)}</td><td class=n>{hrs(v['model_hours_saved'], 0)}</td>"
        f"<td class=n>{hrs(v['true_hours_saved'], 0)}</td></tr>"
        for k, v in adv["by_action"].items()
    )

    abl = m.get("ablations", {})
    abl_rows = [("Full model", ov["cascade"]["mae"], cov["overall"])] + [
        (lbl, abl[k]["mae"], abl[k]["coverage"])
        for k, lbl in [
            ("no_propagation_features", "− propagation / projection features"),
            ("no_priors", "− route / port / carrier priors"),
            ("no_data_quality", "− data-quality (missingness) flags"),
        ]
        if k in abl
    ]
    t_abl = "".join(
        f"<tr><td>{esc(lbl)}</td><td class=n>{hrs(mae)}</td><td class=n>{pct(c)}</td></tr>"
        for lbl, mae, c in abl_rows
    )
    rob = m.get("robustness", {})
    t_rob = "".join(
        f"<tr><td class=n>{pct(float(k))}</td><td class=n>{hrs(v['mae'])}</td>"
        f"<td class=n>{hrs(v['mae_B1'])}</td><td class=n>{pct(v['coverage'])}</td></tr>"
        for k, v in rob.items()
    )

    # Table: seeds
    if seeds:
        s_rows = [
            ("MAE vs carry-forward", "mae_improvement_vs_B1", pct),
            ("MAE vs propagation prior", "mae_improvement_vs_B2", pct),
            ("P10–P90 coverage", "coverage_p10_p90_overall", pct),
            ("Brier P(late)", "brier_tau24", lambda x: num(x, 3)),
            ("PR-AUC P(late)", "pr_auc_tau24", num),
            ("Root cause top-1", "attribution_top1", pct),
            ("Lift vs lane-history", "attribution_lift_vs_lane_prior", lift),
            ("Propagation Spearman", "propagation_spearman", num),
            ("Advisor Spearman", "advisor_spearman", num),
        ]
        t_seed = "".join(
            f"<tr><td>{lbl}</td><td class=n>{f(h[k])}</td><td class=n>{mean_sd(seeds, k, f, lift_sd if f is lift else None)}</td></tr>"
            for lbl, k, f in s_rows
        )
        seed_list = seeds["seeds"].replace(",", ", ")
        n_seeds = len(seeds["runs"])
        best = max(seeds["runs"], key=lambda r: r["mae_improvement_vs_B1"])
        seed42_best = abs(best["mae_improvement_vs_B1"] - h["mae_improvement_vs_B1"]) < 1e-9
        seed_html = f"""
<table><caption>Table 6 · Stability over {n_seeds} simulator seeds ({seed_list})</caption>
<tr><th>Metric</th><th class=n>Seed {meta["seed"]}</th><th class=n>Mean ± sd</th></tr>{t_seed}</table>
<p class=small>Seed {meta["seed"]} is {"the most favourable" if seed42_best else "one"} of the {n_seeds} seeds for the MAE gain; the mean is the fairer
estimate. Weakest claim: root-cause lift over the lane-history explainer ({mean_sd(seeds, "attribution_lift_vs_lane_prior", lift, lift_sd)}),
positive on average but not reliably large.</p>"""
    else:
        seed_html = (
            "<p class=small>Multi-seed study not available (run <code>cascade seeds</code>).</p>"
        )

    shrink_grid = ", ".join(str(k) for k in sel["shrink_mae"])
    blend_grid = ", ".join(str(k) for k in sel["late_blend_brier"])
    if sel.get("late_stack"):
        late_model_html = (
            "P(late) stacks the empirical residual distribution around the rulebook with the "
            "monotone classifier (logistic, fit out-of-fold)."
        )
        late_note_html = f"Out-of-fold Brier of the P(late) stack: {num(sel['late_brier_oof'], 3)}."
    else:
        late_model_html = (
            "P(late) blends a monotone classifier + isotonic calibration with the quantile-implied "
            f"probability (weight from {{{blend_grid}}}; selected {sel['late_blend']})."
        )
        late_note_html = (
            "On temporal validation the blend of classifier and quantile-implied P(late) lowered "
            f"Brier from {num(sel['late_blend_brier']['0.0'], 3)} (quantile-only) and "
            f"{num(sel['late_blend_brier']['1.0'], 3)} (classifier-only) to "
            f"{num(sel['late_blend_brier'][str(sel['late_blend'])], 3)}."
        )
    drivers = ex["drivers"]
    top = drivers[0]
    narrative = ex["narrative"]
    dh = ex["delay_hours"]
    gen = dt.date.today().isoformat()
    author_html = f"{esc(author)} · " if author else ""
    by_cp = a["by_checkpoint_mae"]
    cp_first, cp_last = "0", max(by_cp["cascade"], key=int)
    gates = m.get("gates", {})
    worst_action = max(
        adv["by_action"],
        key=lambda k: abs(
            adv["by_action"][k]["model_hours_saved"] - adv["by_action"][k]["true_hours_saved"]
        ),
    )
    phi_max = max(prop["by_event"], key=lambda k: prop["by_event"][k]["phi_true"])
    phi_min = min(prop["by_event"], key=lambda k: prop["by_event"][k]["phi_true"])
    wf_uri = waterfall_figure(ex, OUT_DIR / "figures" / "waterfall_compact.png").as_uri()
    n_pass = sum(1 for g in gates.values() if g.get("pass"))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>CASCADE Technical Report</title>
<style>{CSS}</style></head><body>

<h1>CASCADE: stage-aware shipment ETA, delay propagation and explanation</h1>
<div class=sub>{author_html}Aiqon AI Internship take-home · model v{esc(meta["version"])}
· seed {meta["seed"]} · out-of-time test (Q4 peak) · {n_pass}/{len(gates)} quality gates pass · generated {gen}</div>

<div class=tldr><p><b>Answer first.</b> On a held-out, later-in-time test season, CASCADE's ETA error (MAE of the P50 final delay) is
<b>{hrs(h["mae_cascade_h"])}</b>, which is <b>{pct(h["mae_improvement_vs_B1"])} better than carry-forward</b>
(95% CI {pct(ci_b1[0])}–{pct(ci_b1[1])}) and {pct(h["mae_improvement_vs_B2"])} better than a lane-level
propagation prior. Its P10–P90 ranges cover {pct(h["coverage_p10_p90_overall"])} of outcomes (target {pct(nominal)}),
P(late&nbsp;&gt;&nbsp;{late_h}&nbsp;h) has Brier {num(h["brier_tau24"], 3)} and PR-AUC {num(h["pr_auc_tau24"])},
and every P50 is shown as realised delay plus a per-stage projection of the delay still to come.
Because a structural causal simulator records a <i>cause ledger</i> for every hour of delay, we can score that explanation:
the stage projected to add the most future delay is the ledger's top future stage {pct(h["attribution_top1"])} of the time (top-2: {pct(h["attribution_top2"])}).
Caveat: the point forecast {"<b>and</b> these stage explanations come" if sel["shrink"] == 0 else "comes mostly"} from a mechanistic operator-rulebook projection; the learned median correction did not beat it out-of-time, so validation set its weight to {sel["shrink"]}. The ML contributes the P10–P90 spread, P(late) and the stage forecasts.</p></div>

<h2>1 · Problem and definitions</h2>
<p>A container shipment moves through a fixed <b>stage graph</b>: gate-in → origin departure → (hub arrival → hub
departure) → destination arrival → discharge → customs release → gate-out → delivery. Direct lanes skip the hub.
Each milestone <i>e<sub>k</sub></i> has a planned and an actual time. All quantities are in hours, and positive means late.</p>
<div class=defs>
<span class=mono>delay(e<sub>k</sub>)</span><span>= actual(e<sub>k</sub>) − planned(e<sub>k</sub>)</span>
<span class=mono>Δ<sub>k</sub></span><span>= delay(e<sub>k</sub>) − delay(e<sub>k−1</sub>): the stage increment (positive adds delay, negative absorbs it)</span>
<span class=mono>D</span><span>= delay(DELIVERED) = Σ<sub>k</sub> Δ<sub>k</sub>: total delay; the model predicts the <i>remaining</i> part R(t) = D − delay<sub>obs</sub>(t)</span>
<span class=mono>ETA<sub>q</sub>(t)</span><span>= planned delivery + observed delay so far + predicted remaining delay R̂<sub>q</sub>(t), for q ∈ {{P10, P50, P90}}</span>
<span class=mono>late</span><span>= 1[D &gt; {late_h} h]; P(late) is reported with every ETA</span>
</div>
<p>Predictions are <b>as-of nowcasts</b>: at each of {len(by_cp["cascade"])} checkpoints (booked … gate-out) the model sees only
what was known at that instant, including <i>forecasts</i> (not realised values) of future congestion and weather.</p>

<h2>2 · Data and ground truth</h2>
<p>Instead of adding random noise to timestamps, we built a <b>structural causal model (SCM)</b> of {meta["n_shipments"]} shipments
on lanes between real Asian origins, hubs (Singapore, Colombo, Jebel Ali, Tanjung Pelepas) and European / US destinations. Shipments share
voyages, so errors are correlated. Each mechanism below writes signed hours into a <b>cause ledger</b>
<span class=mono>(shipment, stage, cause, hours)</span>. Within a stage the ledger sums exactly to Δ<sub>k</sub>, and over all stages to D.
The true root cause is the stage with the largest positive Δ<sub>k</sub>. Late rate in this run: {pct(meta["late_rate"])}.</p>
<table><caption>Table 1 · Logistics mechanics in the simulator (each produces ledger entries)</caption>
<tr><th>Stage</th><th>Real-world behaviour modelled</th></tr>
<tr><td>Origin</td><td>Carrier reliability (latent), origin congestion and storms delay departure (shared by the voyage).</td></tr>
<tr><td>Ocean</td><td>Weather slows the vessel; the vessel <b>recovers</b> part of an incoming delay by speeding up (negative Δ, capped).</td></tr>
<tr><td>Transshipment</td><td>Hub handling (longer when congested) must finish before the connection cut-off. A <b>missed connection waits for the next sailing</b> (weekly or twice-weekly headway), which is the main cascade amplifier.</td></tr>
<tr><td>Destination port</td><td>Kingman-like <b>berth queue</b> W ∝ ρ/(1−ρ); a vessel arriving late <b>loses its berth window</b> and waits longer (congestion × lateness interaction).</td></tr>
<tr><td>Customs</td><td>Inspection probability rises with commodity risk and incomplete documents; release is shifted to the next <b>business slot</b> (weekends, local holidays).</td></tr>
<tr><td>Inland</td><td>Rail leaves at fixed times, so a missed <b>cut-off</b> waits for the next train; trucks need appointments; consignee <b>receiving windows</b>.</td></tr>
</table>
<p><b>External factors.</b> Daily port congestion ρ(t) (base + seasonality incl. the Q4 peak and the Lunar New Year backlog, plus AR(1) noise) and regional
weather with storm episodes and the monsoon. For future dates the model only sees noisy <i>as-of forecasts</i> whose error grows with the horizon.
<b>Missingness is typed:</b> <i>structural</i> (no hub on direct lanes → sentinel, never NaN); <i>MCAR</i> reporting gaps
(rate {pct(sim.get("mcar_rate", 0))}); <i>MNAR</i> gaps from poor carrier EDI feeds (up to {pct(sim.get("edi_tier3_rate", 0))}) and congested terminals that
fail to report discharge. A report reaches the system after a carrier-dependent latency (median 0.5–6 h by feed quality), and delivery is always observed.
<b>Split:</b> out-of-time. The last voyages by departure, which fall in the Q4 peak, form the test set ({a["n_test_shipments"]} shipments, {a["n_test_rows"]} as-of snapshots), so the test season is shifted relative to training.
<b>Assumptions:</b> fixed schedules and headways per lane; costs from a configurable tariff; no strikes or blank sailings; one container per shipment.</p>

<h2>3 · Approach</h2>
<ul>
<li><b>As-of checkpoints.</b> Each shipment expands into one row per milestone. Features use only milestone reports that had <i>arrived</i> by the as-of time (an event that happened but was reported later is invisible), and leakage is property-tested.</li>
<li><b>Operator rulebook vs truth.</b> A physics-style projection of every <i>remaining</i> stage (cut-offs, headways, Kingman queue, customs calendars, rail timetables) from forecast congestion and weather, with coefficients <b>deliberately different from the simulator's</b>, so the model cannot "know the simulator".</li>
<li><b>Propagation features.</b> These include projected hub buffer versus cut-off, congestion × current lateness, days to the next business slot, rail cut-off slack, and missingness flags that carry signal (EDI tier, gaps so far).</li>
<li><b>Residual quantile GBM with temporal shrinkage.</b> LightGBM models P10/P50/P90 of the residual on top of the rulebook ({tc["n_estimators"]} trees, {tc["num_leaves"]} leaves). The learned median correction is blended in with weight λ ∈ {{{shrink_grid}}}, chosen on the latest training voyages{" and out-of-fold" if "shrink_mae_oof" in sel else ""}. <b>λ = {sel["shrink"]} was selected</b>, so the median comes from the rulebook, and ML contributes uncertainty, P(late) and stage forecasts{"; the band uses the learned quantiles directly" if "late_stack" in sel else ""}.</li>
<li><b>Drift-aware CQR and P(late).</b> Conformalised quantile regression per checkpoint group (offset = max(out-of-fold, temporal-slice)) protects coverage under the seasonal shift. {late_model_html}</li>
<li><b>Explanations.</b> Stage bar = rulebook projected increment + λ × exact TreeSHAP of the residual model (<code>pred_contrib</code>){"; at λ = 0 the bars, and the attribution score, are the <b>rulebook alone</b>" if sel["shrink"] == 0 else ""}. Realised delay + stage bars + a floor/ordering adjustment = P50; templates write ops/customer/analyst narratives. Future-stage attribution is inherently noisy, so we report top-2 and lift, not just top-1.</li>
<li><b>Decision layer.</b> Promise ETA with hysteresis, alerts, cost-of-delay, an intervention advisor (model re-run under a fixed action menu), a scenario radar and a prediction ledger; FastAPI with a fallback chain (lane propagation prior → carry-forward) and a Streamlit control tower.</li>
</ul>

<h2>4 · Results</h2>
<table><caption>Table 2 · Final-delay error on the out-of-time test, all {a["n_test_rows"]} snapshots (hours; bias = mean of prediction − actual)</caption>
<tr><th>Model</th><th class=n>MAE</th><th class=n>RMSE</th><th class=n>MedAE</th><th class=n>P90 AE</th><th class=n>Bias</th></tr>{t1}</table>
<p>MAE improvement, bootstrapped over the {a.get("n_test_voyages", "?")} test <i>voyages</i> (the independent unit): <b>{pct(h["mae_improvement_vs_B1"])}</b> vs carry-forward (95% CI {pct(ci_b1[0])}–{pct(ci_b1[1])}) and
<b>{pct(h["mae_improvement_vs_B2"])}</b> vs the propagation prior (CI {pct(ci_b2[0])}–{pct(ci_b2[1])}). Against the <b>rulebook alone</b> CASCADE is {pct(h.get("mae_improvement_vs_rulebook", float("nan")), 1)}
(CI {pct(ci_rule[0], 1)} to {pct(ci_rule[1], 1)}): with λ = {sel["shrink"]} the gain over the baselines is the rulebook's. The negative bias reflects the Q4 shift.
{("<b>Original targets not (fully) met:</b> " + "; ".join(f"{tg['id']} {tg['metric'].lower()} ({tg['status']})" for tg in missed) + " — full table in the model card.") if missed else ""}</p>

<figure><img src="{fig}/convergence.png" style="width:60%">
<figcaption>Figure 1 · ETA convergence. The error of the final-delay forecast falls as milestones arrive (MAE {hrs(by_cp["cascade"][cp_first])} at booking →
{hrs(by_cp["cascade"][cp_last])} at gate-out). The spike at the hub is the missed-connection cliff: it is resolved only once the hub departure is known.</figcaption></figure>

<div class=two>
<div>
<table><caption>Table 3 · Uncertainty and P(late)</caption>
<tr><th>Checkpoint group</th><th class=n>P10–P90 coverage</th><th class=n>Mean width</th></tr>{t_cov}</table>
<table><tr><th>P(late &gt; {late_h} h)</th><th class=n>Brier</th><th class=n>PR-AUC</th><th class=n>ROC-AUC</th></tr>
<tr><td>All snapshots (base rate {pct(cls24["overall"]["base_rate"])})</td><td class=n>{num(cls24["overall"]["brier"], 3)}</td><td class=n>{num(cls24["overall"]["pr_auc"])}</td><td class=n>{num(cls24["overall"]["roc_auc"])}</td></tr>
<tr><td>After destination arrival</td><td class=n>{num(cls24["checkpoint_5"]["brier"], 3)}</td><td class=n>{num(cls24["checkpoint_5"]["pr_auc"])}</td><td class=n>{num(cls24["checkpoint_5"]["roc_auc"])}</td></tr>
</table>
<p class=small>Calibration ECE {num(a["reliability"]["ece"], 3)}. {late_note_html}</p>
</div>
<div>
<table><caption>Table 4 · Explanation fidelity vs simulator ground truth</caption>
<tr><th>Root-cause stage ({att["n"]} pre-arrival snapshots)</th><th class=n>Accuracy</th></tr>
<tr class=hl><td>CASCADE stage ranking (rulebook at λ = 0), top-1 · top-2</td><td class=n>{pct(att["accuracy"]["shap_top1"])} · {pct(att["accuracy"]["shap_top2"])}</td></tr>
<tr><td>… top-1 on major delays only</td><td class=n>{pct(att["accuracy"]["shap_top1_major_delays"])}</td></tr>
<tr><td>Reconciled stage forecast, top-1</td><td class=n>{pct(att["accuracy"]["stage_forecast_top1"])}</td></tr>
<tr><td>Lane-history explainer, top-1</td><td class=n>{pct(att["accuracy"]["lane_prior_top1"])}</td></tr>
<tr><td>Random future stage</td><td class=n>{pct(att["accuracy"]["random_top1"])}</td></tr>
</table>
<table><tr><th>Propagation factor Φ = ΔD / Δstage</th><th class=n>Model</th><th class=n>True</th></tr>{t_prop}</table>
<p class=small>Φ<sub>true</sub> comes from re-running the SCM with the same random state after injecting +{num(prop["delta_h"], 0)} h at a stage.
Spearman over {prop["n"]} shipment × stage pairs: {num(prop["spearman"])}. True Φ is largest at {EVENT_LABEL.get(phi_max, phi_max)} ({num(prop["by_event"][phi_max]["phi_true"])}){" (the next-sailing effect)" if phi_max == "ARRIVE_TS" else ""} and smallest at {EVENT_LABEL.get(phi_min, phi_min)} ({num(prop["by_event"][phi_min]["phi_true"])}); Φ &gt; 1 means the delay amplifies downstream.</p>
</div>
</div>

<div class=two>
<div>
<table><caption>Table 5 · Ablations and robustness to missing milestones</caption>
<tr><th>Variant</th><th class=n>MAE</th><th class=n>Coverage</th></tr>{t_abl}</table>
<table><tr><th>Extra milestones dropped</th><th class=n>MAE</th><th class=n>MAE B1</th><th class=n>Coverage</th></tr>{t_rob}</table>
<p class=small>Only removing propagation features hurts; under heavy missingness CASCADE stays ahead of carry-forward.{sens_txt}</p>
</div>
<div>{seed_html}</div>
</div>

<div class=two>
<div>
<table><caption>Table 7 · Advisor: hours saved, model vs SCM truth</caption>
<tr><th>Action</th><th class=n>Model</th><th class=n>True</th></tr>{t_adv}</table>
</div>
<div>
<p class=small style="margin-top:1mm">Advisor ranking vs truth: Spearman {num(adv["spearman"])}, direction agreement {pct(adv["sign_agreement"])} (n = {adv["n"]}).
Largest miss: {ACTION_LABEL.get(worst_action, worst_action)} ({hrs(adv["by_action"][worst_action]["model_hours_saved"], 0)} predicted vs {hrs(adv["by_action"][worst_action]["true_hours_saved"], 0)} true).
<b>Decision replay:</b> late-alert recall {pct(dec["late_alert_recall"])}, precision {pct(dec["late_alert_precision"])}, false-positive rate {pct(dec.get("late_alert_false_positive_rate", float("nan")))};
{num(dec.get("alerts_per_100_shipment_days", float("nan")), 1)} alerts per 100 shipment-days; median lead {hrs(dec.get("lead_to_actual_h_p10_p50_p90", [0, float("nan"), 0])[1] / 24, 1).replace(" h", " d")} before <i>actual</i> delivery. The promise date holds in {pct(dec["promise_hit_rate"])} of cases, with {num(dec["promise_reversals_per_shipment"])}
reversals per shipment vs {num(dec["raw_eta_reversals_per_shipment"])} for the raw ETA.
<b>Latency:</b> predict + explain p50 {ms(chk["latency_p50_ms"])}, p95 {ms(chk["latency_p95_ms"])} (in-process, sequential, {env.get("cpu_count", "?")}-thread laptop CPU, LightGBM {env.get("lightgbm", "?")}).</p>
</div>
</div>

<h3>Worked example: {esc(ex["shipment_id"])} ({esc(ex["lane_id"])}), as of {esc(ex["as_of"][:16].replace("T", " "))} UTC</h3>
<div class=two>
<figure style="margin-top:0"><img src="{wf_uri}" style="width:100%">
<figcaption>Figure 2 · Additive waterfall: realised delay (solid) + projected stage contributions (hatched) = P50 ({hrs(dh["p50"], 0)}).</figcaption></figure>
<div>
<div class=quote>{esc(narrative)}</div>
<p class=small>The main driver ({esc(top["label"])}, {hrs(top["contribution_h"], 0)}) is a projected missed connection: one more sailing headway.
The cause ledger agrees: the true root cause is <b>{esc(ex["root_cause_group"].title())}</b>. Expected cost of delay ${ex["cost_usd"]["p50"]:,.0f} (P90 ${ex["cost_usd"]["p90"]:,.0f}).</p>
</div>
</div>

<h2>5 · Limitations and next steps</h2>
<p><b>Synthetic</b> mechanisms, not fitted to real data (revisions and feed corrections are simulated); <b>associational</b> counterfactuals (advisor Spearman {num(adv["spearman"])} vs true interventions); <b>small n</b>: {a["n_test_shipments"]} test shipments in {a.get("n_test_voyages", "?")} voyages, so CIs are wide. <b>Alert timing:</b> the LATE threshold (P(late) ≥ {num(dec.get("late_alert_p_threshold", float("nan")), 1)}, actionable F1 on training folds) warns {pct(dec["alert_lead_ge_48h_share"])} of late test shipments ≥ 48 h ahead{seed_lead}. <b>Next:</b> an AIS/EDI adapter, survival models, drift-triggered recalibration.</p>
</body></html>
"""


def find_browser() -> Path | None:
    env = os.environ.get("CASCADE_PDF_BROWSER")
    if env and Path(env).exists():
        return Path(env)
    for p in BROWSER_PATHS:
        if p.exists():
            return p
    for name in BROWSER_COMMANDS:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def to_pdf(html_path: Path, pdf_path: Path) -> None:
    browser = find_browser()
    if browser is None:
        sys.exit(
            "No Chromium-based browser found (Edge, Chrome or Chromium). Install one, set "
            "CASCADE_PDF_BROWSER to its path, or open report/report.html and print to PDF."
        )
    pdf_path.unlink(missing_ok=True)
    subprocess.run(
        [
            str(browser),
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            "--allow-file-access-from-files",
            f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    if not pdf_path.exists():
        sys.exit(f"{browser.name} did not write the PDF.")


def pdf_page_count(pdf_path: Path) -> int:
    data = pdf_path.read_bytes()
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", data))


def say(msg: str) -> None:
    sys.stdout.write(f"{msg}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--author", default="", help="name shown under the title")
    ap.add_argument("--no-pdf", action="store_true", help="write HTML only")
    ap.add_argument("--no-readme", action="store_true", help="do not refresh the README table")
    args = ap.parse_args()

    metrics, seeds, sim = load_inputs()
    OUT_DIR.mkdir(exist_ok=True)
    HTML_OUT.write_text(build_html(metrics, seeds, sim, args.author), encoding="utf-8")
    say(f"wrote {HTML_OUT.relative_to(ROOT)}")
    if not args.no_readme and update_readme(metrics, seeds):
        say("refreshed README.md results table")
    if not args.no_pdf:
        to_pdf(HTML_OUT, PDF_OUT)
        pages = pdf_page_count(PDF_OUT)
        say(f"wrote {PDF_OUT.relative_to(ROOT)} ({pages} pages)")
        if pages > MAX_PAGES:
            sys.exit(
                f"report is {pages} pages; the brief allows {MAX_PAGES}. Shorten it before submitting."
            )


if __name__ == "__main__":
    main()
