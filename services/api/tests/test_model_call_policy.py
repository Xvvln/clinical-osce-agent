from __future__ import annotations

import asyncio
import time
from contextvars import ContextVar
from threading import Event

import pytest
import httpx
from fastapi import Request, Response
from fastapi.testclient import TestClient

from app import main
from app.services.api_call_log_service import API_CALL_CONTEXT
from app.services.model_call_policy import (
    BoundedModelCallExecutor,
    MODEL_CALL_DEADLINE,
    ModelProviderOverloadedError,
    ModelProviderTimeoutError,
    ModelRequestAdmissionGate,
    model_call_budget,
    run_model_provider_call,
)


def test_bounded_executor_rejects_overload_without_queueing() -> None:
    executor = BoundedModelCallExecutor(
        max_concurrency=1,
        thread_name_prefix="test-model-overload",
    )
    entered = Event()
    release = Event()

    def blocking_call() -> str:
        entered.set()
        assert release.wait(timeout=5)
        return "first"

    first = executor.submit(blocking_call)
    assert entered.wait(timeout=2)
    started_at = time.monotonic()

    with pytest.raises(ModelProviderOverloadedError):
        executor.submit(lambda: "must-not-queue")

    assert time.monotonic() - started_at < 0.2
    release.set()
    assert first.result(timeout=2) == "first"
    assert executor.run(lambda: "recovered", timeout_seconds=1) == "recovered"


def test_timed_out_call_keeps_its_slot_until_provider_really_returns() -> None:
    executor = BoundedModelCallExecutor(
        max_concurrency=1,
        thread_name_prefix="test-model-timeout",
    )
    entered = Event()
    release = Event()
    finished = Event()

    def blocking_call() -> None:
        entered.set()
        try:
            assert release.wait(timeout=5)
        finally:
            finished.set()

    started_at = time.monotonic()
    with pytest.raises(ModelProviderTimeoutError):
        executor.run(blocking_call, timeout_seconds=0.05)

    assert entered.is_set()
    assert time.monotonic() - started_at < 0.5
    with pytest.raises(ModelProviderOverloadedError):
        executor.submit(lambda: None)

    release.set()
    assert finished.wait(timeout=2)
    deadline = time.monotonic() + 2
    while True:
        try:
            assert executor.run(
                lambda: "available",
                timeout_seconds=1,
            ) == "available"
            break
        except ModelProviderOverloadedError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def test_model_call_executor_propagates_request_context() -> None:
    executor = BoundedModelCallExecutor(
        max_concurrency=1,
        thread_name_prefix="test-model-context",
    )
    request_marker: ContextVar[str] = ContextVar(
        "request_marker",
        default="missing",
    )
    token = request_marker.set("student-a")
    try:
        assert executor.run(
            request_marker.get,
            timeout_seconds=1,
        ) == "student-a"
    finally:
        request_marker.reset(token)


def _capture_api_call_context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    path: str,
    user: dict[str, str] | None,
) -> dict[str, str]:
    monkeypatch.setattr(
        main.auth_store,
        "get_user_by_session_token",
        lambda _: user,
    )
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )
    observed: dict[str, str] = {}

    async def call_next(_: Request) -> Response:
        observed.update(API_CALL_CONTEXT.get())
        return Response(status_code=204)

    asyncio.run(main.bind_api_call_log_context(request, call_next))
    return observed


def test_api_call_context_binds_safe_session_path_without_leaking_to_other_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = {"user_id": "student-a", "email": "student@example.test"}
    session_id = "8bc85268-6a0b-4c2b-b86f-a8ddf6044332"

    session_context = _capture_api_call_context(
        monkeypatch,
        path=f"/api/sessions/{session_id}/report/generate",
        user=user,
    )
    non_session_context = _capture_api_call_context(
        monkeypatch,
        path="/api/model-config/runtime",
        user=user,
    )

    assert session_context["session_id"] == session_id
    assert non_session_context["session_id"] == ""
    assert API_CALL_CONTEXT.get() == {}


@pytest.mark.parametrize(
    "path",
    [
        "/api/sessions//message",
        "/api/sessions/session.with.dot/message",
        "/api/sessions/%2Fforged/message",
        "/api/sessions/会话/message",
    ],
)
def test_api_call_context_rejects_malformed_or_unauthenticated_session_ids(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticated_context = _capture_api_call_context(
        monkeypatch,
        path=path,
        user={"user_id": "student-a", "email": "student@example.test"},
    )
    unauthenticated_context = _capture_api_call_context(
        monkeypatch,
        path="/api/sessions/session-forged/message",
        user=None,
    )

    assert authenticated_context["session_id"] == ""
    assert unauthenticated_context["session_id"] == ""


def test_nested_model_calls_share_one_monotonic_budget() -> None:
    executor = BoundedModelCallExecutor(
        max_concurrency=1,
        thread_name_prefix="test-model-budget",
    )
    started_at = time.monotonic()

    with model_call_budget(0.12):
        assert run_model_provider_call(
            lambda: time.sleep(0.04) or "first",
            timeout_seconds=1,
            executor=executor,
        ) == "first"
        with pytest.raises(ModelProviderTimeoutError):
            run_model_provider_call(
                lambda: time.sleep(0.3),
                timeout_seconds=1,
                executor=executor,
            )

    assert time.monotonic() - started_at < 0.3


def test_request_admission_gate_never_waits_and_recovers() -> None:
    gate = ModelRequestAdmissionGate(max_concurrency=2)

    assert gate.try_acquire() is True
    assert gate.try_acquire() is True
    assert gate.active == 2
    assert gate.try_acquire() is False

    gate.release()
    assert gate.try_acquire() is True
    gate.release()
    gate.release()
    assert gate.active == 0
    with pytest.raises(RuntimeError, match="released too often"):
        gate.release()


def test_model_request_dependency_rejects_before_sync_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = ModelRequestAdmissionGate(max_concurrency=1)
    assert gate.try_acquire()
    monkeypatch.setattr(main, "model_request_admission_gate", gate)
    monkeypatch.setattr(
        main.auth_store,
        "get_user_by_session_token",
        lambda _: {"user_id": "student-a", "email": "student@example.com"},
    )

    try:
        with TestClient(main.app) as client:
            client.cookies.set(
                main.AUTH_COOKIE_NAME,
                "valid-session",
            )
            response = client.post("/api/sessions/session-a/hint")
    finally:
        gate.release()

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json() == {
        "detail": main.MODEL_PROVIDER_BUSY_DETAIL,
    }


def test_model_request_dependency_leaves_unauthenticated_request_ungated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = ModelRequestAdmissionGate(max_concurrency=1)
    assert gate.try_acquire()
    monkeypatch.setattr(main, "model_request_admission_gate", gate)
    monkeypatch.setattr(
        main.auth_store,
        "get_user_by_session_token",
        lambda _: None,
    )

    try:
        with TestClient(main.app) as client:
            response = client.post("/api/sessions/session-a/hint")
    finally:
        gate.release()

    assert response.status_code == 401


def test_model_request_dependency_holds_lease_through_background_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = ModelRequestAdmissionGate(max_concurrency=1)
    monkeypatch.setattr(main, "model_request_admission_gate", gate)
    monkeypatch.setattr(
        main.auth_store,
        "get_user_by_session_token",
        lambda _: {"user_id": "student-a", "email": "student@example.com"},
    )
    monkeypatch.setattr(
        main,
        "_require_owned_session",
        lambda *_: {"student_id": "student-a"},
    )
    monkeypatch.setattr(
        main.osce_session_service,
        "read_report",
        lambda _: {
            "report_id": "report-a",
            "session_id": "session-a",
            "personal_skill_candidate": {"status": "generation_pending"},
        },
    )
    observed: dict[str, object] = {}

    def background_enrichment(
        session_id: str,
        user_id: str,
    ) -> None:
        observed["session_id"] = session_id
        observed["user_id"] = user_id
        observed["gate_active"] = gate.active
        observed["deadline"] = MODEL_CALL_DEADLINE.get()
        observed["audit_session_id"] = API_CALL_CONTEXT.get().get("session_id")

    monkeypatch.setattr(
        main,
        "_enrich_report_optional_agents_for_user",
        background_enrichment,
    )

    with TestClient(main.app) as client:
        client.cookies.set(
            main.AUTH_COOKIE_NAME,
            "valid-session",
        )
        response = client.post("/api/sessions/session-a/report/enrich")

    assert response.status_code == 202
    assert observed == {
        "session_id": "session-a",
        "user_id": "student-a",
        "gate_active": 1,
        "deadline": observed["deadline"],
        "audit_session_id": "session-a",
    }
    assert isinstance(observed["deadline"], float)
    assert MODEL_CALL_DEADLINE.get() is None
    assert gate.active == 0


def test_report_model_requests_have_a_longer_bounded_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(main.REPORT_MODEL_CALL_TIMEOUT_SECONDS_ENV, raising=False)

    assert main._model_request_timeout_seconds("/api/sessions/a/report/generate") == 90.0
    assert main._model_request_timeout_seconds("/api/sessions/a/report/enrich") == 90.0
    assert main._model_request_timeout_seconds("/api/sessions/a/message") is None

    monkeypatch.setenv(main.REPORT_MODEL_CALL_TIMEOUT_SECONDS_ENV, "120")
    assert main._model_request_timeout_seconds("/api/sessions/a/report/generate") == 120.0
    monkeypatch.setenv(main.REPORT_MODEL_CALL_TIMEOUT_SECONDS_ENV, "9999")
    assert main._model_request_timeout_seconds("/api/sessions/a/report/generate") == 300.0
    monkeypatch.setenv(main.REPORT_MODEL_CALL_TIMEOUT_SECONDS_ENV, "invalid")
    assert main._model_request_timeout_seconds("/api/sessions/a/report/generate") == 90.0


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            ModelProviderOverloadedError("busy"),
            503,
            main.MODEL_PROVIDER_BUSY_DETAIL,
        ),
        (
            ModelProviderTimeoutError("late"),
            504,
            main.MODEL_PROVIDER_TIMEOUT_DETAIL,
        ),
    ],
)
def test_model_policy_errors_have_stable_gateway_mapping(
    error: Exception,
    expected_status: int,
    expected_detail: str,
) -> None:
    mapped = main._model_provider_gateway_error(error)

    assert mapped.status_code == expected_status
    assert mapped.detail == expected_detail
    if expected_status == 503:
        assert mapped.headers == {"Retry-After": "1"}


def test_http_provider_rate_limit_preserves_safe_retry_after() -> None:
    request = httpx.Request(
        "POST",
        "https://provider.example/v1/chat/completions",
    )
    response = httpx.Response(
        status_code=429,
        request=request,
        headers={"Retry-After": "7"},
        json={"error": {"message": "provider-internal detail"}},
    )

    mapped = main._model_provider_gateway_error(
        httpx.HTTPStatusError(
            "rate limited",
            request=request,
            response=response,
        )
    )

    assert mapped.status_code == 503
    assert mapped.detail == main.MODEL_PROVIDER_BUSY_DETAIL
    assert mapped.headers == {"Retry-After": "7"}


@pytest.mark.parametrize("retry_after", ["", "0", "301", "not-a-number"])
def test_http_provider_rate_limit_rejects_unsafe_retry_after(
    retry_after: str,
) -> None:
    request = httpx.Request("POST", "https://provider.example/v1")
    response = httpx.Response(
        status_code=429,
        request=request,
        headers={"Retry-After": retry_after},
    )

    mapped = main._model_provider_gateway_error(
        httpx.HTTPStatusError(
            "rate limited",
            request=request,
            response=response,
        )
    )

    assert mapped.headers == {"Retry-After": "1"}


def test_google_provider_resource_exhausted_maps_to_retryable_busy() -> None:
    from google.genai import errors as google_genai_errors

    mapped = main._model_provider_gateway_error(
        google_genai_errors.ClientError(
            429,
            {
                "error": {
                    "code": 429,
                    "message": "quota exhausted",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )
    )

    assert mapped.status_code == 503
    assert mapped.detail == main.MODEL_PROVIDER_BUSY_DETAIL
    assert mapped.headers == {"Retry-After": "1"}


def test_http_provider_timeout_maps_to_gateway_timeout() -> None:
    mapped = main._model_provider_gateway_error(
        httpx.ReadTimeout(
            "provider timed out",
            request=httpx.Request("POST", "https://provider.example/v1"),
        )
    )

    assert mapped.status_code == 504
    assert mapped.detail == main.MODEL_PROVIDER_TIMEOUT_DETAIL
