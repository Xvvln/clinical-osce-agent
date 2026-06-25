from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.anthropic_chat_client import AnthropicChatClient, AnthropicSettings
from app.services.api_call_log_service import api_call_log_store
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.patient_emotion import infer_patient_emotion, normalize_patient_emotion
from app.services.runtime_model_config_store import runtime_model_config_store

PROJECT_ROOT = Path(__file__).resolve().parents[4]

SYSTEM_PROMPT_TEMPLATE = """你是 OSCE 训练中的受控对话回复层，负责把 canonical_answer 改写成自然、简短的 OSCE 训练回复。

硬性规则：
- patient_private_context 是完整但受控的标准化病人私有上下文，只用于保持身份、语气和病史一致，不得整段复述。
- answerable_fact_candidates 是本轮允许披露的病例事实；只能表达 canonical_answer 和 answerable_fact_candidates 中已经给出的事实，不得新增症状、检查、诊断、治疗或医学解释。
- revealed_fact_ids 是此前或本轮已经披露给学生的事实编号；dialogue_context 是最近对话、已问问题和本轮意图摘要，只用于保持上下文连贯。
- dialogue_context.patient_affect_state 和 dialogue_context.student_affect_response 只用于决定患者语气是否焦虑、困惑、痛苦、受挫或稍微安心；它们只能影响语气，不能新增病例事实、诊断、检查结果、治疗承诺或标准答案。
- 可以参考 dialogue_context 判断学生是否在延续前文、追问同一主题或切换主题，但仍只能表达 canonical_answer 和 answerable_fact_candidates。
- 输出 JSON 必须包含 reply、emotion 和 fact_ids_used；fact_ids_used 只能填写本轮 reply 实际表达过、且存在于 answerable_fact_candidates 的 fact_id。
- emotion 只描述患者当前可见情绪，可用担忧、焦虑、痛苦、困惑、犹豫、欣慰等短标签；没有明显情绪时留空或填“平静”。emotion 不得新增病例事实。
- 如果 current_intents 或 answerable_fact_candidates 显示学生一次问了多个明确问诊点，必须逐一覆盖所有 answerable_fact_candidates，不要只回答第一个；这种多事实回答可用 2-3 个短句。
- forbidden_context 中的诊断、rubric、治疗、剂量、处置边界均不得泄露。
- 不得主动说出 forbidden_terms 中的任何词。
- 语气要像真实来就诊的患者，不要像病历摘要、教科书或医生交班。
- 可以把医学化表达改成生活化表达，但不能改变事实：例如“转移性右下腹痛”可说成“肚子疼，后来右下腹更明显”，“低热”可说成“有点发热”。
- 不要照抄 chief_complaint 或 case_title 里的医学化表述，优先围绕 canonical_answer 作答。
- 如果 canonical_answer 表示病例未提供信息，就只表达“不清楚/没被告知/不太确定”的患者口吻。
- 不要主动引导学生下一步该问什么，不说“你可以继续问”“建议你”“应该先问”。
- 如果 turn_policy 是 answer_boundary_redirect 或 safety_boundary_redirect，用教学边界口吻提醒继续按 OSCE 流程训练，不要扮演真实医生给建议。
- 回答必须是第一人称患者语气，中文，简短；单事实不超过 80 个汉字，多事实不超过 140 个汉字。
- 不输出用药剂量、治疗方案、手术方案或处置建议。
"""


class PatientResponderRequest(BaseModel):
    case_id: str
    case_title: str
    chief_complaint: str
    student_message: str
    current_intents: list[str] = Field(default_factory=list)
    canonical_answer: str
    revealed_fact_id: str | None = None
    revealed_fact_ids: list[str] = Field(default_factory=list)
    patient_private_context: dict[str, Any] = Field(default_factory=dict)
    answerable_fact_candidates: list[dict[str, Any]] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    forbidden_context: dict[str, Any] = Field(default_factory=dict)
    prior_messages: list[dict[str, str]] = Field(default_factory=list)
    dialogue_context: dict[str, Any] = Field(default_factory=dict)
    turn_policy: str = "history_fact_disclosure"
    deterministic_hints: dict[str, Any] = Field(default_factory=dict)


class PatientResponderResponse(BaseModel):
    reply: str = Field(..., min_length=1, max_length=180)
    emotion: str = Field(default="", max_length=20)
    fact_ids_used: list[str] = Field(default_factory=list)


class PatientResponderOutput(BaseModel):
    reply: str = Field(..., min_length=1, max_length=180)
    emotion: str = Field(default="", max_length=20)
    fact_ids_used: list[str] = Field(default_factory=list)


class GeminiPatientSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OSCE_GEMINI_PATIENT_",
        env_file=(PROJECT_ROOT / ".env", ".env"),
        extra="ignore",
    )

    api_key: str = ""
    use_vertex: bool = False
    project: str = ""
    location: str = "global"
    model: str = "gemini-3.1-pro-preview"
    proxy_url: str = "http://127.0.0.1:7897"
    temperature: float = 0.4


class GeminiPatientResponder:
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

    def __call__(self, request: PatientResponderRequest) -> PatientResponderOutput:
        provider = "vertex_gemini_patient" if self._settings.use_vertex else "gemini_patient"
        started_at = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self._settings.model,
                contents=json.dumps(request.model_dump(), ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT_TEMPLATE,
                    response_mime_type="application/json",
                    response_schema=PatientResponderResponse,
                    temperature=self._settings.temperature,
                ),
            )
        except Exception as exc:
            api_call_log_store.record(
                provider=provider,
                operation="generate_content",
                model=self._settings.model,
                endpoint="vertex://generate_content" if self._settings.use_vertex else "gemini://generate_content",
                success=False,
                duration_ms=(time.perf_counter() - started_at) * 1000,
                error=exc,
            )
            raise
        api_call_log_store.record(
            provider=provider,
            operation="generate_content",
            model=self._settings.model,
            endpoint="vertex://generate_content" if self._settings.use_vertex else "gemini://generate_content",
            success=True,
            duration_ms=(time.perf_counter() - started_at) * 1000,
        )
        return _validated_patient_reply(
            PatientResponderResponse.model_validate_json(response.text),
            request,
        )


class OpenAICompatiblePatientResponder:
    def __init__(self, settings: OpenAICompatibleSettings, client: OpenAICompatibleChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or OpenAICompatibleChatClient(settings)

    def __call__(self, request: PatientResponderRequest) -> PatientResponderOutput:
        response = self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=request.model_dump(),
            response_model=PatientResponderResponse,
            temperature=0.4,
        )
        return _validated_patient_reply(response, request)


class AnthropicPatientResponder:
    def __init__(self, settings: AnthropicSettings, client: AnthropicChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or AnthropicChatClient(settings)

    def __call__(self, request: PatientResponderRequest) -> PatientResponderOutput:
        response = self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=request.model_dump(),
            response_model=PatientResponderResponse,
            temperature=0.4,
        )
        return _validated_patient_reply(response, request)


class DeterministicPatientResponder:
    def __call__(self, request: PatientResponderRequest) -> PatientResponderOutput:
        reply = request.canonical_answer.strip() or "这个问题我不太确定，或者病例中没有提供相关信息。"
        for term in request.forbidden_terms:
            if term:
                reply = reply.replace(term, "相关诊断")
        if len(reply) > 180:
            reply = f"{reply[:177]}..."
        _assert_no_forbidden_terms(reply, request.forbidden_terms)
        return PatientResponderOutput(reply=reply, emotion=infer_patient_emotion(reply))


class LazyGeminiPatientResponder:
    def __init__(self) -> None:
        self._responder: GeminiPatientResponder | OpenAICompatiblePatientResponder | AnthropicPatientResponder | DeterministicPatientResponder | None = None
        self._cache_key: tuple[str, ...] | None = None

    def __call__(self, request: PatientResponderRequest) -> PatientResponderOutput:
        cache_key = runtime_model_config_store.active_config_cache_key()
        if self._responder is None or self._cache_key != cache_key:
            self._responder = _create_configured_responder()
            self._cache_key = cache_key
        try:
            return self._responder(request)
        except (RuntimeError, ValidationError, ValueError):
            # Only model-output contract failures fall back here. Provider connectivity
            # and authentication errors should still surface to the API caller.
            return DeterministicPatientResponder()(request)


def create_default_gemini_patient_responder() -> LazyGeminiPatientResponder:
    return LazyGeminiPatientResponder()


def _create_configured_responder() -> GeminiPatientResponder | OpenAICompatiblePatientResponder | AnthropicPatientResponder | DeterministicPatientResponder:
    runtime_openai_settings = runtime_model_config_store.get_openai_compatible_settings()
    if runtime_openai_settings is not None:
        return OpenAICompatiblePatientResponder(runtime_openai_settings)

    runtime_anthropic_settings = runtime_model_config_store.get_anthropic_settings()
    if runtime_anthropic_settings is not None:
        return AnthropicPatientResponder(runtime_anthropic_settings)

    runtime_vertex_api_key_config = runtime_model_config_store.get_vertex_gemini_api_key_config()
    if runtime_vertex_api_key_config is not None:
        _apply_process_proxy(runtime_vertex_api_key_config.proxy_url)
        return GeminiPatientResponder(
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
        return GeminiPatientResponder(
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
        return OpenAICompatiblePatientResponder(openai_settings)

    anthropic_settings = AnthropicSettings()
    if anthropic_settings.is_configured:
        return AnthropicPatientResponder(anthropic_settings)

    settings = GeminiPatientSettings()
    _apply_process_proxy(settings.proxy_url)

    if settings.use_vertex:
        vertex_api_key = settings.api_key or os.getenv("OSCE_VERTEX_API_KEY", "")
        project = settings.project or os.getenv("OSCE_VERTEX_PROJECT", "")
        location = os.getenv("OSCE_GEMINI_PATIENT_LOCATION", "") or os.getenv("OSCE_VERTEX_LOCATION", "") or settings.location
        model = os.getenv("OSCE_GEMINI_PATIENT_MODEL", "") or os.getenv("OSCE_VERTEX_MODEL", "") or settings.model
        if not project and not vertex_api_key:
            raise RuntimeError(
                "未配置 Vertex AI 鉴权，需设置 OSCE_GEMINI_PATIENT_PROJECT/OSCE_VERTEX_PROJECT 走 ADC，"
                "或设置 OSCE_GEMINI_PATIENT_API_KEY/OSCE_VERTEX_API_KEY 走 Vertex API Key。"
            )
        return GeminiPatientResponder(
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
    if not api_key:
        return DeterministicPatientResponder()
    return GeminiPatientResponder(settings=settings.model_copy(update={"api_key": api_key}))


def _assert_no_forbidden_terms(reply: str, forbidden_terms: list[str]) -> None:
    leaked_terms = [term for term in forbidden_terms if term and term in reply]
    if leaked_terms:
        raise RuntimeError(f"标准化病人回答包含禁止泄露词：{leaked_terms}")


def _validated_patient_reply(response: PatientResponderResponse, request: PatientResponderRequest) -> PatientResponderOutput:
    reply = response.reply.strip()
    _assert_no_forbidden_terms(reply, request.forbidden_terms)
    _assert_used_fact_ids_are_answerable(response.fact_ids_used, request.answerable_fact_candidates)
    _assert_multi_intent_fact_coverage(response.fact_ids_used, request)
    emotion = normalize_patient_emotion(response.emotion) or infer_patient_emotion(reply)
    return PatientResponderOutput(reply=reply, emotion=emotion, fact_ids_used=list(response.fact_ids_used))


def _assert_used_fact_ids_are_answerable(
    fact_ids_used: list[str],
    answerable_fact_candidates: list[dict[str, Any]],
) -> None:
    if not fact_ids_used:
        return
    allowed_fact_ids = {
        str(candidate.get("fact_id"))
        for candidate in answerable_fact_candidates
        if isinstance(candidate, dict) and candidate.get("fact_id")
    }
    unauthorized_fact_ids = [fact_id for fact_id in fact_ids_used if fact_id not in allowed_fact_ids]
    if unauthorized_fact_ids:
        raise RuntimeError(f"标准化病人回答声明使用了未授权病例事实：{unauthorized_fact_ids}")


def _assert_multi_intent_fact_coverage(fact_ids_used: list[str], request: PatientResponderRequest) -> None:
    if len(request.current_intents) <= 1:
        return
    expected_fact_ids = [
        str(candidate.get("fact_id"))
        for candidate in request.answerable_fact_candidates
        if isinstance(candidate, dict) and candidate.get("fact_id")
    ]
    if len(expected_fact_ids) <= 1:
        return
    missing_fact_ids = [fact_id for fact_id in expected_fact_ids if fact_id not in set(fact_ids_used)]
    if missing_fact_ids:
        raise RuntimeError(f"标准化病人回答未覆盖本轮多个问诊事实：{missing_fact_ids}")


def _apply_process_proxy(proxy_url: str) -> None:
    if not proxy_url.strip().lower() or proxy_url.strip().lower() in {"direct", "none", "false", "off", "no"}:
        return
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ["ALL_PROXY"] = proxy_url


__all__ = [
    "AnthropicPatientResponder",
    "DeterministicPatientResponder",
    "GeminiPatientResponder",
    "GeminiPatientSettings",
    "OpenAICompatiblePatientResponder",
    "PatientResponderOutput",
    "PatientResponderRequest",
    "PatientResponderResponse",
    "create_default_gemini_patient_responder",
]
