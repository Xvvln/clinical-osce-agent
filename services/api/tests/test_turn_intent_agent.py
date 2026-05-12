import os

import pytest
from pydantic import ValidationError

from app.services import anthropic_chat_client as anthropic_module
from app.services import openai_compatible_chat_client as openai_module
from app.services import turn_intent_agent as module
from app.services.runtime_model_config_store import runtime_model_config_store


class FakeGeminiModels:
    calls: list[dict[str, object]] = []

    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        self.calls.append({"model": model, "contents": contents, "config": config})

        class Response:
            text = '{"current_intent":"ask_onset","confidence":0.88,"is_off_topic":false,"rationale":"学生在询问起病时间。"}'

        return Response()


class FakeGeminiClient:
    created: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.created.append(kwargs)
        self.models = FakeGeminiModels()


class FakeOpenAICompatibleTurnIntentResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"current_intent":"ask_onset","confidence":0.91,'
                            '"is_off_topic":false,"rationale":"学生在询问起病时间。"}'
                        ),
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

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeOpenAICompatibleTurnIntentResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeOpenAICompatibleTurnIntentResponse()


class FakePlainTextOpenAICompatibleTurnIntentResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": "我现在右下腹最疼。",
                    },
                }
            ],
        }


class FakePlainTextOpenAICompatibleHttpClient(FakeOpenAICompatibleHttpClient):
    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakePlainTextOpenAICompatibleTurnIntentResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakePlainTextOpenAICompatibleTurnIntentResponse()


class FakeAnthropicTurnIntentResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        '{"current_intent":"ask_location","confidence":0.87,'
                        '"is_off_topic":false,"rationale":"学生在询问疼痛部位。"}'
                    ),
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

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeAnthropicTurnIntentResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeAnthropicTurnIntentResponse()


class FailingTurnIntentAgent:
    def __call__(self, request: object) -> object:
        raise RuntimeError("provider unavailable")


def _request() -> module.TurnIntentRequest:
    return module.TurnIntentRequest(
        case_id="appendicitis_001",
        case_title="急性腹痛问诊",
        chief_complaint="腹痛 1 天",
        stage="history_taking",
        student_message="腹痛持续多久了？",
        keyword_intent="unknown_history_intent",
        prior_messages=[],
    )


def _request_with_keyword(keyword_intent: str) -> module.TurnIntentRequest:
    return _request().model_copy(update={"keyword_intent": keyword_intent})


def test_create_configured_turn_intent_agent_falls_back_to_deterministic_without_external_config(monkeypatch) -> None:
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
        "OSCE_ANTHROPIC_API_KEY",
        "OSCE_ANTHROPIC_MODEL",
    ]:
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_USE_VERTEX", "false")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "false")
    monkeypatch.setenv("OSCE_ANTHROPIC_ENABLED", "false")

    agent = module._create_configured_turn_intent_agent()

    assert isinstance(agent, module.DeterministicTurnIntentAgent)
    response = agent(_request())
    assert response.current_intent == "unknown_history_intent"


def test_deterministic_turn_intent_agent_classifies_unknown_history_kind() -> None:
    agent = module.DeterministicTurnIntentAgent()
    examples = [
        ("你好", "social_greeting", False, []),
        ("你是谁？", "patient_identity_unclear", False, []),
        ("你喜欢打游戏吗？", "off_topic", True, []),
        ("你的身份证号是多少？", "unsupported_case_question", False, []),
        ("还有没有其他不舒服？", "possible_missed_medical_intent", False, ["ask_associated_nausea", "ask_fever"]),
    ]

    for message, expected_unknown_kind, expected_off_topic, expected_possible_intents in examples:
        response = agent(_request().model_copy(update={"student_message": message}))

        assert response.current_intent == "unknown_history_intent"
        assert response.unknown_kind == expected_unknown_kind
        assert response.is_off_topic is expected_off_topic
        assert response.possible_intents[: len(expected_possible_intents)] == expected_possible_intents


def test_create_configured_turn_intent_agent_uses_runtime_openai_compatible_config(monkeypatch) -> None:
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
        agent = module._create_configured_turn_intent_agent()
        response = agent(_request())
    finally:
        runtime_model_config_store.clear()

    assert isinstance(agent, module.OpenAICompatibleTurnIntentAgent)
    assert response.current_intent == "ask_onset"
    assert FakeOpenAICompatibleHttpClient.calls[0]["url"] == "https://api.proxy.example/v1/chat/completions"
    assert FakeOpenAICompatibleHttpClient.calls[0]["headers"]["Authorization"] == "Bearer student-openai-secret"
    assert FakeOpenAICompatibleHttpClient.calls[0]["json"]["model"] == "gemini-via-proxy"
    assert "hidden_fact" not in str(FakeOpenAICompatibleHttpClient.calls[0]["json"])


def test_lazy_turn_intent_agent_raises_when_provider_returns_plain_text(monkeypatch) -> None:
    FakePlainTextOpenAICompatibleHttpClient.calls = []
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "openai_compatible",
            "api_key": "student-openai-secret",
            "model": "plain-text-model",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "direct",
        }
    )
    monkeypatch.setattr(openai_module.httpx, "Client", FakePlainTextOpenAICompatibleHttpClient)

    try:
        agent = module.LazyTurnIntentAgent()
        with pytest.raises(ValidationError):
            agent(_request_with_keyword("ask_location"))
    finally:
        runtime_model_config_store.clear()

    assert FakePlainTextOpenAICompatibleHttpClient.calls[0]["json"]["model"] == "plain-text-model"


def test_lazy_turn_intent_agent_raises_when_provider_fails(monkeypatch) -> None:
    monkeypatch.setattr(module, "_create_configured_turn_intent_agent", lambda: FailingTurnIntentAgent())

    with pytest.raises(RuntimeError, match="provider unavailable"):
        module.LazyTurnIntentAgent()(_request_with_keyword("ask_location"))


def test_lazy_turn_intent_agent_rebuilds_when_runtime_config_changes(monkeypatch) -> None:
    FakeOpenAICompatibleHttpClient.calls = []
    runtime_model_config_store.clear()
    monkeypatch.setattr(openai_module.httpx, "Client", FakeOpenAICompatibleHttpClient)
    agent = module.LazyTurnIntentAgent()

    try:
        runtime_model_config_store.apply_config(
            {
                "provider": "openai_compatible",
                "api_key": "first-secret",
                "model": "first-model",
                "base_url": "https://api.proxy.example/v1",
                "proxy_url": "direct",
            }
        )
        first_response = agent(_request())
        runtime_model_config_store.apply_config(
            {
                "provider": "openai_compatible",
                "api_key": "second-secret",
                "model": "second-model",
                "base_url": "https://api.proxy.example/v1",
                "proxy_url": "direct",
            }
        )
        second_response = agent(_request())
    finally:
        runtime_model_config_store.clear()

    assert first_response.current_intent == "ask_onset"
    assert second_response.current_intent == "ask_onset"
    assert [call["json"]["model"] for call in FakeOpenAICompatibleHttpClient.calls] == ["first-model", "second-model"]
    assert [call["headers"]["Authorization"] for call in FakeOpenAICompatibleHttpClient.calls] == [
        "Bearer first-secret",
        "Bearer second-secret",
    ]


def test_create_configured_turn_intent_agent_uses_runtime_anthropic_config(monkeypatch) -> None:
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
        agent = module._create_configured_turn_intent_agent()
        response = agent(_request())
    finally:
        runtime_model_config_store.clear()

    assert isinstance(agent, module.AnthropicTurnIntentAgent)
    assert response.current_intent == "ask_location"
    assert FakeAnthropicHttpClient.calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert FakeAnthropicHttpClient.calls[0]["headers"]["x-api-key"] == "student-anthropic-secret"
    assert FakeAnthropicHttpClient.calls[0]["json"]["model"] == "claude-3-5-sonnet-latest"


def test_create_configured_turn_intent_agent_uses_runtime_vertex_adc_config(monkeypatch) -> None:
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
        agent = module._create_configured_turn_intent_agent()
        response = agent(_request())
    finally:
        runtime_model_config_store.clear()

    assert isinstance(agent, module.GeminiTurnIntentAgent)
    assert response.current_intent == "ask_onset"
    assert agent._settings.project == "demo-project"
    assert FakeGeminiClient.created == [{"vertexai": True, "project": "demo-project", "location": "global"}]
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"
