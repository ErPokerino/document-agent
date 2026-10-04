"""Signing in, when the deployment names an account (DOCUFLOW_LOGIN_USER / _PASSWORD).

One account and a signed cookie: enough to keep a shared demo URL from being
used by whoever finds it, not a user system. With no account configured — a
developer machine — nothing here applies and every request is let through.

The cookie holds the user and an expiry, signed with DOCUFLOW_SESSION_SECRET,
so any instance holding the same secret accepts it and nothing is stored
server-side. Failed attempts are counted per client address, in memory: a
brake on guessing, which a deployment running one instance makes meaningful.
"""

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from app import config

router = APIRouter()

COOKIE = "docuflow_session"
SESSION_SECONDS = 12 * 60 * 60
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 10 * 60
# Reachable without a session: the check itself, signing in, and the health
# probe a platform calls without credentials.
OPEN_PATHS = ("/api/auth/", "/api/health")

_failures: dict[str, deque[float]] = defaultdict(deque)


class SignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str


class Session(BaseModel):
    required: bool
    user: str | None = None


def _signature(payload: str) -> str:
    return hmac.new(config.session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue(user: str, now: float | None = None) -> str:
    expires = int((now or time.time()) + SESSION_SECONDS)
    payload = f"{user}|{expires}"
    return f"{payload}|{_signature(payload)}"


def signed_in_user(token: str | None, now: float | None = None) -> str | None:
    """The user a cookie was issued to, if it is genuine, current, and for today's account."""
    account = config.login()
    if not token or account is None:
        return None
    try:
        user, expires, signature = token.rsplit("|", 2)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _signature(f"{user}|{expires}")):
        return None
    if not expires.isdigit() or int(expires) < (now or time.time()):
        return None
    return user if user == account[0] else None


def is_open(path: str) -> bool:
    return not path.startswith("/api/") or any(path.startswith(prefix) for prefix in OPEN_PATHS)


def _client(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _secure(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


@router.get("/api/auth/session", response_model=Session)
async def session(request: Request) -> Session:
    if config.login() is None:
        return Session(required=False)
    return Session(required=True, user=signed_in_user(request.cookies.get(COOKIE)))


@router.post("/api/auth/login", response_model=Session)
async def login(request: Request, response: Response, attempt: SignIn) -> Session:
    account = config.login()
    if account is None:
        return Session(required=False)
    client = _client(request)
    recent = _failures[client]
    now = time.time()
    while recent and recent[0] < now - FAILURE_WINDOW_SECONDS:
        recent.popleft()
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Too many failed sign-in attempts. Sign-in is paused for a few minutes.")
    user_ok = secrets.compare_digest(attempt.username.encode(), account[0].encode())
    password_ok = secrets.compare_digest(attempt.password.encode(), account[1].encode())
    if not (user_ok and password_ok):
        recent.append(now)
        raise HTTPException(status_code=401, detail="The username or password is not correct.")
    recent.clear()
    response.set_cookie(
        COOKIE, issue(account[0]), max_age=SESSION_SECONDS, httponly=True, samesite="lax", secure=_secure(request), path="/",
    )
    return Session(required=True, user=account[0])


@router.post("/api/auth/logout", response_model=Session)
async def logout(response: Response) -> Session:
    response.delete_cookie(COOKIE, path="/")
    return Session(required=config.login() is not None)
