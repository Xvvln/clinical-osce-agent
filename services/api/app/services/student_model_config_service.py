from __future__ import annotations

import json
import os
from typing import Any

import httpx
from google import genai
from google.genai import types


SUPPORTED_STUDENT_MODEL_CONFIG_PROVIDERS = {
    "custom_backend",
    "local_backend",
    "gemini",
    "vertex_gemini_adc",
    "vertex_gemini_api_key",
    "openai_compatible",
}
DEFAULT_CUSTOM_BACKEND_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_OPENAI_COMPATIBLE_BASE_URL = "https://api.openai.com/v1"
DEFAULT_VERTEX_GEMINI_LOCATION = "global"
STUDENT_MODEL_CONFIG_TIMEOUT_SECONDS = 5.0


def test_student_model_config_connectivity(config: dict[str, str]) -> dict[str, object]:
    provider = _normalize_provider(config.get("provider", ""))
    api_key = _normalize_text(config.get("api_key", ""))
    model = _normalize_text(config.get("model", ""))
    base_url = _normalize_text(config.get("base_url", ""))
    proxy_url = _normalize_text(config.get("proxy_url", ""))

    if provider == "custom_backend":
        endpoint = _join_url(base_url or DEFAULT_CUSTOM_BACKEND_BASE_URL, "/health")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        return _test_http_endpoint(
            provider=provider,
            endpoint=endpoint,
            headers=headers,
            proxy_url=proxy_url,
            success_message="自定义后端连通性测试通过。",
        )

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

    if provider == "vertex_gemini_adc":
        if not base_url:
            raise ValueError("project is required for vertex_gemini_adc")
        if not model:
            raise ValueError("model is required for vertex_gemini_adc")
        return _test_vertex_gemini_adc(
            project=base_url,
            location=DEFAULT_VERTEX_GEMINI_LOCATION,
            model=model,
            proxy_url=proxy_url,
        )

    if provider == "vertex_gemini_api_key":
        if not api_key:
            raise ValueError("api_key is required for vertex_gemini_api_key")
        if not model:
            raise ValueError("model is required for vertex_gemini_api_key")
        return _test_vertex_gemini_api_key(
            api_key=api_key,
            model=model,
            proxy_url=proxy_url,
        )

    if not api_key:
        raise ValueError("api_key is required for openai_compatible")
    if not model:
        raise ValueError("model is required for openai_compatible")
    endpoint = _join_url(base_url or DEFAULT_OPENAI_COMPATIBLE_BASE_URL, "/chat/completions")
    return _test_http_endpoint(
        provider=provider,
        endpoint=endpoint,
        headers={"Authorization": f"Bearer {api_key}"},
        method="POST",
        body={
            "model": model,
            "messages": [
                {"role": "system", "content": "只输出 JSON。"},
                {"role": "user", "content": json.dumps({"ping": "clinical-osce-agent"}, ensure_ascii=False, separators=(",", ":"))},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        },
        proxy_url=proxy_url,
        success_message="OpenAI 兼容服务端连通性测试通过。",
    )


def _normalize_provider(value: str) -> str:
    provider = _normalize_text(value)
    if provider == "local_backend":
        return "custom_backend"
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
    method: str = "GET",
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    try:
        client_options: dict[str, Any] = {
            "timeout": STUDENT_MODEL_CONFIG_TIMEOUT_SECONDS,
            "follow_redirects": True,
            "trust_env": False,
        }
        if _should_use_proxy(proxy_url):
            client_options["proxy"] = proxy_url
        with httpx.Client(**client_options) as client:
            if method == "POST":
                response = client.post(endpoint, headers=headers, json=body or {})
            else:
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


def _test_vertex_gemini_adc(*, project: str, location: str, model: str, proxy_url: str) -> dict[str, object]:
    checked_url = f"vertex://{project}/{location}/{model}"
    try:
        _apply_process_proxy(proxy_url)
        client = genai.Client(vertexai=True, project=project, location=location)
        client.models.generate_content(
            model=model,
            contents=json.dumps({"ping": "clinical-osce-agent"}, ensure_ascii=False, separators=(",", ":")),
            config=types.GenerateContentConfig(
                system_instruction="只输出 JSON。",
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:
        return _connectivity_result(
            ok=False,
            provider="vertex_gemini_adc",
            message=f"Vertex Gemini ADC 连通性测试失败：{exc.__class__.__name__}",
            checked_url=checked_url,
        )
    return _connectivity_result(
        ok=True,
        provider="vertex_gemini_adc",
        message="Vertex Gemini ADC 连通性测试通过。",
        checked_url=checked_url,
    )


def _test_vertex_gemini_api_key(*, api_key: str, model: str, proxy_url: str) -> dict[str, object]:
    checked_url = f"vertex-api-key://express/{model}"
    try:
        _apply_process_proxy(proxy_url)
        client = genai.Client(vertexai=True, api_key=api_key)
        client.models.generate_content(
            model=model,
            contents=json.dumps({"ping": "clinical-osce-agent"}, ensure_ascii=False, separators=(",", ":")),
            config=types.GenerateContentConfig(
                system_instruction="只输出 JSON。",
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:
        return _connectivity_result(
            ok=False,
            provider="vertex_gemini_api_key",
            message=f"Vertex Gemini API Key 连通性测试失败：{exc.__class__.__name__}",
            checked_url=checked_url,
        )
    return _connectivity_result(
        ok=True,
        provider="vertex_gemini_api_key",
        message="Vertex Gemini API Key 连通性测试通过。",
        checked_url=checked_url,
    )


def _apply_process_proxy(proxy_url: str) -> None:
    if not _should_use_proxy(proxy_url):
        return
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ["ALL_PROXY"] = proxy_url


def _should_use_proxy(proxy_url: str) -> bool:
    normalized = proxy_url.strip().lower()
    return bool(normalized and normalized not in {"direct", "none", "false", "off", "no"})


__all__ = ["test_student_model_config_connectivity"]
