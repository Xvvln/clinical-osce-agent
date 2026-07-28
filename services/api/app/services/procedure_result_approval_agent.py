from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

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
from app.services.model_call_policy import (
    ModelProviderPolicyError,
    call_google_text_generate_content,
)
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.runtime_model_object_cache import RuntimeModelObjectCache

PROCEDURE_RESULT_APPROVAL_AGENT_ID = "procedure_result_approval_agent"

SYSTEM_PROMPT_TEMPLATE = """你是 OSCE 高级训练中的检查结果审批 Agent。

任务：
- 审核另一个 Agent 生成的“训练用模拟查体/辅助检查结果”是否可展示给学生。
- 你只做安全与教学边界审查，不参与评分，不改病例标准事实，不生成标准答案。

必须批准的条件：
- 结果只描述该项目本身的检查所见。
- 没有泄露标准诊断名、鉴别诊断答案、治疗方案、手术方案、用药剂量或真实诊疗建议。
- 没有声称这是病例标准答案、rubric 依据或评分证据。

如有问题：
- 如果只需轻微改写，decision 输出 revise，并在 revised_result 给出改写后的检查结果。
- 如果无法安全改写，decision 输出 blocked。

输出要求：
- 只输出 JSON。
- decision 只能为 approved、revise 或 blocked。
- revised_result 只有在 revise 时填写；approved 或 blocked 时留空。
- rationale 用一句中文说明。
"""


class ProcedureResultApprovalRequest(BaseModel):
    case_id: str
    case_title: str
    chief_complaint: str
    request_text: str
    procedure_kind: str
    procedure_code: str
    procedure_name_cn: str
    simulated_result: str
    source_context_references: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)


class ProcedureResultApprovalResponse(BaseModel):
    agent_id: str = PROCEDURE_RESULT_APPROVAL_AGENT_ID
    decision: Literal["approved", "revise", "blocked"]
    approval_mode: str = "llm_review"
    rationale: str = Field(default="", max_length=240)
    safety_issues: list[str] = Field(default_factory=list)
    revised_result: str = Field(default="", max_length=180)


def _procedure_approval_provider_payload(request: ProcedureResultApprovalRequest) -> dict[str, str]:
    return {
        "request_text": request.request_text,
        "procedure_kind": request.procedure_kind,
        "procedure_code": request.procedure_code,
        "procedure_name_cn": request.procedure_name_cn,
        "simulated_result": request.simulated_result,
    }


def _approval_provider_unavailable_response() -> ProcedureResultApprovalResponse:
    return ProcedureResultApprovalResponse(
        decision="blocked",
        approval_mode="llm_error_fail_closed",
        rationale="审批模型不可用，已按安全默认值阻断模拟结果。",
        safety_issues=["approval_agent_unavailable"],
    )


class DeterministicProcedureResultApprovalAgent:
    def __call__(self, request: ProcedureResultApprovalRequest) -> ProcedureResultApprovalResponse:
        safety_issues = _detect_simulated_result_safety_issues(request)
        if safety_issues:
            return ProcedureResultApprovalResponse(
                decision="blocked",
                approval_mode="deterministic_safety_gate",
                rationale="模拟结果包含受保护内容，已阻断展示。",
                safety_issues=safety_issues,
            )
        return ProcedureResultApprovalResponse(
            decision="approved",
            approval_mode="deterministic_safety_gate",
            rationale="结果仅作为高级训练补充检查结果展示，不进入评分。",
            safety_issues=[],
        )


def _local_approval_safety_block(
    request: ProcedureResultApprovalRequest,
) -> ProcedureResultApprovalResponse | None:
    review = DeterministicProcedureResultApprovalAgent()(request)
    return review if review.decision == "blocked" else None


class OpenAICompatibleProcedureResultApprovalAgent:
    def __init__(self, settings: OpenAICompatibleSettings, client: OpenAICompatibleChatClient | None = None) -> None:
        self._client = client or OpenAICompatibleChatClient(settings)

    def __call__(self, request: ProcedureResultApprovalRequest) -> ProcedureResultApprovalResponse:
        local_block = _local_approval_safety_block(request)
        if local_block is not None:
            return local_block
        try:
            return self._client.complete_json(
                system_prompt=SYSTEM_PROMPT_TEMPLATE,
                payload=_procedure_approval_provider_payload(request),
                response_model=ProcedureResultApprovalResponse,
                temperature=0.0,
            )
        except ModelProviderPolicyError:
            raise
        except Exception:
            return _approval_provider_unavailable_response()


class AnthropicProcedureResultApprovalAgent:
    def __init__(self, settings: AnthropicSettings, client: AnthropicChatClient | None = None) -> None:
        self._client = client or AnthropicChatClient(settings)

    def __call__(self, request: ProcedureResultApprovalRequest) -> ProcedureResultApprovalResponse:
        local_block = _local_approval_safety_block(request)
        if local_block is not None:
            return local_block
        try:
            return self._client.complete_json(
                system_prompt=SYSTEM_PROMPT_TEMPLATE,
                payload=_procedure_approval_provider_payload(request),
                response_model=ProcedureResultApprovalResponse,
                temperature=0.0,
            )
        except ModelProviderPolicyError:
            raise
        except Exception:
            return _approval_provider_unavailable_response()


class GeminiProcedureResultApprovalAgent:
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

    def __call__(self, request: ProcedureResultApprovalRequest) -> ProcedureResultApprovalResponse:
        local_block = _local_approval_safety_block(request)
        if local_block is not None:
            return local_block
        try:
            return call_with_api_logging(
                provider="vertex_gemini_procedure_approval" if self._settings.use_vertex else "gemini_procedure_approval",
                operation="generate_content",
                model=self._settings.model,
                endpoint="vertex://generate_content" if self._settings.use_vertex else "gemini://generate_content",
                call=lambda: call_google_text_generate_content(
                    client=self._client,
                    model=self._settings.model,
                    contents=json.dumps(_procedure_approval_provider_payload(request), ensure_ascii=False),
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT_TEMPLATE,
                        response_mime_type="application/json",
                        response_schema=ProcedureResultApprovalResponse,
                        temperature=0.0,
                    ),
                ),
                result_parser=lambda response: ProcedureResultApprovalResponse.model_validate_json(
                    response.text
                ),
            )
        except ModelProviderPolicyError:
            raise
        except Exception:
            return _approval_provider_unavailable_response()


class LazyProcedureResultApprovalAgent:
    def __init__(self) -> None:
        self._agent_cache: RuntimeModelObjectCache[
            OpenAICompatibleProcedureResultApprovalAgent
            | AnthropicProcedureResultApprovalAgent
            | GeminiProcedureResultApprovalAgent
            | None
        ] = RuntimeModelObjectCache()
        self._deterministic_agent = DeterministicProcedureResultApprovalAgent()

    def __call__(self, request: ProcedureResultApprovalRequest) -> ProcedureResultApprovalResponse:
        local_review = self._deterministic_agent(request)
        if local_review.decision == "blocked":
            return local_review
        try:
            agent = self._agent_cache.get_or_create(_create_configured_approval_agent)
            if agent is None:
                return local_review
            return agent(request)
        except ModelProviderPolicyError:
            raise
        except Exception:
            return _approval_provider_unavailable_response()


def create_default_procedure_result_approval_agent() -> LazyProcedureResultApprovalAgent:
    return LazyProcedureResultApprovalAgent()


def _create_configured_approval_agent() -> (
    OpenAICompatibleProcedureResultApprovalAgent | AnthropicProcedureResultApprovalAgent | GeminiProcedureResultApprovalAgent | None
):
    runtime_openai_settings = runtime_model_config_store.get_openai_compatible_settings()
    if runtime_openai_settings is not None:
        return OpenAICompatibleProcedureResultApprovalAgent(runtime_openai_settings)

    runtime_anthropic_settings = runtime_model_config_store.get_anthropic_settings()
    if runtime_anthropic_settings is not None:
        return AnthropicProcedureResultApprovalAgent(runtime_anthropic_settings)

    runtime_vertex_api_key_config = runtime_model_config_store.get_vertex_gemini_api_key_config()
    if runtime_vertex_api_key_config is not None:
        return GeminiProcedureResultApprovalAgent(
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
        return GeminiProcedureResultApprovalAgent(
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
        return OpenAICompatibleProcedureResultApprovalAgent(openai_settings)

    anthropic_settings = AnthropicSettings()
    if anthropic_settings.is_configured:
        return AnthropicProcedureResultApprovalAgent(anthropic_settings)

    settings = GeminiPatientSettings()
    if settings.use_vertex:
        vertex_api_key = settings.api_key or os.getenv("OSCE_VERTEX_API_KEY", "")
        project = settings.project or os.getenv("OSCE_VERTEX_PROJECT", "")
        location = os.getenv("OSCE_GEMINI_PATIENT_LOCATION", "") or os.getenv("OSCE_VERTEX_LOCATION", "") or settings.location
        model = os.getenv("OSCE_GEMINI_PATIENT_MODEL", "") or os.getenv("OSCE_VERTEX_MODEL", "") or settings.model
        if project or vertex_api_key:
            return GeminiProcedureResultApprovalAgent(
                settings=settings.model_copy(
                    update={
                        "api_key": vertex_api_key,
                        "project": project,
                        "location": location,
                        "model": model,
                    }
                )
            )
        return None

    api_key = settings.api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    if api_key:
        return GeminiProcedureResultApprovalAgent(settings=settings.model_copy(update={"api_key": api_key}))
    return None


def _detect_simulated_result_safety_issues(request: ProcedureResultApprovalRequest) -> list[str]:
    result_text = request.simulated_result
    issues: list[str] = []
    for forbidden_term in request.forbidden_terms:
        if forbidden_term and re.search(re.escape(forbidden_term), result_text, flags=re.IGNORECASE):
            issues.append(f"包含受保护词：{forbidden_term}")
    for forbidden_term in ["治疗方案", "手术方案", "用药剂量", "处方", "标准诊断", "标准答案"]:
        if forbidden_term in result_text:
            issues.append(f"包含禁止展示内容：{forbidden_term}")
    return issues


__all__ = [
    "PROCEDURE_RESULT_APPROVAL_AGENT_ID",
    "ProcedureResultApprovalRequest",
    "ProcedureResultApprovalResponse",
    "create_default_procedure_result_approval_agent",
]
