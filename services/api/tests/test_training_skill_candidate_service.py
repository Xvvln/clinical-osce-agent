import os

import pytest

from app.services.training_skill_candidate_service import (
    TemplateTrainingSkillCandidateGenerator,
    TrainingSkillCandidateContext,
    TrainingSkillCandidateGenerationError,
    TrainingSkillCandidateMissedItem,
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
            text = '{"title":"LLM 生成的训练模式 Skill","description":"基于多项高频漏项生成的训练级教学 Skill。","suggested_strategy":"提交诊断前，请先按证据链复核主要诊断、鉴别诊断和排除依据。"}'

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


def _training_pattern_candidate_context() -> TrainingSkillCandidateContext:
    return TrainingSkillCandidateContext(
        pattern_id="training_pattern_reasoning_core_rs_exclude",
        missed_items=[
            TrainingSkillCandidateMissedItem(
                item_id="reasoning_core",
                count=2,
                case_ids=["appendicitis_001", "pneumonia_001"],
            ),
            TrainingSkillCandidateMissedItem(
                item_id="rs_exclude",
                count=2,
                case_ids=["appendicitis_001"],
            ),
        ],
        support_count=2,
        case_ids=["appendicitis_001", "pneumonia_001"],
        source_report_count=3,
        related_recommendations=[
            "rubric:appendicitis_001_rubric.item.reasoning_core",
            "knowledge:appendicitis_001.rp_03",
        ],
    )


def test_vertex_gemini_training_skill_candidate_generator_uses_training_pattern_context_and_response_schema() -> None:
    fake_client = FakeSkillCandidateClient()
    generator = VertexGeminiTrainingSkillCandidateGenerator(
        settings=VertexGeminiSkillCandidateSettings(
            project="demo-project",
            skill_candidate_enabled=True,
        ),
        client=fake_client,
    )

    candidate = generator.generate_candidate(_training_pattern_candidate_context())

    assert candidate == {
        "candidate_id": "skill_candidate_training_pattern_reasoning_core_rs_exclude",
        "trigger_item_id": "training_pattern_reasoning_core_rs_exclude",
        "trigger_item_ids": ["reasoning_core", "rs_exclude"],
        "title": "LLM 生成的训练模式 Skill",
        "description": "基于多项高频漏项生成的训练级教学 Skill。",
        "suggested_strategy": "提交诊断前，请先按证据链复核主要诊断、鉴别诊断和排除依据。",
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
    assert '"pattern_id": "training_pattern_reasoning_core_rs_exclude"' in str(call["contents"])
    assert '"missed_items"' in str(call["contents"])
    assert "reasoning_core" in str(call["contents"])
    assert "rs_exclude" in str(call["contents"])
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
        generator.generate_candidate(_training_pattern_candidate_context())

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
        generator.generate_candidate(_training_pattern_candidate_context())

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


def test_training_skill_candidate_service_uses_injected_generator_once_for_training_pattern() -> None:
    captured_contexts: list[TrainingSkillCandidateContext] = []

    class FakeTrainingSkillCandidateGenerator:
        def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, object]:
            captured_contexts.append(context)
            return {
                "candidate_id": f"llm_candidate_{context.pattern_id}",
                "trigger_item_id": context.pattern_id,
                "trigger_item_ids": [item.item_id for item in context.missed_items],
                "title": "LLM 生成的训练模式 Skill",
                "description": f"LLM 基于 {len(context.missed_items)} 类高频漏项生成。",
                "suggested_strategy": "提交诊断前，请先按证据链复核主要诊断、鉴别诊断和排除依据。",
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
                "item_id": "rs_exclude",
                "count": 3,
                "case_ids": ["appendicitis_001"],
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
            pattern_id="training_pattern_rs_exclude_reasoning_core",
            missed_items=[
                TrainingSkillCandidateMissedItem(
                    item_id="rs_exclude",
                    count=3,
                    case_ids=["appendicitis_001"],
                ),
                TrainingSkillCandidateMissedItem(
                    item_id="reasoning_core",
                    count=2,
                    case_ids=["appendicitis_001", "pneumonia_001"],
                ),
            ],
            support_count=3,
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
            "candidate_id": "llm_candidate_training_pattern_rs_exclude_reasoning_core",
            "trigger_item_id": "training_pattern_rs_exclude_reasoning_core",
            "trigger_item_ids": ["rs_exclude", "reasoning_core"],
            "title": "LLM 生成的训练模式 Skill",
            "description": "LLM 基于 2 类高频漏项生成。",
            "suggested_strategy": "提交诊断前，请先按证据链复核主要诊断、鉴别诊断和排除依据。",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 3,
            "related_recommendations": [
                "rubric:appendicitis_001_rubric.item.reasoning_core",
                "knowledge:appendicitis_001.rp_03",
            ],
        }
    ]


def test_training_skill_candidate_service_proposes_one_training_pattern_candidate_from_frequent_missed_items(monkeypatch) -> None:
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
                "item_id": "rs_exclude",
                "count": 3,
                "case_ids": ["appendicitis_001"],
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
            "candidate_id": "skill_candidate_training_pattern_rs_exclude_reasoning_core",
            "trigger_item_id": "training_pattern_rs_exclude_reasoning_core",
            "trigger_item_ids": ["rs_exclude", "reasoning_core"],
            "title": "OSCE 训练模式纠偏提示",
            "description": "3 份报告中反复出现 2 类训练漏项：rs_exclude（3 次，涉及 appendicitis_001）、reasoning_core（2 次，涉及 appendicitis_001、pneumonia_001）。",
            "suggested_strategy": "在不透露标准答案的前提下，提醒学生按本轮训练中反复出现的漏项模式复盘问诊、查体、检查、诊断和推理链，而不是只修补单个评分点。",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 3,
            "related_recommendations": [
                "rubric:appendicitis_001_rubric.item.reasoning_core",
                "knowledge:appendicitis_001.rp_03",
            ],
        }
    ]


def test_training_skill_candidate_service_skips_when_no_repeated_training_pattern(monkeypatch) -> None:
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
