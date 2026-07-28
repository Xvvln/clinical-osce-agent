from __future__ import annotations

import json
import os
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.services.anthropic_chat_client import AnthropicChatClient, AnthropicSettings
from app.services.api_call_log_service import call_with_api_logging
from app.services.gemini_patient_responder import GeminiPatientSettings, _apply_process_proxy
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.runtime_model_config_store import runtime_model_config_store

SYSTEM_PROMPT_TEMPLATE = """你是 OSCE 高级训练中的受控检查结果模拟 Agent。

任务：
- 当学生自由申请的查体或辅助检查项目能被标准目录识别，或已经被自由申请路由 Agent 判定为可生成，但当前病例没有预置结果时，生成一个“训练用模拟结果”。
- 你可以参考病例私有上下文、已配置结果、学生请求和教学知识库片段，使结果与病例情境一致。

硬性边界：
- 只能输出该项目的简短结果，不得输出标准诊断名、鉴别诊断答案、治疗方案、手术方案、用药剂量或真实诊疗建议。
- 不得声称该结果是病例标准答案；它只是训练参考。
- 不得修改病例事实、rubric、评分依据或隐藏信息。
- 不要解释评分，不要告诉学生“应该诊断什么”。
- 如果证据不足，只给出保守、非决定性的结果。
- 输出中文，贴近临床报告口吻，不超过 120 个汉字。
- 只输出 JSON，字段为 result、safety_note。
"""


class ProcedureResultSimulationRequest(BaseModel):
    case_id: str
    case_title: str
    chief_complaint: str
    request_text: str
    procedure_kind: str
    procedure_code: str
    procedure_name_cn: str
    patient_context: dict[str, Any] = Field(default_factory=dict)
    configured_results: list[dict[str, str]] = Field(default_factory=list)
    retrieved_knowledge_context: list[dict[str, Any]] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)


class ProcedureResultSimulationResponse(BaseModel):
    result: str = Field(..., min_length=1, max_length=160)
    safety_note: str = Field(default="", max_length=160)


def _procedure_simulator_provider_payload(request: ProcedureResultSimulationRequest) -> dict[str, str]:
    return {
        "request_text": request.request_text,
        "procedure_kind": request.procedure_kind,
        "procedure_code": request.procedure_code,
        "procedure_name_cn": request.procedure_name_cn,
    }


class OpenAICompatibleProcedureResultSimulator:
    def __init__(self, settings: OpenAICompatibleSettings, client: OpenAICompatibleChatClient | None = None) -> None:
        self._client = client or OpenAICompatibleChatClient(settings)

    def __call__(self, request: ProcedureResultSimulationRequest) -> ProcedureResultSimulationResponse:
        return self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=_procedure_simulator_provider_payload(request),
            response_model=ProcedureResultSimulationResponse,
            temperature=0.2,
        )


class AnthropicProcedureResultSimulator:
    def __init__(self, settings: AnthropicSettings, client: AnthropicChatClient | None = None) -> None:
        self._client = client or AnthropicChatClient(settings)

    def __call__(self, request: ProcedureResultSimulationRequest) -> ProcedureResultSimulationResponse:
        return self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=_procedure_simulator_provider_payload(request),
            response_model=ProcedureResultSimulationResponse,
            temperature=0.2,
        )


class GeminiProcedureResultSimulator:
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

    def __call__(self, request: ProcedureResultSimulationRequest) -> ProcedureResultSimulationResponse:
        response = call_with_api_logging(
            provider="vertex_gemini_procedure_simulator" if self._settings.use_vertex else "gemini_procedure_simulator",
            operation="generate_content",
            model=self._settings.model,
            endpoint="vertex://generate_content" if self._settings.use_vertex else "gemini://generate_content",
            call=lambda: self._client.models.generate_content(
                model=self._settings.model,
                contents=json.dumps(_procedure_simulator_provider_payload(request), ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT_TEMPLATE,
                    response_mime_type="application/json",
                    response_schema=ProcedureResultSimulationResponse,
                    temperature=0.2,
                ),
            ),
        )
        return ProcedureResultSimulationResponse.model_validate_json(response.text)


class LazyProcedureResultSimulator:
    def __init__(self) -> None:
        self._simulator: (
            OpenAICompatibleProcedureResultSimulator
            | AnthropicProcedureResultSimulator
            | GeminiProcedureResultSimulator
            | None
        ) = None
        self._cache_key: tuple[str, ...] | None = None

    def __call__(self, request: ProcedureResultSimulationRequest) -> ProcedureResultSimulationResponse:
        cache_key = runtime_model_config_store.active_config_cache_key()
        if self._simulator is None or self._cache_key != cache_key:
            self._simulator = _create_configured_simulator()
            self._cache_key = cache_key
        if self._simulator is None:
            raise RuntimeError("procedure result simulator is not configured")
        return self._simulator(request)


def create_default_procedure_result_simulator() -> LazyProcedureResultSimulator:
    return LazyProcedureResultSimulator()


def _create_configured_simulator() -> (
    OpenAICompatibleProcedureResultSimulator | AnthropicProcedureResultSimulator | GeminiProcedureResultSimulator | None
):
    runtime_openai_settings = runtime_model_config_store.get_openai_compatible_settings()
    if runtime_openai_settings is not None:
        return OpenAICompatibleProcedureResultSimulator(runtime_openai_settings)

    runtime_anthropic_settings = runtime_model_config_store.get_anthropic_settings()
    if runtime_anthropic_settings is not None:
        return AnthropicProcedureResultSimulator(runtime_anthropic_settings)

    runtime_vertex_api_key_config = runtime_model_config_store.get_vertex_gemini_api_key_config()
    if runtime_vertex_api_key_config is not None:
        _apply_process_proxy(runtime_vertex_api_key_config.proxy_url)
        return GeminiProcedureResultSimulator(
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
        return GeminiProcedureResultSimulator(
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
        return OpenAICompatibleProcedureResultSimulator(openai_settings)

    anthropic_settings = AnthropicSettings()
    if anthropic_settings.is_configured:
        return AnthropicProcedureResultSimulator(anthropic_settings)

    settings = GeminiPatientSettings()
    _apply_process_proxy(settings.proxy_url)
    if settings.use_vertex:
        vertex_api_key = settings.api_key or os.getenv("OSCE_VERTEX_API_KEY", "")
        project = settings.project or os.getenv("OSCE_VERTEX_PROJECT", "")
        location = os.getenv("OSCE_GEMINI_PATIENT_LOCATION", "") or os.getenv("OSCE_VERTEX_LOCATION", "") or settings.location
        model = os.getenv("OSCE_GEMINI_PATIENT_MODEL", "") or os.getenv("OSCE_VERTEX_MODEL", "") or settings.model
        if project or vertex_api_key:
            return GeminiProcedureResultSimulator(
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
        return GeminiProcedureResultSimulator(settings=settings.model_copy(update={"api_key": api_key}))
    return None


__all__ = [
    "ProcedureResultSimulationRequest",
    "ProcedureResultSimulationResponse",
    "create_default_procedure_result_simulator",
]
