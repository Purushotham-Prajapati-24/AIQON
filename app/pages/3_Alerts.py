"""Alerts inbox: rules over consecutive predictions, each with a narrative."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import streamlit as st

import api_client as api
from ui import guard, setup, ts

setup("Alerts")
st.markdown("## 🔔 Alerts inbox")
window = st.slider("Show alerts raised in the last N days", 1, 30, 7)
res = guard(lambda: api.alerts(st.session_state.get("as_of"), float(window)))
st.caption(
    f"As of {ts(res['as_of'], '%d %b %Y %H:%M')} UTC · {res['n']} alert(s) · "
    "rules: tier escalation, promise moved, P(late) jump, silent shipment, missed connection likely"
)
icon = {"critical": "🟥", "warn": "🟧", "info": "🟦"}
rules = sorted({a["rule"] for a in res["alerts"]})
pick = st.multiselect("Rule", rules)
for a in res["alerts"]:
    if pick and a["rule"] not in pick:
        continue
    c = st.columns([1, 6, 1])
    c[0].markdown(f"{icon[a['severity']]} **{a['severity'].upper()}**")
    change = ""
    if a.get("new_risk"):
        p_prev = a.get("previous_p_late")
        change = (
            f"Risk {a.get('previous_risk') or 'new'} → **{a['new_risk']}** · P(late) "
            + (f"{p_prev:.0%} → " if p_prev is not None else "")
            + f"{a['new_p_late']:.0%} · Next step: {a.get('recommended_next_step', '')}  \n"
        )
    dq = ", ".join(a.get("data_quality_flags", []))
    c[1].markdown(
        f"**{a['shipment_id']} · {a['rule'].replace('_', ' ').title()}** — {a['message']}  \n"
        + change
        + f"<span style='opacity:.65'>{'Data: ' + dq + ' · ' if dq else ''}evidence as of "
        f"{ts(a['created_at'], '%d %b %H:%M')} ({a['age_h']:.0f} h ago)</span>",
        unsafe_allow_html=True,
    )
    if c[2].button("Open", key=a["alert_id"]):
        st.session_state["shipment"] = a["shipment_id"]
        st.switch_page("pages/1_Shipment_Detail.py")
