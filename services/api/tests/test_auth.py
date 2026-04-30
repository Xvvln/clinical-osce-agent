from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.auth_store import AuthStore


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"))
    with TestClient(main.app) as test_client:
        yield test_client


def unique_email() -> str:
    return f"student-{uuid4().hex}@example.test"


def test_register_sets_login_cookie_and_me_returns_current_user(client: TestClient) -> None:
    email = unique_email()

    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "safe-password-123", "display_name": "学生甲"},
    )

    assert response.status_code == 200
    assert "set-cookie" in response.headers
    payload = response.json()
    assert payload["user"]["email"] == email
    assert payload["user"]["display_name"] == "学生甲"
    assert "password" not in str(payload).lower()

    me_response = client.get("/api/auth/me")

    assert me_response.status_code == 200
    assert me_response.json()["user"] == payload["user"]


def test_login_reuses_existing_user_and_logout_clears_session(client: TestClient) -> None:
    email = unique_email()
    password = "safe-password-456"
    register_response = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": "学生乙"},
    )
    assert register_response.status_code == 200

    client.post("/api/auth/logout")
    logged_out_response = client.get("/api/auth/me")
    assert logged_out_response.status_code == 401

    login_response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )

    assert login_response.status_code == 200
    assert login_response.json()["user"]["email"] == email
    assert client.get("/api/auth/me").status_code == 200

    logout_response = client.post("/api/auth/logout")

    assert logout_response.status_code == 200
    assert logout_response.json() == {"status": "ok"}
    assert client.get("/api/auth/me").status_code == 401


def test_login_rejects_wrong_password(client: TestClient) -> None:
    email = unique_email()
    register_response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "safe-password-789", "display_name": "学生丙"},
    )
    assert register_response.status_code == 200
    client.post("/api/auth/logout")

    login_response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "wrong-password"},
    )

    assert login_response.status_code == 401
    assert client.get("/api/auth/me").status_code == 401
