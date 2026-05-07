import os

from app.models.rubric import LlmRubricRequest, LlmRubricResponse
from app.services import openai_compatible_chat_client as openai_module
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.vertex_gemini_scorer import (
    VertexGeminiRubricScorer,
    VertexGeminiSettings,
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


def test_create_default_vertex_gemini_scorer_sets_7897_proxy(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OSCE_VERTEX_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_PROJECT", "demo-project")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7897")
    monkeypatch.setattr("app.services.vertex_gemini_scorer.genai.Client", lambda **kwargs: FakeClient())

    scorer = create_default_vertex_gemini_scorer()

    assert scorer is not None
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["ALL_PROXY"] == "http://127.0.0.1:7897"


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


def test_create_default_vertex_gemini_scorer_uses_runtime_openai_compatible_config(monkeypatch) -> None:
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
            "proxy_url": "http://127.0.0.1:7897",
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
    assert created_clients == [{"vertexai": True, "project": "demo-project", "location": "global"}]
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"


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
    assert created_clients == [{"vertexai": True, "api_key": "student-vertex-secret"}]
