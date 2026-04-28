from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.services.osce_session_service import osce_session_service

app = FastAPI(
    title="Clinical OSCE Agent API",
    version="0.1.0",
    description="Backend scaffold for the Clinical Reasoning OSCE Agent.",
)


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


@app.post("/api/sessions")
def create_session(request: CreateSessionRequest) -> dict[str, object]:
    return osce_session_service.create_session(
        case_id=request.case_id,
        student_id=request.student_id,
    )


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, object]:
    session = osce_session_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/api/sessions/{session_id}/message")
def send_message(session_id: str, request: MessageRequest) -> dict[str, object]:
    session = osce_session_service.handle_message(session_id, request.message)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/api/sessions/{session_id}/physical-exam")
def request_physical_exam(session_id: str, request: PhysicalExamRequest) -> dict[str, object]:
    session = osce_session_service.request_physical_exam(session_id, request.exam_code)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/api/sessions/{session_id}/auxiliary-test")
def request_auxiliary_test(session_id: str, request: AuxiliaryTestRequest) -> dict[str, object]:
    session = osce_session_service.request_auxiliary_test(session_id, request.test_code)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/api/sessions/{session_id}/hypotheses")
def record_hypothesis(session_id: str, request: HypothesisRequest) -> dict[str, object]:
    session = osce_session_service.record_hypothesis(session_id, request.hypothesis)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/api/sessions/{session_id}/hint")
def request_hint(session_id: str) -> dict[str, object]:
    session = osce_session_service.request_hint(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/api/sessions/{session_id}/submit-diagnosis")
def submit_diagnosis(session_id: str, request: SubmitDiagnosisRequest) -> dict[str, object]:
    session = osce_session_service.submit_diagnosis(
        session_id=session_id,
        diagnosis=request.diagnosis,
        reasoning=request.reasoning,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.get("/api/sessions/{session_id}/report")
def get_session_report(session_id: str) -> dict[str, object]:
    report = osce_session_service.get_report(session_id)
    if report is None:
        raise HTTPException(status_code=404, detail="session not found")
    return report
