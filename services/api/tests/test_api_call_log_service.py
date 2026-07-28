from __future__ import annotations

import httpx

from app.services.api_call_log_service import ApiCallLogStore


def test_api_call_log_store_summarizes_provider_success_rate(tmp_path) -> None:
    store = ApiCallLogStore(tmp_path / "model_api_calls.jsonl")

    store.record(
        provider="openai_compatible",
        operation="chat.completions",
        model="gemini-3.5-flash",
        endpoint="https://gateway.example/v1/chat/completions?api_key=secret",
        success=True,
        duration_ms=120,
        status_code=200,
    )
    store.record(
        provider="openai_compatible",
        operation="chat.completions",
        model="gemini-3.5-flash",
        endpoint="https://gateway.example/v1/chat/completions",
        success=False,
        duration_ms=80,
        error=RuntimeError("api_key=secret should not leak"),
        status_code=401,
    )
    store.record(
        provider="vertex_gemini_embedding",
        operation="embed_content",
        model="gemini-embedding-001",
        endpoint="vertex://embed_content",
        success=True,
        duration_ms=30,
    )

    payload = store.build_admin_payload(limit=10)

    assert payload["summary"]["total_calls"] == 3
    assert payload["summary"]["success_calls"] == 2
    assert payload["summary"]["failed_calls"] == 1
    assert payload["summary"]["success_rate"] == 2 / 3
    assert payload["summary_by_provider"][0]["provider"] == "openai_compatible"
    assert payload["summary_by_provider"][0]["total_calls"] == 2
    assert payload["summary_by_provider"][0]["success_rate"] == 0.5
    assert payload["logs"][0]["provider"] == "vertex_gemini_embedding"
    assert payload["logs"][1]["endpoint"] == "https://gateway.example/v1/chat/completions"
    assert "secret" not in payload["logs"][1]["error_message"]


def test_api_call_log_store_extracts_http_status_error(tmp_path) -> None:
    store = ApiCallLogStore(tmp_path / "model_api_calls.jsonl")
    request = httpx.Request("POST", "https://primary.example/v1/chat/completions")
    response = httpx.Response(429, request=request, text="too many requests")

    store.record(
        provider="openai_compatible",
        operation="chat.completions",
        model="gemini-3.5-flash",
        endpoint=str(request.url),
        success=False,
        duration_ms=1,
        error=httpx.HTTPStatusError("429 too many requests", request=request, response=response),
    )

    payload = store.build_admin_payload(limit=1)

    assert payload["logs"][0]["status_code"] == 429
    assert payload["logs"][0]["error_type"] == "HTTPStatusError"


def test_api_call_log_store_removes_url_credentials_and_google_keys(tmp_path) -> None:
    store = ApiCallLogStore(tmp_path / "model_api_calls.jsonl")

    store.record(
        provider="vertex_gemini",
        operation="generate_content",
        model="gemini-test",
        endpoint=(
            "https://endpoint-user:endpoint-password@gateway.example:8443/v1/models"
            "?x-goog-api-key=endpoint-secret"
        ),
        success=False,
        duration_ms=1,
        error=RuntimeError(
            "request to https://error-user:error-password@gateway.example/v1/models"
            "?key=query-secret failed; x-goog-api-key=header-secret"
        ),
    )

    log = store.build_admin_payload(limit=1)["logs"][0]
    serialized_log = str(log)
    assert log["endpoint"] == "https://gateway.example:8443/v1/models"
    assert log["error_message"] == (
        "request to https://gateway.example/v1/models failed; "
        "x-goog-api-key=[redacted]"
    )
    for secret in (
        "endpoint-user",
        "endpoint-password",
        "endpoint-secret",
        "error-user",
        "error-password",
        "query-secret",
        "header-secret",
    ):
        assert secret not in serialized_log


def test_api_call_log_store_extracts_generic_provider_status_code(tmp_path) -> None:
    class ProviderError(RuntimeError):
        code = 429

    store = ApiCallLogStore(tmp_path / "model_api_calls.jsonl")
    store.record(
        provider="gemini",
        operation="generate_content",
        model="gemini-test",
        endpoint="gemini://generate_content",
        success=False,
        duration_ms=1,
        error=ProviderError("rate limited"),
    )

    assert store.build_admin_payload(limit=1)["logs"][0]["status_code"] == 429
