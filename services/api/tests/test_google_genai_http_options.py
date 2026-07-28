import importlib
import os

import pytest

from app.services import google_genai_http_options as http_options_module
from app.services.google_genai_http_options import (
    DEFAULT_GOOGLE_GENAI_TIMEOUT_SECONDS,
    INVALID_GOOGLE_GENAI_PROXY_MESSAGE,
    INVALID_GOOGLE_GENAI_TIMEOUT_MESSAGE,
    RUNTIME_VERTEX_ADC_PROXY_UNSUPPORTED_MESSAGE,
    build_google_genai_http_options,
    require_direct_runtime_vertex_adc_proxy,
)
from app.services.gemini_patient_responder import GeminiPatientSettings


PROXY_ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
GEMINI_AGENT_CLIENTS = [
    ("app.services.gemini_patient_responder", "GeminiPatientResponder"),
    ("app.services.turn_intent_agent", "GeminiTurnIntentAgent"),
    ("app.services.coach_agent", "GeminiCoachAgent"),
    ("app.services.teacher_agent", "GeminiTeacherAgent"),
    ("app.services.procedure_request_router", "GeminiProcedureRequestRouter"),
    ("app.services.procedure_result_simulator", "GeminiProcedureResultSimulator"),
    ("app.services.procedure_result_approval_agent", "GeminiProcedureResultApprovalAgent"),
]


def test_google_genai_http_options_do_not_mutate_process_proxy_environment(monkeypatch) -> None:
    original_environment = {
        "HTTP_PROXY": "http://original-http.example",
        "HTTPS_PROXY": "http://original-https.example",
        "ALL_PROXY": "socks5://original-all.example",
    }
    for name, value in original_environment.items():
        monkeypatch.setenv(name, value)

    direct_options = build_google_genai_http_options("direct")
    proxied_options = build_google_genai_http_options("http://request-proxy.example:8080")

    assert {name: os.environ.get(name) for name in PROXY_ENV_NAMES} == original_environment
    assert direct_options.client_args == {
        "follow_redirects": False,
        "trust_env": False,
    }
    assert direct_options.async_client_args["follow_redirects"] is False
    assert direct_options.async_client_args["trust_env"] is False
    assert "proxy" not in direct_options.async_client_args
    assert direct_options.timeout == int(
        DEFAULT_GOOGLE_GENAI_TIMEOUT_SECONDS * 1_000
    )
    assert direct_options.retry_options is not None
    assert direct_options.retry_options.attempts == 1
    assert proxied_options.client_args == {
        "follow_redirects": False,
        "trust_env": False,
        "proxy": "http://request-proxy.example:8080",
    }
    assert proxied_options.async_client_args["follow_redirects"] is False
    assert proxied_options.async_client_args["trust_env"] is False
    assert proxied_options.async_client_args["proxy"] == "http://request-proxy.example:8080"


def test_google_genai_http_options_accept_a_shorter_operation_timeout() -> None:
    options = build_google_genai_http_options(
        "direct",
        timeout_seconds=5.0,
    )

    assert options.timeout == 5_000
    assert options.retry_options is not None
    assert options.retry_options.attempts == 1


@pytest.mark.parametrize(
    "timeout_seconds",
    [0, -1, float("inf"), float("nan"), True, "30"],
)
def test_google_genai_http_options_reject_invalid_timeouts(
    timeout_seconds: object,
) -> None:
    with pytest.raises(
        ValueError,
        match=INVALID_GOOGLE_GENAI_TIMEOUT_MESSAGE,
    ):
        build_google_genai_http_options(
            "direct",
            timeout_seconds=timeout_seconds,  # type: ignore[arg-type]
        )


def test_google_genai_http_options_keep_a_and_b_proxy_settings_isolated() -> None:
    options_a = build_google_genai_http_options("http://proxy-a.example:8080")
    options_b = build_google_genai_http_options("http://proxy-b.example:9090")

    assert options_a.client_args is not options_b.client_args
    assert options_a.async_client_args is not options_b.async_client_args
    assert options_a.client_args["proxy"] == "http://proxy-a.example:8080"
    assert options_a.async_client_args["proxy"] == "http://proxy-a.example:8080"
    assert options_b.client_args["proxy"] == "http://proxy-b.example:9090"
    assert options_b.async_client_args["proxy"] == "http://proxy-b.example:9090"


def test_google_genai_async_transport_disables_environment_and_uses_client_proxy(monkeypatch) -> None:
    created_transports: list[dict[str, object]] = []

    class FakeAsyncTransport:
        def __init__(self, **kwargs: object) -> None:
            created_transports.append(kwargs)

    monkeypatch.setattr(http_options_module.httpx, "AsyncHTTPTransport", FakeAsyncTransport)

    options = build_google_genai_http_options("http://request-proxy.example:8080")

    assert created_transports == [
        {
            "proxy": "http://request-proxy.example:8080",
            "trust_env": False,
        }
    ]
    assert isinstance(options.async_client_args["transport"], FakeAsyncTransport)


@pytest.mark.parametrize(
    "proxy_url",
    [
        "socks5://127.0.0.1:7897",
        "file:///tmp/proxy.sock",
        "proxy.example:8080",
        "http://",
    ],
)
def test_google_genai_http_options_reject_invalid_proxy_urls(proxy_url: str) -> None:
    with pytest.raises(ValueError, match=INVALID_GOOGLE_GENAI_PROXY_MESSAGE):
        build_google_genai_http_options(proxy_url)


@pytest.mark.parametrize(("module_name", "client_class_name"), GEMINI_AGENT_CLIENTS)
def test_gemini_agent_clients_keep_a_and_b_http_options_isolated(
    module_name: str,
    client_class_name: str,
    monkeypatch,
) -> None:
    module = importlib.import_module(module_name)
    created_clients: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            created_clients.append(kwargs)

    original_environment = {
        "HTTP_PROXY": "http://ambient-http.example",
        "HTTPS_PROXY": "http://ambient-https.example",
        "ALL_PROXY": "socks5://ambient-all.example",
    }
    for name, value in original_environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(module.genai, "Client", FakeClient)
    client_class = getattr(module, client_class_name)

    client_class(
        GeminiPatientSettings(
            api_key="vertex-key-a",
            use_vertex=True,
            proxy_url="http://proxy-a.example:8080",
            _env_file=None,
        )
    )
    client_class(
        GeminiPatientSettings(
            api_key="vertex-key-b",
            use_vertex=True,
            proxy_url="http://proxy-b.example:9090",
            _env_file=None,
        )
    )

    options_a = created_clients[0]["http_options"]
    options_b = created_clients[1]["http_options"]
    assert options_a.client_args["proxy"] == "http://proxy-a.example:8080"
    assert options_a.async_client_args["proxy"] == "http://proxy-a.example:8080"
    assert options_b.client_args["proxy"] == "http://proxy-b.example:9090"
    assert options_b.async_client_args["proxy"] == "http://proxy-b.example:9090"
    assert options_a.client_args is not options_b.client_args
    assert options_a.async_client_args is not options_b.async_client_args
    assert {name: os.environ.get(name) for name in PROXY_ENV_NAMES} == original_environment


@pytest.mark.parametrize("proxy_url", ["", "direct", "none", "false", "off", "no"])
def test_runtime_vertex_adc_accepts_only_direct_proxy_values(proxy_url: str) -> None:
    require_direct_runtime_vertex_adc_proxy(proxy_url)


def test_runtime_vertex_adc_rejects_per_user_proxy() -> None:
    with pytest.raises(ValueError, match=RUNTIME_VERTEX_ADC_PROXY_UNSUPPORTED_MESSAGE):
        require_direct_runtime_vertex_adc_proxy("http://per-user-proxy.example:8080")
