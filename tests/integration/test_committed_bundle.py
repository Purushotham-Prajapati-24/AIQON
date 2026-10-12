"""The bundle committed in artifacts/ must load and serve on a fresh clone, on any OS.

Every other test trains its own temporary bundle, so without this file a broken published
bundle (checksums, feature contract, missing files) would only be found by a user (issue #4).
"""

import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from cascade.models.artifacts import _sha256, latest_bundle_dir, load_bundle  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"


def test_checksum_ignores_line_endings(tmp_path):
    lf, crlf = tmp_path / "a.json", tmp_path / "b.json"
    lf.write_bytes(b'{\n "x": 1\n}\n')
    crlf.write_bytes(b'{\r\n "x": 1\r\n}\r\n')
    assert _sha256(lf) == _sha256(crlf)
    # binary files are hashed exactly as stored
    b1, b2 = tmp_path / "a.npz", tmp_path / "b.npz"
    b1.write_bytes(b"\x00\n")
    b2.write_bytes(b"\x00\r\n")
    assert _sha256(b1) != _sha256(b2)


def test_committed_bundle_verifies():
    bundle = load_bundle(latest_bundle_dir(ARTIFACTS))  # verifies checksums + feature contract
    assert bundle.model.version == bundle.manifest["version"]


@pytest.fixture(scope="module")
def client():
    mp = pytest.MonkeyPatch()
    mp.setenv("CASCADE_ARTIFACTS", str(ARTIFACTS))
    from cascade.serving.app import app

    with TestClient(app) as c:
        yield c
    mp.undo()


def test_committed_bundle_serves(client):
    assert client.get("/ready").json()["ready"] is True
    sid = client.get("/v1/shipments").json()[0]["shipment_id"]
    body = client.get(f"/v1/shipments/{sid}/payload").json()
    r = client.post("/v1/predict", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["delay_hours"]["p10"] <= out["delay_hours"]["p50"] <= out["delay_hours"]["p90"]
    assert 0.0 <= out["p_late"] <= 1.0
