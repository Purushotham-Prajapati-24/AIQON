"""Shipment detail — why is this one late, how sure are we, and what should I do? (hero page)"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import json

import plotly.graph_objects as go
import streamlit as st

import api_client as api
from ui import (
    GROUP_LABEL,
    OK,
    PORT_NAMES,
    dur,
    guard,
    setup,
    tier_chip,
    timeline_chart,
    ts,
    usd,
    waterfall_chart,
)

setup("Shipment")
w = guard(api.world)
ships = guard(api.shipments)
ids = [s["shipment_id"] for s in ships]
if "shipment" not in st.session_state:  # default: the riskiest active shipment right now
    active = guard(lambda: api.fleet(st.session_state.get("as_of")))["active"]
    st.session_state["shipment"] = (
        max(active, key=lambda r: r["p_late"])["shipment_id"] if active else ids[0]
    )
default = st.session_state["shipment"]
c0, c1 = st.columns([1, 2])
sid = c0.selectbox("Shipment", ids, index=ids.index(default) if default in ids else 0)
st.session_state["shipment"] = sid

# ---- time-travel replay ------------------------------------------------------------------------
cps = guard(lambda: api.checkpoints(sid))
opts = [c["as_of"] for c in cps] + ["now"]
labels = {c["as_of"]: f"{c['label']} · {ts(c['as_of'], '%d %b %H:%M')}" for c in cps} | {
    "now": f"Now · {ts(w['now'], '%d %b %H:%M')}"
}
choice = c1.select_slider(
    "⏪ Time-travel: replay the shipment milestone by milestone",
    options=opts,
    value="now",
    format_func=lambda o: labels[o],
)
as_of = None if choice == "now" else choice
audience = st.radio(
    "Explain for",
    ["ops", "customer", "analyst"],
    horizontal=True,
    format_func={"ops": "Ops planner", "customer": "Customer", "analyst": "Analyst"}.get,
)
s = guard(lambda: api.shipment(sid, as_of, audience))
info = s["shipment"]
route = " → ".join(PORT_NAMES[p] for p in [info["origin"], info["hub"], info["dest"]] if p)
st.markdown(f"### {sid} · {route}")
st.markdown(
    f"{tier_chip(s['risk_tier'])} <span class='chip'>Carrier {info['carrier']}</span>"
    f"<span class='chip'>{info['inland_mode'].title()} final leg</span>"
    f"<span class='chip'>{s['status'].replace('_', ' ').title()}</span>"
    + (
        "<span class='chip' style='color:#D55E00'>Reduced confidence: degraded</span>"
        if s["flags"]["degraded"]
        else ""
    )
    + (
        f"<span class='chip' style='color:#E69F00'>⚠ {len(s['flags']['missing_events'])} milestone(s) missing</span>"
        if s["flags"]["missing_events"]
        else ""
    ),
    unsafe_allow_html=True,
)

# ---- answer first: ETA card + narrative ---------------------------------------------------------
a, b = st.columns([1, 2])
d = s["delay_hours"]
promise = s.get("promise") or {}
a.markdown(
    f"<div class='eta'><div class='l' style='opacity:.7'>EXPECTED DELIVERY (P50)</div>"
    f"<div class='big'>{ts(s['eta']['p50'], '%a %d %b, %H:%M')}</div>"
    f"<div>Likely between <b>{ts(s['eta']['p10'], '%d %b %H:%M')}</b> and <b>{ts(s['eta']['p90'], '%d %b %H:%M')}</b></div>"
    f"<div style='margin-top:6px'>Delay vs plan: <b>{dur(d['p50'])}</b> (P10 {dur(d['p10'])} · P90 {dur(d['p90'])})</div>"
    f"<div>Probability of &gt;24 h late: <b>{s['p_late']:.0%}</b></div>"
    f"<hr style='margin:8px 0'><div>📅 Promise date: <b>{promise.get('promise_date', '—')}</b>"
    f" <span style='opacity:.7'>({promise.get('changes', 0)} change(s); {promise.get('reason', '')})</span></div>"
    f"<div>💲 Expected delay cost: <b>${s['cost_usd'].get('p50', 0):,.0f}</b>"
    f" <span style='opacity:.7'>(P90 ${s['cost_usd'].get('p90', 0):,.0f})</span></div></div>",
    unsafe_allow_html=True,
)
with b:
    st.markdown(f"<div class='narr'>{s['narrative']}</div>", unsafe_allow_html=True)
    with st.expander("📋 Copy-ready text"):
        st.code(s["narrative"], language=None, wrap_lines=True)
    if "actual_total_delay_h" in s:
        st.info(f"Delivered — actual delay {dur(s['actual_total_delay_h'])}.", icon="✅")

# ---- timeline + waterfall -----------------------------------------------------------------------
st.markdown("#### Milestone timeline — planned vs observed vs projected")
st.plotly_chart(timeline_chart(s["timeline"]), use_container_width=True)

left, right = st.columns([3, 2])
with left:
    st.markdown("#### Delay waterfall")
    if "waterfall" in s:
        st.plotly_chart(waterfall_chart(s["waterfall"]), use_container_width=True)
        st.caption(
            "● realized delay from observed milestones · ◦ forecast contributions by stage (exact, additive)"
        )
with right:
    st.markdown("#### Why? Stage drivers")
    for drv in s.get("drivers", []):
        sign = "+" if drv["contribution_h"] >= 0 else "−"
        with st.expander(f"{drv['label']}: {sign}{abs(drv['contribution_h']):.0f} h"):
            st.write(drv["phrase"].capitalize())
            st.caption(f"Top signal: `{drv['top_feature']}` = {drv['value']:.2f}")
    if s.get("stage_forecast_hours"):
        st.markdown("**Where further delay is expected (reconciled stage forecast)**")
        sf = {GROUP_LABEL[k]: v for k, v in s["stage_forecast_hours"].items() if abs(v) >= 0.5}
        if sf:
            fig = go.Figure(
                go.Bar(
                    x=list(sf.values()),
                    y=list(sf.keys()),
                    orientation="h",
                    marker_color=[OK["vermillion"] if v > 0 else OK["green"] for v in sf.values()],
                    text=[dur(v) for v in sf.values()],
                    textposition="outside",
                    cliponaxis=False,
                )
            )
            # pad the x-range so outside labels (incl. negative bars) stay clear of the axis labels
            lo, hi = min(0.0, *sf.values()), max(0.0, *sf.values())
            pad = 0.25 * (hi - lo) + 4
            fig.update_layout(
                height=220,
                margin=dict(l=10, r=60, t=5, b=5),
                xaxis=dict(title="hours", range=[lo - pad if lo < 0 else 0, hi + pad]),
            )
            st.plotly_chart(fig, use_container_width=True)

# ---- recommended actions ----------------------------------------------------------------------
st.markdown("#### Recommended actions")
adv = guard(lambda: api.advise(sid, as_of))
recs = adv["recommendations"]
if not recs:
    st.caption("No feasible interventions at this point of the journey.")
for rec in recs:
    # ✅ pays for itself · ⏱️ saves real time but costs more than it avoids · ▫️ marginal
    if rec["net_value_usd"] > 0:
        icon, verdict = "✅", ""
    elif rec["hours_saved"] > 6:
        icon, verdict = "⏱️", " · saves time, but costs more than the delay it avoids"
    else:
        icon, verdict = "▫️", ""
    line = (
        f"{icon} **{rec['label']}** — saves **{dur(rec['hours_saved']).lstrip('+')}**, "
        f"{usd(rec['usd_saved'])} avoided for {usd(rec['action_cost_usd'])} "
        f"(net {usd(rec['net_value_usd'], signed=True)}); "
        f"P(late) after: {rec['p_late_after']:.0%}  \n"
        f"<span style='opacity:.7'>{rec['description']} · feasible because "
        f"{rec['feasible_reason']}{verdict}</span>"
    )
    # escape "$": two of them in one string would otherwise render as LaTeX math
    st.markdown(line.replace("$", r"\$"), unsafe_allow_html=True)
st.caption(adv["disclaimer"])

with st.expander("API: reproduce this prediction"):
    st.code(
        "curl -X POST $CASCADE_API_URL/v1/predict -H 'Content-Type: application/json' -d '"
        + json.dumps(guard(lambda: api.payload(sid, as_of)))[:4000]
        + "'",
        language="bash",
    )
