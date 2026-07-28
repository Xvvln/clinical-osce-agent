from __future__ import annotations

import pytest

from app.services.account_model_endpoint_policy import (
    ACCOUNT_MODEL_ENDPOINT_POLICY_ERROR,
    ACCOUNT_MODEL_PROVIDER_POLICY_ERROR,
    ACCOUNT_MODEL_PROXY_POLICY_ERROR,
    validate_account_model_endpoint_policy,
)


@pytest.fixture(autouse=True)
def use_shared_safe_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    monkeypatch.delenv(
        "CLINICAL_OSCE_ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS",
        raising=False,
    )


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [
        ("openai_compatible", "https://api.openai.com/v1"),
        ("anthropic", "https://api.anthropic.com"),
        ("gemini", "https://generativelanguage.googleapis.com"),
        ("vertex_gemini_api_key", ""),
    ],
)
def test_default_account_model_endpoints_allow_only_fixed_public_providers(
    provider: str,
    base_url: str,
) -> None:
    validate_account_model_endpoint_policy(
        provider=provider,
        base_url=base_url,
        proxy_url="direct",
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:8000/v1",
        "https://127.0.0.1/v1",
        "https://localhost/v1",
        "https://metadata.google.internal/v1",
        "https://api.openai.com:444/v1",
        "https://user:password@api.openai.com/v1",
        "https://api.openai.com/v1?redirect=http://127.0.0.1",
    ],
)
def test_default_account_model_endpoint_policy_rejects_local_or_ambiguous_urls(
    base_url: str,
) -> None:
    with pytest.raises(ValueError, match=ACCOUNT_MODEL_ENDPOINT_POLICY_ERROR):
        validate_account_model_endpoint_policy(
            provider="openai_compatible",
            base_url=base_url,
            proxy_url="direct",
        )


def test_account_model_endpoint_policy_requires_server_host_allowlist(
    monkeypatch,
) -> None:
    with pytest.raises(ValueError, match=ACCOUNT_MODEL_ENDPOINT_POLICY_ERROR):
        validate_account_model_endpoint_policy(
            provider="openai_compatible",
            base_url="https://approved-gateway.example/v1",
            proxy_url="direct",
        )

    monkeypatch.setenv(
        "CLINICAL_OSCE_ACCOUNT_MODEL_ALLOWED_HOSTS",
        "approved-gateway.example",
    )
    validate_account_model_endpoint_policy(
        provider="openai_compatible",
        base_url="https://approved-gateway.example/v1",
        proxy_url="direct",
    )


def test_shared_account_model_policy_rejects_proxy_custom_backend_and_adc() -> None:
    with pytest.raises(ValueError, match=ACCOUNT_MODEL_PROXY_POLICY_ERROR):
        validate_account_model_endpoint_policy(
            provider="openai_compatible",
            base_url="https://api.openai.com/v1",
            proxy_url="http://127.0.0.1:7897",
        )
    for provider in ("custom_backend", "local_backend", "vertex_gemini_adc"):
        with pytest.raises(ValueError, match=ACCOUNT_MODEL_PROVIDER_POLICY_ERROR):
            validate_account_model_endpoint_policy(
                provider=provider,
                base_url="http://127.0.0.1:8000",
                proxy_url="direct",
            )


def test_unsafe_account_endpoints_require_explicit_single_user_local_dev(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "CLINICAL_OSCE_ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS",
        "true",
    )
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    with pytest.raises(ValueError, match=ACCOUNT_MODEL_PROVIDER_POLICY_ERROR):
        validate_account_model_endpoint_policy(
            provider="custom_backend",
            base_url="http://127.0.0.1:8000",
            proxy_url="http://127.0.0.1:7897",
        )

    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-dev")
    validate_account_model_endpoint_policy(
        provider="custom_backend",
        base_url="http://127.0.0.1:8000",
        proxy_url="http://127.0.0.1:7897",
    )
