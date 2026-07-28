import os

import pytest

from app.services import anthropic_chat_client as anthropic_module
from app.services import coach_agent as module
from app.services import openai_compatible_chat_client as openai_module
from app.services.coach_hint_context_service import build_coach_hint_context
from app.services.runtime_model_config_store import runtime_model_config_store
from app.graph.osce_graph import _load_case


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
    status_code = 200

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
    status_code = 200

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


class FakeExamStyleCoachClient:
    def complete_json(self, **_: object) -> module.CoachResponse:
        return module.CoachResponse(
            hint="患者提到起初是上腹部痛。请说明你的问诊目的。",
            trigger_kind="manual_hint",
        )


class FakePolicyDroppingCoachClient:
    def complete_json(self, **_: object) -> module.CoachResponse:
        return module.CoachResponse(
            hint="你已经问清了起病时间。接下来继续追问疼痛部位变化和疼痛性质。",
            trigger_kind="manual_hint",
        )


class RecordingCoachClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete_json(self, **kwargs: object) -> module.CoachResponse:
        self.calls.append(kwargs)
        return module.CoachResponse(
            hint="先按时间顺序补充病史，再决定下一步。",
            trigger_kind="manual_hint",
        )


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


def test_coach_request_carries_difficulty_and_hint_context() -> None:
    request = module.CoachRequest(
        case_id="appendicitis_001",
        case_title="急性腹痛问诊",
        chief_complaint="腹痛 1 天",
        stage="history_taking",
        training_difficulty="advanced",
        prompt_kind="socratic_hint",
        base_hint="先解释下一步为什么要补病史。",
        prior_messages=[{"role": "student", "content": "什么时候开始疼的？"}],
        pedagogy_state={"training_phase": "history_taking"},
        clinical_reasoning_state={"pedagogical_phase": "needs_history"},
        skill_context=["腹痛问诊训练：先建立疼痛时间线。"],
        retrieved_knowledge_context=[],
        hint_context={
            "session": {"training_difficulty": "advanced"},
            "next_step": {"base_hint": "先解释下一步为什么要补病史。"},
        },
        forbidden_terms=[],
    )

    payload = request.model_dump()

    assert payload["training_difficulty"] == "advanced"
    assert payload["hint_context"]["session"]["training_difficulty"] == "advanced"
    assert payload["hint_context"]["next_step"]["base_hint"] == "先解释下一步为什么要补病史。"


def test_coach_hint_context_exposes_humanistic_training_goals() -> None:
    case = _load_case("appendicitis_001")

    context = build_coach_hint_context(
        state={
            "session_id": "session-humanistic",
            "case_id": "appendicitis_001",
            "stage": "physical_exam",
            "messages": [],
            "active_skill_context": {
                "current_training_gaps": [
                    {
                        "gap_type": "ethics_consent_missing",
                        "label": "查体或检查前说明目的并征得同意",
                        "trigger_stage": "physical_exam",
                        "next_training_action": "下一轮查体或检查前先说明目的、可能不适并征得同意。",
                        "success_signal": "查体或检查前先说明目的并征得同意。",
                        "skill_type": "ethics_consent",
                        "status": "persistent",
                        "priority": 10,
                    }
                ],
                "humanistic_training_goals": [
                    {
                        "gap_type": "ethics_consent_missing",
                        "label": "查体或检查前说明目的并征得同意",
                        "trigger_stage": "physical_exam",
                        "next_training_action": "下一轮查体或检查前先说明目的、可能不适并征得同意。",
                        "success_signal": "查体或检查前先说明目的并征得同意。",
                        "skill_type": "ethics_consent",
                        "status": "persistent",
                        "priority": 10,
                    }
                ],
            },
        },
        case=case,
        pedagogy_state={},
        base_hint="下一步选择关键查体。",
        retrieved_knowledge_context=[],
    )

    assert context["skill_selection"]["training_goals"][0]["gap_type"] == "ethics_consent_missing"
    assert context["skill_selection"]["humanistic_training_goals"][0]["success_signal"] == "查体或检查前先说明目的并征得同意。"


def test_active_hint_does_not_turn_into_exam_style_question() -> None:
    request = _request().model_copy(update={"base_hint": "先追问疼痛部位变化、疼痛性质和伴随症状，再决定查体重点。"})
    response = module.CoachResponse(
        hint="患者提到起初是上腹部痛。为了避免过早下结论，请说明你的问诊目的。",
        trigger_kind="manual_hint",
    )

    normalized = module._normalize_coach_response_for_request(request, response)

    assert normalized.hint == "先追问疼痛部位变化、疼痛性质和伴随症状，再决定查体重点。"
    assert "问诊目的" not in normalized.hint
    assert "请说明" not in normalized.hint


def test_llm_coach_agent_normalizes_exam_style_active_hint() -> None:
    request = _request().model_copy(update={"base_hint": "先追问疼痛部位变化、疼痛性质和伴随症状，再决定查体重点。"})
    agent = module.OpenAICompatibleCoachAgent(object(), client=FakeExamStyleCoachClient())

    response = agent(request)

    assert response.hint == "先追问疼痛部位变化、疼痛性质和伴随症状，再决定查体重点。"


def test_llm_coach_agent_preserves_active_hint_policy_training_goal() -> None:
    request = _request().model_copy(
        update={
            "base_hint": (
                "本轮可以主动询问患者最担心什么、希望解决什么，或这次不适对学习生活的影响；"
                "如果患者表达担忧，再先回应情绪再继续问诊。"
            ),
            "hint_context": {
                "hint_policy": {
                    "intent": "opportunity_preparation",
                    "selected_goal_type": "relationship_empathy_missing",
                    "training_goal_hint": (
                        "本轮可以主动询问患者最担心什么、希望解决什么，或这次不适对学习生活的影响；"
                        "如果患者表达担忧，再先回应情绪再继续问诊。"
                    ),
                    "trigger_state": "preparation",
                }
            },
        }
    )
    agent = module.OpenAICompatibleCoachAgent(object(), client=FakePolicyDroppingCoachClient())

    response = agent(request)

    assert "最担心" in response.hint
    assert "回应情绪" in response.hint


def test_coach_provider_payload_excludes_case_secrets_and_local_denylist() -> None:
    recording_client = RecordingCoachClient()
    request = _request().model_copy(
        update={
            "case_id": "appendicitis_001",
            "case_title": "急性阑尾炎训练病例",
            "forbidden_terms": ["急性阑尾炎", "appendicitis"],
            "pedagogy_state": {
                "pending_fact_ids": ["appendicitis_001.hf_05"],
                "coverage_map": {"history": [{"label": "低热约 37.8 ℃"}]},
            },
            "hint_context": {
                "next_step": {"base_hint": "先补充病史。"},
                "missing_rubric_items": ["rubric:appendicitis_001.ht_fever"],
            },
        }
    )
    agent = module.OpenAICompatibleCoachAgent(object(), client=recording_client)

    response = agent(request)

    provider_payload = recording_client.calls[0]["payload"]
    payload_text = str(provider_payload)
    assert response.hint
    assert "case_id" not in provider_payload
    assert "forbidden_terms" not in provider_payload
    assert "appendicitis_001" not in payload_text
    assert "急性阑尾炎" not in payload_text
    assert "低热约 37.8 ℃" not in payload_text
    assert "pending_fact_ids" not in payload_text
    assert "coverage_map" not in payload_text
    assert "missing_rubric_items" not in payload_text


def test_coach_hint_redacts_forbidden_terms_case_insensitively() -> None:
    hint = module.sanitize_coach_hint(
        "Do not reveal APPENDICITIS to the student.",
        ["appendicitis"],
    )

    assert "APPENDICITIS" not in hint
    assert "标准诊断" in hint


def test_active_hint_policy_keeps_visible_hint_concise_when_skill_context_is_long() -> None:
    training_goal_hint = "本轮患者表达担忧后，先回应情绪再继续医学问诊。"
    request = _request().model_copy(
        update={
            "base_hint": (
                f"{training_goal_hint} 本轮训练重点是系统性问诊与沟通技巧整合不足。"
                "建议在问诊练习中，有意识地将问诊过程划分为信息收集、患者中心沟通和伦理规范三个阶段。"
            ),
            "hint_context": {
                "hint_policy": {
                    "intent": "relationship_repair",
                    "selected_goal_type": "relationship_empathy_missing",
                    "training_goal_hint": training_goal_hint,
                    "trigger_state": "triggered",
                }
            },
        }
    )
    response = module.CoachResponse(
        hint=request.base_hint,
        trigger_kind="socratic_hint",
    )

    normalized = module._normalize_coach_response_for_request(request, response)

    assert normalized.hint == training_goal_hint
    assert "本轮训练重点" not in normalized.hint


def test_active_hint_keeps_actionable_guidance() -> None:
    request = _request()
    response = module.CoachResponse(
        hint="下一步先追问疼痛是否转移、性质和伴随恶心发热，因为这些能帮助完善问题表征。",
        trigger_kind="manual_hint",
    )

    normalized = module._normalize_coach_response_for_request(request, response)

    assert normalized.hint == "下一步先追问疼痛是否转移、性质和伴随恶心发热，因为这些能帮助完善问题表征。"


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
            "proxy_url": "direct",
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
    client_kwargs = FakeGeminiClient.created[0]
    assert {key: value for key, value in client_kwargs.items() if key != "http_options"} == {
        "vertexai": True,
        "project": "demo-project",
        "location": "global",
    }
    assert client_kwargs["http_options"].client_args == {
        "follow_redirects": False,
        "trust_env": False,
    }
    assert client_kwargs["http_options"].async_client_args["trust_env"] is False
    assert FakeGeminiModels.calls[0]["model"] == "gemini-3.1-pro-preview"
    assert os.environ.get("HTTP_PROXY") is None
    assert os.environ.get("HTTPS_PROXY") is None
