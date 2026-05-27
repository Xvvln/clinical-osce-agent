from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

import yaml

from app.graph.osce_graph import build_osce_graph, reflection_node, training_strategy_node
from app.models.case import AuxiliaryTestItem, Case, PhysicalExamItem
from app.services.osce_session_store import OsceSessionStore, osce_session_store
from app.services.patient_language_service import build_patient_opening_utterance
from app.services.agent_rag_context_service import retrieve_agent_context
from app.services.procedure_result_simulator import (
    ProcedureResultSimulationRequest,
    create_default_procedure_result_simulator,
)
from app.services.procedure_result_approval_agent import (
    ProcedureResultApprovalRequest,
    create_default_procedure_result_approval_agent,
)
from app.services.report_store import ReportStore, report_store
from app.services.student_profile_store import StudentProfileStore, student_profile_store
from app.services.training_event_store import TrainingEventStore, training_event_store
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore, training_skill_candidate_store
from app.services.student_profile_summary_service import build_skill_profile_summary
from app.services.training_skill_orchestrator_service import build_active_skill_context
from app.services.training_skill_store import TrainingSkillStore, training_skill_store
from app.services.vertex_gemini_scorer import create_default_vertex_gemini_scorer
from app.validators.case_validator import validate_case

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"
RUBRICS_DIR = ROOT_DIR / "data" / "rubrics"
PROCEDURE_SIMULATION_SAFETY_BOUNDARY = "AI 模拟补充结果仅用于高级训练反馈，不写入病例标准事实，不进入标准评分。"
TRAINING_DIFFICULTY_MODES = {"beginner", "intermediate", "advanced"}


@dataclass
class OsceSession:
    session_id: str
    student_id: str
    case_id: str
    stage: str
    training_difficulty: str = "beginner"
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
    active_skill_context: dict[str, Any] = field(default_factory=dict)
    agent_turn_memory: list[dict[str, Any]] = field(default_factory=list)
    action_timeline: list[dict[str, Any]] = field(default_factory=list)
    pedagogy_state: dict[str, Any] = field(default_factory=dict)
    agent_decision_trace: list[dict[str, Any]] = field(default_factory=list)
    reflection_summary: dict[str, Any] | None = None
    procedure_simulation_audit_items: list[dict[str, Any]] = field(default_factory=list)


class OsceSessionService:
    def __init__(
        self,
        report_store: ReportStore = report_store,
        training_event_store: TrainingEventStore = training_event_store,
        training_skill_store: TrainingSkillStore = training_skill_store,
        training_skill_candidate_store: TrainingSkillCandidateStore = training_skill_candidate_store,
        session_store: OsceSessionStore = osce_session_store,
        student_profile_store: StudentProfileStore = student_profile_store,
        personal_skill_service: Any | None = None,
        graph: Any | None = None,
        patient_responder: Any | None = None,
        procedure_result_simulator: Any | None = None,
        procedure_result_approval_agent: Any | None = None,
    ) -> None:
        self._sessions: dict[str, OsceSession] = {}
        self.osce_graph = graph or build_osce_graph(
            llm_scorer=create_default_vertex_gemini_scorer(),
            patient_responder=patient_responder,
        )
        self.report_store = report_store
        self.training_event_store = training_event_store
        self.training_skill_store = training_skill_store
        self.training_skill_candidate_store = training_skill_candidate_store
        self.session_store = session_store
        self.student_profile_store = student_profile_store
        self.personal_skill_service = personal_skill_service
        self.procedure_result_simulator = procedure_result_simulator or create_default_procedure_result_simulator()
        self.procedure_result_approval_agent = (
            procedure_result_approval_agent or create_default_procedure_result_approval_agent()
        )
        self._message_processing_statuses: dict[str, dict[str, Any]] = {}
        self._message_processing_status_lock = Lock()

    def list_cases(self) -> list[dict[str, Any]]:
        return [_serialize_case_summary(load_case_node(case_path.stem)) for case_path in sorted(CASES_DIR.glob("*.json"))]

    def get_case_detail(self, case_id: str) -> dict[str, Any] | None:
        case_path = CASES_DIR / f"{case_id}.json"
        if not case_path.exists():
            return None
        return _serialize_case_summary(load_case_node(case_id))

    def get_procedure_catalog(self) -> dict[str, Any]:
        return _build_procedure_catalog()

    def get_case_raw(self, case_id: str) -> dict[str, Any] | None:
        case_path = CASES_DIR / f"{case_id}.json"
        if not case_path.exists():
            return None
        case_payload = json.loads(case_path.read_text(encoding="utf-8"))
        validate_case(case_payload)
        return case_payload

    def create_session(self, case_id: str, student_id: str, training_difficulty: str = "beginner") -> dict[str, Any]:
        graph_state = self.osce_graph.invoke(_initial_graph_state(case_id))
        case = load_case_node(graph_state["case_id"])
        all_enabled_skills = self.training_skill_store.list_enabled_skills()
        rubric_item_ids = _rubric_item_ids(case.case_id)
        student_profile = self._build_skill_profile_summary(student_id, all_enabled_skills)
        enabled_skills = _enabled_skills_for_case(
            all_enabled_skills,
            case,
            graph_state["stage"],
            student_id,
        )
        active_skill_context = build_active_skill_context(
            all_enabled_skills,
            case_id=case.case_id,
            student_id=student_id,
            stage=graph_state["stage"],
            rubric_item_ids=rubric_item_ids,
            student_profile=student_profile,
            patient_profile={"gender": case.patient_profile.gender},
        )
        session = OsceSession(
            session_id=str(uuid4()),
            student_id=student_id,
            case_id=graph_state["case_id"],
            stage=graph_state["stage"],
            training_difficulty=_normalize_training_difficulty(training_difficulty),
            evolution_candidates=_enabled_skill_prompts(enabled_skills),
            active_skill_context=active_skill_context,
        )
        agent_update = _refresh_agent_state(session)
        self._save_session(session)
        self._append_event(session, "session_created", {"stage": session.stage, "training_difficulty": session.training_difficulty})
        self._append_agent_update_event(session, agent_update)
        for skill in enabled_skills:
            skill_event_payload = {
                "skill_id": skill["skill_id"],
                "title": skill["title"],
                "suggested_strategy": skill["suggested_strategy"],
                "skill_type": skill.get("skill_type", "reasoning_bridge"),
                "stage_scope": list(skill.get("stage_scope", [])),
                "effect_status": skill.get("effect_status", "insufficient_samples"),
            }
            if skill.get("scope") and skill.get("scope") != "global":
                skill_event_payload["scope"] = skill["scope"]
            if skill.get("source_session_id"):
                skill_event_payload["source_session_id"] = skill["source_session_id"]
            if skill.get("owner_student_id"):
                skill_event_payload["owner_student_id"] = skill["owner_student_id"]
            self._append_event(
                session,
                "training_skill_applied",
                skill_event_payload,
            )
        return _serialize_session(session, case)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        return _serialize_session(session, load_case_node(session.case_id))

    def begin_message_processing_status(self, session_id: str) -> None:
        with self._message_processing_status_lock:
            self._message_processing_statuses[session_id] = {
                "state": "running",
                "current_step_id": "backend_connect",
                "current_label": "建立后端流程连接",
                "summary": "当前：建立后端流程连接。",
                "steps": [],
            }

    def update_message_processing_status(
        self,
        session_id: str,
        *,
        step_id: str,
        label: str,
        status: str = "active",
    ) -> None:
        step = {
            "step_id": step_id,
            "label": label,
            "status": status,
        }
        with self._message_processing_status_lock:
            payload = self._message_processing_statuses.setdefault(
                session_id,
                {
                    "state": "running",
                    "current_step_id": step_id,
                    "current_label": label,
                    "summary": f"当前：{label}。",
                    "steps": [],
                },
            )
            next_steps = [
                {**existing_step, "status": "completed"}
                if existing_step.get("status") == "active" and existing_step.get("step_id") != step_id
                else existing_step
                for existing_step in payload.get("steps", [])
                if isinstance(existing_step, dict)
            ]
            matching_index = next(
                (index for index, existing_step in enumerate(next_steps) if existing_step.get("step_id") == step_id),
                None,
            )
            if matching_index is None:
                next_steps.append(step)
            else:
                next_steps[matching_index] = step
            payload.update(
                {
                    "state": "running",
                    "current_step_id": step_id,
                    "current_label": label,
                    "summary": f"当前：{label}。",
                    "steps": next_steps,
                }
            )

    def complete_message_processing_status(self, session_id: str, *, errored: bool = False) -> None:
        with self._message_processing_status_lock:
            payload = self._message_processing_statuses.get(session_id)
            if payload is None:
                return
            final_state = "error" if errored else "completed"
            final_steps = [
                {**step, "status": final_state if step.get("status") == "active" and errored else "completed"}
                if isinstance(step, dict)
                else step
                for step in payload.get("steps", [])
            ]
            payload.update(
                {
                    "state": final_state,
                    "summary": "处理失败。" if errored else "已完成本轮智能体流程。",
                    "steps": final_steps,
                }
            )

    def get_message_processing_status(self, session_id: str) -> dict[str, Any]:
        with self._message_processing_status_lock:
            payload = self._message_processing_statuses.get(session_id)
            if payload is None:
                return {
                    "state": "idle",
                    "current_step_id": "",
                    "current_label": "",
                    "summary": "当前没有正在处理的问诊。",
                    "steps": [],
                }
            return {
                "state": payload.get("state", "idle"),
                "current_step_id": payload.get("current_step_id", ""),
                "current_label": payload.get("current_label", ""),
                "summary": payload.get("summary", ""),
                "steps": list(payload.get("steps", [])),
            }

    def handle_message(self, session_id: str, message: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        self.begin_message_processing_status(session_id)
        try:
            self._refresh_active_skill_context(session)
            graph_state = self.osce_graph.invoke(
                _graph_state_from_session(
                    session,
                    message,
                    processing_progress_callback=lambda event: self.update_message_processing_status(
                        session_id,
                        step_id=str(event.get("step_id") or ""),
                        label=str(event.get("label") or event.get("step_id") or ""),
                        status=str(event.get("status") or "active"),
                    ),
                )
            )
            _apply_graph_state(session, graph_state)
            self._refresh_active_skill_context(session)
            agent_update = _refresh_agent_state(session)
            self._save_session(session)
            self.complete_message_processing_status(session_id)
        except Exception:
            self.complete_message_processing_status(session_id, errored=True)
            raise
        payload = _serialize_session(session, load_case_node(session.case_id))
        payload["reply"] = graph_state["reply"]
        payload["current_intents"] = list(graph_state.get("current_intents", []))
        primary_intent = _primary_intent_from_graph_state(graph_state)
        if primary_intent == "safety_boundary":
            self._append_event(
                session,
                "safety_boundary_triggered",
                {
                    "message": message,
                    "safety_flag": graph_state["safety_flags"][-1],
                    "reply": graph_state["reply"],
                    "agent_turn": _latest_agent_turn(graph_state),
                },
            )
            self._append_agent_update_event(session, agent_update)
            return payload
        if primary_intent == "answer_request_redirect":
            self._append_event(
                session,
                "answer_request_redirected",
                {
                    "message": message,
                    "reply": graph_state["reply"],
                    "agent_turn": _latest_agent_turn(graph_state),
                },
            )
            self._append_agent_update_event(session, agent_update)
            return payload
        self._append_event(
            session,
            "history_message",
            {
                "message": message,
                "current_intents": list(graph_state.get("current_intents", [])),
                "reply": graph_state["reply"],
                "agent_turn": _latest_agent_turn(graph_state),
            },
        )
        self._append_agent_update_event(session, agent_update)
        return payload

    def request_physical_exam(self, session_id: str, exam_code: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        self._refresh_active_skill_context(session)
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, exam_code=exam_code))
        _apply_graph_state(session, graph_state)
        self._refresh_active_skill_context(session)
        agent_update = _refresh_agent_state(session)
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
        self._append_agent_update_event(session, agent_update)
        return payload

    def request_physical_exams(self, session_id: str, exam_codes: list[str]) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        self._refresh_active_skill_context(session)
        case = load_case_node(session.case_id)
        case_exam_map = _case_physical_exam_map(case)
        catalog_exam_map = _catalog_physical_exam_map()
        exam_results: list[dict[str, Any]] = []
        for exam_code in _dedupe_non_empty(exam_codes):
            configured_exam = case_exam_map.get(exam_code)
            catalog_exam = catalog_exam_map.get(exam_code, {})
            already_requested = exam_code in session.requested_exams
            graph_state: dict[str, Any] = {
                "exam_code": exam_code,
                "exam_name_cn": configured_exam.exam_name_cn
                if configured_exam is not None
                else str(catalog_exam.get("exam_name_cn") or "未提供查体"),
                "exam_result": configured_exam.result
                if configured_exam is not None
                else "该项目已记录，但本训练站点未提供该查体结果。",
            }
            if not already_requested:
                graph_state = self.osce_graph.invoke(_graph_state_from_session(session, exam_code=exam_code))
                _apply_graph_state(session, graph_state)
                if configured_exam is None and catalog_exam.get("exam_name_cn"):
                    _relabel_latest_action_timeline_event(
                        session,
                        action_type="physical_exam_requested",
                        source_id=exam_code,
                        label=str(catalog_exam["exam_name_cn"]),
                    )
            is_configured = configured_exam is not None
            exam_results.append(
                {
                    "exam_code": graph_state["exam_code"],
                    "exam_name_cn": (
                        configured_exam.exam_name_cn
                        if configured_exam is not None
                        else str(catalog_exam.get("exam_name_cn") or graph_state["exam_name_cn"])
                    ),
                    "result": (
                        graph_state["exam_result"]
                        if is_configured
                        else "该项目已记录，但本训练站点未提供该查体结果。"
                    ),
                    "availability_status": "case_configured" if is_configured else "not_available_for_case",
                }
            )
        self._refresh_active_skill_context(session)
        agent_update = _refresh_agent_state(session)
        self._save_session(session)
        payload = _serialize_session(session, case)
        payload["exam_results"] = exam_results
        self._append_event(
            session,
            "physical_exams_requested",
            {"exam_results": exam_results},
        )
        self._append_agent_update_event(session, agent_update)
        return payload

    def request_auxiliary_test(self, session_id: str, test_code: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        self._refresh_active_skill_context(session)
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, test_code=test_code))
        _apply_graph_state(session, graph_state)
        self._refresh_active_skill_context(session)
        agent_update = _refresh_agent_state(session)
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
        self._append_agent_update_event(session, agent_update)
        return payload

    def request_auxiliary_tests(self, session_id: str, test_codes: list[str]) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        self._refresh_active_skill_context(session)
        case = load_case_node(session.case_id)
        case_test_map = _case_auxiliary_test_map(case)
        catalog_test_map = _catalog_auxiliary_test_map()
        test_results: list[dict[str, Any]] = []
        for test_code in _dedupe_non_empty(test_codes):
            configured_test = case_test_map.get(test_code)
            catalog_test = catalog_test_map.get(test_code, {})
            already_requested = test_code in session.requested_tests
            graph_state: dict[str, Any] = {
                "test_code": test_code,
                "test_name_cn": configured_test.test_name_cn
                if configured_test is not None
                else str(catalog_test.get("test_name_cn") or "未提供检查"),
                "test_result": configured_test.result
                if configured_test is not None
                else "该项目已记录，但本训练站点未提供该辅助检查结果。",
            }
            if not already_requested:
                graph_state = self.osce_graph.invoke(_graph_state_from_session(session, test_code=test_code))
                _apply_graph_state(session, graph_state)
                if configured_test is None and catalog_test.get("test_name_cn"):
                    _relabel_latest_action_timeline_event(
                        session,
                        action_type="auxiliary_test_requested",
                        source_id=test_code,
                        label=str(catalog_test["test_name_cn"]),
                    )
            is_configured = configured_test is not None
            test_results.append(
                {
                    "test_code": graph_state["test_code"],
                    "test_name_cn": (
                        configured_test.test_name_cn
                        if configured_test is not None
                        else str(catalog_test.get("test_name_cn") or graph_state["test_name_cn"])
                    ),
                    "result": (
                        graph_state["test_result"]
                        if is_configured
                        else "该项目已记录，但本训练站点未提供该辅助检查结果。"
                    ),
                    "availability_status": "case_configured" if is_configured else "not_available_for_case",
                }
            )
        self._refresh_active_skill_context(session)
        agent_update = _refresh_agent_state(session)
        self._save_session(session)
        payload = _serialize_session(session, case)
        payload["test_results"] = test_results
        self._append_event(
            session,
            "auxiliary_tests_requested",
            {"test_results": test_results},
        )
        self._append_agent_update_event(session, agent_update)
        return payload

    def request_procedure_text(self, session_id: str, request_text: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        standardization = _standardize_procedure_request_text(request_text)
        exam_results: list[dict[str, Any]] = []
        test_results: list[dict[str, Any]] = []
        if standardization["matched_exam_codes"]:
            exam_payload = self.request_physical_exams(session_id, list(standardization["matched_exam_codes"]))
            if exam_payload is not None:
                exam_results = list(exam_payload.get("exam_results") or [])
        if standardization["matched_test_codes"]:
            test_payload = self.request_auxiliary_tests(session_id, list(standardization["matched_test_codes"]))
            if test_payload is not None:
                test_results = list(test_payload.get("test_results") or [])

        session = self._get_session(session_id)
        if session is None:
            return None
        case = load_case_node(session.case_id)
        exam_result_map = {str(item.get("exam_code")): item for item in exam_results}
        test_result_map = {str(item.get("test_code")): item for item in test_results}
        matched_procedure_results = _build_standardized_procedure_results(
            standardization["matched_items"],
            exam_result_map,
            test_result_map,
        )
        matched_procedure_results = self._simulate_unconfigured_procedure_results(
            session=session,
            case=case,
            request_text=request_text,
            matched_procedure_results=matched_procedure_results,
        )
        has_simulated_results = any(item.get("generated_by_ai") is True for item in matched_procedure_results)
        procedure_simulation_audit_items = _procedure_simulation_audit_items_from_results(matched_procedure_results)
        if procedure_simulation_audit_items:
            session.procedure_simulation_audit_items = _merge_procedure_simulation_audit_items(
                session.procedure_simulation_audit_items,
                procedure_simulation_audit_items,
            )
            self._save_session(session)
        payload = _serialize_session(session, case)
        payload.update(
            {
                "standardized_request": {
                    "mode": "advanced_free_text_catalog",
                    "raw_request": request_text,
                    "matched_exam_codes": list(standardization["matched_exam_codes"]),
                    "matched_test_codes": list(standardization["matched_test_codes"]),
                    "unmatched_requests": list(standardization["unmatched_requests"]),
                    "generated_result_policy": "ai_simulated_not_scoring" if has_simulated_results else "disabled",
                    "safety_boundary": (
                        PROCEDURE_SIMULATION_SAFETY_BOUNDARY
                        if has_simulated_results
                        else "当前高级模式仅标准化到已有目录；未配置项目在无可用模型时不生成模拟结果，也不进入评分。"
                    ),
                },
                "matched_procedure_results": matched_procedure_results,
                "procedure_simulation_audit_items": list(session.procedure_simulation_audit_items),
                "exam_results": exam_results,
                "test_results": test_results,
            }
        )
        self._append_event(
            session,
            "procedure_free_text_requested",
            {
                "request_text": request_text,
                "standardized_request": payload["standardized_request"],
                "matched_procedure_results": matched_procedure_results,
                "procedure_simulation_audit_items": list(session.procedure_simulation_audit_items),
            },
        )
        return payload

    def _simulate_unconfigured_procedure_results(
        self,
        *,
        session: OsceSession,
        case: Case,
        request_text: str,
        matched_procedure_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        forbidden_terms = _procedure_forbidden_terms(case)
        simulated_results: list[dict[str, Any]] = []
        for result in matched_procedure_results:
            if result.get("availability_status") != "not_available_for_case":
                simulated_results.append(result)
                continue
            knowledge_context = _retrieve_procedure_simulation_context(
                case=case,
                request_text=request_text,
                procedure_result=result,
                forbidden_terms=forbidden_terms,
            )
            try:
                simulation = self.procedure_result_simulator(
                    ProcedureResultSimulationRequest(
                        case_id=case.case_id,
                        case_title=case.case_title,
                        chief_complaint=case.chief_complaint,
                        request_text=request_text,
                        procedure_kind=str(result.get("kind", "")),
                        procedure_code=str(result.get("code", "")),
                        procedure_name_cn=str(result.get("name_cn", "")),
                        patient_context=_procedure_simulation_patient_context(case),
                        configured_results=_procedure_simulation_configured_results(case),
                        retrieved_knowledge_context=knowledge_context,
                        forbidden_terms=forbidden_terms,
                    )
                )
            except Exception:
                simulated_results.append(
                    {
                        **result,
                        "approval_status": "simulation_unavailable",
                        "source_context_references": [
                            "policy:advanced_procedure_simulation.not_for_scoring",
                        ],
                    }
                )
                continue

            simulation_text = _sanitize_simulated_procedure_result(simulation.result, forbidden_terms)
            if not simulation_text:
                simulated_results.append(
                    {
                        **result,
                        "approval_status": "blocked_by_safety_gate",
                        "source_context_references": [
                            "policy:advanced_procedure_simulation.not_for_scoring",
                        ],
                    }
                )
                continue
            approval_request = ProcedureResultApprovalRequest(
                case_id=case.case_id,
                case_title=case.case_title,
                chief_complaint=case.chief_complaint,
                request_text=request_text,
                procedure_kind=str(result.get("kind", "")),
                procedure_code=str(result.get("code", "")),
                procedure_name_cn=str(result.get("name_cn", "")),
                simulated_result=simulation_text,
                source_context_references=[
                    str(item.get("reference")) for item in knowledge_context if item.get("reference")
                ],
                forbidden_terms=forbidden_terms,
            )
            try:
                approval_review = _normalize_procedure_simulation_approval_review(
                    self.procedure_result_approval_agent(approval_request)
                )
            except Exception:
                approval_review = _procedure_approval_error_fallback_review(simulation_text, forbidden_terms)
            approval_decision = str(approval_review.get("decision") or "approved")
            if approval_decision == "blocked":
                simulated_results.append(
                    {
                        **result,
                        "approval_status": "blocked_by_procedure_result_approval_agent",
                        "approval_agent_review": approval_review,
                        "source_context_references": [
                            "policy:advanced_procedure_simulation.not_for_scoring",
                        ],
                    }
                )
                continue
            if approval_decision == "revise":
                revised_text = _sanitize_simulated_procedure_result(
                    str(approval_review.get("revised_result") or ""),
                    forbidden_terms,
                )
                if not revised_text:
                    simulated_results.append(
                        {
                            **result,
                            "approval_status": "blocked_by_procedure_result_approval_agent",
                            "approval_agent_review": {
                                **approval_review,
                                "decision": "blocked",
                                "safety_issues": [
                                    *[
                                        str(item)
                                        for item in approval_review.get("safety_issues", [])
                                        if str(item).strip()
                                    ],
                                    "审批 Agent 改写结果为空或仍包含受保护内容。",
                                ],
                            },
                            "source_context_references": [
                                "policy:advanced_procedure_simulation.not_for_scoring",
                            ],
                        }
                    )
                    continue
                simulation_text = revised_text
            simulated_results.append(
                {
                    **result,
                    "result": f"AI 模拟：{simulation_text}（训练参考，不进入评分。）",
                    "availability_status": "ai_simulated_for_training",
                    "generated_by_ai": True,
                    "approval_status": (
                        "revised_by_procedure_result_approval_agent"
                        if approval_decision == "revise"
                        else "approved_by_procedure_result_approval_agent"
                    ),
                    "approval_agent_review": approval_review,
                    "source_context_references": [
                        *[str(item.get("reference")) for item in knowledge_context if item.get("reference")],
                        "policy:advanced_procedure_simulation.not_for_scoring",
                    ],
                    "scoring_eligible": False,
                }
            )
        return simulated_results

    def record_hypothesis(self, session_id: str, hypothesis: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        session.student_hypotheses.append(hypothesis)
        self._refresh_active_skill_context(session)
        agent_update = _refresh_agent_state(session)
        self._save_session(session)
        self._append_event(session, "hypothesis_recorded", {"hypothesis": hypothesis})
        self._append_agent_update_event(session, agent_update)
        return _serialize_session(session, load_case_node(session.case_id))

    def request_hint(self, session_id: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        self._refresh_active_skill_context(session)
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, hint_requested=True))
        _apply_graph_state(session, graph_state)
        self._refresh_active_skill_context(session)
        agent_update = _refresh_agent_state(session)
        self._save_session(session)
        payload = _serialize_session(session, load_case_node(session.case_id))
        payload["hint"] = graph_state["hint"]
        self._append_event(
            session,
            "hint_requested",
            {
                "hint": graph_state["hint"],
                "agent_turn": _latest_agent_turn(graph_state),
            },
        )
        self._append_agent_update_event(session, agent_update)
        return payload

    def get_teaching_focus(self, session_id: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        from app.services.derived_teaching_focus_service import build_session_teaching_focus

        return build_session_teaching_focus(session)

    def build_student_profile_summary(self, student_id: str) -> dict[str, Any]:
        return self._refresh_student_profile(student_id)

    def submit_diagnosis(self, session_id: str, diagnosis: str, reasoning: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        self._refresh_active_skill_context(session)
        graph_state = self.osce_graph.invoke(
            _graph_state_from_session(
                session,
                submitted_diagnosis=diagnosis,
                submitted_reasoning=reasoning,
            )
        )
        _apply_graph_state(session, graph_state)
        self._refresh_active_skill_context(session)
        agent_update = _refresh_agent_state(session)
        self._save_session(session)
        self._append_event(session, "diagnosis_submitted", {"diagnosis": diagnosis, "reasoning": reasoning})
        self._append_agent_update_event(session, agent_update)
        return _serialize_session(session, load_case_node(session.case_id))

    def get_report(self, session_id: str, *, include_optional_agents: bool = True) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        stored_report = self.report_store.get_report(session_id)
        if stored_report is not None:
            report = _ensure_personal_skill_report_defaults(stored_report, self.training_skill_candidate_store)
            if session is None:
                report = _ensure_report_procedure_simulation_audit_items(report, None)
                if _ai_reflection_review_uses_legacy_generic_text(report.get("ai_reflection_review")):
                    report = _rehydrate_orphan_teacher_reflection(report)
                    self.report_store.save_report(report)
                return report
            case = load_case_node(session.case_id)
            report = _ensure_report_training_progress_snapshot(report, session, case)
            report = _ensure_report_procedure_simulation_audit_items(report, session)
            if session.final_submission is not None and _report_needs_completed_session_hydration(report):
                session.feedback_report = report
                agent_update = _refresh_agent_state(session, use_reflection=True)
                if include_optional_agents:
                    session.feedback_report.update(_personal_skill_payload_for_report(self, session, case))
                else:
                    session.feedback_report.update(_deferred_optional_agent_payload(session.feedback_report, case))
                session.feedback_report = _ensure_report_training_progress_snapshot(session.feedback_report, session, case)
                session.feedback_report = _ensure_report_procedure_simulation_audit_items(session.feedback_report, session)
                self._save_session(session)
                self.report_store.save_report(session.feedback_report)
                self._refresh_student_profile(session.student_id)
                self._append_event(session, "report_generated", _report_generated_event_payload(session.feedback_report))
                self._append_agent_update_event(session, agent_update, event_type="agent_reflection_recorded")
                return session.feedback_report
            if report.get("training_progress_snapshot") != stored_report.get("training_progress_snapshot"):
                if session.feedback_report is not None:
                    session.feedback_report = report
                    self._save_session(session)
                self.report_store.save_report(report)
            return report
        if session is None:
            return None
        graph_state = self.osce_graph.invoke(_graph_state_from_session(session, report_requested=True))
        _apply_graph_state(session, graph_state)
        agent_update = _refresh_agent_state(session, use_reflection=True)
        if session.feedback_report is not None:
            case = load_case_node(session.case_id)
            session.feedback_report = _ensure_report_training_progress_snapshot(session.feedback_report, session, case)
            session.feedback_report = _ensure_report_procedure_simulation_audit_items(session.feedback_report, session)
            if include_optional_agents:
                session.feedback_report.update(_personal_skill_payload_for_report(self, session, case))
            else:
                session.feedback_report.update(_deferred_optional_agent_payload(session.feedback_report, case))
            session.feedback_report = _ensure_report_procedure_simulation_audit_items(session.feedback_report, session)
            self._save_session(session)
            self.report_store.save_report(session.feedback_report)
            self._refresh_student_profile(session.student_id)
            self._append_event(session, "report_generated", _report_generated_event_payload(session.feedback_report))
            self._append_agent_update_event(session, agent_update, event_type="agent_reflection_recorded")
        else:
            self._save_session(session)
        return session.feedback_report

    def enrich_report_optional_agents(self, session_id: str) -> dict[str, Any] | None:
        return self.get_report(session_id, include_optional_agents=True)

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

    def _refresh_active_skill_context(self, session: OsceSession) -> dict[str, Any]:
        case = load_case_node(session.case_id)
        enabled_skills = self.training_skill_store.list_enabled_skills()
        student_profile = self._build_skill_profile_summary(session.student_id, enabled_skills)
        active_skill_context = build_active_skill_context(
            enabled_skills,
            case_id=case.case_id,
            student_id=session.student_id,
            stage=session.stage,
            rubric_item_ids=_rubric_item_ids(case.case_id),
            current_missing_evidence=_current_missing_evidence(session),
            student_profile=student_profile,
            patient_profile={"gender": case.patient_profile.gender},
        )
        session.active_skill_context = active_skill_context
        session.evolution_candidates = _enabled_skill_prompts_from_active_context(active_skill_context)
        return active_skill_context

    def _build_skill_profile_summary(self, student_id: str, enabled_skills: list[dict[str, Any]]) -> dict[str, Any]:
        return self._refresh_student_profile(student_id, enabled_skills=enabled_skills)

    def _refresh_student_profile(
        self,
        student_id: str,
        *,
        enabled_skills: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        sessions = self.session_store.list_user_session_summaries(student_id)
        reports = [
            report
            for session in sessions
            if (report := self.report_store.get_report(str(session["session_id"]))) is not None
        ]
        if enabled_skills is None:
            enabled_skills = self.training_skill_store.list_enabled_skills()
        visible_enabled_skills = [
            skill
            for skill in enabled_skills
            if str(skill.get("scope", "global")) != "personal" or str(skill.get("owner_student_id", "")) == student_id
        ]
        profile = build_skill_profile_summary(
            reports=reports,
            enabled_skills=visible_enabled_skills,
        )
        self.student_profile_store.save_profile(student_id, profile)
        return profile

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

    def _append_agent_update_event(
        self,
        session: OsceSession,
        agent_update: dict[str, Any],
        event_type: str = "agent_decision_traced",
    ) -> None:
        latest_decision = session.agent_decision_trace[-1] if session.agent_decision_trace else {}
        payload = {
            "latest_decision": latest_decision,
            "pedagogy_state": agent_update.get("pedagogy_state", session.pedagogy_state),
        }
        if "reflection_summary" in agent_update:
            payload["reflection_summary"] = agent_update["reflection_summary"]
        self._append_event(session, event_type, payload)


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
    return {"exam_code": exam_code, "exam_name_cn": "未提供查体", "result": "该项目已记录，但本训练站点未提供该查体结果。"}


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
    return {"test_code": test_code, "test_name_cn": "未提供检查", "result": "该项目已记录，但本训练站点未提供该辅助检查结果。"}


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
    processing_progress_callback: Any | None = None,
) -> dict[str, Any]:
    case = load_case_node(session.case_id)
    training_progress = _serialize_training_progress(session, case)
    return {
        "session_id": session.session_id,
        "case_id": session.case_id,
        "stage": session.stage,
        "training_difficulty": session.training_difficulty,
        "case_title": case.case_title,
        "chief_complaint": case.chief_complaint,
        "student_message": student_message,
        "keyword_intents": [],
        "current_intents": [],
        "reply": "",
        "report_requested": report_requested,
        "hint_requested": hint_requested,
        "hint": "",
        "training_progress": training_progress,
        "training_progress_next_focus": training_progress["next_focus"],
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
        "active_skill_context": session.active_skill_context or _empty_active_skill_context(),
        "agent_turn_memory": session.agent_turn_memory,
        "action_timeline": session.action_timeline,
        "pedagogy_state": session.pedagogy_state,
        "agent_decision_trace": session.agent_decision_trace,
        "reflection_summary": session.reflection_summary,
        "processing_progress_callback": processing_progress_callback,
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
    session.agent_turn_memory = graph_state.get("agent_turn_memory", session.agent_turn_memory)
    session.action_timeline = graph_state.get("action_timeline", session.action_timeline)
    session.pedagogy_state = graph_state.get("pedagogy_state", session.pedagogy_state)
    session.agent_decision_trace = graph_state.get("agent_decision_trace", session.agent_decision_trace)
    session.reflection_summary = graph_state.get("reflection_summary", session.reflection_summary)


def _refresh_agent_state(session: OsceSession, use_reflection: bool = False) -> dict[str, Any]:
    graph_state = _graph_state_from_session(session)
    agent_update = reflection_node(graph_state) if use_reflection else training_strategy_node(graph_state)
    session.pedagogy_state = agent_update.get("pedagogy_state", session.pedagogy_state)
    session.agent_decision_trace = agent_update.get("agent_decision_trace", session.agent_decision_trace)
    if "reflection_summary" in agent_update:
        session.reflection_summary = agent_update["reflection_summary"]
    return agent_update


def _personal_skill_payload_for_report(
    service: OsceSessionService,
    session: OsceSession,
    case: Case,
) -> dict[str, Any]:
    from app.services.personal_training_skill_service import (
        build_generation_failed_personal_skill_payload,
        build_not_ready_personal_skill_payload,
        personal_training_skill_service,
    )
    from app.services.training_skill_candidate_service import TrainingSkillCandidateGenerationError

    if session.final_submission is None:
        return build_not_ready_personal_skill_payload()
    if session.feedback_report is None:
        return build_not_ready_personal_skill_payload()
    active_personal_skill_service = service.personal_skill_service or personal_training_skill_service
    try:
        return active_personal_skill_service.generate_for_completed_session(
            session=session,
            case=case,
            report=session.feedback_report,
            candidate_store=service.training_skill_candidate_store,
            skill_store=service.training_skill_store,
            event_store=service.training_event_store,
        )
    except TrainingSkillCandidateGenerationError:
        return build_generation_failed_personal_skill_payload(report=session.feedback_report, case=case)
    except Exception as exc:
        payload = build_generation_failed_personal_skill_payload(report=session.feedback_report, case=case)
        payload["generation_warnings"] = _append_report_generation_warning(
            session.feedback_report,
            module="personal_skill_generation",
            exc=exc,
        )
        return payload


def _deferred_optional_agent_payload(report: dict[str, Any], case: Case) -> dict[str, Any]:
    from app.services.personal_training_skill_service import build_teacher_reflection_review_payload

    return {
        "personal_skill_candidate": {
            "status": "generation_pending",
            "reason": "optional_agent_background_enrichment",
            "scope": "personal",
            "candidate_id": None,
            "skill_id": None,
            "web_check_status": "not_configured",
            "external_evidence_checks": [],
            "summary": "评分报告已生成；个人训练 Skill 正在后台生成，稍后刷新报告可查看。",
        },
        "ai_reflection_review": build_teacher_reflection_review_payload(report, case),
    }


def _append_report_generation_warning(
    report: dict[str, Any],
    *,
    module: str,
    exc: Exception,
) -> list[dict[str, str]]:
    warnings = list(report.get("generation_warnings") or [])
    warnings.append(
        {
            "module": module,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    )
    return warnings


def _ensure_report_training_progress_snapshot(
    report: dict[str, Any],
    session: OsceSession,
    case: Case,
) -> dict[str, Any]:
    if report.get("training_progress_snapshot"):
        return report
    return {
        **report,
        "training_progress_snapshot": _serialize_training_progress(session, case),
    }


def _ensure_report_procedure_simulation_audit_items(
    report: dict[str, Any],
    session: OsceSession | None,
) -> dict[str, Any]:
    audit_items = (
        session.procedure_simulation_audit_items
        if session is not None
        else report.get("procedure_simulation_audit_items", [])
    )
    return {
        **report,
        "procedure_simulation_audit_items": list(audit_items) if isinstance(audit_items, list) else [],
    }


def _report_needs_completed_session_hydration(report: dict[str, Any]) -> bool:
    ai_reflection_review = report.get("ai_reflection_review")
    personal_skill_candidate = report.get("personal_skill_candidate")
    ai_status = ai_reflection_review.get("status") if isinstance(ai_reflection_review, dict) else None
    skill_status = personal_skill_candidate.get("status") if isinstance(personal_skill_candidate, dict) else None
    return (
        ai_status != "generated"
        or _ai_reflection_review_uses_legacy_generic_text(ai_reflection_review)
        or skill_status in {None, "legacy_report", "not_complete", "generation_pending"}
    )


def _rehydrate_orphan_teacher_reflection(report: dict[str, Any]) -> dict[str, Any]:
    from app.services.personal_training_skill_service import build_teacher_reflection_review_payload

    case: Case | None = None
    case_id = str(report.get("case_id") or "")
    if case_id:
        try:
            case = load_case_node(case_id)
        except Exception:
            case = None
    return {
        **report,
        "ai_reflection_review": build_teacher_reflection_review_payload(report, case),
    }


def _ai_reflection_review_uses_legacy_generic_text(ai_reflection_review: Any) -> bool:
    if not isinstance(ai_reflection_review, dict):
        return True
    summary = str(ai_reflection_review.get("summary", ""))
    teacher_feedback = str(ai_reflection_review.get("teacher_feedback", ""))
    next_focus = str(ai_reflection_review.get("next_focus", ""))
    safety_note = str(ai_reflection_review.get("safety_note", ""))
    return (
        "本轮主要问题集中在" in summary
        or "建议下一轮先说明为什么要问、查或检验" in teacher_feedback
        or "下一轮 Coach" in next_focus
        or "AI 复盘" in safety_note
    )


def _report_generated_event_payload(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_id": report.get("report_id"),
        "total_score": report.get("total_score"),
        "missed_items": report.get("missed_items", []),
        "knowledge_recommendations": report.get("knowledge_recommendations", []),
        "source_references": report.get("source_references", []),
        "source_reference_items": report.get("source_reference_items", []),
        "personal_skill_candidate": report.get("personal_skill_candidate"),
        "ai_reflection_review": report.get("ai_reflection_review"),
        "procedure_simulation_audit_items": report.get("procedure_simulation_audit_items", []),
    }


def _ensure_personal_skill_report_defaults(
    report: dict[str, Any],
    candidate_store: Any | None = None,
) -> dict[str, Any]:
    normalized_report = dict(report)
    personal_skill_candidate = dict(
        normalized_report.get("personal_skill_candidate")
        or {
            "status": "legacy_report",
            "reason": "personal_skill_not_recorded",
            "scope": "personal",
            "candidate_id": None,
            "skill_id": None,
            "web_check_status": "not_configured",
            "external_evidence_checks": [],
        }
    )
    candidate_id = str(personal_skill_candidate.get("candidate_id") or "")
    if candidate_id and candidate_store is not None:
        stored_candidate = candidate_store.get_candidate(candidate_id)
        if stored_candidate is not None:
            personal_skill_candidate.setdefault("description", stored_candidate.get("description", ""))
            personal_skill_candidate.setdefault("suggested_strategy", stored_candidate.get("suggested_strategy", ""))
    personal_skill_candidate.setdefault("scope", "personal")
    personal_skill_candidate.setdefault("candidate_id", None)
    personal_skill_candidate.setdefault("skill_id", None)
    personal_skill_candidate.setdefault("rag_evidence_items", [])
    personal_skill_candidate.setdefault("web_check_status", "not_configured")
    personal_skill_candidate.setdefault("external_evidence_checks", [])
    normalized_report["personal_skill_candidate"] = personal_skill_candidate

    ai_reflection_review = dict(
        normalized_report.get("ai_reflection_review")
        or {
            "status": "legacy_report",
            "reason": "ai_reflection_not_recorded",
            "summary": "该历史报告生成时尚未记录教师复盘。",
        }
    )
    ai_reflection_review.setdefault("mistake_patterns", [])
    ai_reflection_review.setdefault("teacher_feedback", "")
    ai_reflection_review.setdefault("next_focus", "")
    ai_reflection_review.setdefault("source_references", [])
    ai_reflection_review.setdefault("source_reference_items", [])
    normalized_report["ai_reflection_review"] = ai_reflection_review
    return normalized_report


def _latest_agent_turn(graph_state: dict[str, Any]) -> dict[str, Any]:
    turn_memory = graph_state.get("agent_turn_memory", [])
    if isinstance(turn_memory, list) and turn_memory:
        for agent_turn in reversed(turn_memory):
            if not isinstance(agent_turn, dict):
                continue
            if str(agent_turn.get("turn_policy", "")).startswith("passive_review_"):
                continue
            return agent_turn
        latest_turn = turn_memory[-1]
        if isinstance(latest_turn, dict):
            return latest_turn
    return {}


def _primary_intent_from_graph_state(graph_state: dict[str, Any]) -> str:
    current_intents = graph_state.get("current_intents", [])
    if isinstance(current_intents, list) and current_intents:
        return str(current_intents[0])
    legacy_intent = str(graph_state.get("current_intent", "") or "")
    return legacy_intent or "unknown_history_intent"


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
        "active_skill_context": _empty_active_skill_context(),
        "agent_turn_memory": [],
        "action_timeline": [],
        "pedagogy_state": {},
        "agent_decision_trace": [],
        "reflection_summary": None,
    }


def _serialize_case_summary(case: Case) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "case_title": case.case_title,
        "course_module": case.course_module,
        "difficulty": case.difficulty,
        "chief_complaint": case.chief_complaint,
        "patient_opening_utterance": build_patient_opening_utterance(case.chief_complaint),
        "enabled": True,
        "content_stats": _serialize_case_content_stats(case),
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


def _build_procedure_catalog() -> dict[str, Any]:
    physical_exam_map: dict[str, dict[str, Any]] = {}
    auxiliary_test_map: dict[str, dict[str, Any]] = {}
    for case_path in sorted(CASES_DIR.glob("*.json")):
        case = load_case_node(case_path.stem)
        for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]:
            entry = physical_exam_map.setdefault(
                exam.exam_code,
                {
                    "exam_code": exam.exam_code,
                    "exam_name_cn": exam.exam_name_cn,
                    "category": _physical_exam_category(exam.exam_code),
                },
            )
        for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]:
            entry = auxiliary_test_map.setdefault(
                test.test_code,
                {
                    "test_code": test.test_code,
                    "test_name_cn": test.test_name_cn,
                    "category": test.category,
                    "invasiveness": test.invasiveness,
                    "cost_hint": test.cost_hint,
                },
            )
    return {
        "mode": "intermediate_catalog",
        "physical_exams": sorted(
            physical_exam_map.values(),
            key=lambda item: (item["category"], item["exam_name_cn"], item["exam_code"]),
        ),
        "auxiliary_tests": sorted(
            auxiliary_test_map.values(),
            key=lambda item: (item["category"], item["test_name_cn"], item["test_code"]),
        ),
        "safety_boundary": "目录只展示可申请项目名称，不包含病例结果、标准诊断或评分答案。",
    }


def _physical_exam_category(exam_code: str) -> str:
    if exam_code.startswith("vital."):
        return "生命体征"
    if exam_code.startswith("abd."):
        return "腹部查体"
    if exam_code.startswith(("lung.", "resp.")):
        return "心肺查体"
    if exam_code.startswith("neuro."):
        return "神经系统查体"
    if exam_code.startswith("thy."):
        return "甲状腺查体"
    if exam_code.startswith("ext."):
        return "四肢/外周查体"
    return "其他查体"


def _case_physical_exam_map(case: Case) -> dict[str, PhysicalExamItem]:
    return {exam.exam_code: exam for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]}


def _case_auxiliary_test_map(case: Case) -> dict[str, AuxiliaryTestItem]:
    return {test.test_code: test for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]}


def _catalog_physical_exam_map() -> dict[str, dict[str, Any]]:
    catalog = _build_procedure_catalog()
    return {str(item["exam_code"]): item for item in catalog["physical_exams"]}


def _catalog_auxiliary_test_map() -> dict[str, dict[str, Any]]:
    catalog = _build_procedure_catalog()
    return {str(item["test_code"]): item for item in catalog["auxiliary_tests"]}


PROCEDURE_REQUEST_SYNONYMS_BY_CODE: dict[str, list[str]] = {
    "abd.inspection": ["腹部视诊", "看腹部", "腹部外观"],
    "abd.palpation.tenderness": ["压痛", "腹部压痛", "麦氏点压痛", "mcburney", "mc burney"],
    "abd.palpation.rebound": ["反跳痛", "blumberg", "腹膜刺激"],
    "abd.palpation.guarding": ["肌紧张", "板状腹", "腹肌紧张"],
    "abd.special.rovsing": ["rovsing", "罗氏征"],
    "abd.special.psoas": ["腰大肌征", "psoas"],
    "ecg.st_segment": ["心电图", "心电", "ecg", "st段"],
    "ext.pitting_edema": ["下肢水肿", "凹陷性水肿", "腿肿"],
    "img.abd_ct": ["腹部ct", "腹部 ct", "阑尾ct", "ct"],
    "img.abd_us": ["腹部超声", "腹部彩超", "腹部b超", "腹部 b超", "b超"],
    "img.chest_xray": ["胸片", "胸部x线", "胸部 x线", "胸部x光", "胸部 x光"],
    "img.echo": ["超声心动图", "心脏彩超", "心超"],
    "img.thyroid_us": ["甲状腺超声", "甲状腺彩超"],
    "lab.bnp": ["bnp", "脑钠肽"],
    "lab.cbc": ["血常规", "白细胞", "中性粒", "血象"],
    "lab.crp": ["crp", "c反应蛋白", "c 反应蛋白", "炎症指标"],
    "lab.ft4": ["ft4", "游离甲状腺素"],
    "lab.troponin": ["肌钙蛋白", "肌红蛋白", "心肌酶"],
    "lab.tsh": ["tsh", "促甲状腺激素"],
    "lab.urinalysis": ["尿常规", "小便常规", "尿检"],
    "lung.auscultation.rales": ["肺部听诊", "听诊", "湿啰音", "啰音"],
    "neuro.hand_tremor": ["手颤", "手抖", "震颤"],
    "resp.auscultation.crackle": ["肺部听诊", "听诊", "湿啰音", "啰音"],
    "resp.rate": ["呼吸频率", "呼吸次数", "呼吸"],
    "thy.inspect.goiter": ["甲状腺视诊", "甲状腺肿大", "看甲状腺"],
    "vital.blood_pressure": ["血压", "测血压"],
    "vital.heart_rate": ["心率", "脉搏", "心跳"],
    "vital.temperature": ["体温", "发热", "测体温"],
}


def _standardize_procedure_request_text(request_text: str) -> dict[str, Any]:
    normalized_request = _normalize_procedure_request_text(request_text)
    matched_items: list[dict[str, Any]] = []
    matched_aliases: list[str] = []
    catalog = _build_procedure_catalog()
    for item in catalog["physical_exams"]:
        match = _match_procedure_catalog_item(normalized_request, item, code_key="exam_code", name_key="exam_name_cn")
        if match is not None:
            matched_items.append(
                {
                    "kind": "physical_exam",
                    "code": item["exam_code"],
                    "name_cn": item["exam_name_cn"],
                    "match_index": match["index"],
                    "matched_alias": match["alias"],
                }
            )
            matched_aliases.append(match["alias"])
    for item in catalog["auxiliary_tests"]:
        match = _match_procedure_catalog_item(normalized_request, item, code_key="test_code", name_key="test_name_cn")
        if match is not None:
            matched_items.append(
                {
                    "kind": "auxiliary_test",
                    "code": item["test_code"],
                    "name_cn": item["test_name_cn"],
                    "match_index": match["index"],
                    "matched_alias": match["alias"],
                }
            )
            matched_aliases.append(match["alias"])
    matched_items = sorted(matched_items, key=lambda item: (int(item["match_index"]), str(item["kind"]), str(item["code"])))
    matched_exam_codes = _dedupe_non_empty(
        [str(item["code"]) for item in matched_items if item["kind"] == "physical_exam"]
    )
    matched_test_codes = _dedupe_non_empty(
        [str(item["code"]) for item in matched_items if item["kind"] == "auxiliary_test"]
    )
    return {
        "matched_items": matched_items,
        "matched_exam_codes": matched_exam_codes,
        "matched_test_codes": matched_test_codes,
        "unmatched_requests": _extract_unmatched_procedure_terms(request_text, matched_aliases),
    }


def _match_procedure_catalog_item(
    normalized_request: str,
    item: dict[str, Any],
    *,
    code_key: str,
    name_key: str,
) -> dict[str, Any] | None:
    code = str(item[code_key])
    aliases = _procedure_aliases(code, str(item[name_key]), str(item.get("category") or ""))
    match_candidates: list[dict[str, Any]] = []
    for alias in aliases:
        if not _is_searchable_procedure_alias(alias):
            continue
        index = normalized_request.find(alias)
        if index >= 0:
            match_candidates.append({"alias": alias, "index": index})
    if not match_candidates:
        return None
    return sorted(match_candidates, key=lambda match: (int(match["index"]), -len(str(match["alias"]))))[0]


def _procedure_aliases(code: str, name: str, category: str) -> list[str]:
    aliases = [name, category, code, code.replace(".", " ")]
    aliases.extend(PROCEDURE_REQUEST_SYNONYMS_BY_CODE.get(code, []))
    aliases.extend(_split_procedure_label_terms(name))
    return _dedupe_non_empty([_normalize_procedure_request_text(alias) for alias in aliases])


def _split_procedure_label_terms(label: str) -> list[str]:
    terms = [label]
    terms.extend(re.split(r"[（）()、/·\-_\s]+", label))
    without_brackets = re.sub(r"[（(].*?[）)]", "", label)
    if without_brackets != label:
        terms.append(without_brackets)
    bracket_terms = re.findall(r"[（(](.*?)[）)]", label)
    terms.extend(bracket_terms)
    return terms


def _normalize_procedure_request_text(value: str) -> str:
    return re.sub(r"[\s，,。；;：:、/\\（）()\[\]{}<>《》“”\"'`~!！?？+-]+", "", value.lower())


def _is_searchable_procedure_alias(alias: str) -> bool:
    if len(alias) >= 2 and not alias.isascii():
        return True
    return alias in {"ct", "b超"} or len(alias) >= 3


def _extract_unmatched_procedure_terms(request_text: str, matched_aliases: list[str]) -> list[str]:
    matched_aliases = _dedupe_non_empty(matched_aliases)
    chunks = re.split(
        r"和|及|与|并|再|看看|看一下|查一下|查个|检查|申请|做|测|查|要|想|请|，|,|、|；|;|。|\s+",
        request_text,
    )
    ignored_terms = {"我", "我想", "一下", "一个", "相关", "项目", "结果", "还有", "一下子"}
    unmatched: list[str] = []
    for chunk in chunks:
        term = chunk.strip()
        normalized_term = _normalize_procedure_request_text(term)
        if len(normalized_term) < 2 or normalized_term in ignored_terms:
            continue
        if any(
            normalized_term == alias
            or normalized_term in alias
            or alias in normalized_term
            for alias in matched_aliases
        ):
            continue
        if normalized_term not in [_normalize_procedure_request_text(value) for value in unmatched]:
            unmatched.append(term)
    return unmatched


def _build_standardized_procedure_results(
    matched_items: list[dict[str, Any]],
    exam_result_map: dict[str, dict[str, Any]],
    test_result_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in matched_items:
        code = str(item["code"])
        if item["kind"] == "physical_exam":
            result = exam_result_map.get(code)
            availability_status = str(result.get("availability_status")) if result is not None else "not_available_for_case"
            results.append(
                {
                    "id": f"exam:{code}",
                    "kind": "physical_exam",
                    "code": code,
                    "name_cn": str(item["name_cn"]),
                    "label": f"查体：{item['name_cn']}",
                    "result": str(result.get("result")) if result is not None else "该项目已记录，但本训练站点未提供该查体结果。",
                    "availability_status": availability_status,
                    "generated_by_ai": False,
                    "approval_status": "not_required",
                    "source_context_references": [],
                    "scoring_eligible": availability_status == "case_configured",
                }
            )
        if item["kind"] == "auxiliary_test":
            result = test_result_map.get(code)
            availability_status = str(result.get("availability_status")) if result is not None else "not_available_for_case"
            results.append(
                {
                    "id": f"test:{code}",
                    "kind": "auxiliary_test",
                    "code": code,
                    "name_cn": str(item["name_cn"]),
                    "label": f"检查：{item['name_cn']}",
                    "result": str(result.get("result")) if result is not None else "该项目已记录，但本训练站点未提供该辅助检查结果。",
                    "availability_status": availability_status,
                    "generated_by_ai": False,
                    "approval_status": "not_required",
                    "source_context_references": [],
                    "scoring_eligible": availability_status == "case_configured",
                }
            )
    return results


def _procedure_simulation_audit_items_from_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audit_items: list[dict[str, Any]] = []
    for result in results:
        if result.get("generated_by_ai") is not True:
            continue
        source_context_references = [
            str(reference)
            for reference in result.get("source_context_references", [])
            if str(reference).strip()
        ]
        audit_items.append(
            {
                "procedure_id": str(result.get("id") or ""),
                "kind": _procedure_audit_kind(str(result.get("kind") or "")),
                "code": str(result.get("code") or ""),
                "label": str(result.get("name_cn") or result.get("label") or result.get("code") or ""),
                "result": str(result.get("result") or ""),
                "approval_status": str(result.get("approval_status") or ""),
                "approval_agent_review": _normalize_procedure_simulation_approval_review(
                    result.get("approval_agent_review", {})
                ),
                "source_context_references": source_context_references,
                "scoring_eligible": result.get("scoring_eligible") is True,
                "safety_boundary": PROCEDURE_SIMULATION_SAFETY_BOUNDARY,
            }
        )
    return audit_items


def _normalize_procedure_simulation_approval_review(review: Any) -> dict[str, Any]:
    if hasattr(review, "model_dump"):
        review = review.model_dump()
    if not isinstance(review, dict):
        review = {}
    safety_issues = [
        str(item)
        for item in review.get("safety_issues", [])
        if str(item).strip()
    ]
    return {
        "agent_id": str(review.get("agent_id") or "procedure_result_approval_agent"),
        "decision": str(review.get("decision") or "approved"),
        "approval_mode": str(review.get("approval_mode") or "deterministic_safety_gate"),
        "rationale": str(review.get("rationale") or ""),
        "safety_issues": safety_issues,
        "revised_result": str(review.get("revised_result") or ""),
    }


def _procedure_approval_error_fallback_review(
    simulation_text: str,
    forbidden_terms: list[str],
) -> dict[str, Any]:
    safety_issues = [
        f"包含受保护词：{term}"
        for term in forbidden_terms
        if term and term in simulation_text
    ]
    if safety_issues:
        return {
            "agent_id": "procedure_result_approval_agent",
            "decision": "blocked",
            "approval_mode": "approval_agent_error_fallback",
            "rationale": "审批 Agent 调用失败，本地安全门禁发现受保护内容，已阻断展示。",
            "safety_issues": safety_issues,
            "revised_result": "",
        }
    return {
        "agent_id": "procedure_result_approval_agent",
        "decision": "approved",
        "approval_mode": "approval_agent_error_fallback",
        "rationale": "审批 Agent 调用失败，已使用本地安全门禁降级审核。",
        "safety_issues": [],
        "revised_result": "",
    }


def _procedure_audit_kind(kind: str) -> str:
    if kind == "auxiliary_test":
        return "test"
    if kind == "physical_exam":
        return "exam"
    return kind


def _merge_procedure_simulation_audit_items(
    existing_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged_by_id: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []
    for item in [*existing_items, *new_items]:
        procedure_id = str(item.get("procedure_id") or "")
        if not procedure_id:
            continue
        if procedure_id not in merged_by_id:
            ordered_ids.append(procedure_id)
        merged_by_id[procedure_id] = dict(item)
    return [merged_by_id[procedure_id] for procedure_id in ordered_ids]


def _retrieve_procedure_simulation_context(
    *,
    case: Case,
    request_text: str,
    procedure_result: dict[str, Any],
    forbidden_terms: list[str],
) -> list[dict[str, Any]]:
    try:
        return retrieve_agent_context(
            agent_role="coach",
            case_ids=[case.case_id],
            query_terms=[
                case.chief_complaint,
                request_text,
                str(procedure_result.get("name_cn", "")),
                str(procedure_result.get("code", "")),
            ],
            allowed_visibilities={"pre_submit_safe"},
            forbidden_terms=forbidden_terms,
            limit=3,
        )
    except Exception:
        return []


def _procedure_simulation_patient_context(case: Case) -> dict[str, Any]:
    return {
        "age": f"{case.patient_profile.age_value}{case.patient_profile.age_unit}",
        "gender": case.patient_profile.gender,
        "occupation": case.patient_profile.occupation,
        "department": case.patient_profile.hospital_department,
        "chief_complaint": case.chief_complaint,
        "present_illness_summary": case.history.present_illness_summary,
        "history_facts": [
            {
                "topic": fact.topic,
                "slot": fact.slot,
                "answer": fact.canonical_answer,
            }
            for fact in case.history.hidden_facts
        ],
    }


def _procedure_simulation_configured_results(case: Case) -> list[dict[str, str]]:
    configured_results: list[dict[str, str]] = []
    for item in [*case.physical_exam.must_items, *case.physical_exam.optional_items]:
        configured_results.append(
            {
                "kind": "physical_exam",
                "code": item.exam_code,
                "name_cn": item.exam_name_cn,
                "result": item.result,
            }
        )
    for item in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]:
        configured_results.append(
            {
                "kind": "auxiliary_test",
                "code": item.test_code,
                "name_cn": item.test_name_cn,
                "result": item.result,
            }
        )
    return configured_results


def _procedure_forbidden_terms(case: Case) -> list[str]:
    return [
        case.diagnosis.main_diagnosis,
        *case.diagnosis.main_diagnosis_synonyms,
        *[differential.disease_name for differential in case.diagnosis.differential_diagnoses],
        "治疗方案",
        "用药剂量",
        "手术方案",
        "处置建议",
        "标准答案",
        "rubric",
    ]


def _sanitize_simulated_procedure_result(result: str, forbidden_terms: list[str]) -> str:
    sanitized = re.sub(r"\s+", " ", result).strip()
    for term in forbidden_terms:
        if term:
            sanitized = sanitized.replace(term, "相关诊断")
    for unsafe_term in ["治疗方案", "用药剂量", "手术方案", "处置建议"]:
        sanitized = sanitized.replace(unsafe_term, "真实处置")
    if not sanitized:
        return ""
    if len(sanitized) > 160:
        sanitized = f"{sanitized[:157]}..."
    return sanitized


def _dedupe_non_empty(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _relabel_latest_action_timeline_event(
    session: OsceSession,
    *,
    action_type: str,
    source_id: str,
    label: str,
) -> None:
    for event in reversed(session.action_timeline):
        if event.get("action_type") == action_type and event.get("source_id") == source_id:
            event["label"] = label
            return


def _serialize_case_content_stats(case: Case) -> dict[str, int]:
    history_clue_count = len(case.history.hidden_facts)
    physical_exam_count = len(case.physical_exam.must_items) + len(case.physical_exam.optional_items)
    auxiliary_test_count = len(case.auxiliary_tests.must_items) + len(case.auxiliary_tests.optional_items)
    return {
        "history_clue_count": history_clue_count,
        "physical_exam_count": physical_exam_count,
        "auxiliary_test_count": auxiliary_test_count,
        "total_training_items": history_clue_count + physical_exam_count + auxiliary_test_count,
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


def _serialize_auxiliary_test_quick_option(test: AuxiliaryTestItem) -> dict[str, Any]:
    return {
        "test_code": test.test_code,
        "test_name_cn": test.test_name_cn,
        "category": test.category,
        "invasiveness": test.invasiveness,
        "cost_hint": test.cost_hint,
        "diagnostic_role": test.diagnostic_role,
        "rules_out": test.rules_out,
        "recommended_stage": test.recommended_stage,
        "overuse_warning": test.overuse_warning,
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
        "invasiveness": test.invasiveness,
        "cost_hint": test.cost_hint,
        "diagnostic_role": test.diagnostic_role,
        "rules_out": test.rules_out,
        "recommended_stage": test.recommended_stage,
        "overuse_warning": test.overuse_warning,
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


def _serialize_coverage_map(session: OsceSession, case: Case, reasoning_evidence: list[str]) -> dict[str, list[dict[str, Any]]]:
    return {
        "history": [
            _coverage_map_item(
                _student_safe_evidence_id(case, fact.fact_id),
                fact.canonical_answer,
                fact.fact_id in session.revealed_facts,
                extra={
                    "topic": fact.topic,
                    "slot": fact.slot,
                    "linked_rubric_items": list(fact.linked_rubric_items),
                },
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


def _coverage_map_item(item_id: str, label: str, is_covered: bool, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"id": item_id, "label": label, "status": "covered" if is_covered else "pending"}
    if extra:
        item.update(extra)
    return item


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


def _enabled_skill_prompts_from_active_context(active_skill_context: dict[str, Any]) -> list[str]:
    selected_skills = active_skill_context.get("selected_skills", [])
    if not isinstance(selected_skills, list):
        return []
    prompts: list[str] = []
    for skill in selected_skills:
        if not isinstance(skill, dict):
            continue
        title = str(skill.get("title") or "").strip()
        strategy = str(skill.get("suggested_strategy") or "").strip()
        if title and strategy:
            prompts.append(f"{title}：{strategy}")
        elif title:
            prompts.append(title)
        elif strategy:
            prompts.append(strategy)
    return prompts


def _current_missing_evidence(session: OsceSession) -> list[str]:
    if session.missed_items:
        return [str(item_id) for item_id in session.missed_items if str(item_id)]
    feedback_report = session.feedback_report
    if not isinstance(feedback_report, dict):
        return []
    missing_items = feedback_report.get("missing_items", [])
    if not isinstance(missing_items, list):
        return []
    return [str(item_id) for item_id in missing_items if str(item_id)]


def _enabled_skills_for_case(
    skills: list[dict[str, Any]],
    case: Case,
    stage: str = "case_intro",
    student_id: str = "",
) -> list[dict[str, Any]]:
    case_id = case.case_id
    rubric_item_ids = _rubric_item_ids(case_id)
    return [
        skill
        for skill in skills
        if _enabled_skill_applies_to_case(skill, case_id, rubric_item_ids)
        and _enabled_skill_applies_to_student(skill, student_id)
        and _enabled_skill_applies_to_stage(skill, stage)
        and _enabled_skill_matches_current_missing_evidence(skill, rubric_item_ids)
        and _enabled_skill_context_matches_case(skill, case)
    ]


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


def _enabled_skill_applies_to_student(skill: dict[str, Any], student_id: str) -> bool:
    if str(skill.get("scope", "global")) != "personal":
        return True
    return bool(student_id) and str(skill.get("owner_student_id", "")) == student_id


def _enabled_skill_applies_to_stage(skill: dict[str, Any], stage: str) -> bool:
    applies_when = skill.get("applies_when", {})
    if not isinstance(applies_when, dict):
        applies_when = {}
    stage_scope = [str(stage_name) for stage_name in skill.get("stage_scope") or applies_when.get("stage_scope", [])]
    if stage == "history_taking" and "case_intro" in stage_scope:
        return True
    return not stage_scope or "any" in stage_scope or stage in stage_scope


def _enabled_skill_matches_current_missing_evidence(skill: dict[str, Any], rubric_item_ids: set[str]) -> bool:
    applies_when = skill.get("applies_when", {})
    if not isinstance(applies_when, dict):
        applies_when = {}
    current_missing_evidence = [
        str(item_id)
        for item_id in applies_when.get("current_missing_evidence", skill.get("trigger_item_ids", []))
    ]
    if not current_missing_evidence:
        return True
    return bool(set(current_missing_evidence) & rubric_item_ids)


def _enabled_skill_context_matches_case(skill: dict[str, Any], case: Case) -> bool:
    if case.patient_profile.gender == "男" and _skill_contains_any_term(skill, _FEMALE_REPRODUCTIVE_TERMS):
        return False
    return True


_FEMALE_REPRODUCTIVE_TERMS = [
    "妇科",
    "妊娠",
    "怀孕",
    "宫外孕",
    "异位妊娠",
    "孕产",
    "月经",
    "停经",
    "阴道",
    "ectopic",
    "pregnancy",
    "pregnant",
    "gynecologic",
    "gynecology",
    "obstetric",
]


def _skill_contains_any_term(value: Any, terms: list[str]) -> bool:
    if isinstance(value, str):
        normalized = value.lower()
        return any(term.lower() in normalized for term in terms)
    if isinstance(value, dict):
        return any(
            _skill_contains_any_term(key, terms) or _skill_contains_any_term(item, terms)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_skill_contains_any_term(item, terms) for item in value)
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


def _normalize_training_difficulty(training_difficulty: str) -> str:
    normalized = str(training_difficulty or "beginner").strip()
    return normalized if normalized in TRAINING_DIFFICULTY_MODES else "beginner"


def _serialize_session(session: OsceSession, case: Case) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "student_id": session.student_id,
        "case_id": session.case_id,
        "stage": session.stage,
        "training_difficulty": session.training_difficulty,
        "case_title": case.case_title,
        "chief_complaint": case.chief_complaint,
        "patient_opening_utterance": build_patient_opening_utterance(case.chief_complaint),
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
        "active_skill_context": session.active_skill_context or _empty_active_skill_context(),
        "agent_turn_memory": session.agent_turn_memory,
        "action_timeline": session.action_timeline,
        "pedagogy_state": session.pedagogy_state,
        "agent_decision_trace": session.agent_decision_trace,
        "reflection_summary": session.reflection_summary,
        "procedure_simulation_audit_items": session.procedure_simulation_audit_items,
    }


def _empty_active_skill_context() -> dict[str, list[dict[str, Any]]]:
    return {"skill_index": [], "selected_skills": [], "skipped_reasons": []}


osce_session_service = OsceSessionService()
