from __future__ import annotations

import json
import os
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.services.anthropic_chat_client import AnthropicChatClient, AnthropicSettings
from app.services.gemini_patient_responder import GeminiPatientSettings, _apply_process_proxy
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.runtime_model_config_store import runtime_model_config_store


TEACHER_ANALYSIS_SYSTEM_PROMPT = """你是 OSCE 训练系统中的 TeacherAgent，负责训练后的临床教学分析。

你的任务不是给病例重新评分，也不是证明系统结论正确，而是基于后端提供的可信材料，像带教老师一样分析学生本轮临床思维：
- 学生是否建立了清楚的问题表征；
- 假设形成是否过早或过晚；
- 查体和检查是否服务于验证或排除假设；
- 鉴别诊断是否足够展开；
- 证据链在哪一步断裂；
- 下一轮应该如何具体练习。

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


class TeacherAnalysisResponse(BaseModel):
    agent_id: str = "teacher_agent"
    analysis_mode: str = "post_session_teacher_analysis"
    analysis_summary: str = ""
    overall_comment: str = ""
    major_issues: list[dict[str, Any]] = Field(default_factory=list)
    teacher_coaching_review: list[dict[str, Any]] = Field(default_factory=list)
    reasoning_chain_review: str = ""
    next_practice_plan: list[str] = Field(default_factory=list)
    teacher_note: str = ""
    student_thinking_hypothesis: str = ""
    clinical_thinking_profile: dict[str, Any] = Field(default_factory=dict)
    skill_memory_focus: dict[str, Any] = Field(default_factory=dict)
    source_anchor_labels: list[str] = Field(default_factory=list)


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
        return TeacherAnalysisResponse(
            agent_id=self.agent_id,
            analysis_mode="deterministic_baseline",
            analysis_summary=str(base_reflection.get("overall_comment") or base_reflection.get("summary") or ""),
            overall_comment=str(base_reflection.get("overall_comment") or ""),
            major_issues=list(base_reflection.get("major_issues") or []),
            teacher_coaching_review=list(base_reflection.get("teacher_coaching_review") or []),
            reasoning_chain_review=str(base_reflection.get("reasoning_chain_review") or ""),
            next_practice_plan=[str(item) for item in base_reflection.get("next_practice_plan", [])],
            teacher_note=str(base_reflection.get("teacher_note") or ""),
            student_thinking_hypothesis=thinking_hypothesis,
            clinical_thinking_profile={
                "problem_representation": str(reasoning_summary.get("problem_representation_status") or ""),
                "hypothesis_management": "根据本轮顺序问题和主要问题组判断假设形成路径。",
                "verification_strategy": "根据已覆盖和未覆盖线索判断查体、检查是否服务于验证。",
                "differential_reasoning": "根据证据链断点判断是否形成支持与排除依据。",
                "metacognitive_next_move": str(base_reflection.get("next_focus") or ""),
            },
            skill_memory_focus={
                "problem_pattern_summary": "、".join(issue_titles[:3]) or "本轮临床思维训练问题",
                "recommended_intervention": str(base_reflection.get("next_focus") or ""),
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
            payload=request.model_dump(),
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
            payload=request.model_dump(),
            response_model=TeacherAnalysisResponse,
            temperature=0.2,
        )


class GeminiTeacherAgent:
    def __init__(self, settings: GeminiPatientSettings, client: Any | None = None) -> None:
        self._settings = settings
        if client is not None:
            self._client = client
        elif settings.use_vertex:
            client_options: dict[str, object] = {"vertexai": True}
            if settings.api_key:
                client_options["api_key"] = settings.api_key
            else:
                client_options["project"] = settings.project
                client_options["location"] = settings.location
            self._client = genai.Client(**client_options)
        else:
            self._client = genai.Client(api_key=settings.api_key)

    def __call__(self, request: TeacherAnalysisRequest) -> TeacherAnalysisResponse:
        response = self._client.models.generate_content(
            model=self._settings.model,
            contents=json.dumps(request.model_dump(), ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=TEACHER_ANALYSIS_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=TeacherAnalysisResponse,
                temperature=0.2,
            ),
        )
        return TeacherAnalysisResponse.model_validate_json(response.text)


class LazyTeacherAgent:
    def __init__(self) -> None:
        self._agent: (
            GeminiTeacherAgent
            | OpenAICompatibleTeacherAgent
            | AnthropicTeacherAgent
            | DeterministicTeacherAgent
            | None
        ) = None
        self._cache_key: tuple[str, ...] | None = None

    def __call__(self, request: TeacherAnalysisRequest) -> TeacherAnalysisResponse:
        cache_key = runtime_model_config_store.active_config_cache_key()
        if self._agent is None or self._cache_key != cache_key:
            self._agent = _create_configured_teacher_agent()
            self._cache_key = cache_key
        return self._agent(request)


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
        _apply_process_proxy(runtime_vertex_api_key_config.proxy_url)
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
        _apply_process_proxy(runtime_vertex_config.proxy_url)
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
    _apply_process_proxy(settings.proxy_url)
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
