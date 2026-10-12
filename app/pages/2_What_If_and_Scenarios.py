"""What-If Lab (one shipment) and Disruption Impact Radar (whole fleet)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import pandas as pd
import streamlit as st

import api_client as api
from ui import TIER, dur, guard, kpi, setup

setup("What-if")
st.markdown("## 🧪 What-If Lab & Disruption Radar")
tab1, tab2 = st.tabs(["Single shipment what-if", "Fleet disruption radar"])

with tab1:
    ships = guard(api.shipments)
    ids = [s["shipment_id"] for s in ships]
    if "shipment" not in st.session_state:  # default: the riskiest active shipment right now
        active = guard(lambda: api.fleet(st.session_state.get("as_of")))["active"]
        st.session_state["shipment"] = (
            max(active, key=lambda r: r["p_late"])["shipment_id"] if active else ids[0]
        )
    sid = st.selectbox("Shipment", ids, index=ids.index(st.session_state["shipment"]))
    st.session_state["shipment"] = sid
    c = st.columns(3)
    rho = c[0].slider(
        "Destination berth utilisation",
        0.50,
        0.97,
        0.75,
        0.01,
        help="Override the congestion forecast at the destination port",
    )
    use_rho = c[0].checkbox("Apply utilisation override", value=False)
    shift = c[1].slider("Extra delay at the last milestone (h)", 0, 96, 0, 6)
    docs = c[2].selectbox("Customs documents", ["as is", "complete", "incomplete"])
    c2 = st.columns(3)
    hub = c2[0].checkbox("Priority transshipment handling")
    wk = c2[1].selectbox("Weekend customs", ["as is", "available", "not available"])
    mode = c2[2].selectbox("Final leg", ["as is", "truck", "rail"])
    params = {
        "dest_rho": rho if use_rho else None,
        "delay_shift_h": shift or None,
        "docs_complete": {"as is": None, "complete": True, "incomplete": False}[docs],
        "hub_priority": hub or None,
        "customs_weekend": {"as is": None, "available": True, "not available": False}[wk],
        "inland_mode": None if mode == "as is" else mode,
    }
    res = guard(
        lambda: api.whatif(
            sid, st.session_state.get("as_of"), **{k: v for k, v in params.items() if v is not None}
        )
    )
    b, s = res["baseline"], res["scenario"]
    k = st.columns(4)
    kpi(k[0], "Baseline delay P50", dur(b["delay_hours"]["p50"]), f"P(late) {b['p_late']:.0%}")
    kpi(k[1], "Scenario delay P50", dur(s["delay_hours"]["p50"]), f"P(late) {s['p_late']:.0%}")
    kpi(k[2], "Δ ETA", dur(res["delta_p50_h"]), "negative = earlier")
    kpi(k[3], "Δ expected cost", f"${res['delta_cost_usd']:,.0f}", "illustrative tariffs")
    st.markdown(
        f"<div class='narr' style='margin-top:12px'>{s['narrative']}</div>", unsafe_allow_html=True
    )
    st.caption(
        "Counterfactuals are model-based (associational). On synthetic data they are validated against "
        "true simulator interventions — see Model insights → Advisor fidelity."
    )

with tab2:
    pre = guard(api.presets)
    labels = {p["scenario_id"]: p["label"] for p in pre}
    mode2 = st.radio("Scenario", ["Preset", "Custom"], horizontal=True)
    if mode2 == "Preset":
        pid = st.selectbox("Preset disruption", list(labels), format_func=labels.get)
        body = {"preset": pid}
    else:
        c = st.columns(4)
        kind = c[0].selectbox("Kind", ["congestion", "weather"])
        target = c[1].selectbox(
            "Target",
            ["SGSIN", "NLRTM", "DEHAM", "BEANR", "GBFXT", "USLAX", "LKCMB", "AEJEA", "MYTPP"]
            if kind == "congestion"
            else [
                "INDIAN_OCEAN",
                "SOUTH_CHINA_SEA",
                "NORTH_PACIFIC",
                "ARABIAN_SEA",
                "NORTH_EUROPE",
            ],
        )
        delta = c[2].slider("Shock size", 0.05, 0.6, 0.15, 0.05)
        days = c[3].slider("Duration (days)", 1, 21, 5)
        body = {"kind": kind, "target": target, "delta": delta, "duration_h": days * 24.0}
    if st.session_state.get("as_of"):
        body["as_of"] = st.session_state["as_of"]
    if st.button("Run impact analysis", type="primary"):
        with st.spinner("Re-scoring every active shipment under the scenario…"):
            imp = guard(lambda: api.scenario_impact(body))
        k = st.columns(4)
        kpi(k[0], "Active shipments", str(imp["n_shipments"]))
        kpi(k[1], "Affected (>1 h)", str(imp["n_affected"]))
        kpi(
            k[2],
            "Δ shipments ■ Late",
            f"{imp['delta_late_count']:+d}",
            f"Σ ΔP(late) {imp['delta_expected_late']:+.1f}",
        )
        kpi(k[3], "Δ expected cost", f"${imp['delta_cost_usd']:,.0f}")
        if imp["affected"]:
            df = pd.DataFrame(imp["affected"])
            df["tier"] = (
                df.tier_before.map(lambda t: TIER[t][0])
                + " → "
                + df.tier_after.map(lambda t: TIER[t][0])
            )
            st.dataframe(
                df[
                    [
                        "shipment_id",
                        "lane_id",
                        "delta_p50_h",
                        "p_late_before",
                        "p_late_after",
                        "tier",
                        "delta_cost_usd",
                    ]
                ],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "delta_p50_h": st.column_config.NumberColumn("Δ delay (h)", format="%+.1f"),
                    "p_late_before": st.column_config.NumberColumn(
                        "P(late) before", format="percent"
                    ),
                    "p_late_after": st.column_config.NumberColumn(
                        "P(late) after", format="percent"
                    ),
                    "delta_cost_usd": st.column_config.NumberColumn("Δ cost", format="$%.0f"),
                },
            )
        else:
            st.info("No active shipment's remaining journey crosses this disruption.")
