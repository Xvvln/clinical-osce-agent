from __future__ import annotations

from collections.abc import Iterator
import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.auth_store import AuthStore


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"))
    with TestClient(main.app) as test_client:
        yield test_client


def test_register_is_disabled_for_fixed_demo_accounts(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": "someone@example.test", "password": "safe-password-123", "display_name": "学生甲"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "当前演示仅开放固定学生和管理员账号，不允许创建新账号。"
    }


def test_register_is_disabled_in_production_deployment_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")

    response = client.post(
        "/api/auth/register",
        json={"email": "someone@example.test", "password": "safe-password-123", "display_name": "学生甲"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "当前演示仅开放固定学生和管理员账号，不允许创建新账号。"
    }


def test_fixed_student_login_creates_user_and_logout_clears_session(client: TestClient) -> None:
    login_response = client.post(
        "/api/auth/login",
        json={"email": "student@osce.test", "password": "student"},
    )

    assert login_response.status_code == 200
    assert login_response.json()["user"]["email"] == "student@osce.test"
    assert login_response.json()["user"]["display_name"] == "演示学生"
    current_user_response = client.get("/api/auth/me")
    assert current_user_response.status_code == 200
    assert current_user_response.json()["user"]["is_admin"] is False

    logout_response = client.post("/api/auth/logout")

    assert logout_response.status_code == 200
    assert logout_response.json() == {"status": "ok"}
    assert client.get("/api/auth/me").status_code == 401


def test_fixed_admin_login_marks_current_user_as_admin(client: TestClient) -> None:
    login_response = client.post(
        "/api/auth/login",
        json={"email": "admin@osce.test", "password": "admin"},
    )

    assert login_response.status_code == 200
    assert login_response.json()["user"]["email"] == "admin@osce.test"
    assert login_response.json()["user"]["display_name"] == "演示管理员"
    assert login_response.json()["user"]["is_admin"] is True
    current_user_response = client.get("/api/auth/me")
    assert current_user_response.status_code == 200
    assert current_user_response.json()["user"]["is_admin"] is True


def test_login_rejects_wrong_password(client: TestClient) -> None:
    login_response = client.post(
        "/api/auth/login",
        json={"email": "student@osce.test", "password": "wrong-password"},
    )

    assert login_response.status_code == 401
    assert client.get("/api/auth/me").status_code == 401
