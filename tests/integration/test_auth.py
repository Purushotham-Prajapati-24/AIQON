"""JWT session auth: sign-in, cookie and Bearer sessions, expiry, tampering, demo users, enforcement."""

import contextlib
import time
import warnings

import jwt
import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
from fastapi.testclient import TestClient  # noqa: E402

from cascade.serving import auth  # noqa: E402

SECRET = "test-secret-" + "x" * 40


@contextlib.contextmanager
def make_client(bundle_dir, **env):
    mp = pytest.MonkeyPatch()
    mp.setenv("CASCADE_ARTIFACTS", str(bundle_dir))
    mp.setenv("CASCADE_JWT_SECRET", SECRET)
    for k, v in env.items():
        mp.setenv(k, v)
    from cascade.serving.app import app

    try:
        with TestClient(app) as c:
            yield c
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def client(bundle_dir):
    with make_client(bundle_dir) as c:
        yield c


def test_config_and_demo_users(client):
    cfg = client.get("/v1/auth/config").json()
    assert cfg == {"mode": "optional", "demo_login": True, "session_hours": 8.0}
    users = client.get("/v1/auth/demo-users").json()
    assert {u["id"] for u in users["users"]} == {"priya", "marco", "lena", "reviewer"}
    assert all("password" not in u for u in users["users"])


def test_password_login_sets_httponly_cookie(client):
    bad = client.post("/v1/auth/login", json={"username": "priya", "password": "nope"})
    assert bad.status_code == 401
    assert bad.headers["content-type"].startswith("application/problem+json")
    assert bad.headers["www-authenticate"].startswith("Bearer")

    r = client.post("/v1/auth/login", json={"username": "Priya", "password": auth.DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "planner"
    assert "token" not in r.json()  # browsers get the cookie only; JavaScript never sees the JWT
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    me = client.get("/v1/auth/me").json()
    assert me["user"]["id"] == "priya" and me["expires_at"] > time.time()

    assert client.post("/v1/auth/logout").status_code == 204
    client.cookies.clear()
    signed_out = client.get("/v1/auth/me")
    assert signed_out.status_code == 200 and signed_out.json()["user"] is None


def test_bearer_token_and_tampering(client):
    token = client.post("/v1/auth/demo-login", json={"user_id": "lena", "bearer": True}).json()[
        "token"
    ]
    client.cookies.clear()
    ok = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert ok.json()["user"]["id"] == "lena"

    head, body, sig = token.split(".")
    forged = jwt.encode(
        {**jwt.decode(token, options={"verify_signature": False}), "sub": "priya"},
        "wrong-key-" + "y" * 30,
        algorithm="HS256",
    )
    for bad in (f"{head}.{body}.{sig[:-2]}AA", forged, "not-a-jwt"):
        r = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401 and r.json()["detail"] == "invalid session"


def test_expired_session_is_rejected(client):
    now = int(time.time())
    claims = {"iss": "cascade", "sub": "marco", "iat": now - 7200, "exp": now - 60}
    old = jwt.encode(claims, SECRET, algorithm="HS256")
    r = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 401 and r.json()["detail"] == "session expired"


def test_demo_login_unknown_user(client):
    assert client.post("/v1/auth/demo-login", json={"user_id": "mallory"}).status_code == 404


def test_optional_mode_keeps_api_open(client):
    client.cookies.clear()
    assert client.get("/v1/world").status_code == 200


def test_required_mode_gates_data_routes(bundle_dir):
    # An open demo that still exercises sessions: demo sign-in must be switched on explicitly.
    with make_client(bundle_dir, CASCADE_AUTH="required", CASCADE_DEMO_LOGIN="1") as c:
        assert c.get("/health").status_code == 200
        assert c.get("/v1/auth/config").json()["mode"] == "required"
        r = c.get("/v1/world")
        assert r.status_code == 401 and r.json()["detail"] == "sign in required"
        c.post("/v1/auth/demo-login", json={"user_id": "reviewer"})
        assert c.get("/v1/world").status_code == 200
        assert c.get("/v1/fleet").status_code == 200


def test_required_mode_needs_a_real_password(bundle_dir, monkeypatch):
    monkeypatch.setenv("CASCADE_AUTH", "required")
    monkeypatch.delenv("CASCADE_DEMO_LOGIN", raising=False)
    monkeypatch.delenv("CASCADE_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="CASCADE_PASSWORD"):
        auth.Settings()  # the demo password is public, so it can't guard required mode
    password = "correct-horse-battery"
    with make_client(bundle_dir, CASCADE_AUTH="required", CASCADE_PASSWORD=password) as c:
        assert c.get("/v1/auth/config").json()["demo_login"] is False
        assert c.get("/v1/auth/demo-users").json() == {"users": [], "password_hint": None}
        assert c.post("/v1/auth/demo-login", json={"user_id": "priya"}).status_code == 403
        demo = {"username": "priya", "password": auth.DEMO_PASSWORD}
        assert c.post("/v1/auth/login", json=demo).status_code == 401
        ok = c.post("/v1/auth/login", json={"username": "priya", "password": password})
        assert ok.status_code == 200
        assert c.get("/v1/world").status_code == 200


def test_demo_login_can_be_turned_off(bundle_dir):
    with make_client(bundle_dir, CASCADE_DEMO_LOGIN="0") as c:
        assert c.get("/v1/auth/demo-users").json()["users"] == []
        assert c.post("/v1/auth/demo-login", json={"user_id": "priya"}).status_code == 403
        ok = c.post("/v1/auth/login", json={"username": "priya", "password": auth.DEMO_PASSWORD})
        assert ok.status_code == 200


def test_failed_logins_are_throttled(bundle_dir):
    with make_client(bundle_dir) as c:
        codes = [
            c.post("/v1/auth/login", json={"username": "priya", "password": "x"}).status_code
            for _ in range(11)
        ]
        assert codes[:10] == [401] * 10 and codes[10] == 429


def test_bad_settings_fail_fast(monkeypatch):
    monkeypatch.setenv("CASCADE_AUTH", "sometimes")
    with pytest.raises(ValueError):
        auth.Settings()
    monkeypatch.setenv("CASCADE_AUTH", "optional")
    monkeypatch.setenv("CASCADE_JWT_SECRET", "short")
    with pytest.raises(ValueError):
        auth.Settings()
    monkeypatch.setenv("CASCADE_JWT_SECRET", SECRET)
    monkeypatch.setenv("CASCADE_PASSWORD", "too-short")
    with pytest.raises(ValueError):
        auth.Settings()


def test_throttle_forgets_expired_clients():
    now = [1000.0]  # a fake clock: real sleeps are too coarse on Windows (~15 ms ticks)
    t = auth.Throttle(limit=2, window_s=60, clock=lambda: now[0])
    t.fail("a")
    t.fail("a")
    assert t.blocked("a")
    now[0] += 59
    assert t.blocked("a")
    now[0] += 2
    assert not t.blocked("a") and "a" not in t._fails
