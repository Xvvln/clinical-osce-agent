import os

import pytest

from app.services import anthropic_chat_client as anthropic_module
from app.services import openai_compatible_chat_client as openai_module
from app.services.training_skill_candidate_service import (
    OpenAICompatibleTrainingSkillCandidateGenerator,
    TemplateTrainingSkillCandidateGenerator,
    TrainingSkillCandidateContext,
    TrainingSkillCandidateGenerationError,
    TrainingSkillCandidateMissedItem,
    TrainingSkillCandidateService,
    VertexGeminiSkillCandidateSettings,
    VertexGeminiTrainingSkillCandidateGenerator,
    create_default_training_skill_candidate_generator,
)
from app.services.runtime_model_config_store import runtime_model_config_store


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


def _expected_action_plan(stage_scope: list[str], trigger_item_ids: list[str], suggested_strategy: str) -> list[dict[str, object]]:
    return [
        {
            "action_type": "hint_ladder",
            "level": 1,
            "stage_scope": stage_scope,
            "trigger_item_ids": trigger_item_ids,
            "message_template": suggested_strategy,
        },
        {
            "action_type": "reflection_prompt",
            "level": 1,
            "stage_scope": ["diagnosis_submission"],
            "trigger_item_ids": trigger_item_ids,
            "message_template": "训练结束后，请对照本轮反复漏掉的评分项复盘证据链，不补写标准答案或隐藏事实。",
        },
    ]


def _expected_policy() -> dict[str, object]:
    return {
        "forbid_main_diagnosis": True,
        "forbid_hidden_facts": True,
        "forbid_test_results": True,
        "forbid_treatment_plan": True,
        "forbid_dose": True,
        "allowed_scope": "teaching_strategy_only",
    }


def _expected_success_metrics() -> list[str]:
    return [
        "target_rubric_item_recovery_rate",
        "stage_completion_rate",
        "hint_after_skill_usage",
    ]


def test_vertex_gemini_training_skill_candidate_generator_uses_training_pattern_context_and_response_schema() -> None:
    fake_client = FakeSkillCandidateClient()
    generator = VertexGeminiTrainingSkillCandidateGenerator(
        settings=VertexGeminiSkillCandidateSettings(
            project="demo-project",
            skill_candidate_enabled=True,
            _env_file=None,
        ),
        client=fake_client,
    )

    candidate = generator.generate_candidate(_training_pattern_candidate_context())

    assert candidate == {
        "candidate_id": "skill_candidate_training_pattern_reasoning_core_rs_exclude",
        "trigger_item_id": "training_pattern_reasoning_core_rs_exclude",
        "trigger_item_ids": ["reasoning_core", "rs_exclude"],
        "case_ids": ["appendicitis_001", "pneumonia_001"],
        "skill_type": "reasoning_bridge",
        "stage_scope": ["case_intro", "diagnosis_submission"],
        "effect_status": "insufficient_samples",
        "applies_when": {
            "case_ids": ["appendicitis_001", "pneumonia_001"],
            "stage_scope": ["case_intro", "diagnosis_submission"],
            "trigger_item_ids": ["reasoning_core", "rs_exclude"],
            "current_missing_evidence": ["reasoning_core", "rs_exclude"],
            "min_support_count": 2,
        },
        "title": "LLM 生成的训练模式 Skill",
        "description": "基于多项高频漏项生成的训练级教学 Skill。",
        "suggested_strategy": "提交诊断前，请先按证据链复核主要诊断、鉴别诊断和排除依据。",
        "teaching_action_plan": _expected_action_plan(
            ["case_intro", "diagnosis_submission"],
            ["reasoning_core", "rs_exclude"],
            "提交诊断前，请先按证据链复核主要诊断、鉴别诊断和排除依据。",
        ),
        "prohibited_content_policy": _expected_policy(),
        "success_metrics": _expected_success_metrics(),
        "status": "draft",
        "source_report_count": 3,
        "support_count": 2,
        "related_recommendations": [
            "rubric:appendicitis_001_rubric.item.reasoning_core",
            "knowledge:appendicitis_001.rp_03",
        ],
    }
    call = fake_client.models.calls[0]
    assert call["model"] == "gemini-3.1-pro-preview"
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


class FakeOpenAICompatibleSkillCandidateResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"title":"兼容模型生成的训练模式 Skill","description":"围绕多项高频漏项生成的训练级纠偏说明。","suggested_strategy":"提交诊断前，先按本轮反复漏掉的证据链逐项复盘。"}',
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

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeOpenAICompatibleSkillCandidateResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeOpenAICompatibleSkillCandidateResponse()


class FakeAnthropicSkillCandidateResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": '{"title":"Anthropic 生成的训练模式 Skill","description":"基于多项高频漏项生成的训练级教学 Skill。","suggested_strategy":"提交诊断前，请先按证据链复核主要诊断、鉴别诊断和排除依据。"}',
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

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeAnthropicSkillCandidateResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        return FakeAnthropicSkillCandidateResponse()


def test_create_default_training_skill_candidate_generator_uses_runtime_openai_compatible_config(monkeypatch) -> None:
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
    monkeypatch.delenv("OSCE_VERTEX_SKILL_CANDIDATE_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    try:
        generator = create_default_training_skill_candidate_generator()
        assert isinstance(generator, OpenAICompatibleTrainingSkillCandidateGenerator)
        candidate = generator.generate_candidate(_training_pattern_candidate_context())
    finally:
        runtime_model_config_store.clear()

    assert candidate["candidate_id"] == "skill_candidate_training_pattern_reasoning_core_rs_exclude"
    assert candidate["trigger_item_ids"] == ["reasoning_core", "rs_exclude"]
    assert candidate["title"] == "兼容模型生成的训练模式 Skill"
    assert candidate["source_report_count"] == 3
    assert candidate["support_count"] == 2
    assert FakeOpenAICompatibleHttpClient.calls[0]["url"] == "https://api.proxy.example/v1/chat/completions"
    assert FakeOpenAICompatibleHttpClient.calls[0]["json"]["model"] == "gemini-via-clprox"


def test_create_default_training_skill_candidate_generator_uses_runtime_anthropic_config(monkeypatch) -> None:
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
    monkeypatch.delenv("OSCE_VERTEX_SKILL_CANDIDATE_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    try:
        generator = create_default_training_skill_candidate_generator()
        candidate = generator.generate_candidate(_training_pattern_candidate_context())
    finally:
        runtime_model_config_store.clear()

    assert candidate["candidate_id"] == "skill_candidate_training_pattern_reasoning_core_rs_exclude"
    assert candidate["trigger_item_ids"] == ["reasoning_core", "rs_exclude"]
    assert candidate["title"] == "Anthropic 生成的训练模式 Skill"
    assert candidate["source_report_count"] == 3
    assert candidate["support_count"] == 2
    assert FakeAnthropicHttpClient.calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert FakeAnthropicHttpClient.calls[0]["json"]["model"] == "claude-3-5-sonnet-latest"


def test_create_default_training_skill_candidate_generator_uses_runtime_vertex_gemini_adc_config(monkeypatch) -> None:
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
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    try:
        generator = create_default_training_skill_candidate_generator(client=FakeSkillCandidateClient())
    finally:
        runtime_model_config_store.clear()

    assert isinstance(generator, VertexGeminiTrainingSkillCandidateGenerator)
    assert generator._settings.project == "demo-project"
    assert generator._settings.location == "global"
    assert generator._settings.skill_candidate_model == "gemini-3.1-pro-preview"
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"


def test_create_default_training_skill_candidate_generator_uses_runtime_vertex_gemini_api_key_config(monkeypatch) -> None:
    created_clients: list[dict[str, object]] = []

    def fake_client(**kwargs: object) -> FakeSkillCandidateClient:
        created_clients.append(kwargs)
        return FakeSkillCandidateClient()

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
    monkeypatch.setattr("app.services.training_skill_candidate_service.genai.Client", fake_client)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    try:
        generator = create_default_training_skill_candidate_generator()
    finally:
        runtime_model_config_store.clear()

    assert isinstance(generator, VertexGeminiTrainingSkillCandidateGenerator)
    assert generator._settings.api_key == "student-vertex-secret"
    assert generator._settings.project == ""
    assert generator._settings.location == "global"
    assert generator._settings.skill_candidate_model == "gemini-2.5-flash"
    assert created_clients == [{"vertexai": True, "api_key": "student-vertex-secret"}]
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
                "case_ids": context.case_ids,
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
            "case_ids": ["appendicitis_001", "pneumonia_001"],
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
            "case_ids": ["appendicitis_001", "pneumonia_001"],
            "skill_type": "reasoning_bridge",
            "stage_scope": ["case_intro", "diagnosis_submission"],
            "effect_status": "insufficient_samples",
            "applies_when": {
                "case_ids": ["appendicitis_001", "pneumonia_001"],
                "stage_scope": ["case_intro", "diagnosis_submission"],
                "trigger_item_ids": ["rs_exclude", "reasoning_core"],
                "current_missing_evidence": ["rs_exclude", "reasoning_core"],
                "min_support_count": 3,
            },
            "title": "OSCE 训练模式纠偏提示",
            "description": "3 份报告中反复出现 2 类训练漏项：rs_exclude（3 次，涉及 appendicitis_001）、reasoning_core（2 次，涉及 appendicitis_001、pneumonia_001）。",
            "suggested_strategy": "在不透露标准答案的前提下，提醒学生按本轮训练中反复出现的漏项模式复盘问诊、查体、检查、诊断和推理链，而不是只修补单个评分点。",
            "teaching_action_plan": _expected_action_plan(
                ["case_intro", "diagnosis_submission"],
                ["rs_exclude", "reasoning_core"],
                "在不透露标准答案的前提下，提醒学生按本轮训练中反复出现的漏项模式复盘问诊、查体、检查、诊断和推理链，而不是只修补单个评分点。",
            ),
            "prohibited_content_policy": _expected_policy(),
            "success_metrics": _expected_success_metrics(),
            "status": "draft",
            "source_report_count": 3,
            "support_count": 3,
            "related_recommendations": [
                "rubric:appendicitis_001_rubric.item.reasoning_core",
                "knowledge:appendicitis_001.rp_03",
            ],
        }
    ]


def test_skill_candidate_clusters_multiple_items_into_one_pattern_with_policy_metadata(monkeypatch) -> None:
    monkeypatch.delenv("OSCE_VERTEX_SKILL_CANDIDATE_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    candidates = TrainingSkillCandidateService().propose_candidates(
        {
            "session_count": 3,
            "report_count": 3,
            "frequent_missed_items": [
                {"item_id": "reasoning_core", "count": 2, "case_ids": ["appendicitis_001"]},
                {"item_id": "dxd_crohn", "count": 2, "case_ids": ["appendicitis_001"]},
                {"item_id": "ht_location", "count": 1, "case_ids": ["appendicitis_001"]},
            ],
            "frequent_learning_recommendations": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                    "title": "推理链覆盖关键证据并能自圆其说",
                    "count": 2,
                }
            ],
        },
        min_count=2,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["trigger_item_id"] == "training_pattern_dxd_crohn_reasoning_core"
    assert candidate["trigger_item_ids"] == ["dxd_crohn", "reasoning_core"]
    assert candidate["skill_type"] == "differential_broadening"
    assert candidate["stage_scope"] == ["case_intro", "diagnosis_submission"]
    assert candidate["effect_status"] == "insufficient_samples"
    assert candidate["applies_when"] == {
        "case_ids": ["appendicitis_001"],
        "stage_scope": ["case_intro", "diagnosis_submission"],
        "trigger_item_ids": ["dxd_crohn", "reasoning_core"],
        "current_missing_evidence": ["dxd_crohn", "reasoning_core"],
        "min_support_count": 2,
    }
    assert candidate["teaching_action_plan"] == _expected_action_plan(
        ["case_intro", "diagnosis_submission"],
        ["dxd_crohn", "reasoning_core"],
        candidate["suggested_strategy"],
    )
    assert candidate["prohibited_content_policy"] == _expected_policy()
    assert candidate["success_metrics"] == _expected_success_metrics()


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
