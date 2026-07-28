import base64
import binascii
import hashlib
import json
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any

import httpx
import yaml
from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

try:
    from google.auth import exceptions as google_auth_exceptions
except Exception:  # pragma: no cover - optional provider package guard.
    google_auth_exceptions = None

try:
    from google.genai import errors as google_genai_errors
except Exception:  # pragma: no cover - optional provider package guard.
    google_genai_errors = None

from app.services.env_file_loader import load_api_env_file

load_api_env_file()

from app.graph.osce_graph import build_osce_graph
from app.services import retrieval_index, source_retriever
from app.services.admin_display_resolver import (
    enrich_rag_document,
    enrich_rag_knowledge_item,
    enrich_report,
    enrich_session_summary,
    enrich_teaching_focus_pattern,
    enrich_training_skill_candidate,
    reference_labels,
    rubric_item_labels,
)
from app.services.api_call_log_service import api_call_log_store, reset_api_call_context, set_api_call_context
from app.services.auth_store import auth_store
from app.services.browser_origin_policy import browser_state_change_request_rejection_reason
from app.services.derived_teaching_focus_service import (
    build_admin_teaching_focus_patterns,
    get_admin_teaching_focus_pattern,
)
from app.services.evaluation_result_store import evaluation_result_store
from app.services.evaluation_runner import EvaluationBatchResult, EvaluationCase, EvaluationStep, run_evaluation_cases
from app.services.admin_learning_analytics_service import AdminLearningAnalyticsService
from app.services.deployment_config import (
    ADMIN_EMAILS_ENV_NAME,
    DEMO_ADMIN_ENABLED_ENV_NAME,
    DEMO_ADMIN_EMAIL_ENV_NAME,
    DEMO_ADMIN_PASSWORD_ENV_NAME,
    DEMO_STUDENT_ENABLED_ENV_NAME,
    DEMO_STUDENT_EMAIL_ENV_NAME,
    DEMO_STUDENT_PASSWORD_ENV_NAME,
    get_deployment_mode,
    get_configured_admin_email_set,
    is_account_registration_supported,
    is_admin_email_allowed,
    is_demo_admin_effectively_enabled,
    is_demo_student_effectively_enabled,
    is_demo_student_admin_role_conflict,
    is_production_deployment_mode,
    is_runtime_model_config_write_supported,
)
from app.services.dashscope_speech_service import (
    DashScopeSpeechServiceError,
    SpeechServiceConfigurationError,
    SpeechSynthesisResult,
    build_dashscope_speech_service_from_environment,
)
from app.services.demo_seed_service import DEMO_SEED_CONFIG_ERROR_MESSAGE, seed_demo_data
from app.services.model_config_service import build_admin_model_config
from app.services.model_call_policy import (
    DEFAULT_MODEL_OVERLOAD_RETRY_AFTER_SECONDS,
    ModelProviderOverloadedError,
    ModelProviderPolicyError,
    ModelProviderTimeoutError,
    model_request_admission_gate,
    reset_model_call_deadline,
    set_model_call_deadline,
)
from app.services.osce_session_service import (
    CASES_DIR,
    PROCEDURE_REQUEST_ADVANCED_ONLY_DETAIL,
    InvalidProcedureRequestError,
    OsceSessionService,
    ProcedureRequestLimitError,
    ProcedureRequestTrainingModeError,
    SessionClosedError,
    SessionDeletionConflictError,
    UnknownProcedureCodeError,
    load_case_node,
    osce_session_service,
)
from app.services.osce_session_store import (
    SessionAlreadyExistsError,
    SessionDeletedError,
    SessionNotFoundError,
    SessionPersistenceError,
    SessionWriteConflictError,
)
from app.services.patient_voice_policy_service import PatientSpeechProfile, build_patient_speech_profile
from app.services.rag_knowledge_store import rag_knowledge_store
from app.services.rag_document_ingestion_service import (
    RagDocumentParseError,
    chunk_rag_document,
    generate_rag_document_id,
)
from app.services.report_score_metrics import (
    NormalizedScoreMetric,
    aggregate_score_metrics,
    dimension_score_metrics,
)
from app.services.request_body_limit import RequestBodyLimitMiddleware
from app.services.retrieval_eval_service import run_retrieval_eval
from app.services.runtime_model_config_store import (
    RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS,
    RuntimeModelConfig,
    runtime_model_config_store,
)
from app.services.session_resource_policy import SessionResourceLimitError
from app.services.openai_compatible_chat_client import OpenAICompatibleSettings
from app.services.anthropic_chat_client import AnthropicSettings
from app.services.startup_config_service import build_startup_config_self_check
from app.services.speech_synthesis_cache_service import speech_synthesis_cache
from app.services.rule_evaluator import RUBRICS_DIR
from app.services.student_model_config_service import test_student_model_config_connectivity
from app.services.user_model_config_store import user_model_config_store
from app.services.training_insight_service import TrainingInsightService
from app.services.training_skill_auto_approval_service import (
    AUTO_APPROVAL_AGENT_ID,
    training_skill_approval_agent,
    training_skill_auto_approval_settings_store,
)
from app.services.training_skill_candidate_service import training_skill_candidate_service
from app.services.training_skill_candidate_store import training_skill_candidate_store
from app.services.training_skill_context_safety import candidate_with_context_safety_review
from app.services.training_skill_effect_service import TrainingSkillEffectService
from app.services.training_skill_regression_gate import training_skill_regression_gate
from app.validators.case_validator import validate_case, validate_case_rubric_pair, validate_rubric

AUTH_COOKIE_NAME = "clinical_osce_auth"
AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
AUTH_COOKIE_PATH = "/api"
API_PRIVATE_CACHE_CONTROL = "private, no-store, max-age=0"
MODEL_PROVIDER_BUSY_DETAIL = "模型服务正忙，请稍后重试。"
MODEL_PROVIDER_TIMEOUT_DETAIL = "模型服务响应超时，请稍后重试。"
MAX_MODEL_PROVIDER_RETRY_AFTER_SECONDS = 300
BASE_HTTP_SECURITY_HEADERS = {
    "Content-Security-Policy": "base-uri 'self'; frame-ancestors 'none'; object-src 'none'; form-action 'self'",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
PRODUCTION_HSTS_HEADER = "max-age=31536000; includeSubDomains"
DEFAULT_DEMO_ADMIN_DISPLAY_NAME = "演示管理员"
DEFAULT_DEMO_STUDENT_DISPLAY_NAME = "演示学生"
FIXED_ACCOUNT_REGISTRATION_DISABLED_MESSAGE = (
    "不允许创建新账号；固定学生和管理员账号仅在本地模式下显式配置后可用。"
)
TRAINING_MODEL_CONFIG_REQUIRED_ENV_NAME = "OSCE_REQUIRE_RUNTIME_MODEL_CONFIG_FOR_TRAINING"
TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE = "请先在 API 配置中应用可用模型，再开始训练。"
ADMIN_SKILL_CANDIDATE_REVIEW_EVENT_TYPES = {
    "admin_skill_candidate_approved",
    "admin_skill_candidate_agent_reviewed",
    "admin_skill_candidate_auto_approved",
    "admin_skill_candidate_generated",
    "admin_skill_candidate_rejected",
}
RAG_KNOWLEDGE_SCOPES = {"global", "case", "skill", "source"}
RAG_KNOWLEDGE_VISIBILITIES = {
    "pre_submit_safe",
    "post_submit_review",
    "admin_only",
    "source_only",
    "secret_scoring_only",
}
RAG_KNOWLEDGE_AGENT_ROLES = {
    "admin",
    "coach",
    "reflection",
    "retrieval_eval",
    "scoring",
    "skill_approval",
    "skill_generation",
}
RAG_GENERATIVE_AGENT_ROLES = {"coach", "reflection", "skill_approval", "skill_generation"}
RAG_DOCUMENT_DEFAULT_ALLOWED_AGENTS = ["coach", "reflection", "skill_generation", "skill_approval"]
RAG_DOCUMENT_MAX_BYTES = 8 * 1024 * 1024
RAG_DOCUMENT_MAX_BASE64_CHARS = 4 * ((RAG_DOCUMENT_MAX_BYTES + 2) // 3)
API_REQUEST_BODY_MAX_BYTES = 12 * 1024 * 1024
AUDIO_TRANSCRIPTION_MAX_BYTES = 10 * 1024 * 1024
AUDIO_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
REQUEST_VALIDATION_ERROR_DETAIL = "request validation failed"
ADMIN_CASE_REQUEST_MAX_BYTES = 256 * 1024
AUTH_EMAIL_MAX_CHARS = 254
AUTH_PASSWORD_MAX_CHARS = 256
DISPLAY_NAME_MAX_CHARS = 80
IDENTIFIER_MAX_CHARS = 128
PROCEDURE_CODE_MAX_CHARS = 64
PROCEDURE_BATCH_MAX_ITEMS = 64
QUESTION_MAX_CHARS = 500
PROCEDURE_REQUEST_MAX_CHARS = 500
DIAGNOSIS_MAX_CHARS = 128
DIAGNOSIS_REASONING_MAX_CHARS = 4096
HYPOTHESIS_MAX_CHARS = 256
SPEECH_INPUT_MAX_CHARS = 2000
MODEL_API_KEY_MAX_CHARS = 4096
MODEL_NAME_MAX_CHARS = 256
MODEL_URL_MAX_CHARS = 2048
RAG_TEXT_MAX_CHARS = 16_384
RAG_ALLOWED_AGENTS_MAX_ITEMS = 8
RAG_TAGS_MAX_ITEMS = 32
ADMIN_SKILL_CANDIDATE_GENERATION_BATCH_ID = "admin_skill_candidate_generation_smoke"
ADMIN_EVALUATION_STUDENT_ID_PREFIX = "admin_eval_"
MODEL_PROVIDER_EXCEPTION_TYPES: tuple[type[BaseException], ...] = (
    httpx.HTTPError,
    ModelProviderPolicyError,
)
if google_auth_exceptions is not None:
    MODEL_PROVIDER_EXCEPTION_TYPES = MODEL_PROVIDER_EXCEPTION_TYPES + (google_auth_exceptions.GoogleAuthError,)
if google_genai_errors is not None:
    MODEL_PROVIDER_EXCEPTION_TYPES = MODEL_PROVIDER_EXCEPTION_TYPES + (google_genai_errors.APIError,)
LEARNING_TASK_TYPE_LABELS = {
    "start_first_case": "开始首例训练",
    "redo_same_case": "复训当前病例",
    "contrast_case": "推荐对照病例",
}
SOURCE_REGISTRY_PATH = RUBRICS_DIR.parent / "attribution" / "source_registry" / "sources.json"
ADMIN_EVALUATION_CASES = [
    EvaluationCase(
        case_id="appendicitis_001",
        student_id="admin_eval_student_pass",
        steps=[
            EvaluationStep(kind="message", value="什么时候开始疼的？"),
            EvaluationStep(kind="physical_exam", value="abd.palpation.rebound"),
            EvaluationStep(kind="auxiliary_test", value="lab.cbc"),
            EvaluationStep(
                kind="submit_diagnosis",
                value="急性阑尾炎",
                reasoning="转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
            ),
        ],
        expected_total_score=22,
        forbidden_terms=["用药剂量", "治疗方案", "手术方案", "处置建议"],
    ),
]


def _canonical_admin_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


def _build_admin_evaluation_service() -> OsceSessionService:
    return OsceSessionService(
        report_store=osce_session_service.report_store,
        training_event_store=osce_session_service.training_event_store,
        training_skill_store=osce_session_service.training_skill_store,
        session_store=osce_session_service.session_store,
        graph=build_osce_graph(
            patient_responder=_canonical_admin_patient_responder,
            llm_scorer=None,
        ),
    )


def _run_admin_evaluation_cases() -> EvaluationBatchResult:
    return run_evaluation_cases(ADMIN_EVALUATION_CASES, _build_admin_evaluation_service())


def _real_training_session_ids() -> list[str]:
    return [
        str(session["session_id"])
        for session in osce_session_service.session_store.list_session_summaries()
        if not str(session.get("student_id", "")).startswith(ADMIN_EVALUATION_STUDENT_ID_PREFIX)
    ]


def _filter_admin_items(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    normalized_query = query.strip().lower()
    if not normalized_query:
        return items
    return [
        item
        for item in items
        if normalized_query in json.dumps(item, ensure_ascii=False, sort_keys=True).lower()
    ]


def _build_paginated_admin_payload(
    key: str,
    items: list[dict[str, Any]],
    limit: int | None,
    offset: int,
    query: str,
) -> dict[str, object]:
    filtered_items = _filter_admin_items(items, query)
    effective_limit = limit if limit is not None else max(len(filtered_items) - offset, 0)
    return {
        key: filtered_items[offset : offset + effective_limit],
        "pagination": {"limit": effective_limit, "offset": offset, "total": len(filtered_items)},
    }


def _is_deleted_admin_session(session_id: object) -> bool:
    normalized_session_id = str(session_id or "").strip()
    return bool(normalized_session_id) and osce_session_service.session_store.is_session_deleted(
        normalized_session_id
    )


def _build_admin_procedure_simulation_audit_items() -> list[dict[str, Any]]:
    audit_items: list[dict[str, Any]] = []
    for report in osce_session_service.report_store.list_reports():
        if _is_deleted_admin_session(report.get("session_id")):
            continue
        enriched_report = enrich_report(report)
        report_audit_items = enriched_report.get("procedure_simulation_audit_items", [])
        if not isinstance(report_audit_items, list):
            continue
        for audit_item in report_audit_items:
            if not isinstance(audit_item, dict):
                continue
            approval_review = audit_item.get("approval_agent_review", {})
            if not isinstance(approval_review, dict):
                approval_review = {}
            source_context_references = [
                str(reference)
                for reference in audit_item.get("source_context_references", [])
                if str(reference).strip()
            ]
            safety_issues = [
                str(issue)
                for issue in approval_review.get("safety_issues", [])
                if str(issue).strip()
            ]
            audit_items.append(
                {
                    "report_id": str(enriched_report.get("report_id") or ""),
                    "session_id": str(enriched_report.get("session_id") or ""),
                    "case_id": str(enriched_report.get("case_id") or ""),
                    "case_title": str(enriched_report.get("case_title") or enriched_report.get("case_id") or ""),
                    "student_id": str(enriched_report.get("student_id") or ""),
                    "procedure_id": str(audit_item.get("procedure_id") or ""),
                    "kind": str(audit_item.get("kind") or ""),
                    "code": str(audit_item.get("code") or ""),
                    "label": str(audit_item.get("label") or audit_item.get("code") or ""),
                    "result": str(audit_item.get("result") or ""),
                    "approval_status": str(audit_item.get("approval_status") or ""),
                    "approval_decision": str(approval_review.get("decision") or ""),
                    "approval_mode": str(approval_review.get("approval_mode") or ""),
                    "approval_rationale": str(approval_review.get("rationale") or ""),
                    "safety_issues": safety_issues,
                    "source_context_references": source_context_references,
                    "scoring_eligible": audit_item.get("scoring_eligible") is True,
                    "safety_boundary": str(audit_item.get("safety_boundary") or ""),
                }
            )
    return audit_items


def _build_admin_procedure_simulation_summary(items: list[dict[str, Any]]) -> dict[str, object]:
    by_approval_status: dict[str, int] = {}
    by_case_title: dict[str, int] = {}
    for item in items:
        approval_status = str(item.get("approval_status") or "unknown")
        case_title = str(item.get("case_title") or item.get("case_id") or "未命名病例")
        by_approval_status[approval_status] = by_approval_status.get(approval_status, 0) + 1
        by_case_title[case_title] = by_case_title.get(case_title, 0) + 1
    return {
        "total": len(items),
        "by_approval_status": by_approval_status,
        "by_case_title": by_case_title,
    }


def _filter_training_skill_candidate_items_by_review_status(
    items: list[dict[str, Any]],
    review_status: str,
) -> list[dict[str, Any]]:
    normalized_status = review_status.strip()
    if not normalized_status or normalized_status == "all":
        return items
    accepted_statuses = {"approved", "rejected"} if normalized_status == "processed" else {normalized_status}
    return [item for item in items if str(item.get("status", "")).strip() in accepted_statuses]


PROFILE_DIMENSION_LABELS: dict[str, str] = {
    "history_taking": "问诊",
    "physical_exam": "查体",
    "auxiliary_test": "辅助检查",
    "main_diagnosis": "主诊断",
    "differential_diagnosis": "鉴别诊断",
    "reasoning": "推理链",
    "narrative_medicine": "叙事医学",
    "communication_skill": "沟通技巧",
    "medical_ethics": "医学伦理",
    "relationship_building": "关系建立",
}


@asynccontextmanager
async def _app_lifespan(application: FastAPI) -> AsyncIterator[None]:
    recovery_enabled = getattr(
        application.state,
        "pending_session_deletion_recovery_enabled",
        True,
    )
    if recovery_enabled:
        recovery_service = getattr(
            application.state,
            "session_deletion_recovery_service",
            osce_session_service,
        )
        application.state.session_deletion_recovery_stats = (
            recovery_service.resume_pending_session_deletions()
        )
        recovered_events = 0
        while True:
            recovered_batch = recovery_service.drain_session_event_outbox(
                limit=1_000
            )
            recovered_events += recovered_batch
            if recovered_batch < 1_000:
                break
        application.state.session_event_outbox_recovered = recovered_events
    yield


app = FastAPI(
    title="临境 OSCE 智能体（TraceOSCE）API",
    version="0.1.0",
    description="临境 OSCE 智能体（TraceOSCE）的 OSCE 训练后端服务。",
    lifespan=_app_lifespan,
)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_size=API_REQUEST_BODY_MAX_BYTES,
)


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    _: Request,
    __: RequestValidationError,
) -> JSONResponse:
    # FastAPI's default response includes the rejected input. That can reflect
    # API keys, clinical text, or multi-megabyte base64 bodies back to clients.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": REQUEST_VALIDATION_ERROR_DETAIL},
    )


@app.exception_handler(SessionClosedError)
async def handle_session_closed_error(_: Request, exc: SessionClosedError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


@app.exception_handler(SessionResourceLimitError)
async def handle_session_resource_limit_error(
    _: Request,
    exc: SessionResourceLimitError,
) -> JSONResponse:
    details = {
        "message": "本次训练的问诊轮次已达到上限，请提交诊断或开始新的训练。",
        "hint": "本次训练的过程提示次数已达到上限，请结合现有线索继续训练。",
        "hypothesis": "本次训练记录的诊断假设已达到上限，请整理现有假设后提交诊断。",
    }
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": details.get(
                exc.resource_kind,
                "本次训练的可用操作次数已达到上限。",
            )
        },
    )


@app.exception_handler(InvalidProcedureRequestError)
@app.exception_handler(UnknownProcedureCodeError)
async def handle_invalid_procedure_request_error(
    _: Request,
    exc: InvalidProcedureRequestError | UnknownProcedureCodeError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": str(exc)},
    )


@app.exception_handler(ProcedureRequestLimitError)
async def handle_procedure_request_limit_error(
    _: Request,
    exc: ProcedureRequestLimitError,
) -> JSONResponse:
    detail = (
        "本次训练申请的查体项目已达到上限。"
        if exc.procedure_kind == "physical exam"
        else "本次训练申请的辅助检查项目已达到上限。"
    )
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": detail},
    )


@app.exception_handler(SessionAlreadyExistsError)
@app.exception_handler(SessionWriteConflictError)
async def handle_session_write_conflict_error(
    _: Request,
    __: SessionAlreadyExistsError | SessionWriteConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "训练会话已被其他请求更新，请刷新后重试。"},
    )


@app.exception_handler(SessionDeletedError)
@app.exception_handler(SessionNotFoundError)
async def handle_missing_persisted_session_error(
    _: Request,
    __: SessionDeletedError | SessionNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": "session not found"},
    )


@app.exception_handler(SessionDeletionConflictError)
async def handle_session_deletion_conflict_error(
    _: Request,
    __: SessionDeletionConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "会话关联数据存在冲突，无法安全删除。"},
    )


@app.exception_handler(ModelProviderOverloadedError)
async def handle_model_provider_overloaded_error(
    _: Request,
    __: ModelProviderOverloadedError,
) -> JSONResponse:
    return _model_provider_busy_response()


@app.exception_handler(ModelProviderTimeoutError)
async def handle_model_provider_timeout_error(
    _: Request,
    __: ModelProviderTimeoutError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        content={"detail": MODEL_PROVIDER_TIMEOUT_DETAIL},
    )


@app.middleware("http")
async def bind_api_call_log_context(request: Request, call_next: Any) -> Response:
    user = auth_store.get_user_by_session_token(request.cookies.get(AUTH_COOKIE_NAME, ""))
    token = set_api_call_context(
        caller=str(user.get("email", "")) if user else "",
        user_id=str(user.get("user_id", "")) if user else "",
        student_id=str(user.get("user_id", "")) if user else "",
    )
    try:
        return await call_next(request)
    finally:
        reset_api_call_context(token)


@app.middleware("http")
async def enforce_browser_state_change_origin(request: Request, call_next: Any) -> Response:
    rejection_reason = browser_state_change_request_rejection_reason(
        method=request.method,
        path=request.url.path,
        origin=request.headers.get("origin"),
        referer=request.headers.get("referer"),
        sec_fetch_site=request.headers.get("sec-fetch-site"),
    )
    if rejection_reason is not None:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "cross-origin state-changing request rejected"},
        )
    return await call_next(request)


@app.middleware("http")
async def add_http_security_headers(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    for header_name, header_value in BASE_HTTP_SECURITY_HEADERS.items():
        response.headers[header_name] = header_value
    if request.url.path == "/api" or request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = API_PRIVATE_CACHE_CONTROL
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    if is_production_deployment_mode():
        response.headers["Strict-Transport-Security"] = PRODUCTION_HSTS_HEADER
    return response


ProcedureCode = Annotated[str, Field(max_length=PROCEDURE_CODE_MAX_CHARS)]
RagAgentRole = Annotated[str, Field(max_length=32)]
RagTag = Annotated[str, Field(max_length=64)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _validate_admin_case_request_size(payload: dict[str, Any]) -> None:
    logical_size = len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    if logical_size > ADMIN_CASE_REQUEST_MAX_BYTES:
        raise ValueError(
            f"case request payload must not exceed {ADMIN_CASE_REQUEST_MAX_BYTES} bytes"
        )


class AuthRegisterRequest(RequestModel):
    email: str = Field(max_length=AUTH_EMAIL_MAX_CHARS)
    password: str = Field(max_length=AUTH_PASSWORD_MAX_CHARS)
    display_name: str | None = Field(default=None, max_length=DISPLAY_NAME_MAX_CHARS)


class AuthLoginRequest(RequestModel):
    email: str = Field(max_length=AUTH_EMAIL_MAX_CHARS)
    password: str = Field(max_length=AUTH_PASSWORD_MAX_CHARS)


class CreateSessionRequest(RequestModel):
    case_id: str = Field(max_length=IDENTIFIER_MAX_CHARS)
    student_id: str = Field(default="anonymous", max_length=IDENTIFIER_MAX_CHARS)
    training_difficulty: str = Field(default="beginner", max_length=64)


class MessageRequest(RequestModel):
    message: str = Field(max_length=QUESTION_MAX_CHARS)


class AudioSpeechRequest(RequestModel):
    input: str = Field(max_length=SPEECH_INPUT_MAX_CHARS)
    voice: str | None = Field(default=None, max_length=IDENTIFIER_MAX_CHARS)
    model: str | None = Field(default=None, max_length=MODEL_NAME_MAX_CHARS)
    session_id: str | None = Field(default=None, max_length=IDENTIFIER_MAX_CHARS)
    message_index: int | None = None
    emotion: str | None = Field(default=None, max_length=32)


class PhysicalExamRequest(RequestModel):
    exam_code: ProcedureCode


class PhysicalExamBatchRequest(RequestModel):
    exam_codes: list[ProcedureCode] = Field(
        default_factory=list,
        max_length=PROCEDURE_BATCH_MAX_ITEMS,
    )


class AuxiliaryTestRequest(RequestModel):
    test_code: ProcedureCode


class AuxiliaryTestBatchRequest(RequestModel):
    test_codes: list[ProcedureCode] = Field(
        default_factory=list,
        max_length=PROCEDURE_BATCH_MAX_ITEMS,
    )


class ProcedureFreeTextRequest(RequestModel):
    request_text: str = Field(max_length=PROCEDURE_REQUEST_MAX_CHARS)


class SubmitDiagnosisRequest(RequestModel):
    diagnosis: str = Field(max_length=DIAGNOSIS_MAX_CHARS)
    reasoning: str = Field(max_length=DIAGNOSIS_REASONING_MAX_CHARS)


class HypothesisRequest(RequestModel):
    hypothesis: str = Field(max_length=HYPOTHESIS_MAX_CHARS)


class StudentModelConfigTestRequest(RequestModel):
    provider: str = Field(max_length=64)
    api_key: str = Field(default="", max_length=MODEL_API_KEY_MAX_CHARS)
    model: str = Field(default="", max_length=MODEL_NAME_MAX_CHARS)
    base_url: str = Field(default="", max_length=MODEL_URL_MAX_CHARS)
    proxy_url: str = Field(default="", max_length=MODEL_URL_MAX_CHARS)


class AdminTrainingSkillReviewRequest(RequestModel):
    # Legacy clients may still send reviewer_id; authorization always derives the
    # reviewer from the authenticated admin session, so ignore that untrusted hint.
    model_config = ConfigDict(extra="ignore")

    candidate_id: str = Field(max_length=IDENTIFIER_MAX_CHARS)


class AdminTrainingSkillAutoApprovalSettingsRequest(RequestModel):
    auto_apply_enabled: bool


class AdminCaseValidationRequest(RequestModel):
    case: dict[str, Any]
    rubric: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_logical_payload_size(self) -> "AdminCaseValidationRequest":
        _validate_admin_case_request_size(
            {"case": self.case, "rubric": self.rubric}
        )
        return self


class AdminCaseImportRequest(RequestModel):
    case: dict[str, Any]
    rubric: dict[str, Any]

    @model_validator(mode="after")
    def validate_logical_payload_size(self) -> "AdminCaseImportRequest":
        _validate_admin_case_request_size(
            {"case": self.case, "rubric": self.rubric}
        )
        return self


class AdminCaseFieldUpdateRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    case_title: str | None = Field(default=None, max_length=120)
    course_module: str | None = Field(default=None, max_length=64)
    difficulty: str | None = Field(default=None, max_length=64)
    chief_complaint: str | None = Field(default=None, max_length=500)
    safety_notes: str | None = Field(default=None, max_length=1000)


class AdminRubricItemUpdateRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(..., min_length=1, max_length=1000)


class AdminRagKnowledgeItemRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_id: str = Field(default="", max_length=256)
    scope: str = Field(default="", max_length=64)
    case_id: str = Field(default="", max_length=IDENTIFIER_MAX_CHARS)
    content_kind: str = Field(default="", max_length=64)
    visibility: str = Field(default="", max_length=64)
    allowed_agents: list[RagAgentRole] = Field(
        default_factory=list,
        max_length=RAG_ALLOWED_AGENTS_MAX_ITEMS,
    )
    source_id: str = Field(default="", max_length=IDENTIFIER_MAX_CHARS)
    title: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=RAG_TEXT_MAX_CHARS)
    tags: list[RagTag] = Field(default_factory=list, max_length=RAG_TAGS_MAX_ITEMS)
    version: int = Field(default=1, ge=1, le=2_147_483_647)


class AdminRagDocumentUploadRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(default="", max_length=64)
    case_id: str = Field(default="", max_length=IDENTIFIER_MAX_CHARS)
    file_name: str = Field(default="", max_length=255)
    content_base64: str = Field(default="", max_length=RAG_DOCUMENT_MAX_BASE64_CHARS)
    visibility: str = Field(default="pre_submit_safe", max_length=64)
    allowed_agents: list[RagAgentRole] = Field(
        default_factory=lambda: list(RAG_DOCUMENT_DEFAULT_ALLOWED_AGENTS),
        max_length=RAG_ALLOWED_AGENTS_MAX_ITEMS,
    )
    source_id: str = Field(default="", max_length=IDENTIFIER_MAX_CHARS)
    tags: list[RagTag] = Field(default_factory=list, max_length=RAG_TAGS_MAX_ITEMS)
    enabled: bool = True


class AdminRagDocumentEnabledRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class AdminEvaluationRunRequest(RequestModel):
    batch_id: str = Field(max_length=IDENTIFIER_MAX_CHARS)


def _validate_auth_request(email: str, password: str) -> None:
    if "@" not in email or not email.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="valid email is required")
    if not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="password is required")


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_production_deployment_mode(),
        max_age=AUTH_COOKIE_MAX_AGE_SECONDS,
        path=AUTH_COOKIE_PATH,
    )


async def _read_upload_file_with_limit(file: UploadFile, *, max_bytes: int) -> bytes:
    content = bytearray()
    while True:
        remaining_bytes = max_bytes - len(content)
        chunk = await file.read(min(AUDIO_UPLOAD_READ_CHUNK_BYTES, remaining_bytes + 1))
        if not chunk:
            return bytes(content)
        if len(chunk) > remaining_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="audio file is too large",
            )
        content.extend(chunk)


def _require_current_user(auth_token: str | None) -> dict[str, str]:
    if not auth_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    user = auth_store.get_user_by_session_token(auth_token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user


def _is_training_model_config_required() -> bool:
    value = os.getenv(TRAINING_MODEL_CONFIG_REQUIRED_ENV_NAME, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _resolve_user_runtime_model_config(user_id: str) -> RuntimeModelConfig | None:
    if not is_runtime_model_config_write_supported():
        return None
    saved_config = user_model_config_store.get_runtime_config(user_id)
    if saved_config is None:
        return None
    try:
        return runtime_model_config_store.build_config(saved_config.to_config_dict())
    except ValueError:
        return None


def _runtime_model_config_public_payload_for_user(user_id: str) -> dict[str, object]:
    if not is_runtime_model_config_write_supported():
        environment_payload = _environment_runtime_model_config_public_payload()
        if environment_payload is not None:
            return environment_payload
        return {
            "active": False,
            "provider": "",
            "model": "",
            "base_url": "",
            "proxy_url": "",
            "integration_targets": [],
            "api_key_saved": False,
            "message": "当前服务端未配置可用模型。",
        }
    saved_config = _resolve_user_runtime_model_config(user_id)
    if saved_config is None:
        return {
            "active": False,
            "provider": "",
            "model": "",
            "base_url": "",
            "proxy_url": "",
            "integration_targets": [],
            "api_key_saved": False,
            "message": "当前账号没有已保存并应用的模型配置。",
        }
    payload = saved_config.public_payload()
    payload["api_key_saved"] = bool(saved_config.api_key)
    return payload


def _environment_runtime_model_config_public_payload() -> dict[str, object] | None:
    openai_settings = OpenAICompatibleSettings()
    if openai_settings.is_configured:
        return {
            "active": True,
            "provider": "openai_compatible",
            "model": openai_settings.model,
            "base_url": "",
            "proxy_url": "",
            "integration_targets": list(RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
            "api_key_saved": False,
            "message": "服务端已统一配置 Gemini 模型；前端不可修改 API Key。",
        }

    anthropic_settings = AnthropicSettings()
    if anthropic_settings.is_configured:
        return {
            "active": True,
            "provider": "anthropic",
            "model": anthropic_settings.model,
            "base_url": anthropic_settings.base_url,
            "proxy_url": anthropic_settings.proxy_url,
            "integration_targets": list(RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
            "api_key_saved": False,
            "message": "服务端已统一配置模型；前端不可修改 API Key。",
        }

    if _environment_gemini_or_vertex_model_configured():
        return {
            "active": True,
            "provider": "vertex_gemini_adc" if _truthy_env("OSCE_GEMINI_PATIENT_USE_VERTEX") else "gemini",
            "model": _env("OSCE_GEMINI_PATIENT_MODEL") or _env("OSCE_VERTEX_MODEL") or "gemini-3.1-pro-preview",
            "base_url": _env("OSCE_GEMINI_PATIENT_PROJECT") or _env("OSCE_VERTEX_PROJECT"),
            "proxy_url": _env("OSCE_GEMINI_PATIENT_PROXY_URL") or _env("OSCE_VERTEX_PROXY_URL") or "http://127.0.0.1:7897",
            "integration_targets": ["patient_responder", "turn_intent_agent", "coach_agent", "procedure_request_router"],
            "api_key_saved": False,
            "message": "服务端已统一配置 Gemini 模型；前端不可修改 API Key。",
        }
    return None


def _environment_training_model_configured() -> bool:
    return (
        OpenAICompatibleSettings().is_configured
        or AnthropicSettings().is_configured
        or _environment_gemini_or_vertex_model_configured()
    )


def _environment_gemini_or_vertex_model_configured() -> bool:
    if _truthy_env("OSCE_GEMINI_PATIENT_USE_VERTEX"):
        return bool(
            _env("OSCE_GEMINI_PATIENT_PROJECT")
            or _env("OSCE_VERTEX_PROJECT")
            or _env("OSCE_GEMINI_PATIENT_API_KEY")
            or _env("OSCE_VERTEX_API_KEY")
        )
    return bool(_env("OSCE_GEMINI_PATIENT_API_KEY") or _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY"))


def _truthy_env(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _build_user_runtime_model_config_request(user_id: str, request: "StudentModelConfigTestRequest") -> dict[str, str]:
    api_key = request.api_key
    saved_config = user_model_config_store.get_runtime_config(user_id)
    if not api_key and saved_config is not None and saved_config.provider == request.provider:
        api_key = saved_config.api_key
    return {
        "provider": request.provider,
        "api_key": api_key,
        "model": request.model,
        "base_url": request.base_url,
        "proxy_url": request.proxy_url,
    }


def _require_runtime_model_config_for_training(user_id: str) -> RuntimeModelConfig | None:
    runtime_config = _resolve_user_runtime_model_config(user_id)
    has_user_config = runtime_config is not None
    has_environment_config = not is_runtime_model_config_write_supported() and _environment_training_model_configured()
    if _is_training_model_config_required() and not has_user_config and not has_environment_config:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE)
    return runtime_config


@contextmanager
def _use_user_runtime_model_config(
    user_id: str,
    *,
    require_for_training: bool,
) -> Iterator[RuntimeModelConfig | None]:
    runtime_config = (
        _require_runtime_model_config_for_training(user_id)
        if require_for_training
        else _resolve_user_runtime_model_config(user_id)
    )
    with runtime_model_config_store.use_config(runtime_config):
        yield runtime_config


def _enrich_report_optional_agents_for_user(session_id: str, user_id: str) -> dict[str, Any] | None:
    try:
        with _use_user_runtime_model_config(user_id, require_for_training=False):
            return osce_session_service.enrich_report_optional_agents(session_id)
    except SessionPersistenceError:
        return None


async def _admit_authenticated_model_request(
    request: Request,
) -> AsyncIterator[None]:
    # FastAPI resolves request bodies before dependencies. Invalid or slow
    # unauthenticated uploads therefore cannot reserve scarce model capacity.
    user = auth_store.get_user_by_session_token(
        request.cookies.get(AUTH_COOKIE_NAME, "")
    )
    if user is None:
        yield
        return
    if not model_request_admission_gate.try_acquire():
        raise ModelProviderOverloadedError(
            "model request concurrency limit reached"
        )
    deadline_token = set_model_call_deadline()
    try:
        yield
    finally:
        reset_model_call_deadline(deadline_token)
        model_request_admission_gate.release()


def _model_provider_busy_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": MODEL_PROVIDER_BUSY_DETAIL},
        headers={
            "Retry-After": str(
                DEFAULT_MODEL_OVERLOAD_RETRY_AFTER_SECONDS
            )
        },
    )


def _model_provider_gateway_error(exc: BaseException) -> HTTPException:
    if isinstance(exc, ModelProviderOverloadedError):
        return _model_provider_busy_http_exception()
    if isinstance(exc, (ModelProviderTimeoutError, httpx.TimeoutException)):
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=MODEL_PROVIDER_TIMEOUT_DETAIL,
        )
    if isinstance(exc, httpx.HTTPStatusError):
        upstream_status = exc.response.status_code
        if upstream_status == status.HTTP_429_TOO_MANY_REQUESTS:
            return _model_provider_busy_http_exception(
                retry_after=_safe_model_provider_retry_after(
                    exc.response.headers.get("Retry-After")
                )
            )
        if upstream_status in {
            status.HTTP_408_REQUEST_TIMEOUT,
            status.HTTP_504_GATEWAY_TIMEOUT,
        }:
            return HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=MODEL_PROVIDER_TIMEOUT_DETAIL,
            )
        detail = _model_provider_response_error_detail(exc.response)
        message = f"模型服务调用失败：HTTP {upstream_status}"
        if detail:
            message = f"{message}：{detail}"
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=message,
        )
    if google_auth_exceptions is not None and isinstance(exc, google_auth_exceptions.DefaultCredentialsError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="模型服务鉴权失败：Google ADC 未配置或不可用，请在 API 配置中切换为可用服务端，或在服务器配置 ADC。",
        )
    if google_auth_exceptions is not None and isinstance(exc, google_auth_exceptions.GoogleAuthError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"模型服务鉴权失败：{exc.__class__.__name__}",
        )
    if google_genai_errors is not None and isinstance(exc, google_genai_errors.APIError):
        code = getattr(exc, "code", None)
        status_label = str(getattr(exc, "status", "") or "").strip()
        normalized_status_label = status_label.upper()
        if str(code) == "429" or normalized_status_label == "RESOURCE_EXHAUSTED":
            return _model_provider_busy_http_exception()
        if (
            str(code) in {"408", "504"}
            or normalized_status_label == "DEADLINE_EXCEEDED"
        ):
            return HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=MODEL_PROVIDER_TIMEOUT_DETAIL,
            )
        detail = str(getattr(exc, "message", "") or "").strip()
        parts = [part for part in (detail, status_label) if part]
        compact_detail = "；".join(dict.fromkeys(" ".join(part.split())[:240] for part in parts if part.strip()))
        message = f"模型服务调用失败：HTTP {code}" if code else "模型服务调用失败"
        if compact_detail:
            message = f"{message}：{compact_detail}"
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"模型服务调用失败：{exc.__class__.__name__}")


def _model_provider_busy_http_exception(
    *,
    retry_after: str | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=MODEL_PROVIDER_BUSY_DETAIL,
        headers={
            "Retry-After": (
                retry_after
                or str(DEFAULT_MODEL_OVERLOAD_RETRY_AFTER_SECONDS)
            )
        },
    )


def _safe_model_provider_retry_after(value: str | None) -> str:
    try:
        retry_after_seconds = int(str(value or "").strip())
    except ValueError:
        retry_after_seconds = 0
    if 1 <= retry_after_seconds <= MAX_MODEL_PROVIDER_RETRY_AFTER_SECONDS:
        return str(retry_after_seconds)
    return str(DEFAULT_MODEL_OVERLOAD_RETRY_AFTER_SECONDS)


def _training_flow_runtime_error(exc: BaseException) -> HTTPException:
    trace_id = str(getattr(exc, "osce_runtime_trace_id", "") or "").strip()
    detail = (
        f"训练流程异常，管理员可在训练日志中查看错误编号：{trace_id}"
        if trace_id
        else "训练流程异常，管理员可在训练日志中查看具体错误。"
    )
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail)


def _model_provider_response_error_detail(response: httpx.Response) -> str:
    parts: list[str] = []
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error_payload = payload.get("error", payload)
        if isinstance(error_payload, dict):
            for key in ("message", "code", "type", "param"):
                value = error_payload.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
        elif isinstance(error_payload, str) and error_payload.strip():
            parts.append(error_payload.strip())
    elif isinstance(payload, str) and payload.strip():
        parts.append(payload.strip())
    if not parts and response.text.strip():
        parts.append(response.text.strip())
    compact_parts: list[str] = []
    for part in parts:
        compact_part = " ".join(part.split())
        if compact_part and compact_part not in compact_parts:
            compact_parts.append(compact_part[:240])
    return "；".join(compact_parts)


def _get_admin_email_set() -> set[str]:
    return get_configured_admin_email_set()


def _is_demo_admin_enabled() -> bool:
    return is_demo_admin_effectively_enabled()


def _get_demo_admin_email() -> str:
    return os.environ.get(DEMO_ADMIN_EMAIL_ENV_NAME, "").strip().lower()


def _get_demo_admin_password() -> str:
    return os.environ.get(DEMO_ADMIN_PASSWORD_ENV_NAME, "")


def _is_demo_student_enabled() -> bool:
    return is_demo_student_effectively_enabled()


def _get_demo_student_email() -> str:
    return os.environ.get(DEMO_STUDENT_EMAIL_ENV_NAME, "").strip().lower()


def _get_demo_student_password() -> str:
    return os.environ.get(DEMO_STUDENT_PASSWORD_ENV_NAME, "")


def _build_auth_user_payload(user: dict[str, str]) -> dict[str, object]:
    return {
        **user,
        "is_admin": is_admin_email_allowed(user["email"]),
    }


def _matches_demo_admin_credentials(email: str, password: str) -> bool:
    return _is_demo_admin_enabled() and email.strip().lower() == _get_demo_admin_email() and password == _get_demo_admin_password()


def _ensure_demo_admin_user(email: str, password: str) -> dict[str, str]:
    return auth_store.upsert_user_password(email=email, password=password, display_name=DEFAULT_DEMO_ADMIN_DISPLAY_NAME)


def _matches_demo_student_credentials(email: str, password: str) -> bool:
    return (
        _is_demo_student_enabled()
        and email.strip().lower() == _get_demo_student_email()
        and password == _get_demo_student_password()
    )


def _ensure_demo_student_user(email: str, password: str) -> dict[str, str]:
    return auth_store.upsert_user_password(email=email, password=password, display_name=DEFAULT_DEMO_STUDENT_DISPLAY_NAME)


def _authenticate_fixed_demo_user(email: str, password: str) -> dict[str, str] | None:
    if is_demo_student_admin_role_conflict():
        return None
    if _matches_demo_admin_credentials(email, password):
        return _ensure_demo_admin_user(email, password)
    if _matches_demo_student_credentials(email, password):
        return _ensure_demo_student_user(email, password)
    return None


def _require_admin_user(auth_token: str | None) -> dict[str, str]:
    user = _require_current_user(auth_token)
    if not is_admin_email_allowed(user["email"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin access required")
    return user


def _require_owned_session(session_id: str, auth_token: str | None) -> dict[str, object]:
    user = _require_current_user(auth_token)
    session = osce_session_service.get_session(session_id)
    if session is None or session.get("student_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="session not found")
    return session


def _resolve_patient_speech_request(request: AudioSpeechRequest, auth_token: str | None) -> tuple[str, PatientSpeechProfile]:
    if not request.session_id or request.message_index is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="患者语音上下文不完整。")

    session = _require_owned_session(request.session_id, auth_token)
    messages = session.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="训练会话没有可播放的消息。")
    if request.message_index < 0 or request.message_index >= len(messages):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="患者消息不存在。")

    message = messages[request.message_index]
    if not isinstance(message, dict) or message.get("role") != "patient":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能播放标准化病人消息。")

    speech_text = str(message.get("content") or "").strip()
    if not speech_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="患者消息为空，无法生成语音。")

    case_id = str(session.get("case_id") or "")
    case = load_case_node(case_id)
    speech_profile = build_patient_speech_profile(
        case.patient_profile,
        emotion=str(message.get("emotion") or request.emotion or ""),
    )
    return speech_text, speech_profile


def _build_speech_streaming_response(
    result: SpeechSynthesisResult,
    *,
    speech_profile: PatientSpeechProfile | None,
    cache_status: str,
) -> StreamingResponse:
    headers = {
        "Cache-Control": "no-store",
        "X-OSCE-Speech-Provider": result.provider,
        "X-OSCE-Speech-Model": result.model,
        "X-OSCE-Speech-Voice": result.voice,
        "X-OSCE-Speech-Cache": cache_status,
    }
    if speech_profile is not None:
        headers.update(
            {
                "X-OSCE-Speech-Policy": speech_profile.policy,
                "X-OSCE-Speech-Patient-Gender": speech_profile.normalized_gender,
                "X-OSCE-Speech-Patient-Age-Band": speech_profile.age_band,
                "X-OSCE-Speech-Emotion": speech_profile.normalized_emotion,
            }
        )
    if result.request_id:
        headers["X-OSCE-Speech-Request-Id"] = result.request_id
    return StreamingResponse(BytesIO(result.audio_bytes), media_type=result.mime_type, headers=headers)


def _require_readable_session(session_id: str, auth_token: str | None) -> dict[str, object]:
    user = _require_current_user(auth_token)
    session = osce_session_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.get("student_id") == user["user_id"] or user["email"].lower() in _get_admin_email_set():
        return session
    raise HTTPException(status_code=404, detail="session not found")


def _require_open_owned_session(session_id: str, auth_token: str | None) -> dict[str, object]:
    session = _require_owned_session(session_id, auth_token)
    if _is_completed_training_session(session):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="训练已结束，请查看报告。")
    return session


def _is_completed_training_session(session: dict[str, object]) -> bool:
    return bool(session.get("final_submission")) or bool(session.get("feedback_report")) or session.get("stage") in {
        "diagnosis_submission",
        "feedback",
    }


def _append_admin_skill_candidate_review_event(
    candidate: dict[str, Any],
    reviewer_email: str,
    event_type: str,
    payload: dict[str, object],
) -> None:
    osce_session_service.training_event_store.append_event(
        session_id=str(candidate["candidate_id"]),
        case_id=str(candidate["trigger_item_id"]),
        student_id=reviewer_email,
        event_type=event_type,
        payload=payload,
    )


def _summarize_training_skill_candidate(candidate: dict[str, Any]) -> dict[str, object]:
    candidate = candidate_with_context_safety_review(candidate)
    review = candidate["review"]
    return enrich_training_skill_candidate({
        "candidate_id": candidate["candidate_id"],
        "trigger_item_id": candidate["trigger_item_id"],
        "trigger_item_ids": list(candidate.get("trigger_item_ids", [])),
        "case_ids": list(candidate.get("case_ids", [])),
        "skill_type": str(candidate.get("skill_type", "")),
        "stage_scope": list(candidate.get("stage_scope", [])),
        "effect_status": str(candidate.get("effect_status", "")),
        "title": candidate["title"],
        "status": review["status"],
        "regression_passed": review["regression_passed"],
        "source_report_count": candidate["source_report_count"],
        "support_count": candidate["support_count"],
    })


def _list_admin_skill_candidate_review_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for candidate in training_skill_candidate_store.list_candidate_summaries():
        events.extend(
            event
            for event in osce_session_service.training_event_store.list_session_events(str(candidate["candidate_id"]))
            if event["event_type"] in ADMIN_SKILL_CANDIDATE_REVIEW_EVENT_TYPES
        )
    return sorted(events, key=lambda event: str(event["created_at"]), reverse=True)


def _set_approval_agent_decision(candidate: dict[str, Any], review: dict[str, Any]) -> None:
    agent_review = candidate.get("approval_agent_review")
    if not isinstance(agent_review, dict):
        return
    candidate["approval_agent_review"] = {
        **agent_review,
        "decision": "approved_for_auto_apply" if review["status"] == "ready_for_review" else "blocked_by_regression",
        "regression_status": review["status"],
        "regression_passed": review["regression_passed"],
    }


def _get_average_score(reports: list[dict[str, Any]]) -> int:
    if not reports:
        return 0
    return round(sum(int(report["total_score"]) for report in reports) / len(reports))


def _get_dimension_averages(reports: list[dict[str, Any]]) -> list[dict[str, object]]:
    metrics_by_dimension: dict[str, list[NormalizedScoreMetric]] = {}
    for report in reports:
        for key, metric in dimension_score_metrics(report).items():
            metrics_by_dimension.setdefault(key, []).append(metric)

    return sorted(
        [
            {
                "key": key,
                "label": PROFILE_DIMENSION_LABELS.get(key, key),
                "average": summary["average_score"],
                **summary,
            }
            for key, metrics in metrics_by_dimension.items()
            if (summary := aggregate_score_metrics(metrics))["average_percentage"]
            is not None
        ],
        key=lambda item: float(item["average_percentage"]),
        reverse=True,
    )


def _build_learning_path(reports: list[dict[str, Any]], weakest_dimension: dict[str, object] | None) -> list[dict[str, object]]:
    if not reports:
        return [
            _enrich_learning_path_task(
                {
                    "task_type": "start_first_case",
                    "case_id": "appendicitis_001",
                    "objective": "先完成一次右下腹痛教学病例的完整 OSCE 训练，形成可评分报告后再生成个性化路径。",
                    "target_rubric_items": [],
                    "source_report_count": 0,
                    "source_references": ["case:appendicitis_001"],
                }
            )
        ]

    latest_report = reports[0]
    latest_case_id = str(latest_report.get("case_id") or "appendicitis_001")
    target_items = _get_top_missed_profile_items(reports)
    target_item_ids = [item["item_id"] for item in target_items]
    target_item_refs = [dict(item) for item in target_items]
    weakest_label = str(weakest_dimension.get("label")) if weakest_dimension else "当前薄弱维度"
    source_report_count = len(reports)

    learning_path: list[dict[str, object]] = [
        _enrich_learning_path_task(
            {
                "task_type": "redo_same_case",
                "case_id": latest_case_id,
                "objective": f"复训{_get_case_title(latest_case_id)}，优先补强{weakest_label}并补齐本轮反复缺失的评分项。",
                "target_rubric_items": target_item_ids,
                "target_rubric_item_refs": target_item_refs,
                "source_report_count": source_report_count,
                "source_references": [
                    f"rubric:{item['case_id']}_rubric.item.{item['item_id']}"
                    for item in target_items
                ],
            },
            rubric_label_case_id=latest_case_id,
        )
    ]
    contrast_task = _build_contrast_learning_task(reports, latest_case_id, target_item_refs, source_report_count)
    if contrast_task is not None:
        learning_path.append(_enrich_learning_path_task(contrast_task, rubric_label_case_id=latest_case_id))
    return learning_path


def _enrich_learning_path_task(
    task: dict[str, object],
    *,
    rubric_label_case_id: str | None = None,
) -> dict[str, object]:
    case_id = str(task.get("case_id") or "")
    task_type = str(task.get("task_type") or "")
    target_rubric_items = [str(item_id) for item_id in task.get("target_rubric_items", []) if str(item_id)]
    target_rubric_item_refs = [
        {
            "case_id": str(item.get("case_id") or ""),
            "item_id": str(item.get("item_id") or ""),
        }
        for item in task.get("target_rubric_item_refs", [])
        if isinstance(item, dict) and str(item.get("item_id") or "")
    ]
    source_references = [str(reference) for reference in task.get("source_references", []) if str(reference)]
    label_case_id = rubric_label_case_id or case_id
    target_rubric_item_labels = (
        _rubric_item_labels_for_refs(target_rubric_item_refs, fallback_case_id=label_case_id)
        if target_rubric_item_refs
        else rubric_item_labels(target_rubric_items, [label_case_id])
    )
    public_task = dict(task)
    public_task.pop("target_rubric_item_refs", None)
    return {
        **public_task,
        "task_type_label": LEARNING_TASK_TYPE_LABELS.get(task_type, task_type or "训练任务"),
        "case_title": _get_case_title(case_id),
        "target_rubric_item_labels": target_rubric_item_labels,
        "source_reference_labels": reference_labels(source_references),
    }


def _rubric_item_labels_for_refs(
    item_refs: list[dict[str, str]],
    *,
    fallback_case_id: str,
) -> list[str]:
    labels: list[str] = []
    for item_ref in item_refs:
        item_id = item_ref["item_id"]
        case_id = item_ref.get("case_id") or fallback_case_id
        resolved = rubric_item_labels([item_id], [case_id])
        labels.append(resolved[0] if resolved else item_id)
    return labels


def _get_top_missed_profile_items(reports: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, str]]:
    ranked_items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for report in reports:
        case_id = str(report.get("case_id") or "unknown")
        for item_id in report.get("missed_items", []):
            if not isinstance(item_id, str):
                continue
            key = (case_id, item_id)
            if key in seen:
                continue
            seen.add(key)
            ranked_items.append({"case_id": case_id, "item_id": item_id})
            if len(ranked_items) >= limit:
                return ranked_items
    return ranked_items


def _report_has_pending_optional_agent_enrichment(report: dict[str, Any]) -> bool:
    personal_skill_candidate = report.get("personal_skill_candidate")
    return (
        isinstance(personal_skill_candidate, dict)
        and personal_skill_candidate.get("status") in {"generation_pending", "generation_failed"}
    )


def _build_contrast_learning_task(
    reports: list[dict[str, Any]],
    latest_case_id: str,
    target_item_refs: list[dict[str, str]],
    source_report_count: int,
) -> dict[str, object] | None:
    contrast_case_id = _find_recommended_contrast_case_id(reports, latest_case_id)
    if contrast_case_id is None:
        return None
    target_item_ids = [item["item_id"] for item in target_item_refs]
    return {
        "task_type": "contrast_case",
        "case_id": contrast_case_id,
        "objective": f"对照{_get_case_title(contrast_case_id)}，迁移本轮薄弱维度的问诊、检查选择和证据链表达。",
        "target_rubric_items": target_item_ids,
        "target_rubric_item_refs": [dict(item) for item in target_item_refs],
        "source_report_count": source_report_count,
        "source_references": [f"case:{contrast_case_id}"],
    }


def _find_recommended_contrast_case_id(reports: list[dict[str, Any]], latest_case_id: str) -> str | None:
    for report in reports:
        for recommendation in report.get("knowledge_recommendations", []):
            if not isinstance(recommendation, dict):
                continue
            reference = recommendation.get("reference")
            if not isinstance(reference, str) or not reference.startswith("case:"):
                continue
            case_id = reference.removeprefix("case:")
            if case_id and case_id != latest_case_id:
                return case_id
    for case_path in sorted(CASES_DIR.glob("*.json")):
        case_id = case_path.stem
        if case_id != latest_case_id:
            return case_id
    return None


def _get_case_title(case_id: str) -> str:
    case_path = CASES_DIR / f"{case_id}.json"
    if not case_path.exists():
        return case_id
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    title = payload.get("case_title")
    return str(title) if isinstance(title, str) and title else case_id


def _load_admin_rubric(rubric_id: str) -> dict[str, Any] | None:
    if "/" in rubric_id or "\\" in rubric_id or ".." in rubric_id:
        return None
    rubric_path = RUBRICS_DIR / f"{rubric_id}.yaml"
    if not rubric_path.exists():
        return None
    rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    return rubric if isinstance(rubric, dict) else None


def _load_admin_sources() -> list[dict[str, Any]]:
    sources = json.loads(SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    return sources if isinstance(sources, list) else []


def _build_admin_rag_knowledge_item(request: AdminRagKnowledgeItemRequest) -> dict[str, Any]:
    item = request.model_dump()
    item["scope"] = item["scope"].strip()
    item["case_id"] = item["case_id"].strip()
    item["content_kind"] = item["content_kind"].strip()
    item["visibility"] = item["visibility"].strip()
    item["source_id"] = item["source_id"].strip()
    item["title"] = item["title"].strip()
    item["text"] = item["text"].strip()
    item["allowed_agents"] = [str(agent).strip() for agent in item["allowed_agents"] if str(agent).strip()]
    item["tags"] = [str(tag).strip() for tag in item["tags"] if str(tag).strip()]
    knowledge_id = str(item.get("knowledge_id", "")).strip()
    if not knowledge_id:
        knowledge_id = _generate_admin_rag_knowledge_id(item)
    item["knowledge_id"] = knowledge_id
    _validate_admin_rag_knowledge_item(item)
    return item


def _generate_admin_rag_knowledge_id(item: dict[str, Any]) -> str:
    case_part = item["case_id"] if item["case_id"] else "global"
    digest = hashlib.sha1(
        f"{item['scope']}|{case_part}|{item['content_kind']}|{item['title']}|{item['text']}".encode("utf-8")
    ).hexdigest()[:12]
    return f"kb:{item['scope']}:{case_part}:{item['content_kind']}:{digest}"


def _validate_admin_rag_knowledge_item(item: dict[str, Any]) -> None:
    if item["scope"] not in RAG_KNOWLEDGE_SCOPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported knowledge scope")
    if item["visibility"] not in RAG_KNOWLEDGE_VISIBILITIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported knowledge visibility")
    if not item["content_kind"] or not item["title"] or not item["text"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="knowledge content requires kind, title and text",
        )
    unknown_agent_roles = sorted(set(item["allowed_agents"]) - RAG_KNOWLEDGE_AGENT_ROLES)
    if unknown_agent_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported knowledge agent role")
    if item["scope"] == "case" and not _admin_case_exists(item["case_id"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="case knowledge requires a valid case_id")
    if item["case_id"] and not _admin_case_exists(item["case_id"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="case_id is not registered")
    if item["source_id"] and item["source_id"] not in _admin_source_ids():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source_id is not registered")
    if item["visibility"] == "secret_scoring_only" and set(item["allowed_agents"]) & RAG_GENERATIVE_AGENT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="secret scoring knowledge cannot be exposed to generative agents",
        )


def _build_admin_rag_document_items(request: AdminRagDocumentUploadRequest) -> tuple[str, list[dict[str, Any]]]:
    case_id = request.case_id.strip()
    scope = request.scope.strip() or ("case" if case_id else "global")
    file_name = request.file_name.strip()
    visibility = request.visibility.strip()
    source_id = request.source_id.strip()
    allowed_agents = [str(agent).strip() for agent in request.allowed_agents if str(agent).strip()]
    tags = [str(tag).strip() for tag in request.tags if str(tag).strip()]
    if scope not in {"global", "case"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported document scope")
    if scope == "case" and not _admin_case_exists(case_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="case document requires a valid case_id")
    if scope == "global":
        case_id = ""
    if not file_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="document file_name is required")
    if visibility not in RAG_KNOWLEDGE_VISIBILITIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported knowledge visibility")
    unknown_agent_roles = sorted(set(allowed_agents) - RAG_KNOWLEDGE_AGENT_ROLES)
    if unknown_agent_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported knowledge agent role")
    if source_id and source_id not in _admin_source_ids():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source_id is not registered")
    if visibility == "secret_scoring_only" and set(allowed_agents) & RAG_GENERATIVE_AGENT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="secret scoring knowledge cannot be exposed to generative agents",
        )
    try:
        content_bytes = base64.b64decode(request.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="document content_base64 is invalid") from exc
    if not content_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="document content is empty")
    if len(content_bytes) > RAG_DOCUMENT_MAX_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="document is too large")

    document_id = generate_rag_document_id(case_id=case_id or "global", file_name=file_name, content_bytes=content_bytes)
    try:
        chunks = chunk_rag_document(file_name=file_name, content_bytes=content_bytes, document_id=document_id)
    except RagDocumentParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    file_stem = Path(file_name).stem if file_name else "知识文档"
    suffix_tag = Path(file_name).suffix.lower().lstrip(".")
    document_tags = ["document_upload", *([suffix_tag] if suffix_tag else []), *tags]
    chunk_count = len(chunks)
    return document_id, [
        {
            "knowledge_id": f"{document_id}:chunk:{chunk.chunk_index:04d}",
            "scope": scope,
            "case_id": case_id,
            "content_kind": "document_chunk",
            "visibility": visibility,
            "allowed_agents": allowed_agents,
            "source_id": source_id,
            "title": f"{file_stem} · {chunk.section_title or f'片段 {chunk.chunk_index + 1}'}",
            "text": chunk.text,
            "tags": document_tags,
            "version": 1,
            "document_id": document_id,
            "document_name": Path(file_name).name,
            "chunk_index": chunk.chunk_index,
            "chunk_count": chunk_count,
            "section_title": chunk.section_title,
            "page_number": chunk.page_number,
            "source_location": chunk.source_location,
            "chunking_strategy": chunk.chunking_strategy,
            "chunk_categories": chunk.chunk_categories,
            "quality_warnings": chunk.quality_warnings,
            "risk_flags": chunk.risk_flags,
            "char_count": chunk.char_count,
            "enabled": request.enabled,
        }
        for chunk in chunks
    ]


def _clear_retrieval_documents_cache() -> None:
    retrieval_documents = getattr(retrieval_index, "_retrieval_documents", None)
    cache_clear = getattr(retrieval_documents, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


def _admin_case_exists(case_id: str) -> bool:
    if not case_id or "/" in case_id or "\\" in case_id or ".." in case_id:
        return False
    return (CASES_DIR / f"{case_id}.json").exists()


def _admin_source_ids() -> set[str]:
    return {
        str(source.get("source_id", "")).strip()
        for source in _load_admin_sources()
        if str(source.get("source_id", "")).strip()
    }


def _get_enabled_skill_summaries(user_id: str) -> list[dict[str, object]]:
    return [
        _serialize_enabled_skill_for_profile(skill)
        for skill in osce_session_service.training_skill_store.list_enabled_skills()
        if _enabled_skill_visible_to_user(skill, user_id)
    ]


def _serialize_enabled_skill_for_profile(skill: dict[str, Any]) -> dict[str, object]:
    support_count = int(skill.get("support_count") or 0)
    source_report_count = int(skill.get("source_report_count") or 0)
    effect_status = str(skill.get("effect_status", "insufficient_samples"))

    return {
        "skill_id": str(skill["skill_id"]),
        "title": str(skill["title"]),
        "student_visible_summary": str(skill["student_visible_summary"]),
        "description": str(skill["description"]),
        "learning_action": str(skill["learning_action"]),
        "activation_summary": str(skill["activation_summary"]),
        "source_summary": str(skill["source_summary"]),
        "effect_status_label": str(skill["effect_status_label"]),
        "scope_label": str(skill["scope_label"]),
        "support_count": support_count,
        "source_report_count": source_report_count,
        "effect_status": effect_status,
    }


def _enabled_skill_visible_to_user(skill: dict[str, Any], user_id: str) -> bool:
    if str(skill.get("scope", "global")) != "personal":
        return True
    return str(skill.get("owner_student_id", "")) == user_id


def _get_applied_skill_count(user_id: str, sessions: list[dict[str, object]]) -> int:
    return sum(
        1
        for session in sessions
        for event in osce_session_service.training_event_store.list_session_events(str(session["session_id"]))
        if event["student_id"] == user_id and event["event_type"] == "training_skill_applied"
    )


def _build_skill_accumulation(user_id: str, sessions: list[dict[str, object]]) -> dict[str, object]:
    enabled_skills = _get_enabled_skill_summaries(user_id)
    enabled_skill_count = len(enabled_skills)
    applied_skill_count = _get_applied_skill_count(user_id, sessions)

    if enabled_skill_count == 0:
        return {
            "status": "planned",
            "description": "Step 8 接入已审核教学 Skill、错误模式和个性化提示策略。",
            "enabled_skill_count": 0,
            "applied_skill_count": applied_skill_count,
            "enabled_skills": [],
        }

    return {
        "status": "active",
        "description": f"已启用 {enabled_skill_count} 条教学 Skill，并在当前账号训练中应用 {applied_skill_count} 次。",
        "enabled_skill_count": enabled_skill_count,
        "applied_skill_count": applied_skill_count,
        "enabled_skills": enabled_skills,
    }


PROFILE_RECENT_SESSION_FIELDS = [
    "session_id",
    "case_id",
    "case_title",
    "stage",
    "stage_label",
    "created_at",
    "updated_at",
    "is_completed",
    "can_continue",
    "has_report",
    "completion_status",
    "training_difficulty",
]


def _serialize_profile_recent_session(session: dict[str, object]) -> dict[str, object]:
    enriched_session = enrich_session_summary(dict(session))
    return {
        field: enriched_session[field]
        for field in PROFILE_RECENT_SESSION_FIELDS
        if field in enriched_session
    }


def _build_learning_profile(user: dict[str, str]) -> dict[str, object]:
    sessions = osce_session_service.session_store.list_user_session_summaries(user["user_id"])
    reports = [
        report
        for session in sessions
        if (report := osce_session_service.report_store.get_report(str(session["session_id"]))) is not None
    ]
    visible_enabled_skills = [
        skill
        for skill in osce_session_service.training_skill_store.list_enabled_skills()
        if _enabled_skill_visible_to_user(skill, user["user_id"])
    ]
    dimension_averages = _get_dimension_averages(reports)
    weakest_dimension = dimension_averages[-1] if dimension_averages else None

    return {
        "student_id": user["user_id"],
        "total_sessions": len(sessions),
        "report_count": len(reports),
        "average_score": _get_average_score(reports),
        "dimension_averages": dimension_averages,
        "strongest_dimension": dimension_averages[0] if dimension_averages else None,
        "weakest_dimension": weakest_dimension,
        "next_focus": f"下一轮优先补强{weakest_dimension['label']}，并在训练记录中对比改进趋势。" if weakest_dimension else "先完成一次完整训练并生成评分报告。",
        "learning_path": _build_learning_path(reports, weakest_dimension),
        "recent_sessions": [_serialize_profile_recent_session(dict(session)) for session in sessions[:5]],
        "skill_accumulation": _build_skill_accumulation(user["user_id"], sessions),
        "skill_profile_summary": osce_session_service.build_student_profile_summary(user["user_id"]),
    }


@app.post("/api/auth/register")
def register(request: AuthRegisterRequest, response: Response) -> dict[str, object]:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=FIXED_ACCOUNT_REGISTRATION_DISABLED_MESSAGE,
    )


@app.post("/api/auth/login")
def login(request: AuthLoginRequest, response: Response) -> dict[str, object]:
    _validate_auth_request(request.email, request.password)
    user = _authenticate_fixed_demo_user(request.email, request.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    _set_auth_cookie(response, auth_store.create_session(user["user_id"]))
    return {"user": _build_auth_user_payload(user)}


@app.post("/api/auth/logout")
def logout(response: Response, auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME)) -> dict[str, str]:
    if auth_token:
        auth_store.revoke_session(auth_token)
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path=AUTH_COOKIE_PATH,
        secure=is_production_deployment_mode(),
        httponly=True,
        samesite="lax",
    )
    response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    return {"status": "ok"}


@app.get("/api/auth/me")
def get_current_user(auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME)) -> dict[str, object]:
    return {"user": _build_auth_user_payload(_require_current_user(auth_token))}


@app.get("/")
def read_root() -> dict[str, str]:
    return {
        "name": "clinical-osce-agent",
        "message": "OSCE backend scaffold is running.",
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health")
def public_api_health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/config")
def startup_config_health_check(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return build_startup_config_self_check()


@app.post("/api/audio/transcriptions")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str | None = Form(default=None, max_length=16),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_current_user(auth_token)
    try:
        audio_bytes = await _read_upload_file_with_limit(
            file,
            max_bytes=AUDIO_TRANSCRIPTION_MAX_BYTES,
        )
        result = await build_dashscope_speech_service_from_environment().transcribe(
            audio_bytes,
            mime_type=file.content_type,
            filename=file.filename,
            language=language,
        )
    except SpeechServiceConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DashScopeSpeechServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    finally:
        await file.close()
    return {
        "text": result.text,
        "provider": result.provider,
        "model": result.model,
        "language": result.language,
        "emotion": result.emotion,
        "duration_seconds": result.duration_seconds,
    }


@app.post("/api/audio/speech")
async def synthesize_audio(
    request: AudioSpeechRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> StreamingResponse:
    _require_current_user(auth_token)
    speech_text = request.input
    voice = request.voice
    model = request.model
    instructions: str | None = None
    optimize_instructions: bool | None = None
    speech_profile: PatientSpeechProfile | None = None
    cache_key: str | None = None
    cache_status = "bypass"
    if request.session_id or request.message_index is not None:
        speech_text, speech_profile = _resolve_patient_speech_request(request, auth_token)
        voice = speech_profile.voice
        model = speech_profile.model
        instructions = speech_profile.instructions
        optimize_instructions = speech_profile.optimize_instructions
        cache_key = speech_synthesis_cache.build_key(
            session_id=str(request.session_id or ""),
            message_index=int(request.message_index if request.message_index is not None else -1),
            text=speech_text,
            model=model,
            voice=voice,
            instructions=instructions,
            optimize_instructions=optimize_instructions,
            emotion=speech_profile.normalized_emotion,
        )
        cached_result = speech_synthesis_cache.get(cache_key)
        if cached_result is not None:
            return _build_speech_streaming_response(
                cached_result,
                speech_profile=speech_profile,
                cache_status="hit",
            )
        cache_status = "miss"

    try:
        result = await build_dashscope_speech_service_from_environment().synthesize(
            speech_text,
            voice=voice,
            model=model,
            instructions=instructions,
            optimize_instructions=optimize_instructions,
        )
    except SpeechServiceConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DashScopeSpeechServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if cache_key is not None:
        speech_synthesis_cache.set(cache_key, result)
    return _build_speech_streaming_response(
        result,
        speech_profile=speech_profile,
        cache_status=cache_status,
    )


@app.post(
    "/api/model-config/test",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def test_model_config(
    request: StudentModelConfigTestRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    if not is_runtime_model_config_write_supported():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="runtime model config is disabled in production deployment mode",
        )
    user = _require_current_user(auth_token)
    config_request = _build_user_runtime_model_config_request(user["user_id"], request)
    try:
        return test_student_model_config_connectivity(config_request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/model-config/runtime")
def apply_model_config_runtime(
    request: StudentModelConfigTestRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    if not is_runtime_model_config_write_supported():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="runtime model config is disabled in production deployment mode",
        )
    user = _require_current_user(auth_token)
    try:
        config_request = _build_user_runtime_model_config_request(user["user_id"], request)
        runtime_config = runtime_model_config_store.build_config(config_request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    user_model_config_store.save_runtime_config(user["user_id"], runtime_config)
    payload = runtime_config.public_payload()
    payload["api_key_saved"] = bool(runtime_config.api_key)
    return payload


@app.get("/api/model-config/runtime")
def get_model_config_runtime(auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME)) -> dict[str, object]:
    user = _require_current_user(auth_token)
    payload = _runtime_model_config_public_payload_for_user(user["user_id"])
    payload["runtime_write_supported"] = is_runtime_model_config_write_supported()
    payload["deployment_mode"] = get_deployment_mode()
    return payload


@app.get("/api/cases")
def list_cases() -> dict[str, object]:
    return {"cases": osce_session_service.list_cases()}


@app.get("/api/procedure-catalog")
def get_procedure_catalog(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_current_user(auth_token)
    return osce_session_service.get_procedure_catalog()


def _get_case_detail_response(case_id: str) -> dict[str, object]:
    case_payload = osce_session_service.get_case_detail(case_id)
    if case_payload is None:
        raise HTTPException(status_code=404, detail="case not found")
    return {"case": case_payload}


def _get_case_raw_response(case_id: str) -> dict[str, object]:
    case_payload = osce_session_service.get_case_raw(case_id)
    if case_payload is None:
        raise HTTPException(status_code=404, detail="case not found")
    return {"case": case_payload}


def _build_admin_case_validation_response(request: AdminCaseValidationRequest) -> dict[str, object]:
    errors: list[str] = []
    case_id = request.case.get("case_id")
    rubric_id = request.rubric.get("rubric_id") if request.rubric is not None else None
    case_model = None
    rubric_model = None

    try:
        case_model = validate_case(request.case)
    except Exception as exc:
        errors.append(str(exc))

    if request.rubric is not None:
        try:
            rubric_model = validate_rubric(request.rubric)
        except Exception as exc:
            errors.append(str(exc))

    if case_model is not None and rubric_model is not None:
        try:
            validate_case_rubric_pair(case_model, rubric_model)
        except Exception as exc:
            errors.append(str(exc))

    return {"valid": not errors, "case_id": case_id, "rubric_id": rubric_id, "errors": errors}


def _is_safe_admin_import_id(value: object) -> bool:
    return isinstance(value, str) and bool(value) and "/" not in value and "\\" not in value and ".." not in value


def _build_admin_case_import_response(request: AdminCaseImportRequest) -> dict[str, object]:
    case_id = request.case.get("case_id")
    rubric_id = request.rubric.get("rubric_id")
    errors: list[str] = []

    if not _is_safe_admin_import_id(case_id):
        errors.append(f"invalid case_id: {case_id}")
    if not _is_safe_admin_import_id(rubric_id):
        errors.append(f"invalid rubric_id: {rubric_id}")
    if errors:
        return {"imported": False, "case_id": case_id, "rubric_id": rubric_id, "errors": errors}

    validation = _build_admin_case_validation_response(
        AdminCaseValidationRequest(case=request.case, rubric=request.rubric)
    )
    errors.extend(str(error) for error in validation["errors"])
    if errors:
        return {"imported": False, "case_id": case_id, "rubric_id": rubric_id, "errors": errors}

    case_path = CASES_DIR / f"{case_id}.json"
    rubric_path = RUBRICS_DIR / f"{rubric_id}.yaml"
    if case_path.exists():
        errors.append(f"case already exists: {case_id}")
    if rubric_path.exists():
        errors.append(f"rubric already exists: {rubric_id}")
    if errors:
        return {"imported": False, "case_id": case_id, "rubric_id": rubric_id, "errors": errors}

    case_content = json.dumps(request.case, ensure_ascii=False, indent=2) + "\n"
    rubric_content = yaml.safe_dump(request.rubric, allow_unicode=True, sort_keys=False)
    created_paths = []
    try:
        with case_path.open("x", encoding="utf-8") as case_file:
            case_file.write(case_content)
        created_paths.append(case_path)
        with rubric_path.open("x", encoding="utf-8") as rubric_file:
            rubric_file.write(rubric_content)
        created_paths.append(rubric_path)
    except FileExistsError:
        for created_path in reversed(created_paths):
            created_path.unlink(missing_ok=True)
        conflict_error = f"rubric already exists: {rubric_id}" if created_paths else f"case already exists: {case_id}"
        return {"imported": False, "case_id": case_id, "rubric_id": rubric_id, "errors": [conflict_error]}
    except OSError as exc:
        for created_path in reversed(created_paths):
            created_path.unlink(missing_ok=True)
        return {
            "imported": False,
            "case_id": case_id,
            "rubric_id": rubric_id,
            "errors": [f"import write failed: {exc}"],
        }
    _clear_admin_case_asset_caches()
    return {"imported": True, "case_id": case_id, "rubric_id": rubric_id, "errors": []}


def _clear_admin_case_asset_caches() -> None:
    retrieval_index._retrieval_documents.cache_clear()
    source_retriever._case_payload.cache_clear()
    source_retriever._rubric_items.cache_clear()


def _build_admin_case_update_response(case_id: str, request: AdminCaseFieldUpdateRequest) -> dict[str, object]:
    if not _is_safe_admin_import_id(case_id):
        raise HTTPException(status_code=404, detail="case not found")

    case_path = CASES_DIR / f"{case_id}.json"
    if not case_path.exists():
        raise HTTPException(status_code=404, detail="case not found")

    case_payload = json.loads(case_path.read_text(encoding="utf-8"))
    if not isinstance(case_payload, dict):
        return {"updated": False, "case_id": case_id, "rubric_id": None, "errors": ["case payload is not an object"]}
    if case_payload.get("case_id") != case_id:
        return {
            "updated": False,
            "case_id": case_id,
            "rubric_id": case_payload.get("rubric_ref", {}).get("rubric_id") if isinstance(case_payload.get("rubric_ref"), dict) else None,
            "errors": [f"case_id mismatch: {case_payload.get('case_id')}"],
        }

    updates = request.model_dump(exclude_none=True)
    if not updates:
        return {
            "updated": False,
            "case_id": case_id,
            "rubric_id": case_payload.get("rubric_ref", {}).get("rubric_id") if isinstance(case_payload.get("rubric_ref"), dict) else None,
            "errors": ["no editable case fields provided"],
            "case": case_payload,
        }

    next_case = {**case_payload, **updates}
    rubric_id = next_case.get("rubric_ref", {}).get("rubric_id") if isinstance(next_case.get("rubric_ref"), dict) else None
    errors: list[str] = []
    case_model = None
    rubric_model = None
    try:
        case_model = validate_case(next_case)
    except Exception as exc:
        errors.append(str(exc))

    if isinstance(rubric_id, str) and rubric_id:
        rubric_payload = _load_admin_rubric(rubric_id)
        if rubric_payload is None:
            errors.append(f"rubric not found: {rubric_id}")
        else:
            try:
                rubric_model = validate_rubric(rubric_payload)
            except Exception as exc:
                errors.append(str(exc))
    else:
        errors.append("rubric_id is required")

    if case_model is not None and rubric_model is not None:
        try:
            validate_case_rubric_pair(case_model, rubric_model)
        except Exception as exc:
            errors.append(str(exc))

    if errors:
        return {"updated": False, "case_id": case_id, "rubric_id": rubric_id, "errors": errors, "case": case_payload}

    case_path.write_text(json.dumps(next_case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _clear_admin_case_asset_caches()
    return {"updated": True, "case_id": case_id, "rubric_id": rubric_id, "errors": [], "case": next_case}


def _build_admin_rubric_item_update_response(
    rubric_id: str,
    item_id: str,
    request: AdminRubricItemUpdateRequest,
) -> dict[str, object]:
    if not _is_safe_admin_import_id(rubric_id):
        raise HTTPException(status_code=404, detail="rubric not found")
    if not _is_safe_admin_import_id(item_id):
        raise HTTPException(status_code=404, detail="rubric item not found")

    rubric_path = RUBRICS_DIR / f"{rubric_id}.yaml"
    if not rubric_path.exists():
        raise HTTPException(status_code=404, detail="rubric not found")

    rubric_payload = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    if not isinstance(rubric_payload, dict):
        return {"updated": False, "rubric_id": rubric_id, "case_id": None, "item_id": item_id, "errors": ["rubric payload is not an object"]}

    next_rubric = deepcopy(rubric_payload)
    item_found = False
    for dimension in next_rubric.get("dimensions", []):
        if not isinstance(dimension, dict):
            continue
        for item in dimension.get("items", []):
            if isinstance(item, dict) and item.get("item_id") == item_id:
                item["description"] = request.description
                item_found = True
                break
        if item_found:
            break

    if not item_found:
        raise HTTPException(status_code=404, detail="rubric item not found")

    case_id = next_rubric.get("case_id")
    errors: list[str] = []
    rubric_model = None
    case_model = None
    try:
        rubric_model = validate_rubric(next_rubric)
    except Exception as exc:
        errors.append(str(exc))

    if isinstance(case_id, str) and case_id:
        case_path = CASES_DIR / f"{case_id}.json"
        if not case_path.exists():
            errors.append(f"case not found: {case_id}")
        else:
            try:
                case_payload = json.loads(case_path.read_text(encoding="utf-8"))
                case_model = validate_case(case_payload)
            except Exception as exc:
                errors.append(str(exc))
    else:
        errors.append("case_id is required")

    if case_model is not None and rubric_model is not None:
        try:
            validate_case_rubric_pair(case_model, rubric_model)
        except Exception as exc:
            errors.append(str(exc))

    if errors:
        return {"updated": False, "rubric_id": rubric_id, "case_id": case_id, "item_id": item_id, "errors": errors, "rubric": rubric_payload}

    rubric_path.write_text(yaml.safe_dump(next_rubric, allow_unicode=True, sort_keys=False), encoding="utf-8")
    _clear_admin_case_asset_caches()
    return {"updated": True, "rubric_id": rubric_id, "case_id": case_id, "item_id": item_id, "errors": [], "rubric": next_rubric}


@app.get("/api/cases/{case_id}")
def get_case_detail(case_id: str) -> dict[str, object]:
    return _get_case_detail_response(case_id)


@app.get("/api/cases/{case_id}/raw")
def get_case_raw(
    case_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return _get_case_raw_response(case_id)


@app.get("/api/admin/cases/{case_id}/raw")
def get_admin_case_raw(
    case_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return _get_case_raw_response(case_id)


@app.patch("/api/admin/cases/{case_id}/raw")
def update_admin_case_fields(
    case_id: str,
    request: AdminCaseFieldUpdateRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return _build_admin_case_update_response(case_id, request)


@app.post("/api/admin/cases/validate")
def validate_admin_case(
    request: AdminCaseValidationRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return _build_admin_case_validation_response(request)


@app.post("/api/admin/cases/import")
def import_admin_case(
    request: AdminCaseImportRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return _build_admin_case_import_response(request)


@app.get("/api/admin/rubrics/{rubric_id}")
def get_admin_rubric(
    rubric_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    rubric = _load_admin_rubric(rubric_id)
    if rubric is None:
        raise HTTPException(status_code=404, detail="rubric not found")
    return {"rubric": rubric}


@app.patch("/api/admin/rubrics/{rubric_id}/items/{item_id}")
def update_admin_rubric_item(
    rubric_id: str,
    item_id: str,
    request: AdminRubricItemUpdateRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return _build_admin_rubric_item_update_response(rubric_id, item_id, request)


@app.get("/api/admin/sources")
def list_admin_sources(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return {"sources": _load_admin_sources()}


@app.get("/api/admin/teaching-focus/patterns")
def list_admin_teaching_focus_patterns(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return {"patterns": [enrich_teaching_focus_pattern(pattern) for pattern in build_admin_teaching_focus_patterns()]}


@app.get("/api/admin/teaching-focus/patterns/{focus_id}")
def get_admin_teaching_focus_pattern_detail(
    focus_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    pattern = get_admin_teaching_focus_pattern(focus_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="teaching focus pattern not found")
    return {"pattern": enrich_teaching_focus_pattern(pattern)}


@app.get("/api/admin/model-config")
def get_admin_model_config(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return build_admin_model_config()


@app.get("/api/admin/model-api-logs")
def get_admin_model_api_logs(
    limit: int = Query(default=80, ge=1, le=200),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return api_call_log_store.build_admin_payload(limit=limit)


@app.get(
    "/api/admin/retrieval-eval",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def get_admin_retrieval_eval(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return {"retrieval_eval": run_retrieval_eval()}


@app.get("/api/admin/rag/knowledge")
def list_admin_rag_knowledge_items(
    scope: str = Query(default=""),
    case_id: str = Query(default=""),
    visibility: str = Query(default=""),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return {
        "knowledge_items": [
            enrich_rag_knowledge_item(item)
            for item in rag_knowledge_store.list_items(
                scope=scope.strip(),
                case_id=case_id.strip(),
                visibility=visibility.strip(),
            )
        ]
    }


@app.get("/api/admin/rag/documents")
def list_admin_rag_documents(
    case_id: str = Query(default=""),
    scope: str = Query(default=""),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    normalized_scope = scope.strip()
    if normalized_scope and normalized_scope not in {"global", "case"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported document scope")
    return {
        "documents": [
            enrich_rag_document(document)
            for document in rag_knowledge_store.list_documents(scope=normalized_scope, case_id=case_id.strip())
        ]
    }


@app.post("/api/admin/rag/documents")
def upload_admin_rag_document(
    request: AdminRagDocumentUploadRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    reviewer = _require_admin_user(auth_token)
    document_id, items = _build_admin_rag_document_items(request)
    rag_knowledge_store.delete_document(document_id)
    saved_items = [
        rag_knowledge_store.upsert_item(item, updated_by=reviewer["email"])
        for item in items
    ]
    _clear_retrieval_documents_cache()
    documents = rag_knowledge_store.list_documents(case_id=request.case_id.strip())
    document = next((item for item in documents if item["document_id"] == document_id), None)
    if document is None:
        raise HTTPException(status_code=500, detail="rag document was not persisted")
    return {
        "document": enrich_rag_document(document),
        "knowledge_items": [enrich_rag_knowledge_item(item) for item in saved_items],
    }


@app.patch("/api/admin/rag/documents/{document_id:path}/enabled")
def set_admin_rag_document_enabled(
    document_id: str,
    request: AdminRagDocumentEnabledRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    reviewer = _require_admin_user(auth_token)
    document = rag_knowledge_store.set_document_enabled(
        document_id,
        enabled=request.enabled,
        updated_by=reviewer["email"],
    )
    if document is None:
        raise HTTPException(status_code=404, detail="rag document not found")
    _clear_retrieval_documents_cache()
    return {"document": enrich_rag_document(document)}


@app.post("/api/admin/rag/knowledge")
def upsert_admin_rag_knowledge_item(
    request: AdminRagKnowledgeItemRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    reviewer = _require_admin_user(auth_token)
    item = _build_admin_rag_knowledge_item(request)
    saved_item = rag_knowledge_store.upsert_item(item, updated_by=reviewer["email"])
    _clear_retrieval_documents_cache()
    return {"knowledge_item": enrich_rag_knowledge_item(saved_item)}


@app.get("/api/admin/rag/knowledge/{knowledge_id:path}")
def get_admin_rag_knowledge_item(
    knowledge_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    item = rag_knowledge_store.get_item(knowledge_id)
    if item is None:
        raise HTTPException(status_code=404, detail="knowledge item not found")
    return {"knowledge_item": enrich_rag_knowledge_item(item)}


@app.delete("/api/admin/rag/knowledge/{knowledge_id:path}")
def delete_admin_rag_knowledge_item(
    knowledge_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    deleted = rag_knowledge_store.delete_item(knowledge_id)
    if deleted:
        _clear_retrieval_documents_cache()
    return {"knowledge_id": knowledge_id, "deleted": deleted}


@app.post(
    "/api/admin/demo/seed",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def seed_admin_demo_data(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    reviewer = _require_admin_user(auth_token)
    if not (_is_demo_admin_enabled() and _is_demo_student_enabled()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DEMO_SEED_CONFIG_ERROR_MESSAGE,
        )
    try:
        return seed_demo_data(
            auth_store=auth_store,
            osce_service=osce_session_service,
            candidate_store=training_skill_candidate_store,
            reviewer_email=reviewer["email"],
            admin_email=_get_demo_admin_email(),
            admin_password=_get_demo_admin_password(),
            student_email=_get_demo_student_email(),
            student_password=_get_demo_student_password(),
        )
    except ValueError as exc:
        if str(exc) == DEMO_SEED_CONFIG_ERROR_MESSAGE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=DEMO_SEED_CONFIG_ERROR_MESSAGE,
            ) from exc
        raise


@app.get("/api/admin/evolution/candidates")
def list_admin_training_skill_candidates(
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default=""),
    review_status: str = Query(default=""),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    candidate_items = _filter_training_skill_candidate_items_by_review_status(
        [
            enrich_training_skill_candidate(candidate_item)
            for candidate_item in training_skill_candidate_store.list_candidate_summaries()
        ],
        review_status,
    )
    return _build_paginated_admin_payload(
        "candidates",
        candidate_items,
        limit,
        offset,
        q,
    )


@app.get("/api/admin/evolution/events")
def list_admin_training_skill_review_events(
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default=""),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return _build_paginated_admin_payload(
        "events",
        _list_admin_skill_candidate_review_events(),
        limit,
        offset,
        q,
    )


@app.get("/api/admin/evolution/settings")
def get_admin_training_skill_evolution_settings(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return {"settings": training_skill_auto_approval_settings_store.get_settings()}


@app.patch("/api/admin/evolution/settings")
def update_admin_training_skill_evolution_settings(
    request: AdminTrainingSkillAutoApprovalSettingsRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    reviewer = _require_admin_user(auth_token)
    settings = training_skill_auto_approval_settings_store.update_settings(
        auto_apply_enabled=request.auto_apply_enabled,
        updated_by=reviewer["email"],
    )
    return {"settings": settings}


@app.post(
    "/api/admin/evolution/candidates/generate",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def generate_admin_training_skill_candidates(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    reviewer = _require_admin_user(auth_token)
    session_ids = _real_training_session_ids()
    insights = TrainingInsightService(osce_session_service.training_event_store).summarize_sessions(session_ids)
    candidates = training_skill_candidate_service.propose_candidates(insights, min_count=2)
    batch_result = _run_admin_evaluation_cases()
    evaluation_result_store.save_batch_result(ADMIN_SKILL_CANDIDATE_GENERATION_BATCH_ID, batch_result)
    auto_approval_settings = training_skill_auto_approval_settings_store.get_settings()
    auto_apply_enabled = bool(auto_approval_settings["auto_apply_enabled"])
    saved_candidate_summaries: list[dict[str, object]] = []
    ready_for_review_count = 0
    blocked_by_regression_count = 0
    auto_approved_count = 0
    approval_agent_modified_count = 0

    for candidate in candidates:
        if auto_apply_enabled:
            candidate = training_skill_approval_agent.review_candidate(candidate)
        review = training_skill_regression_gate.review_candidate(candidate, batch_result)
        if auto_apply_enabled:
            _set_approval_agent_decision(candidate, review)
            if review["status"] == "ready_for_review":
                review = {
                    **review,
                    "status": "approved",
                    "reviewer_id": AUTO_APPROVAL_AGENT_ID,
                    "approval_mode": "auto_agent",
                }
        if not training_skill_candidate_store.save_candidate_unless_reviewed(candidate, review):
            continue
        if auto_apply_enabled and candidate["approval_agent_review"]["revision_status"] == "modified":
            approval_agent_modified_count += 1
        if review["status"] == "ready_for_review":
            ready_for_review_count += 1
        if review["status"] == "blocked_by_regression":
            blocked_by_regression_count += 1
        saved_candidate = training_skill_candidate_store.get_candidate(str(candidate["candidate_id"]))
        if saved_candidate is not None:
            saved_candidate_summaries.append(_summarize_training_skill_candidate(saved_candidate))
        _append_admin_skill_candidate_review_event(
            candidate=candidate,
            reviewer_email=reviewer["email"],
            event_type="admin_skill_candidate_generated",
            payload={
                "candidate_id": candidate["candidate_id"],
                "review_status": review["status"],
                "support_count": candidate["support_count"],
                "source_report_count": candidate["source_report_count"],
            },
        )
        if auto_apply_enabled:
            _append_admin_skill_candidate_review_event(
                candidate=candidate,
                reviewer_email=AUTO_APPROVAL_AGENT_ID,
                event_type="admin_skill_candidate_agent_reviewed",
                payload={
                    "candidate_id": candidate["candidate_id"],
                    **candidate["approval_agent_review"],
                },
            )
        if auto_apply_enabled and review["status"] == "approved":
            if not osce_session_service.training_skill_store.enable_candidate({**candidate, "review": review}):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="candidate could not be auto enabled")
            skill_id = f"skill_{candidate['trigger_item_id']}"
            auto_approved_count += 1
            _append_admin_skill_candidate_review_event(
                candidate=candidate,
                reviewer_email=AUTO_APPROVAL_AGENT_ID,
                event_type="admin_skill_candidate_auto_approved",
                payload={
                    "candidate_id": candidate["candidate_id"],
                    "reviewer_email": AUTO_APPROVAL_AGENT_ID,
                    "skill_id": skill_id,
                    "approval_mode": "auto_agent",
                    "revision_status": candidate["approval_agent_review"]["revision_status"],
                },
            )

    return {
        "generated_count": len(candidates),
        "saved_count": len(saved_candidate_summaries),
        "ready_for_review_count": ready_for_review_count,
        "blocked_by_regression_count": blocked_by_regression_count,
        "auto_apply_enabled": auto_apply_enabled,
        "auto_approved_count": auto_approved_count,
        "approval_agent_modified_count": approval_agent_modified_count,
        "candidates": saved_candidate_summaries,
    }


@app.get("/api/admin/evolution/candidates/{candidate_id}")
def get_admin_training_skill_candidate(
    candidate_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    candidate = training_skill_candidate_store.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return {"candidate": enrich_training_skill_candidate(candidate_with_context_safety_review(candidate))}


@app.get("/api/admin/evolution/candidates/{candidate_id}/events")
def list_admin_training_skill_candidate_events(
    candidate_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return {"events": osce_session_service.training_event_store.list_session_events(candidate_id)}


@app.post("/api/admin/evolution/approve")
def approve_admin_training_skill_candidate(
    request: AdminTrainingSkillReviewRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, str]:
    reviewer = _require_admin_user(auth_token)
    if not training_skill_candidate_store.approve_candidate(request.candidate_id, reviewer["email"]):
        raise HTTPException(status_code=404, detail="candidate not found or not ready for review")
    candidate = training_skill_candidate_store.get_candidate(request.candidate_id)
    if candidate is None or not osce_session_service.training_skill_store.enable_candidate(candidate):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="candidate could not be enabled")
    skill_id = f"skill_{candidate['trigger_item_id']}"
    _append_admin_skill_candidate_review_event(
        candidate=candidate,
        reviewer_email=reviewer["email"],
        event_type="admin_skill_candidate_approved",
        payload={
            "candidate_id": request.candidate_id,
            "reviewer_email": reviewer["email"],
            "skill_id": skill_id,
        },
    )
    return {"candidate_id": request.candidate_id, "status": "approved", "skill_id": skill_id}


@app.post("/api/admin/evolution/reject")
def reject_admin_training_skill_candidate(
    request: AdminTrainingSkillReviewRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, str]:
    reviewer = _require_admin_user(auth_token)
    if not training_skill_candidate_store.reject_candidate(request.candidate_id, reviewer["email"]):
        raise HTTPException(status_code=404, detail="candidate not found or not ready for review")
    candidate = training_skill_candidate_store.get_candidate(request.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="candidate could not be audited")
    _append_admin_skill_candidate_review_event(
        candidate=candidate,
        reviewer_email=reviewer["email"],
        event_type="admin_skill_candidate_rejected",
        payload={
            "candidate_id": request.candidate_id,
            "reviewer_email": reviewer["email"],
        },
    )
    return {"candidate_id": request.candidate_id, "status": "rejected"}


@app.get("/api/admin/insights")
def get_admin_training_insights(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    session_ids = _real_training_session_ids()
    insights = TrainingInsightService(osce_session_service.training_event_store).summarize_sessions(session_ids)
    return {"insights": insights}


@app.get("/api/admin/learning-analytics")
def get_admin_learning_analytics(
    case_id: str = Query(default=""),
    student_id: str = Query(default=""),
    limit: int | None = Query(default=None, ge=1),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    session_ids = _real_training_session_ids()
    analytics = AdminLearningAnalyticsService(
        session_store=osce_session_service.session_store,
        report_store=osce_session_service.report_store,
    ).summarize(
        session_ids=session_ids,
        case_id=case_id,
        student_id=student_id,
        limit=limit,
    )
    return {"learning_analytics": analytics}


@app.get("/api/admin/evolution/skill-effects")
def get_admin_training_skill_effects(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    session_ids = _real_training_session_ids()
    skill_effects = TrainingSkillEffectService(osce_session_service.training_event_store).summarize_sessions(session_ids)
    return {"skill_effects": skill_effects}


@app.get("/api/admin/evaluations")
def list_admin_evaluations(
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default=""),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return _build_paginated_admin_payload(
        "evaluations",
        evaluation_result_store.list_batch_summaries(),
        limit,
        offset,
        q,
    )


@app.post(
    "/api/admin/evals/run",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def run_admin_evaluation(
    request: AdminEvaluationRunRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    batch_result = _run_admin_evaluation_cases()
    evaluation_result_store.save_batch_result(request.batch_id, batch_result)
    return {"evaluation": evaluation_result_store.get_batch_result(request.batch_id)}


@app.get("/api/admin/evaluations/{batch_id}")
def get_admin_evaluation(
    batch_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    evaluation = evaluation_result_store.get_batch_result(batch_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="evaluation batch not found")
    return {"evaluation": evaluation}


@app.get("/api/admin/reports")
def list_admin_reports(
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default=""),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return _build_paginated_admin_payload(
        "reports",
        [
            enrich_report(report)
            for report in osce_session_service.report_store.list_reports()
            if not _is_deleted_admin_session(report.get("session_id"))
        ],
        limit,
        offset,
        q,
    )


@app.get("/api/admin/sessions")
def list_admin_sessions(
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default=""),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return _build_paginated_admin_payload(
        "sessions",
        [
            enrich_session_summary(session)
            for session in osce_session_service.session_store.list_session_summaries()
            if not _is_deleted_admin_session(session.get("session_id"))
        ],
        limit,
        offset,
        q,
    )


@app.get("/api/admin/procedure-simulation-audits")
def list_admin_procedure_simulation_audits(
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default=""),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    filtered_items = _filter_admin_items(_build_admin_procedure_simulation_audit_items(), q)
    effective_limit = limit if limit is not None else max(len(filtered_items) - offset, 0)
    return {
        "procedure_simulation_audits": filtered_items[offset : offset + effective_limit],
        "summary": _build_admin_procedure_simulation_summary(filtered_items),
        "pagination": {"limit": effective_limit, "offset": offset, "total": len(filtered_items)},
    }


@app.get("/api/admin/sessions/{session_id}/report")
def get_admin_session_report(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    if _is_deleted_admin_session(session_id):
        raise HTTPException(status_code=404, detail="report not found")
    report = osce_session_service.report_store.get_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return {"report": enrich_report(report)}


@app.get("/api/admin/sessions/{session_id}/events")
def list_admin_session_events(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    if _is_deleted_admin_session(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return {"events": osce_session_service.training_event_store.list_session_events(session_id)}


@app.get("/api/me/sessions")
def list_current_user_sessions(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    user = _require_current_user(auth_token)
    return {"sessions": osce_session_service.session_store.list_user_session_summaries(user["user_id"])}


@app.get("/api/me/profile")
def get_current_user_profile(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    user = _require_current_user(auth_token)
    return {"profile": _build_learning_profile(user)}


@app.get("/api/me/sessions/{session_id}")
def get_current_user_session(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    return _require_readable_session(session_id, auth_token)


@app.delete("/api/me/sessions/{session_id}")
def delete_current_user_session(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, str]:
    user = _require_current_user(auth_token)
    osce_session_service.delete_session(
        session_id,
        expected_student_id=user["user_id"],
    )
    return {"status": "deleted", "session_id": session_id}


@app.get("/api/me/sessions/{session_id}/report")
def get_current_user_session_report(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_readable_session(session_id, auth_token)
    report = osce_session_service.read_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return report


@app.post("/api/sessions")
def create_session(
    request: CreateSessionRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    user = _require_current_user(auth_token)
    if request.training_difficulty not in {"beginner", "intermediate", "advanced"}:
        raise HTTPException(status_code=422, detail="invalid training_difficulty")
    with _use_user_runtime_model_config(user["user_id"], require_for_training=True):
        return osce_session_service.create_session(
            case_id=request.case_id,
            student_id=user["user_id"],
            training_difficulty=request.training_difficulty,
        )


@app.get("/api/sessions/{session_id}")
def get_session(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    return _require_owned_session(session_id, auth_token)


@app.get("/api/sessions/{session_id}/processing-status")
def get_session_processing_status(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_owned_session(session_id, auth_token)
    return osce_session_service.get_message_processing_status(session_id)


@app.post(
    "/api/sessions/{session_id}/message",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def send_message(
    session_id: str,
    request: MessageRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    session_payload = _require_open_owned_session(session_id, auth_token)
    with _use_user_runtime_model_config(str(session_payload["student_id"]), require_for_training=True):
        try:
            session = osce_session_service.handle_message(session_id, request.message)
        except MODEL_PROVIDER_EXCEPTION_TYPES as exc:
            raise _model_provider_gateway_error(exc) from exc
        except (
            SessionClosedError,
            SessionPersistenceError,
            SessionResourceLimitError,
        ):
            raise
        except Exception as exc:
            raise _training_flow_runtime_error(exc) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post(
    "/api/sessions/{session_id}/physical-exam",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def request_physical_exam(
    session_id: str,
    request: PhysicalExamRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    session_payload = _require_open_owned_session(session_id, auth_token)
    with _use_user_runtime_model_config(str(session_payload["student_id"]), require_for_training=True):
        try:
            session = osce_session_service.request_physical_exam(session_id, request.exam_code)
        except MODEL_PROVIDER_EXCEPTION_TYPES as exc:
            raise _model_provider_gateway_error(exc) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post(
    "/api/sessions/{session_id}/physical-exams",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def request_physical_exams(
    session_id: str,
    request: PhysicalExamBatchRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    session_payload = _require_open_owned_session(session_id, auth_token)
    with _use_user_runtime_model_config(str(session_payload["student_id"]), require_for_training=True):
        try:
            session = osce_session_service.request_physical_exams(session_id, request.exam_codes)
        except MODEL_PROVIDER_EXCEPTION_TYPES as exc:
            raise _model_provider_gateway_error(exc) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post(
    "/api/sessions/{session_id}/auxiliary-test",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def request_auxiliary_test(
    session_id: str,
    request: AuxiliaryTestRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    session_payload = _require_open_owned_session(session_id, auth_token)
    with _use_user_runtime_model_config(str(session_payload["student_id"]), require_for_training=True):
        try:
            session = osce_session_service.request_auxiliary_test(session_id, request.test_code)
        except MODEL_PROVIDER_EXCEPTION_TYPES as exc:
            raise _model_provider_gateway_error(exc) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post(
    "/api/sessions/{session_id}/auxiliary-tests",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def request_auxiliary_tests(
    session_id: str,
    request: AuxiliaryTestBatchRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    session_payload = _require_open_owned_session(session_id, auth_token)
    with _use_user_runtime_model_config(str(session_payload["student_id"]), require_for_training=True):
        try:
            session = osce_session_service.request_auxiliary_tests(session_id, request.test_codes)
        except MODEL_PROVIDER_EXCEPTION_TYPES as exc:
            raise _model_provider_gateway_error(exc) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post(
    "/api/sessions/{session_id}/procedure-request",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def request_procedure_text(
    session_id: str,
    request: ProcedureFreeTextRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    session_payload = _require_open_owned_session(session_id, auth_token)
    if session_payload.get("training_difficulty") != "advanced":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=PROCEDURE_REQUEST_ADVANCED_ONLY_DETAIL,
        )
    with _use_user_runtime_model_config(str(session_payload["student_id"]), require_for_training=True):
        try:
            session = osce_session_service.request_procedure_text(session_id, request.request_text)
        except ProcedureRequestTrainingModeError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=PROCEDURE_REQUEST_ADVANCED_ONLY_DETAIL,
            ) from exc
        except MODEL_PROVIDER_EXCEPTION_TYPES as exc:
            raise _model_provider_gateway_error(exc) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post(
    "/api/sessions/{session_id}/hypotheses",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def record_hypothesis(
    session_id: str,
    request: HypothesisRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    session_payload = _require_open_owned_session(session_id, auth_token)
    with _use_user_runtime_model_config(str(session_payload["student_id"]), require_for_training=True):
        try:
            session = osce_session_service.record_hypothesis(session_id, request.hypothesis)
        except MODEL_PROVIDER_EXCEPTION_TYPES as exc:
            raise _model_provider_gateway_error(exc) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post(
    "/api/sessions/{session_id}/hint",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def request_hint(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    session_payload = _require_open_owned_session(session_id, auth_token)
    with _use_user_runtime_model_config(str(session_payload["student_id"]), require_for_training=True):
        try:
            session = osce_session_service.request_hint(session_id)
        except MODEL_PROVIDER_EXCEPTION_TYPES as exc:
            raise _model_provider_gateway_error(exc) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.get("/api/sessions/{session_id}/teaching-focus")
def get_session_teaching_focus(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_owned_session(session_id, auth_token)
    teaching_focus = osce_session_service.get_teaching_focus(session_id)
    if teaching_focus is None:
        raise HTTPException(status_code=404, detail="session not found")
    return teaching_focus


@app.post(
    "/api/sessions/{session_id}/submit-diagnosis",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def submit_diagnosis(
    session_id: str,
    request: SubmitDiagnosisRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    session_payload = _require_open_owned_session(session_id, auth_token)
    with _use_user_runtime_model_config(str(session_payload["student_id"]), require_for_training=True):
        try:
            session = osce_session_service.submit_diagnosis(
                session_id=session_id,
                diagnosis=request.diagnosis,
                reasoning=request.reasoning,
            )
        except MODEL_PROVIDER_EXCEPTION_TYPES as exc:
            raise _model_provider_gateway_error(exc) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.get("/api/sessions/{session_id}/report")
def get_session_report(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_readable_session(session_id, auth_token)
    report = osce_session_service.read_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return report


@app.post(
    "/api/sessions/{session_id}/report/generate",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def generate_session_report(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    session_payload = _require_owned_session(session_id, auth_token)
    if not session_payload.get("final_submission"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先提交诊断，再生成评分报告。",
        )
    with _use_user_runtime_model_config(str(session_payload["student_id"]), require_for_training=False):
        try:
            report = osce_session_service.generate_report(
                session_id,
                include_optional_agents=False,
            )
        except MODEL_PROVIDER_EXCEPTION_TYPES as exc:
            raise _model_provider_gateway_error(exc) from exc
    if report is None:
        raise HTTPException(status_code=404, detail="session not found")
    persisted_report = osce_session_service.read_report(session_id)
    if persisted_report is None:
        raise HTTPException(status_code=404, detail="session not found")
    return persisted_report


@app.post(
    "/api/sessions/{session_id}/report/enrich",
    dependencies=[
        Depends(_admit_authenticated_model_request, scope="request")
    ],
)
def enrich_session_report(
    session_id: str,
    background_tasks: BackgroundTasks,
    response: Response,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    session_payload = _require_owned_session(session_id, auth_token)
    report = osce_session_service.read_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    if _report_has_pending_optional_agent_enrichment(report):
        response.status_code = status.HTTP_202_ACCEPTED
        background_tasks.add_task(
            _enrich_report_optional_agents_for_user,
            session_id,
            str(session_payload["student_id"]),
        )
    return report
