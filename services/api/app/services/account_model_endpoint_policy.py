from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

from app.services.deployment_config import get_deployment_mode

ACCOUNT_MODEL_ALLOWED_HOSTS_ENV_NAME = "CLINICAL_OSCE_ACCOUNT_MODEL_ALLOWED_HOSTS"
ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS_ENV_NAME = (
    "CLINICAL_OSCE_ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS"
)

DEFAULT_ACCOUNT_MODEL_ALLOWED_HOSTS = frozenset(
    {
        "api.anthropic.com",
        "api.openai.com",
        "generativelanguage.googleapis.com",
    }
)
DIRECT_PROXY_VALUES = frozenset({"", "direct", "none", "false", "off", "no"})
ACCOUNT_MODEL_ENDPOINT_POLICY_ERROR = (
    "账号级模型地址不在服务端允许范围内；请使用已批准的 HTTPS provider 地址。"
)
ACCOUNT_MODEL_PROXY_POLICY_ERROR = (
    "共享服务不允许账号级代理；请使用 direct 或由管理员配置服务端代理。"
)
ACCOUNT_MODEL_PROVIDER_POLICY_ERROR = (
    "共享服务不允许账号使用自定义后端或服务端 ADC。"
)


def validate_account_model_endpoint_policy(
    *,
    provider: str,
    base_url: str,
    proxy_url: str,
) -> None:
    normalized_provider = _normalize_provider(provider)
    if unsafe_account_model_endpoints_enabled():
        return

    if normalized_provider in {"custom_backend", "vertex_gemini_adc"}:
        raise ValueError(ACCOUNT_MODEL_PROVIDER_POLICY_ERROR)
    if _proxy_is_enabled(proxy_url):
        raise ValueError(ACCOUNT_MODEL_PROXY_POLICY_ERROR)

    if normalized_provider == "vertex_gemini_api_key":
        return

    default_base_url = {
        "gemini": "https://generativelanguage.googleapis.com",
        "openai_compatible": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com",
    }.get(normalized_provider)
    if default_base_url is None:
        raise ValueError(ACCOUNT_MODEL_PROVIDER_POLICY_ERROR)
    _validate_allowed_https_url(base_url.strip() or default_base_url)


def unsafe_account_model_endpoints_enabled() -> bool:
    return (
        get_deployment_mode() == "local-dev"
        and _truthy(os.environ.get(ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS_ENV_NAME))
    )


def account_model_allowed_hosts() -> frozenset[str]:
    configured_hosts = {
        _normalize_hostname(host)
        for host in os.environ.get(ACCOUNT_MODEL_ALLOWED_HOSTS_ENV_NAME, "").split(",")
        if host.strip()
    }
    return frozenset(
        host
        for host in {*DEFAULT_ACCOUNT_MODEL_ALLOWED_HOSTS, *configured_hosts}
        if host
    )


def _normalize_provider(provider: str) -> str:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "local_backend":
        return "custom_backend"
    return normalized_provider


def _proxy_is_enabled(proxy_url: str) -> bool:
    return str(proxy_url or "").strip().lower() not in DIRECT_PROXY_VALUES


def _validate_allowed_https_url(raw_url: str) -> None:
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(ACCOUNT_MODEL_ENDPOINT_POLICY_ERROR) from exc

    hostname = _normalize_hostname(parsed.hostname or "")
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or hostname not in account_model_allowed_hosts()
        or _hostname_is_local_or_ip_literal(hostname)
    ):
        raise ValueError(ACCOUNT_MODEL_ENDPOINT_POLICY_ERROR)


def _normalize_hostname(hostname: str) -> str:
    return str(hostname or "").strip().lower().rstrip(".")


def _hostname_is_local_or_ip_literal(hostname: str) -> bool:
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
        or hostname.endswith(".internal")
    ):
        return True
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "ACCOUNT_MODEL_ALLOWED_HOSTS_ENV_NAME",
    "ACCOUNT_MODEL_ENDPOINT_POLICY_ERROR",
    "ACCOUNT_MODEL_PROVIDER_POLICY_ERROR",
    "ACCOUNT_MODEL_PROXY_POLICY_ERROR",
    "ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS_ENV_NAME",
    "account_model_allowed_hosts",
    "unsafe_account_model_endpoints_enabled",
    "validate_account_model_endpoint_policy",
]
