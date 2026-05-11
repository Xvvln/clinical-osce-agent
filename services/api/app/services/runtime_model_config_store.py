from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any

from app.services.anthropic_chat_client import AnthropicSettings
from app.services.openai_compatible_chat_client import OpenAICompatibleSettings

RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS = [
    "patient_responder",
    "turn_intent_agent",
    "llm_rubric_scorer",
    "skill_candidate_generator",
]


@dataclass(frozen=True)
class RuntimeModelConfig:
    provider: str
    api_key: str
    model: str
    base_url: str
    proxy_url: str
    project: str = ""
    location: str = "global"

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
                "integration_targets": list(RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
                "message": "Vertex Gemini ADC 配置已应用到本次后端运行时。",
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
                "integration_targets": list(RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
                "message": "Vertex Gemini API Key 配置已应用到本次后端运行时。",
            }
        if self.provider == "anthropic":
            return {
                "active": True,
                "provider": self.provider,
                "model": self.model,
                "base_url": self.base_url,
                "proxy_url": self.proxy_url,
                "integration_targets": list(RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
                "message": "Anthropic 服务端已应用到本次后端运行时。",
            }
        return {
            "active": True,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "proxy_url": self.proxy_url,
            "integration_targets": list(RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
            "message": "OpenAI 兼容服务端已应用到本次后端运行时。",
        }


class RuntimeModelConfigStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active_config: RuntimeModelConfig | None = None

    def apply_config(self, config: dict[str, Any]) -> RuntimeModelConfig:
        provider = _normalize_text(config.get("provider", ""))
        if provider not in {"openai_compatible", "anthropic", "vertex_gemini_adc", "vertex_gemini_api_key"}:
            raise ValueError(
                "runtime model config currently supports openai_compatible, anthropic, vertex_gemini_adc or vertex_gemini_api_key only"
            )

        api_key = _normalize_text(config.get("api_key", ""))
        model = _normalize_text(config.get("model", ""))
        base_url = _normalize_text(config.get("base_url", "")) or "https://api.openai.com/v1"
        proxy_url = _normalize_text(config.get("proxy_url", ""))
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
            project = base_url
            base_url = project
            location = _normalize_text(config.get("location", "")) or "global"
            if not project:
                raise ValueError("project is required for vertex_gemini_adc")
        if provider == "vertex_gemini_api_key":
            base_url = ""
            project = ""
            location = _normalize_text(config.get("location", "")) or "global"

        runtime_config = RuntimeModelConfig(
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            proxy_url=proxy_url,
            project=project,
            location=location,
        )
        with self._lock:
            self._active_config = runtime_config
        return runtime_config

    def get_active_config(self) -> RuntimeModelConfig | None:
        with self._lock:
            return self._active_config

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
    "RuntimeModelConfig",
    "RuntimeModelConfigStore",
    "runtime_model_config_store",
]
