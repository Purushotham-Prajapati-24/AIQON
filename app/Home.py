"""CASCADE Control Tower — Fleet overview (what needs my attention now?)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import api_client as api
from ui import GROUP_LABEL, OK, PORT_LL, PORT_NAMES, TIER, dur, guard, kpi, setup, ts

setup("Fleet")
w = guard(api.world)
m = guard(api.model)

st.markdown("## 🚢 CASCADE Control Tower")
st.caption(
    f"Stage-aware ETA, delay propagation & decisions · model v{m['version']} · "
    f"{w['n_shipments']} unseen test shipments · ● Ready"
)

now = datetime.fromisoformat(w["now"].replace("Z", "+00:00"))
c1, c2 = st.columns([3, 1])
offset = c1.slider(
    "Operating time (days relative to 'now')",
    -21,
    14,
    0,
    help="Move the clock to see the fleet earlier or later.",
)
as_of_dt = now + timedelta(days=offset)
as_of = as_of_dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
c2.markdown(
    f"<div class='kpi'><div class='l'>As of</div><div class='v' style='font-size:1.1rem'>"
    f"{as_of_dt:%a %d %b %Y %H:%M} UTC</div></div>",
    unsafe_allow_html=True,
)
st.session_state["as_of"] = as_of

f = guard(lambda: api.fleet(as_of))
rows = f["active"]
if not rows:
    st.info("No active shipments at this time — move the clock.")
    st.stop()
df = pd.DataFrame(
    [
        {
            "Shipment": r["shipment_id"],
            "Lane": r["lane_id"].replace("-", " → "),
            "Status": r["status"].replace("_", " ").title(),
            "Risk": f"{TIER[r['risk_tier']][2]} {TIER[r['risk_tier']][0]}",
            "P(late)": r["p_late"],
            "ETA (P50)": ts(r["eta"]["p50"], "%d %b %H:%M"),
            "Delay P50": r["delay_hours"]["p50"],
            "Range (P10–P90)": f"{dur(r['delay_hours']['p10'])} … {dur(r['delay_hours']['p90'])}",
            "Main stage ahead": GROUP_LABEL.get(r["main_stage"] or "", "—"),
            "Exp. cost $": r["cost_usd"].get("p50", 0),
            "Data gaps": len(r["missing_events"]),
        }
        for r in rows
    ]
).sort_values("P(late)", ascending=False)

late = sum(r["risk_tier"] == "LATE" for r in rows)
risk = sum(r["risk_tier"] == "AT_RISK" for r in rows)
k = st.columns(5)
kpi(k[0], "Active shipments", f"{len(rows)}", f"{len(f['delivered'])} delivered")
kpi(k[1], "■ Late (>24 h)", f"{late}", f"{late / len(rows):.0%} of active")
kpi(k[2], "▲ At risk", f"{risk}", "6–24 h expected delay")
kpi(k[3], "Expected late (Σ P)", f"{sum(r['p_late'] for r in rows):.1f}", "probability-weighted")
kpi(
    k[4],
    "Expected delay cost",
    f"${sum(r['cost_usd'].get('p50', 0) for r in rows):,.0f}",
    "illustrative tariffs",
)

st.markdown("#### Shipments ranked by risk")
flt = st.columns(3)
lanes = flt[0].multiselect("Lane", sorted(df.Lane.unique()))
tiers = flt[1].multiselect("Risk", [f"{v[2]} {v[0]}" for v in TIER.values()])
stage = flt[2].multiselect("Main stage ahead", sorted(df["Main stage ahead"].unique()))
view = df
if lanes:
    view = view[view.Lane.isin(lanes)]
if tiers:
    view = view[view.Risk.isin(tiers)]
if stage:
    view = view[view["Main stage ahead"].isin(stage)]
event = st.dataframe(
    view,
    hide_index=True,
    use_container_width=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "P(late)": st.column_config.ProgressColumn(
            "P(late)", format="percent", min_value=0, max_value=1
        ),
        "Delay P50": st.column_config.NumberColumn("Delay P50 (h)", format="%+.0f"),
        "Exp. cost $": st.column_config.NumberColumn(format="$%.0f"),
    },
)
sel = event.selection.rows if event and event.selection else []
if sel:
    sid = view.iloc[sel[0]]["Shipment"]
    st.session_state["shipment"] = sid
    st.success(f"Selected {sid} — open **Shipment detail** in the sidebar.", icon="👉")

st.markdown("#### Network risk map")
st.caption(
    "Arcs: lanes coloured by mean P(late) of active shipments · hubs sized by expected delay passing through"
)
lane_risk = (
    pd.DataFrame(rows).groupby(["origin", "hub", "dest"], dropna=False).p_late.mean().reset_index()
)
fig = go.Figure()
for _, r in lane_risk.iterrows():
    pts = [r.origin] + ([r.hub] if isinstance(r.hub, str) and r.hub else []) + [r.dest]
    color = OK["vermillion"] if r.p_late > 0.6 else OK["orange"] if r.p_late > 0.3 else OK["green"]
    fig.add_trace(
        go.Scattergeo(
            lat=[PORT_LL[p][0] for p in pts],
            lon=[PORT_LL[p][1] for p in pts],
            mode="lines",
            line=dict(width=1 + 4 * r.p_late, color=color),
            opacity=0.8,
            hoverinfo="text",
            text=f"{' → '.join(PORT_NAMES[p] for p in pts)}: P(late) {r.p_late:.0%}",
            showlegend=False,
        )
    )
fig.add_trace(
    go.Scattergeo(
        lat=[v[0] for v in PORT_LL.values()],
        lon=[v[1] for v in PORT_LL.values()],
        text=[PORT_NAMES[k] for k in PORT_LL],
        mode="markers+text",
        textposition="top center",
        marker=dict(size=6, color=OK["ink"]),
        textfont=dict(size=9),
        showlegend=False,
        hoverinfo="text",
    )
)
fig.update_geos(
    projection_type="natural earth",
    showcountries=False,
    showland=True,
    landcolor="rgba(128,128,128,.12)",
    showocean=False,
    lataxis_range=[-10, 62],
    lonaxis_range=[-125, 140],
)
fig.update_layout(height=380, margin=dict(l=0, r=0, t=0, b=0))
st.plotly_chart(fig, use_container_width=True)
