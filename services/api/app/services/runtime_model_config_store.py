from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from typing import Any, cast

from app.services.account_model_endpoint_policy import (
    validate_account_model_endpoint_policy,
)
from app.services.anthropic_chat_client import AnthropicSettings
from app.services.google_genai_http_options import (
    require_direct_runtime_vertex_adc_proxy,
    should_use_google_genai_proxy,
    validate_google_genai_proxy_url,
)
from app.services.openai_compatible_chat_client import OpenAICompatibleSettings

RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS = [
    "patient_responder",
    "turn_intent_agent",
    "coach_agent",
    "llm_rubric_scorer",
    "skill_candidate_generator",
    "procedure_request_router",
    "teacher_agent",
    "humanistic_semantic_reviewer",
]

VERTEX_RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS = [
    *RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS,
    "rag_vector_retrieval",
]

_REQUEST_CONFIG_UNSET = object()


@dataclass(frozen=True)
class RuntimeModelConfig:
    provider: str
    api_key: str
    model: str
    base_url: str
    proxy_url: str
    project: str = ""
    location: str = "global"

    def cache_key(self) -> tuple[str, str, str, str, str, str, str]:
        return (
            self.provider,
            self.api_key,
            self.model,
            self.base_url,
            self.proxy_url,
            self.project,
            self.location,
        )

    def to_config_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "model": self.model,
            "base_url": self.project if self.provider == "vertex_gemini_adc" else self.base_url,
            "proxy_url": self.proxy_url,
            "location": self.location,
        }

    def to_openai_compatible_settings(self) -> OpenAICompatibleSettings:
        return OpenAICompatibleSettings(
            enabled=True,
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            proxy_url=self.proxy_url,
        )

    def to_anthropic_settings(self) -> AnthropicSettings:
        return AnthropicSettings(
            enabled=True,
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            proxy_url=self.proxy_url,
        )

    def public_payload(self) -> dict[str, object]:
        if self.provider == "vertex_gemini_adc":
            return {
                "active": True,
                "provider": self.provider,
                "model": self.model,
                "base_url": self.project,
                "proxy_url": self.proxy_url,
                "project": self.project,
                "location": self.location,
                "integration_targets": list(VERTEX_RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
                "message": "Vertex Gemini ADC 配置已保存，仅在当前账号的训练与报告请求中生效。",
            }
        if self.provider == "vertex_gemini_api_key":
            return {
                "active": True,
                "provider": self.provider,
                "model": self.model,
                "base_url": self.base_url,
                "proxy_url": self.proxy_url,
                "project": self.project,
                "location": self.location,
                "integration_targets": list(VERTEX_RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
                "message": "Vertex Gemini API Key 配置已保存，仅在当前账号的训练与报告请求中生效。",
            }
        if self.provider == "anthropic":
            return {
                "active": True,
                "provider": self.provider,
                "model": self.model,
                "base_url": self.base_url,
                "proxy_url": self.proxy_url,
                "integration_targets": list(RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
                "message": "Anthropic 服务端配置已保存，仅在当前账号的训练与报告请求中生效。",
            }
        return {
            "active": True,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "proxy_url": self.proxy_url,
            "integration_targets": list(RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
            "message": "OpenAI 兼容服务端配置已保存，仅在当前账号的训练与报告请求中生效。",
        }


class RuntimeModelConfigStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active_config: RuntimeModelConfig | None = None
        self._request_config: ContextVar[RuntimeModelConfig | None | object] = ContextVar(
            f"runtime_model_config_{id(self)}",
            default=_REQUEST_CONFIG_UNSET,
        )

    def build_config(self, config: dict[str, Any]) -> RuntimeModelConfig:
        provider = _normalize_text(config.get("provider", ""))
        if provider not in {"openai_compatible", "anthropic", "vertex_gemini_adc", "vertex_gemini_api_key"}:
            raise ValueError(
                "runtime model config currently supports openai_compatible, anthropic, vertex_gemini_adc or vertex_gemini_api_key only"
            )

        api_key = _normalize_text(config.get("api_key", ""))
        model = _normalize_text(config.get("model", ""))
        raw_base_url = _normalize_text(config.get("base_url", ""))
        base_url = raw_base_url or "https://api.openai.com/v1"
        proxy_url = _normalize_text(config.get("proxy_url", ""))
        validate_account_model_endpoint_policy(
            provider=provider,
            base_url=raw_base_url,
            proxy_url=proxy_url,
        )
        if provider == "openai_compatible" and not api_key:
            raise ValueError("api_key is required for openai_compatible")
        if provider == "anthropic" and not api_key:
            raise ValueError("api_key is required for anthropic")
        if provider == "vertex_gemini_api_key" and not api_key:
            raise ValueError("api_key is required for vertex_gemini_api_key")
        if not model:
            raise ValueError(f"model is required for {provider}")
        project = ""
        location = "global"
        if provider == "anthropic" and not _normalize_text(config.get("base_url", "")):
            base_url = "https://api.anthropic.com"
        if provider == "vertex_gemini_adc":
            project = raw_base_url
            base_url = project
            location = _normalize_text(config.get("location", "")) or "global"
            if not project:
                raise ValueError("project is required for vertex_gemini_adc")
            require_direct_runtime_vertex_adc_proxy(proxy_url)
        if provider == "vertex_gemini_api_key":
            base_url = ""
            project = ""
            location = _normalize_text(config.get("location", "")) or "global"
            if should_use_google_genai_proxy(proxy_url):
                validate_google_genai_proxy_url(proxy_url)

        runtime_config = RuntimeModelConfig(
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            proxy_url=proxy_url,
            project=project,
            location=location,
        )

        return runtime_config

    def apply_config(self, config: dict[str, Any]) -> RuntimeModelConfig:
        runtime_config = self.build_config(config)
        with self._lock:
            self._active_config = runtime_config
        return runtime_config

    @contextmanager
    def use_config(self, config: RuntimeModelConfig | None) -> Iterator[RuntimeModelConfig | None]:
        token = self._request_config.set(config)
        try:
            yield config
        finally:
            self._request_config.reset(token)

    def get_active_config(self) -> RuntimeModelConfig | None:
        request_config = self._request_config.get()
        if request_config is not _REQUEST_CONFIG_UNSET:
            return cast(RuntimeModelConfig | None, request_config)
        with self._lock:
            return self._active_config

    def active_config_cache_key(self) -> tuple[str, ...]:
        active_config = self.get_active_config()
        if active_config is None:
            return ("env",)
        return ("runtime", *active_config.cache_key())

    def get_openai_compatible_settings(self) -> OpenAICompatibleSettings | None:
        active_config = self.get_active_config()
        if active_config is None or active_config.provider != "openai_compatible":
            return None
        return active_config.to_openai_compatible_settings()

    def get_anthropic_settings(self) -> AnthropicSettings | None:
        active_config = self.get_active_config()
        if active_config is None or active_config.provider != "anthropic":
            return None
        return active_config.to_anthropic_settings()

    def get_vertex_gemini_adc_config(self) -> RuntimeModelConfig | None:
        active_config = self.get_active_config()
        if active_config is None or active_config.provider != "vertex_gemini_adc":
            return None
        return active_config

    def get_vertex_gemini_api_key_config(self) -> RuntimeModelConfig | None:
        active_config = self.get_active_config()
        if active_config is None or active_config.provider != "vertex_gemini_api_key":
            return None
        return active_config

    def get_vertex_gemini_config(self) -> RuntimeModelConfig | None:
        active_config = self.get_active_config()
        if active_config is None or active_config.provider not in {"vertex_gemini_adc", "vertex_gemini_api_key"}:
            return None
        return active_config

    def clear(self) -> None:
        with self._lock:
            self._active_config = None

    def public_status(self) -> dict[str, object]:
        active_config = self.get_active_config()
        if active_config is None:
            return {
                "active": False,
                "provider": "",
                "model": "",
                "base_url": "",
                "proxy_url": "",
                "integration_targets": [],
                "message": "当前没有已应用到后端运行时的模型配置。",
            }
        return active_config.public_payload()


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


runtime_model_config_store = RuntimeModelConfigStore()


__all__ = [
    "RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS",
    "VERTEX_RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS",
    "RuntimeModelConfig",
    "RuntimeModelConfigStore",
    "runtime_model_config_store",
]
