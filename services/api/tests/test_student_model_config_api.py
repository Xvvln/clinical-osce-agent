from fastapi.testclient import TestClient

from app import main
from app.main import AUTH_COOKIE_NAME
from app.services.auth_store import AuthStore
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services import student_model_config_service


class _FakeConnectivityResponse:
    is_success = True
    status_code = 200


class _FakeConnectivityErrorResponse:
    is_success = False
    status_code = 400
    text = '{"error":{"code":"400","message":"Param Incorrect","param":"Not supported model MiMo-V2.5-Pro"}}'

    def json(self) -> dict[str, object]:
        return {
            "error": {
                "code": "400",
                "message": "Param Incorrect",
                "param": "Not supported model MiMo-V2.5-Pro",
            },
        }


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


class _FakeOpenAICompatibleErrorProbeClient(_FakeOpenAICompatibleProbeClient):
    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> _FakeConnectivityErrorResponse:
        self.requested_urls.append(url)
        self.requested_headers.append(headers)
        self.requested_bodies.append(json)
        return _FakeConnectivityErrorResponse()


class _FakeVertexGeminiModels:
    calls: list[dict[str, object]] = []

    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        self.calls.append({"model": model, "contents": contents, "config": config})

        class Response:
            text = '{"ok":true}'

        return Response()


class _FakeVertexGeminiClient:
    created: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.created.append(kwargs)
        self.models = _FakeVertexGeminiModels()


def _authenticated_client(tmp_path, monkeypatch, email: str) -> TestClient:
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(main, "auth_store", auth_store)
    user = auth_store.create_user(email, "safe-password-123", email)
    assert user is not None
    token = auth_store.create_session(user["user_id"])
    client = TestClient(main.app)
    client.cookies.set(AUTH_COOKIE_NAME, token)
    return client


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
                "model": "gemini-3.1-pro-preview",
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


def test_student_model_config_test_includes_sanitized_provider_error_detail(monkeypatch) -> None:
    _FakeOpenAICompatibleErrorProbeClient.requested_urls = []
    _FakeOpenAICompatibleErrorProbeClient.requested_headers = []
    _FakeOpenAICompatibleErrorProbeClient.requested_bodies = []
    monkeypatch.setattr(student_model_config_service.httpx, "Client", _FakeOpenAICompatibleErrorProbeClient)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/test",
            json={
                "provider": "openai_compatible",
                "api_key": "student-openai-secret",
                "model": "MiMo-V2.5-Pro",
                "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                "proxy_url": "direct",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["message"] == "连通性测试失败：HTTP 400：Param Incorrect；Not supported model MiMo-V2.5-Pro"
    assert "student-openai-secret" not in response.text
    assert "student-openai-secret" not in response.text


def test_student_model_config_test_anthropic_uses_messages_probe(monkeypatch) -> None:
    _FakeOpenAICompatibleProbeClient.requested_urls = []
    _FakeOpenAICompatibleProbeClient.requested_headers = []
    _FakeOpenAICompatibleProbeClient.requested_bodies = []
    monkeypatch.setattr(student_model_config_service.httpx, "Client", _FakeOpenAICompatibleProbeClient)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/test",
            json={
                "provider": "anthropic",
                "api_key": "student-anthropic-secret",
                "model": "claude-3-5-sonnet-latest",
                "base_url": "https://api.anthropic.com",
                "proxy_url": "direct",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "anthropic"
    assert payload["checked_url"] == "https://api.anthropic.com/v1/messages"
    assert _FakeOpenAICompatibleProbeClient.requested_urls == ["https://api.anthropic.com/v1/messages"]
    assert _FakeOpenAICompatibleProbeClient.requested_headers[0]["x-api-key"] == "student-anthropic-secret"
    assert _FakeOpenAICompatibleProbeClient.requested_headers[0]["anthropic-version"] == "2023-06-01"
    assert _FakeOpenAICompatibleProbeClient.requested_bodies[0]["model"] == "claude-3-5-sonnet-latest"
    assert _FakeOpenAICompatibleProbeClient.requested_bodies[0]["messages"] == [
        {"role": "user", "content": '{"ping":"clinical-osce-agent"}'},
    ]
    assert "student-anthropic-secret" not in response.text


def test_student_model_config_test_vertex_gemini_adc_uses_adc_without_api_key(monkeypatch) -> None:
    _FakeVertexGeminiClient.created = []
    _FakeVertexGeminiModels.calls = []
    monkeypatch.setattr(student_model_config_service.genai, "Client", _FakeVertexGeminiClient)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/test",
            json={
                "provider": "vertex_gemini_adc",
                "api_key": "",
                "model": "gemini-3.1-pro-preview",
                "base_url": "demo-project",
                "proxy_url": "http://127.0.0.1:7897",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "vertex_gemini_adc"
    assert payload["checked_url"] == "vertex://demo-project/global/gemini-3.1-pro-preview"
    assert _FakeVertexGeminiClient.created == [{"vertexai": True, "project": "demo-project", "location": "global"}]
    assert _FakeVertexGeminiModels.calls[0]["model"] == "gemini-3.1-pro-preview"
    assert "api_key" not in str(_FakeVertexGeminiClient.created)


def test_student_model_config_test_vertex_gemini_api_key_uses_express_mode_without_project(monkeypatch) -> None:
    _FakeVertexGeminiClient.created = []
    _FakeVertexGeminiModels.calls = []
    monkeypatch.setattr(student_model_config_service.genai, "Client", _FakeVertexGeminiClient)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/test",
            json={
                "provider": "vertex_gemini_api_key",
                "api_key": "student-vertex-secret",
                "model": "gemini-2.5-flash",
                "base_url": "",
                "proxy_url": "http://127.0.0.1:7897",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "vertex_gemini_api_key"
    assert payload["checked_url"] == "vertex-api-key://express/gemini-2.5-flash"
    assert _FakeVertexGeminiClient.created == [{"vertexai": True, "api_key": "student-vertex-secret"}]
    assert _FakeVertexGeminiModels.calls[0]["model"] == "gemini-2.5-flash"
    assert "student-vertex-secret" not in response.text


def test_student_can_apply_openai_compatible_config_to_runtime_without_leaking_secret(tmp_path, monkeypatch) -> None:
    runtime_model_config_store.clear()
    client = _authenticated_client(tmp_path, monkeypatch, "student-openai@example.test")
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
        "api_key_saved": True,
        "integration_targets": ["patient_responder", "llm_rubric_scorer", "skill_candidate_generator"],
        "message": "OpenAI 兼容服务端已应用到本次后端运行时。",
    }
    assert status_response.status_code == 200
    assert status_response.json()["active"] is True
    assert status_response.json()["provider"] == "openai_compatible"
    assert "student-openai-secret" not in response.text
    assert "student-openai-secret" not in status_response.text


def test_student_can_apply_anthropic_config_to_runtime_without_leaking_secret(tmp_path, monkeypatch) -> None:
    runtime_model_config_store.clear()
    client = _authenticated_client(tmp_path, monkeypatch, "student-anthropic@example.test")
    response = client.post(
        "/api/model-config/runtime",
        json={
            "provider": "anthropic",
            "api_key": "student-anthropic-secret",
            "model": "claude-3-5-sonnet-latest",
            "base_url": "https://api.anthropic.com",
            "proxy_url": "http://127.0.0.1:7897",
        },
    )
    status_response = client.get("/api/model-config/runtime")
    runtime_model_config_store.clear()

    assert response.status_code == 200
    assert response.json() == {
        "active": True,
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-latest",
        "base_url": "https://api.anthropic.com",
        "proxy_url": "http://127.0.0.1:7897",
        "api_key_saved": True,
        "integration_targets": ["patient_responder", "llm_rubric_scorer", "skill_candidate_generator"],
        "message": "Anthropic 服务端已应用到本次后端运行时。",
    }
    assert status_response.status_code == 200
    assert status_response.json()["active"] is True
    assert status_response.json()["provider"] == "anthropic"
    assert "student-anthropic-secret" not in response.text
    assert "student-anthropic-secret" not in status_response.text


def test_student_can_apply_vertex_gemini_adc_config_to_runtime_without_api_key(tmp_path, monkeypatch) -> None:
    runtime_model_config_store.clear()
    client = _authenticated_client(tmp_path, monkeypatch, "student-vertex-adc@example.test")
    response = client.post(
        "/api/model-config/runtime",
        json={
            "provider": "vertex_gemini_adc",
            "api_key": "",
            "model": "gemini-3.1-pro-preview",
            "base_url": "demo-project",
            "proxy_url": "http://127.0.0.1:7897",
        },
    )
    status_response = client.get("/api/model-config/runtime")
    runtime_model_config_store.clear()

    assert response.status_code == 200
    assert response.json() == {
        "active": True,
        "provider": "vertex_gemini_adc",
        "model": "gemini-3.1-pro-preview",
        "base_url": "demo-project",
        "proxy_url": "http://127.0.0.1:7897",
        "project": "demo-project",
        "location": "global",
        "api_key_saved": False,
        "integration_targets": ["patient_responder", "llm_rubric_scorer", "skill_candidate_generator"],
        "message": "Vertex Gemini ADC 配置已应用到本次后端运行时。",
    }
    assert status_response.status_code == 200
    assert status_response.json()["provider"] == "vertex_gemini_adc"
    assert response.json()["api_key_saved"] is False


def test_student_can_apply_vertex_gemini_api_key_config_to_runtime_without_leaking_secret(tmp_path, monkeypatch) -> None:
    runtime_model_config_store.clear()
    client = _authenticated_client(tmp_path, monkeypatch, "student-vertex-key@example.test")
    response = client.post(
        "/api/model-config/runtime",
        json={
            "provider": "vertex_gemini_api_key",
            "api_key": "student-vertex-secret",
            "model": "gemini-2.5-flash",
            "base_url": "",
            "proxy_url": "http://127.0.0.1:7897",
        },
    )
    status_response = client.get("/api/model-config/runtime")
    runtime_model_config_store.clear()

    assert response.status_code == 200
    assert response.json() == {
        "active": True,
        "provider": "vertex_gemini_api_key",
        "model": "gemini-2.5-flash",
        "base_url": "",
        "proxy_url": "http://127.0.0.1:7897",
        "project": "",
        "location": "global",
        "api_key_saved": True,
        "integration_targets": ["patient_responder", "llm_rubric_scorer", "skill_candidate_generator"],
        "message": "Vertex Gemini API Key 配置已应用到本次后端运行时。",
    }
    assert status_response.status_code == 200
    assert status_response.json()["provider"] == "vertex_gemini_api_key"
    assert "student-vertex-secret" not in response.text
    assert "student-vertex-secret" not in status_response.text


def test_runtime_model_config_persists_per_authenticated_user(tmp_path, monkeypatch) -> None:
    first_client = _authenticated_client(tmp_path, monkeypatch, "student-a@example.test")
    response = first_client.post(
        "/api/model-config/runtime",
        json={
            "provider": "anthropic",
            "api_key": "student-anthropic-secret",
            "model": "claude-3-5-sonnet-latest",
            "base_url": "https://api.anthropic.com",
            "proxy_url": "direct",
        },
    )
    runtime_model_config_store.clear()
    restored_response = first_client.get("/api/model-config/runtime")

    assert response.status_code == 200
    assert restored_response.status_code == 200
    assert restored_response.json()["active"] is True
    assert restored_response.json()["provider"] == "anthropic"
    assert restored_response.json()["model"] == "claude-3-5-sonnet-latest"
    assert restored_response.json()["api_key_saved"] is True
    assert "student-anthropic-secret" not in restored_response.text

    second_client = _authenticated_client(tmp_path, monkeypatch, "student-b@example.test")
    second_user_response = second_client.get("/api/model-config/runtime")

    assert second_user_response.status_code == 200
    assert second_user_response.json()["active"] is False


def test_runtime_model_config_can_reuse_saved_secret_without_echoing_it(tmp_path, monkeypatch) -> None:
    client = _authenticated_client(tmp_path, monkeypatch, "student-a@example.test")
    first_response = client.post(
        "/api/model-config/runtime",
        json={
            "provider": "openai_compatible",
            "api_key": "student-openai-secret",
            "model": "first-model",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "direct",
        },
    )
    runtime_model_config_store.clear()
    second_response = client.post(
        "/api/model-config/runtime",
        json={
            "provider": "openai_compatible",
            "api_key": "",
            "model": "second-model",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "direct",
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["active"] is True
    assert second_response.json()["model"] == "second-model"
    assert second_response.json()["api_key_saved"] is True
    assert runtime_model_config_store.get_active_config().api_key == "student-openai-secret"
    assert "student-openai-secret" not in second_response.text
