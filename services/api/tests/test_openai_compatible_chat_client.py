from __future__ import annotations

import json as json_module
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.services import openai_compatible_chat_client as module
from app.services.api_call_log_service import ApiCallLogStore
from app.services.model_call_policy import ModelProviderTimeoutError
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.runtime_model_config_store import RuntimeModelConfig


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


class FakePrimaryFailureResponse:
    status_code = 503

    def raise_for_status(self) -> None:
        request = httpx.Request("POST", "https://primary.example/v1/chat/completions")
        response = httpx.Response(self.status_code, request=request, text="primary unavailable")
        raise httpx.HTTPStatusError("primary unavailable", request=request, response=response)

    def json(self) -> dict[str, object]:
        return {}


class FakeFallbackSuccessResponse(FakeChatCompletionResponse):
    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"message":"备用 MiMo 模型返回的结构化内容"}',
                    },
                }
            ],
        }


class FakeFallbackHttpxClient:
    calls: list[dict[str, Any]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def __enter__(self) -> "FakeFallbackHttpxClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakePrimaryFailureResponse | FakeFallbackSuccessResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "kwargs": self.kwargs})
        if "primary.example" in url:
            return FakePrimaryFailureResponse()
        return FakeFallbackSuccessResponse()


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
    assert http_client.kwargs["follow_redirects"] is False
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


def test_openai_compatible_chat_client_adds_json_instruction_when_prompt_omits_it(monkeypatch) -> None:
    FakeHttpxClient.instances = []
    monkeypatch.setattr(module.httpx, "Client", FakeHttpxClient)
    client = OpenAICompatibleChatClient(
        OpenAICompatibleSettings(
            enabled=True,
            api_key="openai-secret-value",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-plus",
            proxy_url="direct",
        )
    )

    client.complete_json(
        system_prompt="请返回结构化的临床评分结果。",
        payload={"case_id": "appendicitis_001"},
        response_model=DemoJsonResponse,
    )

    request_body = FakeHttpxClient.instances[0].calls[0]["json"]
    system_content = request_body["messages"][0]["content"]
    assert system_content == "请返回结构化的临床评分结果。\n\n请只输出一个有效的 JSON 对象。"
    assert "json" in system_content.casefold()


def test_openai_compatible_settings_reuses_dashscope_key_for_trusted_endpoint(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "shared-dashscope-test-key")

    settings = OpenAICompatibleSettings(
        _env_file=None,
        enabled=True,
        api_key="",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
    )

    assert settings.is_configured is True
    assert settings.api_key == "shared-dashscope-test-key"


def test_openai_compatible_settings_never_sends_dashscope_key_to_custom_gateway(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "shared-dashscope-test-key")

    settings = OpenAICompatibleSettings(
        _env_file=None,
        enabled=True,
        api_key="",
        base_url="https://custom-gateway.example/v1",
        model="custom-model",
    )

    assert settings.is_configured is False
    assert settings.api_key == ""


def test_openai_compatible_chat_client_falls_back_to_mimo_when_primary_provider_fails(monkeypatch) -> None:
    FakeFallbackHttpxClient.calls = []
    monkeypatch.setattr(module.httpx, "Client", FakeFallbackHttpxClient)
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_API_KEY", "mimo-secret-value")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_BASE_URL", "https://fallback-gateway.example/v1")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_MODEL", "mimo-v2.5-pro")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_PROXY_URL", "direct")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ALLOW_CROSS_PROVIDER", "true")

    client = OpenAICompatibleChatClient(
        OpenAICompatibleSettings(
            enabled=True,
            api_key="primary-secret-value",
            base_url="https://primary.example/v1",
            model="gemini-primary",
            proxy_url="direct",
        )
    )

    result = client.complete_json(
        system_prompt="只输出 JSON。",
        payload={"case_id": "appendicitis_001"},
        response_model=DemoJsonResponse,
    )

    assert result == DemoJsonResponse(message="备用 MiMo 模型返回的结构化内容")
    assert [call["url"] for call in FakeFallbackHttpxClient.calls] == [
        "https://primary.example/v1/chat/completions",
        "https://fallback-gateway.example/v1/chat/completions",
    ]
    assert [call["json"]["model"] for call in FakeFallbackHttpxClient.calls] == ["gemini-primary", "mimo-v2.5-pro"]
    assert FakeFallbackHttpxClient.calls[0]["headers"]["Authorization"] == "Bearer primary-secret-value"
    assert FakeFallbackHttpxClient.calls[1]["headers"]["Authorization"] == "Bearer mimo-secret-value"
    assert "proxy" not in FakeFallbackHttpxClient.calls[1]["kwargs"]


def test_openai_compatible_chat_client_does_not_cross_provider_without_explicit_approval(
    monkeypatch,
) -> None:
    FakeFallbackHttpxClient.calls = []
    monkeypatch.setattr(module.httpx, "Client", FakeFallbackHttpxClient)
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_API_KEY", "mimo-secret-value")
    monkeypatch.setenv(
        "OSCE_OPENAI_FALLBACK_BASE_URL",
        "https://fallback-gateway.example/v1",
    )
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_MODEL", "mimo-v2.5-pro")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_PROXY_URL", "direct")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ALLOW_CROSS_PROVIDER", "false")
    client = OpenAICompatibleChatClient(
        OpenAICompatibleSettings(
            enabled=True,
            api_key="primary-secret-value",
            base_url="https://primary.example/v1",
            model="gemini-primary",
            proxy_url="direct",
        )
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.complete_json(
            system_prompt="只输出 JSON。",
            payload={"case_id": "must-stay-on-primary"},
            response_model=DemoJsonResponse,
        )

    assert [call["url"] for call in FakeFallbackHttpxClient.calls] == [
        "https://primary.example/v1/chat/completions"
    ]


def test_account_scoped_openai_settings_never_inherit_process_fallback(
    monkeypatch,
) -> None:
    FakeFallbackHttpxClient.calls = []
    monkeypatch.setattr(module.httpx, "Client", FakeFallbackHttpxClient)
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_API_KEY", "mimo-secret-value")
    monkeypatch.setenv(
        "OSCE_OPENAI_FALLBACK_BASE_URL",
        "https://fallback-gateway.example/v1",
    )
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_MODEL", "mimo-v2.5-pro")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_PROXY_URL", "direct")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ALLOW_CROSS_PROVIDER", "true")
    client = OpenAICompatibleChatClient(
        OpenAICompatibleSettings(
            enabled=True,
            api_key="account-secret-value",
            base_url="https://primary.example/v1",
            model="account-model",
            proxy_url="direct",
            allow_process_fallback=False,
        )
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.complete_json(
            system_prompt="只输出 JSON。",
            payload={"case_id": "account-private-case"},
            response_model=DemoJsonResponse,
        )

    assert [call["url"] for call in FakeFallbackHttpxClient.calls] == [
        "https://primary.example/v1/chat/completions"
    ]


def test_runtime_openai_config_disables_process_fallback() -> None:
    settings = RuntimeModelConfig(
        provider="openai_compatible",
        api_key="account-secret",
        model="account-model",
        base_url="https://primary.example/v1",
        proxy_url="direct",
    ).to_openai_compatible_settings()

    assert settings.allow_process_fallback is False


def test_same_origin_fallback_does_not_require_cross_provider_approval() -> None:
    fallback_settings = module.OpenAICompatibleFallbackSettings(
        enabled=True,
        api_key="fallback-secret",
        base_url="https://primary.example:443/backup/v1",
        model="fallback-model",
        allow_cross_provider=False,
        _env_file=None,
    )

    assert module._fallback_destination_is_allowed(
        "https://primary.example/v1",
        fallback_settings,
    )


def test_openai_compatible_chat_client_records_primary_failure_and_fallback_success(tmp_path, monkeypatch) -> None:
    FakeFallbackHttpxClient.calls = []
    log_store = ApiCallLogStore(tmp_path / "model_api_calls.jsonl")
    monkeypatch.setattr(module, "api_call_log_store", log_store)
    monkeypatch.setattr(module.httpx, "Client", FakeFallbackHttpxClient)
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_API_KEY", "mimo-secret-value")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_BASE_URL", "https://fallback-gateway.example/v1")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_MODEL", "mimo-v2.5-pro")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_PROXY_URL", "direct")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ALLOW_CROSS_PROVIDER", "true")

    client = OpenAICompatibleChatClient(
        OpenAICompatibleSettings(
            enabled=True,
            api_key="primary-secret-value",
            base_url="https://primary.example/v1",
            model="gemini-primary",
            proxy_url="direct",
        )
    )

    result = client.complete_json(
        system_prompt="只输出 JSON。",
        payload={"case_id": "appendicitis_001"},
        response_model=DemoJsonResponse,
    )

    assert result == DemoJsonResponse(message="备用 MiMo 模型返回的结构化内容")
    payload = log_store.build_admin_payload(limit=10)
    assert [(item["provider"], item["success"], item["status_code"]) for item in payload["logs"]] == [
        ("openai_compatible_fallback", True, 200),
        ("openai_compatible", False, 503),
    ]


def test_openai_compatible_chat_client_logs_invalid_200_response_as_failure(
    tmp_path,
    monkeypatch,
) -> None:
    class InvalidResponse(FakeChatCompletionResponse):
        def json(self) -> dict[str, object]:
            return {"choices": []}

    class InvalidResponseClient(FakeHttpxClient):
        def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> InvalidResponse:
            self.calls.append({"url": url, "headers": headers, "json": json})
            return InvalidResponse()

    log_store = ApiCallLogStore(tmp_path / "model_api_calls.jsonl")
    monkeypatch.setattr(module, "api_call_log_store", log_store)
    monkeypatch.setattr(module.httpx, "Client", InvalidResponseClient)
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ENABLED", "false")
    client = OpenAICompatibleChatClient(
        OpenAICompatibleSettings(
            enabled=True,
            api_key="primary-secret-value",
            base_url="https://primary.example/v1",
            model="gemini-primary",
            proxy_url="direct",
        )
    )

    with pytest.raises(RuntimeError, match="missing choices"):
        client.complete_json(
            system_prompt="只输出 JSON。",
            payload={"case_id": "appendicitis_001"},
            response_model=DemoJsonResponse,
        )

    logs = log_store.build_admin_payload(limit=10)["logs"]
    assert [
        (
            item["provider"],
            item["success"],
            item["status_code"],
            item["error_type"],
        )
        for item in logs
    ] == [("openai_compatible", False, 200, "RuntimeError")]


def test_openai_compatible_chat_client_normalizes_mimo_model_case_without_provider_specific_url(monkeypatch) -> None:
    FakeHttpxClient.instances = []
    monkeypatch.setattr(module.httpx, "Client", FakeHttpxClient)

    client = OpenAICompatibleChatClient(
        OpenAICompatibleSettings(
            enabled=True,
            api_key="openai-secret-value",
            base_url="https://fallback-gateway.example/v1",
            model="MiMo-V2.5-Pro",
            proxy_url="direct",
        )
    )

    result = client.complete_json(
        system_prompt="只输出 JSON。",
        payload={"case_id": "appendicitis_001"},
        response_model=DemoJsonResponse,
    )

    assert result == DemoJsonResponse(message="真实调用路径返回的结构化内容")
    assert FakeHttpxClient.instances[0].calls[0]["json"]["model"] == "mimo-v2.5-pro"


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


class DripChatCompletionHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)
        response_body = json_module.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"message":"slow response"}',
                        }
                    }
                ]
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        try:
            for byte in response_body:
                self.wfile.write(bytes([byte]))
                self.wfile.flush()
                time.sleep(0.02)
        except (BrokenPipeError, ConnectionResetError):
            return

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


def test_openai_compatible_chat_client_enforces_total_deadline_on_drip_response(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ENABLED", "false")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        DripChatCompletionHandler,
    )
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = OpenAICompatibleChatClient(
        OpenAICompatibleSettings(
            enabled=True,
            api_key="local-secret",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            model="slow-local-model",
            proxy_url="direct",
            timeout_seconds=0.15,
        )
    )
    started_at = time.monotonic()

    try:
        with pytest.raises(ModelProviderTimeoutError):
            client.complete_json(
                system_prompt="只输出 JSON。",
                payload={"ping": "clinical-osce-agent"},
                response_model=DemoJsonResponse,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert time.monotonic() - started_at < 0.8


def test_openai_primary_and_fallback_share_one_total_deadline(
    monkeypatch,
) -> None:
    class SlowPrimaryAndFallbackClient(FakeFallbackHttpxClient):
        def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakePrimaryFailureResponse | FakeFallbackSuccessResponse:
            time.sleep(0.08)
            return super().post(
                url,
                headers=headers,
                json=json,
            )

    SlowPrimaryAndFallbackClient.calls = []
    monkeypatch.setattr(
        module.httpx,
        "Client",
        SlowPrimaryAndFallbackClient,
    )
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_API_KEY", "fallback-secret")
    monkeypatch.setenv(
        "OSCE_OPENAI_FALLBACK_BASE_URL",
        "https://fallback-gateway.example/v1",
    )
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_MODEL", "fallback-model")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_PROXY_URL", "direct")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ALLOW_CROSS_PROVIDER", "true")
    client = OpenAICompatibleChatClient(
        OpenAICompatibleSettings(
            enabled=True,
            api_key="primary-secret",
            base_url="https://primary.example/v1",
            model="primary-model",
            proxy_url="direct",
            timeout_seconds=0.12,
        )
    )
    started_at = time.monotonic()

    with pytest.raises(ModelProviderTimeoutError):
        client.complete_json(
            system_prompt="只输出 JSON。",
            payload={"ping": "clinical-osce-agent"},
            response_model=DemoJsonResponse,
        )

    assert time.monotonic() - started_at < 0.3
