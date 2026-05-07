from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.runtime_model_config_store import runtime_model_config_store


@dataclass(frozen=True)
class TrainingSkillCandidateMissedItem:
    item_id: str
    count: int
    case_ids: list[str]


@dataclass(frozen=True)
class TrainingSkillCandidateContext:
    pattern_id: str
    missed_items: list[TrainingSkillCandidateMissedItem]
    support_count: int
    case_ids: list[str]
    source_report_count: int
    related_recommendations: list[str]


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
                        "support_count": context.support_count,
                        "case_ids": context.case_ids,
                        "source_report_count": context.source_report_count,
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
                    "support_count": context.support_count,
                    "case_ids": context.case_ids,
                    "source_report_count": context.source_report_count,
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
        if not recurring_missed_items:
            return []

        related_recommendations = [
            recommendation["reference"]
            for recommendation in insights.get("frequent_learning_recommendations", [])
        ]
        context = TrainingSkillCandidateContext(
            pattern_id=_training_pattern_id(recurring_missed_items),
            missed_items=recurring_missed_items,
            support_count=max(item.count for item in recurring_missed_items),
            case_ids=_pattern_case_ids(recurring_missed_items),
            source_report_count=source_report_count,
            related_recommendations=related_recommendations,
        )
        return [self._generator.generate_candidate(context)]


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


def _candidate_from_content(
    context: TrainingSkillCandidateContext,
    content: GeneratedTrainingSkillCandidateContent,
) -> dict[str, Any]:
    skill_type = _skill_type(context.missed_items)
    stage_scope = _stage_scope(skill_type)
    return {
        "candidate_id": f"skill_candidate_{context.pattern_id}",
        "trigger_item_id": context.pattern_id,
        "trigger_item_ids": [item.item_id for item in context.missed_items],
        "case_ids": list(context.case_ids),
        "skill_type": skill_type,
        "stage_scope": stage_scope,
        "effect_status": "insufficient_samples",
        "applies_when": _applies_when(context, stage_scope),
        "title": content.title,
        "description": content.description,
        "suggested_strategy": content.suggested_strategy,
        "status": "draft",
        "source_report_count": context.source_report_count,
        "support_count": context.support_count,
        "related_recommendations": list(context.related_recommendations),
    }


def _build_candidate(context: TrainingSkillCandidateContext) -> dict[str, Any]:
    skill_type = _skill_type(context.missed_items)
    stage_scope = _stage_scope(skill_type)
    return {
        "candidate_id": f"skill_candidate_{context.pattern_id}",
        "trigger_item_id": context.pattern_id,
        "trigger_item_ids": [item.item_id for item in context.missed_items],
        "case_ids": list(context.case_ids),
        "skill_type": skill_type,
        "stage_scope": stage_scope,
        "effect_status": "insufficient_samples",
        "applies_when": _applies_when(context, stage_scope),
        "title": "OSCE 训练模式纠偏提示",
        "description": _candidate_description(context),
        "suggested_strategy": "在不透露标准答案的前提下，提醒学生按本轮训练中反复出现的漏项模式复盘问诊、查体、检查、诊断和推理链，而不是只修补单个评分点。",
        "status": "draft",
        "source_report_count": context.source_report_count,
        "support_count": context.support_count,
        "related_recommendations": context.related_recommendations,
    }


def _candidate_description(context: TrainingSkillCandidateContext) -> str:
    missed_item_summaries = "、".join(
        f"{item.item_id}（{item.count} 次，涉及 {'、'.join(item.case_ids)}）"
        for item in context.missed_items
    )
    return f"{context.source_report_count} 份报告中反复出现 {len(context.missed_items)} 类训练漏项：{missed_item_summaries}。"


def _skill_type(missed_items: list[TrainingSkillCandidateMissedItem]) -> SkillCandidateType:
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
    trigger_item_ids = [item.item_id for item in context.missed_items]
    return {
        "case_ids": list(context.case_ids),
        "stage_scope": list(stage_scope),
        "trigger_item_ids": trigger_item_ids,
        "current_missing_evidence": trigger_item_ids,
        "min_support_count": context.support_count,
    }


def _apply_process_proxy(proxy_url: str) -> None:
    if not proxy_url.strip().lower() or proxy_url.strip().lower() in {"direct", "none", "false", "off", "no"}:
        return
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ["ALL_PROXY"] = proxy_url


training_skill_candidate_service = TrainingSkillCandidateService()
