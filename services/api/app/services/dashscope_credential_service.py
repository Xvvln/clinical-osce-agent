from __future__ import annotations

import os
from collections.abc import Iterable
from urllib.parse import urlsplit

DASHSCOPE_SHARED_API_KEY_ENV_NAME = "DASHSCOPE_API_KEY"
DASHSCOPE_SPEECH_API_KEY_ENV_NAME = "OSCE_DASHSCOPE_SPEECH_API_KEY"
DASHSCOPE_RERANK_API_KEY_ENV_NAME = "OSCE_DASHSCOPE_RERANK_API_KEY"

DEFAULT_DASHSCOPE_TEXT_BASE_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
DEFAULT_DASHSCOPE_TEXT_MODEL = "qwen-plus"

_DASHSCOPE_HOST = "dashscope.aliyuncs.com"
_DASHSCOPE_HOST_SUFFIX = ".dashscope.aliyuncs.com"
_MAAS_HOST_SUFFIX = ".maas.aliyuncs.com"


def is_trusted_dashscope_endpoint(url: str) -> bool:
    """Return whether *url* is an HTTPS endpoint owned by DashScope/Model Studio.

    The shared Alibaba Cloud key is deliberately limited to Alibaba-owned
    DashScope and MaaS hostnames.  Exact suffix checks prevent lookalike hosts
    such as ``dashscope.aliyuncs.com.example.org`` from receiving the key.
    """

    try:
        parsed = urlsplit(str(url or "").strip())
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        return False
    return (
        hostname == _DASHSCOPE_HOST
        or hostname.endswith(_DASHSCOPE_HOST_SUFFIX)
        or hostname.endswith(_MAAS_HOST_SUFFIX)
    )


def resolve_openai_compatible_api_key(
    explicit_api_key: str,
    *,
    base_url: str,
) -> str:
    """Resolve the server-managed text-model key without crossing providers.

    ``OSCE_OPENAI_API_KEY`` remains an explicit override for custom compatible
    gateways.  A shared DashScope or legacy speech key is inherited only when
    the destination is a trusted Alibaba Cloud endpoint.
    """

    normalized_explicit_key = str(explicit_api_key or "").strip()
    if normalized_explicit_key:
        return normalized_explicit_key
    if not is_trusted_dashscope_endpoint(base_url):
        return ""
    return _first_configured_key(
        (
            DASHSCOPE_SHARED_API_KEY_ENV_NAME,
            DASHSCOPE_SPEECH_API_KEY_ENV_NAME,
        )
    )


def resolve_dashscope_feature_api_key(
    explicit_api_key: str,
    *,
    target_urls: Iterable[str],
    fallback_env_names: Iterable[str] = (
        DASHSCOPE_SHARED_API_KEY_ENV_NAME,
    ),
) -> str:
    """Resolve a DashScope feature key while protecting shared credentials.

    Feature-specific keys may intentionally target a reviewed gateway. Shared
    credentials are inherited only when every destination is an Alibaba Cloud
    DashScope/MaaS HTTPS endpoint.
    """

    normalized_explicit_key = str(explicit_api_key or "").strip()
    if normalized_explicit_key:
        return normalized_explicit_key
    normalized_targets = [str(url or "").strip() for url in target_urls]
    if not normalized_targets or not all(
        is_trusted_dashscope_endpoint(url) for url in normalized_targets
    ):
        return ""
    return _first_configured_key(fallback_env_names)


def _first_configured_key(env_names: Iterable[str]) -> str:
    for env_name in env_names:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return ""


__all__ = [
    "DASHSCOPE_RERANK_API_KEY_ENV_NAME",
    "DASHSCOPE_SHARED_API_KEY_ENV_NAME",
    "DASHSCOPE_SPEECH_API_KEY_ENV_NAME",
    "DEFAULT_DASHSCOPE_TEXT_BASE_URL",
    "DEFAULT_DASHSCOPE_TEXT_MODEL",
    "is_trusted_dashscope_endpoint",
    "resolve_dashscope_feature_api_key",
    "resolve_openai_compatible_api_key",
]
