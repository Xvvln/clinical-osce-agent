from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from app.graph.osce_graph import build_osce_graph
from app.models.case import AuxiliaryTestItem, Case, PhysicalExamItem
from app.services.osce_session_store import OsceSessionStore, osce_session_store
from app.services.report_store import ReportStore, report_store
from app.services.training_event_store import TrainingEventStore, training_event_store
from app.services.training_skill_store import TrainingSkillStore, training_skill_store
from app.services.vertex_gemini_scorer import create_default_vertex_gemini_scorer
from app.validators.case_validator import validate_case

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"
RUBRICS_DIR = ROOT_DIR / "data" / "rubrics"


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
        session_store: OsceSessionStore = osce_session_store,
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
        self.session_store = session_store

    def list_cases(self) -> list[dict[str, Any]]:
        return [_serialize_case_summary(load_case_node(case_path.stem)) for case_path in sorted(CASES_DIR.glob("*.json"))]

    def get_case_detail(self, case_id: str) -> dict[str, Any] | None:
        case_path = CASES_DIR / f"{case_id}.json"
        if not case_path.exists():
            return None
        return _serialize_case_summary(load_case_node(case_id))

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
        enabled_skills = _enabled_skills_for_case(
            self.training_skill_store.list_enabled_skills(),
            graph_state["case_id"],
        )
        session = OsceSession(
            session_id=str(uuid4()),
            student_id=student_id,
            case_id=graph_state["case_id"],
            stage=graph_state["stage"],
            evolution_candidates=_enabled_skill_prompts(enabled_skills),
        )
        self._save_session(session)
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
        session = self._get_session(session_id)
        if session is None:
            return None
        return _serialize_session(session, load_case_node(session.case_id))

    def handle_message(self, session_id: str, message: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, message))
        _apply_graph_state(session, graph_state)
        self._save_session(session)
        payload = _serialize_session(session, load_case_node(session.case_id))
        payload["reply"] = graph_state["reply"]
        payload["current_intent"] = graph_state["current_intent"]
        if graph_state["current_intent"] == "safety_boundary":
            self._append_event(
                session,
                "safety_boundary_triggered",
                {
                    "message": message,
                    "safety_flag": graph_state["safety_flags"][-1],
                    "reply": graph_state["reply"],
                },
            )
            return payload
        if graph_state["current_intent"] == "answer_request_redirect":
            self._append_event(
                session,
                "answer_request_redirected",
                {
                    "message": message,
                    "reply": graph_state["reply"],
                },
            )
            return payload
        self._append_event(
            session,
            "history_message",
            {"message": message, "current_intent": graph_state["current_intent"], "reply": graph_state["reply"]},
        )
        return payload

    def request_physical_exam(self, session_id: str, exam_code: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, exam_code=exam_code))
        _apply_graph_state(session, graph_state)
        self._save_session(session)
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
        session = self._get_session(session_id)
        if session is None:
            return None
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, test_code=test_code))
        _apply_graph_state(session, graph_state)
        self._save_session(session)
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
        session = self._get_session(session_id)
        if session is None:
            return None
        session.student_hypotheses.append(hypothesis)
        self._save_session(session)
        self._append_event(session, "hypothesis_recorded", {"hypothesis": hypothesis})
        return _serialize_session(session, load_case_node(session.case_id))

    def request_hint(self, session_id: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, hint_requested=True))
        _apply_graph_state(session, graph_state)
        self._save_session(session)
        payload = _serialize_session(session, load_case_node(session.case_id))
        payload["hint"] = graph_state["hint"]
        self._append_event(session, "hint_requested", {"hint": graph_state["hint"]})
        return payload

    def get_teaching_focus(self, session_id: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        from app.services.derived_teaching_focus_service import build_session_teaching_focus

        return build_session_teaching_focus(session)

    def submit_diagnosis(self, session_id: str, diagnosis: str, reasoning: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
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
        self._save_session(session)
        self._append_event(session, "diagnosis_submitted", {"diagnosis": diagnosis, "reasoning": reasoning})
        return _serialize_session(session, load_case_node(session.case_id))

    def get_report(self, session_id: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        stored_report = self.report_store.get_report(session_id)
        if stored_report is not None:
            return stored_report
        if session is None:
            return None
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, report_requested=True))
        _apply_graph_state(session, graph_state)
        self._save_session(session)
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
                    "source_references": session.feedback_report["source_references"],
                    "source_reference_items": session.feedback_report["source_reference_items"],
                },
            )
        return session.feedback_report

    def delete_session(self, session_id: str) -> bool:
        self._sessions.pop(session_id, None)
        return self.session_store.delete_session(session_id)

    def _get_session(self, session_id: str) -> OsceSession | None:
        session = self._sessions.get(session_id)
        if session is not None:
            return session
        session_payload = self.session_store.get_session_payload(session_id)
        if session_payload is None:
            return None
        session = OsceSession(**session_payload)
        self._sessions[session.session_id] = session
        return session

    def _save_session(self, session: OsceSession) -> None:
        self._sessions[session.session_id] = session
        self.session_store.save_session(session)

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
        "training_progress_next_focus": _serialize_training_progress(session, case)["next_focus"],
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
        "patient_profile": _serialize_student_visible_patient_profile(case),
        "opening_task_card": _serialize_opening_task_card(case),
        "teaching_focus": _serialize_teaching_focus(case),
        "physical_exam_options": [
            _serialize_physical_exam_quick_option(exam)
            for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]
        ],
        "auxiliary_test_options": [
            _serialize_auxiliary_test_quick_option(test)
            for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]
        ],
    }


def _serialize_teaching_focus(case: Case) -> dict[str, Any]:
    return case.teaching_focus.model_dump(mode="json")


def _serialize_dynamic_teaching_focus(session: OsceSession) -> dict[str, Any]:
    from app.services.derived_teaching_focus_service import build_session_teaching_focus

    return build_session_teaching_focus(session)


def _serialize_physical_exam_quick_option(exam: PhysicalExamItem) -> dict[str, str]:
    return {
        "exam_code": exam.exam_code,
        "exam_name_cn": exam.exam_name_cn,
    }


def _serialize_auxiliary_test_quick_option(test: AuxiliaryTestItem) -> dict[str, str]:
    return {
        "test_code": test.test_code,
        "test_name_cn": test.test_name_cn,
        "category": test.category,
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
        "diagnosis": "",
        "reasoning": "",
    }


def _serialize_student_visible_patient_profile(case: Case) -> dict[str, str]:
    patient_profile = case.patient_profile
    return {
        "age": f"{patient_profile.age_value}{patient_profile.age_unit}",
        "gender": patient_profile.gender,
        "occupation": patient_profile.occupation,
        "hospital_department": patient_profile.hospital_department,
    }


def _serialize_opening_task_card(case: Case) -> dict[str, Any]:
    patient_profile = case.patient_profile
    gender_label = "男性" if patient_profile.gender == "男" else "女性" if patient_profile.gender == "女" else patient_profile.gender
    return {
        "role": f"你是{patient_profile.hospital_department}接诊医生。",
        "scenario": f"一名{patient_profile.age_value}{patient_profile.age_unit}{gender_label}{patient_profile.occupation}因{case.chief_complaint}来诊。",
        "tasks": [
            "进行有重点的病史采集",
            "判断需要哪些查体",
            "选择必要辅助检查",
            "提出诊断假设和鉴别诊断",
            "最终提交诊断与推理依据",
        ],
    }


def _serialize_inquiry_guidance() -> dict[str, Any]:
    return {
        "priority": "先完成现病史的 OPQRST 和伴随症状，再进入既往史、用药过敏史和 ICE。",
        "suggested_questions": [
            "什么时候开始疼的？",
            "最开始和现在分别疼在哪里？",
            "疼痛是什么性质，程度如何？",
            "有没有恶心、呕吐、发热或腹泻？",
            "排尿、排便有没有异常？",
        ],
        "categories": ["起病时间", "部位变化", "疼痛性质", "疼痛程度", "伴随症状", "排尿排便", "既往史", "用药过敏史", "ICE"],
    }


def _serialize_training_progress(session: OsceSession, case: Case) -> dict[str, Any]:
    fact_ids = [
        (fact.fact_id, _student_safe_evidence_id(case, fact.fact_id))
        for fact in case.history.hidden_facts
    ]
    covered_fact_ids = [safe_id for fact_id, safe_id in fact_ids if fact_id in session.revealed_facts]
    pending_fact_ids = [safe_id for fact_id, safe_id in fact_ids if fact_id not in session.revealed_facts]

    exam_codes = _physical_exam_codes(case.physical_exam.must_items, case.physical_exam.optional_items)
    must_exam_codes = _physical_exam_codes(case.physical_exam.must_items)
    requested_exam_codes = [exam_code for exam_code in exam_codes if exam_code in session.requested_exams]
    must_pending_exam_codes = [exam_code for exam_code in must_exam_codes if exam_code not in session.requested_exams]

    test_codes = _auxiliary_test_codes(case.auxiliary_tests.must_items, case.auxiliary_tests.optional_items)
    must_test_codes = _auxiliary_test_codes(case.auxiliary_tests.must_items)
    requested_test_codes = [test_code for test_code in test_codes if test_code in session.requested_tests]
    must_pending_test_codes = [test_code for test_code in must_test_codes if test_code not in session.requested_tests]

    reasoning_evidence = _reasoning_evidence(case)
    collected_reasoning_evidence = [
        evidence for evidence in reasoning_evidence if _session_has_evidence(session, evidence)
    ]
    collected_evidence = [_student_safe_evidence_id(case, evidence) for evidence in collected_reasoning_evidence]

    return {
        "history": {
            "total": len(fact_ids),
            "covered": len(covered_fact_ids),
            "covered_fact_ids": covered_fact_ids,
            "pending_fact_ids": pending_fact_ids,
        },
        "physical_exam": {
            "total": len(exam_codes),
            "requested": len(requested_exam_codes),
            "requested_codes": requested_exam_codes,
            "pending_codes": [exam_code for exam_code in exam_codes if exam_code not in session.requested_exams],
            "must_total": len(must_exam_codes),
            "must_requested": len(must_exam_codes) - len(must_pending_exam_codes),
            "must_pending_codes": must_pending_exam_codes,
        },
        "auxiliary_test": {
            "total": len(test_codes),
            "requested": len(requested_test_codes),
            "requested_codes": requested_test_codes,
            "pending_codes": [test_code for test_code in test_codes if test_code not in session.requested_tests],
            "must_total": len(must_test_codes),
            "must_requested": len(must_test_codes) - len(must_pending_test_codes),
            "must_pending_codes": must_pending_test_codes,
        },
        "reasoning": {
            "total_evidence": len(reasoning_evidence),
            "collected_evidence_count": len(collected_evidence),
            "collected_evidence": collected_evidence,
            "pending_evidence": [
                _student_safe_evidence_id(case, evidence)
                for evidence in reasoning_evidence
                if evidence not in collected_reasoning_evidence
            ],
            "ready_for_hypothesis": bool(covered_fact_ids and requested_exam_codes and requested_test_codes),
        },
        "coverage_map": _serialize_coverage_map(session, case, reasoning_evidence),
        "next_focus": _training_progress_next_focus(
            session,
            covered_fact_ids,
            requested_exam_codes,
            requested_test_codes,
        ),
    }


def _serialize_coverage_map(session: OsceSession, case: Case, reasoning_evidence: list[str]) -> dict[str, list[dict[str, str]]]:
    return {
        "history": [
            _coverage_map_item(
                _student_safe_evidence_id(case, fact.fact_id),
                fact.canonical_answer,
                fact.fact_id in session.revealed_facts,
            )
            for fact in case.history.hidden_facts
        ],
        "physical_exam": [
            _coverage_map_item(exam.exam_code, f"{exam.exam_name_cn}：{exam.result}", exam.exam_code in session.requested_exams)
            for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]
        ],
        "auxiliary_test": [
            _coverage_map_item(test.test_code, f"{test.test_name_cn}：{test.result}", test.test_code in session.requested_tests)
            for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]
        ],
        "reasoning": [
            _coverage_map_item(
                _student_safe_evidence_id(case, evidence),
                _coverage_map_label_by_evidence(case, evidence),
                _session_has_evidence(session, evidence),
            )
            for evidence in reasoning_evidence
        ],
    }


def _coverage_map_item(item_id: str, label: str, is_covered: bool) -> dict[str, str]:
    return {"id": item_id, "label": label, "status": "covered" if is_covered else "pending"}


def _coverage_map_label_by_evidence(case: Case, evidence: str) -> str:
    labels = {
        **{fact.fact_id: fact.canonical_answer for fact in case.history.hidden_facts},
        **{
            exam.exam_code: f"{exam.exam_name_cn}：{exam.result}"
            for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]
        },
        **{
            test.test_code: f"{test.test_name_cn}：{test.result}"
            for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]
        },
    }
    return labels.get(evidence, _student_safe_evidence_id(case, evidence))


def _physical_exam_codes(*exam_groups: list[PhysicalExamItem]) -> list[str]:
    return [exam.exam_code for exam_group in exam_groups for exam in exam_group]


def _auxiliary_test_codes(*test_groups: list[AuxiliaryTestItem]) -> list[str]:
    return [test.test_code for test_group in test_groups for test in test_group]


def _reasoning_evidence(case: Case) -> list[str]:
    evidence_items: list[str] = []
    for reasoning_point in case.diagnosis.reasoning_points:
        for evidence in reasoning_point.required_evidence:
            if evidence not in evidence_items:
                evidence_items.append(evidence)
    return evidence_items


def _student_safe_evidence_id(case: Case, evidence: str) -> str:
    return evidence.removeprefix(f"{case.case_id}.")


def _session_has_evidence(session: OsceSession, evidence: str) -> bool:
    return (
        evidence in session.revealed_facts
        or evidence in session.requested_exams
        or evidence in session.requested_tests
    )


def _training_progress_next_focus(
    session: OsceSession,
    covered_fact_ids: list[str],
    requested_exam_codes: list[str],
    requested_test_codes: list[str],
) -> str:
    if session.final_submission is not None:
        return "你已经提交诊断，建议到报告中复盘哪些证据支持或削弱你的判断。"
    if not covered_fact_ids:
        return "先用开放式问题明确起病、部位、性质、程度和伴随症状。"
    if not requested_exam_codes:
        return "已获得部分病史，下一步选择关键查体来验证当前线索。"
    if not requested_test_codes:
        return "你已经获得部分病史和查体信息，可以申请能验证当前假设的辅助检查。"
    if not session.student_hypotheses:
        return "已有病史、查体和辅助检查证据，先记录一个诊断假设，再继续补齐关键证据。"
    return "继续补齐未覆盖的关键病史、查体和辅助检查，再提交最终诊断。"


def _enabled_skill_prompts(skills: list[dict[str, Any]]) -> list[str]:
    return [f"{skill['title']}：{skill['suggested_strategy']}" for skill in skills]


def _enabled_skills_for_case(skills: list[dict[str, Any]], case_id: str) -> list[dict[str, Any]]:
    rubric_item_ids = _rubric_item_ids(case_id)
    return [skill for skill in skills if _enabled_skill_applies_to_case(skill, case_id, rubric_item_ids)]


def _enabled_skill_applies_to_case(skill: dict[str, Any], case_id: str, rubric_item_ids: set[str]) -> bool:
    case_ids = [str(skill_case_id) for skill_case_id in skill.get("case_ids", [])]
    if case_ids:
        return case_id in case_ids

    related_recommendations = [str(reference) for reference in skill.get("related_recommendations", [])]
    if related_recommendations:
        rubric_prefix = f"rubric:{case_id}_rubric."
        return any(reference.startswith(rubric_prefix) or reference == f"case:{case_id}" for reference in related_recommendations)

    trigger_item_ids = [str(item_id) for item_id in skill.get("trigger_item_ids", [])]
    if trigger_item_ids:
        return bool(set(trigger_item_ids) & rubric_item_ids)

    trigger_item_id = str(skill.get("trigger_item_id", ""))
    if trigger_item_id in rubric_item_ids:
        return True
    if trigger_item_id.startswith("training_pattern_"):
        return any(item_id in trigger_item_id for item_id in rubric_item_ids)
    return False


def _rubric_item_ids(case_id: str) -> set[str]:
    rubric_path = RUBRICS_DIR / f"{case_id}_rubric.yaml"
    if not rubric_path.exists():
        return set()
    rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    return {
        str(item["item_id"])
        for dimension in rubric.get("dimensions", [])
        for item in dimension.get("items", [])
    }


def _serialize_session(session: OsceSession, case: Case) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "student_id": session.student_id,
        "case_id": session.case_id,
        "stage": session.stage,
        "case_title": case.case_title,
        "chief_complaint": case.chief_complaint,
        "patient_profile": _serialize_student_visible_patient_profile(case),
        "opening_task_card": _serialize_opening_task_card(case),
        "teaching_focus": _serialize_teaching_focus(case),
        "dynamic_teaching_focus": _serialize_dynamic_teaching_focus(session),
        "inquiry_guidance": _serialize_inquiry_guidance(),
        "diagnosis_draft": _serialize_diagnosis_draft(case),
        "physical_exam_options": [
            _serialize_physical_exam_option(exam)
            for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]
        ],
        "auxiliary_test_options": [
            _serialize_auxiliary_test_option(test)
            for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]
        ],
        "training_progress": _serialize_training_progress(session, case),
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
