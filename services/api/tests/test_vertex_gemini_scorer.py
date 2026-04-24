import os

from app.models.rubric import LlmRubricRequest, LlmRubricResponse
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
        settings=VertexGeminiSettings(project="demo-project"),
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
    assert call["model"] == "gemini-3.1-flash-lite-preview"
    assert "reasoning_core" in str(call["contents"])
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema is LlmRubricResponse
    assert "不得引入输入之外的医学事实" in call["config"].system_instruction


def test_vertex_gemini_settings_defaults_to_global_gemini_31_flash_lite() -> None:
    settings = VertexGeminiSettings(project="demo-project")

    assert settings.project == "demo-project"
    assert settings.location == "global"
    assert settings.model == "gemini-3.1-flash-lite-preview"
    assert settings.proxy_url == "http://127.0.0.1:7897"


def test_create_default_vertex_gemini_scorer_returns_none_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("OSCE_VERTEX_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    assert create_default_vertex_gemini_scorer() is None


def test_create_default_vertex_gemini_scorer_requires_project_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("OSCE_VERTEX_ENABLED", "true")
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    assert create_default_vertex_gemini_scorer() is None


def test_create_default_vertex_gemini_scorer_sets_7897_proxy(monkeypatch) -> None:
    monkeypatch.setenv("OSCE_VERTEX_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_PROJECT", "demo-project")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    scorer = create_default_vertex_gemini_scorer()

    assert scorer is not None
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"
