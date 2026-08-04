from __future__ import annotations

import json
import re
import hashlib
import traceback
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, fields
from functools import wraps
from pathlib import Path
from threading import Lock, RLock
from typing import Any, TypeVar, cast
from uuid import uuid4

import yaml

from app.graph.osce_graph import build_osce_graph, reflection_node, training_strategy_node
from app.models.case import AuxiliaryTestItem, Case, PhysicalExamItem
from app.services.osce_session_store import (
    SESSION_DELETION_CLEANUP_VERSION,
    OsceSessionStore,
    SessionCreatePreparationConflictError,
    SessionDeletionRecord,
    SessionDerivedReferenceOwnershipError,
    SessionOutboxEvent,
    SessionOutboxItem,
    SessionPersistenceError,
    SessionNotFoundError,
    osce_session_store,
)
from app.services.patient_affect_state_service import build_initial_patient_affect_state
from app.services.patient_language_service import build_patient_opening_utterance
from app.services.procedure_result_simulation_service import (
    PROCEDURE_SIMULATION_SAFETY_BOUNDARY,
    ProcedureResultSimulationService,
    merge_procedure_simulation_audit_items,
)
from app.services.procedure_request_router import (
    ProcedureRequestRoutingRequest,
    create_default_procedure_request_router,
)
from app.services.deep_report_analysis_service import build_legacy_deep_report_analysis
from app.services.model_call_policy import (
    ModelProviderOverloadedError,
    ModelProviderPolicyError,
    ModelProviderTimeoutError,
)
from app.services.report_store import (
    ReportClaimLostError,
    ReportOutboxEvent,
    ReportStore,
    report_store,
)
from app.services.student_profile_store import StudentProfileStore, student_profile_store
from app.services.training_event_store import (
    TrainingEventDeletedSkillSourceError,
    TrainingEventReferenceOwnershipError,
    TrainingEventStore,
    training_event_store,
)
from app.services.training_skill_candidate_store import (
    TrainingSkillCandidateOwnershipError,
    TrainingSkillCandidateStore,
    training_skill_candidate_store,
)
from app.services.student_profile_summary_service import build_skill_profile_summary
from app.services.teacher_intervention_service import (
    TeacherInterventionMode,
    append_teacher_decision_record,
    latest_student_safe_intervention,
    resolve_teacher_intervention,
)
from app.services.training_skill_orchestrator_service import build_active_skill_context
from app.services.training_skill_store import (
    TrainingSkillOwnershipError,
    TrainingSkillStore,
    training_skill_store,
)
from app.services.rule_evaluator import LlmRubricScorer
from app.services.runtime_model_object_cache import RuntimeModelObjectCache
from app.services.session_resource_policy import (
    MAX_HINT_REQUESTS_PER_SESSION,
    MAX_HYPOTHESIS_RECORDS_PER_SESSION,
    MAX_STUDENT_TURNS_PER_SESSION,
    SessionResourceLimitError,
)
from app.services.vertex_gemini_scorer import create_default_vertex_gemini_scorer
from app.validators.case_validator import validate_case

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"
RUBRICS_DIR = ROOT_DIR / "data" / "rubrics"
PROCEDURE_REQUEST_ADVANCED_ONLY_DETAIL = "free-text procedure requests require advanced training"
TRAINING_DIFFICULTY_MODES = {"beginner", "intermediate", "advanced"}
MAX_RUNTIME_ERROR_FIELD_LENGTH = 12000
MAX_PROCEDURE_CODES_PER_REQUEST = 64
MAX_REQUESTED_PROCEDURES_PER_KIND = 64
MAX_PROCEDURE_CODE_LENGTH = 64
SESSION_EVENT_STORE_BUSY_TIMEOUT_MILLISECONDS = 100


class ProcedureRequestTrainingModeError(RuntimeError):
    pass


class InvalidProcedureRequestError(ValueError):
    def __init__(self, procedure_kind: str) -> None:
        super().__init__(f"invalid {procedure_kind} request")
        self.procedure_kind = procedure_kind


class UnknownProcedureCodeError(ValueError):
    def __init__(self, procedure_kind: str) -> None:
        super().__init__(f"unknown {procedure_kind} code")
        self.procedure_kind = procedure_kind


class ProcedureRequestLimitError(RuntimeError):
    def __init__(self, procedure_kind: str) -> None:
        super().__init__(f"{procedure_kind} request limit reached")
        self.procedure_kind = procedure_kind


class SessionClosedError(RuntimeError):
    pass


class SessionDeletionConflictError(RuntimeError):
    """A personal artifact does not belong to the session being deleted."""


@dataclass
class _SessionLockEntry:
    lock: RLock = field(default_factory=RLock)
    holders_and_waiters: int = 0


class _SessionLockRegistry:
    """Keep one re-entrant lock per active session operation.

    The reference count is incremented before waiting on the session lock, so an
    entry cannot be removed and recreated while another thread is queued on the
    old lock.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _SessionLockEntry] = {}
        self._registry_lock = Lock()

    @contextmanager
    def hold(self, session_id: str) -> Iterator[None]:
        with self._registry_lock:
            entry = self._entries.setdefault(session_id, _SessionLockEntry())
            entry.holders_and_waiters += 1
        entry.lock.acquire()
        try:
            yield
        finally:
            entry.lock.release()
            with self._registry_lock:
                entry.holders_and_waiters -= 1
                if (
                    entry.holders_and_waiters == 0
                    and self._entries.get(session_id) is entry
                ):
                    del self._entries[session_id]

    def active_entry_count(self) -> int:
        with self._registry_lock:
            return len(self._entries)


_SessionOperation = TypeVar("_SessionOperation", bound=Callable[..., Any])


def _serialize_session_operation(method: _SessionOperation) -> _SessionOperation:
    @wraps(method)
    def wrapped(
        self: OsceSessionService,
        session_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        with self._session_locks.hold(session_id):
            return method(self, session_id, *args, **kwargs)

    return cast(_SessionOperation, wrapped)


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
    patient_affect_state: dict[str, Any] = field(default_factory=build_initial_patient_affect_state)
    pedagogy_state: dict[str, Any] = field(default_factory=dict)
    agent_decision_trace: list[dict[str, Any]] = field(default_factory=list)
    teacher_decision_records: list[dict[str, Any]] = field(default_factory=list)
    reflection_summary: dict[str, Any] | None = None
    procedure_simulation_audit_items: list[dict[str, Any]] = field(default_factory=list)
    student_turn_count: int = 0
    hint_request_count: int = 0
    hypothesis_record_count: int = 0


@dataclass
class _CachedSession:
    session: OsceSession
    revision: int


@dataclass
class _ProcedureCodeOperation:
    session: OsceSession
    working_session: OsceSession | None
    case: Case
    exam_results: list[dict[str, Any]]
    test_results: list[dict[str, Any]]
    agent_updates: list[dict[str, Any]]
    new_exam_codes: list[str]
    new_test_codes: list[str]


def _refresh_session_in_place(target: OsceSession, source: OsceSession) -> None:
    for session_field in fields(OsceSession):
        setattr(target, session_field.name, getattr(source, session_field.name))


def _require_open_session(session: OsceSession) -> None:
    if (
        session.final_submission is not None
        or session.feedback_report is not None
        or session.stage in {"diagnosis_submission", "feedback"}
    ):
        raise SessionClosedError("训练已结束，请查看报告。")


def _effective_student_turn_count(session: OsceSession) -> int:
    message_count = sum(
        isinstance(message, dict) and message.get("role") == "student"
        for message in session.messages
    )
    memory_count = sum(
        _is_primary_student_turn_memory(turn)
        for turn in session.agent_turn_memory
    )
    return max(
        max(0, session.student_turn_count),
        message_count,
        memory_count,
    )


def _is_primary_student_turn_memory(turn: Any) -> bool:
    if not isinstance(turn, dict):
        return False
    student_message = str(turn.get("student_message") or "").strip()
    turn_policy = str(turn.get("turn_policy") or "")
    if not student_message or student_message == "请求提示":
        return False
    if turn_policy == "intent_short_circuit_hint" or turn_policy.startswith(
        "passive_review_"
    ):
        return False
    return not _is_explicit_hint_turn(turn)


def _is_explicit_hint_turn(turn: Any) -> bool:
    if not isinstance(turn, dict):
        return False
    current_intents = turn.get("current_intents")
    if (
        isinstance(current_intents, list)
        and "socratic_hint" in current_intents
    ):
        return True
    if str(turn.get("current_intent") or "") == "socratic_hint":
        return True
    return (
        str(turn.get("student_message") or "").strip() == "请求提示"
        and str(turn.get("turn_policy") or "").startswith("teaching_hint")
    )


def _effective_hint_request_count(session: OsceSession) -> int:
    memory_count = sum(
        _is_explicit_hint_turn(turn)
        for turn in session.agent_turn_memory
    )
    return max(
        max(0, session.hint_request_count),
        memory_count,
    )


def _effective_hypothesis_record_count(session: OsceSession) -> int:
    return max(
        max(0, session.hypothesis_record_count),
        len(session.student_hypotheses),
    )


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
        procedure_request_router: Any | None = None,
        procedure_result_simulator: Any | None = None,
        procedure_result_approval_agent: Any | None = None,
        procedure_result_simulation_service: Any | None = None,
    ) -> None:
        self._sessions: dict[str, _CachedSession] = {}
        self._session_locks = _SessionLockRegistry()
        self._runtime_llm_scorer_cache: RuntimeModelObjectCache[LlmRubricScorer | None] | None = None
        if graph is not None:
            self.osce_graph = graph
        else:
            runtime_llm_scorer_cache: RuntimeModelObjectCache[LlmRubricScorer | None] = (
                RuntimeModelObjectCache()
            )
            self._runtime_llm_scorer_cache = runtime_llm_scorer_cache
            self.osce_graph = build_osce_graph(
                llm_scorer_factory=lambda: runtime_llm_scorer_cache.get_or_create(
                    create_default_vertex_gemini_scorer
                ),
                patient_responder=patient_responder,
            )
        self.report_store = report_store
        self.training_event_store = training_event_store
        self.training_skill_store = training_skill_store
        self.training_skill_candidate_store = training_skill_candidate_store
        self.session_store = session_store
        self.student_profile_store = student_profile_store
        self.personal_skill_service = personal_skill_service
        self.procedure_request_router = procedure_request_router or create_default_procedure_request_router()
        self.procedure_result_simulation_service = (
            procedure_result_simulation_service
            or ProcedureResultSimulationService(
                procedure_result_simulator=procedure_result_simulator,
                procedure_result_approval_agent=procedure_result_approval_agent,
            )
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
        rubric_item_ids = _rubric_item_ids(case.case_id)
        session = OsceSession(
            session_id=str(uuid4()),
            student_id=student_id,
            case_id=graph_state["case_id"],
            stage=graph_state["stage"],
            training_difficulty=_normalize_training_difficulty(training_difficulty),
        )
        for create_attempt in range(3):
            all_enabled_skills = (
                self.training_skill_store.list_enabled_skills()
            )
            student_profile = self._build_skill_profile_summary(
                student_id,
                all_enabled_skills,
            )
            enabled_skills = _enabled_skills_for_case(
                all_enabled_skills,
                case,
                session.stage,
                student_id,
            )
            session.evolution_candidates = _enabled_skill_prompts(
                enabled_skills
            )
            session.active_skill_context = build_active_skill_context(
                all_enabled_skills,
                case_id=case.case_id,
                student_id=student_id,
                stage=session.stage,
                rubric_item_ids=rubric_item_ids,
                student_profile=student_profile,
                patient_profile={"gender": case.patient_profile.gender},
            )
            prepared = self.session_store.prepare_session_for_create(session)
            _refresh_session_in_place(
                session,
                OsceSession(**prepared.payload),
            )
            session.pedagogy_state = {}
            session.agent_decision_trace = []
            session.teacher_decision_records = []
            agent_update = _refresh_agent_state(session)
            selected_skill_ids = _selected_skill_ids(
                session.active_skill_context
            )
            enabled_skills = [
                skill
                for skill in enabled_skills
                if str(skill.get("skill_id", "")) in selected_skill_ids
            ]
            try:
                self._create_session(
                    session,
                    outbox_events=self._build_session_creation_outbox_events(
                        session,
                        agent_update,
                        enabled_skills,
                    ),
                    expected_deleted_skill_sources_version=(
                        prepared.deleted_skill_sources_version
                    ),
                )
            except SessionCreatePreparationConflictError:
                if create_attempt == 2:
                    raise
                continue
            break
        latest_session = self._get_session(session.session_id)
        if latest_session is None:
            raise SessionNotFoundError(session.session_id)
        session = latest_session
        return _serialize_session(session, case)

    @_serialize_session_operation
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

    @_serialize_session_operation
    def handle_message(self, session_id: str, message: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        _require_open_session(session)
        student_turn_count = max(
            _effective_student_turn_count(session),
            self._count_session_events_best_effort(
                session_id,
                event_types=[
                    "history_message",
                    "safety_boundary_triggered",
                    "answer_request_redirected",
                ],
            ),
        )
        if student_turn_count >= MAX_STUDENT_TURNS_PER_SESSION:
            raise SessionResourceLimitError("message")
        working_session = deepcopy(session)
        self.begin_message_processing_status(session_id)
        try:
            self._refresh_active_skill_context(working_session)
            graph_state = self.osce_graph.invoke(
                _graph_state_from_session(
                    working_session,
                    message,
                    processing_progress_callback=lambda event: self.update_message_processing_status(
                        session_id,
                        step_id=str(event.get("step_id") or ""),
                        label=str(event.get("label") or event.get("step_id") or ""),
                        status=str(event.get("status") or "active"),
                    ),
                )
            )
            _apply_graph_state(working_session, graph_state)
            working_session.student_turn_count = student_turn_count + 1
            self._refresh_active_skill_context(working_session)
            agent_update = _refresh_agent_state(working_session)
            primary_intent = _primary_intent_from_graph_state(graph_state)
            if primary_intent == "safety_boundary":
                business_event = SessionOutboxEvent(
                    event_type="safety_boundary_triggered",
                    payload={
                        "message": message,
                        "safety_flag": graph_state["safety_flags"][-1],
                        "reply": graph_state["reply"],
                        "agent_turn": _latest_agent_turn(graph_state),
                    },
                )
            elif primary_intent == "answer_request_redirect":
                business_event = SessionOutboxEvent(
                    event_type="answer_request_redirected",
                    payload={
                        "message": message,
                        "reply": graph_state["reply"],
                        "agent_turn": _latest_agent_turn(graph_state),
                    },
                )
            else:
                business_event = SessionOutboxEvent(
                    event_type="history_message",
                    payload={
                        "message": message,
                        "current_intents": list(
                            graph_state.get("current_intents", [])
                        ),
                        "reply": graph_state["reply"],
                        "agent_turn": _latest_agent_turn(graph_state),
                    },
                )
            self._commit_working_session(
                session,
                working_session,
                outbox_events=[
                    business_event,
                    self._build_agent_update_outbox_event(
                        working_session,
                        agent_update,
                    ),
                ],
            )
            self.complete_message_processing_status(session_id)
        except SessionPersistenceError:
            self.complete_message_processing_status(session_id, errored=True)
            raise
        except Exception as exc:
            self.complete_message_processing_status(session_id, errored=True)
            trace_id = self._append_runtime_error_event(
                session,
                operation="message",
                exc=exc,
                extra_payload={"student_message": message},
            )
            setattr(exc, "osce_runtime_trace_id", trace_id)
            raise
        payload = _serialize_session(session, load_case_node(session.case_id))
        payload["reply"] = graph_state["reply"]
        payload["current_intents"] = list(graph_state.get("current_intents", []))
        return payload

    @_serialize_session_operation
    def request_physical_exam(self, session_id: str, exam_code: str) -> dict[str, Any] | None:
        operation = self._request_physical_exam_codes(
            session_id,
            [exam_code],
            require_single=True,
        )
        if operation is None:
            return None
        session, case, exam_results, _agent_update = operation
        exam_result = exam_results[0]
        payload = _serialize_session(session, case)
        payload.update(
            {
                "exam_code": exam_result["exam_code"],
                "exam_name_cn": exam_result["exam_name_cn"],
                "result": exam_result["result"],
            }
        )
        return payload

    @_serialize_session_operation
    def request_physical_exams(self, session_id: str, exam_codes: list[str]) -> dict[str, Any] | None:
        operation = self._request_physical_exam_codes(session_id, exam_codes)
        if operation is None:
            return None
        session, case, exam_results, _agent_update = operation
        payload = _serialize_session(session, case)
        payload["exam_results"] = exam_results
        return payload

    def _request_physical_exam_codes(
        self,
        session_id: str,
        exam_codes: list[str],
        *,
        require_single: bool = False,
    ) -> tuple[OsceSession, Case, list[dict[str, Any]], dict[str, Any] | None] | None:
        operation = self._request_procedure_codes(
            session_id,
            exam_codes=exam_codes,
            test_codes=[],
            require_single_exam=require_single,
        )
        if operation is None:
            return None
        agent_update = (
            operation.agent_updates[-1]
            if operation.agent_updates
            else None
        )
        if operation.working_session is not None:
            if agent_update is None:
                raise RuntimeError("procedure update is missing agent state")
            exam_result = operation.exam_results[0] if require_single else None
            business_event = SessionOutboxEvent(
                event_type=(
                    "physical_exam_requested"
                    if require_single
                    else "physical_exams_requested"
                ),
                payload=(
                    {
                        "exam_code": exam_result["exam_code"],
                        "result": exam_result["result"],
                    }
                    if exam_result is not None
                    else {"exam_results": operation.exam_results}
                ),
            )
            self._commit_working_session(
                operation.session,
                operation.working_session,
                outbox_events=[
                    business_event,
                    self._build_agent_update_outbox_event(
                        operation.working_session,
                        agent_update,
                    ),
                ],
            )
        return (
            operation.session,
            operation.case,
            operation.exam_results,
            agent_update,
        )

    @_serialize_session_operation
    def request_auxiliary_test(self, session_id: str, test_code: str) -> dict[str, Any] | None:
        operation = self._request_auxiliary_test_codes(
            session_id,
            [test_code],
            require_single=True,
        )
        if operation is None:
            return None
        session, case, test_results, _agent_update = operation
        test_result = test_results[0]
        payload = _serialize_session(session, case)
        payload.update(
            {
                "test_code": test_result["test_code"],
                "test_name_cn": test_result["test_name_cn"],
                "result": test_result["result"],
            }
        )
        return payload

    @_serialize_session_operation
    def request_auxiliary_tests(self, session_id: str, test_codes: list[str]) -> dict[str, Any] | None:
        operation = self._request_auxiliary_test_codes(session_id, test_codes)
        if operation is None:
            return None
        session, case, test_results, _agent_update = operation
        payload = _serialize_session(session, case)
        payload["test_results"] = test_results
        return payload

    def _request_auxiliary_test_codes(
        self,
        session_id: str,
        test_codes: list[str],
        *,
        require_single: bool = False,
    ) -> tuple[OsceSession, Case, list[dict[str, Any]], dict[str, Any] | None] | None:
        operation = self._request_procedure_codes(
            session_id,
            exam_codes=[],
            test_codes=test_codes,
            require_single_test=require_single,
        )
        if operation is None:
            return None
        agent_update = (
            operation.agent_updates[-1]
            if operation.agent_updates
            else None
        )
        if operation.working_session is not None:
            if agent_update is None:
                raise RuntimeError("procedure update is missing agent state")
            test_result = operation.test_results[0] if require_single else None
            business_event = SessionOutboxEvent(
                event_type=(
                    "auxiliary_test_requested"
                    if require_single
                    else "auxiliary_tests_requested"
                ),
                payload=(
                    {
                        "test_code": test_result["test_code"],
                        "result": test_result["result"],
                    }
                    if test_result is not None
                    else {"test_results": operation.test_results}
                ),
            )
            self._commit_working_session(
                operation.session,
                operation.working_session,
                outbox_events=[
                    business_event,
                    self._build_agent_update_outbox_event(
                        operation.working_session,
                        agent_update,
                    ),
                ],
            )
        return (
            operation.session,
            operation.case,
            operation.test_results,
            agent_update,
        )

    def _request_procedure_codes(
        self,
        session_id: str,
        *,
        exam_codes: list[str],
        test_codes: list[str],
        require_single_exam: bool = False,
        require_single_test: bool = False,
    ) -> _ProcedureCodeOperation | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        _require_open_session(session)
        normalized_exam_codes = _normalize_procedure_codes(
            exam_codes,
            procedure_kind="physical exam",
            require_single=require_single_exam,
        )
        normalized_test_codes = _normalize_procedure_codes(
            test_codes,
            procedure_kind="auxiliary test",
            require_single=require_single_test,
        )
        case = load_case_node(session.case_id)
        case_exam_map = _case_physical_exam_map(case)
        case_test_map = _case_auxiliary_test_map(case)
        catalog = _build_procedure_catalog()
        catalog_exam_map = {
            str(item["exam_code"]): item
            for item in catalog["physical_exams"]
        }
        catalog_test_map = {
            str(item["test_code"]): item
            for item in catalog["auxiliary_tests"]
        }
        if any(
            exam_code not in catalog_exam_map
            for exam_code in normalized_exam_codes
        ):
            raise UnknownProcedureCodeError("physical exam")
        if any(
            test_code not in catalog_test_map
            for test_code in normalized_test_codes
        ):
            raise UnknownProcedureCodeError("auxiliary test")

        requested_exam_codes = set(session.requested_exams)
        requested_test_codes = set(session.requested_tests)
        new_exam_codes = [
            exam_code
            for exam_code in normalized_exam_codes
            if exam_code not in requested_exam_codes
        ]
        new_test_codes = [
            test_code
            for test_code in normalized_test_codes
            if test_code not in requested_test_codes
        ]
        if (
            new_exam_codes
            and len(requested_exam_codes | set(new_exam_codes))
            > MAX_REQUESTED_PROCEDURES_PER_KIND
        ):
            raise ProcedureRequestLimitError("physical exam")
        if (
            new_test_codes
            and len(requested_test_codes | set(new_test_codes))
            > MAX_REQUESTED_PROCEDURES_PER_KIND
        ):
            raise ProcedureRequestLimitError("auxiliary test")

        agent_updates: list[dict[str, Any]] = []
        working_session: OsceSession | None = None
        if new_exam_codes or new_test_codes:
            working_session = deepcopy(session)
            self._refresh_active_skill_context(working_session)
            for exam_code in new_exam_codes:
                graph_state = self.osce_graph.invoke(
                    _graph_state_from_session(
                        working_session,
                        exam_code=exam_code,
                    )
                )
                _apply_graph_state(working_session, graph_state)
                catalog_exam = catalog_exam_map[exam_code]
                if exam_code not in case_exam_map:
                    _relabel_latest_action_timeline_event(
                        working_session,
                        action_type="physical_exam_requested",
                        source_id=exam_code,
                        label=str(catalog_exam["exam_name_cn"]),
                    )
            if new_exam_codes and new_test_codes:
                self._refresh_active_skill_context(working_session)
                agent_updates.append(_refresh_agent_state(working_session))
            for test_code in new_test_codes:
                graph_state = self.osce_graph.invoke(
                    _graph_state_from_session(
                        working_session,
                        test_code=test_code,
                    )
                )
                _apply_graph_state(working_session, graph_state)
                catalog_test = catalog_test_map[test_code]
                if test_code not in case_test_map:
                    _relabel_latest_action_timeline_event(
                        working_session,
                        action_type="auxiliary_test_requested",
                        source_id=test_code,
                        label=str(catalog_test["test_name_cn"]),
                    )
            self._refresh_active_skill_context(working_session)
            agent_updates.append(_refresh_agent_state(working_session))

        exam_results = [
            _build_physical_exam_request_result(
                exam_code,
                case_exam_map=case_exam_map,
                catalog_exam_map=catalog_exam_map,
            )
            for exam_code in normalized_exam_codes
        ]
        test_results = [
            _build_auxiliary_test_request_result(
                test_code,
                case_test_map=case_test_map,
                catalog_test_map=catalog_test_map,
            )
            for test_code in normalized_test_codes
        ]
        return _ProcedureCodeOperation(
            session=session,
            working_session=working_session,
            case=case,
            exam_results=exam_results,
            test_results=test_results,
            agent_updates=agent_updates,
            new_exam_codes=new_exam_codes,
            new_test_codes=new_test_codes,
        )

    @_serialize_session_operation
    def request_procedure_text(self, session_id: str, request_text: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        _require_open_session(session)
        if session.training_difficulty != "advanced":
            raise ProcedureRequestTrainingModeError(PROCEDURE_REQUEST_ADVANCED_ONLY_DETAIL)
        case = load_case_node(session.case_id)
        standardization = _standardize_procedure_request_text(request_text)
        routed_unmatched_requests = self._route_unmatched_procedure_requests(
            case=case,
            request_text=request_text,
            unmatched_requests=list(standardization["unmatched_requests"]),
        )
        operation = self._request_procedure_codes(
            session_id,
            exam_codes=list(standardization["matched_exam_codes"]),
            test_codes=list(standardization["matched_test_codes"]),
        )
        if operation is None:
            return None
        session = operation.session
        case = operation.case
        exam_results = operation.exam_results
        test_results = operation.test_results
        exam_result_map = {str(item.get("exam_code")): item for item in exam_results}
        test_result_map = {str(item.get("test_code")): item for item in test_results}
        matched_procedure_results = _build_standardized_procedure_results(
            standardization["matched_items"],
            exam_result_map,
            test_result_map,
        )
        matched_procedure_results.extend(_build_routed_unmatched_procedure_results(routed_unmatched_requests))
        simulation_session = operation.working_session or session
        simulation_batch = self.procedure_result_simulation_service.simulate(
            case=case,
            request_text=request_text,
            matched_procedure_results=matched_procedure_results,
            existing_audit_items=simulation_session.procedure_simulation_audit_items,
            forbidden_terms=_procedure_forbidden_terms(case),
        )
        matched_procedure_results = simulation_batch.results
        new_simulation_audit_items = simulation_batch.new_audit_items
        if new_simulation_audit_items:
            if operation.working_session is None:
                operation.working_session = deepcopy(session)
            operation.working_session.procedure_simulation_audit_items = (
                merge_procedure_simulation_audit_items(
                    operation.working_session.procedure_simulation_audit_items,
                    new_simulation_audit_items,
                )
            )
        has_simulated_results = any(
            item.get("generated_by_ai") is True
            for item in matched_procedure_results
        )
        standardized_request = {
            "mode": "advanced_free_text_catalog",
            "raw_request": request_text,
            "matched_exam_codes": list(standardization["matched_exam_codes"]),
            "matched_test_codes": list(standardization["matched_test_codes"]),
            "unmatched_requests": _remaining_unmatched_requests(
                list(standardization["unmatched_requests"]),
                routed_unmatched_requests,
            ),
            "routed_unmatched_requests": routed_unmatched_requests,
            "generated_result_policy": (
                "ai_simulated_grounded_not_scoring"
                if has_simulated_results
                else "ai_simulation_enabled_fail_closed"
            ),
            "safety_boundary": PROCEDURE_SIMULATION_SAFETY_BOUNDARY,
        }
        free_text_event = SessionOutboxEvent(
            event_type="procedure_free_text_requested",
            payload={
                "request_text": request_text,
                "standardized_request": standardized_request,
                "matched_procedure_results": matched_procedure_results,
                "procedure_simulation_audit_items": list(
                    (
                        operation.working_session.procedure_simulation_audit_items
                        if operation.working_session is not None
                        else session.procedure_simulation_audit_items
                    )
                ),
            },
        )
        if operation.working_session is not None:
            outbox_events: list[SessionOutboxEvent] = []
            next_agent_update_index = 0
            if operation.new_exam_codes:
                outbox_events.append(
                    SessionOutboxEvent(
                        event_type="physical_exams_requested",
                        payload={"exam_results": exam_results},
                    )
                )
                if operation.new_test_codes and operation.agent_updates:
                    outbox_events.append(
                        self._build_agent_update_outbox_event(
                            operation.working_session,
                            operation.agent_updates[0],
                        )
                    )
                    next_agent_update_index = 1
            if operation.new_test_codes:
                outbox_events.append(
                    SessionOutboxEvent(
                        event_type="auxiliary_tests_requested",
                        payload={"test_results": test_results},
                    )
                )
            outbox_events.extend(
                self._build_agent_update_outbox_event(
                    operation.working_session,
                    agent_update,
                )
                for agent_update in operation.agent_updates[
                    next_agent_update_index:
                ]
            )
            outbox_events.append(free_text_event)
            self._commit_working_session(
                session,
                operation.working_session,
                outbox_events=outbox_events,
            )
        else:
            # A fully repeated or unmatched request does not mutate the session,
            # so it remains an audit-only event rather than inventing a revision.
            try:
                self._append_event(
                    session,
                    free_text_event.event_type,
                    free_text_event.payload,
                )
            except Exception:
                # There is no state/event consistency boundary in this branch.
                # An analytics outage must not fail an otherwise valid no-op.
                pass
        payload = _serialize_session(session, case)
        payload.update(
            {
                "standardized_request": standardized_request,
                "matched_procedure_results": matched_procedure_results,
                "procedure_simulation_audit_items": list(
                    session.procedure_simulation_audit_items
                ),
                "exam_results": exam_results,
                "test_results": test_results,
            }
        )
        return payload

    def _route_unmatched_procedure_requests(
        self,
        *,
        case: Case,
        request_text: str,
        unmatched_requests: list[str],
    ) -> list[dict[str, Any]]:
        if not unmatched_requests:
            return []
        catalog = _build_procedure_catalog()
        known_catalog_labels = [
            *[str(item.get("exam_name_cn") or "") for item in catalog["physical_exams"]],
            *[str(item.get("test_name_cn") or "") for item in catalog["auxiliary_tests"]],
        ]
        try:
            routing_response = self.procedure_request_router(
                ProcedureRequestRoutingRequest(
                    case_id=case.case_id,
                    case_title=case.case_title,
                    chief_complaint=case.chief_complaint,
                    request_text=request_text,
                    unmatched_requests=unmatched_requests,
                    known_catalog_labels=known_catalog_labels,
                    forbidden_terms=_procedure_forbidden_terms(case),
                )
            )
        except ModelProviderPolicyError:
            raise
        except Exception:
            return []
        return _normalize_routed_unmatched_requests(routing_response, unmatched_requests)

    @_serialize_session_operation
    def record_hypothesis(self, session_id: str, hypothesis: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        _require_open_session(session)
        hypothesis_record_count = max(
            _effective_hypothesis_record_count(session),
            self._count_session_events_best_effort(
                session_id,
                event_types=["hypothesis_recorded"],
            ),
        )
        if hypothesis_record_count >= MAX_HYPOTHESIS_RECORDS_PER_SESSION:
            raise SessionResourceLimitError("hypothesis")
        working_session = deepcopy(session)
        working_session.student_hypotheses.append(hypothesis)
        working_session.hypothesis_record_count = hypothesis_record_count + 1
        self._refresh_active_skill_context(working_session)
        _apply_session_teacher_intervention(
            working_session,
            action_type="hypothesis_recorded",
            action_label=hypothesis,
        )
        agent_update = _refresh_agent_state(working_session)
        self._commit_working_session(
            session,
            working_session,
            outbox_events=[
                SessionOutboxEvent(
                    event_type="hypothesis_recorded",
                    payload={"hypothesis": hypothesis},
                ),
                self._build_agent_update_outbox_event(
                    working_session,
                    agent_update,
                ),
            ],
        )
        return _serialize_session(session, load_case_node(session.case_id))

    @_serialize_session_operation
    def request_hint(self, session_id: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        _require_open_session(session)
        hint_request_count = max(
            _effective_hint_request_count(session),
            self._count_session_events_best_effort(
                session_id,
                event_types=["hint_requested"],
            ),
        )
        if hint_request_count >= MAX_HINT_REQUESTS_PER_SESSION:
            raise SessionResourceLimitError("hint")
        working_session = deepcopy(session)
        self.begin_message_processing_status(session_id)
        try:
            self._refresh_active_skill_context(working_session)
            graph_state = self.osce_graph.invoke(
                _graph_state_from_session(
                    working_session,
                    hint_requested=True,
                    processing_progress_callback=lambda event: self.update_message_processing_status(
                        session_id,
                        step_id=str(event.get("step_id") or ""),
                        label=str(event.get("label") or event.get("step_id") or ""),
                        status=str(event.get("status") or "active"),
                    ),
                )
            )
            _apply_graph_state(working_session, graph_state)
            working_session.hint_request_count = hint_request_count + 1
            self._refresh_active_skill_context(working_session)
            agent_update = _refresh_agent_state(working_session)
            self._commit_working_session(
                session,
                working_session,
                outbox_events=[
                    SessionOutboxEvent(
                        event_type="hint_requested",
                        payload={
                            "hint": graph_state["hint"],
                            "agent_turn": _latest_agent_turn(graph_state),
                        },
                    ),
                    self._build_agent_update_outbox_event(
                        working_session,
                        agent_update,
                    ),
                ],
            )
            self.complete_message_processing_status(session_id)
        except Exception:
            self.complete_message_processing_status(session_id, errored=True)
            raise
        payload = _serialize_session(session, load_case_node(session.case_id))
        payload["hint"] = graph_state["hint"]
        return payload

    @_serialize_session_operation
    def get_teaching_focus(self, session_id: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        from app.services.derived_teaching_focus_service import build_session_teaching_focus

        return build_session_teaching_focus(session)

    def build_student_profile_summary(self, student_id: str) -> dict[str, Any]:
        return self._refresh_student_profile(student_id)

    @_serialize_session_operation
    def submit_diagnosis(self, session_id: str, diagnosis: str, reasoning: str) -> dict[str, Any] | None:
        session = self._get_session(session_id)
        if session is None:
            return None
        _require_open_session(session)
        existing_hypotheses = list(session.student_hypotheses)
        working_session = deepcopy(session)
        self._refresh_active_skill_context(working_session)
        graph_state = self.osce_graph.invoke(
            _graph_state_from_session(
                working_session,
                submitted_diagnosis=diagnosis,
                submitted_reasoning=reasoning,
            )
        )
        _apply_graph_state(working_session, graph_state)
        # The final diagnosis is already preserved in final_submission. Do not
        # append it to a full history or truncate legacy sessions that already
        # exceed the current explicit-hypothesis limit.
        if len(existing_hypotheses) >= MAX_HYPOTHESIS_RECORDS_PER_SESSION:
            working_session.student_hypotheses = existing_hypotheses
        else:
            working_session.student_hypotheses = working_session.student_hypotheses[
                :MAX_HYPOTHESIS_RECORDS_PER_SESSION
            ]
        self._refresh_active_skill_context(working_session)
        agent_update = _refresh_agent_state(working_session)
        self._commit_working_session(
            session,
            working_session,
            outbox_events=[
                SessionOutboxEvent(
                    event_type="diagnosis_submitted",
                    payload={"diagnosis": diagnosis, "reasoning": reasoning},
                ),
                self._build_agent_update_outbox_event(
                    working_session,
                    agent_update,
                ),
            ],
        )
        return _serialize_session(session, load_case_node(session.case_id))

    @_serialize_session_operation
    def read_report(self, session_id: str) -> dict[str, Any] | None:
        """Return the persisted report snapshot without generating or saving data."""

        if self.session_store.is_session_deleted(session_id):
            return None
        stored = self.report_store.get_stored_report(session_id)
        if stored is None:
            return None

        report = _ensure_personal_skill_report_defaults(
            stored.payload,
            self.training_skill_candidate_store,
        )
        stored_session = self.session_store.get_session(session_id)
        if stored_session is not None:
            session = OsceSession(**stored_session.payload)
            case = load_case_node(session.case_id)
            report = _ensure_report_training_progress_snapshot(report, session, case)
            report = _ensure_report_procedure_simulation_audit_items(report, session)
        else:
            report = _ensure_report_procedure_simulation_audit_items(report, None)
        if _ai_reflection_review_uses_legacy_generic_text(report.get("ai_reflection_review")):
            report = _rehydrate_orphan_teacher_reflection(report)

        if self.session_store.is_session_deleted(session_id):
            return None
        return report

    def get_report(self, session_id: str) -> dict[str, Any] | None:
        """Compatibility alias for the pure report read."""

        return self.read_report(session_id)

    @_serialize_session_operation
    def generate_report(self, session_id: str, *, include_optional_agents: bool = False) -> dict[str, Any] | None:
        if self.session_store.is_session_deleted(session_id):
            return None
        self.drain_report_outbox()
        session = self._get_session(session_id)
        stored = self.report_store.get_stored_report(session_id)
        if stored is not None:
            stored_report = stored.payload
            report = _ensure_personal_skill_report_defaults(stored_report, self.training_skill_candidate_store)
            if session is None:
                report = _ensure_report_procedure_simulation_audit_items(report, None)
                if _ai_reflection_review_uses_legacy_generic_text(report.get("ai_reflection_review")):
                    report = _rehydrate_orphan_teacher_reflection(report)
                    self.report_store.save_report(report)
                self.drain_report_outbox()
                return report
            case = load_case_node(session.case_id)
            stored_report_had_training_snapshot = bool(stored_report.get("training_progress_snapshot"))
            report = _ensure_report_training_progress_snapshot(report, session, case)
            report = _ensure_report_procedure_simulation_audit_items(report, session)
            if _ai_reflection_review_uses_legacy_generic_text(report.get("ai_reflection_review")):
                report = _rehydrate_orphan_teacher_reflection(report)
                self.report_store.save_report(report)
                session.feedback_report = report
                try:
                    self._save_session(session)
                except SessionPersistenceError:
                    pass
                refreshed = self.report_store.get_stored_report(session_id)
                if refreshed is not None:
                    stored = refreshed
                    report = refreshed.payload
            if (
                not include_optional_agents
                and stored_report_had_training_snapshot
                and _report_only_waits_for_personal_skill_enrichment(report)
            ):
                self._append_report_reflection_event(session, report)
                self.drain_report_outbox()
                return report
            if (
                session.final_submission is not None
                and _report_needs_completed_session_hydration(report)
                and not _report_only_waits_for_personal_skill_enrichment(report)
            ):
                session.feedback_report = report
                agent_update = _refresh_agent_state(session, use_reflection=True)
                session.feedback_report.update(_deferred_optional_agent_payload(session.feedback_report, case))
                session.feedback_report = _ensure_report_training_progress_snapshot(session.feedback_report, session, case)
                session.feedback_report = _ensure_report_procedure_simulation_audit_items(session.feedback_report, session)
                self._save_session(session)
                self.report_store.save_report(session.feedback_report)
                self._refresh_student_profile(session.student_id)
                self._append_report_reflection_event(
                    session,
                    session.feedback_report,
                    agent_update=agent_update,
                )
                refreshed = self.report_store.get_stored_report(session_id)
                if refreshed is not None:
                    stored = refreshed
                    report = refreshed.payload
            if report.get("training_progress_snapshot") != stored_report.get("training_progress_snapshot"):
                if session.feedback_report is not None:
                    session.feedback_report = report
                    self._save_session(session)
                self.report_store.save_report(report)
                refreshed = self.report_store.get_stored_report(session_id)
                if refreshed is not None:
                    stored = refreshed
                    report = refreshed.payload
            if (
                include_optional_agents
                and session.final_submission is not None
                and stored.enrichment_status in {"pending", "claimed", "failed"}
            ):
                report = self._enrich_claimed_report(session, case)
            self._append_report_reflection_event(session, report)
            self.drain_report_outbox()
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
            enrichment_required = session.final_submission is not None
            if enrichment_required:
                session.feedback_report.update(_deferred_optional_agent_payload(session.feedback_report, case))
            else:
                session.feedback_report.update(_personal_skill_payload_for_report(self, session, case))
            session.feedback_report = _ensure_report_procedure_simulation_audit_items(session.feedback_report, session)
            self._save_session(session)
            self.report_store.create_base_report(
                session.feedback_report,
                enrichment_required=enrichment_required,
                outbox_event=ReportOutboxEvent(
                    case_id=session.case_id,
                    student_id=session.student_id,
                    event_type="report_generated",
                    payload=_report_event_payload(session.feedback_report, report_revision=1),
                ),
            )
            self.drain_report_outbox()
            self._refresh_student_profile(session.student_id)
            self._append_report_reflection_event(
                session,
                session.feedback_report,
                agent_update=agent_update,
            )
            if enrichment_required and include_optional_agents:
                session.feedback_report = self._enrich_claimed_report(session, case)
        else:
            self._save_session(session)
        self.drain_report_outbox()
        return session.feedback_report

    @_serialize_session_operation
    def enrich_report_optional_agents(self, session_id: str) -> dict[str, Any] | None:
        if self.session_store.is_session_deleted(session_id):
            return None
        self.drain_report_outbox()
        session = self._get_session(session_id)
        stored = self.report_store.get_stored_report(session_id)
        if session is None or stored is None:
            return None

        report = _ensure_personal_skill_report_defaults(
            stored.payload,
            self.training_skill_candidate_store,
        )
        case = load_case_node(session.case_id)
        report = _ensure_report_training_progress_snapshot(report, session, case)
        report = _ensure_report_procedure_simulation_audit_items(report, session)
        if (
            session.final_submission is not None
            and stored.enrichment_status in {"pending", "claimed", "failed"}
        ):
            report = self._enrich_claimed_report(session, case)
        self._append_report_reflection_event(session, report)
        self.drain_report_outbox()
        return report

    def drain_report_outbox(self, *, limit: int = 100) -> int:
        """Best-effort delivery; keyed events make replay after an ack failure safe."""

        try:
            pending_items = self.report_store.list_pending_outbox(limit=limit)
        except Exception:
            return 0
        acknowledged = 0
        for item in pending_items:
            try:
                self.training_event_store.append_event(
                    session_id=item.session_id,
                    case_id=item.case_id,
                    student_id=item.student_id,
                    event_type=item.event_type,
                    payload=item.payload,
                    event_key=item.event_key,
                )
                if self.report_store.acknowledge_outbox(item.event_key):
                    acknowledged += 1
            except Exception:
                continue
        return acknowledged

    def _enrich_claimed_report(self, session: OsceSession, case: Case) -> dict[str, Any]:
        claim = self.report_store.claim_report_enrichment(session.session_id)
        if claim is None:
            current = self.report_store.get_report(session.session_id)
            if current is not None:
                return current
            return session.feedback_report or {}

        base_report = _ensure_report_training_progress_snapshot(claim.report, session, case)
        base_report = _ensure_report_procedure_simulation_audit_items(base_report, session)
        session.feedback_report = base_report
        enriched_report = {
            **base_report,
            **_personal_skill_payload_for_report(self, session, case),
        }
        enriched_report = _ensure_personal_skill_report_defaults(
            enriched_report,
            self.training_skill_candidate_store,
        )
        enriched_report = _ensure_report_procedure_simulation_audit_items(enriched_report, session)
        candidate = enriched_report.get("personal_skill_candidate")
        candidate_status = candidate.get("status") if isinstance(candidate, dict) else None
        report_revision = claim.expected_revision + 1
        try:
            if candidate_status == "generation_failed":
                stored = self.report_store.fail_report_enrichment(
                    session.session_id,
                    expected_revision=claim.expected_revision,
                    claim_token=claim.claim_token,
                    error_message=_report_enrichment_error_message(enriched_report),
                    case_id=session.case_id,
                    student_id=session.student_id,
                    event_type="report_enrichment_failed",
                    event_payload=_report_event_payload(
                        enriched_report,
                        report_revision=report_revision,
                    ),
                    failed_report=enriched_report,
                )
            else:
                stored = self.report_store.complete_report_enrichment(
                    session.session_id,
                    enriched_report,
                    expected_revision=claim.expected_revision,
                    claim_token=claim.claim_token,
                    case_id=session.case_id,
                    student_id=session.student_id,
                    event_type="report_enriched",
                    event_payload=_report_event_payload(
                        enriched_report,
                        report_revision=report_revision,
                    ),
                )
        except ReportClaimLostError:
            current = self.report_store.get_report(session.session_id)
            return enriched_report if current is None else current

        session.feedback_report = stored.payload
        try:
            self._save_session(session)
        except SessionPersistenceError:
            # The report CAS/outbox transaction is authoritative. A stale session
            # cache must not roll a completed report back to its pending snapshot.
            pass
        try:
            self._refresh_student_profile(session.student_id)
        except Exception:
            pass
        return stored.payload

    def _append_report_reflection_event(
        self,
        session: OsceSession,
        report: dict[str, Any],
        *,
        agent_update: dict[str, Any] | None = None,
    ) -> None:
        report_id = str(report.get("report_id") or f"{session.session_id}_report")
        update = agent_update or {
            "pedagogy_state": session.pedagogy_state,
            "reflection_summary": session.reflection_summary,
        }
        try:
            self._append_agent_update_event(
                session,
                update,
                event_type="agent_reflection_recorded",
                event_key=f"report:{report_id}:reflection:base",
            )
        except Exception:
            # Reflection diagnostics must not turn an already persisted report
            # into a failed response when the event database is unavailable.
            pass

    @_serialize_session_operation
    def delete_session(
        self,
        session_id: str,
        *,
        expected_student_id: str | None = None,
    ) -> bool:
        deletion_started = False
        student_id = expected_student_id
        try:
            existing_deletion = self.session_store.get_session_deletion(session_id)
            if existing_deletion is not None:
                if not existing_deletion.user_id:
                    if student_id is None:
                        raise SessionNotFoundError(session_id)
                    deletion = self._adopt_legacy_deletion_from_evidence(
                        session_id=session_id,
                        expected_student_id=student_id,
                    )
                    if deletion is None:
                        raise SessionNotFoundError(session_id)
                elif student_id is None or existing_deletion.user_id != student_id:
                    raise SessionNotFoundError(session_id)
                else:
                    deletion = self.session_store.begin_session_deletion(
                        session_id,
                        expected_user_id=student_id,
                    )
                    if deletion is None:
                        raise SessionNotFoundError(session_id)
            else:
                stored_session = self.session_store.get_session(session_id)
                if stored_session is None:
                    raise SessionNotFoundError(session_id)
                stored_student_id = str(stored_session.payload.get("student_id", ""))
                if not stored_student_id or (
                    student_id is not None and stored_student_id != student_id
                ):
                    raise SessionNotFoundError(session_id)
                student_id = stored_student_id
                self._validate_personal_artifact_ownership(
                    session_id=session_id,
                    student_id=student_id,
                )
                candidate_id = f"personal_skill_candidate_{session_id}"
                skill_id = f"skill_personal_{session_id}"
                source_report_id = f"{session_id}_report"
                self.session_store.validate_skill_source_references(
                    source_session_id=session_id,
                    owner_user_id=student_id,
                    personal_skill_id=skill_id,
                    personal_candidate_id=candidate_id,
                    source_report_id=source_report_id,
                )
                self.training_event_store.validate_skill_source_references(
                    source_session_id=session_id,
                    owner_student_id=student_id,
                    personal_skill_id=skill_id,
                )
                deletion = self.session_store.begin_session_deletion(
                    session_id,
                    expected_user_id=student_id,
                )
                if deletion is None:
                    raise SessionNotFoundError(session_id)

            assert student_id is not None
            deletion_started = True
            if (
                deletion.cleanup_status == "completed"
                and deletion.cleanup_version
                >= SESSION_DELETION_CLEANUP_VERSION
            ):
                return True

            self._validate_personal_artifact_ownership(
                session_id=session_id,
                student_id=student_id,
            )
            candidate_id = f"personal_skill_candidate_{session_id}"
            skill_id = f"skill_personal_{session_id}"
            source_report_id = f"{session_id}_report"
            self.session_store.validate_skill_source_references(
                source_session_id=session_id,
                owner_user_id=student_id,
                personal_skill_id=skill_id,
                personal_candidate_id=candidate_id,
                source_report_id=source_report_id,
            )
            self.training_event_store.validate_skill_source_references(
                source_session_id=session_id,
                owner_student_id=student_id,
                personal_skill_id=skill_id,
            )
            try:
                self.training_event_store.delete_event_streams(
                    [session_id, candidate_id],
                )
                candidate_cleanup = (
                    self.training_skill_candidate_store.remove_global_source_contributions(
                        source_session_id=session_id,
                        owner_student_id=student_id,
                        source_report_id=source_report_id,
                    )
                )
                skill_cleanup = (
                    self.training_skill_store.remove_global_source_contributions(
                        source_session_id=session_id,
                        owner_student_id=student_id,
                        source_report_id=source_report_id,
                        affected_candidate_ids=list(
                            candidate_cleanup.affected_candidate_ids
                        ),
                    )
                )
                affected_global_skill_ids = list(
                    skill_cleanup.affected_skill_ids
                )
                affected_session_ids = (
                    self.session_store.delete_skill_source_references(
                        source_session_id=session_id,
                        owner_user_id=student_id,
                        personal_skill_id=skill_id,
                        personal_candidate_id=candidate_id,
                        source_report_id=source_report_id,
                        affected_global_skill_ids=affected_global_skill_ids,
                    )
                )
                for affected_session_id in affected_session_ids:
                    self._sessions.pop(affected_session_id, None)
                self.training_event_store.delete_skill_source_references(
                    source_session_id=session_id,
                    owner_student_id=student_id,
                    personal_skill_id=skill_id,
                    affected_global_skill_ids=affected_global_skill_ids,
                )
                self.report_store.delete_session_report(session_id)
                self.training_skill_store.delete_personal_skill(
                    skill_id=skill_id,
                    owner_student_id=student_id,
                    source_session_id=session_id,
                    source_candidate_id=candidate_id,
                )
                self.training_skill_candidate_store.delete_personal_candidate(
                    candidate_id=candidate_id,
                    owner_student_id=student_id,
                    source_session_id=session_id,
                )
            except (
                SessionDerivedReferenceOwnershipError,
                TrainingEventReferenceOwnershipError,
                TrainingSkillOwnershipError,
                TrainingSkillCandidateOwnershipError,
            ) as exc:
                raise SessionDeletionConflictError(
                    "会话关联的个人训练数据存在归属冲突，删除已安全中止。"
                ) from exc

            self.student_profile_store.delete_profile(student_id)
            completed = self.session_store.mark_session_deletion_complete(session_id)
            if completed is None:
                raise SessionPersistenceError(session_id)

            try:
                self._refresh_student_profile(student_id)
            except Exception:
                # The source artifacts are already fenced and removed. A profile
                # snapshot can be rebuilt later without weakening deletion.
                pass
            return True
        except (
            SessionDerivedReferenceOwnershipError,
            TrainingEventReferenceOwnershipError,
            TrainingSkillOwnershipError,
            TrainingSkillCandidateOwnershipError,
        ) as exc:
            raise SessionDeletionConflictError(
                "会话关联的个人训练数据存在归属冲突，删除已安全中止。"
            ) from exc
        finally:
            if deletion_started:
                self._sessions.pop(session_id, None)
                with self._message_processing_status_lock:
                    self._message_processing_statuses.pop(session_id, None)

    def resume_pending_session_deletions(
        self,
        *,
        limit: int | None = None,
    ) -> dict[str, int]:
        pending_deletions = self.session_store.list_pending_deletions(limit=limit)
        legacy_deletions = self.session_store.list_ownerless_legacy_deletions(
            limit=limit,
        )
        deletions_by_session_id = {
            deletion.session_id: deletion
            for deletion in [*pending_deletions, *legacy_deletions]
        }
        recoverable_deletions = sorted(
            deletions_by_session_id.values(),
            key=lambda deletion: (deletion.deleted_at, deletion.session_id),
        )
        if limit is not None:
            recoverable_deletions = recoverable_deletions[:limit]
        stats = {
            "scanned": len(recoverable_deletions),
            "adopted": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
        }
        for deletion in recoverable_deletions:
            if not deletion.user_id:
                try:
                    adopted_deletion = self._adopt_legacy_deletion_from_evidence(
                        session_id=deletion.session_id,
                    )
                except Exception:
                    stats["failed"] += 1
                    continue
                if adopted_deletion is None:
                    stats["skipped"] += 1
                    continue
                deletion = adopted_deletion
                stats["adopted"] += 1
            try:
                self.delete_session(
                    deletion.session_id,
                    expected_student_id=deletion.user_id,
                )
            except Exception:
                stats["failed"] += 1
            else:
                stats["completed"] += 1
        return stats

    def _adopt_legacy_deletion_from_evidence(
        self,
        *,
        session_id: str,
        expected_student_id: str | None = None,
    ) -> SessionDeletionRecord | None:
        recovered_identity = self._recover_legacy_deletion_identity(
            session_id=session_id,
        )
        if recovered_identity is None:
            return None
        recovered_student_id, recovered_case_id = recovered_identity
        if (
            expected_student_id is not None
            and recovered_student_id != expected_student_id
        ):
            return None
        try:
            self._validate_personal_artifact_ownership(
                session_id=session_id,
                student_id=recovered_student_id,
            )
        except SessionDeletionConflictError:
            return None

        deletion = self.session_store.adopt_legacy_session_deletion(
            session_id,
            user_id=recovered_student_id,
            case_id=recovered_case_id,
        )
        if deletion is not None:
            return deletion
        current_deletion = self.session_store.get_session_deletion(session_id)
        if (
            current_deletion is None
            or current_deletion.user_id != recovered_student_id
            or current_deletion.case_id != recovered_case_id
        ):
            return None
        return current_deletion

    def _recover_legacy_deletion_identity(
        self,
        *,
        session_id: str,
    ) -> tuple[str, str] | None:
        report = self.report_store.get_report(session_id)
        event_stream = self.training_event_store.list_session_events(session_id)
        student_ids: set[str] = set()
        case_ids: set[str] = set()

        if report is not None:
            report_session_id = str(report.get("session_id", "")).strip()
            report_student_id = str(report.get("student_id", "")).strip()
            report_case_id = str(report.get("case_id", "")).strip()
            if (
                report_session_id != session_id
                or not report_student_id
                or not report_case_id
            ):
                return None
            student_ids.add(report_student_id)
            case_ids.add(report_case_id)

        for event in event_stream:
            if str(event.get("session_id", "")).strip() != session_id:
                return None
            event_student_id = str(event.get("student_id", "")).strip()
            event_case_id = str(event.get("case_id", "")).strip()
            if event_student_id:
                student_ids.add(event_student_id)
            if event_case_id:
                case_ids.add(event_case_id)

        if len(student_ids) != 1 or len(case_ids) != 1:
            return None
        return next(iter(student_ids)), next(iter(case_ids))

    def _validate_personal_artifact_ownership(
        self,
        *,
        session_id: str,
        student_id: str,
    ) -> None:
        candidate_id = f"personal_skill_candidate_{session_id}"
        candidate = self.training_skill_candidate_store.get_candidate(candidate_id)
        if candidate is not None and (
            str(candidate.get("candidate_id", "")) != candidate_id
            or str(candidate.get("scope", "")) != "personal"
            or str(candidate.get("owner_student_id", "")) != student_id
            or str(candidate.get("source_session_id", "")) != session_id
        ):
            raise SessionDeletionConflictError(
                "会话关联的个人训练数据存在归属冲突，删除已安全中止。"
            )

        skill_id = f"skill_personal_{session_id}"
        skill = self.training_skill_store.get_skill(skill_id)
        if skill is not None and (
            str(skill.get("skill_id", "")) != skill_id
            or str(skill.get("scope", "")) != "personal"
            or str(skill.get("owner_student_id", "")) != student_id
            or str(skill.get("source_session_id", "")) != session_id
            or str(skill.get("source_candidate_id", "")) != candidate_id
        ):
            raise SessionDeletionConflictError(
                "会话关联的个人训练数据存在归属冲突，删除已安全中止。"
            )

    def _get_session(self, session_id: str) -> OsceSession | None:
        stored_session = self.session_store.get_session(session_id)
        cached_session = self._sessions.get(session_id)
        if stored_session is None:
            self._sessions.pop(session_id, None)
            return None
        if cached_session is None:
            session = OsceSession(**stored_session.payload)
            self._sessions[session.session_id] = _CachedSession(
                session=session,
                revision=stored_session.revision,
            )
            return session
        if cached_session.revision != stored_session.revision:
            refreshed_session = OsceSession(**stored_session.payload)
            _refresh_session_in_place(cached_session.session, refreshed_session)
            cached_session.revision = stored_session.revision
        return cached_session.session

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

    def _build_session_creation_outbox_events(
        self,
        session: OsceSession,
        agent_update: dict[str, Any],
        enabled_skills: Sequence[dict[str, Any]],
    ) -> list[SessionOutboxEvent]:
        events = [
            SessionOutboxEvent(
                event_type="session_created",
                payload={
                    "stage": session.stage,
                    "training_difficulty": session.training_difficulty,
                },
            ),
            self._build_agent_update_outbox_event(session, agent_update),
        ]
        for skill in enabled_skills:
            skill_event_payload: dict[str, Any] = {
                "skill_id": skill["skill_id"],
                "title": skill["title"],
                "suggested_strategy": skill["suggested_strategy"],
                "skill_type": skill.get("skill_type", "reasoning_bridge"),
                "stage_scope": list(skill.get("stage_scope", [])),
                "effect_status": skill.get(
                    "effect_status",
                    "insufficient_samples",
                ),
            }
            if skill.get("scope") and skill.get("scope") != "global":
                skill_event_payload["scope"] = skill["scope"]
            if skill.get("source_session_id"):
                skill_event_payload["source_session_id"] = skill[
                    "source_session_id"
                ]
            if skill.get("source_session_ids"):
                skill_event_payload["source_session_ids"] = list(
                    skill["source_session_ids"]
                )
            if skill.get("source_report_ids"):
                skill_event_payload["source_report_ids"] = list(
                    skill["source_report_ids"]
                )
            if skill.get("source_provenance_schema_version"):
                skill_event_payload["source_provenance_schema_version"] = str(
                    skill["source_provenance_schema_version"]
                )
            if skill.get("owner_student_id"):
                skill_event_payload["owner_student_id"] = skill[
                    "owner_student_id"
                ]
            events.append(
                SessionOutboxEvent(
                    event_type="training_skill_applied",
                    payload=skill_event_payload,
                )
            )
        return events

    def _create_session(
        self,
        session: OsceSession,
        *,
        outbox_events: Sequence[SessionOutboxEvent] = (),
        expected_deleted_skill_sources_version: int | None = None,
    ) -> None:
        self.session_store.create_session(
            session,
            outbox_events=outbox_events,
            expected_deleted_skill_sources_version=(
                expected_deleted_skill_sources_version
            ),
        )
        stored_session = self.session_store.get_session(session.session_id)
        if stored_session is None:
            raise SessionNotFoundError(session.session_id)
        _refresh_session_in_place(
            session,
            OsceSession(**stored_session.payload),
        )
        self._sessions[session.session_id] = _CachedSession(
            session=session,
            revision=stored_session.revision,
        )
        self.drain_session_event_outbox(session_id=session.session_id)

    def _save_session(
        self,
        session: OsceSession,
        *,
        outbox_events: Sequence[SessionOutboxEvent] = (),
    ) -> None:
        cached_session = self._sessions.get(session.session_id)
        if cached_session is None or cached_session.session is not session:
            self._sessions.pop(session.session_id, None)
            raise SessionNotFoundError(session.session_id)
        try:
            stored_session = self.session_store.update_session_and_get(
                session,
                expected_revision=cached_session.revision,
                outbox_events=outbox_events,
            )
            _refresh_session_in_place(
                session,
                OsceSession(**stored_session.payload),
            )
            cached_session.revision = stored_session.revision
            self.drain_session_event_outbox(session_id=session.session_id)
        except Exception:
            self._sessions.pop(session.session_id, None)
            raise

    def _commit_working_session(
        self,
        live_session: OsceSession,
        working_session: OsceSession,
        *,
        outbox_events: Sequence[SessionOutboxEvent] = (),
    ) -> None:
        cached_session = self._sessions.get(live_session.session_id)
        if (
            cached_session is None
            or cached_session.session is not live_session
            or working_session is live_session
            or working_session.session_id != live_session.session_id
            or working_session.student_id != live_session.student_id
            or working_session.case_id != live_session.case_id
        ):
            self._sessions.pop(live_session.session_id, None)
            raise SessionNotFoundError(live_session.session_id)
        try:
            stored_session = self.session_store.update_session_and_get(
                working_session,
                expected_revision=cached_session.revision,
                outbox_events=outbox_events,
            )
            _refresh_session_in_place(
                live_session,
                OsceSession(**stored_session.payload),
            )
            cached_session.revision = stored_session.revision
            self.drain_session_event_outbox(
                session_id=live_session.session_id
            )
        except Exception:
            self._sessions.pop(live_session.session_id, None)
            raise

    def _count_session_events_best_effort(
        self,
        session_id: str,
        *,
        event_types: Sequence[str],
    ) -> int:
        try:
            return self.training_event_store.count_session_events(
                session_id,
                event_types=list(event_types),
                busy_timeout_milliseconds=(
                    SESSION_EVENT_STORE_BUSY_TIMEOUT_MILLISECONDS
                ),
            )
        except Exception:
            # Persisted counters and bounded session payloads remain authoritative
            # while the analytics/event database is temporarily unavailable.
            return 0

    def drain_session_event_outbox(
        self,
        *,
        limit: int = 100,
        session_id: str | None = None,
    ) -> int:
        """Deliver one session stream in FIFO order without failing the API."""

        if limit <= 0:
            raise ValueError("limit must be positive")

        def deliver(item: SessionOutboxItem) -> None:
            try:
                self.training_event_store.append_event(
                    session_id=item.session_id,
                    case_id=item.case_id,
                    student_id=item.student_id,
                    event_type=item.event_type,
                    payload=item.payload,
                    event_key=item.event_key,
                    busy_timeout_milliseconds=(
                        SESSION_EVENT_STORE_BUSY_TIMEOUT_MILLISECONDS
                    ),
                )
            except TrainingEventDeletedSkillSourceError:
                # The source-erasure ledger intentionally makes this event
                # obsolete; acknowledging it prevents a permanent poison item.
                return

        acknowledged = 0
        for _ in range(limit):
            try:
                delivered = self.session_store.deliver_next_event_outbox(
                    deliver,
                    session_id=session_id,
                )
            except Exception:
                break
            if not delivered:
                break
            acknowledged += 1
        return acknowledged

    def _append_event(
        self,
        session: OsceSession,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_key: str | None = None,
    ) -> None:
        self.training_event_store.append_event(
            session_id=session.session_id,
            case_id=session.case_id,
            student_id=session.student_id,
            event_type=event_type,
            payload=payload,
            event_key=event_key,
        )

    def _append_agent_update_event(
        self,
        session: OsceSession,
        agent_update: dict[str, Any],
        event_type: str = "agent_decision_traced",
        *,
        event_key: str | None = None,
    ) -> None:
        event = self._build_agent_update_outbox_event(
            session,
            agent_update,
            event_type=event_type,
        )
        self._append_event(
            session,
            event.event_type,
            event.payload,
            event_key=event_key,
        )

    @staticmethod
    def _build_agent_update_outbox_event(
        session: OsceSession,
        agent_update: dict[str, Any],
        event_type: str = "agent_decision_traced",
    ) -> SessionOutboxEvent:
        agent_decision_trace = agent_update.get("agent_decision_trace")
        if isinstance(agent_decision_trace, list) and agent_decision_trace:
            latest_decision = agent_decision_trace[-1]
        elif session.agent_decision_trace:
            latest_decision = session.agent_decision_trace[-1]
        else:
            latest_decision = {}
        payload = {
            "latest_decision": latest_decision,
            "pedagogy_state": agent_update.get("pedagogy_state", session.pedagogy_state),
            "teacher_intervention_decision": (
                dict(session.teacher_decision_records[-1])
                if session.teacher_decision_records
                else {}
            ),
        }
        if "reflection_summary" in agent_update:
            payload["reflection_summary"] = agent_update["reflection_summary"]
        return SessionOutboxEvent(event_type=event_type, payload=payload)

    def _append_runtime_error_event(
        self,
        session: OsceSession,
        *,
        operation: str,
        exc: BaseException,
        extra_payload: dict[str, Any] | None = None,
    ) -> str:
        trace_id = f"osce-error-{uuid4().hex[:12]}"
        payload: dict[str, Any] = {
            "trace_id": trace_id,
            "operation": operation,
            "stage": session.stage,
            "training_difficulty": session.training_difficulty,
            "error_type": type(exc).__name__,
            "message": _sanitize_runtime_error_text(str(exc)),
            "stack_trace": _sanitize_runtime_error_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__))),
        }
        if extra_payload:
            payload.update({key: _sanitize_runtime_error_value(value) for key, value in extra_payload.items()})
        self._append_event(session, "session_runtime_error", payload)
        return trace_id


def load_case_node(case_id: str) -> Case:
    case_path = CASES_DIR / f"{case_id}.json"
    case_payload = json.loads(case_path.read_text(encoding="utf-8"))
    return validate_case(case_payload)


def _sanitize_runtime_error_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_runtime_error_text(value)
    if isinstance(value, list):
        return [_sanitize_runtime_error_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_runtime_error_value(item) for key, item in value.items()}
    return value


def _sanitize_runtime_error_text(value: str) -> str:
    sanitized = re.sub(r"https?://[^\s\"')]+", "[redacted-url]", value)
    sanitized = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+", r"\1[redacted]", sanitized)
    sanitized = re.sub(r"(?i)(api[_-]?key['\"]?\s*[:=]\s*['\"]?)[^,'\"\s}]+", r"\1[redacted]", sanitized)
    sanitized = re.sub(r"\b(sk|tp)-[A-Za-z0-9._\-]{8,}\b", "[redacted-secret]", sanitized)
    return sanitized[:MAX_RUNTIME_ERROR_FIELD_LENGTH]


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
        "hint_request_count": _effective_hint_request_count(session),
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
        "patient_affect_state": session.patient_affect_state,
        "pedagogy_state": session.pedagogy_state,
        "agent_decision_trace": session.agent_decision_trace,
        "teacher_decision_records": session.teacher_decision_records,
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
    session.patient_affect_state = graph_state.get("patient_affect_state", session.patient_affect_state)
    session.pedagogy_state = graph_state.get("pedagogy_state", session.pedagogy_state)
    session.agent_decision_trace = graph_state.get("agent_decision_trace", session.agent_decision_trace)
    session.teacher_decision_records = graph_state.get(
        "teacher_decision_records",
        session.teacher_decision_records,
    )
    session.reflection_summary = graph_state.get("reflection_summary", session.reflection_summary)


def _refresh_agent_state(session: OsceSession, use_reflection: bool = False) -> dict[str, Any]:
    graph_state = _graph_state_from_session(session)
    agent_update = reflection_node(graph_state) if use_reflection else training_strategy_node(graph_state)
    session.pedagogy_state = agent_update.get("pedagogy_state", session.pedagogy_state)
    session.agent_decision_trace = agent_update.get("agent_decision_trace", session.agent_decision_trace)
    if "reflection_summary" in agent_update:
        session.reflection_summary = agent_update["reflection_summary"]
    return agent_update


def _apply_session_teacher_intervention(
    session: OsceSession,
    *,
    action_type: str,
    action_label: str,
) -> None:
    decision = resolve_teacher_intervention(
        _graph_state_from_session(session),
        action_type=action_type,
        action_label=action_label,
    )
    emitted_hint = decision.hint if decision.mode == TeacherInterventionMode.HINT else ""
    if emitted_hint:
        session.messages.append({"role": "coach", "content": emitted_hint})
        session.agent_turn_memory.append(
            {
                "turn_id": f"turn:{len(session.agent_turn_memory) + 1}",
                "student_message": action_label,
                "reply": emitted_hint,
                "reply_role": "coach",
                "current_intents": [action_type],
                "turn_policy": "proactive_teacher_hint",
                "turn_analysis": {
                    "current_intents": [action_type],
                    "confidence": 1.0,
                    "is_off_topic": False,
                    "rationale": decision.reason,
                    "teacher_intervention": {
                        "mode": decision.mode.value,
                        "trigger_kind": decision.trigger_kind,
                        "reason_code": decision.reason_code,
                        "issue_id": decision.issue_id,
                    },
                },
                "agent_path": ["session_service", "teacher_intervention_policy"],
                "safety_flags": list(session.safety_flags),
            }
        )
    session.teacher_decision_records = append_teacher_decision_record(
        session.teacher_decision_records,
        decision,
        emitted_hint=emitted_hint,
    )


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
    from app.services.teacher_agent import DeterministicTeacherAgent
    from app.services.training_skill_candidate_service import TrainingSkillCandidateGenerationError

    if session.final_submission is None:
        return build_not_ready_personal_skill_payload()
    if session.feedback_report is None:
        return build_not_ready_personal_skill_payload()
    active_personal_skill_service = service.personal_skill_service or personal_training_skill_service
    teacher_longitudinal_context = _teacher_longitudinal_context_for_report(
        service,
        session,
    )
    try:
        return active_personal_skill_service.generate_for_completed_session(
            session=session,
            case=case,
            report=session.feedback_report,
            candidate_store=service.training_skill_candidate_store,
            skill_store=service.training_skill_store,
            event_store=service.training_event_store,
            teacher_longitudinal_context=teacher_longitudinal_context,
        )
    except (ModelProviderTimeoutError, ModelProviderOverloadedError) as exc:
        failure_report = {
            **session.feedback_report,
            "final_submission": deepcopy(session.final_submission),
        }
        payload = build_generation_failed_personal_skill_payload(
            report=failure_report,
            case=case,
            teacher_agent=DeterministicTeacherAgent(),
            teacher_longitudinal_context=teacher_longitudinal_context,
        )
        payload["generation_warnings"] = _append_report_generation_warning(
            session.feedback_report,
            module="personal_skill_generation",
            exc=exc,
        )
        return payload
    except ModelProviderPolicyError:
        raise
    except TrainingSkillCandidateGenerationError:
        failure_report = {
            **session.feedback_report,
            "final_submission": deepcopy(session.final_submission),
        }
        return build_generation_failed_personal_skill_payload(
            report=failure_report,
            case=case,
            teacher_agent=DeterministicTeacherAgent(),
            teacher_longitudinal_context=teacher_longitudinal_context,
        )
    except Exception as exc:
        failure_report = {
            **session.feedback_report,
            "final_submission": deepcopy(session.final_submission),
        }
        payload = build_generation_failed_personal_skill_payload(
            report=failure_report,
            case=case,
            teacher_agent=DeterministicTeacherAgent(),
            teacher_longitudinal_context=teacher_longitudinal_context,
        )
        payload["generation_warnings"] = _append_report_generation_warning(
            session.feedback_report,
            module="personal_skill_generation",
            exc=exc,
        )
        return payload


def _teacher_longitudinal_context_for_report(
    service: OsceSessionService,
    session: OsceSession,
) -> dict[str, Any]:
    from app.services.teacher_longitudinal_context_service import (
        MAX_LONGITUDINAL_REPORTS,
        build_teacher_longitudinal_context,
    )

    current_report = session.feedback_report
    if not isinstance(current_report, dict):
        return build_teacher_longitudinal_context([])

    report_entries: list[dict[str, Any]] = [
        {
            "session_id": session.session_id,
            "case_id": session.case_id,
            "training_difficulty": session.training_difficulty,
            "report": current_report,
        }
    ]
    try:
        session_summaries = service.session_store.list_user_session_summaries(
            session.student_id,
        )
        for summary in session_summaries:
            if len(report_entries) >= MAX_LONGITUDINAL_REPORTS:
                break
            session_id = str(summary.get("session_id") or "").strip()
            if (
                not session_id
                or session_id == session.session_id
                or not bool(summary.get("has_report"))
            ):
                continue
            report = service.report_store.get_report(session_id)
            if not isinstance(report, dict):
                continue
            report_entries.append(
                {
                    "session_id": session_id,
                    "case_id": str(summary.get("case_id") or report.get("case_id") or ""),
                    "training_difficulty": str(summary.get("training_difficulty") or ""),
                    "report": report,
                }
            )
        recent_session_ids = [
            str(entry["session_id"])
            for entry in report_entries
        ]
        events_by_session = service.training_event_store.list_events_for_sessions(
            recent_session_ids,
        )
    except Exception:
        # Longitudinal analysis is optional teaching context. A temporary history
        # store problem must not block the deterministic report or personal Skill.
        return build_teacher_longitudinal_context(report_entries[:1])
    return build_teacher_longitudinal_context(
        report_entries,
        events_by_session=events_by_session,
    )


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
    report_audit_items = report.get("procedure_simulation_audit_items")
    session_audit_items = session.procedure_simulation_audit_items if session is not None else None
    if isinstance(report_audit_items, list) and report_audit_items:
        audit_items = report_audit_items
    elif isinstance(session_audit_items, list) and session_audit_items:
        audit_items = session_audit_items
    elif isinstance(report_audit_items, list):
        audit_items = report_audit_items
    else:
        audit_items = []
    return {
        **report,
        "procedure_simulation_audit_items": list(audit_items),
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


def _report_only_waits_for_personal_skill_enrichment(report: dict[str, Any]) -> bool:
    ai_reflection_review = report.get("ai_reflection_review")
    personal_skill_candidate = report.get("personal_skill_candidate")
    ai_status = ai_reflection_review.get("status") if isinstance(ai_reflection_review, dict) else None
    skill_status = personal_skill_candidate.get("status") if isinstance(personal_skill_candidate, dict) else None
    return (
        skill_status == "generation_pending"
        and ai_status == "generated"
        and not _ai_reflection_review_uses_legacy_generic_text(ai_reflection_review)
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


def _report_event_payload(
    report: dict[str, Any],
    *,
    report_revision: int,
) -> dict[str, Any]:
    return {
        "report_id": report.get("report_id"),
        "report_revision": report_revision,
        "report": report,
        "total_score": report.get("total_score"),
        "missed_items": report.get("missed_items", []),
        "knowledge_recommendations": report.get("knowledge_recommendations", []),
        "source_references": report.get("source_references", []),
        "source_reference_items": report.get("source_reference_items", []),
        "personal_skill_candidate": report.get("personal_skill_candidate"),
        "ai_reflection_review": report.get("ai_reflection_review"),
    }


def _report_generated_event_payload(report: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper for callers/tests that still build a base event payload."""

    return _report_event_payload(report, report_revision=1)


def _report_enrichment_error_message(report: dict[str, Any]) -> str:
    warnings = report.get("generation_warnings")
    if isinstance(warnings, list):
        for warning in reversed(warnings):
            if isinstance(warning, dict) and str(warning.get("message") or "").strip():
                return str(warning["message"])
    candidate = report.get("personal_skill_candidate")
    if isinstance(candidate, dict) and str(candidate.get("reason") or "").strip():
        return str(candidate["reason"])
    return "optional report enrichment failed"


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
    normalized_report.setdefault("deep_report_analysis", build_legacy_deep_report_analysis())
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
        "patient_affect_state": build_initial_patient_affect_state(),
        "pedagogy_state": {},
        "agent_decision_trace": [],
        "teacher_decision_records": [],
        "reflection_summary": None,
        "hint_request_count": 0,
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

PROCEDURE_REQUEST_GENERIC_LABEL_TERMS = {
    "腹部",
    "胸部",
    "肺部",
    "心脏",
    "甲状腺",
    "影像",
    "实验室",
    "生命体征",
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
    aliases = _procedure_aliases(code, str(item[name_key]))
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


def _procedure_aliases(code: str, name: str) -> list[str]:
    # Category labels and bare anatomy fragments are too broad for free-text
    # routing: for example, "腹部视诊" must not also request "腹部 CT".
    aliases = [name, code, code.replace(".", " ")]
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
    if alias in PROCEDURE_REQUEST_GENERIC_LABEL_TERMS:
        return False
    if len(alias) >= 2 and not alias.isascii():
        return True
    return alias in {"ct", "b超"} or len(alias) >= 3


def _extract_unmatched_procedure_terms(request_text: str, matched_aliases: list[str]) -> list[str]:
    matched_aliases = _dedupe_non_empty(matched_aliases)
    chunks = re.split(
        r"和|及|与|并|再|看看|看一下|查一下|查个|检查|申请|做|测|查|要|想|请|，|,|、|；|;|。|\s+",
        request_text,
    )
    ignored_terms = {
        "我",
        "我想",
        "一下",
        "一个",
        "相关",
        "项目",
        "结果",
        "还有",
        "一下子",
        "腹部",
        "右下腹",
        "左下腹",
        "右上腹",
        "左上腹",
        "胸部",
        "肺部",
        "心脏",
        "甲状腺",
    }
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


def _normalize_routed_unmatched_requests(routing_response: Any, unmatched_requests: list[str]) -> list[dict[str, Any]]:
    if hasattr(routing_response, "model_dump"):
        routing_response = routing_response.model_dump()
    if not isinstance(routing_response, dict):
        return []
    routed_items = routing_response.get("routed_items", [])
    if not isinstance(routed_items, list):
        return []
    normalized_items: list[dict[str, Any]] = []
    for item in routed_items:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        raw_text = str(item.get("raw_text") or "").strip()
        if not raw_text or not _route_item_matches_any_unmatched(raw_text, unmatched_requests):
            continue
        decision = str(item.get("decision") or "clarify").strip()
        if decision not in {"generate", "clarify", "block"}:
            decision = "clarify"
        kind = str(item.get("kind") or "other").strip()
        if kind not in {"physical_exam", "auxiliary_test", "patient_profile", "vital_sign", "other"}:
            kind = "other"
        name_cn = str(item.get("name_cn") or raw_text).strip()
        rationale = str(item.get("rationale") or "").strip()
        safety_issues = [
            str(safety_issue).strip()
            for safety_issue in item.get("safety_issues", [])
            if str(safety_issue).strip()
        ]
        if decision == "generate" and kind == "patient_profile":
            decision = "block"
            rationale = "病例未配置该患者信息，训练中不得编造姓名、身高、体重或其他患者事实。"
            if "unconfigured_patient_fact" not in safety_issues:
                safety_issues.append("unconfigured_patient_fact")
        normalized_items.append(
            {
                "raw_text": raw_text,
                "decision": decision,
                "kind": kind,
                "name_cn": name_cn,
                "rationale": rationale,
                "safety_issues": safety_issues,
            }
        )
    return normalized_items


def _build_routed_unmatched_procedure_results(routed_unmatched_requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in routed_unmatched_requests:
        if item.get("decision") != "generate":
            continue
        kind = str(item.get("kind") or "other")
        raw_text = str(item.get("raw_text") or "")
        name_cn = str(item.get("name_cn") or raw_text or "未命名申请")
        code = _generated_procedure_code(kind, raw_text, name_cn)
        results.append(
            {
                "id": f"generated:{kind}:{code}",
                "kind": kind,
                "code": code,
                "name_cn": name_cn,
                "label": f"{_routed_procedure_label_prefix(kind)}：{name_cn}",
                "result": "该项目已记录，但本训练站点未提供预置结果。",
                "availability_status": "not_available_for_case",
                "generated_by_ai": False,
                "approval_status": "not_required",
                "approval_agent_review": {
                    "agent_id": "procedure_request_router",
                    "decision": str(item.get("decision") or "generate"),
                    "approval_mode": "request_routing",
                    "rationale": str(item.get("rationale") or ""),
                    "safety_issues": list(item.get("safety_issues") or []),
                    "revised_result": "",
                },
                "source_context_references": [],
                "scoring_eligible": False,
            }
        )
    return results


def _mark_unconfigured_procedure_results_unavailable(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        (
            {
                **result,
                "availability_status": "not_available_for_case",
                "generated_by_ai": False,
                "approval_status": "not_required",
                "source_context_references": [],
                "scoring_eligible": False,
            }
            if result.get("availability_status") == "not_available_for_case"
            else result
        )
        for result in results
    ]


def _remaining_unmatched_requests(
    unmatched_requests: list[str],
    routed_unmatched_requests: list[dict[str, Any]],
) -> list[str]:
    generated_raw_texts = [
        str(item.get("raw_text") or "")
        for item in routed_unmatched_requests
        if item.get("decision") == "generate"
    ]
    return [
        unmatched_request
        for unmatched_request in unmatched_requests
        if not any(_route_item_matches_unmatched(raw_text, unmatched_request) for raw_text in generated_raw_texts)
    ]


def _route_item_matches_any_unmatched(raw_text: str, unmatched_requests: list[str]) -> bool:
    return any(_route_item_matches_unmatched(raw_text, unmatched_request) for unmatched_request in unmatched_requests)


def _route_item_matches_unmatched(raw_text: str, unmatched_request: str) -> bool:
    normalized_raw_text = _normalize_procedure_request_text(raw_text)
    normalized_unmatched_request = _normalize_procedure_request_text(unmatched_request)
    return (
        normalized_raw_text == normalized_unmatched_request
        or normalized_raw_text in normalized_unmatched_request
        or normalized_unmatched_request in normalized_raw_text
    )


def _generated_procedure_code(kind: str, raw_text: str, name_cn: str) -> str:
    digest = hashlib.sha1(f"{kind}:{raw_text}:{name_cn}".encode("utf-8")).hexdigest()[:12]
    normalized_kind = re.sub(r"[^a-z0-9_]+", "_", kind.lower()).strip("_") or "other"
    return f"{normalized_kind}.{digest}"


def _routed_procedure_label_prefix(kind: str) -> str:
    if kind == "physical_exam":
        return "查体"
    if kind == "auxiliary_test":
        return "检查"
    if kind == "vital_sign":
        return "生命体征"
    if kind == "patient_profile":
        return "信息"
    return "申请"


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


def _dedupe_non_empty(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _normalize_procedure_codes(
    values: list[str],
    *,
    procedure_kind: str,
    require_single: bool,
) -> list[str]:
    if len(values) > MAX_PROCEDURE_CODES_PER_REQUEST:
        raise InvalidProcedureRequestError(procedure_kind)
    normalized_codes = _dedupe_non_empty(values)
    if require_single and len(normalized_codes) != 1:
        raise InvalidProcedureRequestError(procedure_kind)
    if any(len(code) > MAX_PROCEDURE_CODE_LENGTH for code in normalized_codes):
        raise InvalidProcedureRequestError(procedure_kind)
    return normalized_codes


def _build_physical_exam_request_result(
    exam_code: str,
    *,
    case_exam_map: dict[str, PhysicalExamItem],
    catalog_exam_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    configured_exam = case_exam_map.get(exam_code)
    if configured_exam is not None:
        return {
            "exam_code": exam_code,
            "exam_name_cn": configured_exam.exam_name_cn,
            "result": configured_exam.result,
            "availability_status": "case_configured",
        }
    return {
        "exam_code": exam_code,
        "exam_name_cn": str(catalog_exam_map[exam_code]["exam_name_cn"]),
        "result": "该项目已记录，但本训练站点未提供该查体结果。",
        "availability_status": "not_available_for_case",
    }


def _build_auxiliary_test_request_result(
    test_code: str,
    *,
    case_test_map: dict[str, AuxiliaryTestItem],
    catalog_test_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    configured_test = case_test_map.get(test_code)
    if configured_test is not None:
        return {
            "test_code": test_code,
            "test_name_cn": configured_test.test_name_cn,
            "result": configured_test.result,
            "availability_status": "case_configured",
        }
    return {
        "test_code": test_code,
        "test_name_cn": str(catalog_test_map[test_code]["test_name_cn"]),
        "result": "该项目已记录，但本训练站点未提供该辅助检查结果。",
        "availability_status": "not_available_for_case",
    }


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
    }


def _serialize_physical_exam_option(exam: PhysicalExamItem) -> dict[str, Any]:
    return {
        "exam_code": exam.exam_code,
        "exam_name_cn": exam.exam_name_cn,
    }


def _serialize_auxiliary_test_option(test: AuxiliaryTestItem) -> dict[str, Any]:
    return {
        "test_code": test.test_code,
        "test_name_cn": test.test_name_cn,
        "category": test.category,
        "invasiveness": test.invasiveness,
        "cost_hint": test.cost_hint,
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


def _serialize_student_training_progress(session: OsceSession, case: Case) -> dict[str, Any]:
    fact_ids = [
        (fact.fact_id, _student_safe_evidence_id(case, fact.fact_id))
        for fact in case.history.hidden_facts
    ]
    covered_fact_ids = [safe_id for fact_id, safe_id in fact_ids if fact_id in session.revealed_facts]
    exam_codes = _physical_exam_codes(case.physical_exam.must_items, case.physical_exam.optional_items)
    test_codes = _auxiliary_test_codes(case.auxiliary_tests.must_items, case.auxiliary_tests.optional_items)
    requested_exam_codes = [exam_code for exam_code in exam_codes if exam_code in session.requested_exams]
    requested_test_codes = [test_code for test_code in test_codes if test_code in session.requested_tests]
    collected_reasoning_evidence = [
        evidence for evidence in _reasoning_evidence(case) if _session_has_evidence(session, evidence)
    ]

    return {
        "history": {
            "total": len(fact_ids),
            "covered": len(covered_fact_ids),
        },
        "physical_exam": {
            "total": len(exam_codes),
            "requested": len(requested_exam_codes),
        },
        "auxiliary_test": {
            "total": len(test_codes),
            "requested": len(requested_test_codes),
        },
        "reasoning": {
            "collected_evidence_count": len(collected_reasoning_evidence),
            "ready_for_hypothesis": bool(covered_fact_ids and requested_exam_codes and requested_test_codes),
        },
        "revealed_items": _serialize_student_revealed_items(
            session,
            case,
            collected_reasoning_evidence,
        ),
        "next_focus": _training_progress_next_focus(
            session,
            covered_fact_ids,
            requested_exam_codes,
            requested_test_codes,
        ),
    }


def _serialize_student_revealed_items(
    session: OsceSession,
    case: Case,
    collected_reasoning_evidence: list[str],
) -> dict[str, list[dict[str, Any]]]:
    history_items = [
        {
            "id": _student_safe_evidence_id(case, fact.fact_id),
            "label": fact.canonical_answer,
            "topic": fact.topic,
            "slot": fact.slot,
        }
        for fact in case.history.hidden_facts
        if fact.fact_id in session.revealed_facts
    ]
    physical_exam_items = [
        {
            "id": exam.exam_code,
            "label": exam.exam_name_cn,
        }
        for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]
        if exam.exam_code in session.requested_exams
    ]
    auxiliary_test_items = [
        {
            "id": test.test_code,
            "label": test.test_name_cn,
        }
        for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]
        if test.test_code in session.requested_tests
    ]
    reasoning_items = [
        {
            "id": _student_safe_evidence_id(case, evidence),
            "label": _student_revealed_reasoning_label(case, evidence),
        }
        for evidence in collected_reasoning_evidence
    ]
    return {
        "history": history_items,
        "physical_exam": physical_exam_items,
        "auxiliary_test": auxiliary_test_items,
        "reasoning": reasoning_items,
    }


def _student_revealed_reasoning_label(case: Case, evidence: str) -> str:
    for fact in case.history.hidden_facts:
        if fact.fact_id == evidence:
            return fact.canonical_answer
    for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]:
        if exam.exam_code == evidence:
            return exam.exam_name_cn
    for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]:
        if test.test_code == evidence:
            return test.test_name_cn
    return _student_safe_evidence_id(case, evidence)


def _serialize_collected_procedure_results(session: OsceSession, case: Case) -> dict[str, list[dict[str, str]]]:
    case_exam_map = _case_physical_exam_map(case)
    case_test_map = _case_auxiliary_test_map(case)
    catalog_exam_map = _catalog_physical_exam_map()
    catalog_test_map = _catalog_auxiliary_test_map()
    physical_exams: list[dict[str, str]] = []
    auxiliary_tests: list[dict[str, str]] = []

    for exam_code in session.requested_exams:
        exam = case_exam_map.get(exam_code)
        physical_exams.append(
            {
                "exam_code": exam_code,
                "exam_name_cn": (
                    exam.exam_name_cn
                    if exam is not None
                    else str(catalog_exam_map.get(exam_code, {}).get("exam_name_cn") or "未提供查体")
                ),
                "result": (
                    exam.result
                    if exam is not None
                    else "该项目已记录，但本训练站点未提供该查体结果。"
                ),
            }
        )

    for test_code in session.requested_tests:
        test = case_test_map.get(test_code)
        auxiliary_tests.append(
            {
                "test_code": test_code,
                "test_name_cn": (
                    test.test_name_cn
                    if test is not None
                    else str(catalog_test_map.get(test_code, {}).get("test_name_cn") or "未提供检查")
                ),
                "result": (
                    test.result
                    if test is not None
                    else "该项目已记录，但本训练站点未提供该辅助检查结果。"
                ),
            }
        )

    return {
        "physical_exams": physical_exams,
        "auxiliary_tests": auxiliary_tests,
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


def _selected_skill_ids(
    active_skill_context: dict[str, Any],
) -> set[str]:
    selected_skills = active_skill_context.get("selected_skills", [])
    if not isinstance(selected_skills, list):
        return set()
    return {
        skill_id
        for skill in selected_skills
        if isinstance(skill, dict)
        and (skill_id := str(skill.get("skill_id", "")).strip())
    }


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


def _serialize_student_pedagogy_state(session: OsceSession) -> dict[str, Any]:
    clinical_reasoning_state = session.pedagogy_state.get("clinical_reasoning_state")
    if not isinstance(clinical_reasoning_state, dict):
        return {}
    next_best_action = clinical_reasoning_state.get("next_best_action")
    return {
        "clinical_reasoning_state": {
            "last_action_stage": str(clinical_reasoning_state.get("last_action_stage") or session.stage),
            "pedagogical_phase": str(clinical_reasoning_state.get("pedagogical_phase") or ""),
            "readiness": dict(clinical_reasoning_state.get("readiness") or {}),
            "sequence_flags": [
                str(flag)
                for flag in clinical_reasoning_state.get("sequence_flags", [])
                if str(flag).strip()
            ],
            "next_best_action": (
                {
                    "action_type": str(next_best_action.get("action_type") or ""),
                    "target_category": str(next_best_action.get("target_category") or ""),
                    "message": str(next_best_action.get("message") or ""),
                    "why": str(next_best_action.get("why") or ""),
                }
                if isinstance(next_best_action, dict)
                else {
                    "action_type": "",
                    "target_category": "",
                    "message": "",
                    "why": "",
                }
            ),
            "socratic_question": str(clinical_reasoning_state.get("socratic_question") or ""),
            "reasoning_rationale": str(clinical_reasoning_state.get("reasoning_rationale") or ""),
            "safety_note": str(clinical_reasoning_state.get("safety_note") or ""),
        }
    }


def _serialize_student_agent_turn_memory(session: OsceSession) -> list[dict[str, Any]]:
    return [
        {
            "turn_id": str(turn.get("turn_id") or ""),
            "student_message": str(turn.get("student_message") or ""),
            "reply": str(turn.get("reply") or ""),
            "reply_role": str(turn.get("reply_role") or ""),
            "current_intents": [
                str(intent)
                for intent in turn.get("current_intents", [])
                if str(intent).strip()
            ],
            "turn_policy": str(turn.get("turn_policy") or ""),
            "revealed_fact_count": len(
                turn.get("revealed_fact_ids")
                or ([turn.get("revealed_fact_id")] if turn.get("revealed_fact_id") else [])
            ),
            "selected_skill_count": len(turn.get("selected_skill_ids") or turn.get("selected_skill_reasons") or []),
            "knowledge_reference_count": len(turn.get("knowledge_references") or []),
            "processing_trace": _serialize_student_processing_trace(turn.get("processing_trace")),
            "processing_duration_ms": turn.get("processing_duration_ms"),
            "safety_flags": [
                str(flag)
                for flag in turn.get("safety_flags", [])
                if str(flag).strip()
            ],
        }
        for turn in session.agent_turn_memory
        if isinstance(turn, dict)
    ]


def _serialize_student_processing_trace(raw_trace: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_trace, list):
        return []
    serialized_trace: list[dict[str, Any]] = []
    for step in raw_trace:
        if not isinstance(step, dict):
            continue
        raw_metadata = step.get("metadata")
        metadata: dict[str, Any] = {}
        if isinstance(raw_metadata, dict):
            for key in ("retrieved_count", "retrievedCount", "reply_role"):
                if key in raw_metadata:
                    metadata[key] = raw_metadata[key]
        serialized_step = {
            "step_id": str(step.get("step_id") or ""),
            "label": str(step.get("label") or ""),
            "status": str(step.get("status") or ""),
            "started_at": str(step.get("started_at") or ""),
            "completed_at": str(step.get("completed_at") or ""),
            "duration_ms": step.get("duration_ms") if isinstance(step.get("duration_ms"), (int, float)) else 0,
        }
        if metadata:
            serialized_step["metadata"] = metadata
        serialized_trace.append(serialized_step)
    return serialized_trace


def _serialize_session(session: OsceSession, case: Case) -> dict[str, Any]:
    include_case_specific_options = session.training_difficulty == "beginner"
    return {
        "payload_schema_version": "student_session.v2",
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
        "diagnosis_draft": _serialize_diagnosis_draft(case),
        "physical_exam_options": (
            [
                _serialize_physical_exam_option(exam)
                for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]
            ]
            if include_case_specific_options
            else []
        ),
        "auxiliary_test_options": (
            [
                _serialize_auxiliary_test_option(test)
                for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]
            ]
            if include_case_specific_options
            else []
        ),
        "collected_procedure_results": _serialize_collected_procedure_results(session, case),
        "training_progress": _serialize_student_training_progress(session, case),
        "messages": session.messages,
        "asked_questions": session.asked_questions,
        "revealed_facts": session.revealed_facts,
        "requested_exams": session.requested_exams,
        "requested_tests": session.requested_tests,
        "student_hypotheses": session.student_hypotheses,
        "final_submission": session.final_submission,
        "feedback_report": session.feedback_report,
        "safety_flags": session.safety_flags,
        "agent_turn_memory": _serialize_student_agent_turn_memory(session),
        "pedagogy_state": _serialize_student_pedagogy_state(session),
        "teacher_intervention": latest_student_safe_intervention(session.teacher_decision_records),
    }


def _empty_active_skill_context() -> dict[str, list[dict[str, Any]]]:
    return {"skill_index": [], "selected_skills": [], "skipped_reasons": []}


osce_session_service = OsceSessionService()
