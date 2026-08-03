from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.anthropic_chat_client import AnthropicChatClient, AnthropicSettings
from app.services.api_call_log_service import call_with_api_logging
from app.services.google_genai_http_options import (
    build_google_genai_http_options,
    require_direct_runtime_vertex_adc_proxy,
)
from app.services.model_context_window import (
    PROVIDER_DIALOGUE_ROLES,
    bounded_provider_messages,
)
from app.services.model_call_policy import (
    call_google_text_generate_content,
)
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.patient_emotion import infer_patient_emotion, normalize_patient_emotion
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.runtime_model_object_cache import RuntimeModelObjectCache

PROJECT_ROOT = Path(__file__).resolve().parents[4]

MAX_PATIENT_PROVIDER_PAYLOAD_BYTES = 64 * 1024
PATIENT_PROVIDER_ENVELOPE_RESERVE_BYTES = 8 * 1024
PATIENT_PROVIDER_CONTENT_BUDGET_BYTES = (
    MAX_PATIENT_PROVIDER_PAYLOAD_BYTES - PATIENT_PROVIDER_ENVELOPE_RESERVE_BYTES
)
MAX_PATIENT_PROVIDER_FACT_CANDIDATES = 12
MAX_PATIENT_PROVIDER_CANONICAL_BYTES = 8 * 1024
MAX_PATIENT_PROVIDER_FACT_CANONICAL_BYTES = 1 * 1024
MAX_PATIENT_PROVIDER_FACT_VARIANTS = 2
MAX_PATIENT_PROVIDER_FACT_VARIANT_BYTES = 384

SYSTEM_PROMPT_TEMPLATE = """你是 OSCE 训练中的受控对话回复层，负责把 canonical_answer 或 answerable_fact_candidates 改写成自然、简短的 OSCE 训练回复。

硬性规则：
- answerable_fact_candidates 是本轮允许披露的病例事实；只能表达 canonical_answer 和 answerable_fact_candidates 中已经给出的事实，不得新增症状、检查、诊断、治疗或医学解释。
- answerable_fact_candidates 非空时，以其中逐条给出的 canonical_answer 为准；顶层 canonical_answer 会留空，以免重复传输同一事实。
- answerable_fact_candidates 中的 fact_id 是本轮临时令牌，不是病例内部编号；fact_ids_used 只能回传实际使用的临时令牌。
- dialogue_context 是最近已可见对话、已问问题和本轮意图摘要，只用于保持上下文连贯。
- dialogue_context.patient_affect_state 和 dialogue_context.student_affect_response 只用于决定患者语气是否焦虑、困惑、痛苦、受挫或稍微安心；它们只能影响语气，不能新增病例事实、诊断、检查结果、治疗承诺或标准答案。
- role_skill_policy 是已批准 Skill 对患者角色的去标识化表达投影；它只能影响语气、当前情绪的可感知度和对沟通行为的自然回应，不能选择、补写或改变任何病例事实。
- role_skill_policy.active=true 时，只在 answerable_fact_candidates 和 patient_affect_state 确实支持时应用 practice_focus；不得为了完成 Skill 而虚构担忧、情绪、生活影响或同意结果。
- 可以参考 dialogue_context 判断学生是否在延续前文、追问同一主题或切换主题，但仍只能表达 canonical_answer 和 answerable_fact_candidates。
- 输出 JSON 必须包含 reply、emotion 和 fact_ids_used；fact_ids_used 只能填写本轮 reply 实际表达过、且存在于 answerable_fact_candidates 的 fact_id。
- emotion 只描述患者当前可见情绪，可用担忧、焦虑、痛苦、困惑、犹豫、欣慰等短标签；没有明显情绪时留空或填“平静”。emotion 不得新增病例事实。
- 如果 current_intents 或 answerable_fact_candidates 显示学生一次问了多个明确问诊点，必须逐一覆盖所有 answerable_fact_candidates，不要只回答第一个；这种多事实回答可用 2-3 个短句。
- 不得输出标准诊断、rubric、治疗、剂量或处置建议。
- 语气要像真实来就诊的患者，不要像病历摘要、教科书或医生交班。
- 可以把医学化表达改成生活化表达，但不能改变事实：例如“转移性右下腹痛”可说成“肚子疼，后来右下腹更明显”，“低热”可说成“有点发热”。
- 不要照抄 chief_complaint 或 case_title 里的医学化表述；候选非空时围绕候选中的 canonical_answer 作答，否则围绕顶层 canonical_answer 作答。
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
    protected_fact_texts: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    forbidden_context: dict[str, Any] = Field(default_factory=dict)
    prior_messages: list[dict[str, str]] = Field(default_factory=list)
    dialogue_context: dict[str, Any] = Field(default_factory=dict)
    turn_policy: str = "history_fact_disclosure"
    deterministic_hints: dict[str, Any] = Field(default_factory=dict)
    role_skill_policy: dict[str, Any] = Field(default_factory=dict)


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

    def __call__(self, request: PatientResponderRequest) -> PatientResponderOutput:
        provider = "vertex_gemini_patient" if self._settings.use_vertex else "gemini_patient"
        provider_payload, provider_fact_id_map = _build_patient_provider_payload(request)
        return call_with_api_logging(
            provider=provider,
            operation="generate_content",
            model=self._settings.model,
            endpoint="vertex://generate_content" if self._settings.use_vertex else "gemini://generate_content",
            call=lambda: call_google_text_generate_content(
                client=self._client,
                model=self._settings.model,
                contents=json.dumps(
                    provider_payload,
                    ensure_ascii=False,
                ),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT_TEMPLATE,
                    response_mime_type="application/json",
                    response_schema=PatientResponderResponse,
                    temperature=self._settings.temperature,
                ),
            ),
            result_parser=lambda response: _validated_patient_reply(
                _restore_patient_provider_fact_ids(
                    PatientResponderResponse.model_validate_json(response.text),
                    provider_fact_id_map,
                ),
                request,
                provider_answerable_fact_ids=list(provider_fact_id_map.values()),
            ),
        )


class OpenAICompatiblePatientResponder:
    def __init__(self, settings: OpenAICompatibleSettings, client: OpenAICompatibleChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or OpenAICompatibleChatClient(settings)

    def __call__(self, request: PatientResponderRequest) -> PatientResponderOutput:
        provider_payload, provider_fact_id_map = _build_patient_provider_payload(request)
        response = self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=provider_payload,
            response_model=PatientResponderResponse,
            temperature=0.4,
        )
        return _validated_patient_reply(
            _restore_patient_provider_fact_ids(response, provider_fact_id_map),
            request,
            provider_answerable_fact_ids=list(provider_fact_id_map.values()),
        )


class AnthropicPatientResponder:
    def __init__(self, settings: AnthropicSettings, client: AnthropicChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or AnthropicChatClient(settings)

    def __call__(self, request: PatientResponderRequest) -> PatientResponderOutput:
        provider_payload, provider_fact_id_map = _build_patient_provider_payload(request)
        response = self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=provider_payload,
            response_model=PatientResponderResponse,
            temperature=0.4,
        )
        return _validated_patient_reply(
            _restore_patient_provider_fact_ids(response, provider_fact_id_map),
            request,
            provider_answerable_fact_ids=list(provider_fact_id_map.values()),
        )


class DeterministicPatientResponder:
    def __call__(self, request: PatientResponderRequest) -> PatientResponderOutput:
        reply = request.canonical_answer.strip() or "这个问题我不太确定，或者病例中没有提供相关信息。"
        for term in request.forbidden_terms:
            if term:
                reply = re.sub(re.escape(term), "相关诊断", reply, flags=re.IGNORECASE)
        if len(reply) > 180:
            reply = f"{reply[:177]}..."
        _assert_no_forbidden_terms(reply, request.forbidden_terms)
        return PatientResponderOutput(reply=reply, emotion=infer_patient_emotion(reply))


class LazyGeminiPatientResponder:
    def __init__(self) -> None:
        self._responder_cache: RuntimeModelObjectCache[
            GeminiPatientResponder
            | OpenAICompatiblePatientResponder
            | AnthropicPatientResponder
            | DeterministicPatientResponder
        ] = RuntimeModelObjectCache()

    def __call__(self, request: PatientResponderRequest) -> PatientResponderOutput:
        responder = self._responder_cache.get_or_create(_create_configured_responder)
        try:
            return responder(request)
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
        require_direct_runtime_vertex_adc_proxy(runtime_vertex_config.proxy_url)
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


def _build_patient_provider_payload(
    request: PatientResponderRequest,
) -> tuple[dict[str, Any], dict[str, str]]:
    protected_terms = [request.case_id, *request.forbidden_terms]
    dialogue_context = request.dialogue_context if isinstance(request.dialogue_context, dict) else {}
    deterministic_hints = request.deterministic_hints if isinstance(request.deterministic_hints, dict) else {}
    payload: dict[str, Any] = {
        "case_title": _bounded_patient_provider_text(
            request.case_title,
            protected_terms,
            max_bytes=1_024,
        ),
        "chief_complaint": _bounded_patient_provider_text(
            request.chief_complaint,
            protected_terms,
            max_bytes=1_024,
        ),
        "student_message": _bounded_patient_provider_text(
            request.student_message,
            protected_terms,
            max_bytes=4_096,
        ),
        "current_intents": _bounded_patient_provider_text_list(
            request.current_intents,
            protected_terms,
            max_items=16,
            max_item_bytes=128,
        ),
        "canonical_answer": "",
        "answerable_fact_candidates": [],
        "dialogue_context": {
            "recent_messages": [],
            "asked_questions": [],
            "current_intents": [],
            "patient_affect_state": {},
            "student_affect_response": {},
        },
        "turn_policy": _bounded_patient_provider_text(
            request.turn_policy,
            protected_terms,
            max_bytes=256,
        ),
        "deterministic_hints": {},
    }

    if request.role_skill_policy:
        payload["role_skill_policy"] = _safe_patient_provider_value(
            request.role_skill_policy,
            protected_terms,
        )

    provider_fact_id_map: dict[str, str] = {}
    selected_candidates: list[dict[str, Any]] = []
    provider_candidates = select_patient_provider_fact_candidates(
        request.answerable_fact_candidates,
        request.current_intents,
    )
    for candidate in provider_candidates:
        original_fact_id = str(candidate.get("fact_id") or "").strip()
        provider_fact_id = f"fact_{len(selected_candidates) + 1}"
        compact_candidate = _compact_patient_provider_fact_candidate(
            provider_fact_id,
            candidate,
            protected_terms,
        )
        selected_candidates.append(compact_candidate)
        payload["answerable_fact_candidates"] = selected_candidates
        if _patient_provider_payload_size(payload) > PATIENT_PROVIDER_CONTENT_BUDGET_BYTES:
            raise RuntimeError("标准化病人事实子集超过内部载荷预算。")
        provider_fact_id_map[provider_fact_id] = original_fact_id

    if not selected_candidates:
        payload["canonical_answer"] = _bounded_patient_provider_text(
            request.canonical_answer,
            protected_terms,
            max_bytes=MAX_PATIENT_PROVIDER_CANONICAL_BYTES,
        )

    recent_dialogue_messages = _patient_provider_messages(
        dialogue_context.get("recent_messages") or request.prior_messages,
        protected_terms,
    )
    _add_recent_patient_provider_messages(payload, recent_dialogue_messages)
    _add_patient_provider_value_if_fits(
        payload,
        ("dialogue_context", "asked_questions"),
        _bounded_patient_provider_text_list(
            dialogue_context.get("asked_questions", []),
            protected_terms,
            max_items=8,
            max_item_bytes=512,
            newest_first=True,
        ),
    )
    _add_patient_provider_value_if_fits(
        payload,
        ("dialogue_context", "current_intents"),
        _bounded_patient_provider_text_list(
            dialogue_context.get("current_intents", []),
            protected_terms,
            max_items=16,
            max_item_bytes=128,
        ),
    )
    for key in ("patient_affect_state", "student_affect_response"):
        _add_patient_provider_value_if_fits(
            payload,
            ("dialogue_context", key),
            _safe_patient_provider_value(dialogue_context.get(key, {}), protected_terms),
        )
    for key in (
        "keyword_intent",
        "keyword_intents",
        "current_intents",
        "unknown_kind",
        "possible_intents",
        "turn_policy",
        "patient_context_mode",
        "stage",
        "safety_flags",
        "training_progress_next_focus",
    ):
        if key not in deterministic_hints:
            continue
        _add_patient_provider_value_if_fits(
            payload,
            ("deterministic_hints", key),
            _safe_patient_provider_value(deterministic_hints.get(key), protected_terms),
        )

    if _patient_provider_payload_size(payload) > PATIENT_PROVIDER_CONTENT_BUDGET_BYTES:
        raise RuntimeError("标准化病人模型请求超过内部载荷上限。")
    return payload, provider_fact_id_map


def select_patient_provider_fact_candidates(
    candidates: list[dict[str, Any]],
    current_intents: list[str],
) -> list[dict[str, Any]]:
    valid_candidates: list[tuple[str, dict[str, Any]]] = []
    seen_fact_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        fact_id = str(candidate.get("fact_id") or "").strip()
        if not fact_id or fact_id in seen_fact_ids:
            continue
        seen_fact_ids.add(fact_id)
        valid_candidates.append((fact_id, candidate))

    selected_fact_ids: set[str] = set()
    for intent in current_intents:
        if len(selected_fact_ids) >= MAX_PATIENT_PROVIDER_FACT_CANDIDATES:
            break
        normalized_intent = str(intent).strip()
        if not normalized_intent:
            continue
        for fact_id, candidate in valid_candidates:
            if fact_id in selected_fact_ids:
                continue
            trigger_intents = candidate.get("trigger_intents", [])
            if not isinstance(trigger_intents, list):
                continue
            if normalized_intent not in {str(item).strip() for item in trigger_intents}:
                continue
            selected_fact_ids.add(fact_id)
            break

    for fact_id, _ in valid_candidates:
        if len(selected_fact_ids) >= MAX_PATIENT_PROVIDER_FACT_CANDIDATES:
            break
        selected_fact_ids.add(fact_id)
    return [
        candidate
        for fact_id, candidate in valid_candidates
        if fact_id in selected_fact_ids
    ]


def _compact_patient_provider_fact_candidate(
    provider_fact_id: str,
    candidate: dict[str, Any],
    protected_terms: list[str],
) -> dict[str, Any]:
    topic = _bounded_patient_provider_text(
        str(candidate.get("topic") or ""),
        protected_terms,
        max_bytes=256,
    )
    slot = _bounded_patient_provider_text(
        str(candidate.get("slot") or ""),
        protected_terms,
        max_bytes=128,
    )
    canonical_answer = _bounded_patient_provider_text(
        str(candidate.get("canonical_answer") or ""),
        protected_terms,
        max_bytes=MAX_PATIENT_PROVIDER_FACT_CANONICAL_BYTES,
    )
    compact_candidate: dict[str, Any] = {"fact_id": provider_fact_id}
    if topic:
        compact_candidate["topic"] = topic
    if slot and _normalized_patient_provider_text(slot) != _normalized_patient_provider_text(topic):
        compact_candidate["slot"] = slot
    if canonical_answer:
        compact_candidate["canonical_answer"] = canonical_answer

    variants = candidate.get("variants", [])
    if isinstance(variants, list):
        compact_variants: list[str] = []
        seen_variants = {_normalized_patient_provider_text(canonical_answer)}
        canonical_normalized = _normalized_patient_provider_text(canonical_answer)
        for variant in variants:
            compact_variant = _bounded_patient_provider_text(
                str(variant),
                protected_terms,
                max_bytes=MAX_PATIENT_PROVIDER_FACT_VARIANT_BYTES,
            )
            normalized_variant = _normalized_patient_provider_text(compact_variant)
            if (
                not normalized_variant
                or normalized_variant in seen_variants
                or (
                    canonical_normalized
                    and (
                        normalized_variant in canonical_normalized
                        or canonical_normalized in normalized_variant
                    )
                )
            ):
                continue
            seen_variants.add(normalized_variant)
            compact_variants.append(compact_variant)
            if len(compact_variants) >= MAX_PATIENT_PROVIDER_FACT_VARIANTS:
                break
        if compact_variants:
            compact_candidate["variants"] = compact_variants
    return compact_candidate


def _bounded_patient_provider_text(
    value: str,
    protected_terms: list[str],
    *,
    max_bytes: int,
) -> str:
    return _truncate_utf8_text(
        _redact_patient_provider_text(str(value), protected_terms).strip(),
        max_bytes=max_bytes,
    )


def _bounded_patient_provider_text_list(
    values: Any,
    protected_terms: list[str],
    *,
    max_items: int,
    max_item_bytes: int,
    newest_first: bool = False,
) -> list[str]:
    if not isinstance(values, list):
        return []
    candidates = values[-max_items:] if newest_first else values[:max_items]
    return [
        bounded_value
        for value in candidates
        if (
            bounded_value := _bounded_patient_provider_text(
                str(value),
                protected_terms,
                max_bytes=max_item_bytes,
            )
        )
    ]


def _truncate_utf8_text(value: str, *, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    marker = "…"
    marker_bytes = marker.encode("utf-8")
    if max_bytes < len(marker_bytes):
        return encoded[:max_bytes].decode("utf-8", errors="ignore")
    prefix = encoded[: max_bytes - len(marker_bytes)].decode("utf-8", errors="ignore").rstrip()
    return f"{prefix}{marker}"


def _normalized_patient_provider_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _patient_provider_payload_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _add_recent_patient_provider_messages(
    payload: dict[str, Any],
    messages: list[dict[str, str]],
) -> None:
    selected_messages: list[dict[str, str]] = []
    for message in reversed(messages):
        candidate_messages = [message, *selected_messages]
        if _add_patient_provider_value_if_fits(
            payload,
            ("dialogue_context", "recent_messages"),
            candidate_messages,
        ):
            selected_messages = candidate_messages


def _add_patient_provider_value_if_fits(
    payload: dict[str, Any],
    path: tuple[str, str],
    value: Any,
) -> bool:
    parent = payload.get(path[0])
    if not isinstance(parent, dict):
        return False
    missing = object()
    previous_value = parent.get(path[1], missing)
    parent[path[1]] = value
    if _patient_provider_payload_size(payload) <= PATIENT_PROVIDER_CONTENT_BUDGET_BYTES:
        return True
    if previous_value is missing:
        parent.pop(path[1], None)
    else:
        parent[path[1]] = previous_value
    return False


def _patient_provider_messages(messages: Any, protected_terms: list[str]) -> list[dict[str, str]]:
    redacted_messages = [
        {
            "role": message["role"],
            "content": _redact_patient_provider_text(
                message["content"],
                protected_terms,
            ),
        }
        for message in bounded_provider_messages(
            messages,
            allowed_roles=PROVIDER_DIALOGUE_ROLES,
        )
    ]
    return bounded_provider_messages(
        redacted_messages,
        allowed_roles=PROVIDER_DIALOGUE_ROLES,
    )


def _safe_patient_provider_value(value: Any, protected_terms: list[str]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe_patient_provider_value(nested_value, protected_terms)
            for key, nested_value in value.items()
            if str(key) not in {
                "answerable_fact_ids",
                "revealed_fact_id",
                "revealed_fact_ids",
                "source_reference",
                "source_references",
            }
        }
    if isinstance(value, list):
        return [_safe_patient_provider_value(item, protected_terms) for item in value]
    if isinstance(value, str):
        return _redact_patient_provider_text(value, protected_terms)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)


def _redact_patient_provider_text(value: str, protected_terms: list[str]) -> str:
    redacted = value
    for term in sorted(
        {str(item).strip() for item in protected_terms if str(item).strip()},
        key=len,
        reverse=True,
    ):
        redacted = re.sub(re.escape(term), "[受保护内容]", redacted, flags=re.IGNORECASE)
    return redacted


def _restore_patient_provider_fact_ids(
    response: PatientResponderResponse,
    provider_fact_id_map: dict[str, str],
) -> PatientResponderResponse:
    return response.model_copy(
        update={
            "fact_ids_used": [
                provider_fact_id_map.get(fact_id, fact_id)
                for fact_id in response.fact_ids_used
            ]
        }
    )


def _assert_no_forbidden_terms(reply: str, forbidden_terms: list[str]) -> None:
    leaked_terms = [
        term
        for term in forbidden_terms
        if term and re.search(re.escape(term), reply, flags=re.IGNORECASE)
    ]
    if leaked_terms:
        raise RuntimeError(f"标准化病人回答包含禁止泄露词：{leaked_terms}")


def _validated_patient_reply(
    response: PatientResponderResponse,
    request: PatientResponderRequest,
    *,
    provider_answerable_fact_ids: list[str] | None = None,
) -> PatientResponderOutput:
    reply = response.reply.strip()
    answerable_fact_candidates = _provider_answerable_fact_candidates(
        request.answerable_fact_candidates,
        provider_answerable_fact_ids,
    )
    protected_fact_texts = [
        *request.protected_fact_texts,
        *_omitted_patient_provider_fact_texts(
            request.answerable_fact_candidates,
            answerable_fact_candidates,
        ),
    ]
    _assert_no_forbidden_terms(reply, request.forbidden_terms)
    _assert_no_protected_fact_text(reply, protected_fact_texts)
    _assert_used_fact_ids_are_answerable(response.fact_ids_used, answerable_fact_candidates)
    _assert_multi_intent_fact_coverage(
        response.fact_ids_used,
        request,
        answerable_fact_candidates=answerable_fact_candidates,
    )
    emotion = normalize_patient_emotion(response.emotion) or infer_patient_emotion(reply)
    return PatientResponderOutput(reply=reply, emotion=emotion, fact_ids_used=list(response.fact_ids_used))


def _provider_answerable_fact_candidates(
    candidates: list[dict[str, Any]],
    provider_answerable_fact_ids: list[str] | None,
) -> list[dict[str, Any]]:
    if provider_answerable_fact_ids is None:
        return candidates
    allowed_fact_ids = set(provider_answerable_fact_ids)
    return [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict)
        and str(candidate.get("fact_id") or "") in allowed_fact_ids
    ]


def _omitted_patient_provider_fact_texts(
    all_candidates: list[dict[str, Any]],
    selected_candidates: list[dict[str, Any]],
) -> list[str]:
    selected_fact_ids = {
        str(candidate.get("fact_id") or "")
        for candidate in selected_candidates
        if isinstance(candidate, dict)
    }
    selected_texts = {
        _normalized_patient_provider_text(text)
        for candidate in selected_candidates
        if isinstance(candidate, dict)
        for text in _patient_fact_candidate_texts(candidate)
        if text
    }
    return [
        text
        for candidate in all_candidates
        if isinstance(candidate, dict)
        and str(candidate.get("fact_id") or "") not in selected_fact_ids
        for text in _patient_fact_candidate_texts(candidate)
        if text and _normalized_patient_provider_text(text) not in selected_texts
    ]


def _patient_fact_candidate_texts(candidate: dict[str, Any]) -> list[str]:
    texts = [str(candidate.get("canonical_answer") or "")]
    variants = candidate.get("variants", [])
    if isinstance(variants, list):
        texts.extend(str(variant) for variant in variants)
    return texts


def _assert_used_fact_ids_are_answerable(
    fact_ids_used: list[str],
    answerable_fact_candidates: list[dict[str, Any]],
) -> None:
    allowed_fact_ids = {
        str(candidate.get("fact_id"))
        for candidate in answerable_fact_candidates
        if isinstance(candidate, dict) and candidate.get("fact_id")
    }
    if allowed_fact_ids and not fact_ids_used:
        raise RuntimeError("标准化病人回答未声明本轮病例事实。")
    if not fact_ids_used:
        return
    unauthorized_fact_ids = [fact_id for fact_id in fact_ids_used if fact_id not in allowed_fact_ids]
    if unauthorized_fact_ids:
        raise RuntimeError(f"标准化病人回答声明使用了未授权病例事实：{unauthorized_fact_ids}")


def _assert_no_protected_fact_text(reply: str, protected_fact_texts: list[str]) -> None:
    normalized_reply = re.sub(r"\s+", "", reply).casefold()
    leaked_facts = [
        fact_text
        for fact_text in protected_fact_texts
        if fact_text
        and len(re.sub(r"\s+", "", fact_text)) >= 6
        and re.sub(r"\s+", "", fact_text).casefold() in normalized_reply
    ]
    if leaked_facts:
        raise RuntimeError("标准化病人回答包含未授权病例事实。")


def _assert_multi_intent_fact_coverage(
    fact_ids_used: list[str],
    request: PatientResponderRequest,
    *,
    answerable_fact_candidates: list[dict[str, Any]] | None = None,
) -> None:
    if len(request.current_intents) <= 1:
        return
    expected_fact_ids = [
        str(candidate.get("fact_id"))
        for candidate in (
            request.answerable_fact_candidates
            if answerable_fact_candidates is None
            else answerable_fact_candidates
        )
        if isinstance(candidate, dict) and candidate.get("fact_id")
    ]
    if len(expected_fact_ids) <= 1:
        return
    missing_fact_ids = [fact_id for fact_id in expected_fact_ids if fact_id not in set(fact_ids_used)]
    if missing_fact_ids:
        raise RuntimeError(f"标准化病人回答未覆盖本轮多个问诊事实：{missing_fact_ids}")


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
    "select_patient_provider_fact_candidates",
]
