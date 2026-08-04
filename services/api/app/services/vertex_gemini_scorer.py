from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models.rubric import LlmRubricRequest, LlmRubricResponse
from app.services.anthropic_chat_client import AnthropicChatClient, AnthropicSettings
from app.services.api_call_log_service import call_with_api_logging
from app.services.google_genai_http_options import (
    build_google_genai_http_options,
    require_direct_runtime_vertex_adc_proxy,
)
from app.services.model_call_policy import call_google_text_generate_content
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.runtime_model_config_store import runtime_model_config_store

SYSTEM_PROMPT_TEMPLATE = """你是 OSCE 临床思维训练的评分员。你只能依据输入中列出的 required_evidence 和学生的 student_final_reasoning 打分。你不得引入输入之外的医学事实。

评分规则：
- 满分为 max_score。
- 学生推理表达每覆盖一项 required_evidence 得 (max_score / len(required_evidence)) 分，四舍五入到整数；score 不得超过 max_score。
- 若学生推理包含不在 relevant_facts_revealed 中的事实编造，rationale 必须指出，并不得因此加分。
- 如果输入包含 provider_projection，证据列表是有界的确定性投影；必须使用其中的原始总数作为评分分母，未列出的证据不得推断为已覆盖，也不得据此补充病例事实；不得仅因某事实未出现在投影列表中就判为编造。
- rationale 不超过 120 字，不输出具体用药方案、剂量或真实诊疗建议。

输出要求：
- 只输出一个 JSON 对象，且必须包含 score、covered_evidence、missing_evidence、rationale 四个字段。
- covered_evidence 和 missing_evidence 必须逐字复制 required_evidence 中的完整条目，并共同覆盖全部 required_evidence；没有内容时也必须输出空数组。
- 示例：{"score": 5, "covered_evidence": ["证据A"], "missing_evidence": ["证据B"], "rationale": "已覆盖证据A，仍缺证据B。"}
"""

RUBRIC_PROVIDER_PAYLOAD_MAX_BYTES = 48 * 1024
RUBRIC_PROVIDER_MAX_PROJECTED_ITEMS_PER_LIST = 128
RUBRIC_PROVIDER_REFERENCE_MAX_BYTES = 2 * 1024
RUBRIC_PROVIDER_REASONING_MAX_BYTES = 16 * 1024
RUBRIC_PROVIDER_DESCRIPTION_MAX_BYTES = 2 * 1024
RUBRIC_PROVIDER_ITEM_ID_MAX_BYTES = 256
_PROJECTION_POLICY = "relevance_first_v1"
_TRUNCATED_REFERENCE_PREFIX_MAX_BYTES = 512


@dataclass(frozen=True)
class RubricProviderProjection:
    payload: dict[str, Any]
    required_evidence_aliases: dict[str, str]
    compacted: bool


def build_rubric_provider_projection(request: LlmRubricRequest) -> RubricProviderProjection:
    """Build the shared, byte-bounded payload sent to every rubric provider.

    The full ``LlmRubricRequest`` remains local. Small payloads retain their
    existing shape exactly; only oversized requests gain projection metadata.
    """

    full_payload = request.model_dump()
    if _provider_payload_size(full_payload) <= RUBRIC_PROVIDER_PAYLOAD_MAX_BYTES:
        return RubricProviderProjection(
            payload=full_payload,
            required_evidence_aliases={value: value for value in request.required_evidence},
            compacted=False,
        )

    relevant_facts = _stable_unique(request.relevant_facts_revealed)
    required_evidence = _stable_unique(request.required_evidence)
    payload: dict[str, Any] = {
        "rubric_item_id": _truncate_utf8_with_digest(
            request.rubric_item_id,
            RUBRIC_PROVIDER_ITEM_ID_MAX_BYTES,
        ),
        "description": _truncate_utf8_with_digest(
            request.description,
            RUBRIC_PROVIDER_DESCRIPTION_MAX_BYTES,
        ),
        "max_score": request.max_score,
        "student_final_reasoning": _truncate_utf8_with_digest(
            request.student_final_reasoning,
            RUBRIC_PROVIDER_REASONING_MAX_BYTES,
        ),
        "relevant_facts_revealed": [],
        "required_evidence": [],
        "provider_projection": {
            "compacted": True,
            "policy": _PROJECTION_POLICY,
            "relevant_facts_revealed_total": len(request.relevant_facts_revealed),
            "relevant_facts_revealed_unique_total": len(relevant_facts),
            "relevant_facts_revealed_included": 0,
            "required_evidence_total": len(request.required_evidence),
            "required_evidence_unique_total": len(required_evidence),
            "required_evidence_included": 0,
        },
    }
    _fit_scalar_fields(payload)

    required_set = set(required_evidence)
    revealed_set = set(relevant_facts)
    reasoning = request.student_final_reasoning
    ranked_required = sorted(
        required_evidence,
        key=lambda value: (
            0 if value and value in reasoning else 1 if value in revealed_set else 2,
            _stable_digest(value),
            value,
        ),
    )
    ranked_relevant = sorted(
        relevant_facts,
        key=lambda value: (
            0 if value in required_set else 1 if value and value in reasoning else 2,
            _stable_digest(value),
            value,
        ),
    )

    required_aliases: dict[str, str] = {}
    candidate_groups = (
        ("required_evidence", ranked_required),
        ("relevant_facts_revealed", ranked_relevant),
    )
    candidate_index = {field: 0 for field, _values in candidate_groups}
    while True:
        exhausted = True
        for field, values in candidate_groups:
            index = candidate_index[field]
            if (
                index >= len(values)
                or len(payload[field]) >= RUBRIC_PROVIDER_MAX_PROJECTED_ITEMS_PER_LIST
            ):
                continue
            exhausted = False
            original = values[index]
            candidate_index[field] = index + 1
            alias = _provider_reference(original)
            payload[field].append(alias)
            metadata_key = f"{field}_included"
            payload["provider_projection"][metadata_key] = len(payload[field])
            if _provider_payload_size(payload) > RUBRIC_PROVIDER_PAYLOAD_MAX_BYTES:
                payload[field].pop()
                payload["provider_projection"][metadata_key] = len(payload[field])
                continue
            if field == "required_evidence":
                required_aliases[alias] = original
        if exhausted:
            break

    if _provider_payload_size(payload) > RUBRIC_PROVIDER_PAYLOAD_MAX_BYTES:
        raise RuntimeError("rubric provider payload projection exceeded its byte budget")
    return RubricProviderProjection(
        payload=payload,
        required_evidence_aliases=required_aliases,
        compacted=True,
    )


def _restore_rubric_response(
    response: LlmRubricResponse,
    *,
    request: LlmRubricRequest,
    projection: RubricProviderProjection,
) -> LlmRubricResponse:
    if not projection.compacted:
        return response

    covered = _restore_evidence_values(
        response.covered_evidence,
        projection.required_evidence_aliases,
    )
    covered_set = set(covered)
    missing = [
        evidence
        for evidence in _stable_unique(request.required_evidence)
        if evidence not in covered_set
    ]
    required_evidence_count = len(request.required_evidence)
    allowed_score = (
        _round_ratio_half_up(
            request.max_score * len(covered),
            required_evidence_count,
        )
        if required_evidence_count
        else 0
    )
    return response.model_copy(
        update={
            "score": min(response.score, allowed_score),
            "covered_evidence": covered,
            "missing_evidence": missing,
        }
    )


def _restore_evidence_values(values: list[str], aliases: dict[str, str]) -> list[str]:
    restored: list[str] = []
    for value in values:
        original = aliases.get(value)
        if original is not None and original not in restored:
            restored.append(original)
    return restored


def _fit_scalar_fields(payload: dict[str, Any]) -> None:
    if _provider_payload_size(payload) <= RUBRIC_PROVIDER_PAYLOAD_MAX_BYTES:
        return
    for field in ("student_final_reasoning", "description", "rubric_item_id"):
        original = str(payload[field])
        low = 0
        high = len(original)
        best = ""
        while low <= high:
            midpoint = (low + high) // 2
            candidate = _truncate_utf8_with_digest(original, midpoint)
            payload[field] = candidate
            if _provider_payload_size(payload) <= RUBRIC_PROVIDER_PAYLOAD_MAX_BYTES:
                best = candidate
                low = midpoint + 1
            else:
                high = midpoint - 1
        payload[field] = best
        if _provider_payload_size(payload) <= RUBRIC_PROVIDER_PAYLOAD_MAX_BYTES:
            return
    raise RuntimeError("rubric provider payload metadata exceeded its byte budget")


def _provider_reference(value: str) -> str:
    serialized_size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    if serialized_size <= RUBRIC_PROVIDER_REFERENCE_MAX_BYTES:
        return value
    return _truncate_utf8_with_digest(value, _TRUNCATED_REFERENCE_PREFIX_MAX_BYTES)


def _truncate_utf8_with_digest(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    digest_suffix = f"…[sha256:{_stable_digest(value)[:16]}]"
    suffix_size = len(digest_suffix.encode("utf-8"))
    if max_bytes <= suffix_size:
        return digest_suffix.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
    prefix = encoded[: max_bytes - suffix_size].decode("utf-8", errors="ignore")
    return f"{prefix}{digest_suffix}"


def _stable_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _stable_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _round_ratio_half_up(numerator: int, denominator: int) -> int:
    quotient, remainder = divmod(numerator, denominator)
    return quotient + int(remainder * 2 >= denominator)


def _provider_payload_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class VertexGeminiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OSCE_VERTEX_", env_file=".env", extra="ignore")

    enabled: bool = False
    api_key: str = ""
    project: str = ""
    location: str = "global"
    model: str = "gemini-3.1-pro-preview"
    proxy_url: str = "http://127.0.0.1:7897"


class VertexGeminiRubricScorer:
    def __init__(self, settings: VertexGeminiSettings, client: Any | None = None) -> None:
        self._settings = settings
        if client is not None:
            self._client = client
        elif settings.api_key:
            self._client = genai.Client(
                vertexai=True,
                api_key=settings.api_key,
                http_options=build_google_genai_http_options(settings.proxy_url),
            )
        else:
            self._client = genai.Client(
                vertexai=True,
                project=settings.project,
                location=settings.location,
                http_options=build_google_genai_http_options(settings.proxy_url),
            )

    def __call__(self, request: LlmRubricRequest) -> LlmRubricResponse:
        projection = build_rubric_provider_projection(request)
        return call_with_api_logging(
            provider="vertex_gemini_rubric_scorer",
            operation="generate_content",
            model=self._settings.model,
            endpoint="vertex://generate_content",
            call=lambda: call_google_text_generate_content(
                client=self._client,
                model=self._settings.model,
                contents=json.dumps(projection.payload, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT_TEMPLATE,
                    response_mime_type="application/json",
                    response_schema=LlmRubricResponse,
                ),
            ),
            result_parser=lambda response: _restore_rubric_response(
                LlmRubricResponse.model_validate_json(response.text),
                request=request,
                projection=projection,
            ),
        )


class OpenAICompatibleRubricScorer:
    def __init__(self, settings: OpenAICompatibleSettings, client: OpenAICompatibleChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or OpenAICompatibleChatClient(settings)

    def __call__(self, request: LlmRubricRequest) -> LlmRubricResponse:
        projection = build_rubric_provider_projection(request)
        response = self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=projection.payload,
            response_model=LlmRubricResponse,
            temperature=0.1,
        )
        return _restore_rubric_response(
            response,
            request=request,
            projection=projection,
        )


class AnthropicRubricScorer:
    def __init__(self, settings: AnthropicSettings, client: AnthropicChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or AnthropicChatClient(settings)

    def __call__(self, request: LlmRubricRequest) -> LlmRubricResponse:
        projection = build_rubric_provider_projection(request)
        response = self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=projection.payload,
            response_model=LlmRubricResponse,
            temperature=0.1,
        )
        return _restore_rubric_response(
            response,
            request=request,
            projection=projection,
        )


def create_default_vertex_gemini_scorer() -> VertexGeminiRubricScorer | OpenAICompatibleRubricScorer | AnthropicRubricScorer | None:
    runtime_openai_settings = runtime_model_config_store.get_openai_compatible_settings()
    if runtime_openai_settings is not None:
        return OpenAICompatibleRubricScorer(runtime_openai_settings)

    runtime_anthropic_settings = runtime_model_config_store.get_anthropic_settings()
    if runtime_anthropic_settings is not None:
        return AnthropicRubricScorer(runtime_anthropic_settings)

    runtime_vertex_api_key_config = runtime_model_config_store.get_vertex_gemini_api_key_config()
    if runtime_vertex_api_key_config is not None:
        return VertexGeminiRubricScorer(
            settings=VertexGeminiSettings(
                enabled=True,
                api_key=runtime_vertex_api_key_config.api_key,
                project="",
                location=runtime_vertex_api_key_config.location,
                model=runtime_vertex_api_key_config.model,
                proxy_url=runtime_vertex_api_key_config.proxy_url,
            )
        )

    runtime_vertex_config = runtime_model_config_store.get_vertex_gemini_adc_config()
    if runtime_vertex_config is not None:
        require_direct_runtime_vertex_adc_proxy(runtime_vertex_config.proxy_url)
        return VertexGeminiRubricScorer(
            settings=VertexGeminiSettings(
                enabled=True,
                project=runtime_vertex_config.project,
                location=runtime_vertex_config.location,
                model=runtime_vertex_config.model,
                proxy_url=runtime_vertex_config.proxy_url,
            )
        )

    openai_settings = OpenAICompatibleSettings()
    if openai_settings.is_configured:
        return OpenAICompatibleRubricScorer(openai_settings)

    anthropic_settings = AnthropicSettings()
    if anthropic_settings.is_configured:
        return AnthropicRubricScorer(anthropic_settings)

    settings = VertexGeminiSettings()
    if not settings.enabled or not (settings.project or settings.api_key):
        return None
    try:
        return VertexGeminiRubricScorer(settings=settings)
    except ImportError:
        return None


__all__ = [
    "AnthropicRubricScorer",
    "OpenAICompatibleRubricScorer",
    "RUBRIC_PROVIDER_PAYLOAD_MAX_BYTES",
    "RubricProviderProjection",
    "VertexGeminiRubricScorer",
    "VertexGeminiSettings",
    "build_rubric_provider_projection",
    "create_default_vertex_gemini_scorer",
]
