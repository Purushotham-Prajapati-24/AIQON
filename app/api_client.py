"""Thin HTTP client for the CASCADE API (the UI never imports model code)."""

from __future__ import annotations

import os

import httpx
import streamlit as st

API = os.environ.get("CASCADE_API_URL", "http://127.0.0.1:8000")
_client = httpx.Client(base_url=API, timeout=30.0)


class ApiError(RuntimeError):
    pass


def _get(path: str, **params):
    try:
        r = _client.get(path, params={k: v for k, v in params.items() if v is not None})
    except httpx.HTTPError as exc:
        raise ApiError(
            f"Cannot reach the CASCADE API at {API} ({exc.__class__.__name__}). "
            "Start it with:  uv run cascade serve"
        ) from exc
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text
        raise ApiError(f"API {r.status_code}: {detail}")
    return r.json()


def _post(path: str, body: dict):
    try:
        r = _client.post(path, json=body)
    except httpx.HTTPError as exc:
        raise ApiError(f"Cannot reach the CASCADE API at {API}") from exc
    if r.status_code >= 400:
        raise ApiError(f"API {r.status_code}: {r.json().get('detail')}")
    return r.json()


@st.cache_data(ttl=30, show_spinner=False)
def world():
    return _get("/v1/world")


@st.cache_data(ttl=300, show_spinner=False)
def model():
    return _get("/v1/model")


@st.cache_data(ttl=60, show_spinner=False)
def fleet(as_of: str | None):
    return _get("/v1/fleet", as_of=as_of)


@st.cache_data(ttl=300, show_spinner=False)
def shipments():
    return _get("/v1/shipments")


@st.cache_data(ttl=300, show_spinner=False)
def shipment(sid: str, as_of: str | None, audience: str = "ops"):
    return _get(f"/v1/shipments/{sid}", as_of=as_of, audience=audience)


@st.cache_data(ttl=300, show_spinner=False)
def checkpoints(sid: str):
    return _get(f"/v1/shipments/{sid}/checkpoints")


@st.cache_data(ttl=300, show_spinner=False)
def advise(sid: str, as_of: str | None):
    return _get(f"/v1/shipments/{sid}/advise", as_of=as_of)


@st.cache_data(ttl=300, show_spinner=False)
def whatif(sid: str, as_of: str | None, **kw):
    return _get(f"/v1/shipments/{sid}/whatif", as_of=as_of, **kw)


@st.cache_data(ttl=60, show_spinner=False)
def alerts(as_of: str | None, window_days: float = 7.0):
    return _get("/v1/alerts", as_of=as_of, window_days=window_days)


@st.cache_data(ttl=300, show_spinner=False)
def presets():
    return _get("/v1/scenarios/presets")


def scenario_impact(body: dict):
    return _post("/v1/scenarios/impact", body)


@st.cache_data(ttl=300, show_spinner=False)
def insights():
    return _get("/v1/insights")


@st.cache_data(ttl=30, show_spinner=False)
def monitoring():
    return _get("/v1/monitoring/accuracy")


@st.cache_data(ttl=300, show_spinner=False)
def data_health():
    return _get("/v1/data-health")


@st.cache_data(ttl=300, show_spinner=False)
def payload(sid: str, as_of: str | None):
    return _get(f"/v1/shipments/{sid}/payload", as_of=as_of)
