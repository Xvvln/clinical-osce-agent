from typing import Any

from fastapi import Cookie, FastAPI, HTTPException, Response, status
from pydantic import BaseModel

from app.services.auth_store import auth_store
from app.services.evaluation_result_store import evaluation_result_store
from app.services.osce_session_service import osce_session_service
from app.services.training_insight_service import TrainingInsightService
from app.services.training_skill_candidate_store import training_skill_candidate_store

AUTH_COOKIE_NAME = "clinical_osce_auth"
AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7

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


class AdminTrainingSkillReviewRequest(BaseModel):
    candidate_id: str
    reviewer_id: str = "local-admin"


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


def _require_owned_session(session_id: str, auth_token: str | None) -> dict[str, object]:
    user = _require_current_user(auth_token)
    session = osce_session_service.get_session(session_id)
    if session is None or session.get("student_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="session not found")
    return session


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


@app.get("/api/cases")
def list_cases() -> dict[str, object]:
    return {"cases": osce_session_service.list_cases()}


@app.get("/api/cases/{case_id}/raw")
def get_case_raw(case_id: str) -> dict[str, object]:
    case_payload = osce_session_service.get_case_raw(case_id)
    if case_payload is None:
        raise HTTPException(status_code=404, detail="case not found")
    return {"case": case_payload}


@app.get("/api/admin/evolution/candidates")
def list_admin_training_skill_candidates() -> dict[str, object]:
    return {"candidates": training_skill_candidate_store.list_candidate_summaries()}


@app.get("/api/admin/evolution/candidates/{candidate_id}")
def get_admin_training_skill_candidate(candidate_id: str) -> dict[str, object]:
    candidate = training_skill_candidate_store.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return {"candidate": candidate}


@app.post("/api/admin/evolution/approve")
def approve_admin_training_skill_candidate(request: AdminTrainingSkillReviewRequest) -> dict[str, str]:
    if not training_skill_candidate_store.approve_candidate(request.candidate_id, request.reviewer_id):
        raise HTTPException(status_code=404, detail="candidate not found or not ready for review")
    candidate = training_skill_candidate_store.get_candidate(request.candidate_id)
    if candidate is None or not osce_session_service.training_skill_store.enable_candidate(candidate):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="candidate could not be enabled")
    skill_id = f"skill_{candidate['trigger_item_id']}"
    return {"candidate_id": request.candidate_id, "status": "approved", "skill_id": skill_id}


@app.post("/api/admin/evolution/reject")
def reject_admin_training_skill_candidate(request: AdminTrainingSkillReviewRequest) -> dict[str, str]:
    if not training_skill_candidate_store.reject_candidate(request.candidate_id, request.reviewer_id):
        raise HTTPException(status_code=404, detail="candidate not found or not ready for review")
    return {"candidate_id": request.candidate_id, "status": "rejected"}


@app.get("/api/admin/insights")
def get_admin_training_insights() -> dict[str, object]:
    session_ids = [
        str(session["session_id"])
        for session in osce_session_service.session_store.list_session_summaries()
    ]
    insights = TrainingInsightService(osce_session_service.training_event_store).summarize_sessions(session_ids)
    return {"insights": insights}


@app.get("/api/admin/evaluations")
def list_admin_evaluations() -> dict[str, object]:
    return {"evaluations": evaluation_result_store.list_batch_summaries()}


@app.get("/api/admin/evaluations/{batch_id}")
def get_admin_evaluation(batch_id: str) -> dict[str, object]:
    evaluation = evaluation_result_store.get_batch_result(batch_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="evaluation batch not found")
    return {"evaluation": evaluation}


@app.get("/api/admin/sessions")
def list_admin_sessions() -> dict[str, object]:
    return {"sessions": osce_session_service.session_store.list_session_summaries()}


@app.get("/api/admin/sessions/{session_id}/report")
def get_admin_session_report(session_id: str) -> dict[str, object]:
    report = osce_session_service.report_store.get_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return {"report": report}


@app.get("/api/admin/sessions/{session_id}/events")
def list_admin_session_events(session_id: str) -> dict[str, object]:
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
