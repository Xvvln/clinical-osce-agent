from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main


EXPECTED_BASE_HEADERS = {
    "content-security-policy": "base-uri 'self'; frame-ancestors 'none'; object-src 'none'; form-action 'self'",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/", 200),
        ("/api/health", 200),
        ("/api/auth/me", 401),
        ("/api/missing-route", 404),
    ],
)
def test_http_responses_include_baseline_security_headers(
    path: str,
    expected_status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")

    with TestClient(main.app) as client:
        response = client.get(path)

    assert response.status_code == expected_status
    for header_name, expected_value in EXPECTED_BASE_HEADERS.items():
        assert response.headers[header_name] == expected_value
    assert "strict-transport-security" not in response.headers


@pytest.mark.parametrize(
    ("path", "expected_cache_control"),
    [
        ("/", None),
        ("/api/health", main.API_PRIVATE_CACHE_CONTROL),
        ("/api/auth/me", main.API_PRIVATE_CACHE_CONTROL),
        ("/api/missing-route", main.API_PRIVATE_CACHE_CONTROL),
    ],
)
def test_only_api_responses_are_forced_private_and_uncacheable(
    path: str,
    expected_cache_control: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")

    with TestClient(main.app) as client:
        response = client.get(path)

    assert response.headers.get("cache-control") == expected_cache_control
    if expected_cache_control is not None:
        assert response.headers["pragma"] == "no-cache"
        assert response.headers["expires"] == "0"


@pytest.mark.parametrize("deployment_mode", ["single-node-prod", "vertex-prod"])
def test_production_responses_enable_hsts(
    deployment_mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", deployment_mode)

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["strict-transport-security"] == main.PRODUCTION_HSTS_HEADER


def test_security_and_privacy_headers_wrap_origin_rejections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/auth/logout",
            headers={
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "cross-site",
            },
        )

    assert response.status_code == 403
    assert response.headers["cache-control"] == main.API_PRIVATE_CACHE_CONTROL
    for header_name, expected_value in EXPECTED_BASE_HEADERS.items():
        assert response.headers[header_name] == expected_value
