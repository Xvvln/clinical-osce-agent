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
        "detail": "不允许创建新账号；固定学生和管理员账号仅在本地模式下显式配置后可用。"
    }


def test_register_is_disabled_in_production_deployment_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")

    response = client.post(
        "/api/auth/register",
        json={"email": "someone@example.test", "password": "safe-password-123", "display_name": "学生甲"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "不允许创建新账号；固定学生和管理员账号仅在本地模式下显式配置后可用。"
    }


def _clear_demo_account_config(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in [
        "CLINICAL_OSCE_DEMO_ADMIN_ENABLED",
        "CLINICAL_OSCE_DEMO_ADMIN_EMAIL",
        "CLINICAL_OSCE_DEMO_ADMIN_PASSWORD",
        "CLINICAL_OSCE_DEMO_STUDENT_ENABLED",
        "CLINICAL_OSCE_DEMO_STUDENT_EMAIL",
        "CLINICAL_OSCE_DEMO_STUDENT_PASSWORD",
    ]:
        monkeypatch.delenv(env_name, raising=False)


def _configure_demo_student(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    email = "configured-student@example.test"
    password = "configured-student-password"
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_ENABLED", "true")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_EMAIL", email)
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_PASSWORD", password)
    return email, password


def _configure_demo_admin(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    email = "configured-admin@example.test"
    password = "configured-admin-password"
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_ENABLED", "true")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_EMAIL", email)
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_PASSWORD", password)
    return email, password


def test_fixed_demo_credentials_are_rejected_by_default(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    _clear_demo_account_config(monkeypatch)

    student_response = client.post(
        "/api/auth/login",
        json={"email": "student@osce.test", "password": "student"},
    )
    admin_response = client.post(
        "/api/auth/login",
        json={"email": "admin@osce.test", "password": "admin"},
    )

    assert student_response.status_code == 401
    assert admin_response.status_code == 401


def test_explicit_local_demo_student_login_creates_user_and_logout_clears_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email, password = _configure_demo_student(monkeypatch)

    login_response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )

    assert login_response.status_code == 200
    assert login_response.json()["user"]["email"] == email
    assert login_response.json()["user"]["display_name"] == "演示学生"
    auth_cookie_header = login_response.headers["set-cookie"].lower()
    assert f"{main.AUTH_COOKIE_NAME}=" in auth_cookie_header
    assert "domain=" not in auth_cookie_header
    assert "httponly" in auth_cookie_header
    assert "path=/" in auth_cookie_header
    assert "samesite=lax" in auth_cookie_header
    current_user_response = client.get("/api/auth/me")
    assert current_user_response.status_code == 200
    assert current_user_response.json()["user"]["is_admin"] is False

    logout_response = client.post("/api/auth/logout")

    assert logout_response.status_code == 200
    assert logout_response.json() == {"status": "ok"}
    assert client.get("/api/auth/me").status_code == 401


def test_explicit_local_demo_admin_login_marks_current_user_as_admin(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email, password = _configure_demo_admin(monkeypatch)

    login_response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )

    assert login_response.status_code == 200
    assert login_response.json()["user"]["email"] == email
    assert login_response.json()["user"]["display_name"] == "演示管理员"
    assert login_response.json()["user"]["is_admin"] is True
    current_user_response = client.get("/api/auth/me")
    assert current_user_response.status_code == 200
    assert current_user_response.json()["user"]["is_admin"] is True


def test_production_mode_rejects_explicit_demo_accounts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    student_email, student_password = _configure_demo_student(monkeypatch)
    admin_email, admin_password = _configure_demo_admin(monkeypatch)
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")

    student_response = client.post(
        "/api/auth/login",
        json={"email": student_email, "password": student_password},
    )
    admin_response = client.post(
        "/api/auth/login",
        json={"email": admin_email, "password": admin_password},
    )

    assert student_response.status_code == 401
    assert admin_response.status_code == 401


def test_demo_admin_missing_password_does_not_fall_back_to_hardcoded_password(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_ENABLED", "true")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_EMAIL", "admin@osce.test")
    monkeypatch.delenv("CLINICAL_OSCE_DEMO_ADMIN_PASSWORD", raising=False)

    login_response = client.post(
        "/api/auth/login",
        json={"email": "admin@osce.test", "password": "admin"},
    )

    assert login_response.status_code == 401


def test_login_rejects_wrong_password(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    email, _password = _configure_demo_student(monkeypatch)

    login_response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "wrong-password"},
    )

    assert login_response.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_demo_admin_and_student_cannot_share_the_same_email(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_email = "shared-role@example.test"
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_ENABLED", "true")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_EMAIL", shared_email)
    monkeypatch.setenv(
        "CLINICAL_OSCE_DEMO_ADMIN_PASSWORD",
        "configured-admin-password",
    )
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_ENABLED", "true")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_EMAIL", shared_email.upper())
    monkeypatch.setenv(
        "CLINICAL_OSCE_DEMO_STUDENT_PASSWORD",
        "configured-student-password",
    )

    admin_response = client.post(
        "/api/auth/login",
        json={
            "email": shared_email,
            "password": "configured-admin-password",
        },
    )
    student_response = client.post(
        "/api/auth/login",
        json={
            "email": shared_email,
            "password": "configured-student-password",
        },
    )

    assert admin_response.status_code == 401
    assert student_response.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_demo_student_email_in_admin_allowlist_remains_non_admin(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    student_email, student_password = _configure_demo_student(monkeypatch)
    monkeypatch.setenv(
        "CLINICAL_OSCE_ADMIN_EMAILS",
        f"other-admin@example.test,{student_email.upper()}",
    )
    user = main.auth_store.upsert_user_password(
        student_email,
        student_password,
        "演示学生",
    )
    token = main.auth_store.create_session(user["user_id"])
    client.cookies.set(main.AUTH_COOKIE_NAME, token)

    current_user_response = client.get("/api/auth/me")
    admin_response = client.get("/api/admin/model-config")

    assert current_user_response.status_code == 200
    assert current_user_response.json()["user"]["is_admin"] is False
    assert admin_response.status_code == 403
    assert admin_response.json() == {"detail": "admin access required"}
