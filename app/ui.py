"""Shared UI vocabulary: palette, formatting, chips and charts (Okabe-Ito, never colour-only)."""

from __future__ import annotations

from datetime import datetime

import plotly.graph_objects as go
import streamlit as st

OK = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "vermillion": "#D55E00",
    "sky": "#56B4E9",
    "purple": "#CC79A7",
    "yellow": "#F0E442",
    "grey": "#8C8C8C",
    "ink": "#1F2933",
}
TIER = {
    "ON_TRACK": ("On track", OK["green"], "●"),
    "AT_RISK": ("At risk", OK["orange"], "▲"),
    "LATE": ("Late", OK["vermillion"], "■"),
}
GROUP_LABEL = {
    "ORIGIN": "Origin",
    "OCEAN": "Ocean transit",
    "TRANSSHIPMENT": "Transshipment",
    "PORT": "Destination port",
    "CUSTOMS": "Customs",
    "INLAND": "Inland & delivery",
    "CONTEXT": "Route context",
    "DATA_QUALITY": "Data quality",
}
PORT_NAMES = {
    "CNSHA": "Shanghai",
    "CNYTN": "Yantian",
    "KRPUS": "Busan",
    "INNSA": "Nhava Sheva",
    "VNSGN": "Ho Chi Minh City",
    "SGSIN": "Singapore",
    "LKCMB": "Colombo",
    "AEJEA": "Jebel Ali",
    "MYTPP": "Tanjung Pelepas",
    "NLRTM": "Rotterdam",
    "DEHAM": "Hamburg",
    "BEANR": "Antwerp",
    "GBFXT": "Felixstowe",
    "USLAX": "Los Angeles",
}
PORT_LL = {
    "CNSHA": (31.23, 121.47),
    "CNYTN": (22.57, 114.27),
    "KRPUS": (35.10, 129.04),
    "INNSA": (18.95, 72.95),
    "VNSGN": (10.77, 106.70),
    "SGSIN": (1.26, 103.84),
    "LKCMB": (6.94, 79.84),
    "AEJEA": (25.01, 55.06),
    "MYTPP": (1.36, 103.55),
    "NLRTM": (51.95, 4.14),
    "DEHAM": (53.54, 9.97),
    "BEANR": (51.26, 4.40),
    "GBFXT": (51.96, 1.33),
    "USLAX": (33.74, -118.27),
}

CSS = """
<style>
.block-container {padding-top: 1.6rem; max-width: 1280px;}
.kpi {border: 1px solid rgba(128,128,128,.25); border-radius: 12px; padding: 14px 16px; height: 100%;}
.kpi .v {font-size: 1.7rem; font-weight: 700; line-height: 1.15;}
.kpi .l {font-size: .78rem; opacity: .75; text-transform: uppercase; letter-spacing: .04em;}
.kpi .s {font-size: .8rem; opacity: .75;}
.chip {display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem; font-weight: 600;
       border: 1px solid currentColor; margin-right: 6px;}
.eta {border-radius: 14px; padding: 16px 18px; border: 1px solid rgba(128,128,128,.25);}
.eta .big {font-size: 1.9rem; font-weight: 750;}
.narr {border-left: 4px solid #0072B2; padding: 10px 14px; border-radius: 6px; background: rgba(0,114,178,.06);}
</style>
"""


def setup(title: str) -> None:
    st.set_page_config(page_title=f"CASCADE · {title}", page_icon="🚢", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)


def tier_chip(tier: str) -> str:
    label, color, icon = TIER.get(tier, (tier, OK["grey"], "?"))
    return f'<span class="chip" style="color:{color}">{icon} {label}</span>'


def kpi(col, label: str, value: str, sub: str = "") -> None:
    col.markdown(
        f'<div class="kpi"><div class="l">{label}</div><div class="v">{value}</div>'
        f'<div class="s">{sub}</div></div>',
        unsafe_allow_html=True,
    )


def dur(h: float) -> str:
    a = abs(h)
    s = f"{a / 24:.1f} d" if a >= 48 else f"{a:.0f} h"
    return ("+" if h > 0.5 else "−" if h < -0.5 else "") + s


def usd(x: float, signed: bool = False) -> str:
    """Money with a proper minus sign: −$194, +$952 (signed) and never "$-0"."""
    v = round(x)
    if v == 0:
        return "$0"
    s = f"${abs(v):,.0f}"
    return "−" + s if v < 0 else ("+" if signed else "") + s


def ts(iso: str, fmt: str = "%a %d %b %H:%M") -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime(fmt)


def guard(fn):
    """Render a friendly error state instead of a traceback."""
    from api_client import ApiError

    try:
        return fn()
    except ApiError as exc:
        st.error(str(exc), icon="🔌")
        st.stop()


def waterfall_chart(items: list[dict], height: int = 360) -> go.Figure:
    measure, x, y, text = [], [], [], []
    for it in items:
        y.append(it["label"] if len(it["label"]) < 44 else it["label"][:42] + "…")
        if it["kind"] == "total":
            measure.append("total")
        else:
            measure.append("relative")
        x.append(it["hours"])
        text.append(dur(it["hours"]))
    fig = go.Figure(
        go.Waterfall(
            orientation="h",
            measure=measure,
            y=y,
            x=x,
            text=text,
            textposition="outside",
            cliponaxis=False,
            connector={"line": {"color": "rgba(128,128,128,.4)"}},
            increasing={"marker": {"color": OK["vermillion"]}},
            decreasing={"marker": {"color": OK["green"]}},
            totals={"marker": {"color": OK["blue"]}},
        )
    )
    # mark forecast bars (hatched) vs realized (solid)
    kinds = [it["kind"] for it in items]
    fig.update_yaxes(
        autorange="reversed",
        ticktext=[
            ("◦ " if k in ("forecast", "baseline", "guardrail") else "● ") + yy
            for k, yy in zip(kinds, y, strict=True)
        ],
        tickvals=y,
    )
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=70, t=10, b=10),
        showlegend=False,
        xaxis_title="hours vs plan   (● realized · ◦ forecast)",
    )
    return fig


def timeline_chart(timeline: list[dict]) -> go.Figure:
    """Planned vs observed vs projected milestone times."""
    fig = go.Figure()
    names = [t["event"].replace("_", " ").title() for t in timeline]
    fig.add_trace(
        go.Scatter(
            x=[t["planned"] for t in timeline],
            y=names,
            mode="markers",
            name="Planned",
            marker=dict(symbol="line-ns-open", size=16, color=OK["grey"], line=dict(width=2)),
        )
    )
    obs = [(t["observed"], n) for t, n in zip(timeline, names, strict=True) if t["observed"]]
    if obs:
        fig.add_trace(
            go.Scatter(
                x=[o[0] for o in obs],
                y=[o[1] for o in obs],
                mode="markers",
                name="Observed",
                marker=dict(symbol="circle", size=11, color=OK["ink"]),
            )
        )
    proj = [(t["projected"], n) for t, n in zip(timeline, names, strict=True) if t["projected"]]
    if proj:
        fig.add_trace(
            go.Scatter(
                x=[p[0] for p in proj],
                y=[p[1] for p in proj],
                mode="markers",
                name="Projected",
                marker=dict(symbol="diamond-open", size=11, color=OK["blue"], line=dict(width=2)),
            )
        )
    for t, n in zip(timeline, names, strict=True):
        end = t["observed"] or t["projected"]
        if end:
            fig.add_trace(
                go.Scatter(
                    x=[t["planned"], end],
                    y=[n, n],
                    mode="lines",
                    showlegend=False,
                    line=dict(color="rgba(213,94,0,.45)", width=3),
                )
            )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(
        height=330, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.08, x=0)
    )
    return fig
