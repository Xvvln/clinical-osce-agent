from fastapi.testclient import TestClient

from app import main
from app.services import student_model_config_service


class _FakeConnectivityResponse:
    is_success = True
    status_code = 200


class _FakeHttpxClient:
    requested_urls: list[str] = []
    requested_headers: list[dict[str, str]] = []

    def __init__(self, **_: object) -> None:
        pass

    def __enter__(self) -> "_FakeHttpxClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get(self, url: str, headers: dict[str, str]) -> _FakeConnectivityResponse:
        self.requested_urls.append(url)
        self.requested_headers.append(headers)
        return _FakeConnectivityResponse()


def test_student_model_config_test_accepts_custom_backend_without_admin_login(monkeypatch) -> None:
    _FakeHttpxClient.requested_urls = []
    _FakeHttpxClient.requested_headers = []
    monkeypatch.setattr(student_model_config_service.httpx, "Client", _FakeHttpxClient)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/test",
            json={
                "provider": "custom_backend",
                "api_key": "student-secret-value",
                "model": "",
                "base_url": "http://custom.example/api",
                "proxy_url": "http://127.0.0.1:7897",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "custom_backend"
    assert payload["checked_url"] == "http://custom.example/api/health"
    assert _FakeHttpxClient.requested_urls == ["http://custom.example/api/health"]
    assert _FakeHttpxClient.requested_headers == [{"Authorization": "Bearer student-secret-value"}]
    assert "student-secret-value" not in response.text


def test_student_model_config_test_rejects_remote_provider_without_api_key() -> None:
    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/test",
            json={
                "provider": "gemini",
                "api_key": "",
                "model": "gemini-3.1-flash-lite-preview",
                "base_url": "https://generativelanguage.googleapis.com",
                "proxy_url": "http://127.0.0.1:7897",
            },
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "api_key is required for gemini"}
