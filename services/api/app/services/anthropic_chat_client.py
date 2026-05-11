from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]
ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class AnthropicSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OSCE_ANTHROPIC_",
        env_file=(PROJECT_ROOT / ".env", ".env"),
        extra="ignore",
    )

    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"
    model: str = ""
    proxy_url: str = "http://127.0.0.1:7897"
    timeout_seconds: float = 30.0
    temperature: float = 0.2
    max_tokens: int = 1024

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.api_key and self.model)


class AnthropicChatClient:
    def __init__(self, settings: AnthropicSettings) -> None:
        self._settings = settings

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type[ResponseModelT],
        temperature: float | None = None,
    ) -> ResponseModelT:
        response = self._post_message(
            {
                "model": self._settings.model,
                "max_tokens": self._settings.max_tokens,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "temperature": self._settings.temperature if temperature is None else temperature,
            }
        )
        content = _extract_text_content(response.json())
        return _validate_response_content(content, response_model=response_model)

    def _post_message(self, payload: dict[str, Any]) -> httpx.Response:
        client_options: dict[str, Any] = {
            "timeout": self._settings.timeout_seconds,
            "follow_redirects": True,
            "trust_env": False,
        }
        if _should_use_proxy(self._settings.proxy_url):
            client_options["proxy"] = self._settings.proxy_url

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": self._settings.api_key,
        }

        with httpx.Client(**client_options) as client:
            response = client.post(_messages_url(self._settings.base_url), headers=headers, json=payload)
        response.raise_for_status()
        return response


def _messages_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/v1/messages"):
        return normalized
    return f"{normalized}/v1/messages"


def _should_use_proxy(proxy_url: str) -> bool:
    normalized = proxy_url.strip().lower()
    return bool(normalized and normalized not in {"direct", "none", "false", "off", "no"})


def _extract_text_content(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        raise RuntimeError("Anthropic response missing content")
    text_chunks = [
        str(item.get("text", ""))
        for item in content
        if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
    ]
    if text_chunks:
        return "".join(text_chunks)
    raise RuntimeError("Anthropic response missing text content")


def _validate_response_content(content: str, *, response_model: type[ResponseModelT]) -> ResponseModelT:
    normalized_content = _strip_json_fence(content.strip())
    try:
        return response_model.model_validate_json(normalized_content)
    except ValidationError as exc:
        single_text_payload = _single_text_field_payload(normalized_content, response_model=response_model)
        if single_text_payload is None:
            raise exc
        return response_model.model_validate(single_text_payload)


def _strip_json_fence(content: str) -> str:
    if not content.startswith("```"):
        return content
    lines = content.splitlines()
    if len(lines) < 3 or not lines[-1].strip().startswith("```"):
        return content
    return "\n".join(lines[1:-1]).strip()


def _single_text_field_payload(content: str, *, response_model: type[BaseModel]) -> dict[str, str] | None:
    fields = response_model.model_fields
    if len(fields) != 1 or not content:
        return None
    field_name, field_info = next(iter(fields.items()))
    if field_info.annotation is not str:
        return None
    return {field_name: content}


__all__ = [
    "AnthropicChatClient",
    "AnthropicSettings",
]
