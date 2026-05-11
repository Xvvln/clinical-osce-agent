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

KNOWN_HISTORY_INTENTS = [
    "ask_onset",
    "ask_location",
    "ask_migration",
    "ask_character",
    "ask_severity",
    "ask_fever",
    "ask_urinary",
    "ask_stool",
    "ask_associated_nausea",
    "ask_allergy",
    "ask_diet",
    "ask_travel",
    "ask_personal",
    "ask_family",
    "ask_concern",
    "ask_expectation",
    "ask_idea",
    "ask_past_medical_history",
    "unknown_history_intent",
]

SYSTEM_PROMPT_TEMPLATE = """你是 OSCE 训练中的受控意图识别 Agent，只负责理解学生本轮输入属于哪类问诊意图。

硬性规则：
- 只能从 allowed_intents 中选择 current_intent。
- keyword_intent 只是后端关键词提示，不能直接当作最终结论；需要结合 student_message、stage 和 prior_messages 判断。
- 不得推断或输出诊断、治疗方案、用药剂量、标准答案、rubric 或病例隐藏事实。
- 如果学生问候、闲聊、偏题、问“你是谁”或没有提出可映射的问诊问题，输出 unknown_history_intent，并将 is_off_topic 设为 true。
- rationale 用一句中文说明判断依据，不超过 40 个汉字。
- 只输出 JSON。
"""


class TurnIntentRequest(BaseModel):
    case_id: str
    case_title: str
    chief_complaint: str
    stage: str
    student_message: str
    keyword_intent: str
    prior_messages: list[dict[str, str]] = Field(default_factory=list)
    allowed_intents: list[str] = Field(default_factory=lambda: list(KNOWN_HISTORY_INTENTS))


class TurnIntentResponse(BaseModel):
    current_intent: str
    confidence: float = Field(default=0.5, ge=0, le=1)
    is_off_topic: bool = False
    rationale: str = ""


class DeterministicTurnIntentAgent:
    def __call__(self, request: TurnIntentRequest) -> TurnIntentResponse:
        keyword_intent = request.keyword_intent
        if keyword_intent in request.allowed_intents and keyword_intent != "unknown_history_intent":
            return TurnIntentResponse(
                current_intent=keyword_intent,
                confidence=0.9,
                is_off_topic=False,
                rationale="命中后端确定性问诊意图提示。",
            )
        return TurnIntentResponse(
            current_intent="unknown_history_intent",
            confidence=0.35,
            is_off_topic=True,
            rationale="未命中当前病例问诊意图提示，作为患者身份或训练目标引导处理。",
        )


class OpenAICompatibleTurnIntentAgent:
    def __init__(self, settings: OpenAICompatibleSettings, client: OpenAICompatibleChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or OpenAICompatibleChatClient(settings)

    def __call__(self, request: TurnIntentRequest) -> TurnIntentResponse:
        return self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=request.model_dump(),
            response_model=TurnIntentResponse,
            temperature=0.0,
        )


class AnthropicTurnIntentAgent:
    def __init__(self, settings: AnthropicSettings, client: AnthropicChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or AnthropicChatClient(settings)

    def __call__(self, request: TurnIntentRequest) -> TurnIntentResponse:
        return self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=request.model_dump(),
            response_model=TurnIntentResponse,
            temperature=0.0,
        )


class GeminiTurnIntentAgent:
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

    def __call__(self, request: TurnIntentRequest) -> TurnIntentResponse:
        response = self._client.models.generate_content(
            model=self._settings.model,
            contents=json.dumps(request.model_dump(), ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT_TEMPLATE,
                response_mime_type="application/json",
                response_schema=TurnIntentResponse,
                temperature=0.0,
            ),
        )
        return TurnIntentResponse.model_validate_json(response.text)


class LazyTurnIntentAgent:
    def __init__(self) -> None:
        self._agent: (
            GeminiTurnIntentAgent
            | OpenAICompatibleTurnIntentAgent
            | AnthropicTurnIntentAgent
            | DeterministicTurnIntentAgent
            | None
        ) = None

    def __call__(self, request: TurnIntentRequest) -> TurnIntentResponse:
        if self._agent is None:
            self._agent = _create_configured_turn_intent_agent()
        return self._agent(request)


def normalize_turn_intent_response(response: TurnIntentResponse | dict[str, Any]) -> dict[str, Any]:
    if isinstance(response, TurnIntentResponse):
        normalized = response
    else:
        normalized = TurnIntentResponse.model_validate(response)
    if normalized.current_intent not in KNOWN_HISTORY_INTENTS:
        normalized = normalized.model_copy(update={"current_intent": "unknown_history_intent", "is_off_topic": True})
    return normalized.model_dump(mode="json")


def create_default_turn_intent_agent() -> LazyTurnIntentAgent:
    return LazyTurnIntentAgent()


def _create_configured_turn_intent_agent() -> (
    GeminiTurnIntentAgent | OpenAICompatibleTurnIntentAgent | AnthropicTurnIntentAgent | DeterministicTurnIntentAgent
):
    runtime_openai_settings = runtime_model_config_store.get_openai_compatible_settings()
    if runtime_openai_settings is not None:
        return OpenAICompatibleTurnIntentAgent(runtime_openai_settings)

    runtime_anthropic_settings = runtime_model_config_store.get_anthropic_settings()
    if runtime_anthropic_settings is not None:
        return AnthropicTurnIntentAgent(runtime_anthropic_settings)

    runtime_vertex_api_key_config = runtime_model_config_store.get_vertex_gemini_api_key_config()
    if runtime_vertex_api_key_config is not None:
        _apply_process_proxy(runtime_vertex_api_key_config.proxy_url)
        return GeminiTurnIntentAgent(
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
        return GeminiTurnIntentAgent(
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
        return OpenAICompatibleTurnIntentAgent(openai_settings)

    anthropic_settings = AnthropicSettings()
    if anthropic_settings.is_configured:
        return AnthropicTurnIntentAgent(anthropic_settings)

    settings = GeminiPatientSettings()
    _apply_process_proxy(settings.proxy_url)
    if settings.use_vertex:
        vertex_api_key = settings.api_key or os.getenv("OSCE_VERTEX_API_KEY", "")
        project = settings.project or os.getenv("OSCE_VERTEX_PROJECT", "")
        location = os.getenv("OSCE_GEMINI_PATIENT_LOCATION", "") or os.getenv("OSCE_VERTEX_LOCATION", "") or settings.location
        model = os.getenv("OSCE_GEMINI_PATIENT_MODEL", "") or os.getenv("OSCE_VERTEX_MODEL", "") or settings.model
        if project or vertex_api_key:
            return GeminiTurnIntentAgent(
                settings=settings.model_copy(
                    update={
                        "api_key": vertex_api_key,
                        "project": project,
                        "location": location,
                        "model": model,
                    }
                )
            )
        return DeterministicTurnIntentAgent()

    api_key = settings.api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    if api_key:
        return GeminiTurnIntentAgent(settings=settings.model_copy(update={"api_key": api_key}))
    return DeterministicTurnIntentAgent()


__all__ = [
    "AnthropicTurnIntentAgent",
    "KNOWN_HISTORY_INTENTS",
    "DeterministicTurnIntentAgent",
    "GeminiTurnIntentAgent",
    "LazyTurnIntentAgent",
    "OpenAICompatibleTurnIntentAgent",
    "TurnIntentRequest",
    "TurnIntentResponse",
    "create_default_turn_intent_agent",
    "normalize_turn_intent_response",
]
