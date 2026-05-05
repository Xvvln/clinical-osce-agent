from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]
ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class OpenAICompatibleSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OSCE_OPENAI_",
        env_file=(PROJECT_ROOT / ".env", ".env"),
        extra="ignore",
    )

    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    proxy_url: str = "http://127.0.0.1:7897"
    timeout_seconds: float = 30.0
    temperature: float = 0.2

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.api_key and self.model)


class OpenAICompatibleChatClient:
    def __init__(self, settings: OpenAICompatibleSettings) -> None:
        self._settings = settings

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type[ResponseModelT],
        temperature: float | None = None,
    ) -> ResponseModelT:
        response = self._post_chat_completion(
            {
                "model": self._settings.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "temperature": self._settings.temperature if temperature is None else temperature,
                "response_format": {"type": "json_object"},
            }
        )
        content = _extract_message_content(response.json())
        return response_model.model_validate_json(content)

    def _post_chat_completion(self, payload: dict[str, Any]) -> httpx.Response:
        client_options: dict[str, Any] = {
            "timeout": self._settings.timeout_seconds,
            "follow_redirects": True,
            "trust_env": False,
        }
        if _should_use_proxy(self._settings.proxy_url):
            client_options["proxy"] = self._settings.proxy_url

        headers = {"Content-Type": "application/json"}
        if self._settings.api_key:
            headers["Authorization"] = f"Bearer {self._settings.api_key}"

        with httpx.Client(**client_options) as client:
            response = client.post(_chat_completions_url(self._settings.base_url), headers=headers, json=payload)
        response.raise_for_status()
        return response


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _should_use_proxy(proxy_url: str) -> bool:
    normalized = proxy_url.strip().lower()
    return bool(normalized and normalized not in {"direct", "none", "false", "off", "no"})


def _extract_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenAI compatible response missing choices")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RuntimeError("OpenAI compatible response has invalid choice")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("OpenAI compatible response missing message")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_chunks = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") in {None, "text", "output_text"}
        ]
        if text_chunks:
            return "".join(text_chunks)
    raise RuntimeError("OpenAI compatible response missing text content")


__all__ = [
    "OpenAICompatibleChatClient",
    "OpenAICompatibleSettings",
]
