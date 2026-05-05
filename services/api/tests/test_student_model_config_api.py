from fastapi.testclient import TestClient

from app import main


def test_student_model_config_test_accepts_local_backend_without_admin_login() -> None:
    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/test",
            json={
                "provider": "local_backend",
                "api_key": "student-secret-value",
                "model": "",
                "base_url": "http://127.0.0.1:8000",
                "proxy_url": "http://127.0.0.1:7897",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "local_backend"
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
