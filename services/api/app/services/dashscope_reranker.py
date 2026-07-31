from __future__ import annotations

import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.api_call_log_service import api_call_log_store
from app.services.dashscope_credential_service import (
    DASHSCOPE_SHARED_API_KEY_ENV_NAME,
    DASHSCOPE_SPEECH_API_KEY_ENV_NAME,
    resolve_dashscope_feature_api_key,
)
from app.services.model_call_policy import (
    TEXT_MODEL_ENVELOPE_MAX_BYTES,
    enforce_text_model_json_envelope,
    json_envelope_utf8_size,
    run_model_provider_call,
)

DEFAULT_DASHSCOPE_RERANK_BASE_URL = "https://dashscope.aliyuncs.com/compatible-api/v1"
DEFAULT_DASHSCOPE_RERANK_MODEL = "qwen3-rerank"
DEFAULT_DASHSCOPE_RERANK_TOP_K = 5
DEFAULT_DASHSCOPE_RERANK_CANDIDATE_K = 30
DEFAULT_DASHSCOPE_RERANK_TIMEOUT_SECONDS = 15.0
DEFAULT_DASHSCOPE_RERANK_INSTRUCT = "Retrieve semantically similar text."
MAX_DASHSCOPE_RERANK_CANDIDATES = 30
MAX_DASHSCOPE_RERANK_TOP_K = 30
MAX_DASHSCOPE_RERANK_QUERY_BYTES = 4 * 1024
MAX_DASHSCOPE_RERANK_INSTRUCT_BYTES = 2 * 1024
MAX_DASHSCOPE_RERANK_DOCUMENT_BYTES = 4 * 1024
MIN_DASHSCOPE_RERANK_DOCUMENT_BYTES = 4


@dataclass(frozen=True)
class DashScopeRerankSettings:
    api_key: str
    base_url: str = DEFAULT_DASHSCOPE_RERANK_BASE_URL
    model: str = DEFAULT_DASHSCOPE_RERANK_MODEL
    top_k: int = DEFAULT_DASHSCOPE_RERANK_TOP_K
    candidate_k: int = DEFAULT_DASHSCOPE_RERANK_CANDIDATE_K
    instruct: str = DEFAULT_DASHSCOPE_RERANK_INSTRUCT
    proxy_url: str = "direct"
    timeout_seconds: float = DEFAULT_DASHSCOPE_RERANK_TIMEOUT_SECONDS


@dataclass(frozen=True)
class DashScopeRerankResult:
    index: int
    relevance_score: float


class DashScopeReranker:
    def __init__(self, settings: DashScopeRerankSettings) -> None:
        self._settings = settings

    def candidate_limit(self, result_limit: int) -> int:
        return min(
            MAX_DASHSCOPE_RERANK_CANDIDATES,
            max(
                _positive_int(result_limit, default=1),
                _positive_int(
                    self._settings.candidate_k,
                    default=DEFAULT_DASHSCOPE_RERANK_CANDIDATE_K,
                ),
            ),
        )

    def top_limit(self, result_limit: int, document_count: int) -> int:
        return max(
            1,
            min(
                _positive_int(result_limit, default=1),
                _positive_int(
                    self._settings.top_k,
                    default=DEFAULT_DASHSCOPE_RERANK_TOP_K,
                ),
                _positive_int(document_count, default=1),
                MAX_DASHSCOPE_RERANK_TOP_K,
            ),
        )

    def rerank(self, query: str, documents: Sequence[str], *, top_k: int) -> list[DashScopeRerankResult]:
        normalized_query = str(query).strip()
        indexed_documents = [
            (index, normalized_document)
            for index, document in enumerate(documents)
            if (normalized_document := str(document).strip())
        ]
        if not normalized_query or not indexed_documents:
            return []

        candidate_limit = self.candidate_limit(top_k)
        indexed_documents = indexed_documents[:candidate_limit]
        original_indexes = [index for index, _ in indexed_documents]

        endpoint = _reranks_url(self._settings.base_url)
        started_at = time.perf_counter()
        try:
            payload = _build_rerank_provider_payload(
                settings=self._settings,
                query=normalized_query,
                documents=[document for _, document in indexed_documents],
                top_k=self.top_limit(top_k, len(indexed_documents)),
            )

            def send_request() -> httpx.Response:
                with httpx.Client(**self._client_options()) as client:
                    response = client.post(
                        endpoint,
                        headers={
                            "Authorization": (
                                f"Bearer {self._settings.api_key}"
                            ),
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                response.raise_for_status()
                return response

            response = run_model_provider_call(
                send_request,
                timeout_seconds=self._settings.timeout_seconds,
            )
            results = _restore_original_result_indexes(
                _parse_qwen3_rerank_results(response.json()),
                original_indexes=original_indexes,
            )
        except Exception as exc:
            api_call_log_store.record(
                provider="dashscope_rerank",
                operation="rerank",
                model=self._settings.model,
                endpoint=endpoint,
                success=False,
                duration_ms=(time.perf_counter() - started_at) * 1000,
                error=exc,
            )
            raise

        api_call_log_store.record(
            provider="dashscope_rerank",
            operation="rerank",
            model=self._settings.model,
            endpoint=endpoint,
            success=True,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            status_code=response.status_code,
        )
        return results

    def _client_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "timeout": self._settings.timeout_seconds,
            "trust_env": False,
        }
        if _should_use_proxy(self._settings.proxy_url):
            options["proxy"] = self._settings.proxy_url
        return options


def build_dashscope_reranker_from_environment() -> DashScopeReranker | None:
    if not _truthy_env("OSCE_DASHSCOPE_RERANK_ENABLED"):
        return None
    base_url = _env(
        "OSCE_DASHSCOPE_RERANK_BASE_URL",
        DEFAULT_DASHSCOPE_RERANK_BASE_URL,
    )
    api_key = resolve_dashscope_feature_api_key(
        _env("OSCE_DASHSCOPE_RERANK_API_KEY"),
        target_urls=(base_url,),
        fallback_env_names=(
            DASHSCOPE_SHARED_API_KEY_ENV_NAME,
            DASHSCOPE_SPEECH_API_KEY_ENV_NAME,
        ),
    )
    if not api_key:
        return None
    settings = DashScopeRerankSettings(
        api_key=api_key,
        base_url=base_url,
        model=_env("OSCE_DASHSCOPE_RERANK_MODEL", DEFAULT_DASHSCOPE_RERANK_MODEL),
        top_k=min(
            _int_env(
                "OSCE_DASHSCOPE_RERANK_TOP_K",
                DEFAULT_DASHSCOPE_RERANK_TOP_K,
            ),
            MAX_DASHSCOPE_RERANK_TOP_K,
        ),
        candidate_k=min(
            _int_env(
                "OSCE_DASHSCOPE_RERANK_CANDIDATE_K",
                DEFAULT_DASHSCOPE_RERANK_CANDIDATE_K,
            ),
            MAX_DASHSCOPE_RERANK_CANDIDATES,
        ),
        instruct=_env("OSCE_DASHSCOPE_RERANK_INSTRUCT", DEFAULT_DASHSCOPE_RERANK_INSTRUCT),
        proxy_url=_env("OSCE_DASHSCOPE_RERANK_PROXY_URL", "direct"),
        timeout_seconds=_float_env("OSCE_DASHSCOPE_RERANK_TIMEOUT_SECONDS", DEFAULT_DASHSCOPE_RERANK_TIMEOUT_SECONDS),
    )
    return DashScopeReranker(settings)


def _parse_qwen3_rerank_results(payload: dict[str, Any]) -> list[DashScopeRerankResult]:
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        output = payload.get("output")
        raw_results = output.get("results") if isinstance(output, dict) else None
    if not isinstance(raw_results, list):
        raise RuntimeError("DashScope rerank response missing results")

    results: list[DashScopeRerankResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        relevance_score = item.get("relevance_score")
        if isinstance(index, int) and isinstance(relevance_score, int | float):
            results.append(DashScopeRerankResult(index=index, relevance_score=float(relevance_score)))
    return results


def _build_rerank_provider_payload(
    *,
    settings: DashScopeRerankSettings,
    query: str,
    documents: Sequence[str],
    top_k: int,
) -> dict[str, Any]:
    projected_query = _truncate_utf8(
        query,
        MAX_DASHSCOPE_RERANK_QUERY_BYTES,
    )
    projected_instruct = _truncate_utf8(
        settings.instruct,
        MAX_DASHSCOPE_RERANK_INSTRUCT_BYTES,
    )
    projected_documents = [
        _truncate_utf8(document, MAX_DASHSCOPE_RERANK_DOCUMENT_BYTES)
        for document in documents[:MAX_DASHSCOPE_RERANK_CANDIDATES]
    ]

    def build_payload(document_byte_limit: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": settings.model,
            "query": projected_query,
            "documents": [
                _truncate_utf8(document, document_byte_limit)
                for document in projected_documents
            ],
            "top_n": max(
                1,
                min(
                    top_k,
                    len(projected_documents),
                    MAX_DASHSCOPE_RERANK_TOP_K,
                ),
            ),
        }
        if projected_instruct:
            payload["instruct"] = projected_instruct
        return payload

    payload = build_payload(MAX_DASHSCOPE_RERANK_DOCUMENT_BYTES)
    if json_envelope_utf8_size(payload) > TEXT_MODEL_ENVELOPE_MAX_BYTES:
        minimum_payload = build_payload(
            MIN_DASHSCOPE_RERANK_DOCUMENT_BYTES
        )
        enforce_text_model_json_envelope(minimum_payload)
        lower_bound = MIN_DASHSCOPE_RERANK_DOCUMENT_BYTES
        upper_bound = MAX_DASHSCOPE_RERANK_DOCUMENT_BYTES
        best_document_limit = lower_bound
        while lower_bound <= upper_bound:
            candidate_limit = (lower_bound + upper_bound) // 2
            candidate_payload = build_payload(candidate_limit)
            if (
                json_envelope_utf8_size(candidate_payload)
                <= TEXT_MODEL_ENVELOPE_MAX_BYTES
            ):
                best_document_limit = candidate_limit
                lower_bound = candidate_limit + 1
            else:
                upper_bound = candidate_limit - 1
        payload = build_payload(best_document_limit)

    enforce_text_model_json_envelope(payload)
    return payload


def _restore_original_result_indexes(
    results: Sequence[DashScopeRerankResult],
    *,
    original_indexes: Sequence[int],
) -> list[DashScopeRerankResult]:
    return [
        DashScopeRerankResult(
            index=original_indexes[result.index],
            relevance_score=result.relevance_score,
        )
        for result in results
        if 0 <= result.index < len(original_indexes)
    ]


def _truncate_utf8(value: str, max_bytes: int) -> str:
    normalized = str(value).strip()
    encoded = normalized.encode("utf-8")
    if len(encoded) <= max_bytes:
        return normalized
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _reranks_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/reranks"):
        return normalized
    return f"{normalized}/reranks"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int_env(name: str, default: int) -> int:
    raw_value = _env(name)
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return normalized if normalized > 0 else default


def _float_env(name: str, default: float) -> float:
    raw_value = _env(name)
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def _truthy_env(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


def _should_use_proxy(proxy_url: str) -> bool:
    normalized = proxy_url.strip().lower()
    return bool(normalized and normalized not in {"direct", "none", "false", "off", "no"})


__all__ = [
    "DEFAULT_DASHSCOPE_RERANK_BASE_URL",
    "DEFAULT_DASHSCOPE_RERANK_CANDIDATE_K",
    "DEFAULT_DASHSCOPE_RERANK_MODEL",
    "DEFAULT_DASHSCOPE_RERANK_TOP_K",
    "MAX_DASHSCOPE_RERANK_CANDIDATES",
    "MAX_DASHSCOPE_RERANK_DOCUMENT_BYTES",
    "MAX_DASHSCOPE_RERANK_INSTRUCT_BYTES",
    "MAX_DASHSCOPE_RERANK_QUERY_BYTES",
    "MAX_DASHSCOPE_RERANK_TOP_K",
    "DashScopeRerankResult",
    "DashScopeRerankSettings",
    "DashScopeReranker",
    "build_dashscope_reranker_from_environment",
]
