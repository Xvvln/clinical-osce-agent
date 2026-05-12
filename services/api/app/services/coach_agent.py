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

SYSTEM_PROMPT_TEMPLATE = """你是 OSCE 训练中的受控教学策略 Agent，只负责生成短提示来帮助学生继续训练。

硬性规则：
- 只能生成教学提示、苏格拉底式引导或下一步训练策略。
- 不得输出诊断答案、病例隐藏事实、rubric 全量、治疗方案、用药剂量或真实医疗建议。
- 不要新增医学事实；只能围绕 base_hint、pedagogy_state、clinical_reasoning_state、skill_context 和已公开对话做教学引导。
- 如果 clinical_reasoning_state 中存在 sequence_flags，应先指出训练顺序缺口，再用“为什么 / 想一想”组织反问式提示。
- 如果学生已接近提交诊断，只提醒整理证据链和排除依据，不要给出标准答案。
- 如果 prompt_kind 是 passive_turn_review，必须先判断是否真的需要打断学生；学生提出有效问诊且患者已回答时，should_emit=false 且 hint=""。
- 如果 prompt_kind 是 answer_boundary_redirect 或 safety_boundary_redirect，必须 should_emit=true，并用 base_hint 改写为教练边界提示。
- 输出中文，简洁，不超过 80 个汉字。
- 只输出 JSON，字段为 should_emit、hint、trigger_kind。
"""


class CoachRequest(BaseModel):
    case_id: str
    case_title: str
    chief_complaint: str
    stage: str
    prompt_kind: str
    base_hint: str
    prior_messages: list[dict[str, str]] = Field(default_factory=list)
    pedagogy_state: dict[str, Any] = Field(default_factory=dict)
    clinical_reasoning_state: dict[str, Any] = Field(default_factory=dict)
    skill_context: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)


class CoachResponse(BaseModel):
    should_emit: bool = True
    hint: str = Field(default="", max_length=160)
    trigger_kind: str = "manual_hint"


class DeterministicCoachAgent:
    def __call__(self, request: CoachRequest) -> CoachResponse:
        if request.prompt_kind == "passive_turn_review":
            base_hint = request.base_hint.strip()
            if not base_hint:
                return CoachResponse(should_emit=False, hint="", trigger_kind="none")
            return CoachResponse(
                should_emit=True,
                hint=sanitize_coach_hint(base_hint, request.forbidden_terms),
                trigger_kind="passive_review",
            )
        return CoachResponse(
            should_emit=True,
            hint=sanitize_coach_hint(request.base_hint, request.forbidden_terms),
            trigger_kind=request.prompt_kind,
        )


class OpenAICompatibleCoachAgent:
    def __init__(self, settings: OpenAICompatibleSettings, client: OpenAICompatibleChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or OpenAICompatibleChatClient(settings)

    def __call__(self, request: CoachRequest) -> CoachResponse:
        return self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=request.model_dump(),
            response_model=CoachResponse,
            temperature=0.2,
        )


class AnthropicCoachAgent:
    def __init__(self, settings: AnthropicSettings, client: AnthropicChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or AnthropicChatClient(settings)

    def __call__(self, request: CoachRequest) -> CoachResponse:
        return self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=request.model_dump(),
            response_model=CoachResponse,
            temperature=0.2,
        )


class GeminiCoachAgent:
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

    def __call__(self, request: CoachRequest) -> CoachResponse:
        response = self._client.models.generate_content(
            model=self._settings.model,
            contents=json.dumps(request.model_dump(), ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT_TEMPLATE,
                response_mime_type="application/json",
                response_schema=CoachResponse,
                temperature=0.2,
            ),
        )
        return CoachResponse.model_validate_json(response.text)


class LazyCoachAgent:
    def __init__(self) -> None:
        self._agent: GeminiCoachAgent | OpenAICompatibleCoachAgent | AnthropicCoachAgent | DeterministicCoachAgent | None = None
        self._cache_key: tuple[str, ...] | None = None

    def __call__(self, request: CoachRequest) -> CoachResponse:
        cache_key = runtime_model_config_store.active_config_cache_key()
        if self._agent is None or self._cache_key != cache_key:
            self._agent = _create_configured_coach_agent()
            self._cache_key = cache_key
        return self._agent(request)


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
        _apply_process_proxy(runtime_vertex_api_key_config.proxy_url)
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
        _apply_process_proxy(runtime_vertex_config.proxy_url)
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
    _apply_process_proxy(settings.proxy_url)
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
            sanitized = sanitized.replace(term, "标准诊断")
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
    "sanitize_coach_hint",
]
