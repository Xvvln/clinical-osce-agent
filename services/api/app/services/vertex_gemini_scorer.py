from __future__ import annotations

import json
import os
from typing import Any

from google import genai
from google.genai import types
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models.rubric import LlmRubricRequest, LlmRubricResponse
from app.services.openai_compatible_chat_client import OpenAICompatibleChatClient, OpenAICompatibleSettings
from app.services.runtime_model_config_store import runtime_model_config_store

SYSTEM_PROMPT_TEMPLATE = """你是 OSCE 临床思维训练的评分员。你只能依据输入中列出的 required_evidence 和学生的 student_final_reasoning 打分。你不得引入输入之外的医学事实。

评分规则：
- 满分为 max_score。
- 学生推理表达每覆盖一项 required_evidence 得 (max_score / len(required_evidence)) 分，四舍五入到整数；score 不得超过 max_score。
- 若学生推理包含不在 relevant_facts_revealed 中的事实编造，rationale 必须指出，并不得因此加分。
- rationale 不超过 120 字，不输出具体用药方案、剂量或真实诊疗建议。
"""


class VertexGeminiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OSCE_VERTEX_", env_file=".env", extra="ignore")

    enabled: bool = False
    project: str = ""
    location: str = "global"
    model: str = "gemini-3.1-flash-lite-preview"
    proxy_url: str = "http://127.0.0.1:7897"


class VertexGeminiRubricScorer:
    def __init__(self, settings: VertexGeminiSettings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client or genai.Client(
            vertexai=True,
            project=settings.project,
            location=settings.location,
        )

    def __call__(self, request: LlmRubricRequest) -> LlmRubricResponse:
        response = self._client.models.generate_content(
            model=self._settings.model,
            contents=json.dumps(request.model_dump(), ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT_TEMPLATE,
                response_mime_type="application/json",
                response_schema=LlmRubricResponse,
            ),
        )
        return LlmRubricResponse.model_validate_json(response.text)


class OpenAICompatibleRubricScorer:
    def __init__(self, settings: OpenAICompatibleSettings, client: OpenAICompatibleChatClient | None = None) -> None:
        self._settings = settings
        self._client = client or OpenAICompatibleChatClient(settings)

    def __call__(self, request: LlmRubricRequest) -> LlmRubricResponse:
        return self._client.complete_json(
            system_prompt=SYSTEM_PROMPT_TEMPLATE,
            payload=request.model_dump(),
            response_model=LlmRubricResponse,
            temperature=0.1,
        )


def create_default_vertex_gemini_scorer() -> VertexGeminiRubricScorer | OpenAICompatibleRubricScorer | None:
    runtime_openai_settings = runtime_model_config_store.get_openai_compatible_settings()
    if runtime_openai_settings is not None:
        return OpenAICompatibleRubricScorer(runtime_openai_settings)

    openai_settings = OpenAICompatibleSettings()
    if openai_settings.is_configured:
        return OpenAICompatibleRubricScorer(openai_settings)

    settings = VertexGeminiSettings()
    if not settings.enabled or not settings.project:
        return None
    os.environ["HTTP_PROXY"] = settings.proxy_url
    os.environ["HTTPS_PROXY"] = settings.proxy_url
    os.environ["ALL_PROXY"] = settings.proxy_url
    try:
        return VertexGeminiRubricScorer(settings=settings)
    except ImportError:
        return None


__all__ = [
    "OpenAICompatibleRubricScorer",
    "VertexGeminiRubricScorer",
    "VertexGeminiSettings",
    "create_default_vertex_gemini_scorer",
]
