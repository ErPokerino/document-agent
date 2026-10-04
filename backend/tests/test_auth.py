"""The one-account sign-in a deployment can require, and its absence on a developer machine."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api.routes import auth


@pytest.fixture
def account(monkeypatch):
    monkeypatch.setenv("DOCUFLOW_LOGIN_USER", "admin")
    monkeypatch.setenv("DOCUFLOW_LOGIN_PASSWORD", "s3cret")
    monkeypatch.setenv("DOCUFLOW_SESSION_SECRET", "test-secret")
    auth._failures.clear()
    yield
    auth._failures.clear()


def test_without_an_account_nothing_asks_anyone_to_sign_in(monkeypatch) -> None:
    monkeypatch.delenv("DOCUFLOW_LOGIN_USER", raising=False)
    monkeypatch.delenv("DOCUFLOW_LOGIN_PASSWORD", raising=False)
    client = TestClient(main.app)

    assert client.get("/api/auth/session").json()["required"] is False
    assert client.get("/api/pipelines").status_code == 200


def test_with_an_account_the_api_answers_only_after_sign_in(account) -> None:
    client = TestClient(main.app)

    assert client.get("/api/pipelines").status_code == 401
    assert client.get("/api/auth/session").json() == {"required": True, "user": None}
    # A platform's health probe carries no cookie.
    assert client.get("/api/health").status_code == 200

    signed_in = client.post("/api/auth/login", json={"username": "admin", "password": "s3cret"})
    assert signed_in.status_code == 200
    assert "httponly" in signed_in.headers["set-cookie"].lower()
    assert client.get("/api/pipelines").status_code == 200
    assert client.get("/api/auth/session").json() == {"required": True, "user": "admin"}

    client.post("/api/auth/logout")
    assert client.get("/api/pipelines").status_code == 401


def test_a_wrong_password_is_refused_and_repeated_guessing_is_paused(account) -> None:
    client = TestClient(main.app)

    for _ in range(auth.MAX_FAILURES):
        assert client.post("/api/auth/login", json={"username": "admin", "password": "guess"}).status_code == 401
    paused = client.post("/api/auth/login", json={"username": "admin", "password": "s3cret"})
    assert paused.status_code == 429


def test_a_cookie_is_genuine_only_when_signed_with_the_secret_and_current(account) -> None:
    token = auth.issue("admin", now=1_000)

    assert auth.signed_in_user(token, now=1_000) == "admin"
    assert auth.signed_in_user(token, now=1_000 + auth.SESSION_SECONDS + 1) is None
    user, expires, signature = token.split("|")
    assert auth.signed_in_user(f"admin|{int(expires) + 10_000}|{signature}", now=1_000) is None
    assert auth.signed_in_user(f"someone|{expires}|{signature}", now=1_000) is None
    assert auth.signed_in_user("garbage", now=1_000) is None


def test_the_cookie_is_secure_behind_https(account) -> None:
    client = TestClient(main.app)

    answer = client.post(
        "/api/auth/login", json={"username": "admin", "password": "s3cret"}, headers={"x-forwarded-proto": "https"}
    )
    assert "secure" in answer.headers["set-cookie"].lower()
