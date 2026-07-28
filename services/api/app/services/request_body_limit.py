from __future__ import annotations

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


REQUEST_BODY_TOO_LARGE_DETAIL = "request body is too large"


class _RequestBodyTooLarge(StarletteHTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=413,
            detail=REQUEST_BODY_TOO_LARGE_DETAIL,
            headers={"Connection": "close"},
        )


class RequestBodyLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_size: int,
        path_prefix: str = "/api",
    ) -> None:
        if max_body_size < 1:
            raise ValueError("max_body_size must be positive")
        self._app = app
        self._max_body_size = max_body_size
        self._path_prefix = path_prefix.rstrip("/") or "/"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._is_limited_path(str(scope.get("path", ""))):
            await self._app(scope, receive, send)
            return

        declared_length = _declared_content_length(scope)
        if declared_length is not None and declared_length > self._max_body_size:
            await _send_payload_too_large(scope, receive, send)
            return

        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self._max_body_size:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await _send_payload_too_large(scope, receive, send)

    def _is_limited_path(self, path: str) -> bool:
        if self._path_prefix == "/":
            return True
        return path == self._path_prefix or path.startswith(f"{self._path_prefix}/")


def _declared_content_length(scope: Scope) -> int | None:
    declared_lengths: list[int] = []
    for header_name, header_value in scope.get("headers", []):
        if header_name.lower() != b"content-length":
            continue
        try:
            parsed_length = int(header_value.strip())
        except (TypeError, ValueError):
            continue
        if parsed_length >= 0:
            declared_lengths.append(parsed_length)
    return max(declared_lengths) if declared_lengths else None


async def _send_payload_too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse(
        status_code=413,
        content={"detail": REQUEST_BODY_TOO_LARGE_DETAIL},
        headers={"Connection": "close"},
    )
    await response(scope, receive, send)


__all__ = [
    "REQUEST_BODY_TOO_LARGE_DETAIL",
    "RequestBodyLimitMiddleware",
]
