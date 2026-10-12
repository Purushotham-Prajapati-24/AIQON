"""Report figures (matplotlib, headless). Okabe-Ito palette, never colour-only encodings."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OKABE = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "vermillion": "#D55E00",
    "sky": "#56B4E9",
    "purple": "#CC79A7",
    "yellow": "#F0E442",
    "black": "#000000",
    "grey": "#8C8C8C",
}
CP_SHORT = {
    0: "Booked",
    1: "Gate-in",
    2: "Departed",
    3: "At hub",
    4: "Left hub",
    5: "Arrived",
    6: "Discharged",
    7: "Cleared",
    8: "Gate-out",
}


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)


def convergence(metrics: dict, out: Path) -> None:
    by = metrics["accuracy"]["by_checkpoint_mae"]
    series = [
        ("cascade", "CASCADE (P50)", OKABE["blue"], "o", "-"),
        ("B2_propagation_prior", "B2 propagation prior", OKABE["orange"], "s", "--"),
        ("B1_carry_forward", "B1 carry-forward", OKABE["grey"], "^", ":"),
        ("physics_rulebook", "Operator rulebook (no ML)", OKABE["green"], "d", "-."),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    for key, label, color, marker, ls in series:
        d = by[key]
        cps = sorted(int(c) for c in d)
        ax.plot(
            cps,
            [d[c] if c in d else d[str(c)] for c in cps],
            label=label,
            color=color,
            marker=marker,
            ls=ls,
        )
    ax.set_xticks(range(9), [CP_SHORT[i] for i in range(9)], rotation=30, ha="right")
    ax.set_ylabel("MAE of final delay (h)")
    ax.set_title("ETA convergence: error falls as milestones arrive")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def coverage(metrics: dict, out: Path) -> None:
    cov = metrics["accuracy"]["coverage_p10_p90"]
    groups = ["pre_departure", "at_sea", "at_port", "post_customs", "overall"]
    vals = [cov.get(g, np.nan) for g in groups]
    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    ax.bar(groups, vals, color=OKABE["sky"], edgecolor=OKABE["blue"])
    ax.axhline(0.8, color=OKABE["vermillion"], ls="--", label="80% target")
    for i, v in enumerate(vals):
        ax.text(i, v + 0.015, f"{v:.0%}", ha="center", fontsize=8)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("P10–P90 coverage")
    ax.set_title("Conformal intervals by checkpoint group")
    ax.legend(frameon=False, fontsize=8)
    ax.tick_params(axis="x", labelrotation=20)
    _style(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def reliability(metrics: dict, out: Path) -> None:
    r = metrics["accuracy"]["reliability"]
    fig, ax = plt.subplots(figsize=(3.6, 3.4))
    ax.plot([0, 1], [0, 1], color=OKABE["grey"], ls=":")
    ax.plot(r["bin_mean_pred"], r["bin_frac_pos"], marker="o", color=OKABE["blue"])
    ax.set_xlabel("Predicted P(late > 24 h)")
    ax.set_ylabel("Observed frequency")
    ax.set_title(f"Calibration (ECE {r['ece']:.3f})")
    _style(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def attribution(metrics: dict, out: Path) -> None:
    acc = metrics["attribution_fidelity"]["accuracy"]
    keys = [
        ("shap_top1", "CASCADE stage ranking (top-1)"),
        ("shap_top2", "CASCADE stage ranking (top-2)"),
        ("stage_forecast_top1", "Reconciled stage forecast"),
        ("lane_prior_top1", "Lane-history explainer"),
        ("random_top1", "Random future stage"),
    ]
    fig, ax = plt.subplots(figsize=(6.0, 2.8))
    colors = [OKABE["blue"], OKABE["sky"], OKABE["green"], OKABE["orange"], OKABE["grey"]]
    ax.barh([k[1] for k in keys][::-1], [acc[k[0]] for k in keys][::-1], color=colors[::-1])
    for i, k in enumerate(keys[::-1]):
        ax.text(acc[k[0]] + 0.01, i, f"{acc[k[0]]:.0%}", va="center", fontsize=8)
    ax.set_xlim(0, 1)
    ax.set_xlabel("Root-cause stage accuracy vs simulator cause ledger")
    ax.set_title(
        f"Explanation fidelity (n = {metrics['attribution_fidelity']['n']} pre-arrival snapshots)"
    )
    _style(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def propagation(metrics: dict, out: Path) -> None:
    pf = metrics["propagation_fidelity"]["by_event"]
    events = [
        e for e in ["DEPART_ORIGIN", "ARRIVE_TS", "ARRIVE_DEST_PORT", "DISCHARGED"] if e in pf
    ]
    x = np.arange(len(events))
    fig, ax = plt.subplots(figsize=(5.8, 3.0))
    ax.bar(
        x - 0.18,
        [pf[e]["phi_true"] for e in events],
        0.36,
        label="True (SCM re-simulation)",
        color=OKABE["orange"],
    )
    ax.bar(
        x + 0.18,
        [pf[e]["phi_hat"] for e in events],
        0.36,
        label="CASCADE",
        color=OKABE["blue"],
        hatch="//",
        edgecolor="white",
    )
    ax.axhline(1.0, color=OKABE["grey"], ls=":")
    ax.set_xticks(x, [e.replace("_", " ").title() for e in events], fontsize=8)
    ax.set_ylabel("Δ final delay / Δ stage delay")
    ax.set_title(
        f"Delay propagation factor (Spearman {metrics['propagation_fidelity']['spearman']:.2f})"
    )
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def robustness_fig(metrics: dict, out: Path) -> None:
    rb = metrics.get("robustness")
    if not rb:
        return
    rates = sorted(rb, key=float)
    fig, ax = plt.subplots(figsize=(4.4, 3.0))
    ax.plot(
        [float(r) for r in rates],
        [rb[r]["mae"] for r in rates],
        marker="o",
        color=OKABE["blue"],
        label="CASCADE",
    )
    ax.plot(
        [float(r) for r in rates],
        [rb[r]["mae_B1"] for r in rates],
        marker="^",
        ls=":",
        color=OKABE["grey"],
        label="B1 carry-forward",
    )
    ax.set_xlabel("Extra milestones dropped at test time")
    ax.set_ylabel("MAE (h)")
    ax.set_title("Robustness to missing milestones")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def waterfall_example(result_json: dict, out: Path) -> None:
    items = result_json["waterfall"]
    labels, starts, vals, kinds = [], [], [], []
    run = 0.0
    for it in items:
        if it["kind"] == "total":
            labels.append(it["label"])
            starts.append(0.0)
            vals.append(it["hours"])
            kinds.append("total")
            continue
        labels.append(it["label"])
        starts.append(run)
        vals.append(it["hours"])
        kinds.append(it["kind"])
        run += it["hours"]
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    for i, (s, v, k) in enumerate(zip(starts, vals, kinds, strict=True)):
        color = {
            "realized": OKABE["vermillion"],
            "rulebook": OKABE["blue"],
            "learned": OKABE["green"],
            "ordering": OKABE["purple"],
            "floor": OKABE["purple"],
            "delivered": OKABE["grey"],
            "total": OKABE["black"],
        }.get(k, OKABE["grey"])
        ax.barh(
            i,
            v,
            left=s,
            color=color,
            hatch="//" if k in ("rulebook", "learned") else None,
            edgecolor="white" if k in ("rulebook", "learned") else color,
            alpha=0.9,
        )
        ax.text(
            s + v + (2 if v >= 0 else -2),
            i,
            f"{v:+.0f} h",
            va="center",
            ha="left" if v >= 0 else "right",
            fontsize=7,
        )
    ax.set_yticks(range(len(labels)), labels, fontsize=7)
    ax.invert_yaxis()
    ax.axvline(0, color=OKABE["grey"], lw=0.8)
    ax.set_xlabel(
        "Hours vs plan (solid = observed, hatched = projected: rulebook blue, learned green)"
    )
    ax.set_title(
        f"{result_json['shipment_id']}: delay waterfall at {result_json['checkpoint'].replace('_', ' ').lower()}"
    )
    _style(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def all_figures(metrics: dict, out_dir: Path, example: dict | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for name, fn in [
        ("convergence", convergence),
        ("coverage", coverage),
        ("reliability", reliability),
        ("attribution", attribution),
        ("propagation", propagation),
        ("robustness", robustness_fig),
    ]:
        p = out_dir / f"{name}.png"
        fn(metrics, p)
        if p.exists():
            made.append(p)
    if example:
        p = out_dir / "waterfall_example.png"
        waterfall_example(example, p)
        made.append(p)
    return made
