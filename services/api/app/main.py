import json
import os
from copy import deepcopy
from typing import Any

import yaml
from fastapi import Cookie, FastAPI, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.graph.osce_graph import build_osce_graph
from app.services import retrieval_index, source_retriever
from app.services.auth_store import auth_store
from app.services.evaluation_result_store import evaluation_result_store
from app.services.evaluation_runner import EvaluationBatchResult, EvaluationCase, EvaluationStep, run_evaluation_cases
from app.services.model_config_service import build_admin_model_config
from app.services.osce_session_service import CASES_DIR, OsceSessionService, osce_session_service
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.rule_evaluator import RUBRICS_DIR
from app.services.student_model_config_service import test_student_model_config_connectivity
from app.services.training_insight_service import TrainingInsightService
from app.services.training_skill_candidate_service import training_skill_candidate_service
from app.services.training_skill_candidate_store import training_skill_candidate_store
from app.services.training_skill_effect_service import TrainingSkillEffectService
from app.services.training_skill_regression_gate import training_skill_regression_gate
from app.validators.case_validator import validate_case, validate_case_rubric_pair, validate_rubric

AUTH_COOKIE_NAME = "clinical_osce_auth"
AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
ADMIN_EMAILS_ENV_NAME = "CLINICAL_OSCE_ADMIN_EMAILS"
DEMO_ADMIN_ENABLED_ENV_NAME = "CLINICAL_OSCE_DEMO_ADMIN_ENABLED"
DEMO_ADMIN_EMAIL_ENV_NAME = "CLINICAL_OSCE_DEMO_ADMIN_EMAIL"
DEMO_ADMIN_PASSWORD_ENV_NAME = "CLINICAL_OSCE_DEMO_ADMIN_PASSWORD"
DEFAULT_DEMO_ADMIN_EMAIL = "admin-demo@example.test"
DEFAULT_DEMO_ADMIN_PASSWORD = "safe-admin-password"
DEFAULT_DEMO_ADMIN_DISPLAY_NAME = "演示管理员"
ADMIN_SKILL_CANDIDATE_REVIEW_EVENT_TYPES = {
    "admin_skill_candidate_approved",
    "admin_skill_candidate_generated",
    "admin_skill_candidate_rejected",
}
ADMIN_SKILL_CANDIDATE_GENERATION_BATCH_ID = "admin_skill_candidate_generation_smoke"
ADMIN_EVALUATION_STUDENT_ID_PREFIX = "admin_eval_"
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
        expected_total_score=32,
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
        graph=build_osce_graph(patient_responder=_canonical_admin_patient_responder),
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


PROFILE_DIMENSION_LABELS: dict[str, str] = {
    "history_taking": "问诊",
    "physical_exam": "查体",
    "auxiliary_test": "辅助检查",
    "main_diagnosis": "主诊断",
    "differential_diagnosis": "鉴别诊断",
    "reasoning": "推理链",
}

app = FastAPI(
    title="Clinical OSCE Agent API",
    version="0.1.0",
    description="Backend scaffold for the Clinical Reasoning OSCE Agent.",
)


class AuthRegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class CreateSessionRequest(BaseModel):
    case_id: str
    student_id: str = "anonymous"


class MessageRequest(BaseModel):
    message: str


class PhysicalExamRequest(BaseModel):
    exam_code: str


class AuxiliaryTestRequest(BaseModel):
    test_code: str


class SubmitDiagnosisRequest(BaseModel):
    diagnosis: str
    reasoning: str


class HypothesisRequest(BaseModel):
    hypothesis: str


class StudentModelConfigTestRequest(BaseModel):
    provider: str
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    proxy_url: str = ""


class AdminTrainingSkillReviewRequest(BaseModel):
    candidate_id: str


class AdminCaseValidationRequest(BaseModel):
    case: dict[str, Any]
    rubric: dict[str, Any] | None = None


class AdminCaseImportRequest(BaseModel):
    case: dict[str, Any]
    rubric: dict[str, Any]


class AdminCaseFieldUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_title: str | None = None
    course_module: str | None = None
    difficulty: str | None = None
    chief_complaint: str | None = None
    safety_notes: str | None = None


class AdminRubricItemUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(..., min_length=1)


class AdminEvaluationRunRequest(BaseModel):
    batch_id: str


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
        max_age=AUTH_COOKIE_MAX_AGE_SECONDS,
        path="/",
    )


def _require_current_user(auth_token: str | None) -> dict[str, str]:
    if not auth_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    user = auth_store.get_user_by_session_token(auth_token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    return user


def _get_admin_email_set() -> set[str]:
    admin_emails = {
        email.strip().lower()
        for email in os.environ.get(ADMIN_EMAILS_ENV_NAME, "").split(",")
        if email.strip()
    }
    if _is_demo_admin_enabled():
        admin_emails.add(_get_demo_admin_email())
    return admin_emails


def _is_demo_admin_enabled() -> bool:
    return os.environ.get(DEMO_ADMIN_ENABLED_ENV_NAME, "true").strip().lower() not in {"0", "false", "no", "off"}


def _get_demo_admin_email() -> str:
    return os.environ.get(DEMO_ADMIN_EMAIL_ENV_NAME, DEFAULT_DEMO_ADMIN_EMAIL).strip().lower()


def _get_demo_admin_password() -> str:
    return os.environ.get(DEMO_ADMIN_PASSWORD_ENV_NAME, DEFAULT_DEMO_ADMIN_PASSWORD)


def _matches_demo_admin_credentials(email: str, password: str) -> bool:
    return _is_demo_admin_enabled() and email.strip().lower() == _get_demo_admin_email() and password == _get_demo_admin_password()


def _ensure_demo_admin_user(email: str, password: str) -> dict[str, str]:
    return auth_store.upsert_user_password(email=email, password=password, display_name=DEFAULT_DEMO_ADMIN_DISPLAY_NAME)


def _require_admin_user(auth_token: str | None) -> dict[str, str]:
    user = _require_current_user(auth_token)
    if user["email"].lower() not in _get_admin_email_set():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin access required")
    return user


def _require_owned_session(session_id: str, auth_token: str | None) -> dict[str, object]:
    user = _require_current_user(auth_token)
    session = osce_session_service.get_session(session_id)
    if session is None or session.get("student_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="session not found")
    return session


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
    review = candidate["review"]
    return {
        "candidate_id": candidate["candidate_id"],
        "trigger_item_id": candidate["trigger_item_id"],
        "title": candidate["title"],
        "status": review["status"],
        "regression_passed": review["regression_passed"],
        "source_report_count": candidate["source_report_count"],
        "support_count": candidate["support_count"],
    }


def _list_admin_skill_candidate_review_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for candidate in training_skill_candidate_store.list_candidate_summaries():
        events.extend(
            event
            for event in osce_session_service.training_event_store.list_session_events(str(candidate["candidate_id"]))
            if event["event_type"] in ADMIN_SKILL_CANDIDATE_REVIEW_EVENT_TYPES
        )
    return sorted(events, key=lambda event: str(event["created_at"]), reverse=True)


def _get_average_score(reports: list[dict[str, Any]]) -> int:
    if not reports:
        return 0
    return round(sum(int(report["total_score"]) for report in reports) / len(reports))


def _get_dimension_averages(reports: list[dict[str, Any]]) -> list[dict[str, object]]:
    dimension_totals: dict[str, dict[str, int]] = {}
    for report in reports:
        for key, score in dict(report.get("dimension_scores", {})).items():
            current = dimension_totals.setdefault(str(key), {"count": 0, "total": 0})
            current["count"] += 1
            current["total"] += int(score)

    return sorted(
        [
            {
                "key": key,
                "label": PROFILE_DIMENSION_LABELS.get(key, key),
                "average": round(value["total"] / value["count"]),
            }
            for key, value in dimension_totals.items()
        ],
        key=lambda item: int(item["average"]),
        reverse=True,
    )


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


def _get_enabled_skill_summaries() -> list[dict[str, object]]:
    return [
        {
            "skill_id": skill["skill_id"],
            "title": skill["title"],
            "trigger_item_id": skill["trigger_item_id"],
            "suggested_strategy": skill["suggested_strategy"],
            "support_count": skill["support_count"],
        }
        for skill in osce_session_service.training_skill_store.list_enabled_skills()
    ]


def _get_applied_skill_count(user_id: str, sessions: list[dict[str, object]]) -> int:
    return sum(
        1
        for session in sessions
        for event in osce_session_service.training_event_store.list_session_events(str(session["session_id"]))
        if event["student_id"] == user_id and event["event_type"] == "training_skill_applied"
    )


def _build_skill_accumulation(user_id: str, sessions: list[dict[str, object]]) -> dict[str, object]:
    enabled_skills = _get_enabled_skill_summaries()
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


def _build_learning_profile(user: dict[str, str]) -> dict[str, object]:
    sessions = osce_session_service.session_store.list_user_session_summaries(user["user_id"])
    reports = [
        report
        for session in sessions
        if (report := osce_session_service.report_store.get_report(str(session["session_id"]))) is not None
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
        "recent_sessions": sessions[:5],
        "skill_accumulation": _build_skill_accumulation(user["user_id"], sessions),
    }


@app.post("/api/auth/register")
def register(request: AuthRegisterRequest, response: Response) -> dict[str, object]:
    _validate_auth_request(request.email, request.password)
    user = auth_store.create_user(
        email=request.email,
        password=request.password,
        display_name=request.display_name,
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")
    _set_auth_cookie(response, auth_store.create_session(user["user_id"]))
    return {"user": user}


@app.post("/api/auth/login")
def login(request: AuthLoginRequest, response: Response) -> dict[str, object]:
    _validate_auth_request(request.email, request.password)
    user = auth_store.authenticate_user(request.email, request.password)
    if user is None and _matches_demo_admin_credentials(request.email, request.password):
        user = _ensure_demo_admin_user(request.email, request.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    _set_auth_cookie(response, auth_store.create_session(user["user_id"]))
    return {"user": user}


@app.post("/api/auth/logout")
def logout(response: Response, auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME)) -> dict[str, str]:
    if auth_token:
        auth_store.revoke_session(auth_token)
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")
    return {"status": "ok"}


@app.get("/api/auth/me")
def get_current_user(auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME)) -> dict[str, object]:
    return {"user": _require_current_user(auth_token)}


@app.get("/")
def read_root() -> dict[str, str]:
    return {
        "name": "clinical-osce-agent",
        "message": "OSCE backend scaffold is running.",
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/model-config/test")
def test_model_config(request: StudentModelConfigTestRequest) -> dict[str, object]:
    try:
        return test_student_model_config_connectivity(
            {
                "provider": request.provider,
                "api_key": request.api_key,
                "model": request.model,
                "base_url": request.base_url,
                "proxy_url": request.proxy_url,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/model-config/runtime")
def apply_model_config_runtime(request: StudentModelConfigTestRequest) -> dict[str, object]:
    try:
        runtime_config = runtime_model_config_store.apply_config(
            {
                "provider": request.provider,
                "api_key": request.api_key,
                "model": request.model,
                "base_url": request.base_url,
                "proxy_url": request.proxy_url,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return runtime_config.public_payload()


@app.get("/api/model-config/runtime")
def get_model_config_runtime() -> dict[str, object]:
    return runtime_model_config_store.public_status()


@app.get("/api/cases")
def list_cases() -> dict[str, object]:
    return {"cases": osce_session_service.list_cases()}


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


@app.get("/api/admin/model-config")
def get_admin_model_config(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return build_admin_model_config()


@app.get("/api/admin/evolution/candidates")
def list_admin_training_skill_candidates(
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default=""),
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    return _build_paginated_admin_payload(
        "candidates",
        training_skill_candidate_store.list_candidate_summaries(),
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


@app.post("/api/admin/evolution/candidates/generate")
def generate_admin_training_skill_candidates(
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    reviewer = _require_admin_user(auth_token)
    session_ids = _real_training_session_ids()
    insights = TrainingInsightService(osce_session_service.training_event_store).summarize_sessions(session_ids)
    candidates = training_skill_candidate_service.propose_candidates(insights, min_count=2)
    batch_result = _run_admin_evaluation_cases()
    evaluation_result_store.save_batch_result(ADMIN_SKILL_CANDIDATE_GENERATION_BATCH_ID, batch_result)
    saved_candidate_summaries: list[dict[str, object]] = []
    ready_for_review_count = 0
    blocked_by_regression_count = 0

    for candidate in candidates:
        review = training_skill_regression_gate.review_candidate(candidate, batch_result)
        if not training_skill_candidate_store.save_candidate_unless_reviewed(candidate, review):
            continue
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

    return {
        "generated_count": len(candidates),
        "saved_count": len(saved_candidate_summaries),
        "ready_for_review_count": ready_for_review_count,
        "blocked_by_regression_count": blocked_by_regression_count,
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
    return {"candidate": candidate}


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


@app.post("/api/admin/evals/run")
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
        osce_session_service.report_store.list_reports(),
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
        osce_session_service.session_store.list_session_summaries(),
        limit,
        offset,
        q,
    )


@app.get("/api/admin/sessions/{session_id}/report")
def get_admin_session_report(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
    report = osce_session_service.report_store.get_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return {"report": report}


@app.get("/api/admin/sessions/{session_id}/events")
def list_admin_session_events(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_admin_user(auth_token)
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
    return _require_owned_session(session_id, auth_token)


@app.delete("/api/me/sessions/{session_id}")
def delete_current_user_session(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, str]:
    _require_owned_session(session_id, auth_token)
    osce_session_service.delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}


@app.get("/api/me/sessions/{session_id}/report")
def get_current_user_session_report(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_owned_session(session_id, auth_token)
    report = osce_session_service.get_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="session not found")
    return report


@app.post("/api/sessions")
def create_session(
    request: CreateSessionRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    user = _require_current_user(auth_token)
    return osce_session_service.create_session(
        case_id=request.case_id,
        student_id=user["user_id"],
    )


@app.get("/api/sessions/{session_id}")
def get_session(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    return _require_owned_session(session_id, auth_token)


@app.post("/api/sessions/{session_id}/message")
def send_message(
    session_id: str,
    request: MessageRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_owned_session(session_id, auth_token)
    session = osce_session_service.handle_message(session_id, request.message)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/api/sessions/{session_id}/physical-exam")
def request_physical_exam(
    session_id: str,
    request: PhysicalExamRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_owned_session(session_id, auth_token)
    session = osce_session_service.request_physical_exam(session_id, request.exam_code)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/api/sessions/{session_id}/auxiliary-test")
def request_auxiliary_test(
    session_id: str,
    request: AuxiliaryTestRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_owned_session(session_id, auth_token)
    session = osce_session_service.request_auxiliary_test(session_id, request.test_code)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/api/sessions/{session_id}/hypotheses")
def record_hypothesis(
    session_id: str,
    request: HypothesisRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_owned_session(session_id, auth_token)
    session = osce_session_service.record_hypothesis(session_id, request.hypothesis)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/api/sessions/{session_id}/hint")
def request_hint(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_owned_session(session_id, auth_token)
    session = osce_session_service.request_hint(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/api/sessions/{session_id}/submit-diagnosis")
def submit_diagnosis(
    session_id: str,
    request: SubmitDiagnosisRequest,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_owned_session(session_id, auth_token)
    session = osce_session_service.submit_diagnosis(
        session_id=session_id,
        diagnosis=request.diagnosis,
        reasoning=request.reasoning,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.get("/api/sessions/{session_id}/report")
def get_session_report(
    session_id: str,
    auth_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> dict[str, object]:
    _require_owned_session(session_id, auth_token)
    report = osce_session_service.get_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="session not found")
    return report
