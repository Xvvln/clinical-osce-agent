import os

import pytest

from app.services import anthropic_chat_client as anthropic_module
from app.services import coach_agent as module
from app.services import openai_compatible_chat_client as openai_module
from app.services.runtime_model_config_store import runtime_model_config_store


class FakeGeminiModels:
    calls: list[dict[str, object]] = []

    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        self.calls.append({"model": model, "contents": contents, "config": config})

        class Response:
            text = '{"hint":"先按时间顺序追问疼痛演变，再决定下一步查体。"}'

        return Response()


class FakeGeminiClient:
    created: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.created.append(kwargs)
        self.models = FakeGeminiModels()


class FakeOpenAICompatibleCoachResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"choices": [{"message": {"content": '{"hint":"先追问疼痛转移，再进入查体。"}'}}]}


class FakeOpenAICompatibleHttpClient:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def __enter__(self) -> "FakeOpenAICompatibleHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeOpenAICompatibleCoachResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeOpenAICompatibleCoachResponse()


class FakeAnthropicCoachResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"content": [{"type": "text", "text": '{"hint":"先追问核心症状维度，再决定检查。"}'}]}


class FakeAnthropicHttpClient:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def __enter__(self) -> "FakeAnthropicHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeAnthropicCoachResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeAnthropicCoachResponse()


class FailingCoachAgent:
    def __call__(self, request: object) -> object:
        raise RuntimeError("provider unavailable")


def _request() -> module.CoachRequest:
    return module.CoachRequest(
        case_id="appendicitis_001",
        case_title="急性腹痛问诊",
        chief_complaint="腹痛 1 天",
        stage="history_taking",
        prompt_kind="socratic_hint",
        base_hint="先围绕疼痛的部位、性质、程度、伴随症状和既往史继续追问，不要急于下诊断。",
        prior_messages=[],
        pedagogy_state={"training_phase": "history_taking"},
        skill_context=[],
        forbidden_terms=[],
    )


def test_create_configured_coach_agent_falls_back_to_deterministic_without_external_config(monkeypatch) -> None:
    runtime_model_config_store.clear()
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "false")
    monkeypatch.setenv("OSCE_ANTHROPIC_ENABLED", "false")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_USE_VERTEX", "false")
    for key in ["OSCE_OPENAI_API_KEY", "OSCE_ANTHROPIC_API_KEY", "OSCE_GEMINI_PATIENT_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"]:
        monkeypatch.setenv(key, "")

    agent = module._create_configured_coach_agent()

    assert isinstance(agent, module.DeterministicCoachAgent)
    assert agent(_request()).hint == "先围绕疼痛的部位、性质、程度、伴随症状和既往史继续追问，不要急于下诊断。"


def test_lazy_coach_agent_raises_when_provider_fails(monkeypatch) -> None:
    monkeypatch.setattr(module, "_create_configured_coach_agent", lambda: FailingCoachAgent())

    with pytest.raises(RuntimeError, match="provider unavailable"):
        module.LazyCoachAgent()(_request())


def test_create_configured_coach_agent_uses_runtime_openai_compatible_config(monkeypatch) -> None:
    FakeOpenAICompatibleHttpClient.calls = []
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "openai_compatible",
            "api_key": "student-openai-secret",
            "model": "gemini-via-proxy",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "direct",
        }
    )
    monkeypatch.setattr(openai_module.httpx, "Client", FakeOpenAICompatibleHttpClient)

    try:
        agent = module._create_configured_coach_agent()
        response = agent(_request())
    finally:
        runtime_model_config_store.clear()

    assert isinstance(agent, module.OpenAICompatibleCoachAgent)
    assert response.hint == "先追问疼痛转移，再进入查体。"
    assert FakeOpenAICompatibleHttpClient.calls[0]["url"] == "https://api.proxy.example/v1/chat/completions"
    assert FakeOpenAICompatibleHttpClient.calls[0]["headers"]["Authorization"] == "Bearer student-openai-secret"
    assert FakeOpenAICompatibleHttpClient.calls[0]["json"]["model"] == "gemini-via-proxy"
    assert "急性阑尾炎" not in str(FakeOpenAICompatibleHttpClient.calls[0]["json"])


def test_create_configured_coach_agent_uses_runtime_anthropic_config(monkeypatch) -> None:
    FakeAnthropicHttpClient.calls = []
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "anthropic",
            "api_key": "student-anthropic-secret",
            "model": "claude-3-5-sonnet-latest",
            "base_url": "https://api.anthropic.com",
            "proxy_url": "direct",
        }
    )
    monkeypatch.setattr(anthropic_module.httpx, "Client", FakeAnthropicHttpClient)

    try:
        agent = module._create_configured_coach_agent()
        response = agent(_request())
    finally:
        runtime_model_config_store.clear()

    assert isinstance(agent, module.AnthropicCoachAgent)
    assert response.hint == "先追问核心症状维度，再决定检查。"
    assert FakeAnthropicHttpClient.calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert FakeAnthropicHttpClient.calls[0]["headers"]["x-api-key"] == "student-anthropic-secret"
    assert FakeAnthropicHttpClient.calls[0]["json"]["model"] == "claude-3-5-sonnet-latest"


def test_create_configured_coach_agent_uses_runtime_vertex_adc_config(monkeypatch) -> None:
    FakeGeminiClient.created = []
    FakeGeminiModels.calls = []
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
    monkeypatch.setattr(module.genai, "Client", FakeGeminiClient)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    try:
        agent = module._create_configured_coach_agent()
        response = agent(_request())
    finally:
        runtime_model_config_store.clear()

    assert isinstance(agent, module.GeminiCoachAgent)
    assert response.hint == "先按时间顺序追问疼痛演变，再决定下一步查体。"
    assert FakeGeminiClient.created == [{"vertexai": True, "project": "demo-project", "location": "global"}]
    assert FakeGeminiModels.calls[0]["model"] == "gemini-3.1-pro-preview"
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"
