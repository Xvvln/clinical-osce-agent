import os

from app.services import gemini_patient_responder as module
from app.services import anthropic_chat_client as anthropic_module
from app.services import openai_compatible_chat_client as openai_module
from app.services.runtime_model_config_store import runtime_model_config_store


class FakeModels:
    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        raise AssertionError("本测试只验证客户端创建，不应触发模型调用")


class FakeVertexClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.models = FakeModels()


def test_gemini_patient_settings_defaults_to_gemini_31_pro_preview() -> None:
    settings = module.GeminiPatientSettings(_env_file=None)

    assert settings.location == "global"
    assert settings.model == "gemini-3.1-pro-preview"
    assert settings.proxy_url == "http://127.0.0.1:7897"


def test_create_configured_patient_responder_falls_back_to_deterministic_without_external_config(monkeypatch) -> None:
    runtime_model_config_store.clear()
    for key in [
        "OSCE_GEMINI_PATIENT_API_KEY",
        "OSCE_GEMINI_PATIENT_PROJECT",
        "OSCE_VERTEX_API_KEY",
        "OSCE_VERTEX_PROJECT",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OSCE_OPENAI_API_KEY",
        "OSCE_OPENAI_MODEL",
    ]:
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_USE_VERTEX", "false")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "false")

    def fail_client(**kwargs: object) -> object:
        raise AssertionError(f"external Gemini client should not be created: {kwargs}")

    monkeypatch.setattr(module.genai, "Client", fail_client)

    responder = module._create_configured_responder()
    reply = responder(
        module.PatientResponderRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            student_message="哪里疼？",
            current_intent="ask_location",
            canonical_answer="右下腹疼痛明显。",
            forbidden_terms=["急性阑尾炎"],
        )
    )

    assert isinstance(responder, module.DeterministicPatientResponder)
    assert reply == "右下腹疼痛明显。"


def test_create_configured_patient_responder_uses_vertex_adc_without_api_key(monkeypatch) -> None:
    captured_clients: list[FakeVertexClient] = []

    def fake_client(**kwargs: object) -> FakeVertexClient:
        client = FakeVertexClient(**kwargs)
        captured_clients.append(client)
        return client

    monkeypatch.setattr(module.genai, "Client", fake_client)
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_USE_VERTEX", "true")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_PROJECT", "demo-project")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_LOCATION", "global")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_MODEL", "gemini-3.1-pro-preview")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7897")

    responder = module._create_configured_responder()

    assert responder._settings.api_key == ""
    assert responder._settings.use_vertex is True
    assert responder._settings.project == "demo-project"
    assert responder._settings.location == "global"
    assert responder._settings.model == "gemini-3.1-pro-preview"
    assert captured_clients[0].kwargs == {
        "vertexai": True,
        "project": "demo-project",
        "location": "global",
    }
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["ALL_PROXY"] == "http://127.0.0.1:7897"


class FakeOpenAICompatiblePatientResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"reply":"我右下腹疼得比较明显。"}',
                    },
                }
            ],
        }


class FakeOpenAICompatibleHttpClient:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def __enter__(self) -> "FakeOpenAICompatibleHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeOpenAICompatiblePatientResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeOpenAICompatiblePatientResponse()


class FakeAnthropicPatientResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": '{"reply":"我右下腹疼得比较明显。"}',
                }
            ],
        }


class FakeAnthropicHttpClient:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def __enter__(self) -> "FakeAnthropicHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeAnthropicPatientResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeAnthropicPatientResponse()


class FakePlainTextAnthropicPatientResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "开始时上腹部疼，现在右下腹最疼。",
                }
            ],
        }


class FakePlainTextAnthropicHttpClient(FakeAnthropicHttpClient):
    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakePlainTextAnthropicPatientResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakePlainTextAnthropicPatientResponse()


def test_create_configured_patient_responder_uses_runtime_openai_compatible_config(monkeypatch) -> None:
    FakeOpenAICompatibleHttpClient.calls = []
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "openai_compatible",
            "api_key": "student-openai-secret",
            "model": "gemini-via-clprox",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "http://127.0.0.1:7897",
        }
    )
    monkeypatch.setattr(openai_module.httpx, "Client", FakeOpenAICompatibleHttpClient)
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    try:
        responder = module._create_configured_responder()
        reply = responder(
            module.PatientResponderRequest(
                case_id="appendicitis_001",
                case_title="急性腹痛问诊",
                chief_complaint="腹痛 1 天",
                student_message="哪里疼？",
                current_intent="ask_location",
                canonical_answer="右下腹疼痛明显。",
                forbidden_terms=["急性阑尾炎"],
            )
        )
    finally:
        runtime_model_config_store.clear()

    assert reply == "我右下腹疼得比较明显。"
    assert FakeOpenAICompatibleHttpClient.calls[0]["url"] == "https://api.proxy.example/v1/chat/completions"
    assert FakeOpenAICompatibleHttpClient.calls[0]["headers"]["Authorization"] == "Bearer student-openai-secret"
    assert FakeOpenAICompatibleHttpClient.calls[0]["json"]["model"] == "gemini-via-clprox"


def test_create_configured_patient_responder_uses_runtime_anthropic_config(monkeypatch) -> None:
    FakeAnthropicHttpClient.calls = []
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "anthropic",
            "api_key": "student-anthropic-secret",
            "model": "claude-3-5-sonnet-latest",
            "base_url": "https://api.anthropic.com",
            "proxy_url": "http://127.0.0.1:7897",
        }
    )
    monkeypatch.setattr(anthropic_module.httpx, "Client", FakeAnthropicHttpClient)
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    try:
        responder = module._create_configured_responder()
        reply = responder(
            module.PatientResponderRequest(
                case_id="appendicitis_001",
                case_title="急性腹痛问诊",
                chief_complaint="腹痛 1 天",
                student_message="哪里疼？",
                current_intent="ask_location",
                canonical_answer="右下腹疼痛明显。",
                forbidden_terms=["急性阑尾炎"],
            )
        )
    finally:
        runtime_model_config_store.clear()

    assert reply == "我右下腹疼得比较明显。"
    assert FakeAnthropicHttpClient.calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert FakeAnthropicHttpClient.calls[0]["headers"]["x-api-key"] == "student-anthropic-secret"
    assert FakeAnthropicHttpClient.calls[0]["headers"]["anthropic-version"] == "2023-06-01"
    assert FakeAnthropicHttpClient.calls[0]["json"]["model"] == "claude-3-5-sonnet-latest"


def test_anthropic_patient_responder_accepts_plain_text_reply_for_single_field_schema(monkeypatch) -> None:
    FakePlainTextAnthropicHttpClient.calls = []
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "anthropic",
            "api_key": "student-anthropic-secret",
            "model": "mimo-v2.5-pro",
            "base_url": "https://api.anthropic.com",
            "proxy_url": "direct",
        }
    )
    monkeypatch.setattr(anthropic_module.httpx, "Client", FakePlainTextAnthropicHttpClient)
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    try:
        responder = module._create_configured_responder()
        reply = responder(
            module.PatientResponderRequest(
                case_id="appendicitis_001",
                case_title="急性腹痛问诊",
                chief_complaint="腹痛 1 天",
                student_message="哪里最疼？",
                current_intent="ask_location",
                canonical_answer="现在右下腹疼痛明显。",
                forbidden_terms=["急性阑尾炎"],
            )
        )
    finally:
        runtime_model_config_store.clear()

    assert reply == "开始时上腹部疼，现在右下腹最疼。"
    assert FakePlainTextAnthropicHttpClient.calls[0]["url"] == "https://api.anthropic.com/v1/messages"


def test_create_configured_patient_responder_uses_runtime_vertex_gemini_adc_config(monkeypatch) -> None:
    captured_clients: list[FakeVertexClient] = []

    def fake_client(**kwargs: object) -> FakeVertexClient:
        client = FakeVertexClient(**kwargs)
        captured_clients.append(client)
        return client

    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "vertex_gemini_adc",
            "api_key": "",
            "model": "gemini-3.1-pro-preview",
            "base_url": "demo-project",
            "proxy_url": "http://127.0.0.1:7897",
        }
    )
    monkeypatch.setattr(module.genai, "Client", fake_client)
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    try:
        responder = module._create_configured_responder()
    finally:
        runtime_model_config_store.clear()

    assert responder._settings.use_vertex is True
    assert responder._settings.project == "demo-project"
    assert responder._settings.location == "global"
    assert responder._settings.model == "gemini-3.1-pro-preview"
    assert captured_clients[0].kwargs == {
        "vertexai": True,
        "project": "demo-project",
        "location": "global",
    }
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"


def test_create_configured_patient_responder_uses_runtime_vertex_gemini_api_key_config(monkeypatch) -> None:
    captured_clients: list[FakeVertexClient] = []

    def fake_client(**kwargs: object) -> FakeVertexClient:
        client = FakeVertexClient(**kwargs)
        captured_clients.append(client)
        return client

    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "vertex_gemini_api_key",
            "api_key": "student-vertex-secret",
            "model": "gemini-2.5-flash",
            "base_url": "",
            "proxy_url": "http://127.0.0.1:7897",
        }
    )
    monkeypatch.setattr(module.genai, "Client", fake_client)
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    try:
        responder = module._create_configured_responder()
    finally:
        runtime_model_config_store.clear()

    assert responder._settings.use_vertex is True
    assert responder._settings.api_key == "student-vertex-secret"
    assert responder._settings.project == ""
    assert responder._settings.location == "global"
    assert responder._settings.model == "gemini-2.5-flash"
    assert captured_clients[0].kwargs == {
        "vertexai": True,
        "api_key": "student-vertex-secret",
    }
