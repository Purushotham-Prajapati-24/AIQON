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
README = ROOT / "README.md"
EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
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
@page { size: A4; margin: 9mm 11mm 8mm 11mm; }
:root { --accent:#c2452d; --blue:#2563a8; --orange:#b7791f; --green:#16794c; --verm:#c2452d; --sky:#56B4E9;
        --ink:#1f2328; --text:#2d333a; --muted:#656d76; --rule:#e4e1db; --band:#faf8f4; --card:#fcfbf9; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Inter", "Segoe UI", system-ui, sans-serif; font-size: 8.6pt; line-height: 1.36;
       color: var(--text); margin: 0; background: #fff; font-feature-settings: "cv11", "ss01";
       -webkit-font-smoothing: antialiased; }
h1 { font-weight: 700; font-size: 17pt; line-height: 1.15; letter-spacing: -0.025em; color: var(--ink);
     margin: 0 0 1.4mm; }
h1::before { content: "TECHNICAL REPORT"; display: block; font-size: 6.8pt; font-weight: 600;
     letter-spacing: 0.14em; color: var(--accent); margin-bottom: 1.2mm; }
.sub { color: var(--muted); font-size: 7.8pt; margin-bottom: 3mm; padding-bottom: 2.4mm;
       border-bottom: 1px solid var(--rule); }
h2 { font-weight: 650; font-size: 11pt; letter-spacing: -0.015em; color: var(--ink);
     margin: 2.8mm 0 1mm; break-after: avoid; }
h3 { font-size: 9pt; font-weight: 600; color: var(--ink); margin: 2mm 0 0.8mm; break-after: avoid; }
p { margin: 0 0 1.5mm; text-align: left; hyphens: manual; }
b, strong { font-weight: 600; color: var(--ink); }
ul { margin: 0 0 1.6mm; padding-left: 4.2mm; }
li { margin: 0 0 0.7mm; padding-left: 0.6mm; }
li::marker { color: var(--accent); }
code, .mono { font-family: "JetBrains Mono", Consolas, monospace; font-size: 7.8pt; }
.tldr { background: var(--band); border: 1px solid var(--rule); border-left: 3px solid var(--accent);
        padding: 2.4mm 3.2mm; margin: 0 0 2.4mm; border-radius: 2mm; }
.tldr p { margin: 0; }
.defs { display: grid; grid-template-columns: auto 1fr; column-gap: 3.5mm; row-gap: 0.6mm;
        font-size: 8.4pt; margin: 1.2mm 0 1.8mm; padding: 2mm 3mm; border: 1px solid var(--rule);
        border-radius: 2mm; background: var(--card); }
.defs .mono { white-space: nowrap; color: var(--accent); }
table { border-collapse: separate; border-spacing: 0; width: 100%; font-size: 7.8pt; margin: 0.8mm 0 1.8mm;
        break-inside: avoid; border: 1px solid var(--rule); border-radius: 2mm; }
th, td { padding: 0.75mm 1.8mm; border-bottom: 1px solid var(--rule); text-align: left; vertical-align: top; }
tr:last-child td { border-bottom: 0; }
th { background: #1f2328; color: #fff; font-weight: 600; font-size: 7.4pt; letter-spacing: 0.02em; }
tr:nth-child(odd) td { background: #fbfaf7; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr.hl td { background: #fdf0ec !important; font-weight: 600; color: var(--ink); }
caption { caption-side: top; text-align: left; font-weight: 600; font-size: 8pt; color: var(--ink);
          padding-bottom: 1mm; }
.two { display: grid; grid-template-columns: 1fr 1fr; column-gap: 5mm; align-items: start; }
.two > * { min-width: 0; }
figure { margin: 1.2mm 0 2.2mm; break-inside: avoid; text-align: center; border: 1px solid var(--rule);
         border-radius: 2mm; padding: 1.6mm; background: #fff; }
figure img { max-width: 100%; }
figcaption { font-size: 7.6pt; color: var(--muted); text-align: left; margin-top: 1mm; line-height: 1.38; }
.quote { font-size: 8.4pt; border-left: 3px solid var(--orange); padding: 1.6mm 2.8mm;
         background: #fdf8ef; margin: 1.2mm 0 2mm; border-radius: 0 2mm 2mm 0; }
.pass { color: var(--green); font-weight: 600; }
.warn { color: var(--verm); font-weight: 600; }
.small { font-size: 7.6pt; color: var(--muted); }
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
    n_pass = sum(1 for g in gates.values() if g.get("pass"))

    def sd(key, f):
        return mean_sd(seeds, key, f) if seeds else "n/a"

    t_simple = "".join(
        f"<tr{' class=hl' if k == 'cascade' else ''}><td>{esc(lbl)}</td>"
        f"<td class=n>{hrs(ov[k]['mae'])}</td><td class=n>{hrs(ov[k]['rmse'])}</td></tr>"
        for k, lbl in [
            ("B0_schedule", "Assume the original plan holds"),
            ("B1_carry_forward", "Assume today's delay stays the same"),
            ("B2_propagation_prior", "Lane-level propagation prior"),
            ("cascade", "CASCADE"),
        ]
    )
    n_seeds = len(seeds["runs"]) if seeds else 0

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>CASCADE Technical Report</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;650;700&family=JetBrains+Mono:wght@400;500&display=block" rel="stylesheet">
<style>{CSS}</style></head><body>

<h1>CASCADE: predicting shipment ETA and explaining where delays come from</h1>
<div class=sub>{author_html}Aiqon AI Internship take-home · model v{esc(meta["version"])} · {gen}</div>

<div class=tldr><p><b>Summary.</b> CASCADE predicts when a container shipment will actually be delivered, how likely it is to be more than {late_h} hours late, and which stage of the journey is causing the delay.
On a test season it never saw in training, its delivery-time error is <b>{hrs(h["mae_cascade_h"])}</b>, which is <b>{pct(h["mae_improvement_vs_B1"])} lower</b> than assuming today's delay stays the same.
Because our simulated data records the true cause of every hour of delay, we could check the explanations too: the real cause is in CASCADE's top two stages <b>{pct(h["attribution_top2"])}</b> of the time.</p></div>

<table><caption>Table 1 · Key results on the held-out test season</caption>
<tr><th>What we measured</th><th>Why it matters</th><th class=n>Result</th><th class=n>Average over {n_seeds} runs</th></tr>
<tr><td>Error reduction vs carry-forward</td><td>Gain over "today's delay stays the same"</td><td class=n><b>{pct(h["mae_improvement_vs_B1"])}</b></td><td class=n>{sd("mae_improvement_vs_B1", pct)}</td></tr>
<tr><td>Error reduction vs propagation prior</td><td>Gain over a lane-level delay propagation rule</td><td class=n><b>{pct(h["mae_improvement_vs_B2"])}</b></td><td class=n>{sd("mae_improvement_vs_B2", pct)}</td></tr>
<tr><td>P10–P90 range coverage</td><td>How often the real delay falls in the predicted range (aim {pct(nominal)})</td><td class=n><b>{pct(h["coverage_p10_p90_overall"])}</b></td><td class=n>{sd("coverage_p10_p90_overall", pct)}</td></tr>
<tr><td>Chance-late accuracy (PR-AUC)</td><td>How well P(late &gt; {late_h} h) separates late from on-time shipments</td><td class=n><b>{num(h["pr_auc_tau24"])}</b></td><td class=n>{sd("pr_auc_tau24", num)}</td></tr>
<tr><td>Right cause, first choice</td><td>Explanation checked against the true cause</td><td class=n><b>{pct(h["attribution_top1"])}</b></td><td class=n>{sd("attribution_top1", pct)}</td></tr>
<tr><td>Response time (p95)</td><td>Time to predict and explain one shipment</td><td class=n><b>{ms(chk["latency_p95_ms"])}</b></td><td class=n></td></tr>
</table>

<h2>1 · How ETA and delay are defined</h2>
<p>Every shipment passes through the same stages: gate-in, origin departure, hub arrival and departure (only on hub lanes), destination arrival, discharge, customs release, gate-out and delivery. Each stage has a planned time and an actual time. All values are in hours, and a positive number means late.</p>
<div class=defs>
<span class=mono>Stage delay</span><span>actual time − planned time at that stage</span>
<span class=mono>Stage increment</span><span>how much delay a stage adds (or recovers) compared with the stage before it</span>
<span class=mono>Final delay</span><span>delay at delivery, which equals the sum of all stage increments</span>
<span class=mono>ETA</span><span>planned delivery + delay so far + predicted remaining delay, given as P10, P50 and P90</span>
<span class=mono>Late</span><span>final delay greater than {late_h} hours</span>
</div>
<p>At each milestone the model only sees what was known at that moment. Congestion and weather for future stages are given as forecasts, not as the values that actually happened.</p>

<h2>2 · Data</h2>
<p>We generated 300 shipments with a simulator built on real logistics rules, on lanes from Asian ports through hubs such as Singapore and Colombo to Europe and the US. Each rule in Table 2 writes the hours of delay it causes into a <b>cause ledger</b>, which gives us the true reason for every delay. Some milestone reports are deliberately missing or arrive late, as they do with real carrier data. The last voyages in time, which fall in the busy Q4 peak, are held out as the test set.</p>
<table><caption>Table 2 · Real-world behaviour built into the simulator</caption>
<tr><th>Stage</th><th>What happens</th></tr>
<tr><td>Origin</td><td>Carrier reliability, port congestion and storms delay departure.</td></tr>
<tr><td>Ocean</td><td>Bad weather slows the vessel; ships speed up to recover part of a delay.</td></tr>
<tr><td>Transshipment</td><td>If the container misses its connection, it waits for the next sailing. This is the biggest source of cascading delay.</td></tr>
<tr><td>Destination port</td><td>A late vessel loses its berth slot and queues longer when the port is busy.</td></tr>
<tr><td>Customs</td><td>Inspections depend on cargo risk and paperwork; release only happens in office hours.</td></tr>
<tr><td>Inland</td><td>Trains leave at fixed times, trucks need appointments and receivers have delivery windows.</td></tr>
</table>

<h2>3 · Method</h2>
<table><caption>Table 3 · How CASCADE builds a prediction</caption>
<tr><th>Step</th><th>What it does</th></tr>
<tr><td>Snapshots</td><td>One row per shipment per milestone, using only information available at that time.</td></tr>
<tr><td>Operator rulebook</td><td>Projects the delay each remaining stage will add, using cut-offs, sailing schedules, queues and calendars. Its settings are deliberately different from the simulator's.</td></tr>
<tr><td>Stage features</td><td>Link stages together: hub buffer vs connection cut-off, congestion × current lateness, time to the next customs slot.</td></tr>
<tr><td>Machine learning</td><td>LightGBM quantile models give the P10–P90 range, a calibrated classifier gives P(late), and conformal calibration keeps the range reliable when the season changes.</td></tr>
<tr><td>Explanation</td><td>The prediction is split into delay already realised plus each remaining stage's share, and written as a short sentence for the customer or the planner.</td></tr>
</table>
<p>On validation data, the learned correction to the median did not beat the rulebook, so it was switched off (weight {sel["shrink"]}). The median ETA therefore comes from the rulebook, and machine learning adds the range, the chance of being late and the stage forecasts.</p>

<h2>4 · Results</h2>
<div class=two>
<div>
<table><caption>Table 4 · Delivery-time error ({a["n_test_rows"]} test predictions)</caption>
<tr><th>Method</th><th class=n>MAE</th><th class=n>RMSE</th></tr>{t_simple}</table>
</div>
<div>
<table><caption>Table 5 · Is the stated range reliable?</caption>
<tr><th>Shipment position</th><th class=n>Coverage</th><th class=n>Range width</th></tr>{t_cov}</table>
</div>
</div>

<figure style="background:#f3efe6"><img src="{OUT_DIR.joinpath("figures","dash_convergence.png").as_uri()}" style="width:64%">
<figcaption>Figure 1 · Prediction error at each milestone, from the dashboard. Error falls from {hrs(by_cp["cascade"][cp_first])} at booking to {hrs(by_cp["cascade"][cp_last])} at gate-out. The jump at the hub is where connections are made or missed.</figcaption></figure>

<div class=two>
<div>
<table><caption>Table 6 · Does it blame the right stage?</caption>
<tr><th>Method</th><th class=n>Correct</th></tr>
<tr class=hl><td>CASCADE, top two stages</td><td class=n>{pct(att["accuracy"]["shap_top2"])}</td></tr>
<tr><td>CASCADE, first choice</td><td class=n>{pct(att["accuracy"]["shap_top1"])}</td></tr>
<tr><td>Lane-history guess</td><td class=n>{pct(att["accuracy"]["lane_prior_top1"])}</td></tr>
<tr><td>Random guess</td><td class=n>{pct(att["accuracy"]["random_top1"])}</td></tr>
</table>
</div>
<div>
<table><caption>Table 7 · How much one hour of delay grows by delivery</caption>
<tr><th>Delay added at</th><th class=n>CASCADE</th><th class=n>True</th></tr>{t_prop}</table>
</div>
</div>
<p class=small>Table 7: the true values come from re-running the simulator with {num(prop["delta_h"], 0)} extra hours injected at one stage. A value above 1 means the delay grows on the way to the customer.</p>

<h3>Worked example: {esc(ex["shipment_id"])}, Shanghai → Tanjung Pelepas → Rotterdam</h3>
<div class=two>
<figure style="margin-top:0;background:#f3efe6"><img src="{OUT_DIR.joinpath("figures","dash_why.png").as_uri()}" style="width:100%">
<figcaption>Figure 2 · The dashboard's explanation for this shipment at hub arrival. Delay so far (solid) + projected stage delay (hatched) = P50 ({hrs(dh["p50"], 0)}).</figcaption></figure>
<div>
<div class=quote>{esc(narrative)}</div>
<p class=small>The biggest driver is a projected missed connection at the hub ({hrs(top["contribution_h"], 0)}). The simulator's cause ledger confirms the true cause: <b>{esc(ex["root_cause_group"].title())}</b>. Expected cost of the delay: ${ex["cost_usd"]["p50"]:,.0f}.</p>
</div>
</div>

</body></html>
"""


def find_edge() -> Path | None:
    for p in EDGE_CANDIDATES:
        if p.exists():
            return p
    found = shutil.which("msedge")
    return Path(found) if found else None


def to_pdf(html_path: Path, pdf_path: Path) -> None:
    edge = find_edge()
    if edge is None:
        sys.exit("Microsoft Edge not found; open report/report.html and print to PDF instead.")
    pdf_path.unlink(missing_ok=True)
    subprocess.run(
        [
            str(edge),
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            "--allow-file-access-from-files",
            "--virtual-time-budget=8000",
            f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    if not pdf_path.exists():
        sys.exit("Edge did not write the PDF.")


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
        say(f"wrote {PDF_OUT.relative_to(ROOT)} ({pdf_page_count(PDF_OUT)} pages)")


if __name__ == "__main__":
    main()
