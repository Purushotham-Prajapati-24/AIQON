"""Smoke test: verify API boots and serves predictions on the published bundle."""

from __future__ import annotations

from fastapi.testclient import TestClient

from cascade.serving.app import app

with TestClient(app) as client:
    ready = client.get("/ready").json()
    print(ready)
    assert ready.get("ready") is True, ready
    sid = client.get("/v1/shipments").json()[0]["shipment_id"]
    body = client.get(f"/v1/shipments/{sid}/payload").json()
    r = client.post("/v1/predict", json=body)
    assert r.status_code == 200, r.text
    print(sid, r.json()["delay_hours"])
