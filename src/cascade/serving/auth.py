"""JWT session auth for the CASCADE API and dashboard.

A session is a signed HS256 JWT. Browsers get it in an httpOnly, SameSite=Lax cookie; API clients
may send it as ``Authorization: Bearer <token>``. Users are the four PRD personas, as demo accounts.

Configuration (environment):
- ``CASCADE_AUTH``: ``optional`` (default: anonymous API calls are allowed, so the Streamlit UI and
  TMS integrations keep working; the dashboard still signs in) or ``required`` (every ``/v1`` route
  except ``/v1/auth/*`` needs a valid session).
- ``CASCADE_JWT_SECRET``: signing key. Without it a random key is made per process, so sessions
  end when the API restarts. Set it in any shared deployment.
- ``CASCADE_SESSION_HOURS``: session lifetime (default 8).
- ``CASCADE_DEMO_LOGIN``: ``1`` allows one-click demo sign-in, ``0`` turns it off. Default: on in
  ``optional`` mode, off in ``required`` mode.
- ``CASCADE_PASSWORD``: the accounts' password (12+ characters). Without it the public demo
  password applies, so ``required`` mode refuses to start without it unless demo sign-in is
  switched on explicitly (an open demo that still exercises sessions).
- ``CASCADE_COOKIE_SECURE``: ``1`` marks the cookie Secure (set it behind HTTPS).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
import uuid
from dataclasses import asdict, dataclass

import jwt

log = logging.getLogger("cascade.auth")

COOKIE = "cascade_session"
ISSUER = "cascade"
ALGORITHM = "HS256"
DEMO_PASSWORD = "cascade-demo"


@dataclass(frozen=True)
class User:
    id: str
    name: str
    role: str  # planner | support | analyst | first  (matches the dashboard's roles)
    title: str
    team: str


USERS: dict[str, User] = {
    u.id: u
    for u in [
        User("priya", "Priya Raman", "planner", "Ops planner", "Asia–Europe desk"),
        User("marco", "Marco Bianchi", "support", "Customer support", "Key accounts"),
        User("lena", "Lena Fischer", "analyst", "Network analyst", "Network design"),
        User("reviewer", "Aiqon Reviewer", "first", "Assessment reviewer", "Aiqon"),
    ]
}

_SALT = b"cascade-demo-v1"


def _hash(password: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), _SALT, 120_000)


class AuthError(Exception):
    """Raised for a missing, invalid or expired session."""


class Settings:
    def __init__(self) -> None:
        self.mode = os.environ.get("CASCADE_AUTH", "optional").strip().lower()
        if self.mode not in {"optional", "required"}:
            raise ValueError(f"CASCADE_AUTH must be 'optional' or 'required', not {self.mode!r}")
        secret = os.environ.get("CASCADE_JWT_SECRET", "")
        if not secret:
            secret = secrets.token_urlsafe(48)
            log.warning(
                "CASCADE_JWT_SECRET not set: using a per-process key (sessions end on restart)"
            )
        if len(secret) < 32:
            raise ValueError("CASCADE_JWT_SECRET must be at least 32 characters")
        self.secret = secret
        self.ttl_s = int(float(os.environ.get("CASCADE_SESSION_HOURS", "8")) * 3600)
        demo = os.environ.get("CASCADE_DEMO_LOGIN") or ("0" if self.mode == "required" else "1")
        self.demo_login = demo != "0"
        self.cookie_secure = os.environ.get("CASCADE_COOKIE_SECURE", "0") == "1"
        password = os.environ.get("CASCADE_PASSWORD", "")
        if password and len(password) < 12:
            raise ValueError("CASCADE_PASSWORD must be at least 12 characters")
        if not password and self.mode == "required" and not self.demo_login:
            raise ValueError(
                "CASCADE_AUTH=required needs CASCADE_PASSWORD (the demo password is public); "
                "set CASCADE_DEMO_LOGIN=1 instead for an open demo"
            )
        self.demo_password = not password
        # The accounts share one password; only its hash is kept in memory.
        self.password_hash = _hash(password or DEMO_PASSWORD)


def authenticate(username: str, password: str, settings: Settings) -> User | None:
    """Check a username and password in constant time; None on any mismatch."""
    uid = username.strip().lower()
    expected = settings.password_hash if uid in USERS else _hash(secrets.token_hex(8))
    ok = hmac.compare_digest(expected, _hash(password))
    return USERS[uid] if ok and uid in USERS else None


def issue(user: User, settings: Settings) -> tuple[str, int]:
    """A signed session token and its expiry (unix seconds)."""
    now = int(time.time())
    exp = now + settings.ttl_s
    claims = {
        "iss": ISSUER,
        "sub": user.id,
        "name": user.name,
        "role": user.role,
        "iat": now,
        "exp": exp,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.secret, algorithm=ALGORITHM), exp


def verify(token: str, settings: Settings) -> tuple[User, int]:
    """The user a token belongs to and its expiry; AuthError if it is not valid now."""
    try:
        claims = jwt.decode(
            token,
            settings.secret,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("session expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("invalid session") from exc
    user = USERS.get(str(claims["sub"]))
    if user is None:
        raise AuthError("unknown user")
    return user, int(claims["exp"])


def public(user: User) -> dict:
    return asdict(user)


class Throttle:
    """At most ``limit`` failed sign-ins per client per ``window_s``; a success clears the count."""

    def __init__(self, limit: int = 10, window_s: float = 60.0) -> None:
        self.limit, self.window_s = limit, window_s
        self._fails: dict[str, list[float]] = {}

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        recent = [t for t in self._fails.get(key, []) if now - t < self.window_s]
        if recent:
            self._fails[key] = recent
        else:
            self._fails.pop(key, None)
        return len(recent) >= self.limit

    def fail(self, key: str) -> None:
        self._fails.setdefault(key, []).append(time.monotonic())

    def clear(self, key: str) -> None:
        self._fails.pop(key, None)
