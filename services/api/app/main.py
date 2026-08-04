import asyncio
import base64
import binascii
import csv
import hashlib
import json
import logging
import math
import os
import re
import tempfile
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from copy import deepcopy
from datetime import UTC, date, datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import Annotated, Any, Literal

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
from app.services import admin_display_resolver, retrieval_index, source_retriever
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
from app.services.admin_audit_store import admin_audit_store
from app.services.admin_asset_version_store import admin_asset_version_store
from app.services.admin_evaluation_config_store import admin_evaluation_config_store
from app.services.api_call_log_service import (
    api_call_log_store,
    normalize_api_call_session_id,
    reset_api_call_context,
    set_api_call_context,
    use_api_call_session_context,
)
from app.services.auth_store import AUTH_USER_ROLES, auth_store
from app.services.browser_origin_policy import browser_state_change_request_rejection_reason
from app.services.classroom_store import (
    ClassroomNameConflictError,
    classroom_store,
)
from app.services.derived_teaching_focus_service import (
    build_admin_teaching_focus_patterns,
    get_admin_teaching_focus_pattern,
)
from app.services.evaluation_result_store import evaluation_result_store
from app.services.evaluation_runner import (
    EvaluationBatchResult,
    EvaluationCase,
    EvaluationStep,
    EvaluationThresholds,
    run_evaluation_cases,
)
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
from app.services.dashscope_credential_service import (
    is_trusted_dashscope_endpoint,
)
from app.services.demo_seed_service import DEMO_SEED_CONFIG_ERROR_MESSAGE, seed_demo_data
from app.services.model_config_service import build_admin_model_config
from app.services.model_call_policy import (
    DEFAULT_MODEL_OVERLOAD_RETRY_AFTER_SECONDS,
    ModelProviderOverloadedError,
    ModelProviderPayloadTooLargeError,
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
from app.services.rag_knowledge_store import (
    RAG_KNOWLEDGE_REVIEW_STATUSES,
    RAG_KNOWLEDGE_STAGE_SCOPES,
    normalize_rag_stage_scope,
    rag_knowledge_store,
    unsupported_rag_stage_scopes,
)
from app.services.rag_document_ingestion_service import (
    RagDocumentParseError,
    assess_rag_text,
    chunk_rag_document,
    generate_rag_document_id,
)
from app.services.report_score_metrics import (
    NormalizedScoreMetric,
    aggregate_score_metrics,
    dimension_score_metrics,
)
from app.services.request_body_limit import (
    RequestBodyLimitMiddleware,
    build_request_body_too_large_response,
    declared_content_length,
)
from app.services.retrieval_eval_service import run_retrieval_eval
from app.services.runtime_model_config_store import (
    RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS,
    RuntimeModelConfig,
    runtime_model_config_store,
)
from app.services.session_resource_policy import SessionResourceLimitError
from app.services.openai_compatible_chat_client import OpenAICompatibleSettings
from app.services.anthropic_chat_client import AnthropicSettings
from app.services.startup_config_service import (
    TRAINING_MODEL_CONFIG_REQUIRED_ENV_NAME,
    SQLiteReadinessTarget,
    build_readiness_self_check,
    build_startup_config_self_check,
)
from app.services.speech_synthesis_cache_service import speech_synthesis_cache
from app.services.rule_evaluator import RUBRICS_DIR
from app.services.source_freshness_service import enrich_source_freshness, summarize_source_freshness
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

logger = logging.getLogger(__name__)

AUTH_COOKIE_NAME = "clinical_osce_auth"
AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
AUTH_COOKIE_PATH = "/api"
API_PRIVATE_CACHE_CONTROL = "private, no-store, max-age=0"
MODEL_PROVIDER_BUSY_DETAIL = "模型服务正忙，请稍后重试。"
MODEL_PROVIDER_PAYLOAD_TOO_LARGE_DETAIL = "模型请求内容过大，未发送到服务商。"
MODEL_PROVIDER_TIMEOUT_DETAIL = "模型服务响应超时，请稍后重试。"
SPEECH_PROVIDER_FAILURE_DETAIL = "语音服务调用失败，请稍后重试。"
MAX_MODEL_PROVIDER_RETRY_AFTER_SECONDS = 300
REPORT_MODEL_CALL_TIMEOUT_SECONDS_ENV = "OSCE_REPORT_MODEL_CALL_TIMEOUT_SECONDS"
DEFAULT_REPORT_MODEL_CALL_TIMEOUT_SECONDS = 90.0
MAX_REPORT_MODEL_CALL_TIMEOUT_SECONDS = 300.0
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
TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE = "请先在 API 配置中应用可用模型，再开始训练。"
PUBLIC_UNAUTHENTICATED_HEALTH_PATHS = frozenset({"/health", "/ready", "/api/health"})
AUDIO_PROVIDER_REQUEST_PATHS = frozenset(
    {"/api/audio/transcriptions", "/api/audio/speech"}
)
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
RAG_STAGE_SCOPE_MAX_ITEMS = len(RAG_KNOWLEDGE_STAGE_SCOPES)
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
CLASSROOM_NAME_MAX_CHARS = 80
CLASSROOM_DESCRIPTION_MAX_CHARS = 500
CLASSROOM_MEMBER_MAX_ITEMS = 500
CLASSROOM_IMPORT_MAX_CHARS = 256 * 1024
CLASSROOM_IMPORT_MAX_ROWS = 2_000
ADMIN_AUDIT_SUMMARY_MAX_CHARS = 500
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
ADMIN_DEFAULT_EVALUATION_CASE_KEY = "appendicitis_complete_flow"
ADMIN_DEFAULT_EVALUATION_SUITE_ID = "default_regression"
ADMIN_EVALUATION_SCHEDULER_POLL_SECONDS_ENV = "OSCE_ADMIN_EVALUATION_SCHEDULER_POLL_SECONDS"


def _default_admin_evaluation_case_payload() -> dict[str, Any]:
    evaluation_case = ADMIN_EVALUATION_CASES[0]
    return {
        "case_key": ADMIN_DEFAULT_EVALUATION_CASE_KEY,
        "label": "急性阑尾炎完整训练链路",
        "case_id": evaluation_case.case_id,
        "steps": [
            {"kind": step.kind, "value": step.value, "reasoning": step.reasoning}
            for step in evaluation_case.steps
        ],
        "expected_total_score": evaluation_case.expected_total_score,
        "forbidden_terms": evaluation_case.forbidden_terms,
        "enabled": True,
    }


def _default_admin_evaluation_suite_payload() -> dict[str, Any]:
    return {
        "suite_id": ADMIN_DEFAULT_EVALUATION_SUITE_ID,
        "label": "默认核心回归套件",
        "description": "验证问诊、查体、检查、诊断、报告、RAG 来源和安全边界。",
        "case_keys": [ADMIN_DEFAULT_EVALUATION_CASE_KEY],
        "thresholds": {
            "maximum_score_delta": 0,
            "minimum_batch_pass_rate": 1.0,
            "minimum_rag_explanation_coverage_ratio": 1.0,
            "minimum_rag_evidence_coverage_ratio": 1.0,
            "require_rag_source_coverage": True,
            "maximum_case_duration_ms": 0,
        },
        "enabled": True,
    }


def _ensure_admin_evaluation_config_defaults() -> None:
    admin_evaluation_config_store.ensure_defaults(
        evaluation_case=_default_admin_evaluation_case_payload(),
        suite=_default_admin_evaluation_suite_payload(),
    )


def _admin_evaluation_case_from_payload(payload: dict[str, Any]) -> EvaluationCase:
    return EvaluationCase(
        case_id=str(payload["case_id"]),
        student_id=f"{ADMIN_EVALUATION_STUDENT_ID_PREFIX}{payload['case_key']}",
        steps=[
            EvaluationStep(
                kind=str(step["kind"]),
                value=str(step["value"]),
                reasoning=str(step.get("reasoning") or ""),
            )
            for step in payload.get("steps", [])
        ],
        expected_total_score=int(payload["expected_total_score"]),
        forbidden_terms=[str(term) for term in payload.get("forbidden_terms", [])],
    )


def _admin_evaluation_thresholds_from_suite(suite: dict[str, Any]) -> EvaluationThresholds:
    thresholds = suite.get("thresholds", {})
    return EvaluationThresholds(
        maximum_score_delta=int(thresholds.get("maximum_score_delta", 0)),
        minimum_batch_pass_rate=float(thresholds.get("minimum_batch_pass_rate", 1.0)),
        minimum_rag_explanation_coverage_ratio=float(
            thresholds.get("minimum_rag_explanation_coverage_ratio", 1.0)
        ),
        minimum_rag_evidence_coverage_ratio=float(
            thresholds.get("minimum_rag_evidence_coverage_ratio", 1.0)
        ),
        require_rag_source_coverage=bool(
            thresholds.get("require_rag_source_coverage", True)
        ),
        maximum_case_duration_ms=int(
            thresholds.get("maximum_case_duration_ms", 0)
        ),
    )


def _run_admin_evaluation_suite(
    suite_id: str,
) -> tuple[EvaluationBatchResult, dict[str, Any]]:
    _ensure_admin_evaluation_config_defaults()
    suite = admin_evaluation_config_store.get_suite(suite_id)
    if suite is None or not suite.get("enabled", True):
        raise ValueError("evaluation suite not found or disabled")
    configured_cases: list[EvaluationCase] = []
    for case_key in suite.get("case_keys", []):
        evaluation_case = admin_evaluation_config_store.get_case(str(case_key))
        if evaluation_case is None or not evaluation_case.get("enabled", True):
            raise ValueError(f"evaluation case unavailable: {case_key}")
        configured_cases.append(_admin_evaluation_case_from_payload(evaluation_case))
    if not configured_cases:
        raise ValueError("evaluation suite has no enabled cases")
    return (
        run_evaluation_cases(
            configured_cases,
            _build_admin_evaluation_service(),
            _admin_evaluation_thresholds_from_suite(suite),
        ),
        suite,
    )


def _scheduled_evaluation_batch_id(suite_id: str, now: datetime) -> str:
    safe_suite_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", suite_id).strip("_")
    return f"scheduled_{safe_suite_id}_{now.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}"


def _run_due_admin_evaluation_schedule(now: datetime | None = None) -> dict[str, Any] | None:
    current_time = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    claimed_schedule = admin_evaluation_config_store.claim_due_schedule(current_time)
    if claimed_schedule is None:
        return None
    suite_id = str(claimed_schedule["suite_id"])
    batch_id = _scheduled_evaluation_batch_id(suite_id, current_time)
    try:
        batch_result, suite = _run_admin_evaluation_suite(suite_id)
        evaluation_result_store.save_batch_result(
            batch_id,
            batch_result,
            metadata={
                "suite_id": suite_id,
                "suite_label": str(suite.get("label") or suite_id),
                "thresholds": suite.get("thresholds", {}),
                "triggered_by": "schedule",
                "created_at": current_time.isoformat(),
            },
        )
        admin_evaluation_config_store.complete_schedule_run(batch_id=batch_id)
        admin_audit_store.record(
            actor_user_id="system",
            actor_email="system@local",
            action="evaluation.schedule_completed",
            resource_type="evaluation",
            resource_id=batch_id,
            summary=f"定时评测已完成：{suite.get('label') or suite_id}",
            after={"batch_id": batch_id, "passed": batch_result.passed},
            metadata={"suite_id": suite_id},
        )
        return {"batch_id": batch_id, "passed": batch_result.passed}
    except Exception as exc:
        admin_evaluation_config_store.complete_schedule_run(
            batch_id=batch_id,
            error=exc.__class__.__name__,
        )
        admin_audit_store.record(
            actor_user_id="system",
            actor_email="system@local",
            action="evaluation.schedule_failed",
            resource_type="evaluation",
            resource_id=batch_id,
            summary=f"定时评测失败：{suite_id}",
            metadata={"suite_id": suite_id, "error_type": exc.__class__.__name__},
        )
        logger.error("scheduled admin evaluation failed (%s)", exc.__class__.__name__)
        return {"batch_id": batch_id, "error": exc.__class__.__name__}


async def _admin_evaluation_scheduler_loop() -> None:
    raw_poll_seconds = os.getenv(ADMIN_EVALUATION_SCHEDULER_POLL_SECONDS_ENV, "30")
    try:
        poll_seconds = min(max(float(raw_poll_seconds), 1.0), 300.0)
    except ValueError:
        poll_seconds = 30.0
    while True:
        try:
            await asyncio.to_thread(_run_due_admin_evaluation_schedule)
        except Exception as exc:
            logger.error(
                "admin evaluation scheduler poll failed (%s)",
                exc.__class__.__name__,
            )
        await asyncio.sleep(poll_seconds)


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


def _csv_safe_cell(value: object) -> str:
    cell = str(value or "")
    return f"'{cell}" if cell.startswith(("=", "+", "-", "@")) else cell


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
    application.state.startup_persistence_ready = True
    application.state.startup_recovery_ready = True
    persistence_initialization_enabled = getattr(
        application.state,
        "persistence_initialization_enabled",
        application is app,
    )
    if persistence_initialization_enabled:
        try:
            persistence_failures = _initialize_readiness_persistence()
            application.state.startup_persistence_failures = persistence_failures
            if persistence_failures:
                application.state.startup_persistence_ready = False
                logger.error(
                    "startup persistence initialization incomplete (%s targets)",
                    len(persistence_failures),
                )
        except Exception as exc:
            application.state.startup_persistence_ready = False
            logger.error(
                "startup persistence initialization failed (%s)",
                exc.__class__.__name__,
            )
    recovery_enabled = getattr(
        application.state,
        "pending_session_deletion_recovery_enabled",
        True,
    )
    if recovery_enabled:
        try:
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
        except Exception as exc:
            # Keep the process available for liveness diagnostics, but never
            # advertise readiness after an incomplete recovery.  Raw database
            # errors are intentionally not retained in public application state.
            application.state.startup_recovery_ready = False
            logger.error(
                "startup recovery failed (%s)",
                exc.__class__.__name__,
            )
    scheduler_task: asyncio.Task[None] | None = None
    scheduler_enabled = getattr(
        application.state,
        "admin_evaluation_scheduler_enabled",
        application is app,
    )
    if scheduler_enabled and application.state.startup_persistence_ready:
        scheduler_task = asyncio.create_task(_admin_evaluation_scheduler_loop())
    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task


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


@app.exception_handler(ModelProviderPayloadTooLargeError)
async def handle_model_provider_payload_too_large_error(
    _: Request,
    __: ModelProviderPayloadTooLargeError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        content={"detail": MODEL_PROVIDER_PAYLOAD_TOO_LARGE_DETAIL},
    )


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
    user = None
    if request.url.path not in PUBLIC_UNAUTHENTICATED_HEALTH_PATHS:
        user = auth_store.get_user_by_session_token(
            request.cookies.get(AUTH_COOKIE_NAME, "")
        )
    token = set_api_call_context(
        caller=str(user.get("email", "")) if user else "",
        user_id=str(user.get("user_id", "")) if user else "",
        student_id=str(user.get("user_id", "")) if user else "",
        session_id=_api_call_session_id_from_path(request.url.path) if user else "",
    )
    try:
        return await call_next(request)
    finally:
        reset_api_call_context(token)


API_CALL_SESSION_PATH_PATTERN = re.compile(r"^/api/sessions/([^/]+)(?:/|$)")


def _api_call_session_id_from_path(path: str) -> str:
    match = API_CALL_SESSION_PATH_PATTERN.match(str(path or ""))
    if match is None:
        return ""
    return normalize_api_call_session_id(match.group(1))


@app.middleware("http")
async def admit_audio_provider_request_before_body(
    request: Request,
    call_next: Any,
) -> Response:
    if (
        request.method.upper() != "POST"
        or request.url.path not in AUDIO_PROVIDER_REQUEST_PATHS
    ):
        return await call_next(request)

    content_length = declared_content_length(request.scope)
    if (
        content_length is not None
        and content_length > API_REQUEST_BODY_MAX_BYTES
    ):
        return build_request_body_too_large_response()

    user = auth_store.get_user_by_session_token(
        request.cookies.get(AUTH_COOKIE_NAME, "")
    )
    if user is None:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "not authenticated"},
        )
    if not model_request_admission_gate.try_acquire():
        return _model_provider_busy_response()

    deadline_token = set_model_call_deadline()
    try:
        return await call_next(request)
    finally:
        reset_model_call_deadline(deadline_token)
        model_request_admission_gate.release()


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
RagStageScope = Annotated[str, Field(max_length=32)]


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


class AdminUserCreateRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=AUTH_EMAIL_MAX_CHARS)
    password: str = Field(min_length=8, max_length=AUTH_PASSWORD_MAX_CHARS)
    display_name: str = Field(min_length=1, max_length=DISPLAY_NAME_MAX_CHARS)
    role: Literal["student", "teacher", "admin"] = "student"

    @model_validator(mode="after")
    def validate_admin_created_user(self) -> "AdminUserCreateRequest":
        if "@" not in self.email or not self.display_name.strip():
            raise ValueError("valid email and display name are required")
        return self


class AdminUserUpdateRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, min_length=3, max_length=AUTH_EMAIL_MAX_CHARS)
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=DISPLAY_NAME_MAX_CHARS,
    )
    role: Literal["student", "teacher", "admin"] | None = None
    status: Literal["active", "disabled"] | None = None

    @model_validator(mode="after")
    def validate_admin_user_update(self) -> "AdminUserUpdateRequest":
        if not any(
            value is not None
            for value in (self.email, self.display_name, self.role, self.status)
        ):
            raise ValueError("at least one user field is required")
        if self.email is not None and "@" not in self.email:
            raise ValueError("valid email is required")
        if self.display_name is not None and not self.display_name.strip():
            raise ValueError("display name is required")
        return self


class AdminUserPasswordResetRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=8, max_length=AUTH_PASSWORD_MAX_CHARS)


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


class AdminClassroomUpsertRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=CLASSROOM_NAME_MAX_CHARS)
    description: str = Field(default="", max_length=CLASSROOM_DESCRIPTION_MAX_CHARS)
    member_user_ids: list[
        Annotated[str, Field(min_length=1, max_length=IDENTIFIER_MAX_CHARS)]
    ] = Field(default_factory=list, max_length=CLASSROOM_MEMBER_MAX_ITEMS)
    teacher_user_id: str = Field(default="", max_length=IDENTIFIER_MAX_CHARS)
    status: Literal["active", "archived"] = "active"

    @model_validator(mode="after")
    def validate_classroom_name(self) -> "AdminClassroomUpsertRequest":
        if not self.name.strip():
            raise ValueError("classroom name is required")
        return self


class AdminClassroomMemberTransferRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    target_classroom_id: str = Field(min_length=1, max_length=IDENTIFIER_MAX_CHARS)
    member_user_ids: list[
        Annotated[str, Field(min_length=1, max_length=IDENTIFIER_MAX_CHARS)]
    ] = Field(min_length=1, max_length=CLASSROOM_MEMBER_MAX_ITEMS)
    mode: Literal["copy", "move"] = "move"


class AdminClassroomImportRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    csv_text: str = Field(min_length=1, max_length=CLASSROOM_IMPORT_MAX_CHARS)
    mode: Literal["merge", "replace"] = "merge"


class AdminSourceUpsertRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=IDENTIFIER_MAX_CHARS)
    source_name: str = Field(min_length=1, max_length=300)
    source_url: str = Field(default="", max_length=2_000)
    license: str = Field(default="", max_length=300)
    data_type: str = Field(min_length=1, max_length=128)
    allowed_usage: list[str] = Field(default_factory=list, max_length=64)
    transformation: str = Field(default="", max_length=2_000)
    attribution_required: bool = True
    risk_note: str = Field(default="", max_length=2_000)
    source_version: str = Field(default="", max_length=500)
    last_reviewed_at: str = Field(default="", max_length=10)
    review_interval_days: int = Field(default=365, ge=1, le=3_650)
    source_status: Literal["active", "superseded", "inactive"] = "active"
    superseded_by: str = Field(default="", max_length=IDENTIFIER_MAX_CHARS)
    review_basis: str = Field(default="", max_length=2_000)
    search_aliases: list[str] = Field(default_factory=list, max_length=64)
    change_note: str = Field(default="", max_length=500)
    medical_review_note: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def validate_source_payload(self) -> "AdminSourceUpsertRequest":
        if not _is_safe_admin_import_id(self.source_id):
            raise ValueError("source_id is invalid")
        if self.last_reviewed_at:
            try:
                date.fromisoformat(self.last_reviewed_at)
            except ValueError as exc:
                raise ValueError("last_reviewed_at must use YYYY-MM-DD") from exc
        return self


class AdminSourceReviewRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    last_reviewed_at: str = Field(min_length=10, max_length=10)
    review_interval_days: int = Field(default=365, ge=1, le=3_650)
    review_basis: str = Field(min_length=1, max_length=2_000)
    source_status: Literal["active", "superseded", "inactive"] = "active"
    superseded_by: str = Field(default="", max_length=IDENTIFIER_MAX_CHARS)
    medical_review_note: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def validate_review_date(self) -> "AdminSourceReviewRequest":
        try:
            date.fromisoformat(self.last_reviewed_at)
        except ValueError as exc:
            raise ValueError("last_reviewed_at must use YYYY-MM-DD") from exc
        return self


class AdminCaseAssetReplaceRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    case: dict[str, Any]
    rubric: dict[str, Any]
    change_note: str = Field(min_length=1, max_length=500)
    review_status: Literal["unreviewed", "approved", "rejected"] = "unreviewed"
    medical_review_note: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def validate_logical_payload_size(self) -> "AdminCaseAssetReplaceRequest":
        _validate_admin_case_request_size({"case": self.case, "rubric": self.rubric})
        return self


class AdminAssetReviewRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    review_status: Literal["approved", "rejected"]
    medical_review_note: str = Field(min_length=1, max_length=2_000)


class AdminAssetRollbackRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    change_note: str = Field(default="", max_length=500)


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
    stage_scope: list[RagStageScope] = Field(
        default_factory=lambda: ["any"],
        max_length=RAG_STAGE_SCOPE_MAX_ITEMS,
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
    stage_scope: list[RagStageScope] = Field(
        default_factory=lambda: ["any"],
        max_length=RAG_STAGE_SCOPE_MAX_ITEMS,
    )
    source_id: str = Field(default="", max_length=IDENTIFIER_MAX_CHARS)
    tags: list[RagTag] = Field(default_factory=list, max_length=RAG_TAGS_MAX_ITEMS)
    enabled: bool = True


class AdminRagDocumentEnabledRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class AdminRagKnowledgeReviewRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=1000)


class AdminEvaluationRunRequest(RequestModel):
    batch_id: str = Field(max_length=IDENTIFIER_MAX_CHARS)
    suite_id: str = Field(default=ADMIN_DEFAULT_EVALUATION_SUITE_ID, max_length=IDENTIFIER_MAX_CHARS)


class AdminEvaluationStepRequest(RequestModel):
    kind: Literal["message", "physical_exam", "auxiliary_test", "submit_diagnosis"]
    value: str = Field(min_length=1, max_length=4096)
    reasoning: str = Field(default="", max_length=4096)


class AdminEvaluationCaseUpsertRequest(RequestModel):
    case_key: str = Field(min_length=1, max_length=IDENTIFIER_MAX_CHARS, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=120)
    case_id: str = Field(min_length=1, max_length=IDENTIFIER_MAX_CHARS)
    steps: list[AdminEvaluationStepRequest] = Field(min_length=1, max_length=40)
    expected_total_score: int = Field(ge=0, le=1000)
    forbidden_terms: list[str] = Field(default_factory=list, max_length=40)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_steps(self) -> "AdminEvaluationCaseUpsertRequest":
        if sum(step.kind == "submit_diagnosis" for step in self.steps) != 1:
            raise ValueError("evaluation case must contain exactly one submit_diagnosis step")
        if any(not term.strip() or len(term) > 100 for term in self.forbidden_terms):
            raise ValueError("forbidden terms must contain 1 to 100 characters")
        return self


class AdminEvaluationThresholdsRequest(RequestModel):
    maximum_score_delta: int = Field(default=0, ge=0, le=1000)
    minimum_batch_pass_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    minimum_rag_explanation_coverage_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    minimum_rag_evidence_coverage_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    require_rag_source_coverage: bool = True
    maximum_case_duration_ms: int = Field(default=0, ge=0, le=3_600_000)


class AdminEvaluationSuiteUpsertRequest(RequestModel):
    suite_id: str = Field(min_length=1, max_length=IDENTIFIER_MAX_CHARS, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    case_keys: list[str] = Field(min_length=1, max_length=100)
    thresholds: AdminEvaluationThresholdsRequest = Field(default_factory=AdminEvaluationThresholdsRequest)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_case_keys(self) -> "AdminEvaluationSuiteUpsertRequest":
        normalized = [case_key.strip() for case_key in self.case_keys]
        if any(not case_key for case_key in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("evaluation suite case keys must be unique and non-empty")
        return self


class AdminEvaluationScheduleUpdateRequest(RequestModel):
    enabled: bool
    suite_id: str = Field(min_length=1, max_length=IDENTIFIER_MAX_CHARS)
    interval_minutes: int = Field(ge=5, le=10_080)


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
        provider_label = (
            "阿里云百炼 Qwen"
            if is_trusted_dashscope_endpoint(openai_settings.base_url)
            else "OpenAI 兼容模型"
        )
        return {
            "active": True,
            "provider": "openai_compatible",
            "model": openai_settings.model,
            "base_url": "",
            "proxy_url": "",
            "integration_targets": list(RUNTIME_MODEL_CONFIG_INTEGRATION_TARGETS),
            "api_key_saved": False,
            "message": f"服务端已统一配置：{provider_label}；前端不可修改 API Key。",
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


def _run_report_enrichment_background_task(session_id: str, user_id: str) -> dict[str, Any] | None:
    with use_api_call_session_context(session_id):
        return _enrich_report_optional_agents_for_user(session_id, user_id)


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
    deadline_token = set_model_call_deadline(
        _model_request_timeout_seconds(request.url.path)
    )
    try:
        yield
    finally:
        reset_model_call_deadline(deadline_token)
        model_request_admission_gate.release()


def _model_request_timeout_seconds(path: str) -> float | None:
    if not str(path).endswith(("/report/generate", "/report/enrich")):
        return None
    raw_value = os.getenv(REPORT_MODEL_CALL_TIMEOUT_SECONDS_ENV, "").strip()
    try:
        configured = float(raw_value) if raw_value else DEFAULT_REPORT_MODEL_CALL_TIMEOUT_SECONDS
    except ValueError:
        return DEFAULT_REPORT_MODEL_CALL_TIMEOUT_SECONDS
    if not math.isfinite(configured) or configured <= 0:
        return DEFAULT_REPORT_MODEL_CALL_TIMEOUT_SECONDS
    return min(configured, MAX_REPORT_MODEL_CALL_TIMEOUT_SECONDS)


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
    if isinstance(exc, ModelProviderPayloadTooLargeError):
        return HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=MODEL_PROVIDER_PAYLOAD_TOO_LARGE_DETAIL,
        )
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


def _is_fixed_demo_account(email: str) -> bool:
    normalized_email = email.strip().lower()
    return normalized_email in {
        configured_email
        for configured_email in (
            _get_demo_admin_email() if _is_demo_admin_enabled() else "",
            _get_demo_student_email() if _is_demo_student_enabled() else "",
        )
        if configured_email
    }


def _effective_user_role(user: dict[str, str]) -> str:
    email = user.get("email", "").strip().lower()
    if _is_demo_student_enabled() and email == _get_demo_student_email():
        return "student"
    stored_role = user.get("role", "student").strip().lower()
    if stored_role == "admin" or is_admin_email_allowed(email):
        return "admin"
    return stored_role if stored_role in AUTH_USER_ROLES else "student"


def _build_auth_user_payload(user: dict[str, str]) -> dict[str, object]:
    role = _effective_user_role(user)
    return {
        **user,
        "role": role,
        "status": user.get("status", "active"),
        "is_admin": role == "admin",
    }


def _build_admin_user_payload(user: dict[str, str]) -> dict[str, object]:
    payload = _build_auth_user_payload(user)
    return {
        **payload,
        "eligible_for_classroom": (
            payload.get("role") == "student" and payload.get("status") == "active"
        ),
        "eligible_as_teacher": (
            payload.get("role") == "teacher" and payload.get("status") == "active"
        ),
        "managed_by_environment": _is_fixed_demo_account(
            str(payload.get("email") or "")
        ),
    }


def _admin_user_directory() -> list[dict[str, object]]:
    return [_build_admin_user_payload(user) for user in auth_store.list_users()]


def _validated_classroom_member_user_ids(
    requested_user_ids: list[str],
) -> list[str]:
    normalized_user_ids = list(
        dict.fromkeys(user_id.strip() for user_id in requested_user_ids)
    )
    users_by_id = {
        str(user["user_id"]): user
        for user in _admin_user_directory()
    }
    invalid_user_ids = [
        user_id
        for user_id in normalized_user_ids
        if user_id not in users_by_id
        or users_by_id[user_id].get("role") != "student"
        or users_by_id[user_id].get("status") != "active"
    ]
    if invalid_user_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="班级成员必须是已存在且启用中的学生账号",
        )
    return normalized_user_ids


def _validated_classroom_teacher_user_id(teacher_user_id: str) -> str:
    normalized_teacher_user_id = teacher_user_id.strip()
    if not normalized_teacher_user_id:
        return ""
    users_by_id = {
        str(user["user_id"]): user
        for user in _admin_user_directory()
    }
    teacher = users_by_id.get(normalized_teacher_user_id)
    if (
        teacher is None
        or teacher.get("role") != "teacher"
        or teacher.get("status") != "active"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="班级负责人必须是已存在且启用中的教师账号",
        )
    return normalized_teacher_user_id


def _classroom_import_value(
    row: dict[str, str | None],
    *field_names: str,
) -> str:
    normalized_row = {
        str(key or "").strip().lstrip("\ufeff").lower(): str(value or "").strip()
        for key, value in row.items()
    }
    for field_name in field_names:
        value = normalized_row.get(field_name.lower(), "")
        if value:
            return value
    return ""


def _split_classroom_import_emails(value: str) -> list[str]:
    return list(
        dict.fromkeys(
            email.strip().lower()
            for email in re.split(r"[;,，、\n]+", value)
            if email.strip()
        )
    )


def _parse_admin_classroom_import(
    request: AdminClassroomImportRequest,
) -> list[dict[str, Any]]:
    reader = csv.DictReader(StringIO(request.csv_text.lstrip("\ufeff")))
    if reader.fieldnames is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="班级 CSV 缺少表头",
        )
    rows = list(reader)
    if len(rows) > CLASSROOM_IMPORT_MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"班级 CSV 不能超过 {CLASSROOM_IMPORT_MAX_ROWS} 行",
        )
    users_by_email = {
        str(user["email"]).lower(): user
        for user in _admin_user_directory()
    }
    existing_by_name = {
        str(classroom["name"]).casefold(): classroom
        for classroom in classroom_store.list_classrooms()
    }
    grouped: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for row_number, row in enumerate(rows, start=2):
        name = _classroom_import_value(row, "classroom_name", "name", "班级名称")
        if not name:
            if any(str(value or "").strip() for value in row.values()):
                errors.append(f"第 {row_number} 行缺少班级名称")
            continue
        key = name.casefold()
        existing = existing_by_name.get(key)
        record = grouped.setdefault(
            key,
            {
                "name": name,
                "description": (
                    str(existing.get("description") or "")
                    if request.mode == "merge" and existing
                    else ""
                ),
                "teacher_user_id": (
                    str(existing.get("teacher_user_id") or "")
                    if request.mode == "merge" and existing
                    else ""
                ),
                "status": (
                    str(existing.get("status") or "active")
                    if request.mode == "merge" and existing
                    else "active"
                ),
                "member_user_ids": list(
                    existing.get("member_user_ids", [])
                    if request.mode == "merge" and existing
                    else []
                ),
            },
        )
        description = _classroom_import_value(
            row,
            "description",
            "班级说明",
        )
        if description:
            record["description"] = description
        status_value = _classroom_import_value(row, "status", "状态")
        if status_value:
            normalized_status = {
                "启用": "active",
                "活动": "active",
                "归档": "archived",
            }.get(status_value, status_value.lower())
            if normalized_status not in {"active", "archived"}:
                errors.append(f"第 {row_number} 行班级状态无效")
            else:
                record["status"] = normalized_status
        teacher_email = _classroom_import_value(
            row,
            "teacher_email",
            "负责教师邮箱",
            "教师邮箱",
        ).lower()
        if teacher_email:
            teacher = users_by_email.get(teacher_email)
            if (
                teacher is None
                or teacher.get("role") != "teacher"
                or teacher.get("status") != "active"
            ):
                errors.append(f"第 {row_number} 行教师账号不存在或未启用")
            else:
                record["teacher_user_id"] = teacher["user_id"]
        student_value = _classroom_import_value(
            row,
            "student_email",
            "member_email",
            "学生邮箱",
            "学生邮箱列表",
        )
        for student_email in _split_classroom_import_emails(student_value):
            student = users_by_email.get(student_email)
            if (
                student is None
                or student.get("role") != "student"
                or student.get("status") != "active"
            ):
                errors.append(
                    f"第 {row_number} 行学生 {student_email} 不存在或未启用"
                )
                continue
            if student["user_id"] not in record["member_user_ids"]:
                record["member_user_ids"].append(student["user_id"])
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "班级 CSV 校验失败", "errors": errors[:50]},
        )
    if not grouped:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="班级 CSV 没有可导入的数据",
        )
    return list(grouped.values())


def _build_admin_classroom_payload(
    classroom: dict[str, Any],
) -> dict[str, object]:
    users_by_id = {
        str(user["user_id"]): user
        for user in _admin_user_directory()
    }
    member_user_ids = _eligible_classroom_member_user_ids(
        classroom,
        users_by_id=users_by_id,
    )
    members = [
        users_by_id[user_id]
        for user_id in member_user_ids
        if user_id in users_by_id
    ]
    teacher_user_id = str(classroom.get("teacher_user_id") or "")
    return {
        **classroom,
        "member_user_ids": member_user_ids,
        "member_count": len(member_user_ids),
        "members": members,
        "teacher": users_by_id.get(teacher_user_id),
    }


def _eligible_classroom_member_user_ids(
    classroom: dict[str, Any],
    *,
    users_by_id: dict[str, dict[str, object]] | None = None,
) -> list[str]:
    effective_users_by_id = (
        users_by_id
        if users_by_id is not None
        else {
            str(user["user_id"]): user
            for user in _admin_user_directory()
        }
    )
    return [
        user_id
        for user_id in (
            str(value)
            for value in classroom.get("member_user_ids", [])
        )
        if user_id in effective_users_by_id
        and effective_users_by_id[user_id].get("role") == "student"
        and effective_users_by_id[user_id].get("status") == "active"
    ]


def _record_admin_audit(
    *,
    actor: dict[str, str],
    action: str,
    resource_type: str,
    resource_id: str,
    summary: str,
    before: Any = None,
    after: Any = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return admin_audit_store.record(
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        summary=summary[:ADMIN_AUDIT_SUMMARY_MAX_CHARS],
        before=before,
        after=after,
        metadata=metadata,
    )


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
    if _effective_user_role(user) != "admin":
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


def _set_approval_agent_decision(
    candidate: dict[str, Any],
    review: dict[str, Any],
    *,
    auto_apply_enabled: bool,
) -> None:
    agent_review = candidate.get("approval_agent_review")
    if not isinstance(agent_review, dict):
        return
    candidate["approval_agent_review"] = {
        **agent_review,
        "decision": (
            "approved_for_auto_apply"
            if auto_apply_enabled and review["status"] == "ready_for_review"
            else "ready_for_human_review"
            if review["status"] == "ready_for_review"
            else "blocked_by_regression"
        ),
        "regression_status": review["status"],
        "regression_passed": review["regression_passed"],
        "regression_gate": {
            "status": review["status"],
            "passed": review["regression_passed"],
            "evaluation_total_cases": review.get("evaluation_total_cases", 0),
            "evaluation_passed_cases": review.get("evaluation_passed_cases", 0),
            "evaluation_failed_cases": review.get("evaluation_failed_cases", 0),
            "blocking_failures": list(review.get("blocking_failures", [])),
            "candidate_safety_violations": list(review.get("candidate_safety_violations", [])),
            "candidate_context_violations": list(review.get("candidate_context_violations", [])),
            "approval_agent_violations": list(review.get("approval_agent_violations", [])),
        },
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
    if not target_rubric_item_refs:
        target_rubric_item_refs = [
            {"case_id": rubric_label_case_id or case_id, "item_id": item_id}
            for item_id in target_rubric_items
        ]
    source_references = [str(reference) for reference in task.get("source_references", []) if str(reference)]
    label_case_id = rubric_label_case_id or case_id
    target_rubric_item_labels = (
        _rubric_item_labels_for_refs(target_rubric_item_refs, fallback_case_id=label_case_id)
        if target_rubric_item_refs
        else rubric_item_labels(target_rubric_items, [label_case_id])
    )
    public_task = dict(task)
    return {
        **public_task,
        "task_type_label": LEARNING_TASK_TYPE_LABELS.get(task_type, task_type or "训练任务"),
        "case_title": _get_case_title(case_id),
        "target_rubric_item_refs": target_rubric_item_refs,
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
    if not SOURCE_REGISTRY_PATH.exists():
        return []
    sources = json.loads(SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    return [
        enrich_source_freshness(source)
        for source in sources
        if isinstance(source, dict)
    ] if isinstance(sources, list) else []


def _load_admin_sources_raw() -> list[dict[str, Any]]:
    if not SOURCE_REGISTRY_PATH.exists():
        return []
    payload = json.loads(SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("source registry must be a list")
    return [deepcopy(item) for item in payload if isinstance(item, dict)]


def _normalize_admin_source_payload(request: AdminSourceUpsertRequest) -> dict[str, Any]:
    payload = request.model_dump(exclude={"change_note", "medical_review_note"})
    for field_name in (
        "source_id",
        "source_name",
        "source_url",
        "license",
        "data_type",
        "transformation",
        "risk_note",
        "source_version",
        "last_reviewed_at",
        "source_status",
        "superseded_by",
        "review_basis",
    ):
        payload[field_name] = str(payload.get(field_name) or "").strip()
    payload["allowed_usage"] = list(
        dict.fromkeys(
            str(value).strip()
            for value in payload.get("allowed_usage", [])
            if str(value).strip()
        )
    )
    payload["search_aliases"] = list(
        dict.fromkeys(
            str(value).strip()
            for value in payload.get("search_aliases", [])
            if str(value).strip()
        )
    )
    return payload


def _validate_admin_source_registry(sources: list[dict[str, Any]]) -> None:
    source_ids = [str(source.get("source_id") or "").strip() for source in sources]
    if any(not _is_safe_admin_import_id(source_id) for source_id in source_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="来源 ID 无效")
    if len(set(source_ids)) != len(source_ids):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="来源 ID 已存在")
    known_ids = set(source_ids)
    for source in sources:
        source_id = str(source.get("source_id") or "").strip()
        replacement = str(source.get("superseded_by") or "").strip()
        if replacement and (replacement == source_id or replacement not in known_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="替代来源必须是台账中另一个已登记来源",
            )
        if source.get("source_status") == "superseded" and not replacement:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="标记为已替代时必须选择替代来源",
            )


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_admin_sources(sources: list[dict[str, Any]]) -> None:
    _validate_admin_source_registry(sources)
    _atomic_write_text(
        SOURCE_REGISTRY_PATH,
        json.dumps(sources, ensure_ascii=False, indent=2) + "\n",
    )
    _clear_admin_source_caches()


def _clear_admin_source_caches() -> None:
    source_retriever._source_registry.cache_clear()
    admin_display_resolver._source_registry_map.cache_clear()
    _clear_retrieval_documents_cache()


def _admin_source_by_id(source_id: str) -> dict[str, Any] | None:
    return next(
        (
            source
            for source in _load_admin_sources_raw()
            if str(source.get("source_id") or "").strip() == source_id
        ),
        None,
    )


def _build_admin_rag_knowledge_item(request: AdminRagKnowledgeItemRequest) -> dict[str, Any]:
    item = request.model_dump()
    unknown_stage_scopes = unsupported_rag_stage_scopes(item.get("stage_scope"))
    if unknown_stage_scopes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported knowledge stage scope")
    item["scope"] = item["scope"].strip()
    item["case_id"] = item["case_id"].strip()
    item["content_kind"] = item["content_kind"].strip()
    item["visibility"] = item["visibility"].strip()
    item["source_id"] = item["source_id"].strip()
    item["title"] = item["title"].strip()
    item["text"] = item["text"].strip()
    item["allowed_agents"] = [str(agent).strip() for agent in item["allowed_agents"] if str(agent).strip()]
    item["stage_scope"] = normalize_rag_stage_scope(item.get("stage_scope"))
    item["tags"] = [str(tag).strip() for tag in item["tags"] if str(tag).strip()]
    knowledge_id = str(item.get("knowledge_id", "")).strip()
    if not knowledge_id:
        knowledge_id = _generate_admin_rag_knowledge_id(item)
    item["knowledge_id"] = knowledge_id
    existing_item = rag_knowledge_store.get_item(knowledge_id)
    if existing_item is not None:
        item = {**existing_item, **item}
    assessment = assess_rag_text(
        item["text"],
        section_title=str(item.get("section_title") or item["title"]),
        categories=[str(value) for value in item.get("chunk_categories", []) if str(value)],
    )
    item["quality_warnings"] = assessment["quality_warnings"]
    item["risk_flags"] = assessment["risk_flags"]
    item["char_count"] = assessment["char_count"]
    if existing_item is None or _rag_knowledge_exposure_changed(existing_item, item):
        item["review_status"] = "pending_review" if item["risk_flags"] else "approved"
        item["review_note"] = ""
        item["reviewed_by"] = ""
        item["reviewed_at"] = ""
    _validate_admin_rag_knowledge_item(item, existing_item=existing_item)
    return item


def _rag_knowledge_exposure_changed(existing_item: dict[str, Any], next_item: dict[str, Any]) -> bool:
    safety_fields = {
        "title",
        "text",
        "visibility",
        "allowed_agents",
        "stage_scope",
        "case_id",
        "scope",
        "source_id",
    }
    return any(existing_item.get(field) != next_item.get(field) for field in safety_fields)


def _generate_admin_rag_knowledge_id(item: dict[str, Any]) -> str:
    case_part = item["case_id"] if item["case_id"] else "global"
    digest = hashlib.sha1(
        f"{item['scope']}|{case_part}|{item['content_kind']}|{item['title']}|{item['text']}".encode("utf-8")
    ).hexdigest()[:12]
    return f"kb:{item['scope']}:{case_part}:{item['content_kind']}:{digest}"


def _validate_admin_rag_knowledge_item(
    item: dict[str, Any],
    *,
    existing_item: dict[str, Any] | None = None,
) -> None:
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
    if (
        item["source_id"]
        and item["source_id"] not in _admin_selectable_source_ids()
        and (
            existing_item is None
            or item["source_id"] != str(existing_item.get("source_id") or "").strip()
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="source_id is not current; review the source ledger or select an active source",
        )
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
    unknown_stage_scopes = unsupported_rag_stage_scopes(request.stage_scope)
    if unknown_stage_scopes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported knowledge stage scope")
    stage_scope = normalize_rag_stage_scope(request.stage_scope)
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
    if source_id and source_id not in _admin_selectable_source_ids():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="source_id is not current; review the source ledger or select an active source",
        )
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
            "stage_scope": stage_scope,
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
            "review_status": "pending_review" if chunk.risk_flags else "approved",
            "review_note": "",
            "reviewed_by": "",
            "reviewed_at": "",
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


def _admin_selectable_source_ids() -> set[str]:
    return {
        str(source.get("source_id", "")).strip()
        for source in _load_admin_sources()
        if str(source.get("source_id", "")).strip()
        and source.get("selectable_for_new_knowledge") is True
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
        # Admin-provisioned accounts authenticate in every deployment mode.
        # Fixed demo accounts are still only auto-provisioned by explicit local
        # demo configuration above.
        user = auth_store.authenticate_user(request.email, request.password)
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


def _build_readiness_sqlite_targets() -> tuple[SQLiteReadinessTarget, ...]:
    session_service = osce_session_service
    session_store = session_service.session_store
    report_store = session_service.report_store
    event_store = session_service.training_event_store
    profile_store = session_service.student_profile_store
    candidate_store = session_service.training_skill_candidate_store
    skill_store = session_service.training_skill_store
    return (
        SQLiteReadinessTarget(
            database_path=auth_store.database_path,
            required_tables=("auth_sessions", "users"),
        ),
        SQLiteReadinessTarget(
            database_path=classroom_store.database_path,
            required_tables=("classroom_memberships", "classrooms"),
        ),
        SQLiteReadinessTarget(
            database_path=admin_audit_store.database_path,
            required_tables=("admin_audit_events",),
        ),
        SQLiteReadinessTarget(
            database_path=admin_asset_version_store.database_path,
            required_tables=("admin_asset_versions",),
        ),
        SQLiteReadinessTarget(
            database_path=session_store.database_path,
            required_tables=("osce_sessions", "osce_session_event_outbox"),
        ),
        SQLiteReadinessTarget(
            database_path=report_store.database_path,
            required_tables=("reports", "report_outbox"),
        ),
        SQLiteReadinessTarget(
            database_path=event_store.database_path,
            required_tables=("training_events",),
        ),
        SQLiteReadinessTarget(
            database_path=profile_store.database_path,
            required_tables=("student_profiles",),
        ),
        SQLiteReadinessTarget(
            database_path=candidate_store.database_path,
            required_tables=("training_skill_candidates",),
        ),
        SQLiteReadinessTarget(
            database_path=skill_store.database_path,
            required_tables=("training_skills",),
        ),
        SQLiteReadinessTarget(
            database_path=user_model_config_store.database_path,
            required_tables=("user_runtime_model_configs",),
        ),
        SQLiteReadinessTarget(
            database_path=rag_knowledge_store.database_path,
            required_tables=("rag_knowledge_items",),
        ),
        SQLiteReadinessTarget(
            database_path=evaluation_result_store.database_path,
            required_tables=("evaluation_results",),
        ),
        SQLiteReadinessTarget(
            database_path=admin_evaluation_config_store.database_path,
            required_tables=(
                "admin_evaluation_cases",
                "admin_evaluation_suites",
                "admin_evaluation_schedule",
            ),
        ),
        SQLiteReadinessTarget(
            database_path=training_skill_auto_approval_settings_store.database_path,
            required_tables=("training_skill_auto_approval_settings",),
        ),
    )


def _readiness_persistence_initializers() -> tuple[tuple[str, Callable[[], None]], ...]:
    session_service = osce_session_service
    return (
        ("auth", auth_store._initialize),
        ("classrooms", classroom_store._initialize),
        ("admin_audit", admin_audit_store._initialize),
        ("admin_asset_versions", admin_asset_version_store._initialize),
        ("sessions", session_service.session_store._initialize),
        ("reports", session_service.report_store._initialize),
        ("training_events", session_service.training_event_store._initialize),
        ("student_profiles", session_service.student_profile_store._initialize),
        ("skill_candidates", session_service.training_skill_candidate_store._initialize),
        ("skills", session_service.training_skill_store._initialize),
        ("user_model_config", user_model_config_store._initialize),
        ("rag_knowledge", rag_knowledge_store._initialize),
        ("evaluation_results", evaluation_result_store._initialize),
        ("evaluation_config", _ensure_admin_evaluation_config_defaults),
        ("skill_auto_approval", training_skill_auto_approval_settings_store._initialize),
    )


def _initialize_readiness_persistence() -> list[str]:
    failures: list[str] = []
    for target_name, initializer in _readiness_persistence_initializers():
        try:
            initializer()
        except Exception as exc:
            failures.append(target_name)
            logger.error(
                "startup persistence target failed (%s: %s)",
                target_name,
                exc.__class__.__name__,
            )
    return failures


def _readiness_writable_directories(
    sqlite_targets: tuple[SQLiteReadinessTarget, ...],
) -> tuple[Path, ...]:
    return tuple(
        dict.fromkeys(
            [
                CASES_DIR,
                RUBRICS_DIR,
                *(target.database_path.parent for target in sqlite_targets),
            ]
        )
    )


def _production_admin_account_is_ready() -> bool:
    if not is_production_deployment_mode():
        return True
    try:
        return auth_store.has_any_user(get_configured_admin_email_set())
    except Exception:
        return False


@app.get("/ready")
def readiness_check() -> JSONResponse:
    sqlite_targets = _build_readiness_sqlite_targets()
    payload = build_readiness_self_check(
        writable_directories=_readiness_writable_directories(sqlite_targets),
        sqlite_targets=sqlite_targets,
        admin_account_ready=_production_admin_account_is_ready(),
        startup_persistence_ready=bool(
            getattr(app.state, "startup_persistence_ready", True)
        ),
        startup_recovery_ready=bool(
            getattr(app.state, "startup_recovery_ready", True)
        ),
    )
    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if payload["status"] == "ready"
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content=payload,
    )


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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=SPEECH_PROVIDER_FAILURE_DETAIL,
        ) from exc
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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=SPEECH_PROVIDER_FAILURE_DETAIL,
        ) from exc
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
    admin_display_resolver._load_case_payload.cache_clear()
    admin_display_resolver._load_rubric_payload.cache_clear()


def _load_admin_case_assets(case_id: str) -> dict[str, Any] | None:
    if not _is_safe_admin_import_id(case_id):
        return None
    case_path = CASES_DIR / f"{case_id}.json"
    if not case_path.exists():
        return None
    case_payload = json.loads(case_path.read_text(encoding="utf-8"))
    if not isinstance(case_payload, dict):
        return None
    rubric_ref = case_payload.get("rubric_ref")
    rubric_id = (
        str(rubric_ref.get("rubric_id") or "").strip()
        if isinstance(rubric_ref, dict)
        else ""
    )
    rubric_payload = _load_admin_rubric(rubric_id) if rubric_id else None
    if rubric_payload is None:
        return None
    return {"case": case_payload, "rubric": rubric_payload}


def _validate_admin_case_assets(
    case_id: str,
    case_payload: dict[str, Any],
    rubric_payload: dict[str, Any],
) -> tuple[str, list[str]]:
    errors: list[str] = []
    if case_payload.get("case_id") != case_id:
        errors.append("case_id 与路径不一致")
    rubric_id = str(rubric_payload.get("rubric_id") or "").strip()
    if not _is_safe_admin_import_id(rubric_id):
        errors.append("rubric_id 无效")
    case_model = None
    rubric_model = None
    try:
        case_model = validate_case(case_payload)
    except Exception as exc:
        errors.append(str(exc))
    try:
        rubric_model = validate_rubric(rubric_payload)
    except Exception as exc:
        errors.append(str(exc))
    if case_model is not None and rubric_model is not None:
        try:
            validate_case_rubric_pair(case_model, rubric_model)
        except Exception as exc:
            errors.append(str(exc))
    return rubric_id, errors


def _write_admin_case_assets(
    case_id: str,
    case_payload: dict[str, Any],
    rubric_payload: dict[str, Any],
) -> None:
    rubric_id, errors = _validate_admin_case_assets(
        case_id,
        case_payload,
        rubric_payload,
    )
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "病例与评分表校验失败", "errors": errors},
        )
    case_path = CASES_DIR / f"{case_id}.json"
    rubric_path = RUBRICS_DIR / f"{rubric_id}.yaml"
    previous_case = case_path.read_text(encoding="utf-8") if case_path.exists() else None
    previous_rubric = rubric_path.read_text(encoding="utf-8") if rubric_path.exists() else None
    try:
        _atomic_write_text(
            case_path,
            json.dumps(case_payload, ensure_ascii=False, indent=2) + "\n",
        )
        _atomic_write_text(
            rubric_path,
            yaml.safe_dump(rubric_payload, allow_unicode=True, sort_keys=False),
        )
    except Exception:
        if previous_case is None:
            case_path.unlink(missing_ok=True)
        else:
            _atomic_write_text(case_path, previous_case)
        if previous_rubric is None:
            rubric_path.unlink(missing_ok=True)
        else:
            _atomic_write_text(rubric_path, previous_rubric)
        raise
    _clear_admin_case_asset_caches()


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


@app.get("/api/admin/users")
def list_admin_users(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return {"users": _admin_user_directory()}


@app.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
def create_admin_user(
    request: AdminUserCreateRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    _validate_auth_request(request.email, request.password)
    user = auth_store.create_user(
        request.email,
        request.password,
        request.display_name,
        role=request.role,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="账号邮箱已存在",
        )
    payload = _build_admin_user_payload(user)
    _record_admin_audit(
        actor=actor,
        action="user.created",
        resource_type="user",
        resource_id=user["user_id"],
        summary=f"创建账号 {user['email']}",
        after=payload,
    )
    return {"user": payload}


@app.patch("/api/admin/users/{user_id}")
def update_admin_user(
    user_id: str,
    request: AdminUserUpdateRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    current = auth_store.get_user_by_id(user_id)
    if current is None or current.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="账号不存在")
    if _is_fixed_demo_account(current["email"]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="演示账号由运行环境配置管理",
        )
    if actor["user_id"] == user_id and (
        request.email is not None
        or request.role not in {None, "admin"}
        or request.status not in {None, "active"}
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能修改当前管理员自己的邮箱、角色或启用状态",
        )
    updated = auth_store.update_user(
        user_id,
        email=request.email,
        display_name=request.display_name,
        role=request.role,
        status=request.status,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="账号更新失败，邮箱可能已被占用",
        )
    before_payload = _build_auth_user_payload(current)
    after_payload = _build_admin_user_payload(updated)
    _record_admin_audit(
        actor=actor,
        action="user.updated",
        resource_type="user",
        resource_id=user_id,
        summary=f"更新账号 {updated['email']}",
        before=before_payload,
        after=after_payload,
    )
    return {"user": after_payload}


@app.post("/api/admin/users/{user_id}/reset-password")
def reset_admin_user_password(
    user_id: str,
    request: AdminUserPasswordResetRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    current = auth_store.get_user_by_id(user_id)
    if current is None or current.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="账号不存在")
    if _is_fixed_demo_account(current["email"]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="演示账号密码由运行环境配置管理",
        )
    updated = auth_store.reset_password(user_id, request.password)
    if updated is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    _record_admin_audit(
        actor=actor,
        action="user.password_reset",
        resource_type="user",
        resource_id=user_id,
        summary=f"重置账号 {updated['email']} 的密码并注销旧会话",
        metadata={"revoked_existing_sessions": True},
    )
    return {"user": _build_admin_user_payload(updated), "sessions_revoked": True}


@app.delete("/api/admin/users/{user_id}")
def delete_admin_user(
    user_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    current = auth_store.get_user_by_id(user_id)
    if current is None or current.get("status") == "deleted":
        raise HTTPException(status_code=404, detail="账号不存在")
    if actor["user_id"] == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能删除当前登录的管理员账号",
        )
    if _is_fixed_demo_account(current["email"]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="演示账号由运行环境配置管理",
        )
    deleted = auth_store.delete_user(user_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    _record_admin_audit(
        actor=actor,
        action="user.deleted",
        resource_type="user",
        resource_id=user_id,
        summary=f"删除账号 {current['email']} 的登录权限，保留历史训练证据",
        before=_build_auth_user_payload(current),
        after=_build_auth_user_payload(deleted),
    )
    return {"deleted": True, "user": _build_admin_user_payload(deleted)}


@app.get("/api/admin/classrooms")
def list_admin_classrooms(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return {
        "classrooms": [
            _build_admin_classroom_payload(classroom)
            for classroom in classroom_store.list_classrooms()
        ]
    }


@app.post("/api/admin/classrooms/import")
def import_admin_classrooms(
    request: AdminClassroomImportRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    records = _parse_admin_classroom_import(request)
    imported = classroom_store.import_classrooms(
        records,
        actor_user_id=actor["user_id"],
    )
    payloads = [
        _build_admin_classroom_payload(classroom)
        for classroom in imported
    ]
    _record_admin_audit(
        actor=actor,
        action="classroom.imported",
        resource_type="classroom",
        resource_id="bulk-import",
        summary=f"批量导入或更新 {len(payloads)} 个班级",
        after=payloads,
        metadata={"mode": request.mode},
    )
    return {"classrooms": payloads, "imported_count": len(payloads)}


@app.post("/api/admin/classrooms", status_code=status.HTTP_201_CREATED)
def create_admin_classroom(
    request: AdminClassroomUpsertRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    admin_user = _require_admin_user(auth_token)
    member_user_ids = _validated_classroom_member_user_ids(
        request.member_user_ids
    )
    teacher_user_id = _validated_classroom_teacher_user_id(
        request.teacher_user_id
    )
    try:
        classroom = classroom_store.create_classroom(
            name=request.name,
            description=request.description,
            member_user_ids=member_user_ids,
            actor_user_id=admin_user["user_id"],
            teacher_user_id=teacher_user_id,
            status=request.status,
        )
    except ClassroomNameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="班级名称已存在",
        ) from exc
    payload = _build_admin_classroom_payload(classroom)
    _record_admin_audit(
        actor=admin_user,
        action="classroom.created",
        resource_type="classroom",
        resource_id=classroom["classroom_id"],
        summary=f"创建班级 {classroom['name']}",
        after=payload,
    )
    return {"classroom": payload}


@app.put("/api/admin/classrooms/{classroom_id}")
def update_admin_classroom(
    classroom_id: str,
    request: AdminClassroomUpsertRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    admin_user = _require_admin_user(auth_token)
    previous = classroom_store.get_classroom(classroom_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="班级不存在")
    member_user_ids = _validated_classroom_member_user_ids(
        request.member_user_ids
    )
    teacher_user_id = _validated_classroom_teacher_user_id(
        request.teacher_user_id
    )
    try:
        classroom = classroom_store.update_classroom(
            classroom_id,
            name=request.name,
            description=request.description,
            member_user_ids=member_user_ids,
            actor_user_id=admin_user["user_id"],
            teacher_user_id=teacher_user_id,
            status=request.status,
        )
    except ClassroomNameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="班级名称已存在",
        ) from exc
    if classroom is None:
        raise HTTPException(status_code=404, detail="班级不存在")
    payload = _build_admin_classroom_payload(classroom)
    _record_admin_audit(
        actor=admin_user,
        action="classroom.updated",
        resource_type="classroom",
        resource_id=classroom_id,
        summary=f"更新班级 {classroom['name']}",
        before=_build_admin_classroom_payload(previous),
        after=payload,
    )
    return {"classroom": payload}


@app.delete("/api/admin/classrooms/{classroom_id}")
def delete_admin_classroom(
    classroom_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    previous = classroom_store.get_classroom(classroom_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="班级不存在")
    if not classroom_store.delete_classroom(classroom_id):
        raise HTTPException(status_code=404, detail="班级不存在")
    _record_admin_audit(
        actor=actor,
        action="classroom.deleted",
        resource_type="classroom",
        resource_id=classroom_id,
        summary=f"删除班级 {previous['name']}",
        before=_build_admin_classroom_payload(previous),
    )
    return {"deleted": True, "classroom_id": classroom_id}


@app.post("/api/admin/classrooms/{classroom_id}/members/transfer")
def transfer_admin_classroom_members(
    classroom_id: str,
    request: AdminClassroomMemberTransferRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    member_user_ids = _validated_classroom_member_user_ids(
        request.member_user_ids
    )
    try:
        result = classroom_store.transfer_members(
            source_classroom_id=classroom_id,
            target_classroom_id=request.target_classroom_id,
            member_user_ids=member_user_ids,
            move=request.mode == "move",
            actor_user_id=actor["user_id"],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="调班成员必须属于源班级，且目标班级必须不同",
        ) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="源班级或目标班级不存在")
    source, target = result
    source_payload = _build_admin_classroom_payload(source)
    target_payload = _build_admin_classroom_payload(target)
    _record_admin_audit(
        actor=actor,
        action=f"classroom.members_{request.mode}",
        resource_type="classroom",
        resource_id=classroom_id,
        summary=(
            f"{'移动' if request.mode == 'move' else '复制'} "
            f"{len(member_user_ids)} 名学生到 {target['name']}"
        ),
        after={"source": source_payload, "target": target_payload},
        metadata={
            "target_classroom_id": request.target_classroom_id,
            "member_user_ids": member_user_ids,
        },
    )
    return {"source_classroom": source_payload, "target_classroom": target_payload}


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
    actor = _require_admin_user(auth_token)
    before = _load_admin_case_assets(case_id)
    if before is None:
        raise HTTPException(status_code=404, detail="case not found")
    admin_asset_version_store.ensure_initial_version(
        asset_type="case",
        asset_id=case_id,
        payload=before,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
    )
    response = _build_admin_case_update_response(case_id, request)
    if response.get("updated") is True:
        after = _load_admin_case_assets(case_id)
        if after is not None:
            version = admin_asset_version_store.save_version(
                asset_type="case",
                asset_id=case_id,
                payload=after,
                actor_user_id=actor["user_id"],
                actor_email=actor["email"],
                change_note="更新病例基础字段",
                review_status="unreviewed",
                review_note="",
            )
            _record_admin_audit(
                actor=actor,
                action="case.updated",
                resource_type="case",
                resource_id=case_id,
                summary=f"更新病例 {case_id} 的基础字段",
                before=before,
                after=after,
                metadata={"version": version["version"]},
            )
    return response


@app.get("/api/admin/cases/{case_id}/assets")
def get_admin_case_assets(
    case_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    assets = _load_admin_case_assets(case_id)
    if assets is None:
        raise HTTPException(status_code=404, detail="case not found")
    version = admin_asset_version_store.ensure_initial_version(
        asset_type="case",
        asset_id=case_id,
        payload=assets,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
    )
    return {**assets, "current_version": version}


@app.put("/api/admin/cases/{case_id}/assets")
def replace_admin_case_assets(
    case_id: str,
    request: AdminCaseAssetReplaceRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    previous = _load_admin_case_assets(case_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="case not found")
    previous_rubric_id = str(previous["rubric"].get("rubric_id") or "")
    next_rubric_id = str(request.rubric.get("rubric_id") or "")
    if next_rubric_id != previous_rubric_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="rubric_id 不允许在版本编辑中改名")
    admin_asset_version_store.ensure_initial_version(
        asset_type="case",
        asset_id=case_id,
        payload=previous,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
    )
    _write_admin_case_assets(case_id, request.case, request.rubric)
    assets = {"case": deepcopy(request.case), "rubric": deepcopy(request.rubric)}
    version = admin_asset_version_store.save_version(
        asset_type="case",
        asset_id=case_id,
        payload=assets,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
        change_note=request.change_note,
        review_status=request.review_status,
        review_note=request.medical_review_note,
    )
    _record_admin_audit(
        actor=actor,
        action="case.assets_updated",
        resource_type="case",
        resource_id=case_id,
        summary=f"更新病例 {case_id} 的完整病例事实与评分表",
        before=previous,
        after=assets,
        metadata={"version": version["version"], "review_status": request.review_status},
    )
    return {**assets, "current_version": version}


@app.post("/api/admin/cases/{case_id}/review")
def review_admin_case_assets(
    case_id: str,
    request: AdminAssetReviewRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    assets = _load_admin_case_assets(case_id)
    if assets is None:
        raise HTTPException(status_code=404, detail="case not found")
    admin_asset_version_store.ensure_initial_version(
        asset_type="case",
        asset_id=case_id,
        payload=assets,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
    )
    version = admin_asset_version_store.save_version(
        asset_type="case",
        asset_id=case_id,
        payload=assets,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
        change_note="病例医学审核",
        review_status=request.review_status,
        review_note=request.medical_review_note,
    )
    _record_admin_audit(
        actor=actor,
        action=f"case.{request.review_status}",
        resource_type="case",
        resource_id=case_id,
        summary=f"{request.review_status} 病例 {case_id}",
        after=assets,
        metadata={"version": version["version"], "review_note": request.medical_review_note},
    )
    return {"case_id": case_id, "current_version": version}


@app.get("/api/admin/cases/{case_id}/versions")
def list_admin_case_versions(
    case_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, Any]:
    actor = _require_admin_user(auth_token)
    assets = _load_admin_case_assets(case_id)
    if assets is None:
        raise HTTPException(status_code=404, detail="case not found")
    admin_asset_version_store.ensure_initial_version(
        asset_type="case",
        asset_id=case_id,
        payload=assets,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
    )
    return admin_asset_version_store.list_versions(
        asset_type="case",
        asset_id=case_id,
        limit=limit,
        offset=offset,
    )


@app.get("/api/admin/cases/{case_id}/diff")
def diff_admin_case_versions(
    case_id: str,
    from_version: int = Query(ge=1),
    to_version: int = Query(ge=1),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, Any]:
    _require_admin_user(auth_token)
    diff = admin_asset_version_store.diff_versions(
        asset_type="case",
        asset_id=case_id,
        from_version=from_version,
        to_version=to_version,
    )
    if diff is None:
        raise HTTPException(status_code=404, detail="病例版本不存在")
    return diff


@app.post("/api/admin/cases/{case_id}/rollback")
def rollback_admin_case_assets(
    case_id: str,
    request: AdminAssetRollbackRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    previous = _load_admin_case_assets(case_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="case not found")
    target = admin_asset_version_store.get_version(
        asset_type="case",
        asset_id=case_id,
        version=request.version,
    )
    if target is None or not isinstance(target.get("payload"), dict):
        raise HTTPException(status_code=404, detail="病例版本不存在")
    payload = target["payload"]
    case_payload = payload.get("case")
    rubric_payload = payload.get("rubric")
    if not isinstance(case_payload, dict) or not isinstance(rubric_payload, dict):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="病例版本快照不完整")
    _write_admin_case_assets(case_id, case_payload, rubric_payload)
    assets = {"case": deepcopy(case_payload), "rubric": deepcopy(rubric_payload)}
    version = admin_asset_version_store.save_version(
        asset_type="case",
        asset_id=case_id,
        payload=assets,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
        change_note=request.change_note or f"回滚到版本 {request.version}",
        review_status=str(target.get("review_status") or "unreviewed"),
        review_note=str(target.get("review_note") or ""),
    )
    _record_admin_audit(
        actor=actor,
        action="case.rolled_back",
        resource_type="case",
        resource_id=case_id,
        summary=f"回滚病例 {case_id} 到版本 {request.version}",
        before=previous,
        after=assets,
        metadata={"target_version": request.version, "version": version["version"]},
    )
    return {**assets, "current_version": version}


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
    actor = _require_admin_user(auth_token)
    response = _build_admin_case_import_response(request)
    if response.get("imported") is True:
        case_id = str(response.get("case_id") or "")
        assets = _load_admin_case_assets(case_id)
        if assets is not None:
            version = admin_asset_version_store.save_version(
                asset_type="case",
                asset_id=case_id,
                payload=assets,
                actor_user_id=actor["user_id"],
                actor_email=actor["email"],
                change_note="导入病例",
                review_status="unreviewed",
                review_note="",
            )
            _record_admin_audit(
                actor=actor,
                action="case.imported",
                resource_type="case",
                resource_id=case_id,
                summary=f"导入病例 {case_id}",
                after=assets,
                metadata={"version": version["version"]},
            )
    return response


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
    actor = _require_admin_user(auth_token)
    rubric = _load_admin_rubric(rubric_id)
    case_id = str(rubric.get("case_id") or "") if rubric else ""
    before = _load_admin_case_assets(case_id) if case_id else None
    if before is not None:
        admin_asset_version_store.ensure_initial_version(
            asset_type="case",
            asset_id=case_id,
            payload=before,
            actor_user_id=actor["user_id"],
            actor_email=actor["email"],
        )
    response = _build_admin_rubric_item_update_response(rubric_id, item_id, request)
    if response.get("updated") is True and before is not None:
        after = _load_admin_case_assets(case_id)
        if after is not None:
            version = admin_asset_version_store.save_version(
                asset_type="case",
                asset_id=case_id,
                payload=after,
                actor_user_id=actor["user_id"],
                actor_email=actor["email"],
                change_note=f"更新评分项 {item_id}",
                review_status="unreviewed",
                review_note="",
            )
            response["version"] = version
            _record_admin_audit(
                actor=actor,
                action="rubric.updated",
                resource_type="rubric",
                resource_id=rubric_id,
                summary=f"更新评分表 {rubric_id} 的评分项 {item_id}",
                before=before,
                after=after,
                metadata={"case_id": case_id, "version": version["version"]},
            )
    return response


@app.get("/api/admin/sources")
def list_admin_sources(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    sources = _load_admin_sources()
    return {
        "sources": sources,
        "freshness_summary": summarize_source_freshness(sources),
    }


@app.post("/api/admin/sources", status_code=status.HTTP_201_CREATED)
def create_admin_source(
    request: AdminSourceUpsertRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    sources = _load_admin_sources_raw()
    source = _normalize_admin_source_payload(request)
    if any(item.get("source_id") == source["source_id"] for item in sources):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="来源 ID 已存在")
    next_sources = [*sources, source]
    _write_admin_sources(next_sources)
    version = admin_asset_version_store.save_version(
        asset_type="source",
        asset_id=source["source_id"],
        payload=source,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
        change_note=request.change_note or "创建来源",
        review_status=("approved" if source.get("last_reviewed_at") and source.get("review_basis") else "unreviewed"),
        review_note=request.medical_review_note,
    )
    enriched = enrich_source_freshness(source)
    _record_admin_audit(
        actor=actor,
        action="source.created",
        resource_type="source",
        resource_id=source["source_id"],
        summary=f"创建来源 {source['source_name']}",
        after=enriched,
        metadata={"version": version["version"]},
    )
    return {"source": enriched, "version": version}


@app.put("/api/admin/sources/{source_id}")
def update_admin_source(
    source_id: str,
    request: AdminSourceUpsertRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    if request.source_id != source_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="来源 ID 不允许改名")
    sources = _load_admin_sources_raw()
    index = next((index for index, item in enumerate(sources) if item.get("source_id") == source_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="来源不存在")
    previous = sources[index]
    admin_asset_version_store.ensure_initial_version(
        asset_type="source",
        asset_id=source_id,
        payload=previous,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
    )
    source = _normalize_admin_source_payload(request)
    next_sources = list(sources)
    next_sources[index] = source
    _write_admin_sources(next_sources)
    version = admin_asset_version_store.save_version(
        asset_type="source",
        asset_id=source_id,
        payload=source,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
        change_note=request.change_note or "更新来源",
        review_status="unreviewed",
        review_note=request.medical_review_note,
    )
    enriched = enrich_source_freshness(source)
    _record_admin_audit(
        actor=actor,
        action="source.updated",
        resource_type="source",
        resource_id=source_id,
        summary=f"更新来源 {source['source_name']}",
        before=enrich_source_freshness(previous),
        after=enriched,
        metadata={"version": version["version"]},
    )
    return {"source": enriched, "version": version}


@app.post("/api/admin/sources/{source_id}/review")
def review_admin_source(
    source_id: str,
    request: AdminSourceReviewRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    sources = _load_admin_sources_raw()
    index = next((index for index, item in enumerate(sources) if item.get("source_id") == source_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="来源不存在")
    previous = sources[index]
    admin_asset_version_store.ensure_initial_version(
        asset_type="source",
        asset_id=source_id,
        payload=previous,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
    )
    source = {
        **previous,
        "last_reviewed_at": request.last_reviewed_at,
        "review_interval_days": request.review_interval_days,
        "review_basis": request.review_basis.strip(),
        "source_status": request.source_status,
        "superseded_by": request.superseded_by.strip(),
    }
    next_sources = list(sources)
    next_sources[index] = source
    _write_admin_sources(next_sources)
    version = admin_asset_version_store.save_version(
        asset_type="source",
        asset_id=source_id,
        payload=source,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
        change_note="来源复核",
        review_status="approved",
        review_note=request.medical_review_note,
    )
    enriched = enrich_source_freshness(source)
    _record_admin_audit(
        actor=actor,
        action="source.reviewed",
        resource_type="source",
        resource_id=source_id,
        summary=f"复核来源 {source.get('source_name') or source_id}",
        before=enrich_source_freshness(previous),
        after=enriched,
        metadata={"version": version["version"]},
    )
    return {"source": enriched, "version": version}


@app.delete("/api/admin/sources/{source_id}")
def deactivate_admin_source(
    source_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    sources = _load_admin_sources_raw()
    index = next((index for index, item in enumerate(sources) if item.get("source_id") == source_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="来源不存在")
    previous = sources[index]
    if previous.get("source_status") == "inactive":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="来源已停用")
    admin_asset_version_store.ensure_initial_version(
        asset_type="source",
        asset_id=source_id,
        payload=previous,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
    )
    source = {**previous, "source_status": "inactive", "superseded_by": ""}
    next_sources = list(sources)
    next_sources[index] = source
    _write_admin_sources(next_sources)
    version = admin_asset_version_store.save_version(
        asset_type="source",
        asset_id=source_id,
        payload=source,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
        change_note="停用来源",
        review_status="approved",
        review_note="来源已从新病例和新知识的可选范围移除",
    )
    enriched = enrich_source_freshness(source)
    _record_admin_audit(
        actor=actor,
        action="source.deactivated",
        resource_type="source",
        resource_id=source_id,
        summary=f"停用来源 {source.get('source_name') or source_id}",
        before=enrich_source_freshness(previous),
        after=enriched,
        metadata={"version": version["version"]},
    )
    return {"source": enriched, "version": version}


@app.get("/api/admin/sources/{source_id}/versions")
def list_admin_source_versions(
    source_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, Any]:
    actor = _require_admin_user(auth_token)
    source = _admin_source_by_id(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="来源不存在")
    admin_asset_version_store.ensure_initial_version(
        asset_type="source",
        asset_id=source_id,
        payload=source,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
    )
    return admin_asset_version_store.list_versions(
        asset_type="source",
        asset_id=source_id,
        limit=limit,
        offset=offset,
    )


@app.get("/api/admin/sources/{source_id}/diff")
def diff_admin_source_versions(
    source_id: str,
    from_version: int = Query(ge=1),
    to_version: int = Query(ge=1),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, Any]:
    _require_admin_user(auth_token)
    diff = admin_asset_version_store.diff_versions(
        asset_type="source",
        asset_id=source_id,
        from_version=from_version,
        to_version=to_version,
    )
    if diff is None:
        raise HTTPException(status_code=404, detail="来源版本不存在")
    return diff


@app.post("/api/admin/sources/{source_id}/rollback")
def rollback_admin_source(
    source_id: str,
    request: AdminAssetRollbackRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    target = admin_asset_version_store.get_version(
        asset_type="source",
        asset_id=source_id,
        version=request.version,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="来源版本不存在")
    sources = _load_admin_sources_raw()
    index = next((index for index, item in enumerate(sources) if item.get("source_id") == source_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="来源不存在")
    previous = sources[index]
    restored = deepcopy(target["payload"])
    next_sources = list(sources)
    next_sources[index] = restored
    _write_admin_sources(next_sources)
    version = admin_asset_version_store.save_version(
        asset_type="source",
        asset_id=source_id,
        payload=restored,
        actor_user_id=actor["user_id"],
        actor_email=actor["email"],
        change_note=request.change_note or f"回滚到版本 {request.version}",
        review_status=str(target.get("review_status") or "unreviewed"),
        review_note=str(target.get("review_note") or ""),
    )
    enriched = enrich_source_freshness(restored)
    _record_admin_audit(
        actor=actor,
        action="source.rolled_back",
        resource_type="source",
        resource_id=source_id,
        summary=f"回滚来源 {source_id} 到版本 {request.version}",
        before=enrich_source_freshness(previous),
        after=enriched,
        metadata={"target_version": request.version, "version": version["version"]},
    )
    return {"source": enriched, "version": version}


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


@app.get("/api/admin/audit-events")
def list_admin_audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default="", max_length=200),
    resource_type: str = Query(default="", max_length=64),
    action: str = Query(default="", max_length=128),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, Any]:
    _require_admin_user(auth_token)
    return admin_audit_store.list_events(
        limit=limit,
        offset=offset,
        query=q,
        resource_type=resource_type,
        action=action,
    )


@app.get("/api/admin/audit-events/export")
def export_admin_audit_events(
    export_format: Literal["json", "csv"] = Query(default="json", alias="format"),
    q: str = Query(default="", max_length=200),
    resource_type: str = Query(default="", max_length=64),
    action: str = Query(default="", max_length=128),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> Response:
    _require_admin_user(auth_token)
    events = admin_audit_store.list_events(
        limit=10_000,
        offset=0,
        query=q,
        resource_type=resource_type,
        action=action,
    )["events"]
    if export_format == "json":
        return Response(
            content=json.dumps(events, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="admin-audit-events.json"'
            },
        )
    output = StringIO()
    fieldnames = [
        "event_id",
        "created_at",
        "actor_email",
        "action",
        "resource_type",
        "resource_id",
        "summary",
        "before",
        "after",
        "metadata",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for event in events:
        writer.writerow(
            {
                field: (
                    json.dumps(event.get(field), ensure_ascii=False)
                    if field in {"before", "after", "metadata"}
                    else _csv_safe_cell(event.get(field))
                )
                for field in fieldnames
            }
        )
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="admin-audit-events.csv"'
        },
    )


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
    document_id: str = Query(default="", max_length=IDENTIFIER_MAX_CHARS * 4),
    q: str = Query(default="", max_length=200),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    items = [
        enrich_rag_knowledge_item(item)
        for item in rag_knowledge_store.list_items(
            scope=scope.strip(),
            case_id=case_id.strip(),
            visibility=visibility.strip(),
        )
        if not document_id.strip()
        or str(item.get("document_id") or "").strip() == document_id.strip()
    ]
    return _build_paginated_admin_payload(
        "knowledge_items",
        items,
        limit,
        offset,
        q,
    )


@app.get("/api/admin/rag/documents")
def list_admin_rag_documents(
    case_id: str = Query(default=""),
    scope: str = Query(default=""),
    q: str = Query(default="", max_length=200),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    normalized_scope = scope.strip()
    if normalized_scope and normalized_scope not in {"global", "case"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unsupported document scope")
    return _build_paginated_admin_payload(
        "documents",
        [
            enrich_rag_document(document)
            for document in rag_knowledge_store.list_documents(scope=normalized_scope, case_id=case_id.strip())
        ],
        limit,
        offset,
        q,
    )


@app.post("/api/admin/rag/documents")
def upload_admin_rag_document(
    request: AdminRagDocumentUploadRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    reviewer = _require_admin_user(auth_token)
    document_id, items = _build_admin_rag_document_items(request)
    previous_items = rag_knowledge_store.list_document_items(document_id)
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
    enriched_document = enrich_rag_document(document)
    _record_admin_audit(
        actor=reviewer,
        action="rag_document.uploaded",
        resource_type="rag_document",
        resource_id=document_id,
        summary=f"上传知识文档 {request.file_name}",
        before=[enrich_rag_knowledge_item(item) for item in previous_items] or None,
        after=enriched_document,
        metadata={"chunk_count": len(saved_items), "replaced_existing": bool(previous_items)},
    )
    return {
        "document": enriched_document,
        "knowledge_items": [enrich_rag_knowledge_item(item) for item in saved_items],
    }


@app.patch("/api/admin/rag/documents/{document_id:path}/enabled")
def set_admin_rag_document_enabled(
    document_id: str,
    request: AdminRagDocumentEnabledRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    reviewer = _require_admin_user(auth_token)
    previous = next(
        (
            document
            for document in rag_knowledge_store.list_documents()
            if document.get("document_id") == document_id
        ),
        None,
    )
    document = rag_knowledge_store.set_document_enabled(
        document_id,
        enabled=request.enabled,
        updated_by=reviewer["email"],
    )
    if document is None:
        raise HTTPException(status_code=404, detail="rag document not found")
    _clear_retrieval_documents_cache()
    enriched = enrich_rag_document(document)
    _record_admin_audit(
        actor=reviewer,
        action="rag_document.enabled" if request.enabled else "rag_document.disabled",
        resource_type="rag_document",
        resource_id=document_id,
        summary=f"{'启用' if request.enabled else '停用'}知识文档 {document_id}",
        before=enrich_rag_document(previous) if previous else None,
        after=enriched,
    )
    return {"document": enriched}


@app.patch("/api/admin/rag/documents/{document_id:path}/review")
def review_admin_rag_document(
    document_id: str,
    request: AdminRagKnowledgeReviewRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    reviewer = _require_admin_user(auth_token)
    items = rag_knowledge_store.list_document_items(document_id)
    if not items:
        raise HTTPException(status_code=404, detail="rag document not found")
    pending_items = [item for item in items if item.get("review_status") == "pending_review"]
    if request.decision == "approved":
        for item in pending_items:
            _validate_rag_knowledge_approval(item)
    document = rag_knowledge_store.set_document_review_status(
        document_id,
        review_status=request.decision,
        review_note=request.note,
        reviewed_by=reviewer["email"],
        pending_only=True,
    )
    if document is None:
        raise HTTPException(status_code=404, detail="rag document not found")
    _clear_retrieval_documents_cache()
    enriched_items = [
            enrich_rag_knowledge_item(item)
            for item in rag_knowledge_store.list_document_items(document_id)
        ]
    enriched_document = enrich_rag_document(document)
    _record_admin_audit(
        actor=reviewer,
        action=f"rag_document.{request.decision}",
        resource_type="rag_document",
        resource_id=document_id,
        summary=f"批量{request.decision}知识文档 {document_id} 的待审片段",
        before=[enrich_rag_knowledge_item(item) for item in items],
        after=enriched_items,
        metadata={"review_note": request.note},
    )
    return {"document": enriched_document, "knowledge_items": enriched_items}


@app.post("/api/admin/rag/knowledge")
def upsert_admin_rag_knowledge_item(
    request: AdminRagKnowledgeItemRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    reviewer = _require_admin_user(auth_token)
    item = _build_admin_rag_knowledge_item(request)
    previous_item = rag_knowledge_store.get_item(item["knowledge_id"])
    saved_item = rag_knowledge_store.upsert_item(item, updated_by=reviewer["email"])
    _clear_retrieval_documents_cache()
    response: dict[str, object] = {"knowledge_item": enrich_rag_knowledge_item(saved_item)}
    document_id = str(saved_item.get("document_id", "")).strip()
    if document_id:
        documents = rag_knowledge_store.list_documents()
        document = next((item for item in documents if item["document_id"] == document_id), None)
        if document is not None:
            response["document"] = enrich_rag_document(document)
    _record_admin_audit(
        actor=reviewer,
        action="rag_knowledge.updated" if previous_item else "rag_knowledge.created",
        resource_type="rag_knowledge",
        resource_id=str(saved_item["knowledge_id"]),
        summary=f"{'更新' if previous_item else '创建'}知识片段 {saved_item.get('title') or saved_item['knowledge_id']}",
        before=enrich_rag_knowledge_item(previous_item) if previous_item else None,
        after=response["knowledge_item"],
    )
    return response


@app.patch("/api/admin/rag/knowledge/{knowledge_id:path}/review")
def review_admin_rag_knowledge_item(
    knowledge_id: str,
    request: AdminRagKnowledgeReviewRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    reviewer = _require_admin_user(auth_token)
    item = rag_knowledge_store.get_item(knowledge_id)
    if item is None:
        raise HTTPException(status_code=404, detail="knowledge item not found")
    if request.decision == "approved":
        _validate_rag_knowledge_approval(item)
    saved_item = rag_knowledge_store.set_item_review_status(
        knowledge_id,
        review_status=request.decision,
        review_note=request.note,
        reviewed_by=reviewer["email"],
    )
    if saved_item is None:
        raise HTTPException(status_code=404, detail="knowledge item not found")
    _clear_retrieval_documents_cache()
    response: dict[str, object] = {"knowledge_item": enrich_rag_knowledge_item(saved_item)}
    document_id = str(saved_item.get("document_id", "")).strip()
    if document_id:
        documents = rag_knowledge_store.list_documents()
        document = next((entry for entry in documents if entry["document_id"] == document_id), None)
        if document is not None:
            response["document"] = enrich_rag_document(document)
    _record_admin_audit(
        actor=reviewer,
        action=f"rag_knowledge.{request.decision}",
        resource_type="rag_knowledge",
        resource_id=knowledge_id,
        summary=f"{request.decision}知识片段 {item.get('title') or knowledge_id}",
        before=enrich_rag_knowledge_item(item),
        after=response["knowledge_item"],
        metadata={"review_note": request.note},
    )
    return response


def _validate_rag_knowledge_approval(item: dict[str, Any]) -> None:
    review_status = str(item.get("review_status", "")).strip()
    if review_status and review_status not in RAG_KNOWLEDGE_REVIEW_STATUSES:
        raise HTTPException(status_code=409, detail="knowledge item has an invalid review status")
    blocking_flags = {"diagnosis_answer_content", "treatment_or_dose_content"}.intersection(
        str(flag) for flag in item.get("risk_flags", [])
    )
    allowed_agents = {str(agent) for agent in item.get("allowed_agents", [])}
    if (
        blocking_flags
        and str(item.get("visibility", "")) == "pre_submit_safe"
        and allowed_agents.intersection(RAG_GENERATIVE_AGENT_ROLES)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "pre-submit generative knowledge contains diagnosis or treatment content; "
                "change visibility to post_submit_review or remove the risky content before approval"
            ),
        )


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


@app.delete("/api/admin/rag/documents/{document_id:path}")
def delete_admin_rag_document(
    document_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    items = rag_knowledge_store.list_document_items(document_id)
    if not items:
        raise HTTPException(status_code=404, detail="rag document not found")
    deleted_count = rag_knowledge_store.delete_document(document_id)
    _clear_retrieval_documents_cache()
    _record_admin_audit(
        actor=actor,
        action="rag_document.deleted",
        resource_type="rag_document",
        resource_id=document_id,
        summary=f"删除知识文档 {document_id} 及其 {deleted_count} 个片段",
        before=[enrich_rag_knowledge_item(item) for item in items],
        metadata={"deleted_chunk_count": deleted_count},
    )
    return {"document_id": document_id, "deleted": True, "deleted_chunk_count": deleted_count}


@app.delete("/api/admin/rag/knowledge/{knowledge_id:path}")
def delete_admin_rag_knowledge_item(
    knowledge_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    item = rag_knowledge_store.get_item(knowledge_id)
    deleted = rag_knowledge_store.delete_item(knowledge_id)
    if deleted:
        _clear_retrieval_documents_cache()
        _record_admin_audit(
            actor=actor,
            action="rag_knowledge.deleted",
            resource_type="rag_knowledge",
            resource_id=knowledge_id,
            summary=f"删除知识片段 {item.get('title') if item else knowledge_id}",
            before=enrich_rag_knowledge_item(item) if item else None,
        )
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
    before = training_skill_auto_approval_settings_store.get_settings()
    settings = training_skill_auto_approval_settings_store.update_settings(
        auto_apply_enabled=request.auto_apply_enabled,
        updated_by=reviewer["email"],
    )
    _record_admin_audit(
        actor=reviewer,
        action="skill.auto_apply_enabled" if settings["auto_apply_enabled"] else "skill.auto_apply_disabled",
        resource_type="skill_settings",
        resource_id="auto_approval",
        summary="开启 Skill 自动应用" if settings["auto_apply_enabled"] else "关闭 Skill 自动应用",
        before=before,
        after=settings,
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
        candidate = training_skill_approval_agent.review_candidate(candidate)
        review = training_skill_regression_gate.review_candidate(candidate, batch_result)
        _set_approval_agent_decision(
            candidate,
            review,
            auto_apply_enabled=auto_apply_enabled,
        )
        if auto_apply_enabled and review["status"] == "ready_for_review":
            review = {
                **review,
                "status": "approved",
                "reviewer_id": AUTO_APPROVAL_AGENT_ID,
                "approval_mode": "auto_agent",
            }
        if not training_skill_candidate_store.save_candidate_unless_reviewed(candidate, review):
            continue
        if candidate["approval_agent_review"]["revision_status"] == "modified":
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

    response = {
        "generated_count": len(candidates),
        "saved_count": len(saved_candidate_summaries),
        "ready_for_review_count": ready_for_review_count,
        "blocked_by_regression_count": blocked_by_regression_count,
        "auto_apply_enabled": auto_apply_enabled,
        "auto_approved_count": auto_approved_count,
        "approval_agent_modified_count": approval_agent_modified_count,
        "candidates": saved_candidate_summaries,
    }
    _record_admin_audit(
        actor=reviewer,
        action="skill.candidates_generated",
        resource_type="skill_candidate_batch",
        resource_id=ADMIN_SKILL_CANDIDATE_GENERATION_BATCH_ID,
        summary=f"生成候选 Skill：保存 {len(saved_candidate_summaries)} 个",
        after={
            key: value
            for key, value in response.items()
            if key != "candidates"
        },
    )
    return response


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
    before = training_skill_candidate_store.get_candidate(request.candidate_id)
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
    _record_admin_audit(
        actor=reviewer,
        action="skill.candidate_approved",
        resource_type="skill_candidate",
        resource_id=request.candidate_id,
        summary=f"批准并启用候选 Skill：{candidate.get('title') or request.candidate_id}",
        before=before,
        after=training_skill_candidate_store.get_candidate(request.candidate_id),
        metadata={"skill_id": skill_id},
    )
    return {"candidate_id": request.candidate_id, "status": "approved", "skill_id": skill_id}


@app.post("/api/admin/evolution/reject")
def reject_admin_training_skill_candidate(
    request: AdminTrainingSkillReviewRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, str]:
    reviewer = _require_admin_user(auth_token)
    before = training_skill_candidate_store.get_candidate(request.candidate_id)
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
    _record_admin_audit(
        actor=reviewer,
        action="skill.candidate_rejected",
        resource_type="skill_candidate",
        resource_id=request.candidate_id,
        summary=f"拒绝候选 Skill：{candidate.get('title') or request.candidate_id}",
        before=before,
        after=training_skill_candidate_store.get_candidate(request.candidate_id),
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
    classroom_id: str = Query(default="", max_length=IDENTIFIER_MAX_CHARS),
    limit: int | None = Query(default=None, ge=1),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    classroom = None
    classroom_student_ids: set[str] | None = None
    if classroom_id:
        classroom = classroom_store.get_classroom(classroom_id)
        if classroom is None:
            raise HTTPException(status_code=404, detail="班级不存在")
        classroom_student_ids = {
            user_id
            for user_id in _eligible_classroom_member_user_ids(classroom)
        }
    session_ids = _real_training_session_ids()
    analytics = AdminLearningAnalyticsService(
        session_store=osce_session_service.session_store,
        report_store=osce_session_service.report_store,
    ).summarize(
        session_ids=session_ids,
        case_id=case_id,
        student_id=student_id,
        student_ids=classroom_student_ids,
        cohort_scope=(
            f"classroom:{classroom_id}" if classroom is not None else "all_users"
        ),
        cohort_scope_label=(
            str(classroom["name"]) if classroom is not None else "全用户"
        ),
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


@app.get("/api/admin/evaluation-config")
def get_admin_evaluation_config(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    _ensure_admin_evaluation_config_defaults()
    return {
        "evaluation_cases": admin_evaluation_config_store.list_cases(),
        "suites": admin_evaluation_config_store.list_suites(),
        "schedule": admin_evaluation_config_store.get_schedule(
            ADMIN_DEFAULT_EVALUATION_SUITE_ID
        ),
    }


@app.put("/api/admin/evaluation-cases/{case_key}")
def upsert_admin_evaluation_case(
    case_key: str,
    request: AdminEvaluationCaseUpsertRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    if case_key != request.case_key:
        raise HTTPException(status_code=400, detail="case key does not match request path")
    if request.case_id not in {
        str(case_item.get("case_id")) for case_item in osce_session_service.list_cases()
    }:
        raise HTTPException(status_code=404, detail="training case not found")
    _ensure_admin_evaluation_config_defaults()
    before = admin_evaluation_config_store.get_case(case_key)
    saved_case = admin_evaluation_config_store.upsert_case(
        request.model_dump(),
        updated_by=actor["email"],
    )
    _record_admin_audit(
        actor=actor,
        action="evaluation_case.updated" if before else "evaluation_case.created",
        resource_type="evaluation_case",
        resource_id=case_key,
        summary=f"{'更新' if before else '创建'}评测场景：{saved_case['label']}",
        before=before,
        after=saved_case,
    )
    return {"evaluation_case": saved_case}


@app.delete("/api/admin/evaluation-cases/{case_key}")
def delete_admin_evaluation_case(
    case_key: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    _ensure_admin_evaluation_config_defaults()
    try:
        deleted_case = admin_evaluation_config_store.delete_case(case_key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if deleted_case is None:
        raise HTTPException(status_code=404, detail="evaluation case not found")
    _record_admin_audit(
        actor=actor,
        action="evaluation_case.deleted",
        resource_type="evaluation_case",
        resource_id=case_key,
        summary=f"删除评测场景：{deleted_case.get('label') or case_key}",
        before=deleted_case,
    )
    return {"deleted": True, "case_key": case_key}


@app.put("/api/admin/evaluation-suites/{suite_id}")
def upsert_admin_evaluation_suite(
    suite_id: str,
    request: AdminEvaluationSuiteUpsertRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    if suite_id != request.suite_id:
        raise HTTPException(status_code=400, detail="suite id does not match request path")
    _ensure_admin_evaluation_config_defaults()
    before = admin_evaluation_config_store.get_suite(suite_id)
    try:
        saved_suite = admin_evaluation_config_store.upsert_suite(
            request.model_dump(),
            updated_by=actor["email"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _record_admin_audit(
        actor=actor,
        action="evaluation_suite.updated" if before else "evaluation_suite.created",
        resource_type="evaluation_suite",
        resource_id=suite_id,
        summary=f"{'更新' if before else '创建'}评测套件：{saved_suite['label']}",
        before=before,
        after=saved_suite,
    )
    return {"suite": saved_suite}


@app.delete("/api/admin/evaluation-suites/{suite_id}")
def delete_admin_evaluation_suite(
    suite_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    _ensure_admin_evaluation_config_defaults()
    try:
        deleted_suite = admin_evaluation_config_store.delete_suite(suite_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if deleted_suite is None:
        raise HTTPException(status_code=404, detail="evaluation suite not found")
    _record_admin_audit(
        actor=actor,
        action="evaluation_suite.deleted",
        resource_type="evaluation_suite",
        resource_id=suite_id,
        summary=f"删除评测套件：{deleted_suite.get('label') or suite_id}",
        before=deleted_suite,
    )
    return {"deleted": True, "suite_id": suite_id}


@app.patch("/api/admin/evaluation-schedule")
def update_admin_evaluation_schedule(
    request: AdminEvaluationScheduleUpdateRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    actor = _require_admin_user(auth_token)
    _ensure_admin_evaluation_config_defaults()
    before = admin_evaluation_config_store.get_schedule(
        ADMIN_DEFAULT_EVALUATION_SUITE_ID
    )
    try:
        schedule = admin_evaluation_config_store.update_schedule(
            request.model_dump(),
            updated_by=actor["email"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _record_admin_audit(
        actor=actor,
        action="evaluation_schedule.enabled" if schedule["enabled"] else "evaluation_schedule.disabled",
        resource_type="evaluation_schedule",
        resource_id="default",
        summary=(
            f"启用定时评测：每 {schedule['interval_minutes']} 分钟运行 {schedule['suite_id']}"
            if schedule["enabled"]
            else "停用定时评测"
        ),
        before=before,
        after=schedule,
    )
    return {"schedule": schedule}


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
    actor = _require_admin_user(auth_token)
    try:
        batch_result, suite = _run_admin_evaluation_suite(request.suite_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    evaluation_result_store.save_batch_result(
        request.batch_id,
        batch_result,
        metadata={
            "suite_id": request.suite_id,
            "suite_label": str(suite.get("label") or request.suite_id),
            "thresholds": suite.get("thresholds", {}),
            "triggered_by": actor["email"],
            "created_at": created_at,
        },
    )
    evaluation = evaluation_result_store.get_batch_result(request.batch_id)
    _record_admin_audit(
        actor=actor,
        action="evaluation.run",
        resource_type="evaluation",
        resource_id=request.batch_id,
        summary=f"运行评测套件：{suite.get('label') or request.suite_id}",
        after={
            "batch_id": request.batch_id,
            "suite_id": request.suite_id,
            "passed": batch_result.passed,
            "passed_cases": batch_result.passed_cases,
            "total_cases": batch_result.total_cases,
        },
    )
    return {"evaluation": evaluation}


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
        _list_enriched_admin_reports(),
        limit,
        offset,
        q,
    )


def _list_enriched_admin_reports() -> list[dict[str, Any]]:
    return [
        enrich_report(report)
        for report in osce_session_service.report_store.list_reports()
        if not _is_deleted_admin_session(report.get("session_id"))
    ]


@app.get("/api/admin/reports/export")
def export_admin_reports(
    export_format: Literal["json", "csv"] = Query(default="json", alias="format"),
    q: str = Query(default="", max_length=200),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> Response:
    _require_admin_user(auth_token)
    reports = _filter_admin_items(_list_enriched_admin_reports(), q)
    if export_format == "json":
        return Response(
            content=json.dumps(reports, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="admin-reports.json"'},
        )
    output = StringIO()
    fieldnames = [
        "report_id",
        "session_id",
        "student_id",
        "case_id",
        "case_title",
        "total_score",
        "missed_item_labels",
        "generation_warnings",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for report in reports:
        writer.writerow(
            {
                field: (
                    json.dumps(report.get(field), ensure_ascii=False)
                    if field in {"missed_item_labels", "generation_warnings"}
                    else _csv_safe_cell(report.get(field))
                )
                for field in fieldnames
            }
        )
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="admin-reports.csv"'},
    )


@app.get("/api/admin/reports/{report_id}")
def get_admin_report(
    report_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    report = next(
        (
            item
            for item in _list_enriched_admin_reports()
            if str(item.get("report_id") or "") == report_id
            or str(item.get("session_id") or "") == report_id
        ),
        None,
    )
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return {"report": report}


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
            _run_report_enrichment_background_task,
            session_id,
            str(session_payload["student_id"]),
        )
    return report
