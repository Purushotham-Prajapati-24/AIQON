"""API contract: readiness, validation (RFC 7807), predictions, decisions, integrity checks."""

import json
import warnings

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from cascade.models.artifacts import ArtifactError, load_bundle  # noqa: E402


@pytest.fixture(scope="module")
def client(bundle_dir, monkeypatch_module):
    monkeypatch_module.setenv("CASCADE_ARTIFACTS", str(bundle_dir))
    from cascade.serving.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def body(client):
    sid = client.get("/v1/shipments").json()[0]["shipment_id"]
    return client.get(f"/v1/shipments/{sid}/payload").json()


def test_health_ready_model(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json()["ready"] is True
    m = client.get("/v1/model").json()
    assert m["version"] == "0.0.1" and m["feature_hash"]


def test_predict_contract_and_headers(client, body):
    r = client.post("/v1/predict", json=body)
    assert r.status_code == 200
    j = r.json()
    for k in (
        "eta",
        "delay_hours",
        "p_late",
        "risk_tier",
        "drivers",
        "waterfall",
        "narrative",
        "flags",
        "promise",
        "cost_usd",
    ):
        assert k in j
    assert j["delay_hours"]["p10"] <= j["delay_hours"]["p50"] <= j["delay_hours"]["p90"]
    assert r.headers["x-model-version"] == "0.0.1"
    assert "server-timing" in r.headers and "x-request-id" in r.headers


def test_customer_audience_hides_internals(client, body):
    j = client.post("/v1/predict", json={**body, "options": {"audience": "customer"}}).json()
    assert "drivers" not in j and "waterfall" not in j
    assert "Carrier" not in j["narrative"]


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda b: b.update(as_of=b["as_of"].replace("Z", "")), "timezone"),
        (lambda b: b["shipment"].update(lane_id="XXX-YYY"), "unknown lane_id"),
        (lambda b: b["shipment"].update(commodity_risk=7), "less than or equal"),
        (lambda b: b.update(as_of="2025-01-02T00:00:00Z"), "after as_of"),
    ],
)
def test_validation_problems(client, body, mutate, needle):
    b = json.loads(json.dumps(body))
    if not b["shipment"]["observed"] and needle == "after as_of":
        pytest.skip("no observed events to violate")
    mutate(b)
    r = client.post("/v1/predict", json=b)
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert needle.lower() in json.dumps(r.json()).lower()


def test_batch_explain_whatif_advise(client, body):
    r = client.post("/v1/predict/batch", json={"items": [body] * 20}).json()
    assert r["n"] == 20
    ex = client.post("/v1/explain", json=body).json()
    assert "feature_contributions_h" in ex
    wi = client.post("/v1/whatif", json={**body, "whatif": {"dest_rho": 0.5}}).json()
    assert "delta_p50_h" in wi
    adv = client.post("/v1/advise", json=body).json()
    assert "recommendations" in adv


def test_world_endpoints(client):
    assert client.get("/v1/fleet").status_code == 200
    assert client.get("/v1/alerts").status_code == 200
    assert client.get("/v1/scenarios/presets").status_code == 200
    r = client.post("/v1/scenarios/impact", json={"preset": "rtm_surge"}).json()
    assert {"n_affected", "delta_late_count", "delta_cost_usd"} <= set(r)
    assert client.get("/v1/monitoring/accuracy").status_code == 200
    assert client.get("/v1/shipments/NOPE").status_code == 404


def test_time_travel_never_goes_past_now(client):
    now_h = client.get("/v1/world").json()["now_h"]
    for s in client.get("/v1/shipments").json():
        cps = client.get(f"/v1/shipments/{s['shipment_id']}/checkpoints").json()
        assert all(c["as_of_h"] <= now_h for c in cps), s["shipment_id"]
    sid = client.get("/v1/shipments").json()[0]["shipment_id"]
    assert client.get(f"/v1/shipments/{sid}", params={"as_of": ""}).status_code == 200


def test_tampered_bundle_is_refused(bundle_dir, tmp_path):
    import shutil

    src = next(bundle_dir.glob("v*"))
    dst = tmp_path / src.name
    shutil.copytree(src, dst)
    f = dst / "models" / "q50.txt"
    f.write_text(f.read_text() + "\n")
    with pytest.raises(ArtifactError):
        load_bundle(dst)


def test_prediction_carries_data_quality_and_explanation_mode(client, body):
    r = client.post("/v1/predict", json=body).json()
    dq = r["data_quality"]
    assert dq["mode"] == "model"
    assert dq["confidence_reason"] in {"horizon", "missing_data", "stale_data", "fallback"}
    assert {"last_milestone", "next_expected", "missing_critical", "source_tier"} <= set(dq)
    assert r["explanation"]["mode"] in {"rulebook", "rulebook+learned", "learned"}


def test_alerts_carry_the_explanation_contract(client):
    alerts = client.get("/v1/alerts", params={"window_days": 120}).json()["alerts"]
    assert alerts
    for a in alerts:
        assert a["reason_code"] == a["rule"]
        assert a["new_risk"] in {"ON_TRACK", "AT_RISK", "LATE"}
        assert a["recommended_next_step"]


def test_reported_at_before_event_is_rejected(client, body):
    import copy

    b = copy.deepcopy(body)
    obs = b["shipment"]["observed"]
    if not obs:
        return
    e, t = next(iter(obs.items()))
    b["shipment"]["reported_at"] = {e: "2000-01-01T00:00:00Z"}
    assert client.post("/v1/predict", json=b).status_code == 422


def test_advise_is_valid_json_at_every_checkpoint(client):
    """Regression: a passed action deadline must not serialise as -inf (invalid JSON -> 500)."""
    ships = [s["shipment_id"] for s in client.get("/v1/shipments").json()][:12]
    for sid in ships:
        for cp in client.get(f"/v1/shipments/{sid}/checkpoints").json():
            r = client.get(f"/v1/shipments/{sid}/advise", params={"as_of": cp["as_of"]})
            assert r.status_code == 200, (sid, cp["label"], r.text[:200])


def test_schedule_revisions_are_reported_beside_the_original_commitment(client, body):
    import copy

    b = copy.deepcopy(body)
    planned = b["shipment"]["planned"]
    as_of = b["as_of"]
    b["shipment"]["schedule_revisions"] = [
        {"effective_at": "2000-01-01T00:00:00Z", "planned": {"DELIVERED": planned["DELIVERED"]}},
        {"effective_at": "2099-01-01T00:00:00Z", "planned": {"DELIVERED": "2099-02-01T00:00:00Z"}},
    ]
    r = client.post("/v1/predict", json=b).json()
    sc = r["schedule"]
    assert sc["revisions_known"] == 1  # the 2099 revision is not known yet at as_of
    assert sc["original_planned_delivery"] == r["planned_delivery"]
    assert sc["delay_vs_original_commitment_h"] == r["delay_hours"]["p50"]
    assert as_of
