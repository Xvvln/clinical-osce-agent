from __future__ import annotations

import pytest

from app.services.dashscope_credential_service import (
    is_trusted_dashscope_endpoint,
    resolve_dashscope_feature_api_key,
    resolve_openai_compatible_api_key,
)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://dashscope.aliyuncs.com:443/api/v1",
        "https://trial.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "https://workspace-123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "https://coding-intl.dashscope.aliyuncs.com/v1",
    ],
)
def test_trusted_dashscope_endpoint_accepts_only_alibaba_owned_https_hosts(
    endpoint: str,
) -> None:
    assert is_trusted_dashscope_endpoint(endpoint) is True


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://dashscope.aliyuncs.com:8443/compatible-mode/v1",
        "https://user:password@dashscope.aliyuncs.com/compatible-mode/v1",
        "https://dashscope.aliyuncs.com/compatible-mode/v1?next=evil",
        "https://dashscope.aliyuncs.com.example.org/compatible-mode/v1",
        "https://maas.aliyuncs.com/compatible-mode/v1",
        "https://example.org/compatible-mode/v1",
    ],
)
def test_trusted_dashscope_endpoint_rejects_lookalike_or_unsafe_urls(
    endpoint: str,
) -> None:
    assert is_trusted_dashscope_endpoint(endpoint) is False


def test_text_model_reuses_shared_key_only_for_trusted_dashscope_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "shared-test-key")

    assert (
        resolve_openai_compatible_api_key(
            "",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        == "shared-test-key"
    )
    assert (
        resolve_openai_compatible_api_key(
            "",
            base_url="https://custom-gateway.example/v1",
        )
        == ""
    )


def test_text_model_can_reuse_legacy_speech_key_on_trusted_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("OSCE_DASHSCOPE_SPEECH_API_KEY", "speech-test-key")

    assert (
        resolve_openai_compatible_api_key(
            "",
            base_url=(
                "https://workspace.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1"
            ),
        )
        == "speech-test-key"
    )


def test_explicit_compatible_key_remains_available_for_custom_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "must-not-be-used")

    assert (
        resolve_openai_compatible_api_key(
            "custom-gateway-key",
            base_url="https://custom-gateway.example/v1",
        )
        == "custom-gateway-key"
    )


def test_feature_shared_key_is_not_sent_to_custom_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "must-not-be-used")

    assert (
        resolve_dashscope_feature_api_key(
            "",
            target_urls=("https://speech-gateway.example/v1",),
        )
        == ""
    )
    assert (
        resolve_dashscope_feature_api_key(
            "explicit-feature-key",
            target_urls=("https://speech-gateway.example/v1",),
        )
        == "explicit-feature-key"
    )
