from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from app import main
from app.services import anthropic_chat_client as anthropic_module
from app.services import api_call_log_service as api_log_module
from app.services import openai_compatible_chat_client as openai_module
from app.services.anthropic_chat_client import AnthropicChatClient, AnthropicSettings
from app.services.api_call_log_service import ApiCallLogStore, call_with_api_logging
from app.services.model_call_policy import (
    TEXT_MODEL_ENVELOPE_MAX_BYTES,
    ModelProviderOverloadedError,
    ModelProviderPayloadTooLargeError,
    call_google_text_generate_content,
    enforce_text_model_json_envelope,
    json_envelope_utf8_size,
)
from app.services.openai_compatible_chat_client import (
    OpenAICompatibleChatClient,
    OpenAICompatibleSettings,
)
from app.services.osce_session_service import load_case_node, osce_session_service


class _DemoResponse(BaseModel):
    message: str


class _NetworkMustNotStart:
    starts = 0

    def __init__(self, **_: object) -> None:
        type(self).starts += 1
        raise AssertionError("network client must not be constructed")


class _ForbiddenGoogleModels:
    calls = 0

    def generate_content(self, **_: object) -> object:
        type(self).calls += 1
        raise AssertionError("Google SDK transport must not be called")


class _ForbiddenGoogleClient:
    models = _ForbiddenGoogleModels()


class _InvalidAnthropicResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "不是 JSON",
                }
            ]
        }


class _InvalidAnthropicHttpClient:
    def __init__(self, **_: object) -> None:
        pass

    def __enter__(self) -> _InvalidAnthropicHttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, *_: object, **__: object) -> _InvalidAnthropicResponse:
        return _InvalidAnthropicResponse()


def _exact_sized_payload(size_bytes: int) -> dict[str, str]:
    prefix = '中文🙂"quoted"'
    base_size = json_envelope_utf8_size({"text": prefix})
    assert base_size <= size_bytes
    return {"text": prefix + ("x" * (size_bytes - base_size))}


def _assert_one_policy_failure(log_store: ApiCallLogStore, *, provider: str) -> None:
    logs = log_store.build_admin_payload(limit=10)["logs"]
    assert len(logs) == 1
    assert logs[0]["provider"] == provider
    assert logs[0]["success"] is False
    assert logs[0]["error_type"] == "ModelProviderPayloadTooLargeError"


def test_text_model_envelope_uses_exact_compact_utf8_json_boundary() -> None:
    at_limit = _exact_sized_payload(TEXT_MODEL_ENVELOPE_MAX_BYTES)
    over_limit = {
        "text": f'{at_limit["text"]}🙂"',
    }

    assert json_envelope_utf8_size(at_limit) == TEXT_MODEL_ENVELOPE_MAX_BYTES
    assert (
        enforce_text_model_json_envelope(at_limit)
        == TEXT_MODEL_ENVELOPE_MAX_BYTES
    )
    assert json_envelope_utf8_size(over_limit) > TEXT_MODEL_ENVELOPE_MAX_BYTES
    with pytest.raises(ModelProviderPayloadTooLargeError):
        enforce_text_model_json_envelope(over_limit)


def test_openai_oversized_envelope_is_logged_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _NetworkMustNotStart.starts = 0
    log_store = ApiCallLogStore(tmp_path / "openai-calls.jsonl")
    monkeypatch.setattr(openai_module, "api_call_log_store", log_store)
    monkeypatch.setattr(openai_module.httpx, "Client", _NetworkMustNotStart)
    client = OpenAICompatibleChatClient(
        OpenAICompatibleSettings(
            enabled=True,
            api_key="test-key",
            base_url="https://provider.example/v1",
            model="test-model",
            proxy_url="direct",
            allow_process_fallback=False,
            _env_file=None,
        )
    )

    with pytest.raises(ModelProviderPayloadTooLargeError):
        client.complete_json(
            system_prompt="只输出 JSON。",
            payload={"text": '病史🙂"引用"' * 20_000},
            response_model=_DemoResponse,
        )

    assert _NetworkMustNotStart.starts == 0
    _assert_one_policy_failure(log_store, provider="openai_compatible")


def test_anthropic_oversized_envelope_is_logged_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _NetworkMustNotStart.starts = 0
    log_store = ApiCallLogStore(tmp_path / "anthropic-calls.jsonl")
    monkeypatch.setattr(anthropic_module, "api_call_log_store", log_store)
    monkeypatch.setattr(anthropic_module.httpx, "Client", _NetworkMustNotStart)
    client = AnthropicChatClient(
        AnthropicSettings(
            enabled=True,
            api_key="test-key",
            base_url="https://provider.example",
            model="test-model",
            proxy_url="direct",
            _env_file=None,
        )
    )

    with pytest.raises(ModelProviderPayloadTooLargeError):
        client.complete_json(
            system_prompt="只输出 JSON。",
            payload={"text": '病史🙂"引用"' * 20_000},
            response_model=_DemoResponse,
        )

    assert _NetworkMustNotStart.starts == 0
    _assert_one_policy_failure(log_store, provider="anthropic")


def test_anthropic_invalid_200_response_is_logged_as_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_store = ApiCallLogStore(tmp_path / "anthropic-invalid.jsonl")
    monkeypatch.setattr(anthropic_module, "api_call_log_store", log_store)
    monkeypatch.setattr(
        anthropic_module.httpx,
        "Client",
        _InvalidAnthropicHttpClient,
    )
    client = AnthropicChatClient(
        AnthropicSettings(
            enabled=True,
            api_key="test-key",
            base_url="https://provider.example",
            model="test-model",
            proxy_url="direct",
            _env_file=None,
        )
    )

    with pytest.raises(ValidationError):
        client.complete_json(
            system_prompt="只输出 JSON。",
            payload={"text": '中文🙂"引用"'},
            response_model=_DemoResponse,
        )

    logs = log_store.build_admin_payload(limit=10)["logs"]
    assert len(logs) == 1
    assert logs[0]["provider"] == "anthropic"
    assert logs[0]["success"] is False
    assert logs[0]["status_code"] == 200
    assert logs[0]["error_type"] == "ValidationError"


def test_google_oversized_envelope_is_logged_without_sdk_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ForbiddenGoogleModels.calls = 0
    log_store = ApiCallLogStore(tmp_path / "google-calls.jsonl")
    monkeypatch.setattr(api_log_module, "api_call_log_store", log_store)
    config = SimpleNamespace(system_instruction="只输出 JSON。")

    with pytest.raises(ModelProviderPayloadTooLargeError):
        call_with_api_logging(
            provider="vertex_gemini_test",
            operation="generate_content",
            model="gemini-test",
            endpoint="vertex://generate_content",
            call=lambda: call_google_text_generate_content(
                client=_ForbiddenGoogleClient(),
                model="gemini-test",
                contents='病史🙂"引用"' * 20_000,
                config=config,
            ),
        )

    assert _ForbiddenGoogleModels.calls == 0
    _assert_one_policy_failure(log_store, provider="vertex_gemini_test")


@pytest.mark.parametrize("provider", ["gemini_test", "vertex_gemini_test"])
def test_google_invalid_200_response_is_logged_as_failure(
    provider: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_store = ApiCallLogStore(tmp_path / f"{provider}-invalid.jsonl")
    monkeypatch.setattr(api_log_module, "api_call_log_store", log_store)
    response = SimpleNamespace(text="不是 JSON", status_code=200)

    with pytest.raises(ValidationError):
        call_with_api_logging(
            provider=provider,
            operation="generate_content",
            model="gemini-test",
            endpoint=f"{provider}://generate_content",
            call=lambda: response,
            result_parser=lambda raw_response: _DemoResponse.model_validate_json(
                raw_response.text
            ),
        )

    logs = log_store.build_admin_payload(limit=10)["logs"]
    assert len(logs) == 1
    assert logs[0]["provider"] == provider
    assert logs[0]["success"] is False
    assert logs[0]["status_code"] == 200
    assert logs[0]["error_type"] == "ValidationError"


def test_all_google_text_generate_content_calls_use_shared_guard() -> None:
    services_dir = Path(__file__).parents[1] / "app" / "services"
    direct_call_files = {
        path.name
        for path in services_dir.glob("*.py")
        if ".models.generate_content(" in path.read_text(encoding="utf-8")
    }
    expected_guarded_business_files = {
        "coach_agent.py",
        "gemini_patient_responder.py",
        "procedure_request_router.py",
        "procedure_result_approval_agent.py",
        "procedure_result_simulator.py",
        "teacher_agent.py",
        "training_skill_candidate_service.py",
        "turn_intent_agent.py",
        "vertex_gemini_scorer.py",
    }
    guarded_files = {
        path.name
        for path in services_dir.glob("*.py")
        if "call_google_text_generate_content(" in path.read_text(encoding="utf-8")
    }
    parse_before_success_files = {
        path.name
        for path in services_dir.glob("*.py")
        if "result_parser=" in path.read_text(encoding="utf-8")
    }

    assert direct_call_files == {"model_call_policy.py"}
    assert expected_guarded_business_files <= guarded_files
    assert expected_guarded_business_files <= parse_before_success_files


def test_session_procedure_router_does_not_swallow_model_policy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def overloaded_router(_: object) -> object:
        raise ModelProviderOverloadedError("provider busy")

    monkeypatch.setattr(
        osce_session_service,
        "procedure_request_router",
        overloaded_router,
    )

    with pytest.raises(ModelProviderOverloadedError):
        osce_session_service._route_unmatched_procedure_requests(
            case=load_case_node("appendicitis_001"),
            request_text="申请一个未配置检查",
            unmatched_requests=["未配置检查"],
        )


def test_model_business_fallbacks_rethrow_policy_errors_before_broad_catches() -> None:
    app_dir = Path(__file__).parents[1] / "app"
    model_call_markers = (
        ".complete_json(",
        "call_with_api_logging(",
        "coach_agent(",
        "teacher_agent(",
        "self.procedure_request_router(",
        ".generate_candidate(",
        ".generate_for_completed_session(",
        "reviewer.review(",
        "return router(request)",
        "return agent(request)",
    )
    offenders: list[str] = []

    for path in app_dir.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try) or not node.body:
                continue
            body_source = "\n".join(
                ast.get_source_segment(source, statement) or ""
                for statement in node.body
            )
            if not any(marker in body_source for marker in model_call_markers):
                continue
            handler_names = [
                ast.unparse(handler.type) if handler.type is not None else "bare"
                for handler in node.handlers
            ]
            broad_index = next(
                (
                    index
                    for index, name in enumerate(handler_names)
                    if name in {"Exception", "BaseException", "bare"}
                ),
                None,
            )
            if broad_index is None:
                continue
            try:
                policy_index = handler_names.index("ModelProviderPolicyError")
            except ValueError:
                policy_index = None
            if policy_index is None or policy_index > broad_index:
                offenders.append(f"{path.relative_to(app_dir)}:{node.lineno}")

    assert offenders == []


def test_payload_policy_error_has_stable_non_sensitive_http_mapping() -> None:
    mapped = main._model_provider_gateway_error(
        ModelProviderPayloadTooLargeError("secret-payload-contents")
    )

    assert mapped.status_code == 413
    assert mapped.detail == main.MODEL_PROVIDER_PAYLOAD_TOO_LARGE_DETAIL
    assert "secret-payload-contents" not in mapped.detail
