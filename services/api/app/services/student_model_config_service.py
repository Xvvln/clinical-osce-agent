from __future__ import annotations

from typing import Any

import httpx


SUPPORTED_STUDENT_MODEL_CONFIG_PROVIDERS = {"local_backend", "gemini", "openai_compatible"}
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_OPENAI_COMPATIBLE_BASE_URL = "https://api.openai.com/v1"
STUDENT_MODEL_CONFIG_TIMEOUT_SECONDS = 5.0


def test_student_model_config_connectivity(config: dict[str, str]) -> dict[str, object]:
    provider = _normalize_provider(config.get("provider", ""))
    api_key = _normalize_text(config.get("api_key", ""))
    model = _normalize_text(config.get("model", ""))
    base_url = _normalize_text(config.get("base_url", ""))
    proxy_url = _normalize_text(config.get("proxy_url", ""))

    if provider == "local_backend":
        return {
            "ok": True,
            "provider": provider,
            "message": "已连接本地 API 服务。",
            "checked_url": "/health",
        }

    if provider == "gemini":
        if not api_key:
            raise ValueError("api_key is required for gemini")
        endpoint = _join_url(base_url or DEFAULT_GEMINI_BASE_URL, "/v1beta/models")
        return _test_http_endpoint(
            provider=provider,
            endpoint=endpoint,
            headers={"x-goog-api-key": api_key},
            proxy_url=proxy_url,
            success_message="Gemini Developer API 连通性测试通过。",
        )

    if not api_key:
        raise ValueError("api_key is required for openai_compatible")
    if not model:
        raise ValueError("model is required for openai_compatible")
    endpoint = _join_url(base_url or DEFAULT_OPENAI_COMPATIBLE_BASE_URL, "/models")
    return _test_http_endpoint(
        provider=provider,
        endpoint=endpoint,
        headers={"Authorization": f"Bearer {api_key}"},
        proxy_url=proxy_url,
        success_message="OpenAI 兼容服务端连通性测试通过。",
    )


def _normalize_provider(value: str) -> str:
    provider = _normalize_text(value)
    if provider not in SUPPORTED_STUDENT_MODEL_CONFIG_PROVIDERS:
        raise ValueError(f"unsupported provider: {provider or 'empty'}")
    return provider


def _normalize_text(value: str) -> str:
    return str(value or "").strip()


def _join_url(base_url: str, suffix: str) -> str:
    return f"{base_url.rstrip('/')}{suffix}"


def _test_http_endpoint(
    *,
    provider: str,
    endpoint: str,
    headers: dict[str, str],
    proxy_url: str,
    success_message: str,
) -> dict[str, object]:
    try:
        client_options: dict[str, Any] = {
            "timeout": STUDENT_MODEL_CONFIG_TIMEOUT_SECONDS,
            "follow_redirects": True,
        }
        if proxy_url:
            client_options["proxy"] = proxy_url
        with httpx.Client(**client_options) as client:
            response = client.get(endpoint, headers=headers)
    except httpx.HTTPError as exc:
        return _connectivity_result(
            ok=False,
            provider=provider,
            message=f"连通性测试失败：{exc.__class__.__name__}",
            checked_url=endpoint,
        )

    if response.is_success:
        return _connectivity_result(
            ok=True,
            provider=provider,
            message=success_message,
            checked_url=endpoint,
        )

    return _connectivity_result(
        ok=False,
        provider=provider,
        message=f"连通性测试失败：HTTP {response.status_code}",
        checked_url=endpoint,
    )


def _connectivity_result(*, ok: bool, provider: str, message: str, checked_url: str) -> dict[str, object]:
    return {
        "ok": ok,
        "provider": provider,
        "message": message,
        "checked_url": checked_url,
    }


__all__ = ["test_student_model_config_connectivity"]
