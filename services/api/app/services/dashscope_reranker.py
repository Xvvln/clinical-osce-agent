from __future__ import annotations

import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.api_call_log_service import api_call_log_store
from app.services.model_call_policy import run_model_provider_call

DEFAULT_DASHSCOPE_RERANK_BASE_URL = "https://dashscope.aliyuncs.com/compatible-api/v1"
DEFAULT_DASHSCOPE_RERANK_MODEL = "qwen3-rerank"
DEFAULT_DASHSCOPE_RERANK_TOP_K = 5
DEFAULT_DASHSCOPE_RERANK_CANDIDATE_K = 30
DEFAULT_DASHSCOPE_RERANK_TIMEOUT_SECONDS = 15.0
DEFAULT_DASHSCOPE_RERANK_INSTRUCT = "Retrieve semantically similar text."


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
        return max(result_limit, self._settings.candidate_k)

    def top_limit(self, result_limit: int, document_count: int) -> int:
        return max(1, min(result_limit, self._settings.top_k, document_count))

    def rerank(self, query: str, documents: Sequence[str], *, top_k: int) -> list[DashScopeRerankResult]:
        normalized_query = str(query).strip()
        normalized_documents = [str(document).strip() for document in documents]
        if not normalized_query or not normalized_documents:
            return []

        payload: dict[str, Any] = {
            "model": self._settings.model,
            "query": normalized_query,
            "documents": normalized_documents,
            "top_n": max(1, min(top_k, len(normalized_documents))),
        }
        if self._settings.instruct:
            payload["instruct"] = self._settings.instruct

        endpoint = _reranks_url(self._settings.base_url)
        started_at = time.perf_counter()
        try:
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
            results = _parse_qwen3_rerank_results(response.json())
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
    api_key = _env("OSCE_DASHSCOPE_RERANK_API_KEY") or _env("DASHSCOPE_API_KEY")
    if not api_key:
        return None
    settings = DashScopeRerankSettings(
        api_key=api_key,
        base_url=_env("OSCE_DASHSCOPE_RERANK_BASE_URL", DEFAULT_DASHSCOPE_RERANK_BASE_URL),
        model=_env("OSCE_DASHSCOPE_RERANK_MODEL", DEFAULT_DASHSCOPE_RERANK_MODEL),
        top_k=_int_env("OSCE_DASHSCOPE_RERANK_TOP_K", DEFAULT_DASHSCOPE_RERANK_TOP_K),
        candidate_k=_int_env("OSCE_DASHSCOPE_RERANK_CANDIDATE_K", DEFAULT_DASHSCOPE_RERANK_CANDIDATE_K),
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
    "DashScopeRerankResult",
    "DashScopeRerankSettings",
    "DashScopeReranker",
    "build_dashscope_reranker_from_environment",
]
