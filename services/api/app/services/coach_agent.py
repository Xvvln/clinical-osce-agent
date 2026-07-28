from __future__ import annotations

import json
import os
import re
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.services.anthropic_chat_client import AnthropicChatClient, AnthropicSettings
from app.services.api_call_log_service import call_with_api_logging
from app.services.gemini_patient_responder import GeminiPatientSettings
from app.services.google_genai_http_options import (
    build_google_genai_http_options,
    require_direct_runtime_vertex_adc_proxy,
)
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.runtime_model_object_cache import RuntimeModelObjectCache

SYSTEM_PROMPT_TEMPLATE = """你是 OSCE 训练系统中的 TeacherAgent 训练中提示模块，只负责生成短提示来帮助学生继续训练。

硬性规则：
- 只能生成教学提示、苏格拉底式引导或下一步训练策略。
- 不得输出诊断答案、病例隐藏事实、rubric 全量、治疗方案、用药剂量或真实医疗建议。
- 不要新增医学事实；只能围绕 base_hint、hint_context、pedagogy_state、clinical_reasoning_state、skill_context、retrieved_knowledge_context 和已公开对话做教学引导。
- 如果 hint_context 存在，优先参考其中的 next_step、hint_policy、evidence_coverage、difficulty_policy、skill_selection 和 rag_context，综合判断下一步提示，而不是只复述 base_hint。
- 如果 hint_context.hint_policy.trigger_state 是 preparation 或 triggered，必须保留 hint_policy.training_goal_hint 的教学目标，不能改写成普通临床下一步提示。
- 如果 prompt_kind 是 skill_router，只判断 TeacherAgent 此刻是否需要使用候选 Skill：只可从 hint_context.skill_selection.candidate_skills 中选择 selected_skill_ids；空白开局、普通下一步提示或没有明确错误模式时 selected_skill_ids=[]，skill_intervention_level="none"。
- 如果 prompt_kind 是 socratic_hint，只有 skill_context 非空时才把其中 Skill 作为本轮教学策略；skill_context 为空时不要编造“本轮训练重点”。
- 如果 prompt_kind 是 socratic_hint，输出必须像“下一步可以怎么问/怎么做 + 为什么这样做”的教学提示，不要写成考试题。
- training_difficulty 会影响提示粒度：beginner 可更明确指出下一类动作；intermediate 应提示学生选择项目并说明目的；advanced 应引导学生用自由文本表达想申请什么和为什么。
- 如果 clinical_reasoning_state 中存在 sequence_flags，应指出训练顺序缺口，并给出下一步可执行动作及简短理由。
- 不要要求学生“请说明/解释/写出问诊目的、检查目的、操作目的或申请目的”；提示可以反问，但必须包含可执行下一步。
- 如果学生已接近提交诊断，只提醒整理证据链和排除依据，不要给出标准答案。
- 如果 prompt_kind 是 passive_turn_review，必须先判断是否真的需要打断学生；学生提出有效问诊且患者已回答时，should_emit=false 且 hint=""。
- 如果 prompt_kind 是 answer_boundary_redirect 或 safety_boundary_redirect，必须 should_emit=true，并用 base_hint 改写为教练边界提示。
- 输出中文，简洁，不超过 80 个汉字。
- 只输出 JSON，字段为 should_emit、hint、trigger_kind、selected_skill_ids、skill_intervention_level、skill_selection_reason。
"""


class CoachRequest(BaseModel):
    case_id: str
    case_title: str
    chief_complaint: str
    stage: str
    training_difficulty: str = "beginner"
    prompt_kind: str
    base_hint: str
    prior_messages: list[dict[str, str]] = Field(default_factory=list)
    pedagogy_state: dict[str, Any] = Field(default_factory=dict)
    clinical_reasoning_state: dict[str, Any] = Field(default_factory=dict)
    skill_context: list[str] = Field(default_factory=list)
    retrieved_knowledge_context: list[dict[str, Any]] = Field(default_factory=list)
    hint_context: dict[str, Any] = Field(default_factory=dict)
    forbidden_terms: list[str] = Field(default_factory=list)


class CoachResponse(BaseModel):
    should_emit: bool = True
    hint: str = Field(default="", max_length=160)
    trigger_kind: str = "manual_hint"
    selected_skill_ids: list[str] = Field(default_factory=list)
    skill_intervention_level: str = "auto"
    skill_selection_reason: str = ""


_COACH_PROVIDER_REDACTION = "[redacted]"
_COACH_SENSITIVE_KEY_PARTS = (
    "answer",
    "canonical",
    "case_id",
    "coverage",
    "covered",
    "diagnos",
    "fact",
    "forbidden",
    "hidden",
    "missing",
    "must",
    "pending",
    "private",
    "reference",
    "result",
    "rubric",
    "score",
    "secret",
    "session",
    "source",
    "treatment",
)


def _coach_provider_payload(request: CoachRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": request.stage,
        "training_difficulty": request.training_difficulty,
        "prompt_kind": request.prompt_kind,
        "base_hint": request.base_hint,
        "prior_messages": request.prior_messages,
        "pedagogy_state": request.pedagogy_state,
        "clinical_reasoning_state": request.clinical_reasoning_state,
        "skill_context": request.skill_context,
        "retrieved_knowledge_context": request.retrieved_knowledge_context,
        "hint_context": request.hint_context,
    }
    redaction_terms = _coach_redaction_terms(request)
    return _sanitize_coach_provider_value(payload, redaction_terms)


def _coach_redaction_terms(request: CoachRequest) -> tuple[str, ...]:
    terms = {
        term.strip()
        for term in [request.case_id, *request.forbidden_terms]
        if isinstance(term, str) and term.strip()
    }
    return tuple(sorted(terms, key=len, reverse=True))


def _sanitize_coach_provider_value(value: Any, redaction_terms: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if _is_sensitive_coach_provider_key(key) or _coach_text_contains_redaction_term(
                key,
                redaction_terms,
            ):
                continue
            sanitized[key] = _sanitize_coach_provider_value(item, redaction_terms)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_coach_provider_value(item, redaction_terms) for item in value]
    if isinstance(value, str):
        return _redact_coach_provider_text(value, redaction_terms)
    return value


def _is_sensitive_coach_provider_key(key: str) -> bool:
    normalized_key = re.sub(r"[^a-z0-9]+", "_", key.casefold())
    return any(part in normalized_key for part in _COACH_SENSITIVE_KEY_PARTS)


def _coach_text_contains_redaction_term(text: str, redaction_terms: tuple[str, ...]) -> bool:
    return any(re.search(re.escape(term), text, flags=re.IGNORECASE) for term in redaction_terms)


def _redact_coach_provider_text(text: str, redaction_terms: tuple[str, ...]) -> str:
    sanitized = text
    for term in redaction_terms:
        sanitized = re.sub(
            re.escape(term),
            _COACH_PROVIDER_REDACTION,
            sanitized,
            flags=re.IGNORECASE,
        )
    return sanitized


_EXAM_STYLE_VERBS = ("请说明", "请解释", "请写", "写出", "说出", "阐述")
_EXAM_STYLE_OBJECTS = ("问诊目的", "检查目的", "查体目的", "操作目的", "申请目的")
_ACTIVE_HINT_POLICY_TRIGGER_STATES = {"preparation", "triggered"}


def _looks_like_exam_style_prompt(hint: str) -> bool:
    compact_hint = "".join(hint.split())
    return any(verb in compact_hint for verb in _EXAM_STYLE_VERBS) and any(
        target in compact_hint for target in _EXAM_STYLE_OBJECTS
    )


def _active_hint_policy_training_goal(request: CoachRequest) -> str:
    hint_policy = request.hint_context.get("hint_policy")
    if not isinstance(hint_policy, dict):
        return ""
    trigger_state = str(hint_policy.get("trigger_state") or "").strip()
    if trigger_state not in _ACTIVE_HINT_POLICY_TRIGGER_STATES:
        return ""
    return str(hint_policy.get("training_goal_hint") or "").strip()


def _policy_hint_is_overloaded(hint: str, policy_goal: str) -> bool:
    if not hint or not policy_goal:
        return False
    return len(hint) > max(100, len(policy_goal) + 40) or "本轮训练重点" in hint


def normalize_coach_response_for_request(request: CoachRequest, response: CoachResponse | dict[str, Any]) -> CoachResponse:
    normalized = normalize_coach_response(response)
    if request.prompt_kind == "skill_router":
        return normalized
    if not normalized.should_emit:
        return normalized.model_copy(update={"hint": ""})

    sanitized_hint = sanitize_coach_hint(normalized.hint, request.forbidden_terms)
    if request.prompt_kind == "socratic_hint":
        policy_training_goal = _active_hint_policy_training_goal(request)
        if policy_training_goal:
            sanitized_policy_goal = sanitize_coach_hint(policy_training_goal, request.forbidden_terms)
            if sanitized_policy_goal and (
                sanitized_policy_goal not in sanitized_hint
                or _policy_hint_is_overloaded(sanitized_hint, sanitized_policy_goal)
            ):
                sanitized_base_hint = sanitize_coach_hint(request.base_hint, request.forbidden_terms)
                sanitized_hint = (
                    sanitized_base_hint
                    if sanitized_policy_goal in sanitized_base_hint
                    and not _policy_hint_is_overloaded(sanitized_base_hint, sanitized_policy_goal)
                    else sanitized_policy_goal
                )
        elif _looks_like_exam_style_prompt(sanitized_hint):
            sanitized_hint = sanitize_coach_hint(request.base_hint, request.forbidden_terms)

    return normalized.model_copy(
        update={
            "hint": sanitized_hint,
            "trigger_kind": normalized.trigger_kind or request.prompt_kind,
        }
    )


_normalize_coach_response_for_request = normalize_coach_response_for_request


class DeterministicCoachAgent:
    def __call__(self, request: CoachRequest) -> CoachResponse:
        if request.prompt_kind == "skill_router":
            skill_selection = request.hint_context.get("skill_selection", {})
            candidate_ids = [
                str(skill_id)
                for skill_id in skill_selection.get("available_skill_ids", [])
                if str(skill_id).strip()
            ]
            conversation = request.hint_context.get("conversation", {})
            evidence_coverage = request.hint_context.get("evidence_coverage", {})
            has_student_progress = bool(
                conversation.get("asked_questions_count")
                or conversation.get("student_hypotheses")
                or evidence_coverage.get("history", {}).get("collected")
                or evidence_coverage.get("physical_exam", {}).get("collected")
                or evidence_coverage.get("physical_exam", {}).get("requested_count")
                or evidence_coverage.get("auxiliary_test", {}).get("collected")
                or evidence_coverage.get("auxiliary_test", {}).get("requested_count")
                or evidence_coverage.get("reasoning", {}).get("hypothesis_count")
            )
            if candidate_ids and has_student_progress:
                return CoachResponse(
                    should_emit=True,
                    hint="",
                    trigger_kind="skill_router",
                    selected_skill_ids=candidate_ids[:3],
                    skill_intervention_level="active",
                    skill_selection_reason="deterministic_router_selected_after_student_progress",
                )
            return CoachResponse(
                should_emit=True,
                hint="",
                trigger_kind="skill_router",
                selected_skill_ids=[],
                skill_intervention_level="none",
                skill_selection_reason="deterministic_router_keeps_skill_as_background",
            )
        if request.prompt_kind == "passive_turn_review":
            base_hint = request.base_hint.strip()
            if not base_hint:
                return CoachResponse(should_emit=False, hint="", trigger_kind="none")
            return _normalize_coach_response_for_request(
                request,
                CoachResponse(
                    should_emit=True,
                    hint=base_hint,
                    trigger_kind="passive_review",
                ),
            )
        return _normalize_coach_response_for_request(
            request,
            CoachResponse(
                should_emit=True,
                hint=request.base_hint,
                trigger_kind=request.prompt_kind,
            ),
        )


class OpenAICompatibleCoachAgent:
    def __init__(self, settings: OpenAICompatibleSettings, client: OpenAICompatibleChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or OpenAICompatibleChatClient(settings)

    def __call__(self, request: CoachRequest) -> CoachResponse:
        response = self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=_coach_provider_payload(request),
            response_model=CoachResponse,
            temperature=0.2,
        )
        return _normalize_coach_response_for_request(request, response)


class AnthropicCoachAgent:
    def __init__(self, settings: AnthropicSettings, client: AnthropicChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or AnthropicChatClient(settings)

    def __call__(self, request: CoachRequest) -> CoachResponse:
        response = self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=_coach_provider_payload(request),
            response_model=CoachResponse,
            temperature=0.2,
        )
        return _normalize_coach_response_for_request(request, response)


class GeminiCoachAgent:
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

    def __call__(self, request: CoachRequest) -> CoachResponse:
        response = call_with_api_logging(
            provider="vertex_gemini_coach" if self._settings.use_vertex else "gemini_coach",
            operation="generate_content",
            model=self._settings.model,
            endpoint="vertex://generate_content" if self._settings.use_vertex else "gemini://generate_content",
            call=lambda: self._client.models.generate_content(
                model=self._settings.model,
                contents=json.dumps(_coach_provider_payload(request), ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT_TEMPLATE,
                    response_mime_type="application/json",
                    response_schema=CoachResponse,
                    temperature=0.2,
                ),
            ),
        )
        return _normalize_coach_response_for_request(request, CoachResponse.model_validate_json(response.text))


class LazyCoachAgent:
    def __init__(self) -> None:
        self._agent_cache: RuntimeModelObjectCache[
            GeminiCoachAgent
            | OpenAICompatibleCoachAgent
            | AnthropicCoachAgent
            | DeterministicCoachAgent
        ] = RuntimeModelObjectCache()

    def __call__(self, request: CoachRequest) -> CoachResponse:
        agent = self._agent_cache.get_or_create(_create_configured_coach_agent)
        return agent(request)


def normalize_coach_response(response: CoachResponse | dict[str, Any]) -> CoachResponse:
    if isinstance(response, CoachResponse):
        return response
    return CoachResponse.model_validate(response)


def create_default_coach_agent() -> LazyCoachAgent:
    return LazyCoachAgent()


def _create_configured_coach_agent() -> (
    GeminiCoachAgent | OpenAICompatibleCoachAgent | AnthropicCoachAgent | DeterministicCoachAgent
):
    runtime_openai_settings = runtime_model_config_store.get_openai_compatible_settings()
    if runtime_openai_settings is not None:
        return OpenAICompatibleCoachAgent(runtime_openai_settings)

    runtime_anthropic_settings = runtime_model_config_store.get_anthropic_settings()
    if runtime_anthropic_settings is not None:
        return AnthropicCoachAgent(runtime_anthropic_settings)

    runtime_vertex_api_key_config = runtime_model_config_store.get_vertex_gemini_api_key_config()
    if runtime_vertex_api_key_config is not None:
        return GeminiCoachAgent(
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
        return GeminiCoachAgent(
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
        return OpenAICompatibleCoachAgent(openai_settings)

    anthropic_settings = AnthropicSettings()
    if anthropic_settings.is_configured:
        return AnthropicCoachAgent(anthropic_settings)

    settings = GeminiPatientSettings()
    if settings.use_vertex:
        vertex_api_key = settings.api_key or os.getenv("OSCE_VERTEX_API_KEY", "")
        project = settings.project or os.getenv("OSCE_VERTEX_PROJECT", "")
        location = os.getenv("OSCE_GEMINI_PATIENT_LOCATION", "") or os.getenv("OSCE_VERTEX_LOCATION", "") or settings.location
        model = os.getenv("OSCE_GEMINI_PATIENT_MODEL", "") or os.getenv("OSCE_VERTEX_MODEL", "") or settings.model
        if project or vertex_api_key:
            return GeminiCoachAgent(
                settings=settings.model_copy(
                    update={
                        "api_key": vertex_api_key,
                        "project": project,
                        "location": location,
                        "model": model,
                    }
                )
            )
        return DeterministicCoachAgent()

    api_key = settings.api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    if api_key:
        return GeminiCoachAgent(settings=settings.model_copy(update={"api_key": api_key}))
    return DeterministicCoachAgent()


def sanitize_coach_hint(hint: str, forbidden_terms: list[str]) -> str:
    sanitized = hint.strip() or "请继续按 OSCE 流程补齐证据，不要急于下结论。"
    for term in forbidden_terms:
        if term:
            sanitized = re.sub(re.escape(term), "标准诊断", sanitized, flags=re.IGNORECASE)
    for unsafe_term in ["治疗方案", "用药剂量", "手术方案", "手术"]:
        sanitized = sanitized.replace(unsafe_term, "真实处置")
    if len(sanitized) > 160:
        sanitized = f"{sanitized[:157]}..."
    return sanitized


__all__ = [
    "AnthropicCoachAgent",
    "CoachRequest",
    "CoachResponse",
    "DeterministicCoachAgent",
    "GeminiCoachAgent",
    "LazyCoachAgent",
    "OpenAICompatibleCoachAgent",
    "create_default_coach_agent",
    "normalize_coach_response",
    "normalize_coach_response_for_request",
    "sanitize_coach_hint",
]
