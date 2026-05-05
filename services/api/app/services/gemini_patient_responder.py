from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]

SYSTEM_PROMPT_TEMPLATE = """你是 OSCE 训练中的标准化病人，只能把 canonical_answer 改写成自然口语回答。

硬性规则：
- 只能表达 canonical_answer 中已经给出的事实，不得新增症状、检查、诊断、治疗或医学解释。
- 不得主动说出 forbidden_terms 中的任何词。
- 如果 canonical_answer 表示病例未提供信息，就只表达“不清楚/没被告知/不太确定”的患者口吻。
- 回答必须是第一人称患者语气，中文，简短，不超过 80 个汉字。
- 不输出用药剂量、治疗方案、手术方案或处置建议。
"""


class PatientResponderRequest(BaseModel):
    case_id: str
    case_title: str
    chief_complaint: str
    student_message: str
    current_intent: str
    canonical_answer: str
    revealed_fact_id: str | None = None
    forbidden_terms: list[str] = Field(default_factory=list)
    prior_messages: list[dict[str, str]] = Field(default_factory=list)


class PatientResponderResponse(BaseModel):
    reply: str = Field(..., min_length=1, max_length=120)


class GeminiPatientSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OSCE_GEMINI_PATIENT_",
        env_file=(PROJECT_ROOT / ".env", ".env"),
        extra="ignore",
    )

    api_key: str = ""
    use_vertex: bool = False
    project: str = ""
    location: str = "global"
    model: str = "gemini-2.5-flash"
    proxy_url: str = "http://127.0.0.1:7897"
    temperature: float = 0.4


class GeminiPatientResponder:
    def __init__(self, settings: GeminiPatientSettings, client: Any | None = None) -> None:
        self._settings = settings
        if client is not None:
            self._client = client
        elif settings.use_vertex:
            self._client = genai.Client(
                vertexai=True,
                project=settings.project,
                location=settings.location,
            )
        else:
            self._client = genai.Client(api_key=settings.api_key)

    def __call__(self, request: PatientResponderRequest) -> str:
        response = self._client.models.generate_content(
            model=self._settings.model,
            contents=json.dumps(request.model_dump(), ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT_TEMPLATE,
                response_mime_type="application/json",
                response_schema=PatientResponderResponse,
                temperature=self._settings.temperature,
            ),
        )
        reply = PatientResponderResponse.model_validate_json(response.text).reply.strip()
        _assert_no_forbidden_terms(reply, request.forbidden_terms)
        return reply


class LazyGeminiPatientResponder:
    def __init__(self) -> None:
        self._responder: GeminiPatientResponder | None = None

    def __call__(self, request: PatientResponderRequest) -> str:
        if self._responder is None:
            self._responder = _create_configured_responder()
        return self._responder(request)


def create_default_gemini_patient_responder() -> LazyGeminiPatientResponder:
    return LazyGeminiPatientResponder()


def _create_configured_responder() -> GeminiPatientResponder:
    settings = GeminiPatientSettings()
    os.environ["HTTP_PROXY"] = settings.proxy_url
    os.environ["HTTPS_PROXY"] = settings.proxy_url
    os.environ["ALL_PROXY"] = settings.proxy_url

    if settings.use_vertex:
        project = settings.project or os.getenv("OSCE_VERTEX_PROJECT", "")
        location = os.getenv("OSCE_GEMINI_PATIENT_LOCATION", "") or os.getenv("OSCE_VERTEX_LOCATION", "") or settings.location
        model = os.getenv("OSCE_GEMINI_PATIENT_MODEL", "") or os.getenv("OSCE_VERTEX_MODEL", "") or settings.model
        if not project:
            raise RuntimeError("未配置 Vertex AI 项目，需设置 OSCE_GEMINI_PATIENT_PROJECT 或 OSCE_VERTEX_PROJECT。")
        return GeminiPatientResponder(
            settings=settings.model_copy(
                update={
                    "api_key": "",
                    "project": project,
                    "location": location,
                    "model": model,
                }
            )
        )

    api_key = settings.api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "未配置 Gemini API key，需设置 OSCE_GEMINI_PATIENT_API_KEY、GEMINI_API_KEY 或 GOOGLE_API_KEY；"
            "如需使用 Vertex ADC，需设置 OSCE_GEMINI_PATIENT_USE_VERTEX=true 和 OSCE_GEMINI_PATIENT_PROJECT。"
        )
    return GeminiPatientResponder(settings=settings.model_copy(update={"api_key": api_key}))


def _assert_no_forbidden_terms(reply: str, forbidden_terms: list[str]) -> None:
    leaked_terms = [term for term in forbidden_terms if term and term in reply]
    if leaked_terms:
        raise RuntimeError(f"标准化病人回答包含禁止泄露词：{leaked_terms}")


__all__ = [
    "GeminiPatientResponder",
    "GeminiPatientSettings",
    "PatientResponderRequest",
    "PatientResponderResponse",
    "create_default_gemini_patient_responder",
]
