from __future__ import annotations

import json as json_module
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

from pydantic import BaseModel

from app.services import openai_compatible_chat_client as module
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings


class DemoJsonResponse(BaseModel):
    message: str


class FakeChatCompletionResponse:
    is_success = True
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"message":"真实调用路径返回的结构化内容"}',
                    },
                }
            ],
        }


class FakeHttpxClient:
    instances: list["FakeHttpxClient"] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.calls: list[dict[str, Any]] = []
        self.instances.append(self)

    def __enter__(self) -> "FakeHttpxClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeChatCompletionResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})
        return FakeChatCompletionResponse()


def test_openai_compatible_chat_client_posts_chat_completion_with_proxy_and_auth(monkeypatch) -> None:
    FakeHttpxClient.instances = []
    monkeypatch.setattr(module.httpx, "Client", FakeHttpxClient)

    client = OpenAICompatibleChatClient(
        OpenAICompatibleSettings(
            enabled=True,
            api_key="openai-secret-value",
            base_url="https://api.proxy.example/v1/",
            model="gemini-via-clprox",
            proxy_url="http://127.0.0.1:7897",
        )
    )

    result = client.complete_json(
        system_prompt="只输出 JSON。",
        payload={"case_id": "appendicitis_001", "student_message": "哪里疼？"},
        response_model=DemoJsonResponse,
        temperature=0.2,
    )

    assert result == DemoJsonResponse(message="真实调用路径返回的结构化内容")
    assert len(FakeHttpxClient.instances) == 1
    http_client = FakeHttpxClient.instances[0]
    assert http_client.kwargs["proxy"] == "http://127.0.0.1:7897"
    assert http_client.calls[0]["url"] == "https://api.proxy.example/v1/chat/completions"
    assert http_client.calls[0]["headers"]["Authorization"] == "Bearer openai-secret-value"
    request_body = http_client.calls[0]["json"]
    assert request_body["model"] == "gemini-via-clprox"
    assert request_body["temperature"] == 0.2
    assert request_body["messages"] == [
        {"role": "system", "content": "只输出 JSON。"},
        {
            "role": "user",
            "content": '{"case_id": "appendicitis_001", "student_message": "哪里疼？"}',
        },
    ]
    assert request_body["response_format"] == {"type": "json_object"}


class RecordingOpenAICompatibleHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        self.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
                "body": json_module.loads(body),
            }
        )
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"message":"本地真实 HTTP 服务返回的结构化内容"}',
                    }
                }
            ]
        }
        response_body = json_module.dumps(response_payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, *_: object) -> None:
        return None


def test_openai_compatible_chat_client_can_call_real_http_endpoint() -> None:
    RecordingOpenAICompatibleHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingOpenAICompatibleHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        client = OpenAICompatibleChatClient(
            OpenAICompatibleSettings(
                enabled=True,
                api_key="local-secret",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                model="local-openai-compatible-model",
                proxy_url="direct",
            )
        )
        result = client.complete_json(
            system_prompt="只输出 JSON。",
            payload={"ping": "clinical-osce-agent"},
            response_model=DemoJsonResponse,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result == DemoJsonResponse(message="本地真实 HTTP 服务返回的结构化内容")
    assert RecordingOpenAICompatibleHandler.requests == [
        {
            "path": "/v1/chat/completions",
            "authorization": "Bearer local-secret",
            "body": {
                "model": "local-openai-compatible-model",
                "messages": [
                    {"role": "system", "content": "只输出 JSON。"},
                    {"role": "user", "content": '{"ping": "clinical-osce-agent"}'},
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
        }
    ]
