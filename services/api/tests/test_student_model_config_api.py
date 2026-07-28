import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import AUTH_COOKIE_NAME
from app.services.account_model_endpoint_policy import (
    ACCOUNT_MODEL_ENDPOINT_POLICY_ERROR,
    ACCOUNT_MODEL_PROVIDER_POLICY_ERROR,
    ACCOUNT_MODEL_PROXY_POLICY_ERROR,
)
from app.services.auth_store import AuthStore
from app.services.model_call_policy import ModelProviderTimeoutError
from app.services.runtime_model_config_store import (
    RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS,
    VERTEX_RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS,
    RuntimeModelConfig,
)
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services import student_model_config_service


class _FakeConnectivityResponse:
    is_success = True
    status_code = 200


class _FakeConnectivityErrorResponse:
    is_success = False
    status_code = 400
    text = '{"error":{"code":"400","message":"Param Incorrect","param":"Not supported model unsupported-model"}}'

    def json(self) -> dict[str, object]:
        return {
            "error": {
                "code": "400",
                "message": "Param Incorrect",
                "param": "Not supported model unsupported-model",
            },
        }


class _FakeHttpxClient:
    requested_urls: list[str] = []
    requested_headers: list[dict[str, str]] = []
    created_options: list[dict[str, object]] = []

    def __init__(self, **options: object) -> None:
        self.created_options.append(options)

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
    created_options: list[dict[str, object]] = []

    def __init__(self, **options: object) -> None:
        self.created_options.append(options)

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
    # Existing provider-adapter tests intentionally exercise the explicit
    # single-user escape hatch. Security-default tests override this below.
    monkeypatch.setenv(
        "CLINICAL_OSCE_ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS",
        "true",
    )
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(main, "auth_store", auth_store)
    user = auth_store.create_user(email, "safe-password-123", email)
    assert user is not None
    token = auth_store.create_session(user["user_id"])
    client = TestClient(main.app)
    client.cookies.set(AUTH_COOKIE_NAME, token)
    return client


def test_student_model_config_test_requires_authentication_before_http_probe(monkeypatch) -> None:
    _FakeHttpxClient.requested_urls = []
    _FakeHttpxClient.requested_headers = []
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-dev")
    monkeypatch.setattr(student_model_config_service.httpx, "Client", _FakeHttpxClient)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/test",
            json={
                "provider": "custom_backend",
                "api_key": "anonymous-secret-value",
                "model": "",
                "base_url": "http://internal.example/api",
                "proxy_url": "direct",
            },
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}
    assert _FakeHttpxClient.requested_urls == []
    assert _FakeHttpxClient.requested_headers == []


def test_unauthenticated_model_config_test_does_not_change_process_proxy(monkeypatch) -> None:
    _FakeVertexGeminiClient.created = []
    _FakeVertexGeminiModels.calls = []
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    original_proxy_environment = {
        "HTTP_PROXY": "http://original-http-proxy.example",
        "HTTPS_PROXY": "http://original-https-proxy.example",
        "ALL_PROXY": "socks5://original-all-proxy.example",
    }
    for name, value in original_proxy_environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(student_model_config_service.genai, "Client", _FakeVertexGeminiClient)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/test",
            json={
                "provider": "vertex_gemini_adc",
                "api_key": "",
                "model": "gemini-3.1-pro-preview",
                "base_url": "demo-project",
                "proxy_url": "http://attacker-proxy.example",
            },
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}
    assert {name: os.environ.get(name) for name in original_proxy_environment} == original_proxy_environment
    assert _FakeVertexGeminiClient.created == []
    assert _FakeVertexGeminiModels.calls == []


def test_authenticated_student_model_config_test_accepts_custom_byok_backend_without_admin_role(
    tmp_path,
    monkeypatch,
) -> None:
    _FakeHttpxClient.requested_urls = []
    _FakeHttpxClient.requested_headers = []
    monkeypatch.setattr(student_model_config_service.httpx, "Client", _FakeHttpxClient)

    client = _authenticated_client(tmp_path, monkeypatch, "student-custom-byok@example.test")
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


def test_shared_account_model_endpoints_reject_ssrf_proxy_and_server_adc_before_io(
    tmp_path,
    monkeypatch,
) -> None:
    _FakeHttpxClient.requested_urls = []
    _FakeHttpxClient.requested_headers = []
    _FakeVertexGeminiClient.created = []
    _FakeVertexGeminiModels.calls = []
    monkeypatch.setattr(student_model_config_service.httpx, "Client", _FakeHttpxClient)
    monkeypatch.setattr(
        student_model_config_service.genai,
        "Client",
        _FakeVertexGeminiClient,
    )
    client = _authenticated_client(
        tmp_path,
        monkeypatch,
        "student-shared-policy@example.test",
    )
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")

    custom_response = client.post(
        "/api/model-config/test",
        json={
            "provider": "custom_backend",
            "api_key": "student-secret",
            "model": "",
            "base_url": "http://127.0.0.1:8765/internal",
            "proxy_url": "direct",
        },
    )
    private_url_response = client.post(
        "/api/model-config/runtime",
        json={
            "provider": "openai_compatible",
            "api_key": "student-secret",
            "model": "student-model",
            "base_url": "http://127.0.0.1:8765/v1",
            "proxy_url": "direct",
        },
    )
    proxy_response = client.post(
        "/api/model-config/runtime",
        json={
            "provider": "openai_compatible",
            "api_key": "student-secret",
            "model": "student-model",
            "base_url": "https://api.openai.com/v1",
            "proxy_url": "http://127.0.0.1:7897",
        },
    )
    adc_response = client.post(
        "/api/model-config/runtime",
        json={
            "provider": "vertex_gemini_adc",
            "api_key": "",
            "model": "gemini-3.1-pro-preview",
            "base_url": "server-project",
            "proxy_url": "direct",
        },
    )

    assert custom_response.status_code == 400
    assert custom_response.json() == {
        "detail": ACCOUNT_MODEL_PROVIDER_POLICY_ERROR,
    }
    assert private_url_response.status_code == 400
    assert private_url_response.json() == {
        "detail": ACCOUNT_MODEL_ENDPOINT_POLICY_ERROR,
    }
    assert proxy_response.status_code == 400
    assert proxy_response.json() == {
        "detail": ACCOUNT_MODEL_PROXY_POLICY_ERROR,
    }
    assert adc_response.status_code == 400
    assert adc_response.json() == {
        "detail": ACCOUNT_MODEL_PROVIDER_POLICY_ERROR,
    }
    assert _FakeHttpxClient.requested_urls == []
    assert _FakeHttpxClient.requested_headers == []
    assert _FakeVertexGeminiClient.created == []
    assert _FakeVertexGeminiModels.calls == []


def test_previously_saved_unsafe_account_config_is_not_bound_to_real_calls(
    tmp_path,
    monkeypatch,
) -> None:
    client = _authenticated_client(
        tmp_path,
        monkeypatch,
        "student-stale-unsafe@example.test",
    )
    saved_user = main.auth_store.get_user_by_session_token(
        client.cookies.get(AUTH_COOKIE_NAME)
    )
    assert saved_user is not None
    main.user_model_config_store.save_runtime_config(
        saved_user["user_id"],
        RuntimeModelConfig(
            provider="openai_compatible",
            api_key="stale-secret",
            model="stale-model",
            base_url="http://127.0.0.1:8765/v1",
            proxy_url="direct",
        ),
    )
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")

    status_response = client.get("/api/model-config/runtime")
    resolved_config = main._resolve_user_runtime_model_config(
        saved_user["user_id"]
    )
    with main._use_user_runtime_model_config(
        saved_user["user_id"],
        require_for_training=False,
    ):
        bound_config = runtime_model_config_store.get_active_config()

    assert status_response.status_code == 200
    assert status_response.json()["active"] is False
    assert status_response.json()["base_url"] == ""
    assert "127.0.0.1" not in status_response.text
    assert "stale-secret" not in status_response.text
    assert resolved_config is None
    assert bound_config is None


def test_student_model_config_test_rejects_remote_provider_without_api_key(tmp_path, monkeypatch) -> None:
    client = _authenticated_client(tmp_path, monkeypatch, "student-gemini-missing-key@example.test")
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


def test_student_model_config_test_is_disabled_in_production_deployment_mode(monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")
    monkeypatch.setenv("CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS", "https://osce.example")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/test",
            headers={"Origin": "https://osce.example", "Sec-Fetch-Site": "same-origin"},
            json={
                "provider": "openai_compatible",
                "api_key": "student-openai-secret",
                "model": "gemini-via-proxy",
                "base_url": "https://api.proxy.example/v1",
                "proxy_url": "direct",
            },
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "runtime model config is disabled in production deployment mode"}


def test_student_model_config_test_openai_compatible_uses_chat_completion_probe(tmp_path, monkeypatch) -> None:
    _FakeOpenAICompatibleProbeClient.requested_urls = []
    _FakeOpenAICompatibleProbeClient.requested_headers = []
    _FakeOpenAICompatibleProbeClient.requested_bodies = []
    monkeypatch.setattr(student_model_config_service.httpx, "Client", _FakeOpenAICompatibleProbeClient)

    client = _authenticated_client(tmp_path, monkeypatch, "student-openai-probe@example.test")
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
    assert _FakeOpenAICompatibleProbeClient.created_options[-1]["follow_redirects"] is False


def test_student_model_config_test_includes_sanitized_provider_error_detail(tmp_path, monkeypatch) -> None:
    _FakeOpenAICompatibleErrorProbeClient.requested_urls = []
    _FakeOpenAICompatibleErrorProbeClient.requested_headers = []
    _FakeOpenAICompatibleErrorProbeClient.requested_bodies = []
    monkeypatch.setattr(student_model_config_service.httpx, "Client", _FakeOpenAICompatibleErrorProbeClient)

    client = _authenticated_client(tmp_path, monkeypatch, "student-openai-error@example.test")
    response = client.post(
        "/api/model-config/test",
        json={
            "provider": "openai_compatible",
            "api_key": "student-openai-secret",
            "model": "unsupported-model",
            "base_url": "https://fallback-gateway.example/v1",
            "proxy_url": "direct",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["message"] == "连通性测试失败：HTTP 400"
    assert "Param Incorrect" not in response.text
    assert "unsupported-model" not in response.text
    assert "student-openai-secret" not in response.text
    assert "student-openai-secret" not in response.text


def test_student_model_config_test_anthropic_uses_messages_probe(tmp_path, monkeypatch) -> None:
    _FakeOpenAICompatibleProbeClient.requested_urls = []
    _FakeOpenAICompatibleProbeClient.requested_headers = []
    _FakeOpenAICompatibleProbeClient.requested_bodies = []
    monkeypatch.setattr(student_model_config_service.httpx, "Client", _FakeOpenAICompatibleProbeClient)

    client = _authenticated_client(tmp_path, monkeypatch, "student-anthropic-probe@example.test")
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


def test_student_model_config_test_vertex_gemini_adc_uses_adc_without_api_key(tmp_path, monkeypatch) -> None:
    _FakeVertexGeminiClient.created = []
    _FakeVertexGeminiModels.calls = []
    monkeypatch.setattr(student_model_config_service.genai, "Client", _FakeVertexGeminiClient)

    client = _authenticated_client(tmp_path, monkeypatch, "student-vertex-adc-probe@example.test")
    response = client.post(
        "/api/model-config/test",
        json={
            "provider": "vertex_gemini_adc",
            "api_key": "",
            "model": "gemini-3.1-pro-preview",
            "base_url": "demo-project",
            "proxy_url": "direct",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "vertex_gemini_adc"
    assert payload["checked_url"] == "vertex://demo-project/global/gemini-3.1-pro-preview"
    client_kwargs = _FakeVertexGeminiClient.created[0]
    assert {key: value for key, value in client_kwargs.items() if key != "http_options"} == {
        "vertexai": True,
        "project": "demo-project",
        "location": "global",
    }
    assert client_kwargs["http_options"].client_args == {
        "follow_redirects": False,
        "trust_env": False,
    }
    assert client_kwargs["http_options"].timeout == int(
        student_model_config_service.STUDENT_MODEL_CONFIG_TIMEOUT_SECONDS
        * 1_000
    )
    assert client_kwargs["http_options"].retry_options.attempts == 1
    assert client_kwargs["http_options"].async_client_args["trust_env"] is False
    assert _FakeVertexGeminiModels.calls[0]["model"] == "gemini-3.1-pro-preview"
    assert "api_key" not in str(_FakeVertexGeminiClient.created)


@pytest.mark.parametrize(
    ("provider", "api_key", "base_url"),
    [
        ("vertex_gemini_adc", "", "demo-project"),
        ("vertex_gemini_api_key", "student-vertex-secret", ""),
    ],
)
def test_student_vertex_probe_preserves_model_policy_timeout(
    tmp_path,
    monkeypatch,
    provider: str,
    api_key: str,
    base_url: str,
) -> None:
    monkeypatch.setattr(
        student_model_config_service.genai,
        "Client",
        _FakeVertexGeminiClient,
    )

    def fail_with_policy_timeout(*_: object, **__: object) -> object:
        raise ModelProviderTimeoutError("deadline exceeded")

    monkeypatch.setattr(
        student_model_config_service,
        "run_model_provider_call",
        fail_with_policy_timeout,
    )
    client = _authenticated_client(
        tmp_path,
        monkeypatch,
        f"student-{provider}-timeout@example.test",
    )

    response = client.post(
        "/api/model-config/test",
        json={
            "provider": provider,
            "api_key": api_key,
            "model": "gemini-3.1-pro-preview",
            "base_url": base_url,
            "proxy_url": "direct",
        },
    )

    assert response.status_code == 504
    assert response.json() == {
        "detail": main.MODEL_PROVIDER_TIMEOUT_DETAIL,
    }


def test_student_model_config_test_rejects_per_user_vertex_adc_proxy_without_environment_mutation(
    tmp_path,
    monkeypatch,
) -> None:
    _FakeVertexGeminiClient.created = []
    _FakeVertexGeminiModels.calls = []
    monkeypatch.setattr(student_model_config_service.genai, "Client", _FakeVertexGeminiClient)
    original_proxy_environment = {
        "HTTP_PROXY": "http://original-http-proxy.example",
        "HTTPS_PROXY": "http://original-https-proxy.example",
        "ALL_PROXY": "socks5://original-all-proxy.example",
    }
    for name, value in original_proxy_environment.items():
        monkeypatch.setenv(name, value)

    client = _authenticated_client(tmp_path, monkeypatch, "student-vertex-adc-proxy@example.test")
    response = client.post(
        "/api/model-config/test",
        json={
            "provider": "vertex_gemini_adc",
            "api_key": "",
            "model": "gemini-3.1-pro-preview",
            "base_url": "demo-project",
            "proxy_url": "http://per-user-proxy.example:8080",
        },
    )

    assert response.status_code == 400
    assert "账号级代理仅支持 direct" in response.json()["detail"]
    assert _FakeVertexGeminiClient.created == []
    assert _FakeVertexGeminiModels.calls == []
    assert {name: os.environ.get(name) for name in original_proxy_environment} == original_proxy_environment


def test_student_model_config_test_vertex_gemini_api_key_uses_express_mode_without_project(
    tmp_path,
    monkeypatch,
) -> None:
    _FakeVertexGeminiClient.created = []
    _FakeVertexGeminiModels.calls = []
    monkeypatch.setattr(student_model_config_service.genai, "Client", _FakeVertexGeminiClient)

    client = _authenticated_client(tmp_path, monkeypatch, "student-vertex-key-probe@example.test")
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
    client_kwargs = _FakeVertexGeminiClient.created[0]
    assert {key: value for key, value in client_kwargs.items() if key != "http_options"} == {
        "vertexai": True,
        "api_key": "student-vertex-secret",
    }
    assert client_kwargs["http_options"].client_args == {
        "follow_redirects": False,
        "trust_env": False,
        "proxy": "http://127.0.0.1:7897",
    }
    assert client_kwargs["http_options"].timeout == int(
        student_model_config_service.STUDENT_MODEL_CONFIG_TIMEOUT_SECONDS
        * 1_000
    )
    assert client_kwargs["http_options"].retry_options.attempts == 1
    assert client_kwargs["http_options"].async_client_args["trust_env"] is False
    assert client_kwargs["http_options"].async_client_args["proxy"] == "http://127.0.0.1:7897"
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
        "integration_targets": list(RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
        "message": "OpenAI 兼容服务端配置已保存，仅在当前账号的训练与报告请求中生效。",
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
        "integration_targets": list(RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
        "message": "Anthropic 服务端配置已保存，仅在当前账号的训练与报告请求中生效。",
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
            "proxy_url": "direct",
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
        "proxy_url": "direct",
        "project": "demo-project",
        "location": "global",
        "api_key_saved": False,
        "integration_targets": list(VERTEX_RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
        "message": "Vertex Gemini ADC 配置已保存，仅在当前账号的训练与报告请求中生效。",
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
        "integration_targets": list(VERTEX_RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
        "message": "Vertex Gemini API Key 配置已保存，仅在当前账号的训练与报告请求中生效。",
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


def test_production_runtime_config_status_exposes_environment_default_without_user_secret(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "true")
    monkeypatch.setenv("OSCE_OPENAI_API_KEY", "server-gemini-secret")
    monkeypatch.setenv("OSCE_OPENAI_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("OSCE_OPENAI_BASE_URL", "https://managed-gateway.example/v1")
    monkeypatch.setenv("OSCE_OPENAI_PROXY_URL", "direct")
    client = _authenticated_client(tmp_path, monkeypatch, "student-prod@example.test")

    status_response = client.get("/api/model-config/runtime")

    assert status_response.status_code == 200
    assert status_response.json() == {
        "active": True,
        "provider": "openai_compatible",
        "model": "gemini-3.5-flash",
        "base_url": "",
        "proxy_url": "",
        "integration_targets": list(RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
        "api_key_saved": False,
        "message": "服务端已统一配置 Gemini 模型；前端不可修改 API Key。",
        "runtime_write_supported": False,
        "deployment_mode": "single-node-prod",
    }
    assert "server-gemini-secret" not in status_response.text


def test_server_managed_model_config_disables_runtime_writes_in_demo_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-dev")
    monkeypatch.setenv("CLINICAL_OSCE_SERVER_MANAGED_MODEL_CONFIG", "true")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "true")
    monkeypatch.setenv("OSCE_OPENAI_API_KEY", "server-gemini-secret")
    monkeypatch.setenv("OSCE_OPENAI_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("OSCE_OPENAI_BASE_URL", "https://managed-gateway.example/v1")
    monkeypatch.setenv("OSCE_OPENAI_PROXY_URL", "direct")
    client = _authenticated_client(tmp_path, monkeypatch, "student-managed@example.test")

    write_response = client.post(
        "/api/model-config/runtime",
        json={
            "provider": "openai_compatible",
            "api_key": "student-openai-secret",
            "model": "student-model",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "direct",
        },
    )
    status_response = client.get("/api/model-config/runtime")

    assert write_response.status_code == 403
    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["active"] is True
    assert payload["provider"] == "openai_compatible"
    assert payload["model"] == "gemini-3.5-flash"
    assert payload["base_url"] == ""
    assert payload["proxy_url"] == ""
    assert payload["api_key_saved"] is False
    assert payload["runtime_write_supported"] is False
    assert payload["deployment_mode"] == "local-dev"
    assert "server-gemini-secret" not in status_response.text
    assert "student-openai-secret" not in status_response.text


def test_server_managed_model_config_ignores_previously_saved_user_runtime_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    monkeypatch.setenv("CLINICAL_OSCE_SERVER_MANAGED_MODEL_CONFIG", "true")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "true")
    monkeypatch.setenv("OSCE_OPENAI_API_KEY", "server-gemini-secret")
    monkeypatch.setenv("OSCE_OPENAI_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("OSCE_OPENAI_BASE_URL", "https://managed-gateway.example/v1")
    monkeypatch.setenv("OSCE_OPENAI_PROXY_URL", "direct")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(main, "auth_store", auth_store)
    user = auth_store.create_user("student-managed-saved@example.test", "safe-password-123", "学生")
    assert user is not None
    main.user_model_config_store.save_runtime_config(
        user["user_id"],
        RuntimeModelConfig(
            provider="openai_compatible",
            api_key="old-student-secret",
            model="student-old-model",
            base_url="https://student-old.example/v1",
            proxy_url="direct",
        ),
    )
    token = auth_store.create_session(user["user_id"])
    client = TestClient(main.app)
    client.cookies.set(AUTH_COOKIE_NAME, token)

    status_response = client.get("/api/model-config/runtime")

    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["active"] is True
    assert payload["provider"] == "openai_compatible"
    assert payload["model"] == "gemini-3.5-flash"
    assert payload["base_url"] == ""
    assert payload["api_key_saved"] is False
    assert payload["runtime_write_supported"] is False
    assert "old-student-secret" not in status_response.text


def test_production_training_uses_environment_default_when_runtime_write_is_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")
    monkeypatch.setenv("CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS", "https://osce.example")
    monkeypatch.setenv("OSCE_REQUIRE_RUNTIME_MODEL_CONFIG_FOR_TRAINING", "1")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "true")
    monkeypatch.setenv("OSCE_OPENAI_API_KEY", "server-gemini-secret")
    monkeypatch.setenv("OSCE_OPENAI_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("OSCE_OPENAI_BASE_URL", "https://managed-gateway.example/v1")
    monkeypatch.setenv("OSCE_OPENAI_PROXY_URL", "direct")
    client = _authenticated_client(tmp_path, monkeypatch, "student-prod-session@example.test")

    response = client.post(
        "/api/sessions",
        headers={"Origin": "https://osce.example", "Sec-Fetch-Site": "same-origin"},
        json={"case_id": "appendicitis_001"},
    )

    assert response.status_code == 200
    assert response.json()["case_id"] == "appendicitis_001"


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
    saved_user = main.auth_store.get_user_by_session_token(client.cookies.get(AUTH_COOKIE_NAME))
    assert saved_user is not None
    saved_config = main.user_model_config_store.get_runtime_config(saved_user["user_id"])
    assert saved_config is not None
    assert saved_config.api_key == "student-openai-secret"
    assert runtime_model_config_store.get_active_config() is None
    assert "student-openai-secret" not in second_response.text


def test_authenticated_connectivity_test_reuses_saved_secret_without_echoing_it(tmp_path, monkeypatch) -> None:
    _FakeOpenAICompatibleProbeClient.requested_urls = []
    _FakeOpenAICompatibleProbeClient.requested_headers = []
    _FakeOpenAICompatibleProbeClient.requested_bodies = []
    monkeypatch.setattr(student_model_config_service.httpx, "Client", _FakeOpenAICompatibleProbeClient)

    client = _authenticated_client(tmp_path, monkeypatch, "student-retest@example.test")
    save_response = client.post(
        "/api/model-config/runtime",
        json={
            "provider": "openai_compatible",
            "api_key": "student-openai-secret",
            "model": "saved-model",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "direct",
        },
    )
    runtime_model_config_store.clear()
    test_response = client.post(
        "/api/model-config/test",
        json={
            "provider": "openai_compatible",
            "api_key": "",
            "model": "saved-model",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "direct",
        },
    )

    assert save_response.status_code == 200
    assert test_response.status_code == 200
    assert test_response.json()["ok"] is True
    assert _FakeOpenAICompatibleProbeClient.requested_headers == [{"Authorization": "Bearer student-openai-secret"}]
    assert "student-openai-secret" not in test_response.text
