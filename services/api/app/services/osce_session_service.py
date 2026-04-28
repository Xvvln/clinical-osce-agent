from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.graph.osce_graph import build_osce_graph
from app.models.case import AuxiliaryTestItem, Case, PhysicalExamItem
from app.services.report_store import ReportStore, report_store
from app.services.training_event_store import TrainingEventStore, training_event_store
from app.services.training_skill_store import TrainingSkillStore, training_skill_store
from app.services.vertex_gemini_scorer import create_default_vertex_gemini_scorer
from app.validators.case_validator import validate_case

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"


@dataclass
class OsceSession:
    session_id: str
    student_id: str
    case_id: str
    stage: str
    messages: list[dict[str, str]] = field(default_factory=list)
    asked_questions: list[str] = field(default_factory=list)
    intent_history: list[str] = field(default_factory=list)
    revealed_facts: list[str] = field(default_factory=list)
    requested_exams: list[str] = field(default_factory=list)
    requested_tests: list[str] = field(default_factory=list)
    student_hypotheses: list[str] = field(default_factory=list)
    final_submission: dict[str, str] | None = None
    rubric_scores: dict[str, Any] = field(default_factory=dict)
    missed_items: list[str] = field(default_factory=list)
    retrieved_sources: list[str] = field(default_factory=list)
    feedback_report: dict[str, Any] | None = None
    safety_flags: list[str] = field(default_factory=list)
    evolution_candidates: list[str] = field(default_factory=list)


class OsceSessionService:
    def __init__(
        self,
        report_store: ReportStore = report_store,
        training_event_store: TrainingEventStore = training_event_store,
        training_skill_store: TrainingSkillStore = training_skill_store,
        graph: Any | None = None,
        patient_responder: Any | None = None,
    ) -> None:
        self._sessions: dict[str, OsceSession] = {}
        self.osce_graph = graph or build_osce_graph(
            llm_scorer=create_default_vertex_gemini_scorer(),
            patient_responder=patient_responder,
        )
        self.report_store = report_store
        self.training_event_store = training_event_store
        self.training_skill_store = training_skill_store

    def list_cases(self) -> list[dict[str, Any]]:
        return [_serialize_case_summary(load_case_node(case_path.stem)) for case_path in sorted(CASES_DIR.glob("*.json"))]

    def get_case_raw(self, case_id: str) -> dict[str, Any] | None:
        case_path = CASES_DIR / f"{case_id}.json"
        if not case_path.exists():
            return None
        case_payload = json.loads(case_path.read_text(encoding="utf-8"))
        validate_case(case_payload)
        return case_payload

    def create_session(self, case_id: str, student_id: str) -> dict[str, Any]:
        graph_state = self.osce_graph.invoke(_initial_graph_state(case_id))
        case = load_case_node(graph_state["case_id"])
        enabled_skills = self.training_skill_store.list_enabled_skills()
        session = OsceSession(
            session_id=str(uuid4()),
            student_id=student_id,
            case_id=graph_state["case_id"],
            stage=graph_state["stage"],
            evolution_candidates=_enabled_skill_prompts(enabled_skills),
        )
        self._sessions[session.session_id] = session
        self._append_event(session, "session_created", {"stage": session.stage})
        for skill in enabled_skills:
            self._append_event(
                session,
                "training_skill_applied",
                {
                    "skill_id": skill["skill_id"],
                    "title": skill["title"],
                    "suggested_strategy": skill["suggested_strategy"],
                },
            )
        return _serialize_session(session, case)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return _serialize_session(session, load_case_node(session.case_id))

    def handle_message(self, session_id: str, message: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, message))
        _apply_graph_state(session, graph_state)
        payload = _serialize_session(session, load_case_node(session.case_id))
        payload["reply"] = graph_state["reply"]
        payload["current_intent"] = graph_state["current_intent"]
        self._append_event(
            session,
            "history_message",
            {"message": message, "current_intent": graph_state["current_intent"], "reply": graph_state["reply"]},
        )
        return payload

    def request_physical_exam(self, session_id: str, exam_code: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, exam_code=exam_code))
        _apply_graph_state(session, graph_state)
        payload = _serialize_session(session, load_case_node(session.case_id))
        payload.update(
            {
                "exam_code": graph_state["exam_code"],
                "exam_name_cn": graph_state["exam_name_cn"],
                "result": graph_state["exam_result"],
            }
        )
        self._append_event(
            session,
            "physical_exam_requested",
            {"exam_code": graph_state["exam_code"], "result": graph_state["exam_result"]},
        )
        return payload

    def request_auxiliary_test(self, session_id: str, test_code: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, test_code=test_code))
        _apply_graph_state(session, graph_state)
        payload = _serialize_session(session, load_case_node(session.case_id))
        payload.update(
            {
                "test_code": graph_state["test_code"],
                "test_name_cn": graph_state["test_name_cn"],
                "result": graph_state["test_result"],
            }
        )
        self._append_event(
            session,
            "auxiliary_test_requested",
            {"test_code": graph_state["test_code"], "result": graph_state["test_result"]},
        )
        return payload

    def record_hypothesis(self, session_id: str, hypothesis: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        session.student_hypotheses.append(hypothesis)
        self._append_event(session, "hypothesis_recorded", {"hypothesis": hypothesis})
        return _serialize_session(session, load_case_node(session.case_id))

    def request_hint(self, session_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, hint_requested=True))
        _apply_graph_state(session, graph_state)
        payload = _serialize_session(session, load_case_node(session.case_id))
        payload["hint"] = graph_state["hint"]
        self._append_event(session, "hint_requested", {"hint": graph_state["hint"]})
        return payload

    def submit_diagnosis(self, session_id: str, diagnosis: str, reasoning: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        graph_state = self.osce_graph.invoke(
            _graph_state_from_session(
                session,
                submitted_diagnosis=diagnosis,
                submitted_reasoning=reasoning,
            )
        )
        _apply_graph_state(session, graph_state)
        self._append_event(session, "diagnosis_submitted", {"diagnosis": diagnosis, "reasoning": reasoning})
        return _serialize_session(session, load_case_node(session.case_id))

    def get_report(self, session_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        stored_report = self.report_store.get_report(session_id)
        if stored_report is not None:
            return stored_report
        if session is None:
            return None
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, report_requested=True))
        _apply_graph_state(session, graph_state)
        if session.feedback_report is not None:
            self.report_store.save_report(session.feedback_report)
            self._append_event(
                session,
                "report_generated",
                {
                    "report_id": session.feedback_report["report_id"],
                    "total_score": session.feedback_report["total_score"],
                    "missed_items": session.feedback_report["missed_items"],
                    "knowledge_recommendations": session.feedback_report["knowledge_recommendations"],
                },
            )
        return session.feedback_report

    def _append_event(self, session: OsceSession, event_type: str, payload: dict[str, Any]) -> None:
        self.training_event_store.append_event(
            session_id=session.session_id,
            case_id=session.case_id,
            student_id=session.student_id,
            event_type=event_type,
            payload=payload,
        )


def load_case_node(case_id: str) -> Case:
    case_path = CASES_DIR / f"{case_id}.json"
    case_payload = json.loads(case_path.read_text(encoding="utf-8"))
    return validate_case(case_payload)


def input_router_node(message: str) -> str:
    normalized = message.lower()
    if any(keyword in normalized for keyword in ["什么时候", "何时", "多久", "开始"]):
        return "ask_onset"
    if any(keyword in normalized for keyword in ["哪里", "位置", "部位"]):
        return "ask_location"
    if any(keyword in normalized for keyword in ["恶心", "吐", "腹泻", "伴随"]):
        return "ask_associated_symptom"
    if any(keyword in normalized for keyword in ["既往", "以前", "手术史"]):
        return "ask_past_medical_history"
    return "unknown_history_intent"


def patient_response_node(case: Case, session: OsceSession, message: str, intent: str) -> str:
    for hidden_fact in case.history.hidden_facts:
        if intent in hidden_fact.trigger_intents:
            if hidden_fact.fact_id not in session.revealed_facts:
                session.revealed_facts.append(hidden_fact.fact_id)
            return hidden_fact.canonical_answer
    return "这个问题我不太确定，或者病例中没有提供相关信息。"


def physical_exam_node(case: Case, session: OsceSession, exam_code: str) -> dict[str, str]:
    session.stage = "physical_exam"
    if exam_code not in session.requested_exams:
        session.requested_exams.append(exam_code)
    for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]:
        if exam.exam_code == exam_code:
            return {
                "exam_code": exam.exam_code,
                "exam_name_cn": exam.exam_name_cn,
                "result": exam.result,
            }
    return {"exam_code": exam_code, "exam_name_cn": "未提供查体", "result": "本病例未提供该查体结果。"}


def auxiliary_test_node(case: Case, session: OsceSession, test_code: str) -> dict[str, str]:
    session.stage = "auxiliary_test"
    if test_code not in session.requested_tests:
        session.requested_tests.append(test_code)
    for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]:
        if test.test_code == test_code:
            return {
                "test_code": test.test_code,
                "test_name_cn": test.test_name_cn,
                "result": test.result,
            }
    return {"test_code": test_code, "test_name_cn": "未提供检查", "result": "本病例未提供该辅助检查结果。"}


def diagnosis_submit_node(session: OsceSession, diagnosis: str, reasoning: str) -> None:
    session.stage = "diagnosis_submission"
    session.final_submission = {"diagnosis": diagnosis, "reasoning": reasoning}
    session.student_hypotheses.append(diagnosis)


def _graph_state_from_session(
    session: OsceSession,
    student_message: str = "",
    exam_code: str = "",
    test_code: str = "",
    submitted_diagnosis: str = "",
    submitted_reasoning: str = "",
    report_requested: bool = False,
    hint_requested: bool = False,
) -> dict[str, Any]:
    case = load_case_node(session.case_id)
    return {
        "session_id": session.session_id,
        "case_id": session.case_id,
        "stage": session.stage,
        "case_title": case.case_title,
        "chief_complaint": case.chief_complaint,
        "student_message": student_message,
        "current_intent": "",
        "reply": "",
        "report_requested": report_requested,
        "hint_requested": hint_requested,
        "hint": "",
        "exam_code": exam_code,
        "exam_name_cn": "",
        "exam_result": "",
        "test_code": test_code,
        "test_name_cn": "",
        "test_result": "",
        "submitted_diagnosis": submitted_diagnosis,
        "submitted_reasoning": submitted_reasoning,
        "messages": session.messages,
        "asked_questions": session.asked_questions,
        "intent_history": session.intent_history,
        "revealed_facts": session.revealed_facts,
        "requested_exams": session.requested_exams,
        "requested_tests": session.requested_tests,
        "student_hypotheses": session.student_hypotheses,
        "final_submission": session.final_submission,
        "rubric_scores": session.rubric_scores,
        "missed_items": session.missed_items,
        "retrieved_sources": session.retrieved_sources,
        "feedback_report": session.feedback_report,
        "safety_flags": session.safety_flags,
        "evolution_candidates": session.evolution_candidates,
    }


def _apply_graph_state(session: OsceSession, graph_state: dict[str, Any]) -> None:
    session.stage = graph_state["stage"]
    session.messages = graph_state["messages"]
    session.asked_questions = graph_state["asked_questions"]
    session.intent_history = graph_state["intent_history"]
    session.revealed_facts = graph_state["revealed_facts"]
    session.requested_exams = graph_state["requested_exams"]
    session.requested_tests = graph_state["requested_tests"]
    session.student_hypotheses = graph_state["student_hypotheses"]
    session.final_submission = graph_state["final_submission"]
    session.rubric_scores = graph_state["rubric_scores"]
    session.missed_items = graph_state["missed_items"]
    session.retrieved_sources = graph_state["retrieved_sources"]
    session.feedback_report = graph_state["feedback_report"]
    session.safety_flags = graph_state["safety_flags"]
    session.evolution_candidates = graph_state["evolution_candidates"]


def _initial_graph_state(case_id: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "stage": "",
        "case_title": "",
        "chief_complaint": "",
        "messages": [],
        "asked_questions": [],
        "intent_history": [],
        "revealed_facts": [],
        "requested_exams": [],
        "requested_tests": [],
        "student_hypotheses": [],
        "final_submission": None,
        "rubric_scores": {},
        "missed_items": [],
        "retrieved_sources": [],
        "feedback_report": None,
        "safety_flags": [],
        "evolution_candidates": [],
    }


def _serialize_case_summary(case: Case) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "case_title": case.case_title,
        "course_module": case.course_module,
        "difficulty": case.difficulty,
        "chief_complaint": case.chief_complaint,
        "enabled": True,
    }


def _serialize_physical_exam_option(exam: PhysicalExamItem) -> dict[str, Any]:
    return {
        "exam_code": exam.exam_code,
        "exam_name_cn": exam.exam_name_cn,
        "result": exam.result,
        "is_abnormal": exam.is_abnormal,
    }


def _serialize_auxiliary_test_option(test: AuxiliaryTestItem) -> dict[str, Any]:
    return {
        "test_code": test.test_code,
        "test_name_cn": test.test_name_cn,
        "category": test.category,
        "result": test.result,
        "is_abnormal": test.is_abnormal,
    }


def _serialize_diagnosis_draft(case: Case) -> dict[str, str]:
    return {
        "diagnosis": case.diagnosis.main_diagnosis,
        "reasoning": "".join(reasoning_point.statement for reasoning_point in case.diagnosis.reasoning_points),
    }


def _enabled_skill_prompts(skills: list[dict[str, Any]]) -> list[str]:
    return [f"{skill['title']}：{skill['suggested_strategy']}" for skill in skills]


def _serialize_session(session: OsceSession, case: Case) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "student_id": session.student_id,
        "case_id": session.case_id,
        "stage": session.stage,
        "case_title": case.case_title,
        "chief_complaint": case.chief_complaint,
        "diagnosis_draft": _serialize_diagnosis_draft(case),
        "physical_exam_options": [
            _serialize_physical_exam_option(exam)
            for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]
        ],
        "auxiliary_test_options": [
            _serialize_auxiliary_test_option(test)
            for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]
        ],
        "messages": session.messages,
        "asked_questions": session.asked_questions,
        "intent_history": session.intent_history,
        "revealed_facts": session.revealed_facts,
        "requested_exams": session.requested_exams,
        "requested_tests": session.requested_tests,
        "student_hypotheses": session.student_hypotheses,
        "final_submission": session.final_submission,
        "rubric_scores": session.rubric_scores,
        "missed_items": session.missed_items,
        "retrieved_sources": session.retrieved_sources,
        "feedback_report": session.feedback_report,
        "safety_flags": session.safety_flags,
        "evolution_candidates": session.evolution_candidates,
    }


osce_session_service = OsceSessionService()
