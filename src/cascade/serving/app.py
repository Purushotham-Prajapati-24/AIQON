"""CASCADE Inference API (FastAPI).

Hot path rules: no disk/DB I/O in /v1/predict, ledger writes are queued, any model failure is
served by the fallback chain with ``flags.degraded=true`` (never a 500 for valid input).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cascade.decision.cost import CostModel
from cascade.decision.engine import Engine, World
from cascade.decision.ledger import Ledger
from cascade.decision.scenarios import Scenario, presets
from cascade.domain.delay import to_datetime, to_hours
from cascade.domain.network import NETWORK
from cascade.domain.stages import EventType, event_sequence
from cascade.models.artifacts import ArtifactError, latest_bundle_dir, load_bundle
from cascade.models.drift import DRIFT_FEATURES, psi
from cascade.models.drift import status as drift_status
from cascade.serving import auth
from cascade.serving.schemas import (
    BatchRequest,
    DemoLoginRequest,
    LoginRequest,
    PredictRequest,
    ScenarioRequest,
    WhatIfRequest,
)
from cascade.sim.external import ExternalSeries

log = logging.getLogger("cascade.api")
ROOT = Path(__file__).resolve().parents[3]
MAX_BODY_BYTES = 2_000_000


class State:
    def __init__(self) -> None:
        self.engine: Engine | None = None
        self.ledger: Ledger | None = None
        self.ready = False
        self.error: str | None = None
        self.insights: dict = {}
        self.auth: auth.Settings | None = None
        self.throttle = auth.Throttle()


S = State()


def _iso(h: float) -> str:
    return to_datetime(h).isoformat().replace("+00:00", "Z")


def load_engine(artifacts: Path | None = None, version: str | None = None) -> Engine:
    root = artifacts or Path(os.environ.get("CASCADE_ARTIFACTS", ROOT / "artifacts"))
    ver = version or os.environ.get("CASCADE_MODEL_VERSION", "latest")
    path = latest_bundle_dir(root) if ver == "latest" else root / f"v{ver.lstrip('v')}"
    bundle = load_bundle(path)
    ext = ExternalSeries.load(path / "external.npz")
    world = World.load(path) if (path / "world_shipments.csv").exists() else None
    return Engine(bundle, ext, CostModel.load(ROOT / "configs" / "costs.yaml"), world)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import json

    # Auth settings are read at startup so a bad value fails loudly instead of on first sign-in.
    S.auth = auth.Settings()
    S.throttle = auth.Throttle()
    try:
        S.engine = load_engine()
        S.insights = (
            json.loads((S.engine.bundle.path / "insights.json").read_text())
            if (S.engine.bundle.path / "insights.json").exists()
            else {}
        )
        S.ledger = Ledger(os.environ.get("CASCADE_LEDGER", ":memory:"))
        _warm_up_and_seed(S.engine, S.ledger)
        S.ready = True
    except (ArtifactError, FileNotFoundError) as exc:
        S.error = str(exc)
        log.error("model not loaded: %s", exc)
    yield
    if S.ledger:
        S.ledger.close()


def _warm_up_and_seed(engine: Engine, ledger: Ledger) -> None:
    """Warm the hot path and seed the ledger with history up to 'now' (live accuracy demo)."""
    w = engine.world
    if w is None:
        return
    for sid, v in list(w.views.items()):
        for cp in w.checkpoints(sid):
            if cp["as_of"] > w.now_h:
                break
            r = engine.predict_many([(v, cp["as_of"])], with_cost=False)[0]
            _log_prediction(ledger, r)
        if w.actual_delivered[sid] <= w.now_h:
            ledger.submit("actuals", {"shipment_id": sid, "total_delay_h": w.total_delay[sid]})
    ledger.flush()


def _log_prediction(ledger: Ledger | None, r) -> None:
    if ledger is None:
        return
    ledger.submit(
        "predictions",
        {
            "shipment_id": r.shipment_id,
            "as_of": r.as_of,
            "model_version": r.model_version,
            "checkpoint": int(r.snapshot.checkpoint) if r.snapshot else -1,
            "lane_id": r.lane_id,
            "delay_p10": r.delay_p10,
            "delay_p50": r.delay_p50,
            "delay_p90": r.delay_p90,
            "p_late": r.p_late,
            "degraded": int(r.flags.get("degraded", False)),
            "features": {k: r.snapshot.features.get(k) for k in DRIFT_FEATURES}
            if r.snapshot
            else None,
        },
    )


def _session(request: Request) -> tuple[auth.User, int] | None:
    """The signed-in user from the session cookie or a Bearer token; None if there is none."""
    settings = S.auth or auth.Settings()
    token = request.cookies.get(auth.COOKIE)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    if not token:
        return None
    try:
        return auth.verify(token, settings)
    except auth.AuthError as exc:
        raise HTTPException(401, str(exc)) from exc


def require_session(request: Request) -> None:
    """Gate for every route: in CASCADE_AUTH=required mode, /v1 data routes need a session."""
    settings = S.auth
    path = request.url.path
    if settings is None or settings.mode != "required" or request.method == "OPTIONS":
        return
    if not path.startswith("/v1/") or path.startswith("/v1/auth/"):
        return
    if _session(request) is None:
        raise HTTPException(401, "sign in required")


app = FastAPI(
    title="CASCADE Inference API",
    version="1.0.0",
    description="Stage-aware shipment ETA, delay propagation, explanations and decisions.",
    lifespan=lifespan,
    dependencies=[Depends(require_session)],
)
# Browsers may send the session cookie only to listed origins (credentials rule out "*").
# Server-to-server clients (TMS, Streamlit) are not affected by CORS.
_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CASCADE_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    length = int(request.headers.get("content-length") or 0)
    if length > MAX_BODY_BYTES:
        return _problem(413, "payload-too-large", f"body exceeds {MAX_BODY_BYTES} bytes", rid)
    t0 = time.perf_counter()
    response = await call_next(request)
    dur = (time.perf_counter() - t0) * 1000
    response.headers["X-Request-ID"] = rid
    response.headers["Server-Timing"] = f"total;dur={dur:.2f}"
    if S.engine:
        response.headers["X-Model-Version"] = S.engine.model.version
    return response


def _problem(
    status: int, kind: str, detail: str, rid: str | None = None, errors=None
) -> JSONResponse:
    body = {
        "type": f"/errors/{kind}",
        "title": kind.replace("-", " ").capitalize(),
        "status": status,
        "detail": detail,
    }
    if errors:
        body["errors"] = errors
    if rid:
        body["request_id"] = rid
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


@app.exception_handler(RequestValidationError)
async def _validation(request: Request, exc: RequestValidationError):
    errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
    return _problem(422, "validation", "request does not satisfy the v1 contract", errors=errs)


@app.exception_handler(HTTPException)
async def _http(request: Request, exc: HTTPException):
    kinds = {
        400: "bad-request",
        401: "unauthorized",
        403: "forbidden",
        404: "not-found",
        413: "payload-too-large",
        429: "too-many-requests",
        503: "not-ready",
    }
    resp = _problem(exc.status_code, kinds.get(exc.status_code, "error"), str(exc.detail))
    if exc.status_code == 401:
        resp.headers["WWW-Authenticate"] = 'Bearer realm="cascade"'
        resp.delete_cookie(auth.COOKIE, path="/")
    return resp


def engine() -> Engine:
    if not S.ready or S.engine is None:
        raise HTTPException(503, S.error or "model not loaded yet")
    return S.engine


def world() -> World:
    w = engine().world
    if w is None:
        raise HTTPException(404, "no demo world in this bundle")
    return w


# ---- health ------------------------------------------------------------------------------------
@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
def ready():
    if not S.ready:
        raise HTTPException(503, S.error or "warming up")
    return {"ready": True, "model_version": S.engine.model.version}


# ---- auth (JWT sessions) ------------------------------------------------------------------------
def _settings() -> auth.Settings:
    if S.auth is None:
        raise HTTPException(503, "auth not initialised")
    return S.auth


def _start_session(response: Response, user: auth.User, bearer: bool) -> dict:
    """Set the session cookie. The token goes in the body only when an API client asks for it,
    so browser JavaScript never sees it."""
    settings = _settings()
    token, exp = auth.issue(user, settings)
    response.set_cookie(
        auth.COOKIE,
        token,
        max_age=settings.ttl_s,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    out = {"user": auth.public(user), "expires_at": exp, "mode": settings.mode}
    return {**out, "token": token} if bearer else out


@app.get("/v1/auth/config", tags=["auth"])
def auth_config():
    st = _settings()
    return {"mode": st.mode, "demo_login": st.demo_login, "session_hours": st.ttl_s / 3600}


@app.get("/v1/auth/demo-users", tags=["auth"])
def demo_users():
    """Demo accounts for one-click sign-in (empty when CASCADE_DEMO_LOGIN=0)."""
    st = _settings()
    if not st.demo_login:
        return {"users": [], "password_hint": None}
    return {
        "users": [auth.public(u) for u in auth.USERS.values()],
        "password_hint": auth.DEMO_PASSWORD if st.demo_password else None,
    }


@app.post("/v1/auth/login", tags=["auth"])
def login(req: LoginRequest, request: Request, response: Response):
    # The client address; behind a proxy, uvicorn takes it from X-Forwarded-For when the proxy is
    # trusted (FORWARDED_ALLOW_IPS, default 127.0.0.1, which covers the Vite dev proxy).
    key = request.client.host if request.client else "unknown"
    if S.throttle.blocked(key):
        raise HTTPException(429, "too many failed sign-ins; wait a minute and try again")
    user = auth.authenticate(req.username, req.password, _settings())
    if user is None:
        S.throttle.fail(key)
        raise HTTPException(401, "wrong username or password")
    S.throttle.clear(key)
    return _start_session(response, user, req.bearer)


@app.post("/v1/auth/demo-login", tags=["auth"])
def demo_login(req: DemoLoginRequest, response: Response):
    if not _settings().demo_login:
        raise HTTPException(403, "demo sign-in is turned off on this server")
    user = auth.USERS.get(req.user_id)
    if user is None:
        raise HTTPException(404, f"unknown demo user {req.user_id}")
    return _start_session(response, user, req.bearer)


@app.get("/v1/auth/me", tags=["auth"])
def me(request: Request):
    """The signed-in user. No credentials at all is an answer (`user: null`), not an error, so a
    browser checking for a session on page load doesn't log a failed request; a credential that
    is invalid, tampered with or expired is still a 401."""
    found = _session(request)
    if found is None:
        return {"user": None, "expires_at": None, "mode": _settings().mode}
    user, exp = found
    return {"user": auth.public(user), "expires_at": exp, "mode": _settings().mode}


@app.post("/v1/auth/logout", tags=["auth"], status_code=204)
def logout(response: Response):
    response.delete_cookie(auth.COOKIE, path="/")
    response.status_code = 204
    return None


@app.get("/v1/model", tags=["ops"])
def model_info():
    e = engine()
    m = e.bundle.manifest
    return {
        "version": m.get("version"),
        "created_at": m.get("created_at"),
        "git_sha": m.get("git_sha"),
        "feature_hash": m.get("feature_hash"),
        "metrics": m.get("metrics"),
        "gates": m.get("gates"),
        "shrink": e.model.shrink,
        "late_blend": e.model.late_blend,
        "ledger": asdict(S.ledger.stats) if S.ledger else None,
    }


# ---- core predictions ----------------------------------------------------------------------------
@app.post("/v1/predict", tags=["predict"])
def predict(req: PredictRequest):
    e = engine()
    r = e.predict(req.shipment.to_view(), to_hours(req.as_of), explain=req.options.explain)
    _log_prediction(S.ledger, r)
    return r.to_json(req.options.audience, req.options.include_waterfall, req.options.top_k)


@app.post("/v1/predict/batch", tags=["predict"])
def predict_batch(req: BatchRequest):
    e = engine()
    t0 = time.perf_counter()
    res = e.predict_many(
        [(it.shipment.to_view(), to_hours(it.as_of)) for it in req.items], explain=False
    )
    for r in res:
        _log_prediction(S.ledger, r)
    return {
        "n": len(res),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
        "results": [r.to_json(include_waterfall=False) for r in res],
    }


@app.post("/v1/explain", tags=["predict"])
def explain(req: PredictRequest):
    e = engine()
    r = e.predict(req.shipment.to_view(), to_hours(req.as_of), explain=True)
    return r.to_json("analyst", True, 20)


@app.post("/v1/whatif", tags=["decide"])
def whatif(req: WhatIfRequest):
    e = engine()
    v, t = req.shipment.to_view(), to_hours(req.as_of)
    base = e.predict(v, t, explain=False, with_promise=False)
    alt = e.predict(v, t, whatif=req.whatif.to_whatif(), explain=True, with_promise=False)
    return {
        "baseline": base.to_json(include_waterfall=False),
        "scenario": alt.to_json(req.options.audience),
        "delta_p50_h": alt.delay_p50 - base.delay_p50,
        "delta_p_late": alt.p_late - base.p_late,
        "delta_cost_usd": alt.cost_usd.get("p50", 0) - base.cost_usd.get("p50", 0),
    }


@app.post("/v1/advise", tags=["decide"])
def advise(req: PredictRequest):
    e = engine()
    base, recs = e.advise(req.shipment.to_view(), to_hours(req.as_of))
    return {
        "baseline": base.to_json(include_waterfall=False),
        "recommendations": [asdict(r) for r in recs],
        "disclaimer": "Advisory: model-based counterfactuals; validate before acting.",
    }


# ---- demo world (fleet, shipments, alerts, scenarios, monitoring) ----------------------------------
def _as_of(as_of: str | None) -> float:
    if as_of is None or not as_of.strip():
        return world().now_h
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, f"bad as_of: {exc}") from exc
    if dt.tzinfo is None:
        raise HTTPException(400, "as_of must be timezone-aware (e.g. 2025-11-02T10:00:00Z)")
    return to_hours(dt)


@app.get("/v1/world", tags=["demo"])
def world_info():
    w = world()
    return {"now": _iso(w.now_h), "now_h": w.now_h, "n_shipments": len(w.views)}


@app.get("/v1/fleet", tags=["demo"])
def fleet(as_of: str | None = None):
    e, w = engine(), world()
    t = _as_of(as_of)
    items, status = [], {}
    for sid in w.views:
        st = w.status(sid, t)
        status[sid] = st
        if st != "DELIVERED":
            items.append((w.views[sid], t))
    res = e.predict_many(items, explain=False, with_promise=False)
    rows = []
    for r in res:
        v = w.views[r.shipment_id]
        lane = NETWORK.lanes[v.lane_id]
        top = max(r.stage_forecast, key=r.stage_forecast.get) if r.stage_forecast else None
        rows.append(
            {
                **{
                    k: r.to_json(include_waterfall=False)[k]
                    for k in (
                        "shipment_id",
                        "lane_id",
                        "eta",
                        "delay_hours",
                        "p_late",
                        "risk_tier",
                        "checkpoint",
                        "cost_usd",
                    )
                },
                "status": status[r.shipment_id],
                "origin": lane.origin,
                "hub": lane.hub,
                "dest": lane.dest,
                "carrier": v.carrier,
                "main_stage": top,
                "missing_events": r.flags["missing_events"],
            }
        )
    delivered = [
        {"shipment_id": sid, "total_delay_h": w.total_delay[sid]}
        for sid, s in status.items()
        if s == "DELIVERED"
    ]
    return {"as_of": _iso(t), "active": rows, "delivered": delivered}


@app.get("/v1/shipments", tags=["demo"])
def list_shipments():
    w = world()
    return [
        {
            "shipment_id": sid,
            "lane_id": v.lane_id,
            "carrier": v.carrier,
            "planned_delivery": _iso(v.planned[EventType.DELIVERED]),
        }
        for sid, v in w.views.items()
    ]


@app.get("/v1/shipments/{sid}", tags=["demo"])
def shipment(
    sid: str,
    as_of: str | None = None,
    audience: str = Query("ops", pattern="^(ops|customer|analyst)$"),
):
    e, w = engine(), world()
    if sid not in w.views:
        raise HTTPException(404, f"unknown shipment {sid}")
    t = _as_of(as_of)
    v = w.view_as_of(sid, t)
    r = e.predict(v, t, explain=True)
    out = r.to_json(audience, True, 8)
    lane = NETWORK.lanes[v.lane_id]
    seq = event_sequence(lane.has_transshipment)
    out["timeline"] = [
        {
            "event": ev.value,
            "planned": _iso(v.planned[ev]),
            "observed": _iso(v.reported[ev]) if ev in v.reported else None,
            "projected": _iso(v.planned[ev] + r.snapshot.projected_delay[ev])
            if r.snapshot and ev in r.snapshot.projected_delay
            else None,
        }
        for ev in seq
    ]
    out["shipment"] = {
        "carrier": v.carrier,
        "commodity_risk": v.commodity_risk,
        "docs_complete": v.docs_complete,
        "inland_mode": v.inland_mode,
        "cargo_value_usd": v.cargo_value_usd,
        "origin": lane.origin,
        "hub": lane.hub,
        "dest": lane.dest,
        "carrier_edi_tier": v.carrier_edi_tier,
    }
    out["status"] = w.status(sid, t)
    if out["status"] == "DELIVERED":
        out["actual_total_delay_h"] = w.total_delay[sid]
    return out


@app.get("/v1/shipments/{sid}/checkpoints", tags=["demo"])
def checkpoints(sid: str):
    w = world()
    if sid not in w.views:
        raise HTTPException(404, f"unknown shipment {sid}")
    # Only milestones already reported by the world's "now": time-travel replays the past.
    return [
        {"label": c["label"], "as_of": _iso(c["as_of"]), "as_of_h": c["as_of"]}
        for c in w.checkpoints(sid)
        if c["as_of"] <= w.now_h
    ]


@app.get("/v1/shipments/{sid}/payload", tags=["demo"])
def payload(sid: str, as_of: str | None = None):
    """A ready-to-POST /v1/predict body for this shipment (API onboarding helper)."""
    w = world()
    if sid not in w.views:
        raise HTTPException(404, f"unknown shipment {sid}")
    t = _as_of(as_of)
    v = w.view_as_of(sid, t)
    return {
        "shipment": {
            "shipment_id": v.shipment_id,
            "lane_id": v.lane_id,
            "carrier": v.carrier,
            "commodity_risk": v.commodity_risk,
            "docs_complete": v.docs_complete,
            "inland_mode": v.inland_mode,
            "cargo_value_usd": v.cargo_value_usd,
            "carrier_edi_tier": v.carrier_edi_tier,
            "planned": {e.value: _iso(h) for e, h in v.planned.items()},
            "observed": {e.value: _iso(h) for e, h in v.reported.items()},
            "reported_at": {e.value: _iso(v.known_at(e)) for e in v.reported},
            "schedule_revisions": [
                {"effective_at": _iso(eff), "planned": {e.value: _iso(h) for e, h in upd.items()}}
                for eff, upd in v.revisions
            ],
        },
        "as_of": _iso(t),
    }


@app.get("/v1/shipments/{sid}/advise", tags=["demo"])
def shipment_advise(sid: str, as_of: str | None = None):
    e, w = engine(), world()
    if sid not in w.views:
        raise HTTPException(404, f"unknown shipment {sid}")
    t = _as_of(as_of)
    base, recs = e.advise(w.view_as_of(sid, t), t)
    return {
        "baseline": base.to_json(include_waterfall=False),
        "recommendations": [asdict(r) for r in recs],
        "disclaimer": "Advisory: model-based counterfactuals; validate before acting.",
    }


@app.get("/v1/shipments/{sid}/whatif", tags=["demo"])
def shipment_whatif(
    sid: str,
    as_of: str | None = None,
    dest_rho: float | None = None,
    hub_priority: bool = False,
    customs_weekend: bool | None = None,
    docs_complete: bool | None = None,
    inland_mode: str | None = None,
    delay_shift_h: float = 0.0,
):
    from cascade.serving.schemas import WhatIfIn

    e, w = engine(), world()
    if sid not in w.views:
        raise HTTPException(404, f"unknown shipment {sid}")
    t = _as_of(as_of)
    wi = WhatIfIn(
        dest_rho=dest_rho,
        hub_priority=hub_priority,
        customs_weekend=customs_weekend,
        docs_complete=docs_complete,
        inland_mode=inland_mode,
        delay_shift_h=delay_shift_h,
    )
    v = w.view_as_of(sid, t)
    base = e.predict(v, t, explain=False, with_promise=False)
    alt = e.predict(v, t, whatif=wi.to_whatif(), explain=True, with_promise=False)
    return {
        "baseline": base.to_json(include_waterfall=False),
        "scenario": alt.to_json(),
        "delta_p50_h": alt.delay_p50 - base.delay_p50,
        "delta_p_late": alt.p_late - base.p_late,
        "delta_cost_usd": alt.cost_usd.get("p50", 0) - base.cost_usd.get("p50", 0),
    }


@app.get("/v1/alerts", tags=["demo"])
def alerts(as_of: str | None = None, window_days: float = Query(7.0, gt=0, le=120)):
    e, w = engine(), world()
    t = _as_of(as_of)
    out = []
    for sid in w.views:
        if w.status(sid, t) == "DELIVERED":
            continue
        _, al = e.replay_decisions(w.view_as_of(sid, t), t)
        out.extend(
            {**asdict(a), "created_at": _iso(a.created_at), "age_h": round(t - a.created_at, 1)}
            for a in al
            if t - a.created_at <= window_days * 24
        )
    rank = {"critical": 0, "warn": 1, "info": 2}
    out.sort(key=lambda a: (rank[a["severity"]], a["age_h"]))
    return {"as_of": _iso(t), "window_days": window_days, "n": len(out), "alerts": out}


@app.get("/v1/scenarios/presets", tags=["demo"])
def scenario_presets():
    return [asdict(s) for s in presets(world().now_h)]


@app.post("/v1/scenarios/impact", tags=["decide"])
def scenario_impact(req: ScenarioRequest):
    e, w = engine(), world()
    t = to_hours(req.as_of) if req.as_of else w.now_h
    if req.preset:
        sc = {s.scenario_id: s for s in presets(t)}.get(req.preset)
        if sc is None:
            raise HTTPException(404, f"unknown preset {req.preset}")
    else:
        if not (req.kind and req.target and req.delta is not None):
            raise HTTPException(400, "custom scenario needs kind, target and delta")
        sc = Scenario(
            "custom",
            f"{req.kind} {req.delta:+.2f} at {req.target}",
            req.kind,
            req.target,
            req.delta,
            t,
            req.duration_h,
        )
    items = [(w.view_as_of(sid, t), t) for sid in w.views if w.status(sid, t) != "DELIVERED"]
    try:
        return e.scenario_impact(sc, items)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/v1/monitoring/accuracy", tags=["monitor"])
def monitoring():
    if S.ledger is None:
        raise HTTPException(503, "ledger unavailable")
    S.ledger.flush(1.0)
    return {
        "by_checkpoint": S.ledger.accuracy(),
        "by_lane": S.ledger.lane_trust(),
        "ledger": asdict(S.ledger.stats)
        | {
            "durable": S.ledger.path != ":memory:",
            "mode": "best-effort telemetry (bounded queue; overflow dropped and counted)",
        },
    }


@app.get("/v1/monitoring/drift", tags=["monitor"])
def monitoring_drift():
    """Live feature drift: PSI of logged predictions vs the training reference in the bundle."""
    if S.ledger is None or S.engine is None:
        raise HTTPException(503, "ledger unavailable")
    S.ledger.flush(1.0)
    ref = S.engine.model.drift_ref
    feats = S.ledger.logged_features()
    if not ref or not feats:
        return {
            "n": len(feats),
            "features": {},
            "note": "no reference or no logged predictions yet",
        }
    out = {}
    for name, r in ref.items():
        vals = np.array([f.get(name) if f.get(name) is not None else np.nan for f in feats], float)
        v = psi(r, vals)
        out[name] = {"psi": round(v, 4), "status": drift_status(v)}
    return {
        "n": len(feats),
        "features": out,
        "rule": "PSI < 0.1 stable · 0.1-0.2 watch · > 0.2 drift",
    }


@app.get("/v1/insights", tags=["monitor"])
def insights():
    engine()
    return S.insights


@app.get("/v1/data-health", tags=["monitor"])
def data_health():
    w = world()
    ev = w.events.merge(w.shipments[["shipment_id", "carrier", "dest"]], on="shipment_id")
    ev = ev[ev.event != "DELIVERED"]
    by_carrier = ev.groupby(["carrier", "event"]).reported.mean().unstack().round(3)
    by_dest = ev.groupby("dest").reported.mean().round(3)
    return {
        "completeness_by_carrier_event": by_carrier.fillna(-1).to_dict(orient="index"),
        "completeness_by_destination": by_dest.to_dict(),
        "overall_completeness": float(ev.reported.mean()),
    }
