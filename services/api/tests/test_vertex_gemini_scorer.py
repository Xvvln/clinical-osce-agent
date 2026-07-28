import json
import os

from app.models.rubric import LlmRubricRequest, LlmRubricResponse
from app.services import anthropic_chat_client as anthropic_module
from app.services import openai_compatible_chat_client as openai_module
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.vertex_gemini_scorer import (
    AnthropicRubricScorer,
    OpenAICompatibleRubricScorer,
    RUBRIC_PROVIDER_PAYLOAD_MAX_BYTES,
    VertexGeminiRubricScorer,
    VertexGeminiSettings,
    build_rubric_provider_projection,
    create_default_vertex_gemini_scorer,
)


class FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        self.calls.append({"model": model, "contents": contents, "config": config})

        class Response:
            text = '{"score":10,"covered_evidence":["hf_01"],"missing_evidence":["lab.cbc"],"rationale":"覆盖核心病史，缺少检查证据。"}'

        return Response()


class FakeClient:
    def __init__(self) -> None:
        self.models = FakeModels()


class CapturingStructuredClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def complete_json(self, **kwargs: object) -> LlmRubricResponse:
        self.payloads.append(kwargs["payload"])
        return LlmRubricResponse(
            score=0,
            covered_evidence=[],
            missing_evidence=[],
            rationale="未确认投影证据覆盖。",
        )


def _oversized_rubric_request(count: int) -> LlmRubricRequest:
    relevant_facts = [
        f"病例事实_{index:04d}_" + "超长中文病例事实🩺🧬" * 36
        for index in range(count)
    ]
    required_evidence = [
        f"评分证据_{index:04d}_" + "超长中文评分证据🔬🧠" * 36
        for index in range(count)
    ]
    return LlmRubricRequest(
        rubric_item_id="reasoning_quality",
        description="推理链覆盖关键证据并能自圆其说",
        max_score=15,
        student_final_reasoning="转移性右下腹痛和反跳痛支持急性阑尾炎。",
        relevant_facts_revealed=relevant_facts,
        required_evidence=required_evidence,
    )


def test_vertex_gemini_scorer_uses_adc_vertex_settings_and_response_schema() -> None:
    fake_client = FakeClient()
    scorer = VertexGeminiRubricScorer(
        settings=VertexGeminiSettings(project="demo-project", _env_file=None),
        client=fake_client,
    )

    response = scorer(
        LlmRubricRequest(
            rubric_item_id="reasoning_core",
            description="推理链覆盖关键证据并能自圆其说",
            max_score=15,
            student_final_reasoning="转移性右下腹痛支持急性阑尾炎。",
            relevant_facts_revealed=["hf_01"],
            required_evidence=["hf_01", "lab.cbc"],
        )
    )

    assert response == LlmRubricResponse(
        score=10,
        covered_evidence=["hf_01"],
        missing_evidence=["lab.cbc"],
        rationale="覆盖核心病史，缺少检查证据。",
    )
    call = fake_client.models.calls[0]
    assert call["model"] == "gemini-3.1-pro-preview"
    assert "reasoning_core" in str(call["contents"])
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema is LlmRubricResponse
    assert "不得引入输入之外的医学事实" in call["config"].system_instruction


def test_small_rubric_provider_payload_keeps_the_existing_shape() -> None:
    request = LlmRubricRequest(
        rubric_item_id="reasoning_core",
        description="推理链覆盖关键证据并能自圆其说",
        max_score=15,
        student_final_reasoning="转移性右下腹痛支持急性阑尾炎。",
        relevant_facts_revealed=["hf_01"],
        required_evidence=["hf_01", "lab.cbc"],
    )

    projection = build_rubric_provider_projection(request)

    assert projection.compacted is False
    assert projection.payload == request.model_dump()
    assert "provider_projection" not in projection.payload


def test_oversized_rubric_provider_payload_is_utf8_bounded_and_deterministic() -> None:
    for count in (100, 200):
        request = _oversized_rubric_request(count)
        original_request = request.model_dump()
        reordered_request = request.model_copy(
            update={
                "relevant_facts_revealed": list(reversed(request.relevant_facts_revealed)),
                "required_evidence": list(reversed(request.required_evidence)),
            }
        )

        projection = build_rubric_provider_projection(request)
        repeated_projection = build_rubric_provider_projection(request)
        reordered_projection = build_rubric_provider_projection(reordered_request)
        serialized = json.dumps(projection.payload, ensure_ascii=False).encode("utf-8")

        assert projection.compacted is True
        assert len(serialized) <= RUBRIC_PROVIDER_PAYLOAD_MAX_BYTES
        assert projection.payload == repeated_projection.payload == reordered_projection.payload
        assert len(projection.payload["relevant_facts_revealed"]) < count
        assert len(projection.payload["required_evidence"]) < count
        assert projection.payload["provider_projection"] == {
            "compacted": True,
            "policy": "relevance_first_v1",
            "relevant_facts_revealed_total": count,
            "relevant_facts_revealed_unique_total": count,
            "relevant_facts_revealed_included": len(projection.payload["relevant_facts_revealed"]),
            "required_evidence_total": count,
            "required_evidence_unique_total": count,
            "required_evidence_included": len(projection.payload["required_evidence"]),
        }
        omitted_evidence = next(
            value
            for value in request.required_evidence
            if value not in projection.payload["required_evidence"]
        )
        assert omitted_evidence not in serialized.decode("utf-8")
        # Projection is outbound-only: the complete local scoring request stays intact.
        assert request.model_dump() == original_request


def test_all_rubric_providers_share_the_same_bounded_projection() -> None:
    request = _oversized_rubric_request(200)
    expected_projection = build_rubric_provider_projection(request)

    vertex_client = FakeClient()
    vertex_scorer = VertexGeminiRubricScorer(
        settings=VertexGeminiSettings(project="demo-project", _env_file=None),
        client=vertex_client,
    )
    openai_client = CapturingStructuredClient()
    openai_scorer = OpenAICompatibleRubricScorer(
        settings=openai_module.OpenAICompatibleSettings(_env_file=None),
        client=openai_client,
    )
    anthropic_client = CapturingStructuredClient()
    anthropic_scorer = AnthropicRubricScorer(
        settings=anthropic_module.AnthropicSettings(_env_file=None),
        client=anthropic_client,
    )

    vertex_scorer(request)
    openai_scorer(request)
    anthropic_scorer(request)

    vertex_payload = json.loads(vertex_client.models.calls[0]["contents"])
    assert (
        vertex_payload
        == openai_client.payloads[0]
        == anthropic_client.payloads[0]
        == expected_projection.payload
    )
    assert (
        len(json.dumps(vertex_payload, ensure_ascii=False).encode("utf-8"))
        <= RUBRIC_PROVIDER_PAYLOAD_MAX_BYTES
    )
    assert request.model_dump()["required_evidence"] == request.required_evidence


def test_compacted_provider_response_uses_full_local_evidence_denominator_and_missing_list() -> None:
    request = _oversized_rubric_request(100)
    request = request.model_copy(
        update={
            "required_evidence": [
                f"评分证据_{index:04d}_" + "带引号的超长证据\"🧠" * 180
                for index in range(10)
            ]
        }
    )
    projection = build_rubric_provider_projection(request)
    projected_reference = projection.payload["required_evidence"][0]
    original_reference = projection.required_evidence_aliases[projected_reference]

    class EchoProjectedEvidenceClient:
        def complete_json(self, **kwargs: object) -> LlmRubricResponse:
            return LlmRubricResponse(
                score=15,
                covered_evidence=[kwargs["payload"]["required_evidence"][0]],
                missing_evidence=[],
                rationale="错误地把投影子集当成全集并给出满分。",
            )

    scorer = OpenAICompatibleRubricScorer(
        settings=openai_module.OpenAICompatibleSettings(_env_file=None),
        client=EchoProjectedEvidenceClient(),
    )

    response = scorer(request)

    assert projected_reference != original_reference
    assert response.score == 2
    assert response.covered_evidence == [original_reference]
    assert response.missing_evidence == [
        evidence
        for evidence in request.required_evidence
        if evidence != original_reference
    ]
    assert len(request.required_evidence) == 10


def test_compacted_provider_response_with_no_required_evidence_is_conservatively_zero() -> None:
    request = _oversized_rubric_request(100).model_copy(
        update={"required_evidence": []}
    )

    class IncorrectFullScoreClient:
        def complete_json(self, **kwargs: object) -> LlmRubricResponse:
            return LlmRubricResponse(
                score=15,
                covered_evidence=[],
                missing_evidence=[],
                rationale="错误地给出满分。",
            )

    scorer = AnthropicRubricScorer(
        settings=anthropic_module.AnthropicSettings(_env_file=None),
        client=IncorrectFullScoreClient(),
    )

    response = scorer(request)

    assert build_rubric_provider_projection(request).compacted is True
    assert response.score == 0
    assert response.covered_evidence == []
    assert response.missing_evidence == []


def test_vertex_gemini_settings_defaults_to_global_gemini_31_pro_preview() -> None:
    settings = VertexGeminiSettings(project="demo-project", _env_file=None)

    assert settings.project == "demo-project"
    assert settings.location == "global"
    assert settings.model == "gemini-3.1-pro-preview"
    assert settings.proxy_url == "http://127.0.0.1:7897"


def test_create_default_vertex_gemini_scorer_returns_none_when_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OSCE_VERTEX_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    assert create_default_vertex_gemini_scorer() is None


def test_create_default_vertex_gemini_scorer_requires_project_when_enabled(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OSCE_VERTEX_ENABLED", "true")
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    assert create_default_vertex_gemini_scorer() is None


def test_create_default_vertex_gemini_scorer_uses_isolated_7897_client_proxy(tmp_path, monkeypatch) -> None:
    created_clients: list[dict[str, object]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OSCE_VERTEX_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_PROJECT", "demo-project")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7897")
    monkeypatch.setattr(
        "app.services.vertex_gemini_scorer.genai.Client",
        lambda **kwargs: created_clients.append(kwargs) or FakeClient(),
    )

    scorer = create_default_vertex_gemini_scorer()

    assert scorer is not None
    http_options = created_clients[0]["http_options"]
    assert http_options.client_args == {
        "follow_redirects": False,
        "trust_env": False,
        "proxy": "http://127.0.0.1:7897",
    }
    assert http_options.async_client_args["trust_env"] is False
    assert http_options.async_client_args["proxy"] == "http://127.0.0.1:7897"
    assert os.environ.get("HTTP_PROXY") is None
    assert os.environ.get("HTTPS_PROXY") is None
    assert os.environ["ALL_PROXY"] == "socks5://127.0.0.1:7897"


def test_create_default_vertex_gemini_scorer_falls_back_when_client_dependency_is_missing(monkeypatch) -> None:
    monkeypatch.setenv("OSCE_VERTEX_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_PROJECT", "demo-project")

    def raise_missing_dependency(*args: object, **kwargs: object) -> object:
        raise ImportError("Using SOCKS proxy, but the 'socksio' package is not installed.")

    monkeypatch.setattr("app.services.vertex_gemini_scorer.genai.Client", raise_missing_dependency)

    assert create_default_vertex_gemini_scorer() is None


class FakeOpenAICompatibleRubricResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"score":8,"covered_evidence":["hf_01"],"missing_evidence":["lab.cbc"],"rationale":"覆盖核心病史，缺少血常规证据。"}',
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

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeOpenAICompatibleRubricResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeOpenAICompatibleRubricResponse()


class FakeAnthropicRubricResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": '{"score":8,"covered_evidence":["hf_01"],"missing_evidence":["lab.cbc"],"rationale":"覆盖核心病史，缺少血常规证据。"}',
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

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeAnthropicRubricResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeAnthropicRubricResponse()


def test_create_default_vertex_gemini_scorer_uses_runtime_openai_compatible_config(monkeypatch) -> None:
    FakeOpenAICompatibleHttpClient.calls = []
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "openai_compatible",
            "api_key": "student-openai-secret",
            "model": "gemini-via-clprox",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "direct",
        }
    )
    monkeypatch.setattr(openai_module.httpx, "Client", FakeOpenAICompatibleHttpClient)
    monkeypatch.delenv("OSCE_VERTEX_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    try:
        scorer = create_default_vertex_gemini_scorer()
        assert scorer is not None
        response = scorer(
            LlmRubricRequest(
                rubric_item_id="reasoning_core",
                description="推理链覆盖关键证据并能自圆其说",
                max_score=10,
                student_final_reasoning="转移性右下腹痛支持诊断。",
                relevant_facts_revealed=["hf_01"],
                required_evidence=["hf_01", "lab.cbc"],
            )
        )
    finally:
        runtime_model_config_store.clear()

    assert response == LlmRubricResponse(
        score=8,
        covered_evidence=["hf_01"],
        missing_evidence=["lab.cbc"],
        rationale="覆盖核心病史，缺少血常规证据。",
    )
    assert FakeOpenAICompatibleHttpClient.calls[0]["url"] == "https://api.proxy.example/v1/chat/completions"
    assert FakeOpenAICompatibleHttpClient.calls[0]["json"]["model"] == "gemini-via-clprox"


def test_create_default_vertex_gemini_scorer_uses_runtime_anthropic_config(monkeypatch) -> None:
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
    monkeypatch.delenv("OSCE_VERTEX_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    try:
        scorer = create_default_vertex_gemini_scorer()
        assert scorer is not None
        response = scorer(
            LlmRubricRequest(
                rubric_item_id="reasoning_core",
                description="推理链覆盖关键证据并能自圆其说",
                max_score=10,
                student_final_reasoning="转移性右下腹痛支持诊断。",
                relevant_facts_revealed=["hf_01"],
                required_evidence=["hf_01", "lab.cbc"],
            )
        )
    finally:
        runtime_model_config_store.clear()

    assert response == LlmRubricResponse(
        score=8,
        covered_evidence=["hf_01"],
        missing_evidence=["lab.cbc"],
        rationale="覆盖核心病史，缺少血常规证据。",
    )
    assert FakeAnthropicHttpClient.calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert FakeAnthropicHttpClient.calls[0]["json"]["model"] == "claude-3-5-sonnet-latest"


def test_create_default_vertex_gemini_scorer_uses_runtime_vertex_gemini_adc_config(monkeypatch) -> None:
    created_clients: list[dict[str, object]] = []

    def fake_client(**kwargs: object) -> FakeClient:
        created_clients.append(kwargs)
        return FakeClient()

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
    monkeypatch.setattr("app.services.vertex_gemini_scorer.genai.Client", fake_client)
    monkeypatch.delenv("OSCE_VERTEX_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)

    try:
        scorer = create_default_vertex_gemini_scorer()
    finally:
        runtime_model_config_store.clear()

    assert isinstance(scorer, VertexGeminiRubricScorer)
    assert scorer._settings.project == "demo-project"
    assert scorer._settings.location == "global"
    assert scorer._settings.model == "gemini-3.1-pro-preview"
    client_kwargs = created_clients[0]
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
    assert os.environ.get("HTTP_PROXY") is None


def test_create_default_vertex_gemini_scorer_uses_runtime_vertex_gemini_api_key_config(monkeypatch) -> None:
    created_clients: list[dict[str, object]] = []

    def fake_client(**kwargs: object) -> FakeClient:
        created_clients.append(kwargs)
        return FakeClient()

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
    monkeypatch.setattr("app.services.vertex_gemini_scorer.genai.Client", fake_client)
    monkeypatch.delenv("OSCE_VERTEX_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    try:
        scorer = create_default_vertex_gemini_scorer()
    finally:
        runtime_model_config_store.clear()

    assert isinstance(scorer, VertexGeminiRubricScorer)
    assert scorer._settings.api_key == "student-vertex-secret"
    assert scorer._settings.project == ""
    assert scorer._settings.location == "global"
    assert scorer._settings.model == "gemini-2.5-flash"
    client_kwargs = created_clients[0]
    assert {key: value for key, value in client_kwargs.items() if key != "http_options"} == {
        "vertexai": True,
        "api_key": "student-vertex-secret",
    }
    assert client_kwargs["http_options"].client_args == {
        "follow_redirects": False,
        "trust_env": False,
        "proxy": "http://127.0.0.1:7897",
    }
    assert client_kwargs["http_options"].async_client_args["trust_env"] is False
    assert client_kwargs["http_options"].async_client_args["proxy"] == "http://127.0.0.1:7897"
