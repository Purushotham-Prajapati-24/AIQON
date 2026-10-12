"""Model & network insights: can I trust it, and where do delays amplify?"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import api_client as api
from ui import GROUP_LABEL, OK, guard, kpi, setup

setup("Insights")
st.markdown("## 📈 Model & network insights")
ins = guard(api.insights)
h = ins["headline"]
k = st.columns(5)
kpi(
    k[0],
    "MAE vs carry-forward",
    f"−{h['mae_improvement_vs_B1']:.0%}",
    f"95% CI {h['mae_improvement_vs_B1_ci95'][0]:.0%}–{h['mae_improvement_vs_B1_ci95'][1]:.0%}",
)
kpi(k[1], "P10–P90 coverage", f"{h['coverage_p10_p90_overall']:.0%}", "target 80%")
kpi(k[2], "P(late) PR-AUC", f"{h['pr_auc_tau24']:.2f}", f"Brier {h['brier_tau24']:.3f}")
kpi(
    k[3],
    "Root-cause accuracy",
    f"{h['attribution_top1']:.0%}",
    f"top-2 {h['attribution_top2']:.0%} · vs ledger",
)
kpi(k[4], "Latency p95", f"{h.get('latency_p95_ms', 0):.1f} ms", "predict + explain")

t1, t2, t3, t4, t5 = st.tabs(
    [
        "Accuracy",
        "Uncertainty & calibration",
        "Explanation fidelity",
        "Delay propagation",
        "Live monitoring & gates",
    ]
)
acc = ins["accuracy"]
CP = [
    "Booked",
    "Gate-in",
    "Departed",
    "At hub",
    "Left hub",
    "Arrived",
    "Discharged",
    "Cleared",
    "Gate-out",
]
with t1:
    st.markdown("**ETA convergence** — error falls as milestones arrive")
    fig = go.Figure()
    for key, name, color, dash in [
        ("cascade", "CASCADE", OK["blue"], "solid"),
        ("B2_propagation_prior", "B2 propagation prior", OK["orange"], "dash"),
        ("B1_carry_forward", "B1 carry-forward", OK["grey"], "dot"),
    ]:
        d = acc["by_checkpoint_mae"][key]
        cps = sorted(int(c) for c in d)
        fig.add_trace(
            go.Scatter(
                x=[CP[c] for c in cps],
                y=[d[str(c)] for c in cps],
                name=name,
                line=dict(color=color, dash=dash),
                mode="lines+markers",
            )
        )
    fig.update_layout(height=340, yaxis_title="MAE of final delay (h)", margin=dict(t=10))
    st.plotly_chart(fig, use_container_width=True)
    rows = [
        {
            "Model": k,
            "MAE (h)": v["mae"],
            "RMSE": v["rmse"],
            "Median AE": v["medae"],
            "P90 AE": v["p90ae"],
            "Bias": v["bias"],
        }
        for k, v in acc["overall"].items()
    ]
    st.dataframe(pd.DataFrame(rows).round(1), hide_index=True, use_container_width=True)
    if ins.get("ablations"):
        st.markdown("**Ablations** (test MAE, h) — what each feature family is worth")
        ab = {
            "full model": h["mae_cascade_h"],
            **{k: v["mae"] for k, v in ins["ablations"].items()},
        }
        st.bar_chart(pd.Series(ab, name="MAE (h)"), horizontal=True, color=OK["blue"])
    mi = guard(api.model)
    st.caption(
        f"Trust in the learned median correction (chosen on temporal validation, never on test): "
        f"shrink = {mi['shrink']} · classifier blend = {mi['late_blend']}. "
        "Out-of-time test = Q4 peak season (a deliberate distribution shift)."
    )
with t2:
    c = st.columns(2)
    cov = acc["coverage_p10_p90"]
    groups = ["pre_departure", "at_sea", "at_port", "post_customs"]
    fig = go.Figure(
        go.Bar(
            x=groups,
            y=[cov[g] for g in groups],
            marker_color=OK["sky"],
            text=[f"{cov[g]:.0%}" for g in groups],
            textposition="outside",
        )
    )
    fig.add_hline(
        y=0.8, line_dash="dash", line_color=OK["vermillion"], annotation_text="80% target"
    )
    fig.update_layout(
        height=320, yaxis_range=[0, 1.05], title="Conformal P10–P90 coverage", margin=dict(t=40)
    )
    c[0].plotly_chart(fig, use_container_width=True)
    rel = acc["reliability"]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[0, 1],
            y=[0, 1],
            mode="lines",
            line=dict(dash="dot", color=OK["grey"]),
            name="perfect",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=rel["bin_mean_pred"],
            y=rel["bin_frac_pos"],
            mode="lines+markers",
            line=dict(color=OK["blue"]),
            name="CASCADE",
        )
    )
    fig.update_layout(
        height=320,
        title=f"P(late) calibration · ECE {rel['ece']:.3f}",
        xaxis_title="predicted",
        yaxis_title="observed",
        margin=dict(t=40),
    )
    c[1].plotly_chart(fig, use_container_width=True)
with t3:
    at = ins["attribution"]["accuracy"]
    st.markdown(
        "Does the explanation blame the stage that **actually** caused the remaining delay? "
        "Ground truth comes from the simulator's cause ledger (pre-arrival snapshots, significant delays)."
    )
    names = {
        "shap_top1": "CASCADE stage attribution (top-1)",
        "shap_top2": "CASCADE (top-2)",
        "stage_forecast_top1": "Reconciled stage forecast",
        "lane_prior_top1": "Lane-history explainer",
        "random_top1": "Random future stage",
    }
    s = pd.Series({names[k]: at[k] for k in names})
    st.bar_chart(s, horizontal=True, color=OK["blue"])
    st.caption(
        f"n = {ins['attribution']['n']}; major delays (>24 h) top-1: {at['shap_top1_major_delays']:.0%}"
    )
    adv = ins.get("advisor") or {}
    if adv.get("n"):
        st.markdown(
            f"**Advisor fidelity** — model vs true (re-simulated) hours saved: Spearman "
            f"**{adv['spearman']:.2f}**, direction agreement **{adv['sign_agreement']:.0%}** (n={adv['n']})"
        )
        st.dataframe(pd.DataFrame(adv["by_action"]).T.round(1), use_container_width=True)
with t4:
    pr = ins["propagation"]
    st.markdown(
        f"**Propagation factor** Φ = Δ final delay / Δ delay injected at a stage. Φ > 1 amplifies "
        f"(missed connections, lost berth windows), Φ < 1 absorbs (slack, speed recovery). "
        f"Model vs SCM truth: Spearman **{pr['spearman']:.2f}**, MAE {pr['mae']:.2f}."
    )
    mat = pd.DataFrame(pr["matrix"])
    if not mat.empty:
        piv = mat.pivot_table(index="lane_id", columns="event", values="phi_hat")
        order = [
            c
            for c in ["DEPART_ORIGIN", "ARRIVE_TS", "ARRIVE_DEST_PORT", "DISCHARGED"]
            if c in piv.columns
        ]
        piv = piv[order]
        fig = go.Figure(
            go.Heatmap(
                z=piv.values,
                x=[c.replace("_", " ").title() for c in order],
                y=piv.index,
                colorscale=[[0, OK["green"]], [0.33, "#f7f7f7"], [1, OK["vermillion"]]],
                zmin=0,
                zmax=3,
                text=piv.round(2).values,
                texttemplate="%{text}",
                colorbar=dict(title="Φ"),
            )
        )
        fig.update_layout(height=420, margin=dict(t=10), title="")
        st.plotly_chart(fig, use_container_width=True)
    gi = ins.get("group_importance", {})
    st.markdown("**Global importance by stage group** (mean |contribution|, h)")
    st.bar_chart(
        pd.Series({GROUP_LABEL.get(k, k): v for k, v in gi.items() if v > 0.01}),
        horizontal=True,
        color=OK["blue"],
    )
with t5:
    mon = guard(api.monitoring)
    st.markdown("**Live accuracy from the prediction ledger** (predictions joined to deliveries)")
    if mon["by_checkpoint"]:
        st.dataframe(
            pd.DataFrame(mon["by_checkpoint"]).round(3), hide_index=True, use_container_width=True
        )
    st.caption(
        f"Ledger: {mon['ledger']['written']} written, {mon['ledger']['dropped']} dropped (never blocks requests)"
    )
    st.markdown("**Publication quality gates**")
    st.dataframe(pd.DataFrame(ins["gates"]).T, use_container_width=True)
    if ins.get("robustness"):
        rb = ins["robustness"]
        st.markdown("**Robustness to missing milestones** (extra drop rate → MAE h)")
        st.line_chart(
            pd.DataFrame(
                {
                    "CASCADE": {float(k): v["mae"] for k, v in rb.items()},
                    "B1 carry-forward": {float(k): v["mae_B1"] for k, v in rb.items()},
                }
            )
        )
