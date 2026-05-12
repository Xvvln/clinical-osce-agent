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
    "ask_patient_age",
    "ask_patient_gender",
    "ask_patient_occupation",
    "ask_past_medical_history",
    "unknown_history_intent",
]

KNOWN_UNKNOWN_KINDS = [
    "social_greeting",
    "patient_identity_unclear",
    "unsupported_case_question",
    "off_topic",
    "possible_missed_medical_intent",
]

SYSTEM_PROMPT_TEMPLATE = """你是 OSCE 训练中的受控意图识别 Agent，只负责理解学生本轮输入属于哪类问诊意图。

硬性规则：
- 只能从 allowed_intents 中选择 current_intent。
- keyword_intent 只是后端关键词提示，不能直接当作最终结论；需要结合 student_message、stage 和 prior_messages 判断。
- 不得推断或输出诊断、治疗方案、用药剂量、标准答案、rubric 或病例隐藏事实。
- 如果学生询问患者年龄、性别或职业，可选择对应患者公开画像意图。
- 如果没有提出可映射的问诊问题，输出 unknown_history_intent，并同时输出 unknown_kind：
  social_greeting=问候；patient_identity_unclear=笼统问身份；unsupported_case_question=病例脚本未提供的信息；off_topic=明显偏题；possible_missed_medical_intent=疑似医学问诊但表达太宽泛或未命中意图。
- possible_missed_medical_intent 可在 possible_intents 中给出 1-4 个可能的 allowed_intents，但不能替学生决定最终事实披露。
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
    unknown_kind: str = ""
    possible_intents: list[str] = Field(default_factory=list)


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
        unknown_analysis = classify_unknown_history_message(request.student_message)
        return TurnIntentResponse(
            current_intent="unknown_history_intent",
            confidence=0.35,
            is_off_topic=bool(unknown_analysis["is_off_topic"]),
            rationale=str(unknown_analysis["rationale"]),
            unknown_kind=str(unknown_analysis["unknown_kind"]),
            possible_intents=list(unknown_analysis["possible_intents"]),
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
        self._cache_key: tuple[str, ...] | None = None

    def __call__(self, request: TurnIntentRequest) -> TurnIntentResponse:
        cache_key = runtime_model_config_store.active_config_cache_key()
        if self._agent is None or self._cache_key != cache_key:
            self._agent = _create_configured_turn_intent_agent()
            self._cache_key = cache_key
        return self._agent(request)


def normalize_turn_intent_response(response: TurnIntentResponse | dict[str, Any]) -> dict[str, Any]:
    if isinstance(response, TurnIntentResponse):
        normalized = response
    else:
        normalized = TurnIntentResponse.model_validate(response)
    if normalized.current_intent not in KNOWN_HISTORY_INTENTS:
        normalized = normalized.model_copy(update={"current_intent": "unknown_history_intent", "is_off_topic": True})
    if normalized.current_intent == "unknown_history_intent":
        update_payload: dict[str, Any] = {}
        if normalized.unknown_kind not in KNOWN_UNKNOWN_KINDS:
            update_payload["unknown_kind"] = ""
        update_payload["possible_intents"] = [
            intent
            for intent in normalized.possible_intents
            if intent in KNOWN_HISTORY_INTENTS and intent != "unknown_history_intent"
        ]
        if update_payload:
            normalized = normalized.model_copy(update=update_payload)
    elif normalized.unknown_kind or normalized.possible_intents:
        normalized = normalized.model_copy(update={"unknown_kind": "", "possible_intents": []})
    result = normalized.model_dump(mode="json")
    if result["current_intent"] != "unknown_history_intent":
        result.pop("unknown_kind", None)
        result.pop("possible_intents", None)
    return result


def classify_unknown_history_message(message: str) -> dict[str, Any]:
    normalized = message.strip().lower()
    if not normalized:
        return _unknown_analysis("unsupported_case_question", False, [], "学生输入为空或缺少可识别问诊内容。")
    if _contains_any(normalized, ["你好", "您好", "早上好", "下午好", "晚上好", "嗨", "hello", "hi"]):
        return _unknown_analysis("social_greeting", False, [], "学生在寒暄问候。")
    if _contains_any(normalized, ["身份证", "手机号", "电话号码", "微信", "qq", "住址", "详细地址", "叫什么名字", "真名"]):
        return _unknown_analysis("unsupported_case_question", False, [], "学生询问病例脚本未提供的信息。")
    if _contains_any(normalized, ["你是谁", "什么人", "你的身份", "来干嘛", "为什么来"]):
        return _unknown_analysis("patient_identity_unclear", False, [], "学生在笼统询问患者身份。")
    if _contains_any(normalized, ["游戏", "天气", "唱歌", "笑话", "电影", "电视剧", "股票", "新闻"]):
        return _unknown_analysis("off_topic", True, [], "学生输入明显偏离 OSCE 问诊。")
    if _looks_like_broad_medical_question(normalized):
        return _unknown_analysis(
            "possible_missed_medical_intent",
            False,
            _possible_intents_for_broad_medical_question(normalized),
            "学生可能在问症状，但表达过于宽泛。",
        )
    return _unknown_analysis("unsupported_case_question", False, [], "未命中当前病例可映射问诊意图。")


def _unknown_analysis(
    unknown_kind: str,
    is_off_topic: bool,
    possible_intents: list[str],
    rationale: str,
) -> dict[str, Any]:
    return {
        "unknown_kind": unknown_kind,
        "is_off_topic": is_off_topic,
        "possible_intents": possible_intents,
        "rationale": rationale,
    }


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _looks_like_broad_medical_question(text: str) -> bool:
    medical_markers = ["不舒服", "症状", "难受", "伴随", "还有", "其他", "身体", "情况", "疼", "痛"]
    question_markers = ["吗", "呢", "么", "？", "?", "有没有", "是不是"]
    return _contains_any(text, medical_markers) and _contains_any(text, question_markers)


def _possible_intents_for_broad_medical_question(text: str) -> list[str]:
    if _contains_any(text, ["不舒服", "症状", "伴随", "还有", "其他", "身体", "情况"]):
        return ["ask_associated_nausea", "ask_fever", "ask_stool", "ask_urinary"]
    if _contains_any(text, ["疼", "痛"]):
        return ["ask_location", "ask_character", "ask_severity"]
    return []


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
    "classify_unknown_history_message",
    "create_default_turn_intent_agent",
    "normalize_turn_intent_response",
]
