"""Data-feed health: which carriers / milestones go silent, and what that does to confidence."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import api_client as api
from ui import OK, PORT_NAMES, guard, kpi, setup

setup("Data health")
st.markdown("## 🩺 Milestone feed health")
dh = guard(api.data_health)
k = st.columns(3)
kpi(
    k[0],
    "Overall completeness",
    f"{dh['overall_completeness']:.0%}",
    "intermediate milestones reported",
)
by_dest = dh["completeness_by_destination"]
worst = min(by_dest, key=by_dest.get)
kpi(k[1], "Weakest destination", PORT_NAMES.get(worst, worst), f"{by_dest[worst]:.0%} complete")
kpi(k[2], "Missing ≠ not happened", "Handled", "reporting-gap inference keeps ETAs sane")
df = pd.DataFrame(dh["completeness_by_carrier_event"]).T.replace(-1, None)
order = [
    c
    for c in [
        "GATE_IN_ORIGIN",
        "DEPART_ORIGIN",
        "ARRIVE_TS",
        "DEPART_TS",
        "ARRIVE_DEST_PORT",
        "DISCHARGED",
        "CUSTOMS_CLEARED",
        "GATE_OUT",
    ]
    if c in df.columns
]
df = df[order]
fig = go.Figure(
    go.Heatmap(
        z=df.values.astype(float),
        x=[c.replace("_", " ").title() for c in order],
        y=df.index,
        colorscale=[[0, OK["vermillion"]], [0.5, OK["yellow"]], [1, OK["green"]]],
        zmin=0.5,
        zmax=1,
        text=[[f"{v:.0%}" if v == v else "n/a" for v in row] for row in df.values.astype(float)],
        texttemplate="%{text}",
        colorbar=dict(title="reported"),
    )
)
fig.update_layout(height=360, margin=dict(t=10), yaxis_title="carrier")
st.plotly_chart(fig, use_container_width=True)
st.caption(
    "Carrier E has a tier-3 EDI feed (25% extra gaps); DISCHARGED also drops when terminals are congested "
    "(missing-not-at-random). The model receives typed missingness features and the UI lowers its "
    "confidence statement when milestones are missing."
)
