from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.anthropic_chat_client import AnthropicChatClient, AnthropicSettings
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.training_skill_policy import (
    build_prohibited_content_policy,
    build_success_metrics,
    build_teaching_action_plan,
)


@dataclass(frozen=True)
class TrainingSkillCandidateMissedItem:
    item_id: str
    count: int
    case_ids: list[str]


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
    turn_patterns: list[TrainingSkillCandidateTurnPattern] = field(default_factory=list)


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
- suggested_strategy 必须是面向学生的训练提醒，而不是临床处方。
"""


class VertexGeminiTrainingSkillCandidateGenerator:
    def __init__(self, settings: VertexGeminiSkillCandidateSettings, client: Any | None = None) -> None:
        self._settings = settings
        if client is not None:
            self._client = client
        elif settings.api_key:
            self._client = genai.Client(vertexai=True, api_key=settings.api_key)
        else:
            self._client = genai.Client(
                vertexai=True,
                project=settings.project,
                location=settings.location,
            )

    def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, Any]:
        try:
            response = self._client.models.generate_content(
                model=self._settings.skill_candidate_model,
                contents=json.dumps(
                    {
                        "pattern_id": context.pattern_id,
                        "missed_items": _missed_item_payloads(context.missed_items),
                        "turn_patterns": _turn_pattern_payloads(context.turn_patterns),
                        "support_count": context.support_count,
                        "case_ids": context.case_ids,
                        "source_report_count": context.source_report_count,
                        "source_report_ids": _context_source_report_ids(context),
                        "related_recommendations": context.related_recommendations,
                    },
                    ensure_ascii=False,
                ),
                config=types.GenerateContentConfig(
                    system_instruction=SKILL_CANDIDATE_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=GeneratedTrainingSkillCandidateContent,
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
                payload={
                    "pattern_id": context.pattern_id,
                    "missed_items": _missed_item_payloads(context.missed_items),
                    "turn_patterns": _turn_pattern_payloads(context.turn_patterns),
                    "support_count": context.support_count,
                    "case_ids": context.case_ids,
                    "source_report_count": context.source_report_count,
                    "source_report_ids": _context_source_report_ids(context),
                    "related_recommendations": context.related_recommendations,
                },
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
                payload={
                    "pattern_id": context.pattern_id,
                    "missed_items": _missed_item_payloads(context.missed_items),
                    "turn_patterns": _turn_pattern_payloads(context.turn_patterns),
                    "support_count": context.support_count,
                    "case_ids": context.case_ids,
                    "source_report_count": context.source_report_count,
                    "source_report_ids": _context_source_report_ids(context),
                    "related_recommendations": context.related_recommendations,
                },
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
        _apply_process_proxy(runtime_vertex_api_key_config.proxy_url)
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
        _apply_process_proxy(runtime_vertex_config.proxy_url)
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
    _apply_process_proxy(settings.proxy_url)
    return VertexGeminiTrainingSkillCandidateGenerator(settings=settings, client=client)


class TrainingSkillCandidateService:
    def __init__(self, generator: TrainingSkillCandidateGenerator | None = None) -> None:
        self._generator = generator or create_default_training_skill_candidate_generator()

    def propose_candidates(self, insights: dict[str, Any], min_count: int = 2) -> list[dict[str, Any]]:
        source_report_count = int(insights.get("report_count", 0))
        recurring_missed_items = _recurring_missed_items(insights, min_count)
        related_recommendations = [
            recommendation["reference"]
            for recommendation in insights.get("frequent_learning_recommendations", [])
        ]
        candidates: list[dict[str, Any]] = []
        if recurring_missed_items:
            context = TrainingSkillCandidateContext(
                pattern_id=_training_pattern_id(recurring_missed_items),
                missed_items=recurring_missed_items,
                support_count=max(item.count for item in recurring_missed_items),
                case_ids=_pattern_case_ids(recurring_missed_items),
                source_report_count=source_report_count,
                related_recommendations=related_recommendations,
            )
            candidates.append(self._generator.generate_candidate(context))

        for turn_pattern in _recurring_turn_patterns(insights, min_count):
            context = TrainingSkillCandidateContext(
                pattern_id=turn_pattern.pattern_id,
                missed_items=[],
                support_count=turn_pattern.count,
                case_ids=list(turn_pattern.case_ids),
                source_report_count=turn_pattern.source_report_count,
                related_recommendations=related_recommendations,
                turn_patterns=[turn_pattern],
            )
            candidates.append(self._generator.generate_candidate(context))
        return candidates


def _recurring_missed_items(insights: dict[str, Any], min_count: int) -> list[TrainingSkillCandidateMissedItem]:
    missed_items = [
        TrainingSkillCandidateMissedItem(
            item_id=missed_item["item_id"],
            count=int(missed_item["count"]),
            case_ids=sorted(str(case_id) for case_id in missed_item["case_ids"]),
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


def _missed_item_payloads(missed_items: list[TrainingSkillCandidateMissedItem]) -> list[dict[str, Any]]:
    return [
        {
            "item_id": item.item_id,
            "count": item.count,
            "case_ids": item.case_ids,
        }
        for item in missed_items
    ]


def _turn_pattern_payloads(turn_patterns: list[TrainingSkillCandidateTurnPattern]) -> list[dict[str, Any]]:
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
    _add_turn_pattern_source_fields(candidate, context)
    return candidate


def _build_candidate(context: TrainingSkillCandidateContext) -> dict[str, Any]:
    skill_type = _skill_type(context)
    stage_scope = _stage_scope(skill_type)
    trigger_item_ids = _context_trigger_item_ids(context)
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
    _add_turn_pattern_source_fields(candidate, context)
    return candidate


def _candidate_description(context: TrainingSkillCandidateContext) -> str:
    if context.turn_patterns:
        turn_pattern_summaries = "、".join(
            f"{pattern.title}（{pattern.count} 次，涉及 {'、'.join(pattern.session_ids)}）"
            for pattern in context.turn_patterns
        )
        return f"{context.source_report_count} 份报告关联的话轮记录中反复出现 {len(context.turn_patterns)} 类训练过程模式：{turn_pattern_summaries}。"
    missed_item_summaries = "、".join(
        f"{item.item_id}（{item.count} 次，涉及 {'、'.join(item.case_ids)}）"
        for item in context.missed_items
    )
    return f"{context.source_report_count} 份报告中反复出现 {len(context.missed_items)} 类训练漏项：{missed_item_summaries}。"


def _suggested_strategy(context: TrainingSkillCandidateContext) -> str:
    if context.turn_patterns:
        return "在不透露标准答案的前提下，先识别本轮训练中的偏题、跳步或过早索要答案模式，再用苏格拉底式问题把学生带回当前 OSCE 阶段的证据采集目标。"
    return "在不透露标准答案的前提下，提醒学生按本轮训练中反复出现的漏项模式复盘问诊、查体、检查、诊断和推理链，而不是只修补单个评分点。"


def _skill_type(context: TrainingSkillCandidateContext) -> SkillCandidateType:
    if context.turn_patterns:
        pattern_types = [pattern.pattern_type for pattern in context.turn_patterns]
        if any(pattern_type in {"off_topic_redirect"} for pattern_type in pattern_types):
            return "conversation_repair"
        if any("answer" in pattern_type or "safety" in pattern_type for pattern_type in pattern_types):
            return "safety_boundary"
        if any("before_history" in pattern_type for pattern_type in pattern_types):
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
    return sorted({report_id for pattern in context.turn_patterns for report_id in pattern.source_report_ids})


def _context_source_session_ids(context: TrainingSkillCandidateContext) -> list[str]:
    return sorted({session_id for pattern in context.turn_patterns for session_id in pattern.session_ids})


def _add_turn_pattern_source_fields(candidate: dict[str, Any], context: TrainingSkillCandidateContext) -> None:
    if not context.turn_patterns:
        return
    candidate["source_report_ids"] = _context_source_report_ids(context)
    candidate["source_session_ids"] = _context_source_session_ids(context)
    candidate["source_turn_patterns"] = _turn_pattern_payloads(context.turn_patterns)


def _apply_process_proxy(proxy_url: str) -> None:
    if not proxy_url.strip().lower() or proxy_url.strip().lower() in {"direct", "none", "false", "off", "no"}:
        return
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ["ALL_PROXY"] = proxy_url


training_skill_candidate_service = TrainingSkillCandidateService()
