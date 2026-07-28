from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlsplit

import httpx
from google.genai import types


DIRECT_PROXY_VALUES = frozenset({"", "direct", "none", "false", "off", "no"})
DEFAULT_GOOGLE_GENAI_TIMEOUT_SECONDS = 30.0
INVALID_GOOGLE_GENAI_PROXY_MESSAGE = "Google GenAI 代理仅支持完整的 http:// 或 https:// URL。"
INVALID_GOOGLE_GENAI_TIMEOUT_MESSAGE = "Google GenAI 超时必须是有限的正数秒数。"
RUNTIME_VERTEX_ADC_PROXY_UNSUPPORTED_MESSAGE = (
    "Vertex Gemini ADC 的账号级代理仅支持 direct；"
    "需要代理时请改用 Vertex API Key，或由运维统一配置服务端托管代理。"
)


def build_google_genai_http_options(
    proxy_url: str,
    *,
    timeout_seconds: float = DEFAULT_GOOGLE_GENAI_TIMEOUT_SECONDS,
) -> types.HttpOptions:
    """Build request-isolated Google GenAI transport options."""
    normalized_proxy_url = str(proxy_url or "").strip()
    use_proxy = should_use_google_genai_proxy(normalized_proxy_url)
    if use_proxy:
        validate_google_genai_proxy_url(normalized_proxy_url)
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError(INVALID_GOOGLE_GENAI_TIMEOUT_MESSAGE)
    timeout_milliseconds = max(1, round(timeout_seconds * 1_000))
    client_args: dict[str, Any] = {
        "follow_redirects": False,
        "trust_env": False,
    }
    async_client_args: dict[str, Any] = {
        "follow_redirects": False,
        "trust_env": False,
        # google-genai otherwise prefers aiohttp when installed, whose internally
        # created session trusts process proxy variables. A transport forces the
        # SDK onto the configured per-client httpx path.
        "transport": httpx.AsyncHTTPTransport(
            proxy=normalized_proxy_url if use_proxy else None,
            trust_env=False,
        ),
    }
    if use_proxy:
        client_args["proxy"] = normalized_proxy_url
        async_client_args["proxy"] = normalized_proxy_url
    return types.HttpOptions(
        timeout=timeout_milliseconds,
        # Do not multiply the per-attempt transport timeout through the SDK's
        # implicit retry loop; higher-level overload handling owns retries.
        retry_options=types.HttpRetryOptions(attempts=1),
        client_args=client_args,
        async_client_args=async_client_args,
    )


def require_direct_runtime_vertex_adc_proxy(proxy_url: str) -> None:
    """Reject per-account ADC proxies that cannot isolate credential refresh."""
    if should_use_google_genai_proxy(proxy_url):
        raise ValueError(RUNTIME_VERTEX_ADC_PROXY_UNSUPPORTED_MESSAGE)


def should_use_google_genai_proxy(proxy_url: str) -> bool:
    return str(proxy_url or "").strip().lower() not in DIRECT_PROXY_VALUES


def validate_google_genai_proxy_url(proxy_url: str) -> None:
    parsed_proxy_url = urlsplit(proxy_url)
    if parsed_proxy_url.scheme.lower() not in {"http", "https"} or not parsed_proxy_url.netloc:
        raise ValueError(INVALID_GOOGLE_GENAI_PROXY_MESSAGE)


__all__ = [
    "DEFAULT_GOOGLE_GENAI_TIMEOUT_SECONDS",
    "INVALID_GOOGLE_GENAI_PROXY_MESSAGE",
    "INVALID_GOOGLE_GENAI_TIMEOUT_MESSAGE",
    "RUNTIME_VERTEX_ADC_PROXY_UNSUPPORTED_MESSAGE",
    "build_google_genai_http_options",
    "require_direct_runtime_vertex_adc_proxy",
    "should_use_google_genai_proxy",
    "validate_google_genai_proxy_url",
]
