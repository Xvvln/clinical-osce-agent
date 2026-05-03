import os

import pytest

from app.services.training_skill_candidate_service import (
    TemplateTrainingSkillCandidateGenerator,
    TrainingSkillCandidateContext,
    TrainingSkillCandidateGenerationError,
    TrainingSkillCandidateService,
    VertexGeminiSkillCandidateSettings,
    VertexGeminiTrainingSkillCandidateGenerator,
    create_default_training_skill_candidate_generator,
)


class FakeSkillCandidateModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        self.calls.append({"model": model, "contents": contents, "config": config})

        class Response:
            text = '{"title":"LLM 生成的推理训练 Skill","description":"基于 2 次高频漏项生成的教学 Skill。","suggested_strategy":"提交诊断前，请先按证据链复核主要诊断和鉴别诊断。"}'

        return Response()


class FakeSkillCandidateClient:
    def __init__(self) -> None:
        self.models = FakeSkillCandidateModels()


class FakeFailingSkillCandidateModels:
    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        raise RuntimeError("vertex service unavailable")


class FakeInvalidJsonSkillCandidateModels:
    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        class Response:
            text = "not-json"

        return Response()


class FakeFailingSkillCandidateClient:
    def __init__(self) -> None:
        self.models = FakeFailingSkillCandidateModels()


class FakeInvalidJsonSkillCandidateClient:
    def __init__(self) -> None:
        self.models = FakeInvalidJsonSkillCandidateModels()


def _reasoning_candidate_context() -> TrainingSkillCandidateContext:
    return TrainingSkillCandidateContext(
        item_id="reasoning_core",
        support_count=2,
        case_ids=["appendicitis_001", "pneumonia_001"],
        source_report_count=3,
        related_recommendations=[
            "rubric:appendicitis_001_rubric.item.reasoning_core",
            "knowledge:appendicitis_001.rp_03",
        ],
    )


def test_vertex_gemini_training_skill_candidate_generator_uses_context_and_response_schema() -> None:
    fake_client = FakeSkillCandidateClient()
    generator = VertexGeminiTrainingSkillCandidateGenerator(
        settings=VertexGeminiSkillCandidateSettings(
            project="demo-project",
            skill_candidate_enabled=True,
        ),
        client=fake_client,
    )

    candidate = generator.generate_candidate(_reasoning_candidate_context())

    assert candidate == {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "LLM 生成的推理训练 Skill",
        "description": "基于 2 次高频漏项生成的教学 Skill。",
        "suggested_strategy": "提交诊断前，请先按证据链复核主要诊断和鉴别诊断。",
        "status": "draft",
        "source_report_count": 3,
        "support_count": 2,
        "related_recommendations": [
            "rubric:appendicitis_001_rubric.item.reasoning_core",
            "knowledge:appendicitis_001.rp_03",
        ],
    }
    call = fake_client.models.calls[0]
    assert call["model"] == "gemini-3.1-flash-lite-preview"
    assert '"item_id": "reasoning_core"' in str(call["contents"])
    assert "appendicitis_001" in str(call["contents"])
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema.__name__ == "GeneratedTrainingSkillCandidateContent"
    assert "不得生成真实诊疗建议" in call["config"].system_instruction


def test_vertex_gemini_training_skill_candidate_generator_raises_generation_error_when_model_call_fails() -> None:
    generator = VertexGeminiTrainingSkillCandidateGenerator(
        settings=VertexGeminiSkillCandidateSettings(
            project="demo-project",
            skill_candidate_enabled=True,
        ),
        client=FakeFailingSkillCandidateClient(),
    )

    with pytest.raises(TrainingSkillCandidateGenerationError) as exc_info:
        generator.generate_candidate(_reasoning_candidate_context())

    assert "Skill candidate generation failed" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_vertex_gemini_training_skill_candidate_generator_raises_generation_error_when_response_is_invalid_json() -> None:
    generator = VertexGeminiTrainingSkillCandidateGenerator(
        settings=VertexGeminiSkillCandidateSettings(
            project="demo-project",
            skill_candidate_enabled=True,
        ),
        client=FakeInvalidJsonSkillCandidateClient(),
    )

    with pytest.raises(TrainingSkillCandidateGenerationError) as exc_info:
        generator.generate_candidate(_reasoning_candidate_context())

    assert "Skill candidate generation failed" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None


def test_create_default_training_skill_candidate_generator_uses_template_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("OSCE_VERTEX_SKILL_CANDIDATE_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    generator = create_default_training_skill_candidate_generator()

    assert isinstance(generator, TemplateTrainingSkillCandidateGenerator)


def test_create_default_training_skill_candidate_generator_sets_proxy_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("OSCE_VERTEX_SKILL_CANDIDATE_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_PROJECT", "demo-project")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    generator = create_default_training_skill_candidate_generator(client=FakeSkillCandidateClient())

    assert isinstance(generator, VertexGeminiTrainingSkillCandidateGenerator)
    assert "HTTP_PROXY" in os.environ
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"


def test_training_skill_candidate_service_uses_injected_generator_for_high_frequency_items() -> None:
    captured_contexts: list[TrainingSkillCandidateContext] = []

    class FakeTrainingSkillCandidateGenerator:
        def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, object]:
            captured_contexts.append(context)
            return {
                "candidate_id": f"llm_candidate_{context.item_id}",
                "trigger_item_id": context.item_id,
                "title": "LLM 生成的推理训练 Skill",
                "description": f"LLM 基于 {context.support_count} 次漏项生成。",
                "suggested_strategy": "提交诊断前，请先按证据链复核主要诊断和鉴别诊断。",
                "status": "draft",
                "source_report_count": context.source_report_count,
                "support_count": context.support_count,
                "related_recommendations": context.related_recommendations,
            }

    insights = {
        "session_count": 3,
        "report_count": 3,
        "frequent_missed_items": [
            {
                "item_id": "reasoning_core",
                "count": 2,
                "case_ids": ["appendicitis_001", "pneumonia_001"],
            },
            {
                "item_id": "ht_location",
                "count": 1,
                "case_ids": ["appendicitis_001"],
            },
        ],
        "frequent_learning_recommendations": [
            {
                "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                "title": "推理链覆盖关键证据并能自圆其说",
                "count": 2,
            },
            {
                "reference": "knowledge:appendicitis_001.rp_03",
                "title": "急性阑尾炎诊断依据",
                "count": 1,
            },
        ],
    }

    candidates = TrainingSkillCandidateService(
        generator=FakeTrainingSkillCandidateGenerator(),
    ).propose_candidates(insights, min_count=2)

    assert captured_contexts == [
        TrainingSkillCandidateContext(
            item_id="reasoning_core",
            support_count=2,
            case_ids=["appendicitis_001", "pneumonia_001"],
            source_report_count=3,
            related_recommendations=[
                "rubric:appendicitis_001_rubric.item.reasoning_core",
                "knowledge:appendicitis_001.rp_03",
            ],
        )
    ]
    assert candidates == [
        {
            "candidate_id": "llm_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "LLM 生成的推理训练 Skill",
            "description": "LLM 基于 2 次漏项生成。",
            "suggested_strategy": "提交诊断前，请先按证据链复核主要诊断和鉴别诊断。",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
            "related_recommendations": [
                "rubric:appendicitis_001_rubric.item.reasoning_core",
                "knowledge:appendicitis_001.rp_03",
            ],
        }
    ]


def test_training_skill_candidate_service_proposes_reasoning_candidate_from_frequent_missed_item(monkeypatch) -> None:
    monkeypatch.delenv("OSCE_VERTEX_SKILL_CANDIDATE_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    insights = {
        "session_count": 3,
        "report_count": 3,
        "frequent_missed_items": [
            {
                "item_id": "reasoning_core",
                "count": 2,
                "case_ids": ["appendicitis_001", "pneumonia_001"],
            },
            {
                "item_id": "ht_location",
                "count": 1,
                "case_ids": ["appendicitis_001"],
            },
        ],
        "frequent_learning_recommendations": [
            {
                "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                "title": "推理链覆盖关键证据并能自圆其说",
                "count": 2,
            },
            {
                "reference": "knowledge:appendicitis_001.rp_03",
                "title": "急性阑尾炎诊断依据",
                "count": 1,
            },
        ],
    }

    candidates = TrainingSkillCandidateService().propose_candidates(insights, min_count=2)

    assert candidates == [
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "3 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001、pneumonia_001。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
            "related_recommendations": [
                "rubric:appendicitis_001_rubric.item.reasoning_core",
                "knowledge:appendicitis_001.rp_03",
            ],
        }
    ]


def test_training_skill_candidate_service_skips_low_frequency_missed_items(monkeypatch) -> None:
    monkeypatch.delenv("OSCE_VERTEX_SKILL_CANDIDATE_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    insights = {
        "session_count": 1,
        "report_count": 1,
        "frequent_missed_items": [
            {
                "item_id": "ht_location",
                "count": 1,
                "case_ids": ["appendicitis_001"],
            }
        ],
        "frequent_learning_recommendations": [],
    }

    candidates = TrainingSkillCandidateService().propose_candidates(insights, min_count=2)

    assert candidates == []
