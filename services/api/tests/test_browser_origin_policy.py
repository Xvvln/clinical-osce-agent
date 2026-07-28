from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app import main
from app.services.auth_store import AuthStore
from app.services.browser_origin_policy import normalize_browser_origin

TRUSTED_BROWSER_ORIGINS_ENV_NAME = "CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS"
STUDENT_ORIGIN = "http://localhost:3000"
ADMIN_COMPOSE_ORIGIN = "http://127.0.0.1:3001"


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_ENABLED", "true")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_EMAIL", "student@example.test")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_PASSWORD", "configured-password")
    monkeypatch.delenv(TRUSTED_BROWSER_ORIGINS_ENV_NAME, raising=False)
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"))
    with TestClient(main.app) as test_client:
        yield test_client


def _login(client: TestClient, *, origin: str | None = STUDENT_ORIGIN) -> Response:
    headers = {}
    if origin is not None:
        headers = {"Origin": origin, "Sec-Fetch-Site": "same-origin"}
    return client.post(
        "/api/auth/login",
        headers=headers,
        json={
            "email": "student@example.test",
            "password": "configured-password",
        },
    )


def test_trusted_local_browser_origins_can_write(client: TestClient) -> None:
    student_response = _login(client)
    client.post(
        "/api/auth/logout",
        headers={"Origin": STUDENT_ORIGIN, "Sec-Fetch-Site": "same-origin"},
    )
    admin_origin_response = _login(client, origin=ADMIN_COMPOSE_ORIGIN)

    assert student_response.status_code == 200
    assert admin_origin_response.status_code == 200


def test_untrusted_same_site_origin_cannot_logout_existing_session(client: TestClient) -> None:
    assert _login(client).status_code == 200

    logout_response = client.post(
        "/api/auth/logout",
        headers={
            "Origin": "http://localhost:3999",
            "Sec-Fetch-Site": "same-site",
        },
    )

    assert logout_response.status_code == 403
    assert logout_response.json() == {"detail": "cross-origin state-changing request rejected"}
    assert client.get("/api/auth/me").status_code == 200


def test_rejected_request_does_not_lookup_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(_: str) -> None:
        raise AssertionError("origin guard must run before session lookup")

    monkeypatch.setattr(main.auth_store, "get_user_by_session_token", fail_if_called)

    response = _login(client, origin="https://evil.example")

    assert response.status_code == 403


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "https://evil.example",
        "http://localhost:3000.evil.example",
    ],
)
def test_untrusted_origin_variants_are_rejected(client: TestClient, origin: str) -> None:
    response = _login(client, origin=origin)

    assert response.status_code == 403
    assert response.json() == {"detail": "cross-origin state-changing request rejected"}


def test_exact_trusted_origin_takes_priority_over_same_site_fetch_metadata(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling_origin = "http://student.localhost:3000"
    monkeypatch.setenv(TRUSTED_BROWSER_ORIGINS_ENV_NAME, sibling_origin)

    response = client.post(
        "/api/auth/login",
        headers={"Origin": sibling_origin, "Sec-Fetch-Site": "same-site"},
        json={
            "email": "student@example.test",
            "password": "configured-password",
        },
    )

    assert response.status_code == 200


def test_trusted_referer_is_accepted_when_origin_is_missing(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        headers={"Referer": f"{STUDENT_ORIGIN}/"},
        json={
            "email": "student@example.test",
            "password": "configured-password",
        },
    )

    assert response.status_code == 200


def test_local_non_browser_client_without_origin_remains_supported(client: TestClient) -> None:
    assert _login(client, origin=None).status_code == 200


def test_production_write_without_browser_origin_fails_closed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")
    monkeypatch.setenv(TRUSTED_BROWSER_ORIGINS_ENV_NAME, "https://osce.example")

    response = _login(client, origin=None)

    assert response.status_code == 403
    assert response.json() == {"detail": "cross-origin state-changing request rejected"}


def test_production_trusted_https_origin_reaches_authentication(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")
    monkeypatch.setenv(TRUSTED_BROWSER_ORIGINS_ENV_NAME, "https://osce.example")

    response = _login(client, origin="https://osce.example")

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid credentials"}


@pytest.mark.parametrize(
    ("trusted_origins", "origin"),
    [
        ("", "https://osce.example"),
        ("http://osce.example", "http://osce.example"),
    ],
)
def test_production_origin_misconfiguration_fails_closed_at_runtime(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    trusted_origins: str,
    origin: str,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")
    if trusted_origins:
        monkeypatch.setenv(TRUSTED_BROWSER_ORIGINS_ENV_NAME, trusted_origins)
    else:
        monkeypatch.delenv(TRUSTED_BROWSER_ORIGINS_ENV_NAME, raising=False)

    response = _login(client, origin=origin)

    assert response.status_code == 403
    assert response.json() == {"detail": "cross-origin state-changing request rejected"}


def test_unknown_deployment_mode_does_not_fall_back_to_local_origin_policy(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-pro")

    response = _login(client, origin=None)

    assert response.status_code == 403
    assert response.json() == {"detail": "cross-origin state-changing request rejected"}


def test_pure_report_get_is_not_subject_to_state_change_origin_policy(client: TestClient) -> None:
    response = client.get(
        "/api/sessions/session-1/report",
        headers={
            "Origin": "http://localhost:3999",
            "Sec-Fetch-Site": "same-site",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


@pytest.mark.parametrize(
    "origin",
    [
        "\x00https://osce.example",
        "https://osce.example\x7f",
        "https://osce.example?",
        "https://osce.example#",
    ],
)
def test_origin_normalization_rejects_control_characters_and_empty_suffixes(origin: str) -> None:
    assert normalize_browser_origin(origin) is None


def test_options_response_does_not_enable_cross_origin_access(client: TestClient) -> None:
    response = client.options(
        "/api/auth/login",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "access-control-allow-origin" not in response.headers
