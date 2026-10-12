"""Load profile for the CASCADE inference API (optional; not part of the pytest suite).

Each simulated client fetches real request bodies once from ``/v1/shipments/{id}/payload``
and then replays them against ``/v1/predict``, the hot path a TMS integration would call.

    pip install locust
    locust -f tests/perf/locustfile.py --host http://127.0.0.1:8000 \
        --headless -u 50 -r 10 -t 1m

Budget (docs/Architecture.md): p95 < 50 ms for predict + explain on a single worker.
"""

from __future__ import annotations

import random

from locust import HttpUser, between, task

N_PAYLOADS = 20


class TmsClient(HttpUser):
    wait_time = between(0.05, 0.2)

    def on_start(self) -> None:
        ships = self.client.get("/v1/shipments", name="/v1/shipments").json()
        ids = [s["shipment_id"] for s in random.sample(ships, min(N_PAYLOADS, len(ships)))]
        self.payloads = [
            self.client.get(
                f"/v1/shipments/{sid}/payload", name="/v1/shipments/[id]/payload"
            ).json()
            for sid in ids
        ]

    @task(10)
    def predict(self) -> None:
        self.client.post("/v1/predict", json=random.choice(self.payloads), name="/v1/predict")

    @task(2)
    def predict_batch(self) -> None:
        self.client.post(
            "/v1/predict/batch",
            json={"items": random.sample(self.payloads, min(5, len(self.payloads)))},
            name="/v1/predict/batch",
        )

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="/health")
