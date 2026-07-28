from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Iterable
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app import main
from app.services.request_body_limit import REQUEST_BODY_TOO_LARGE_DETAIL, RequestBodyLimitMiddleware


def _http_scope(*, path: str, headers: Iterable[tuple[bytes, bytes]] = ()) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": list(headers),
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }


def _response_status(messages: list[dict[str, Any]]) -> int:
    return next(message["status"] for message in messages if message["type"] == "http.response.start")


def _response_body(messages: list[dict[str, Any]]) -> dict[str, object]:
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return json.loads(body)


def test_declared_oversized_body_is_rejected_before_downstream_app() -> None:
    downstream_called = False
    sent_messages: list[dict[str, Any]] = []

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_called
        downstream_called = True

    async def receive() -> dict[str, Any]:
        raise AssertionError("declared oversized request body must not be read")

    async def send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    middleware = RequestBodyLimitMiddleware(downstream, max_body_size=5)
    asyncio.run(
        middleware(
            _http_scope(path="/api/upload", headers=[(b"content-length", b"6")]),
            receive,
            send,
        )
    )

    assert downstream_called is False
    assert _response_status(sent_messages) == 413
    assert _response_body(sent_messages) == {"detail": REQUEST_BODY_TOO_LARGE_DETAIL}


def test_chunked_body_without_content_length_is_rejected_at_cumulative_limit() -> None:
    downstream_completed = False
    sent_messages: list[dict[str, Any]] = []
    request_messages = iter(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ]
    )

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_completed
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        downstream_completed = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, Any]:
        return next(request_messages)

    async def send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    middleware = RequestBodyLimitMiddleware(downstream, max_body_size=5)
    asyncio.run(middleware(_http_scope(path="/api/upload"), receive, send))

    assert downstream_completed is False
    assert _response_status(sent_messages) == 413
    assert _response_body(sent_messages) == {"detail": REQUEST_BODY_TOO_LARGE_DETAIL}


def test_chunked_body_at_exact_limit_reaches_downstream_app() -> None:
    downstream_body = b""
    sent_messages: list[dict[str, Any]] = []
    request_messages = iter(
        [
            {"type": "http.request", "body": b"12", "more_body": True},
            {"type": "http.request", "body": b"345", "more_body": False},
        ]
    )

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_body
        while True:
            message = await receive()
            downstream_body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, Any]:
        return next(request_messages)

    async def send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    middleware = RequestBodyLimitMiddleware(downstream, max_body_size=5)
    asyncio.run(middleware(_http_scope(path="/api/upload"), receive, send))

    assert downstream_body == b"12345"
    assert _response_status(sent_messages) == 204


def test_non_api_body_is_not_subject_to_api_limit() -> None:
    downstream_body = b""
    sent_messages: list[dict[str, Any]] = []
    request_messages = iter(
        [{"type": "http.request", "body": b"123456", "more_body": False}]
    )

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_body
        downstream_body = (await receive())["body"]
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, Any]:
        return next(request_messages)

    async def send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    middleware = RequestBodyLimitMiddleware(downstream, max_body_size=5)
    asyncio.run(middleware(_http_scope(path="/health"), receive, send))

    assert downstream_body == b"123456"
    assert _response_status(sent_messages) == 204


def test_api_integration_rejects_oversized_content_length_with_private_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/audio/transcriptions",
            headers={"Content-Length": str(main.API_REQUEST_BODY_MAX_BYTES + 1)},
            content=b"x",
        )

    assert response.status_code == 413
    assert response.json() == {"detail": REQUEST_BODY_TOO_LARGE_DETAIL}
    assert response.headers["cache-control"] == main.API_PRIVATE_CACHE_CONTROL
    assert response.headers["connection"] == "close"


def test_fastapi_stack_rejects_streamed_body_without_content_length() -> None:
    test_app = FastAPI()
    test_app.add_middleware(RequestBodyLimitMiddleware, max_body_size=5)
    route_completed = False

    @test_app.post("/api/upload")
    async def upload(request: Request) -> dict[str, bool]:
        nonlocal route_completed
        await request.body()
        route_completed = True
        return {"ok": True}

    with TestClient(test_app) as client:
        response = client.post(
            "/api/upload",
            content=iter([b"123", b"456"]),
        )

    assert response.status_code == 413
    assert response.json() == {"detail": REQUEST_BODY_TOO_LARGE_DETAIL}
    assert response.headers["connection"] == "close"
    assert route_completed is False


def test_main_app_preserves_413_for_chunked_json_body_without_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    sent_messages: list[dict[str, Any]] = []
    json_prefix = b'{"email":"'
    first_chunk = json_prefix + (
        b"a" * (main.API_REQUEST_BODY_MAX_BYTES - len(json_prefix))
    )
    request_messages = iter(
        [
            {"type": "http.request", "body": first_chunk, "more_body": True},
            {"type": "http.request", "body": b"x", "more_body": False},
        ]
    )

    async def receive() -> dict[str, Any]:
        return next(request_messages)

    async def send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    asyncio.run(
        main.app(
            _http_scope(
                path="/api/auth/login",
                headers=[(b"content-type", b"application/json")],
            ),
            receive,
            send,
        )
    )

    response_starts = [
        message
        for message in sent_messages
        if message["type"] == "http.response.start"
    ]
    assert len(response_starts) == 1
    assert _response_status(sent_messages) == 413
    assert _response_body(sent_messages) == {"detail": REQUEST_BODY_TOO_LARGE_DETAIL}
    response_headers = {
        name.decode("latin-1").lower(): value.decode("latin-1")
        for name, value in response_starts[0]["headers"]
    }
    assert response_headers["connection"] == "close"
    assert response_headers["cache-control"] == main.API_PRIVATE_CACHE_CONTROL


def test_rag_document_decoded_size_limit_returns_413(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "RAG_DOCUMENT_MAX_BYTES", 5)
    request = main.AdminRagDocumentUploadRequest(
        scope="global",
        file_name="oversized.txt",
        content_base64=base64.b64encode(b"123456").decode("ascii"),
    )

    with pytest.raises(HTTPException) as exc_info:
        main._build_admin_rag_document_items(request)

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == "document is too large"
