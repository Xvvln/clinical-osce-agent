from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.anthropic_chat_client import AnthropicChatClient, AnthropicSettings
from app.services.agent_rag_context_service import retrieve_agent_context
from app.services.api_call_log_service import call_with_api_logging
from app.services.google_genai_http_options import (
    build_google_genai_http_options,
    require_direct_runtime_vertex_adc_proxy,
)
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.rag_knowledge_store import rag_knowledge_store
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.runtime_model_object_cache import RuntimeModelObjectCache
from app.services.admin_display_resolver import trigger_item_labels as resolve_trigger_item_labels
from app.services.training_skill_policy import (
    build_prohibited_content_policy,
    build_skill_memory_fields,
    build_success_metrics,
    build_teaching_action_plan,
)


@dataclass(frozen=True)
class TrainingSkillCandidateMissedItem:
    item_id: str
    count: int
    case_ids: list[str]
    session_ids: list[str] = field(default_factory=list)
    source_report_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TrainingSkillCandidateTurnPattern:
    pattern_id: str
    pattern_type: str
    title: str
    count: int
    trigger_item_ids: list[str]
    case_ids: list[str]
    session_ids: list[str]
    source_report_ids: list[str]
    source_report_count: int


@dataclass(frozen=True)
class TrainingSkillCandidateContext:
    pattern_id: str
    missed_items: list[TrainingSkillCandidateMissedItem]
    support_count: int
    case_ids: list[str]
    source_report_count: int
    related_recommendations: list[str]
    source_session_ids: list[str] = field(default_factory=list)
    source_report_ids: list[str] = field(default_factory=list)
    turn_patterns: list[TrainingSkillCandidateTurnPattern] = field(default_factory=list)
    retrieved_knowledge_context: list[dict[str, Any]] = field(default_factory=list)
    teacher_analysis_context: dict[str, Any] = field(default_factory=dict)


SkillCandidateType = str


class TrainingSkillCandidateGenerator(Protocol):
    def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, Any]:
        ...


class TrainingSkillCandidateGenerationError(RuntimeError):
    pass


class GeneratedTrainingSkillCandidateContent(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=240)
    suggested_strategy: str = Field(min_length=1, max_length=300)


class VertexGeminiSkillCandidateSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OSCE_VERTEX_", env_file=".env", extra="ignore")

    skill_candidate_enabled: bool = False
    api_key: str = ""
    project: str = ""
    location: str = "global"
    skill_candidate_model: str = "gemini-3.1-pro-preview"
    proxy_url: str = "http://127.0.0.1:7897"


SKILL_CANDIDATE_SYSTEM_PROMPT = """你是 OSCE 临床思维训练的教学 Skill 候选生成器。

你只能基于输入的训练报告统计、训练级漏项模式、病例 ID 和学习建议引用，生成用于训练复盘的教学策略候选。

输出要求：
- 只输出 title、description、suggested_strategy 三个字段；
- Skill 必须面向一次训练或一批训练暴露出的整体错误模式，不得只针对单个 rubric 漏项机械改写；
- 不得透露标准诊断、隐藏病例事实或标准答案；
- 不得生成真实诊疗建议、治疗方案、用药剂量、手术方案或处置建议；
- suggested_strategy 必须是面向学生的训练提醒，而不是临床处方；
- 如输入包含 retrieved_knowledge_context，只能把它作为教学策略参考，不得复制隐藏答案或病例事实。
"""

SKILL_GENERATION_RAG_VISIBILITIES = {"pre_submit_safe", "post_submit_review"}


class VertexGeminiTrainingSkillCandidateGenerator:
    def __init__(self, settings: VertexGeminiSkillCandidateSettings, client: Any | None = None) -> None:
        self._settings = settings
        if client is not None:
            self._client = client
        elif settings.api_key:
            self._client = genai.Client(
                vertexai=True,
                api_key=settings.api_key,
                http_options=build_google_genai_http_options(settings.proxy_url),
            )
        else:
            self._client = genai.Client(
                vertexai=True,
                project=settings.project,
                location=settings.location,
                http_options=build_google_genai_http_options(settings.proxy_url),
            )

    def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, Any]:
        try:
            model_payload = _model_generation_payload(context)
            response = call_with_api_logging(
                provider="vertex_gemini_skill_candidate",
                operation="generate_content",
                model=self._settings.skill_candidate_model,
                endpoint="vertex://generate_content",
                call=lambda: self._client.models.generate_content(
                    model=self._settings.skill_candidate_model,
                    contents=json.dumps(
                        model_payload,
                        ensure_ascii=False,
                    ),
                    config=types.GenerateContentConfig(
                        system_instruction=SKILL_CANDIDATE_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=GeneratedTrainingSkillCandidateContent,
                    ),
                ),
            )
            content = GeneratedTrainingSkillCandidateContent.model_validate_json(response.text)
        except Exception as exc:
            raise TrainingSkillCandidateGenerationError("Skill candidate generation failed") from exc

        return _candidate_from_content(context, content)


class OpenAICompatibleTrainingSkillCandidateGenerator:
    def __init__(self, settings: OpenAICompatibleSettings, client: OpenAICompatibleChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or OpenAICompatibleChatClient(settings)

    def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, Any]:
        try:
            content = self._client.complete_json(
                system_prompt=SKILL_CANDIDATE_SYSTEM_PROMPT,
                payload=_model_generation_payload(context),
                response_model=GeneratedTrainingSkillCandidateContent,
                temperature=0.2,
            )
        except Exception as exc:
            raise TrainingSkillCandidateGenerationError("Skill candidate generation failed") from exc

        return _candidate_from_content(context, content)


class AnthropicTrainingSkillCandidateGenerator:
    def __init__(self, settings: AnthropicSettings, client: AnthropicChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or AnthropicChatClient(settings)

    def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, Any]:
        try:
            content = self._client.complete_json(
                system_prompt=SKILL_CANDIDATE_SYSTEM_PROMPT,
                payload=_model_generation_payload(context),
                response_model=GeneratedTrainingSkillCandidateContent,
                temperature=0.2,
            )
        except Exception as exc:
            raise TrainingSkillCandidateGenerationError("Skill candidate generation failed") from exc

        return _candidate_from_content(context, content)


class TemplateTrainingSkillCandidateGenerator:
    def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, Any]:
        return _build_candidate(context)


def create_default_training_skill_candidate_generator(
    client: Any | None = None,
) -> TrainingSkillCandidateGenerator:
    runtime_openai_settings = runtime_model_config_store.get_openai_compatible_settings()
    if runtime_openai_settings is not None:
        return OpenAICompatibleTrainingSkillCandidateGenerator(settings=runtime_openai_settings)

    runtime_anthropic_settings = runtime_model_config_store.get_anthropic_settings()
    if runtime_anthropic_settings is not None:
        return AnthropicTrainingSkillCandidateGenerator(settings=runtime_anthropic_settings)

    runtime_vertex_api_key_config = runtime_model_config_store.get_vertex_gemini_api_key_config()
    if runtime_vertex_api_key_config is not None:
        return VertexGeminiTrainingSkillCandidateGenerator(
            settings=VertexGeminiSkillCandidateSettings(
                skill_candidate_enabled=True,
                api_key=runtime_vertex_api_key_config.api_key,
                project="",
                location=runtime_vertex_api_key_config.location,
                skill_candidate_model=runtime_vertex_api_key_config.model,
                proxy_url=runtime_vertex_api_key_config.proxy_url,
            ),
            client=client,
        )

    runtime_vertex_config = runtime_model_config_store.get_vertex_gemini_adc_config()
    if runtime_vertex_config is not None:
        require_direct_runtime_vertex_adc_proxy(runtime_vertex_config.proxy_url)
        return VertexGeminiTrainingSkillCandidateGenerator(
            settings=VertexGeminiSkillCandidateSettings(
                skill_candidate_enabled=True,
                project=runtime_vertex_config.project,
                location=runtime_vertex_config.location,
                skill_candidate_model=runtime_vertex_config.model,
                proxy_url=runtime_vertex_config.proxy_url,
            ),
            client=client,
        )

    openai_settings = OpenAICompatibleSettings()
    if openai_settings.is_configured:
        return OpenAICompatibleTrainingSkillCandidateGenerator(settings=openai_settings)

    anthropic_settings = AnthropicSettings()
    if anthropic_settings.is_configured:
        return AnthropicTrainingSkillCandidateGenerator(settings=anthropic_settings)

    settings = VertexGeminiSkillCandidateSettings()
    if not settings.skill_candidate_enabled or not (settings.project or settings.api_key):
        return TemplateTrainingSkillCandidateGenerator()
    return VertexGeminiTrainingSkillCandidateGenerator(settings=settings, client=client)


class TrainingSkillCandidateService:
    def __init__(self, generator: TrainingSkillCandidateGenerator | None = None) -> None:
        self._generator = generator
        self._runtime_generator_cache: RuntimeModelObjectCache[TrainingSkillCandidateGenerator] = (
            RuntimeModelObjectCache()
        )
        self._fallback_generator = TemplateTrainingSkillCandidateGenerator()

    def propose_candidates(self, insights: dict[str, Any], min_count: int = 2) -> list[dict[str, Any]]:
        source_report_count = int(insights.get("report_count", 0))
        analysis_session_ids = _normalized_source_ids(
            insights.get("analysis_session_ids")
        )
        analysis_report_ids = _normalized_source_ids(
            insights.get("analysis_report_ids")
        )
        recurring_missed_items = _recurring_missed_items(insights, min_count)
        related_recommendations = [
            recommendation["reference"]
            for recommendation in insights.get("frequent_learning_recommendations", [])
        ]
        related_source_session_ids = sorted(
            {
                session_id
                for recommendation in insights.get(
                    "frequent_learning_recommendations",
                    [],
                )
                for session_id in _normalized_source_ids(
                    recommendation.get("session_ids")
                )
            }
        )
        related_source_report_ids = sorted(
            {
                report_id
                for recommendation in insights.get(
                    "frequent_learning_recommendations",
                    [],
                )
                for report_id in _normalized_source_ids(
                    recommendation.get("source_report_ids")
                )
            }
        )
        candidates: list[dict[str, Any]] = []
        if recurring_missed_items:
            context = TrainingSkillCandidateContext(
                pattern_id=_training_pattern_id(recurring_missed_items),
                missed_items=recurring_missed_items,
                support_count=max(item.count for item in recurring_missed_items),
                case_ids=_pattern_case_ids(recurring_missed_items),
                source_report_count=len(
                    {
                        report_id
                        for item in recurring_missed_items
                        for report_id in item.source_report_ids
                    }
                )
                or source_report_count,
                related_recommendations=related_recommendations,
                source_session_ids=sorted(
                    set(related_source_session_ids)
                    | {
                        session_id
                        for item in recurring_missed_items
                        for session_id in item.session_ids
                    }
                ),
                source_report_ids=sorted(
                    set(related_source_report_ids)
                    | {
                        report_id
                        for item in recurring_missed_items
                        for report_id in item.source_report_ids
                    }
                ),
            )
            context = _with_skill_generation_knowledge_context(context)
            candidates.append(
                _with_analysis_source_provenance(
                    self._generate_candidate(context),
                    analysis_session_ids=analysis_session_ids,
                    analysis_report_ids=analysis_report_ids,
                )
            )

        for turn_pattern in _recurring_turn_patterns(insights, min_count):
            context = TrainingSkillCandidateContext(
                pattern_id=turn_pattern.pattern_id,
                missed_items=[],
                support_count=turn_pattern.count,
                case_ids=list(turn_pattern.case_ids),
                source_report_count=turn_pattern.source_report_count,
                related_recommendations=related_recommendations,
                source_session_ids=related_source_session_ids,
                source_report_ids=related_source_report_ids,
                turn_patterns=[turn_pattern],
            )
            context = _with_skill_generation_knowledge_context(context)
            candidates.append(
                _with_analysis_source_provenance(
                    self._generate_candidate(context),
                    analysis_session_ids=analysis_session_ids,
                    analysis_report_ids=analysis_report_ids,
                )
            )
        return candidates

    def _generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, Any]:
        generator = self._generator or self._runtime_generator_cache.get_or_create(
            create_default_training_skill_candidate_generator
        )
        try:
            candidate = generator.generate_candidate(context)
        except TrainingSkillCandidateGenerationError as exc:
            candidate = self._fallback_generator.generate_candidate(context)
            candidate["generation_mode"] = "template_fallback"
            candidate["generation_warnings"] = [str(exc)]
        _add_turn_pattern_source_fields(candidate, context)
        return candidate


def _recurring_missed_items(insights: dict[str, Any], min_count: int) -> list[TrainingSkillCandidateMissedItem]:
    missed_items = [
        TrainingSkillCandidateMissedItem(
            item_id=missed_item["item_id"],
            count=int(missed_item["count"]),
            case_ids=sorted(str(case_id) for case_id in missed_item["case_ids"]),
            session_ids=_normalized_source_ids(
                missed_item.get("session_ids")
            ),
            source_report_ids=_normalized_source_ids(
                missed_item.get("source_report_ids")
            ),
        )
        for missed_item in insights.get("frequent_missed_items", [])
        if int(missed_item["count"]) >= min_count
    ]
    return sorted(missed_items, key=lambda item: (-item.count, item.item_id))


def _recurring_turn_patterns(insights: dict[str, Any], min_count: int) -> list[TrainingSkillCandidateTurnPattern]:
    turn_patterns = [
        TrainingSkillCandidateTurnPattern(
            pattern_id=str(turn_pattern["pattern_id"]),
            pattern_type=str(turn_pattern["pattern_type"]),
            title=str(turn_pattern["title"]),
            count=int(turn_pattern["count"]),
            trigger_item_ids=sorted(str(trigger) for trigger in turn_pattern.get("trigger_item_ids", [])),
            case_ids=sorted(str(case_id) for case_id in turn_pattern.get("case_ids", [])),
            session_ids=sorted(str(session_id) for session_id in turn_pattern.get("session_ids", [])),
            source_report_ids=sorted(str(report_id) for report_id in turn_pattern.get("source_report_ids", [])),
            source_report_count=int(turn_pattern.get("source_report_count", 0)),
        )
        for turn_pattern in insights.get("frequent_turn_patterns", [])
        if int(turn_pattern["count"]) >= min_count
    ]
    return sorted(turn_patterns, key=lambda pattern: (-pattern.count, pattern.pattern_id))


def _training_pattern_id(missed_items: list[TrainingSkillCandidateMissedItem]) -> str:
    top_item_ids = [item.item_id for item in missed_items[:5]]
    suffix = "_".join(top_item_ids)
    if len(missed_items) > 5:
        suffix = f"{suffix}_plus_{len(missed_items) - 5}"
    return f"training_pattern_{suffix}"


def _pattern_case_ids(missed_items: list[TrainingSkillCandidateMissedItem]) -> list[str]:
    return sorted({case_id for item in missed_items for case_id in item.case_ids})


def _model_generation_payload(context: TrainingSkillCandidateContext) -> dict[str, Any]:
    """Build the provider payload without exporting local audit identifiers.

    Session and report IDs remain on ``context`` so the returned candidate can
    retain complete local provenance. The model only needs aggregate support
    counts and teaching signals; sending every historical source identifier
    would make the request grow linearly without improving generation quality.
    """

    return {
        "pattern_id": context.pattern_id,
        "missed_items": _model_missed_item_payloads(context.missed_items),
        "turn_patterns": _model_turn_pattern_payloads(context.turn_patterns),
        "support_count": context.support_count,
        "case_ids": context.case_ids,
        "source_report_count": context.source_report_count,
        "related_recommendations": context.related_recommendations,
        "retrieved_knowledge_context": _model_knowledge_context(
            context.retrieved_knowledge_context
        ),
        "teacher_analysis_context": _model_teacher_analysis_context(
            context.teacher_analysis_context
        ),
    }


def _model_missed_item_payloads(
    missed_items: list[TrainingSkillCandidateMissedItem],
) -> list[dict[str, Any]]:
    return [
        {
            "item_id": item.item_id,
            "count": item.count,
            "case_ids": item.case_ids,
        }
        for item in missed_items
    ]


def _model_turn_pattern_payloads(
    turn_patterns: list[TrainingSkillCandidateTurnPattern],
) -> list[dict[str, Any]]:
    return [
        {
            "pattern_id": pattern.pattern_id,
            "pattern_type": pattern.pattern_type,
            "title": pattern.title,
            "count": pattern.count,
            "trigger_item_ids": pattern.trigger_item_ids,
            "case_ids": pattern.case_ids,
            "source_report_count": pattern.source_report_count,
        }
        for pattern in turn_patterns
    ]


def _model_knowledge_context(
    knowledge_context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            key: item[key]
            for key in ("title", "snippet", "case_id", "visibility")
            if key in item
        }
        for item in knowledge_context
    ]


def _model_teacher_analysis_context(
    teacher_analysis_context: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        key: teacher_analysis_context[key]
        for key in (
            "agent_id",
            "analysis_mode",
            "analysis_summary",
            "student_thinking_hypothesis",
            "major_issue_titles",
            "source_anchor_labels",
            "teaching_prompt_version",
        )
        if key in teacher_analysis_context
    }
    clinical_thinking_profile = teacher_analysis_context.get(
        "clinical_thinking_profile"
    )
    if isinstance(clinical_thinking_profile, dict):
        payload["clinical_thinking_profile"] = {
            key: clinical_thinking_profile[key]
            for key in (
                "problem_representation",
                "hypothesis_management",
                "verification_strategy",
                "differential_reasoning",
                "metacognitive_next_move",
                "next_teacher_move",
            )
            if key in clinical_thinking_profile
        }
    skill_memory_focus = teacher_analysis_context.get("skill_memory_focus")
    if isinstance(skill_memory_focus, dict):
        payload["skill_memory_focus"] = {
            key: skill_memory_focus[key]
            for key in (
                "problem_pattern_summary",
                "recommended_intervention",
            )
            if key in skill_memory_focus
        }
    return payload


def _local_missed_item_provenance_payloads(
    missed_items: list[TrainingSkillCandidateMissedItem],
) -> list[dict[str, Any]]:
    """Serialize missed-item source associations for local audit only."""

    return [
        {
            "item_id": item.item_id,
            "count": item.count,
            "case_ids": item.case_ids,
            "session_ids": item.session_ids,
            "source_report_ids": item.source_report_ids,
        }
        for item in missed_items
        if item.session_ids or item.source_report_ids
    ]


def _local_turn_pattern_provenance_payloads(
    turn_patterns: list[TrainingSkillCandidateTurnPattern],
) -> list[dict[str, Any]]:
    """Serialize the full source chain for local persistence and audit only."""

    return [
        {
            "pattern_id": pattern.pattern_id,
            "pattern_type": pattern.pattern_type,
            "title": pattern.title,
            "count": pattern.count,
            "trigger_item_ids": pattern.trigger_item_ids,
            "case_ids": pattern.case_ids,
            "session_ids": pattern.session_ids,
            "source_report_ids": pattern.source_report_ids,
            "source_report_count": pattern.source_report_count,
        }
        for pattern in turn_patterns
    ]


def _candidate_from_content(
    context: TrainingSkillCandidateContext,
    content: GeneratedTrainingSkillCandidateContent,
) -> dict[str, Any]:
    skill_type = _skill_type(context)
    stage_scope = _stage_scope(skill_type)
    trigger_item_ids = _context_trigger_item_ids(context)
    trigger_labels = resolve_trigger_item_labels(trigger_item_ids, context.case_ids)
    candidate = {
        "candidate_id": f"skill_candidate_{context.pattern_id}",
        "trigger_item_id": context.pattern_id,
        "trigger_item_ids": trigger_item_ids,
        "case_ids": list(context.case_ids),
        "skill_type": skill_type,
        "stage_scope": stage_scope,
        "effect_status": "insufficient_samples",
        "applies_when": _applies_when(context, stage_scope),
        "title": content.title,
        "description": content.description,
        "suggested_strategy": content.suggested_strategy,
        "teaching_action_plan": build_teaching_action_plan(
            stage_scope=stage_scope,
            trigger_item_ids=trigger_item_ids,
            suggested_strategy=content.suggested_strategy,
        ),
        "prohibited_content_policy": build_prohibited_content_policy(),
        "success_metrics": build_success_metrics(),
        "status": "draft",
        "source_report_count": context.source_report_count,
        "support_count": context.support_count,
        "related_recommendations": list(context.related_recommendations),
    }
    candidate.update(
        build_skill_memory_fields(
            pattern_id=context.pattern_id,
            skill_type=skill_type,
            trigger_item_ids=trigger_item_ids,
            case_ids=list(context.case_ids),
            source_report_count=context.source_report_count,
            support_count=context.support_count,
            title=content.title,
            description=content.description,
            suggested_strategy=content.suggested_strategy,
            stage_scope=stage_scope,
            effect_status="insufficient_samples",
            reasoning_pattern_ids=[pattern.pattern_id for pattern in context.turn_patterns],
            reasoning_pattern_labels=[pattern.title for pattern in context.turn_patterns],
            trigger_item_labels=trigger_labels,
        )
    )
    _add_turn_pattern_source_fields(candidate, context)
    _add_knowledge_context_source_fields(candidate, context)
    _add_teacher_analysis_context(candidate, context)
    return candidate


def _build_candidate(context: TrainingSkillCandidateContext) -> dict[str, Any]:
    skill_type = _skill_type(context)
    stage_scope = _stage_scope(skill_type)
    trigger_item_ids = _context_trigger_item_ids(context)
    trigger_labels = resolve_trigger_item_labels(trigger_item_ids, context.case_ids)
    suggested_strategy = _suggested_strategy(context)
    candidate = {
        "candidate_id": f"skill_candidate_{context.pattern_id}",
        "trigger_item_id": context.pattern_id,
        "trigger_item_ids": trigger_item_ids,
        "case_ids": list(context.case_ids),
        "skill_type": skill_type,
        "stage_scope": stage_scope,
        "effect_status": "insufficient_samples",
        "applies_when": _applies_when(context, stage_scope),
        "title": "OSCE 训练模式纠偏提示",
        "description": _candidate_description(context),
        "suggested_strategy": suggested_strategy,
        "teaching_action_plan": build_teaching_action_plan(
            stage_scope=stage_scope,
            trigger_item_ids=trigger_item_ids,
            suggested_strategy=suggested_strategy,
        ),
        "prohibited_content_policy": build_prohibited_content_policy(),
        "success_metrics": build_success_metrics(),
        "status": "draft",
        "source_report_count": context.source_report_count,
        "support_count": context.support_count,
        "related_recommendations": context.related_recommendations,
    }
    candidate.update(
        build_skill_memory_fields(
            pattern_id=context.pattern_id,
            skill_type=skill_type,
            trigger_item_ids=trigger_item_ids,
            case_ids=list(context.case_ids),
            source_report_count=context.source_report_count,
            support_count=context.support_count,
            title="OSCE 训练模式纠偏提示",
            description=_candidate_description(context),
            suggested_strategy=suggested_strategy,
            stage_scope=stage_scope,
            effect_status="insufficient_samples",
            reasoning_pattern_ids=[pattern.pattern_id for pattern in context.turn_patterns],
            reasoning_pattern_labels=[pattern.title for pattern in context.turn_patterns],
            trigger_item_labels=trigger_labels,
        )
    )
    _add_turn_pattern_source_fields(candidate, context)
    _add_knowledge_context_source_fields(candidate, context)
    _add_teacher_analysis_context(candidate, context)
    return candidate


def _with_skill_generation_knowledge_context(context: TrainingSkillCandidateContext) -> TrainingSkillCandidateContext:
    return TrainingSkillCandidateContext(
        pattern_id=context.pattern_id,
        missed_items=context.missed_items,
        support_count=context.support_count,
        case_ids=context.case_ids,
        source_report_count=context.source_report_count,
        related_recommendations=context.related_recommendations,
        source_session_ids=context.source_session_ids,
        source_report_ids=context.source_report_ids,
        turn_patterns=context.turn_patterns,
        retrieved_knowledge_context=_retrieve_skill_generation_knowledge_context(context),
        teacher_analysis_context=dict(context.teacher_analysis_context),
    )


def _retrieve_skill_generation_knowledge_context(
    context: TrainingSkillCandidateContext,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    query_terms = [
        context.pattern_id,
        *[item.item_id for item in context.missed_items],
        *[case_id for case_id in context.case_ids],
        *context.related_recommendations,
    ]
    for turn_pattern in context.turn_patterns:
        query_terms.extend(
            [
                turn_pattern.pattern_id,
                turn_pattern.pattern_type,
                turn_pattern.title,
                *turn_pattern.trigger_item_ids,
            ]
        )
    return retrieve_agent_context(
        agent_role="skill_generation",
        case_ids=context.case_ids,
        query_terms=query_terms,
        allowed_visibilities=SKILL_GENERATION_RAG_VISIBILITIES,
        limit=limit,
        store=rag_knowledge_store,
    )


def _add_knowledge_context_source_fields(candidate: dict[str, Any], context: TrainingSkillCandidateContext) -> None:
    if not context.retrieved_knowledge_context:
        return
    candidate["knowledge_references"] = [
        item["reference"] for item in context.retrieved_knowledge_context if item.get("reference")
    ]
    candidate["retrieved_knowledge_context"] = list(context.retrieved_knowledge_context)


def _add_teacher_analysis_context(candidate: dict[str, Any], context: TrainingSkillCandidateContext) -> None:
    if context.teacher_analysis_context:
        candidate["teacher_analysis_context"] = dict(context.teacher_analysis_context)


def _candidate_description(context: TrainingSkillCandidateContext) -> str:
    teacher_summary = _teacher_analysis_summary(context)
    thinking_hypothesis = _teacher_student_thinking_hypothesis(context)
    teacher_prefix = ""
    if teacher_summary and thinking_hypothesis:
        teacher_prefix = f"TeacherAgent 分析指出：{teacher_summary}；学生思维假设：{thinking_hypothesis}。"
    elif teacher_summary:
        teacher_prefix = f"TeacherAgent 分析指出：{teacher_summary}。"
    elif thinking_hypothesis:
        teacher_prefix = f"TeacherAgent 学生思维假设：{thinking_hypothesis}。"
    if context.turn_patterns:
        turn_pattern_summaries = "、".join(
            f"{pattern.title}（{pattern.count} 次，涉及 {'、'.join(pattern.session_ids)}）"
            for pattern in context.turn_patterns
        )
        if teacher_prefix:
            return f"{teacher_prefix}{context.source_report_count} 份报告关联的话轮记录中反复出现 {len(context.turn_patterns)} 类训练过程模式：{turn_pattern_summaries}。"
        return f"{context.source_report_count} 份报告关联的话轮记录中反复出现 {len(context.turn_patterns)} 类训练过程模式：{turn_pattern_summaries}。"
    missed_item_summaries = "、".join(
        f"{item.item_id}（{item.count} 次，涉及 {'、'.join(item.case_ids)}）"
        for item in context.missed_items
    )
    if teacher_prefix:
        return f"{teacher_prefix}{context.source_report_count} 份报告中反复出现 {len(context.missed_items)} 类训练漏项：{missed_item_summaries}。"
    return f"{context.source_report_count} 份报告中反复出现 {len(context.missed_items)} 类训练漏项：{missed_item_summaries}。"


def _suggested_strategy(context: TrainingSkillCandidateContext) -> str:
    teacher_intervention = _teacher_recommended_intervention(context)
    if teacher_intervention:
        return teacher_intervention
    if context.turn_patterns:
        pattern_types = [pattern.pattern_type for pattern in context.turn_patterns]
        if any(pattern_type == "evidence_chain_breakpoint" for pattern_type in pattern_types):
            return "在不透露标准答案的前提下，围绕本轮证据链断点追问学生：缺少哪些病史、查体或检查证据，以及这些证据如何支持或排除诊断假设。"
        if any(pattern_type == "sequence_issue" for pattern_type in pattern_types):
            return "在不透露标准答案的前提下，先指出本轮训练中的顺序跳步，再用问题引导学生回到病史、查体、检查和诊断表达的合理验证链。"
        return "在不透露标准答案的前提下，先识别本轮训练中的偏题、跳步或过早索要答案模式，再用苏格拉底式问题把学生带回当前 OSCE 阶段的证据采集目标。"
    return "在不透露标准答案的前提下，提醒学生按本轮训练中反复出现的漏项模式复盘问诊、查体、检查、诊断和推理链，而不是只修补单个评分点。"


def _teacher_analysis_summary(context: TrainingSkillCandidateContext) -> str:
    value = context.teacher_analysis_context.get("analysis_summary")
    return str(value or "").strip()


def _teacher_student_thinking_hypothesis(context: TrainingSkillCandidateContext) -> str:
    value = context.teacher_analysis_context.get("student_thinking_hypothesis")
    return str(value or "").strip()


def _teacher_recommended_intervention(context: TrainingSkillCandidateContext) -> str:
    focus = context.teacher_analysis_context.get("skill_memory_focus")
    if not isinstance(focus, dict):
        return ""
    return str(focus.get("recommended_intervention") or "").strip()


def _skill_type(context: TrainingSkillCandidateContext) -> SkillCandidateType:
    if context.turn_patterns:
        pattern_types = [pattern.pattern_type for pattern in context.turn_patterns]
        if any(pattern_type == "evidence_chain_breakpoint" for pattern_type in pattern_types):
            return "reasoning_bridge"
        if any(pattern_type == "sequence_issue" for pattern_type in pattern_types):
            return "workflow_sequencing"
        if any(pattern_type in {"off_topic_redirect"} for pattern_type in pattern_types):
            return "conversation_repair"
        if any("answer" in pattern_type or "safety" in pattern_type for pattern_type in pattern_types):
            return "safety_boundary"
        if any("before_history" in pattern_type or "before_physical_exam" in pattern_type for pattern_type in pattern_types):
            return "workflow_sequencing"
        return "conversation_repair"
    missed_items = context.missed_items
    item_ids = [item.item_id for item in missed_items]
    if any("safety" in item_id or "forbidden" in item_id for item_id in item_ids):
        return "safety_boundary"
    if any(item_id.startswith(("dxd_", "diff_")) for item_id in item_ids):
        return "differential_broadening"
    if any("reasoning" in item_id or item_id.startswith("rp_") for item_id in item_ids):
        return "reasoning_bridge"
    if any(item_id.startswith("nm_") for item_id in item_ids):
        return "narrative_perspective"
    if any(item_id.startswith("comm_") for item_id in item_ids):
        return "communication_structure"
    if any(item_id.startswith("eth_") for item_id in item_ids):
        return "ethics_consent"
    if any(item_id.startswith("rel_") for item_id in item_ids):
        return "relationship_repair"
    if any(item_id.startswith("ht_") for item_id in item_ids):
        return "history_bundle"
    if any(item_id.startswith(("pe_", "exam_")) for item_id in item_ids):
        return "exam_bundle"
    if any(item_id.startswith(("at_", "lab_", "img_", "test_")) for item_id in item_ids):
        return "test_strategy"
    return "reasoning_bridge"


def _stage_scope(skill_type: SkillCandidateType) -> list[str]:
    if skill_type == "conversation_repair":
        return ["case_intro", "history_taking"]
    if skill_type == "workflow_sequencing":
        return ["case_intro", "history_taking", "physical_exam", "auxiliary_testing"]
    if skill_type == "history_bundle":
        return ["case_intro", "history_taking"]
    if skill_type in {"narrative_perspective", "communication_structure", "relationship_repair"}:
        return ["case_intro", "history_taking"]
    if skill_type == "ethics_consent":
        return ["case_intro", "physical_exam", "auxiliary_testing"]
    if skill_type == "exam_bundle":
        return ["case_intro", "physical_exam"]
    if skill_type == "test_strategy":
        return ["case_intro", "auxiliary_testing"]
    if skill_type in {"reasoning_bridge", "differential_broadening"}:
        return ["case_intro", "diagnosis_submission"]
    if skill_type == "safety_boundary":
        return ["case_intro", "history_taking", "physical_exam", "auxiliary_testing", "diagnosis_submission"]
    return ["case_intro"]


def _applies_when(context: TrainingSkillCandidateContext, stage_scope: list[str]) -> dict[str, Any]:
    trigger_item_ids = _context_trigger_item_ids(context)
    return {
        "case_ids": list(context.case_ids),
        "stage_scope": list(stage_scope),
        "trigger_item_ids": trigger_item_ids,
        "current_missing_evidence": trigger_item_ids,
        "min_support_count": context.support_count,
    }


def _context_trigger_item_ids(context: TrainingSkillCandidateContext) -> list[str]:
    if context.turn_patterns:
        return sorted({trigger for pattern in context.turn_patterns for trigger in pattern.trigger_item_ids})
    return [item.item_id for item in context.missed_items]


def _context_source_report_ids(context: TrainingSkillCandidateContext) -> list[str]:
    return sorted(
        {
            *context.source_report_ids,
            *{
                report_id
                for item in context.missed_items
                for report_id in item.source_report_ids
            },
            *{
                report_id
                for pattern in context.turn_patterns
                for report_id in pattern.source_report_ids
            },
        }
    )


def _context_source_session_ids(context: TrainingSkillCandidateContext) -> list[str]:
    return sorted(
        {
            *context.source_session_ids,
            *{
                session_id
                for item in context.missed_items
                for session_id in item.session_ids
            },
            *{
                session_id
                for pattern in context.turn_patterns
                for session_id in pattern.session_ids
            },
        }
    )


def _normalized_source_ids(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if str(item)})


def _with_analysis_source_provenance(
    candidate: dict[str, Any],
    *,
    analysis_session_ids: list[str],
    analysis_report_ids: list[str],
) -> dict[str, Any]:
    candidate_session_ids = _normalized_source_ids(
        candidate.get("source_session_ids")
    )
    candidate_report_ids = _normalized_source_ids(
        candidate.get("source_report_ids")
    )
    source_session_ids = candidate_session_ids or analysis_session_ids
    source_report_ids = candidate_report_ids or analysis_report_ids
    if not source_session_ids and not source_report_ids:
        return candidate
    return {
        **candidate,
        "source_provenance_schema_version": "training_candidate_sources.v1",
        "source_session_ids": list(source_session_ids),
        "source_report_ids": list(source_report_ids),
    }


def _add_turn_pattern_source_fields(candidate: dict[str, Any], context: TrainingSkillCandidateContext) -> None:
    source_report_ids = _context_source_report_ids(context)
    source_session_ids = _context_source_session_ids(context)
    if source_report_ids:
        candidate["source_report_ids"] = source_report_ids
    if source_session_ids:
        candidate["source_session_ids"] = source_session_ids
    source_missed_items = _local_missed_item_provenance_payloads(
        context.missed_items
    )
    if source_missed_items:
        candidate["source_missed_items"] = source_missed_items
    if context.turn_patterns:
        candidate["source_turn_patterns"] = _local_turn_pattern_provenance_payloads(
            context.turn_patterns
        )


training_skill_candidate_service = TrainingSkillCandidateService()
