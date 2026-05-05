from fastapi.testclient import TestClient

from app import main
from app.services.runtime_model_config_store import runtime_model_config_store
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


class _FakeOpenAICompatibleProbeClient:
    requested_urls: list[str] = []
    requested_headers: list[dict[str, str]] = []
    requested_bodies: list[dict[str, object]] = []

    def __init__(self, **_: object) -> None:
        pass

    def __enter__(self) -> "_FakeOpenAICompatibleProbeClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> _FakeConnectivityResponse:
        self.requested_urls.append(url)
        self.requested_headers.append(headers)
        self.requested_bodies.append(json)
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


def test_student_model_config_test_openai_compatible_uses_chat_completion_probe(monkeypatch) -> None:
    _FakeOpenAICompatibleProbeClient.requested_urls = []
    _FakeOpenAICompatibleProbeClient.requested_headers = []
    _FakeOpenAICompatibleProbeClient.requested_bodies = []
    monkeypatch.setattr(student_model_config_service.httpx, "Client", _FakeOpenAICompatibleProbeClient)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/test",
            json={
                "provider": "openai_compatible",
                "api_key": "student-openai-secret",
                "model": "gemini-via-clprox",
                "base_url": "https://api.proxy.example/v1",
                "proxy_url": "direct",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "openai_compatible"
    assert payload["checked_url"] == "https://api.proxy.example/v1/chat/completions"
    assert _FakeOpenAICompatibleProbeClient.requested_urls == ["https://api.proxy.example/v1/chat/completions"]
    assert _FakeOpenAICompatibleProbeClient.requested_headers == [{"Authorization": "Bearer student-openai-secret"}]
    assert _FakeOpenAICompatibleProbeClient.requested_bodies[0]["model"] == "gemini-via-clprox"
    assert _FakeOpenAICompatibleProbeClient.requested_bodies[0]["messages"] == [
        {"role": "system", "content": "只输出 JSON。"},
        {"role": "user", "content": '{"ping":"clinical-osce-agent"}'},
    ]
    assert "student-openai-secret" not in response.text


def test_student_can_apply_openai_compatible_config_to_runtime_without_leaking_secret() -> None:
    runtime_model_config_store.clear()
    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/runtime",
            json={
                "provider": "openai_compatible",
                "api_key": "student-openai-secret",
                "model": "gemini-via-clprox",
                "base_url": "https://api.proxy.example/v1",
                "proxy_url": "http://127.0.0.1:7897",
            },
        )
        status_response = client.get("/api/model-config/runtime")
    runtime_model_config_store.clear()

    assert response.status_code == 200
    assert response.json() == {
        "active": True,
        "provider": "openai_compatible",
        "model": "gemini-via-clprox",
        "base_url": "https://api.proxy.example/v1",
        "proxy_url": "http://127.0.0.1:7897",
        "integration_targets": ["patient_responder", "llm_rubric_scorer", "skill_candidate_generator"],
        "message": "OpenAI 兼容服务端已应用到本次后端运行时。",
    }
    assert status_response.status_code == 200
    assert status_response.json()["active"] is True
    assert status_response.json()["provider"] == "openai_compatible"
    assert "student-openai-secret" not in response.text
    assert "student-openai-secret" not in status_response.text
