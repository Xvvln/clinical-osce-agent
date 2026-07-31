from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, field_validator

from app.services.anthropic_chat_client import AnthropicChatClient, AnthropicSettings
from app.services.api_call_log_service import call_with_api_logging
from app.services.gemini_patient_responder import GeminiPatientSettings
from app.services.google_genai_http_options import (
    build_google_genai_http_options,
    require_direct_runtime_vertex_adc_proxy,
)
from app.services.model_call_policy import call_google_text_generate_content
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.runtime_model_object_cache import RuntimeModelObjectCache


MAX_TEACHER_PROVIDER_PAYLOAD_BYTES = 48 * 1024
_MAX_TEACHER_TRACE_BYTES = 14 * 1024
_MAX_TEACHER_REASONING_SUMMARY_BYTES = 7 * 1024
_MAX_TEACHER_SUBMISSION_BYTES = 7 * 1024
_MAX_TEACHER_BASE_REFLECTION_BYTES = 10 * 1024
_MAX_TEACHER_SOURCE_REFERENCES_BYTES = 2 * 1024
_MAX_TEACHER_LONGITUDINAL_CONTEXT_BYTES = 4 * 1024

TEACHER_ANALYSIS_SYSTEM_PROMPT = """你是 OSCE 训练系统中的 TeacherAgent，负责训练后的临床教学分析。

你的任务不是给病例重新评分，也不是证明系统结论正确，而是基于后端提供的可信材料，像带教老师一样分析学生本轮临床思维：
- 学生是否建立了清楚的问题表征；
- 假设形成是否过早或过晚；
- 查体和检查是否服务于验证或排除假设；
- 鉴别诊断是否足够展开；
- 证据链在哪一步断裂；
- 下一轮应该如何具体练习。

若输入包含 longitudinal_context，它只是最近 3 份已完成训练报告的压缩教学摘要。你必须区分：
- first_seen_current_window：本轮窗口内首次出现，不得写成“长期反复”；
- repeated：本轮和上一份报告都出现；
- reactivated_after_improvement：更早出现、上一份暂时未出现、本轮再次出现；
- recovered_since_previous_report：上一份出现但本轮未出现，只能表述为“本轮暂未再现”，不得宣称已永久掌握。
training_skill_applied 只证明某个人 Skill 在训练中被调用，不证明它已产生效果。你应先处理反复或改善后再犯的问题，再处理本轮首次问题；下一步动作最多 3 条。
不同病例或不同难度的分数只能作描述性参考；当 direction= mixed_context_not_directly_comparable 时，不得据此宣称能力提升或下降。

不要只复述 missed_items。你需要提出一个“学生临床思维假设”：从本轮对话、动作顺序、诊断提交和 trace 推断学生的内在思维问题，例如结论先行、只收集阳性证据、缺少排除路径、查体/检查和假设脱节等。该假设必须是教学分析，不得改变事实或评分。

clinical_thinking_profile 建议包含这些键：
- problem_representation：学生是否形成了稳定的问题表征；
- hypothesis_management：学生如何形成、修正或过早锁定假设；
- verification_strategy：查体和检查是否围绕假设验证；
- differential_reasoning：鉴别诊断是否有支持/排除依据；
- metacognitive_next_move：下一轮最该练的思维动作。

硬性边界：
- 不得修改病例事实、标准诊断、rubric、评分结果或隐藏事实；
- 不得输出真实诊疗建议、治疗方案、用药剂量或处置指令；
- 不得泄露标准答案或把未披露病例事实直接讲给学生；
- 可以分析学生为什么漏、推理哪里断、下一步该如何训练；
- 每条分析应尽量锚定输入材料中的 trace、rubric 中文训练点、已覆盖/未覆盖线索或学生提交内容；
- 输出中文 JSON。
"""


class TeacherAnalysisRequest(BaseModel):
    case_id: str
    case_title: str
    score_text: str = ""
    missed_items: list[str] = Field(default_factory=list)
    missed_labels: list[str] = Field(default_factory=list)
    covered_labels: list[str] = Field(default_factory=list)
    pending_labels: list[str] = Field(default_factory=list)
    student_submission: dict[str, Any] = Field(default_factory=dict)
    clinical_reasoning_trace: dict[str, Any] = Field(default_factory=dict)
    reasoning_trace_summary: dict[str, Any] = Field(default_factory=dict)
    base_reflection: dict[str, Any] = Field(default_factory=dict)
    source_reference_items: list[dict[str, Any]] = Field(default_factory=list)
    longitudinal_context: dict[str, Any] = Field(default_factory=dict)


class TeacherAnalysisResponse(BaseModel):
    agent_id: str = "teacher_agent"
    analysis_mode: str = "post_session_teacher_analysis"
    analysis_summary: str = ""
    overall_comment: str = ""
    major_issues: list[dict[str, Any]] = Field(default_factory=list)
    teacher_coaching_review: list[dict[str, Any]] = Field(default_factory=list)
    reasoning_chain_review: str = ""
    next_practice_plan: list[str] = Field(default_factory=list, max_length=3)
    teacher_note: str = ""
    student_thinking_hypothesis: str = ""
    clinical_thinking_profile: dict[str, Any] = Field(default_factory=dict)
    skill_memory_focus: dict[str, Any] = Field(default_factory=dict)
    source_anchor_labels: list[str] = Field(default_factory=list)

    @field_validator("next_practice_plan", mode="before")
    @classmethod
    def _limit_next_practice_plan(cls, value: Any) -> Any:
        return list(value)[:3] if isinstance(value, list | tuple) else value


class DeterministicTeacherAgent:
    agent_id = "teacher_agent_deterministic"

    def __call__(self, request: TeacherAnalysisRequest) -> TeacherAnalysisResponse:
        base_reflection = request.base_reflection
        issue_titles = [
            str(issue.get("title", ""))
            for issue in base_reflection.get("major_issues", [])
            if isinstance(issue, dict) and issue.get("title")
        ]
        reasoning_summary = request.reasoning_trace_summary if isinstance(request.reasoning_trace_summary, dict) else {}
        dominant_patterns = [
            str(pattern.get("label") or pattern.get("pattern_id") or "")
            for pattern in reasoning_summary.get("dominant_patterns", [])
            if isinstance(pattern, dict) and (pattern.get("label") or pattern.get("pattern_id"))
        ]
        thinking_hypothesis = (
            "、".join(dominant_patterns[:2])
            if dominant_patterns
            else ("、".join(issue_titles[:2]) if issue_titles else "本轮仍需把临床线索组织成可验证的推理链")
        )
        longitudinal_assessment = _deterministic_longitudinal_assessment(
            request.longitudinal_context,
        )
        if longitudinal_assessment:
            thinking_hypothesis = f"{thinking_hypothesis}；{longitudinal_assessment}"
        return TeacherAnalysisResponse(
            agent_id=self.agent_id,
            analysis_mode="deterministic_baseline",
            analysis_summary=str(base_reflection.get("overall_comment") or base_reflection.get("summary") or ""),
            overall_comment=str(base_reflection.get("overall_comment") or ""),
            major_issues=list(base_reflection.get("major_issues") or []),
            teacher_coaching_review=list(base_reflection.get("teacher_coaching_review") or []),
            reasoning_chain_review=str(base_reflection.get("reasoning_chain_review") or ""),
            next_practice_plan=[str(item) for item in base_reflection.get("next_practice_plan", [])][:3],
            teacher_note=str(base_reflection.get("teacher_note") or ""),
            student_thinking_hypothesis=thinking_hypothesis,
            clinical_thinking_profile={
                "problem_representation": str(reasoning_summary.get("problem_representation_status") or ""),
                "hypothesis_management": "根据本轮顺序问题和主要问题组判断假设形成路径。",
                "verification_strategy": "根据已覆盖和未覆盖线索判断查体、检查是否服务于验证。",
                "differential_reasoning": "根据证据链断点判断是否形成支持与排除依据。",
                "metacognitive_next_move": str(base_reflection.get("next_focus") or ""),
                "longitudinal_gap_assessment": longitudinal_assessment,
            },
            skill_memory_focus={
                "problem_pattern_summary": "、".join(issue_titles[:3]) or "本轮临床思维训练问题",
                "recommended_intervention": str(base_reflection.get("next_focus") or ""),
                "longitudinal_status": longitudinal_assessment,
            },
            source_anchor_labels=[*request.missed_labels[:4], *request.pending_labels[:4]],
        )


class OpenAICompatibleTeacherAgent:
    def __init__(self, settings: OpenAICompatibleSettings, client: OpenAICompatibleChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or OpenAICompatibleChatClient(settings)

    def __call__(self, request: TeacherAnalysisRequest) -> TeacherAnalysisResponse:
        return self._client.complete_json(
            system_prompt=TEACHER_ANALYSIS_SYSTEM_PROMPT,
            payload=_build_teacher_provider_payload(request),
            response_model=TeacherAnalysisResponse,
            temperature=0.2,
        )


class AnthropicTeacherAgent:
    def __init__(self, settings: AnthropicSettings, client: AnthropicChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or AnthropicChatClient(settings)

    def __call__(self, request: TeacherAnalysisRequest) -> TeacherAnalysisResponse:
        return self._client.complete_json(
            system_prompt=TEACHER_ANALYSIS_SYSTEM_PROMPT,
            payload=_build_teacher_provider_payload(request),
            response_model=TeacherAnalysisResponse,
            temperature=0.2,
        )


class GeminiTeacherAgent:
    def __init__(self, settings: GeminiPatientSettings, client: Any | None = None) -> None:
        self._settings = settings
        if client is not None:
            self._client = client
        elif settings.use_vertex:
            client_options: dict[str, object] = {
                "vertexai": True,
                "http_options": build_google_genai_http_options(settings.proxy_url),
            }
            if settings.api_key:
                client_options["api_key"] = settings.api_key
            else:
                client_options["project"] = settings.project
                client_options["location"] = settings.location
            self._client = genai.Client(**client_options)
        else:
            self._client = genai.Client(
                api_key=settings.api_key,
                http_options=build_google_genai_http_options(settings.proxy_url),
            )

    def __call__(self, request: TeacherAnalysisRequest) -> TeacherAnalysisResponse:
        provider_payload = _build_teacher_provider_payload(request)
        return call_with_api_logging(
            provider="vertex_gemini_teacher" if self._settings.use_vertex else "gemini_teacher",
            operation="generate_content",
            model=self._settings.model,
            endpoint="vertex://generate_content" if self._settings.use_vertex else "gemini://generate_content",
            call=lambda: call_google_text_generate_content(
                client=self._client,
                model=self._settings.model,
                contents=json.dumps(provider_payload, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=TEACHER_ANALYSIS_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=TeacherAnalysisResponse,
                    temperature=0.2,
                ),
            ),
            result_parser=lambda response: TeacherAnalysisResponse.model_validate_json(
                response.text
            ),
        )


class LazyTeacherAgent:
    def __init__(self) -> None:
        self._agent_cache: RuntimeModelObjectCache[
            GeminiTeacherAgent
            | OpenAICompatibleTeacherAgent
            | AnthropicTeacherAgent
            | DeterministicTeacherAgent
        ] = RuntimeModelObjectCache()

    def __call__(self, request: TeacherAnalysisRequest) -> TeacherAnalysisResponse:
        agent = self._agent_cache.get_or_create(_create_configured_teacher_agent)
        return agent(request)


def normalize_teacher_analysis_response(response: TeacherAnalysisResponse | dict[str, Any]) -> TeacherAnalysisResponse:
    if isinstance(response, TeacherAnalysisResponse):
        return response
    return TeacherAnalysisResponse.model_validate(response)


def create_default_teacher_agent() -> LazyTeacherAgent:
    return LazyTeacherAgent()


def _create_configured_teacher_agent() -> (
    GeminiTeacherAgent | OpenAICompatibleTeacherAgent | AnthropicTeacherAgent | DeterministicTeacherAgent
):
    runtime_openai_settings = runtime_model_config_store.get_openai_compatible_settings()
    if runtime_openai_settings is not None:
        return OpenAICompatibleTeacherAgent(runtime_openai_settings)

    runtime_anthropic_settings = runtime_model_config_store.get_anthropic_settings()
    if runtime_anthropic_settings is not None:
        return AnthropicTeacherAgent(runtime_anthropic_settings)

    runtime_vertex_api_key_config = runtime_model_config_store.get_vertex_gemini_api_key_config()
    if runtime_vertex_api_key_config is not None:
        return GeminiTeacherAgent(
            settings=GeminiPatientSettings(
                api_key=runtime_vertex_api_key_config.api_key,
                use_vertex=True,
                project="",
                location=runtime_vertex_api_key_config.location,
                model=runtime_vertex_api_key_config.model,
                proxy_url=runtime_vertex_api_key_config.proxy_url,
            )
        )

    runtime_vertex_config = runtime_model_config_store.get_vertex_gemini_adc_config()
    if runtime_vertex_config is not None:
        require_direct_runtime_vertex_adc_proxy(runtime_vertex_config.proxy_url)
        return GeminiTeacherAgent(
            settings=GeminiPatientSettings(
                api_key="",
                use_vertex=True,
                project=runtime_vertex_config.project,
                location=runtime_vertex_config.location,
                model=runtime_vertex_config.model,
                proxy_url=runtime_vertex_config.proxy_url,
            )
        )

    openai_settings = OpenAICompatibleSettings()
    if openai_settings.is_configured:
        return OpenAICompatibleTeacherAgent(openai_settings)

    anthropic_settings = AnthropicSettings()
    if anthropic_settings.is_configured:
        return AnthropicTeacherAgent(anthropic_settings)

    settings = GeminiPatientSettings()
    if settings.use_vertex:
        vertex_api_key = settings.api_key or os.getenv("OSCE_VERTEX_API_KEY", "")
        project = settings.project or os.getenv("OSCE_VERTEX_PROJECT", "")
        location = os.getenv("OSCE_GEMINI_PATIENT_LOCATION", "") or os.getenv("OSCE_VERTEX_LOCATION", "") or settings.location
        model = os.getenv("OSCE_GEMINI_PATIENT_MODEL", "") or os.getenv("OSCE_VERTEX_MODEL", "") or settings.model
        if project or vertex_api_key:
            return GeminiTeacherAgent(
                settings=settings.model_copy(
                    update={
                        "api_key": vertex_api_key,
                        "project": project,
                        "location": location,
                        "model": model,
                    }
                )
            )

    api_key = settings.api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    if api_key:
        return GeminiTeacherAgent(settings=settings.model_copy(update={"api_key": api_key}))
    return DeterministicTeacherAgent()


def _build_teacher_provider_payload(request: TeacherAnalysisRequest) -> dict[str, Any]:
    """Project a full local analysis request into one bounded provider payload.

    The full clinical trace remains available to local deterministic analysis and
    persistence. Providers receive only the teaching signals that are useful for
    post-session reasoning, without the repeated action timeline and evidence
    structures already represented by the summary.
    """

    payload: dict[str, Any] = {
        "case_id": _bounded_teacher_provider_text(request.case_id, max_json_bytes=256),
        "case_title": _bounded_teacher_provider_text(request.case_title, max_json_bytes=768),
        "score_text": _bounded_teacher_provider_text(request.score_text, max_json_bytes=512),
        "missed_items": _bounded_teacher_provider_text_list(
            request.missed_items,
            max_items=12,
            max_item_json_bytes=160,
            max_json_bytes=768,
        ),
        "missed_labels": _bounded_teacher_provider_text_list(
            request.missed_labels,
            max_items=12,
            max_item_json_bytes=192,
            max_json_bytes=768,
        ),
        "covered_labels": _bounded_teacher_provider_text_list(
            request.covered_labels,
            max_items=12,
            max_item_json_bytes=192,
            max_json_bytes=768,
        ),
        "pending_labels": _bounded_teacher_provider_text_list(
            request.pending_labels,
            max_items=12,
            max_item_json_bytes=192,
            max_json_bytes=768,
        ),
        "student_submission": _teacher_submission_projection(
            request.student_submission,
        ),
        "clinical_reasoning_trace": _teacher_trace_projection(
            request.clinical_reasoning_trace,
        ),
        "reasoning_trace_summary": _teacher_reasoning_summary_projection(
            request.reasoning_trace_summary,
        ),
        "base_reflection": _teacher_base_reflection_projection(
            request.base_reflection,
        ),
        "source_reference_items": _teacher_source_reference_projection(
            request.source_reference_items,
        ),
        "longitudinal_context": _teacher_longitudinal_context_projection(
            request.longitudinal_context,
        ),
    }
    if _teacher_provider_json_size(payload) <= MAX_TEACHER_PROVIDER_PAYLOAD_BYTES:
        return payload

    # Component budgets already leave room for the top-level envelope. Keep a
    # deterministic last line of defence if a future field name grows or a
    # component budget changes without updating the total.
    for field_name in (
        "source_reference_items",
        "covered_labels",
        "missed_items",
        "missed_labels",
        "pending_labels",
    ):
        payload[field_name] = []
        if _teacher_provider_json_size(payload) <= MAX_TEACHER_PROVIDER_PAYLOAD_BYTES:
            return payload
    raise RuntimeError("TeacherAgent 模型请求超过内部载荷上限。")


def _deterministic_longitudinal_assessment(value: Any) -> str:
    context = _teacher_mapping(value)
    counts = _teacher_mapping(context.get("gap_status_counts"))
    reactivated = _bounded_non_negative_int(counts.get("reactivated_after_improvement"), maximum=12)
    repeated = _bounded_non_negative_int(counts.get("repeated"), maximum=12)
    first_seen = _bounded_non_negative_int(counts.get("first_seen_current_window"), maximum=12)
    recovered = _bounded_non_negative_int(counts.get("recovered_since_previous_report"), maximum=8)
    parts: list[str] = []
    if reactivated:
        parts.append(f"{reactivated} 个问题改善后再现")
    if repeated:
        parts.append(f"{repeated} 个问题连续出现")
    if first_seen:
        parts.append(f"{first_seen} 个问题为本窗口首次出现")
    if recovered:
        parts.append(f"{recovered} 个上轮问题本轮暂未再现")
    return "，".join(parts)


def _teacher_longitudinal_context_projection(value: Any) -> dict[str, Any]:
    context = _teacher_mapping(value)
    score_trend = _teacher_mapping(context.get("score_trend"))
    score_points = _bounded_teacher_provider_object_list(
        score_trend.get("points", []),
        projector=_teacher_longitudinal_score_point_projection,
        max_items=3,
        max_json_bytes=1_024,
    )
    current_gaps = _bounded_teacher_provider_object_list(
        context.get("current_gap_statuses", []),
        projector=_teacher_longitudinal_gap_projection,
        max_items=12,
        max_json_bytes=1_536,
    )
    recovered_gaps = _bounded_teacher_provider_object_list(
        context.get("recovered_gaps", []),
        projector=_teacher_longitudinal_gap_projection,
        max_items=8,
        max_json_bytes=1_024,
    )
    applied_skills = _bounded_teacher_provider_object_list(
        context.get("applied_personal_skills", []),
        projector=_teacher_longitudinal_skill_projection,
        max_items=6,
        max_json_bytes=1_024,
    )
    raw_counts = _teacher_mapping(context.get("gap_status_counts"))
    counts = {
        status: _bounded_non_negative_int(raw_counts.get(status), maximum=12)
        for status in (
            "first_seen_current_window",
            "repeated",
            "reactivated_after_improvement",
            "recovered_since_previous_report",
        )
    }
    projection = {
        "schema_version": _bounded_teacher_provider_text(
            context.get("schema_version", ""),
            max_json_bytes=128,
        ),
        "report_window_size": _bounded_non_negative_int(
            context.get("report_window_size"),
            maximum=3,
        ),
        "score_trend": {
            "order": _bounded_teacher_provider_text(
                score_trend.get("order", "oldest_to_newest"),
                max_json_bytes=64,
            ),
            "direction": _bounded_teacher_provider_text(
                score_trend.get("direction", "insufficient_history"),
                max_json_bytes=64,
            ),
            "points": score_points,
        },
        "current_gap_statuses": current_gaps,
        "recovered_gaps": recovered_gaps,
        "gap_status_counts": counts,
        "applied_personal_skills": applied_skills,
        "evidence_boundary": _bounded_teacher_provider_text(
            context.get("evidence_boundary", ""),
            max_json_bytes=512,
        ),
    }
    if _teacher_provider_json_size(projection) > _MAX_TEACHER_LONGITUDINAL_CONTEXT_BYTES:
        raise RuntimeError("TeacherAgent 纵向上下文投影超过内部载荷上限。")
    return projection


def _teacher_longitudinal_score_point_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "report_offset": _bounded_non_negative_int(value.get("report_offset"), maximum=2),
        "case_id": _bounded_teacher_provider_text(value.get("case_id", ""), max_json_bytes=128),
    }
    training_difficulty = _bounded_teacher_provider_text(
        value.get("training_difficulty", ""),
        max_json_bytes=64,
    )
    if training_difficulty:
        projection["training_difficulty"] = training_difficulty
    for field_name in ("total_score", "max_score", "score_percent"):
        number = _bounded_teacher_number(value.get(field_name))
        if number is not None:
            projection[field_name] = number
    return projection


def _teacher_longitudinal_gap_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return _compact_teacher_text_mapping(
        value,
        {
            "gap_id": 160,
            "gap_type": 96,
            "label": 256,
            "status": 128,
        },
    )


def _teacher_longitudinal_skill_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    projection = _compact_teacher_text_mapping(
        value,
        {
            "title": 256,
            "skill_type": 128,
            "effect_status": 128,
            "evidence": 128,
        },
    )
    projection["report_offset"] = _bounded_non_negative_int(
        value.get("report_offset"),
        maximum=2,
    )
    return projection


def _bounded_teacher_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if value != value or value in {float("inf"), float("-inf")}:
        return None
    return round(float(value), 2)


def _bounded_non_negative_int(value: Any, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return min(max(int(value), 0), maximum)


def _teacher_trace_projection(trace_value: Any) -> dict[str, Any]:
    trace = _teacher_mapping(trace_value)
    pattern_values = trace.get("cognitive_patterns", [])
    if not isinstance(pattern_values, list | tuple):
        pattern_values = []
    raw_patterns = [
        pattern
        for pattern in pattern_values
        if isinstance(pattern, Mapping)
    ]
    ordered_patterns = [
        pattern
        for _, pattern in sorted(
            enumerate(raw_patterns),
            key=lambda item: (
                _teacher_severity_priority(item[1].get("severity")),
                item[0],
            ),
        )
    ]
    projection = {
        "trace_version": _bounded_teacher_provider_text(
            trace.get("trace_version", ""),
            max_json_bytes=256,
        ),
        "cognitive_patterns": _bounded_teacher_provider_object_list(
            ordered_patterns,
            projector=_teacher_cognitive_pattern_projection,
            max_items=8,
            max_json_bytes=9 * 1024,
        ),
        "evidence_chain_breakpoints": _bounded_teacher_provider_object_list(
            trace.get("evidence_chain_breakpoints", []),
            projector=_teacher_evidence_breakpoint_projection,
            max_items=8,
            max_json_bytes=4 * 1024,
        ),
    }
    if _teacher_provider_json_size(projection) > _MAX_TEACHER_TRACE_BYTES:
        raise RuntimeError("TeacherAgent trace 投影超过内部载荷上限。")
    return projection


def _teacher_cognitive_pattern_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return _compact_teacher_text_mapping(
        value,
        {
            "pattern_id": 128,
            "label": 192,
            "category": 128,
            "severity": 64,
            "evidence": 512,
            "why_it_matters": 512,
            "remediation": 512,
        },
        list_fields={
            "source_signal_ids": (8, 128, 768),
            "trigger_item_ids": (8, 128, 512),
        },
    )


def _teacher_evidence_breakpoint_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return _compact_teacher_text_mapping(
        value,
        {
            "breakpoint_id": 128,
            "statement": 512,
            "kind": 128,
            "status": 64,
            "teacher_action": 768,
        },
        list_fields={
            "covered_evidence_labels": (6, 192, 512),
            "missing_evidence_labels": (8, 192, 768),
        },
    )


def _teacher_reasoning_summary_projection(summary_value: Any) -> dict[str, Any]:
    summary = _teacher_mapping(summary_value)
    projection = {
        "trace_version": _bounded_teacher_provider_text(
            summary.get("trace_version", ""),
            max_json_bytes=192,
        ),
        "dominant_patterns": _bounded_teacher_provider_object_list(
            summary.get("dominant_patterns", []),
            projector=_teacher_dominant_pattern_projection,
            max_items=6,
            max_json_bytes=1_280,
        ),
        "problem_representation_status": _bounded_teacher_provider_text(
            summary.get("problem_representation_status", ""),
            max_json_bytes=128,
        ),
        "illness_script_status": _bounded_teacher_provider_text(
            summary.get("illness_script_status", ""),
            max_json_bytes=128,
        ),
        "evidence_synthesis_status": _bounded_teacher_provider_text(
            summary.get("evidence_synthesis_status", ""),
            max_json_bytes=128,
        ),
        "sequence_flags": _bounded_teacher_provider_object_list(
            summary.get("sequence_flags", []),
            projector=_teacher_sequence_flag_projection,
            max_items=6,
            max_json_bytes=1_024,
        ),
        "action_order_summary": _teacher_action_order_projection(
            summary.get("action_order_summary", {}),
        ),
        "evidence_chain_breakpoints": _bounded_teacher_provider_object_list(
            summary.get("evidence_chain_breakpoints", []),
            projector=_teacher_summary_breakpoint_projection,
            max_items=5,
            max_json_bytes=1_536,
        ),
        "evidence_chain_focus": _bounded_teacher_provider_object_list(
            summary.get("evidence_chain_focus", []),
            projector=_teacher_summary_breakpoint_projection,
            max_items=3,
            max_json_bytes=1_536,
        ),
    }
    if _teacher_provider_json_size(projection) > _MAX_TEACHER_REASONING_SUMMARY_BYTES:
        raise RuntimeError("TeacherAgent reasoning summary 投影超过内部载荷上限。")
    return projection


def _teacher_dominant_pattern_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return _compact_teacher_text_mapping(
        value,
        {
            "pattern_id": 96,
            "label": 192,
            "category": 96,
            "severity": 64,
        },
    )


def _teacher_sequence_flag_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return _compact_teacher_text_mapping(
        value,
        {
            "flag_id": 96,
            "label": 192,
            "severity": 64,
            "evidence": 384,
        },
    )


def _teacher_summary_breakpoint_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return _compact_teacher_text_mapping(
        value,
        {
            "breakpoint_id": 96,
            "statement": 256,
            "teacher_action": 384,
        },
        list_fields={
            "missing_evidence_labels": (6, 160, 512),
        },
    )


def _teacher_action_order_projection(value: Any) -> dict[str, Any]:
    action_order = _teacher_mapping(value)
    result: dict[str, Any] = {}
    for field_name in (
        "first_history_fact_turn_index",
        "first_history_turn_index",
        "first_physical_exam_turn_index",
        "first_auxiliary_test_turn_index",
        "first_diagnosis_hypothesis_turn_index",
        "diagnosis_submission_turn_index",
        "history_fact_count_before_first_test",
        "problem_representation_coverage_ratio",
    ):
        if field_name not in action_order:
            continue
        raw_value = action_order[field_name]
        if isinstance(raw_value, bool | int | float) or raw_value is None:
            compact_value: Any = raw_value
        else:
            compact_value = _bounded_teacher_provider_text(
                raw_value,
                max_json_bytes=128,
            )
        candidate = {**result, field_name: compact_value}
        if _teacher_provider_json_size(candidate) <= 768:
            result = candidate
    return result


def _teacher_submission_projection(value: Any) -> dict[str, Any]:
    submission = _teacher_mapping(value)
    projection = {
        "diagnosis": _bounded_teacher_provider_text(
            submission.get("diagnosis", ""),
            max_json_bytes=1_024,
        ),
        "reasoning": _bounded_teacher_provider_text(
            submission.get("reasoning", ""),
            max_json_bytes=5_632,
        ),
    }
    if _teacher_provider_json_size(projection) > _MAX_TEACHER_SUBMISSION_BYTES:
        raise RuntimeError("TeacherAgent student submission 投影超过内部载荷上限。")
    return projection


def _teacher_base_reflection_projection(value: Any) -> dict[str, Any]:
    reflection = _teacher_mapping(value)
    projection = {
        "summary": _bounded_teacher_provider_text(
            reflection.get("summary", ""),
            max_json_bytes=512,
        ),
        "overall_comment": _bounded_teacher_provider_text(
            reflection.get("overall_comment", ""),
            max_json_bytes=768,
        ),
        "major_issues": _bounded_teacher_provider_object_list(
            reflection.get("major_issues", []),
            projector=_teacher_major_issue_projection,
            max_items=4,
            max_json_bytes=2 * 1024,
        ),
        "teacher_coaching_review": _bounded_teacher_provider_object_list(
            reflection.get("teacher_coaching_review", []),
            projector=_teacher_coaching_section_projection,
            max_items=6,
            max_json_bytes=3 * 1024,
        ),
        "reasoning_chain_review": _bounded_teacher_provider_text(
            reflection.get("reasoning_chain_review", ""),
            max_json_bytes=640,
        ),
        "next_practice_plan": _bounded_teacher_provider_text_list(
            reflection.get("next_practice_plan", []),
            max_items=3,
            max_item_json_bytes=384,
            max_json_bytes=640,
        ),
        "teacher_feedback": _bounded_teacher_provider_text(
            reflection.get("teacher_feedback", ""),
            max_json_bytes=512,
        ),
        "next_focus": _bounded_teacher_provider_text(
            reflection.get("next_focus", ""),
            max_json_bytes=512,
        ),
        "teacher_note": _bounded_teacher_provider_text(
            reflection.get("teacher_note", ""),
            max_json_bytes=384,
        ),
    }
    if _teacher_provider_json_size(projection) > _MAX_TEACHER_BASE_REFLECTION_BYTES:
        raise RuntimeError("TeacherAgent base reflection 投影超过内部载荷上限。")
    return projection


def _teacher_major_issue_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return _compact_teacher_text_mapping(
        value,
        {
            "title": 192,
            "observed_behavior": 320,
            "why_it_matters": 320,
            "correct_approach": 320,
            "next_action": 320,
        },
        list_fields={
            "linked_items": (6, 160, 384),
        },
    )


def _teacher_coaching_section_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return _compact_teacher_text_mapping(
        value,
        {
            "section_id": 128,
            "title": 192,
            "teacher_comment": 384,
            "why_it_matters": 320,
            "next_move": 384,
        },
        list_fields={
            "evidence_labels": (6, 160, 384),
        },
    )


def _teacher_source_reference_projection(value: Any) -> list[dict[str, Any]]:
    return _bounded_teacher_provider_object_list(
        value,
        projector=lambda item: _compact_teacher_text_mapping(
            item,
            {
                "reference": 384,
                "source_type": 128,
                "title": 384,
            },
        ),
        max_items=8,
        max_json_bytes=_MAX_TEACHER_SOURCE_REFERENCES_BYTES,
    )


def _compact_teacher_text_mapping(
    value: Mapping[str, Any],
    text_fields: Mapping[str, int],
    *,
    list_fields: Mapping[str, tuple[int, int, int]] | None = None,
) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for field_name, max_json_bytes in text_fields.items():
        if field_name not in value:
            continue
        compact[field_name] = _bounded_teacher_provider_text(
            value[field_name],
            max_json_bytes=max_json_bytes,
        )
    for field_name, (
        max_items,
        max_item_json_bytes,
        max_json_bytes,
    ) in (list_fields or {}).items():
        if field_name not in value:
            continue
        compact[field_name] = _bounded_teacher_provider_text_list(
            value[field_name],
            max_items=max_items,
            max_item_json_bytes=max_item_json_bytes,
            max_json_bytes=max_json_bytes,
        )
    return compact


def _bounded_teacher_provider_object_list(
    values: Any,
    *,
    projector: Callable[[Mapping[str, Any]], dict[str, Any]],
    max_items: int,
    max_json_bytes: int,
) -> list[dict[str, Any]]:
    if not isinstance(values, list | tuple):
        return []
    result: list[dict[str, Any]] = []
    for value in values:
        if len(result) >= max_items:
            break
        if not isinstance(value, Mapping):
            continue
        projected = projector(value)
        if not projected:
            continue
        candidate = [*result, projected]
        if _teacher_provider_json_size(candidate) <= max_json_bytes:
            result = candidate
    return result


def _bounded_teacher_provider_text_list(
    values: Any,
    *,
    max_items: int,
    max_item_json_bytes: int,
    max_json_bytes: int,
) -> list[str]:
    if not isinstance(values, list | tuple):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if len(result) >= max_items:
            break
        text = _bounded_teacher_provider_text(
            value,
            max_json_bytes=max_item_json_bytes,
        )
        if not text or text in seen:
            continue
        candidate = [*result, text]
        if _teacher_provider_json_size(candidate) > max_json_bytes:
            continue
        result = candidate
        seen.add(text)
    return result


def _bounded_teacher_provider_text(value: Any, *, max_json_bytes: int) -> str:
    if value is None:
        return ""
    normalized = (
        str(value)
        .encode("utf-8", errors="replace")
        .decode("utf-8")
        .strip()
    )
    if _teacher_provider_json_size(normalized) <= max_json_bytes:
        return normalized

    marker = "…"
    if _teacher_provider_json_size(marker) > max_json_bytes:
        return ""
    low = 0
    high = len(normalized)
    best = marker
    while low <= high:
        midpoint = (low + high) // 2
        candidate = f"{normalized[:midpoint]}{marker}"
        if _teacher_provider_json_size(candidate) <= max_json_bytes:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best


def _teacher_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _teacher_severity_priority(value: Any) -> int:
    return {
        "high": 0,
        "medium": 1,
        "low": 2,
    }.get(str(value).strip().casefold(), 3)


def _teacher_provider_json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


__all__ = [
    "AnthropicTeacherAgent",
    "DeterministicTeacherAgent",
    "GeminiTeacherAgent",
    "LazyTeacherAgent",
    "OpenAICompatibleTeacherAgent",
    "TeacherAnalysisRequest",
    "TeacherAnalysisResponse",
    "create_default_teacher_agent",
    "normalize_teacher_analysis_response",
]
