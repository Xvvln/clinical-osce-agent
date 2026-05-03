from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class TrainingSkillCandidateContext:
    item_id: str
    support_count: int
    case_ids: list[str]
    source_report_count: int
    related_recommendations: list[str]


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
    project: str = ""
    location: str = "global"
    skill_candidate_model: str = "gemini-3.1-flash-lite-preview"
    proxy_url: str = "http://127.0.0.1:7897"


SKILL_CANDIDATE_SYSTEM_PROMPT = """你是 OSCE 临床思维训练的教学 Skill 候选生成器。

你只能基于输入的漏项统计、病例 ID 和学习建议引用，生成用于训练复盘的教学策略候选。

输出要求：
- 只输出 title、description、suggested_strategy 三个字段；
- 不得透露标准诊断、隐藏病例事实或标准答案；
- 不得生成真实诊疗建议、治疗方案、用药剂量、手术方案或处置建议；
- suggested_strategy 必须是面向学生的训练提醒，而不是临床处方。
"""


class VertexGeminiTrainingSkillCandidateGenerator:
    def __init__(self, settings: VertexGeminiSkillCandidateSettings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client or genai.Client(
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
                        "item_id": context.item_id,
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

        return {
            "candidate_id": f"skill_candidate_{context.item_id}",
            "trigger_item_id": context.item_id,
            "title": content.title,
            "description": content.description,
            "suggested_strategy": content.suggested_strategy,
            "status": "draft",
            "source_report_count": context.source_report_count,
            "support_count": context.support_count,
            "related_recommendations": list(context.related_recommendations),
        }


class TemplateTrainingSkillCandidateGenerator:
    def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, Any]:
        return _build_candidate(
            item_id=context.item_id,
            support_count=context.support_count,
            case_ids=context.case_ids,
            source_report_count=context.source_report_count,
            related_recommendations=context.related_recommendations,
        )


def create_default_training_skill_candidate_generator(
    client: Any | None = None,
) -> TrainingSkillCandidateGenerator:
    settings = VertexGeminiSkillCandidateSettings()
    if not settings.skill_candidate_enabled or not settings.project:
        return TemplateTrainingSkillCandidateGenerator()
    os.environ["HTTP_PROXY"] = settings.proxy_url
    os.environ["HTTPS_PROXY"] = settings.proxy_url
    return VertexGeminiTrainingSkillCandidateGenerator(settings=settings, client=client)


class TrainingSkillCandidateService:
    def __init__(self, generator: TrainingSkillCandidateGenerator | None = None) -> None:
        self._generator = generator or create_default_training_skill_candidate_generator()

    def propose_candidates(self, insights: dict[str, Any], min_count: int = 2) -> list[dict[str, Any]]:
        source_report_count = insights.get("report_count", 0)
        related_recommendations = [
            recommendation["reference"]
            for recommendation in insights.get("frequent_learning_recommendations", [])
        ]
        candidates: list[dict[str, Any]] = []

        for missed_item in insights.get("frequent_missed_items", []):
            support_count = missed_item["count"]
            if support_count < min_count:
                continue
            context = TrainingSkillCandidateContext(
                item_id=missed_item["item_id"],
                support_count=support_count,
                case_ids=missed_item["case_ids"],
                source_report_count=source_report_count,
                related_recommendations=related_recommendations,
            )
            candidates.append(self._generator.generate_candidate(context))
        return candidates


def _build_candidate(
    item_id: str,
    support_count: int,
    case_ids: list[str],
    source_report_count: int,
    related_recommendations: list[str],
) -> dict[str, Any]:
    if item_id == "reasoning_core":
        return {
            "candidate_id": f"skill_candidate_{item_id}",
            "trigger_item_id": item_id,
            "title": "临床推理链纠偏提示",
            "description": _candidate_description(item_id, support_count, case_ids, source_report_count),
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": source_report_count,
            "support_count": support_count,
            "related_recommendations": related_recommendations,
        }
    return {
        "candidate_id": f"skill_candidate_{item_id}",
        "trigger_item_id": item_id,
        "title": "OSCE 漏项纠偏提示",
        "description": _candidate_description(item_id, support_count, case_ids, source_report_count),
        "suggested_strategy": "在不透露标准答案的前提下，提醒学生回顾本轮训练中反复遗漏的问诊、查体、检查或推理要点。",
        "status": "draft",
        "source_report_count": source_report_count,
        "support_count": support_count,
        "related_recommendations": related_recommendations,
    }


def _candidate_description(item_id: str, support_count: int, case_ids: list[str], source_report_count: int) -> str:
    return f"{source_report_count} 份报告中有 {support_count} 次漏掉 {item_id}，涉及病例：{'、'.join(case_ids)}。"


training_skill_candidate_service = TrainingSkillCandidateService()
