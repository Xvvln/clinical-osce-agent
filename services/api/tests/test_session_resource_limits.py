from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Barrier
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import AUTH_COOKIE_NAME
from app.services.auth_store import AuthStore
from app.services.osce_session_service import OsceSessionService
from app.services.osce_session_store import (
    OsceSessionStore,
    SessionWriteConflictError,
)
from app.services.report_store import ReportStore
from app.services.session_resource_policy import (
    MAX_HINT_REQUESTS_PER_SESSION,
    MAX_HYPOTHESIS_RECORDS_PER_SESSION,
    MAX_STUDENT_TURNS_PER_SESSION,
    SessionResourceLimitError,
)
from app.services.student_profile_store import StudentProfileStore
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_store import TrainingSkillStore


ResourceKind = Literal["message", "hint", "hypothesis"]


@dataclass(frozen=True)
class _ResourceContract:
    kind: ResourceKind
    counter_field: str
    maximum: int
    endpoint_suffix: str
    accepted_payload: dict[str, str] | None
    rejected_payload: dict[str, str] | None
    expected_detail: str
    rejected_sentinel: str | None = None


RESOURCE_CONTRACTS = (
    pytest.param(
        _ResourceContract(
            kind="message",
            counter_field="student_turn_count",
            maximum=MAX_STUDENT_TURNS_PER_SESSION,
            endpoint_suffix="/message",
            accepted_payload={"message": "上限前最后一轮：什么时候开始疼的？"},
            rejected_payload={
                "message": "REJECTED-MESSAGE-SENTINEL：这条问诊不能进入训练记录。"
            },
            expected_detail="本次训练的问诊轮次已达到上限，请提交诊断或开始新的训练。",
            rejected_sentinel="REJECTED-MESSAGE-SENTINEL",
        ),
        id="student-turns",
    ),
    pytest.param(
        _ResourceContract(
            kind="hint",
            counter_field="hint_request_count",
            maximum=MAX_HINT_REQUESTS_PER_SESSION,
            endpoint_suffix="/hint",
            accepted_payload=None,
            rejected_payload=None,
            expected_detail="本次训练的过程提示次数已达到上限，请结合现有线索继续训练。",
        ),
        id="hints",
    ),
    pytest.param(
        _ResourceContract(
            kind="hypothesis",
            counter_field="hypothesis_record_count",
            maximum=MAX_HYPOTHESIS_RECORDS_PER_SESSION,
            endpoint_suffix="/hypotheses",
            accepted_payload={"hypothesis": "上限前最后一个显式诊断假设"},
            rejected_payload={
                "hypothesis": "REJECTED-HYPOTHESIS-SENTINEL：这条假设不能进入训练记录。"
            },
            expected_detail="本次训练记录的诊断假设已达到上限，请整理现有假设后提交诊断。",
            rejected_sentinel="REJECTED-HYPOTHESIS-SENTINEL",
        ),
        id="explicit-hypotheses",
    ),
)


class _ProviderProbe:
    def __init__(self) -> None:
        self.calls: list[ResourceKind | Literal["diagnosis"]] = []

    def invoke(self, operation: ResourceKind | Literal["diagnosis"]) -> None:
        self.calls.append(operation)


class _CountingTrainingGraph:
    """Small deterministic graph double that keeps the tests provider-free."""

    def __init__(self, provider: _ProviderProbe) -> None:
        self.provider = provider
        self.calls: list[ResourceKind | Literal["create", "diagnosis"]] = []

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        operation = self._operation_from_state(state)
        self.calls.append(operation)
        next_state = dict(state)

        if operation == "create":
            next_state["stage"] = "case_intro"
            return next_state

        self.provider.invoke(operation)
        progress_callback = state.get("processing_progress_callback")
        if callable(progress_callback):
            progress_callback(
                {
                    "step_id": f"fake_{operation}",
                    "label": f"测试 {operation}",
                    "status": "active",
                }
            )

        if operation == "message":
            message = str(state.get("student_message") or "")
            next_state.update(
                {
                    "stage": "history_taking",
                    "messages": [
                        *state.get("messages", []),
                        {"role": "student", "content": message},
                        {"role": "patient", "content": "这是边界测试中的标准化病人回复。"},
                    ],
                    "asked_questions": [
                        *state.get("asked_questions", []),
                        message,
                    ],
                    "intent_history": [
                        *state.get("intent_history", []),
                        "ask_onset",
                    ],
                    "current_intents": ["ask_onset"],
                    "reply": "这是边界测试中的标准化病人回复。",
                    "agent_turn_memory": [
                        *state.get("agent_turn_memory", []),
                        {
                            "student_message": message,
                            "reply": "这是边界测试中的标准化病人回复。",
                            "reply_role": "patient",
                            "current_intents": ["ask_onset"],
                            "turn_policy": "patient_fact_answer",
                        },
                    ],
                }
            )
            return next_state

        if operation == "hint":
            hint = "这是边界测试中的过程提示。"
            next_state.update(
                {
                    "hint": hint,
                    "messages": [
                        *state.get("messages", []),
                        {"role": "coach", "content": hint},
                    ],
                    "agent_turn_memory": [
                        *state.get("agent_turn_memory", []),
                        {
                            "student_message": "请求提示",
                            "reply": hint,
                            "reply_role": "coach",
                            "current_intents": ["socratic_hint"],
                            "turn_policy": "teaching_hint",
                        },
                    ],
                }
            )
            return next_state

        diagnosis = str(state.get("submitted_diagnosis") or "")
        next_state.update(
            {
                "stage": "diagnosis_submission",
                "final_submission": {
                    "diagnosis": diagnosis,
                    "reasoning": str(state.get("submitted_reasoning") or ""),
                },
                # The real graph proposes the final diagnosis as another
                # hypothesis. The service policy must keep the explicit-history
                # cap without blocking completion.
                "student_hypotheses": [
                    *state.get("student_hypotheses", []),
                    diagnosis,
                ],
            }
        )
        return next_state

    @staticmethod
    def _operation_from_state(
        state: dict[str, Any],
    ) -> ResourceKind | Literal["create", "diagnosis"]:
        if state.get("hint_requested"):
            return "hint"
        if state.get("submitted_diagnosis"):
            return "diagnosis"
        if "student_message" in state:
            return "message"
        return "create"


class _BarrierTrainingGraph(_CountingTrainingGraph):
    def __init__(self, provider: _ProviderProbe, barrier: Barrier) -> None:
        super().__init__(provider)
        self.barrier = barrier

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        if self._operation_from_state(state) == "message":
            self.barrier.wait(timeout=5)
        return super().invoke(state)


class _FailingTrainingGraph(_CountingTrainingGraph):
    def __init__(
        self,
        provider: _ProviderProbe,
        failing_operation: Literal["message", "hint"],
    ) -> None:
        super().__init__(provider)
        self.failing_operation = failing_operation

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        operation = self._operation_from_state(state)
        if operation == self.failing_operation:
            self.calls.append(operation)
            self.provider.invoke(operation)
            raise RuntimeError(f"forced {operation} failure")
        return super().invoke(state)


@dataclass(frozen=True)
class _ServiceSnapshot:
    live_payload: dict[str, Any]
    persisted_payload: dict[str, Any]
    revision: int
    events: list[dict[str, Any]]
    processing_status: dict[str, Any]
    graph_calls: tuple[str, ...]
    provider_calls: tuple[str, ...]


def _build_service(
    storage_dir: Path,
    graph: _CountingTrainingGraph,
) -> OsceSessionService:
    return OsceSessionService(
        report_store=ReportStore(storage_dir / "reports.sqlite3"),
        training_event_store=TrainingEventStore(
            storage_dir / "training_events.sqlite3"
        ),
        training_skill_store=TrainingSkillStore(
            storage_dir / "training_skills.sqlite3"
        ),
        training_skill_candidate_store=TrainingSkillCandidateStore(
            storage_dir / "training_skill_candidates.sqlite3"
        ),
        session_store=OsceSessionStore(storage_dir / "osce_sessions.sqlite3"),
        student_profile_store=StudentProfileStore(
            storage_dir / "student_profiles.sqlite3"
        ),
        graph=graph,
    )


def _build_authenticated_client(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    service: OsceSessionService,
) -> tuple[TestClient, str]:
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    user = auth_store.create_user(
        "resource-limit-student@example.test",
        "safe-password-123",
        "资源上限测试学生",
    )
    assert user is not None
    token = auth_store.create_session(str(user["user_id"]))
    monkeypatch.setattr(main, "auth_store", auth_store)
    monkeypatch.setattr(main, "osce_session_service", service)
    client = TestClient(main.app, raise_server_exceptions=False)
    client.cookies.set(AUTH_COOKIE_NAME, token)
    return client, str(user["user_id"])


def _post_training_action(
    client: TestClient,
    session_id: str,
    contract: _ResourceContract,
    *,
    accepted: bool,
) -> Any:
    payload = (
        contract.accepted_payload if accepted else contract.rejected_payload
    )
    path = f"/api/sessions/{session_id}{contract.endpoint_suffix}"
    return client.post(path, json=payload) if payload is not None else client.post(path)


def _call_service_action(
    service: OsceSessionService,
    session_id: str,
    contract: _ResourceContract,
) -> dict[str, Any] | None:
    if contract.kind == "message":
        return service.handle_message(session_id, "不能进入已满会话的问诊")
    if contract.kind == "hint":
        return service.request_hint(session_id)
    return service.record_hypothesis(session_id, "不能进入已满会话的假设")


def _prime_one_below_limit(
    service: OsceSessionService,
    session_id: str,
    contract: _ResourceContract,
) -> None:
    session = service._get_session(session_id)
    assert session is not None
    setattr(session, contract.counter_field, contract.maximum - 1)
    if contract.kind == "hypothesis":
        session.student_hypotheses = [
            f"显式诊断假设 {index + 1}"
            for index in range(contract.maximum - 1)
        ]
    service._save_session(session)


def _snapshot(
    service: OsceSessionService,
    graph: _CountingTrainingGraph,
    session_id: str,
) -> tuple[Any, _ServiceSnapshot]:
    live_session = service._get_session(session_id)
    stored_session = service.session_store.get_session(session_id)
    assert live_session is not None
    assert stored_session is not None
    return live_session, _ServiceSnapshot(
        live_payload=deepcopy(asdict(live_session)),
        persisted_payload=deepcopy(stored_session.payload),
        revision=stored_session.revision,
        events=deepcopy(
            service.training_event_store.list_session_events(session_id)
        ),
        processing_status=deepcopy(
            service.get_message_processing_status(session_id)
        ),
        graph_calls=tuple(graph.calls),
        provider_calls=tuple(graph.provider.calls),
    )


def _assert_rejection_has_no_side_effects(
    *,
    service: OsceSessionService,
    graph: _CountingTrainingGraph,
    session_id: str,
    held_session: Any,
    before: _ServiceSnapshot,
) -> None:
    current_session = service._get_session(session_id)
    stored_session = service.session_store.get_session(session_id)
    assert current_session is held_session
    assert current_session is not None
    assert stored_session is not None
    assert asdict(current_session) == before.live_payload
    assert stored_session.payload == before.persisted_payload
    assert stored_session.revision == before.revision
    assert (
        service.training_event_store.list_session_events(session_id)
        == before.events
    )
    assert service.get_message_processing_status(session_id) == (
        before.processing_status
    )
    assert tuple(graph.calls) == before.graph_calls
    assert tuple(graph.provider.calls) == before.provider_calls


def test_session_resource_policy_uses_declared_limits() -> None:
    assert MAX_STUDENT_TURNS_PER_SESSION == 40
    assert MAX_HINT_REQUESTS_PER_SESSION == 20
    assert MAX_HYPOTHESIS_RECORDS_PER_SESSION == 20


def test_successful_empty_message_still_consumes_a_student_turn(
    tmp_path: Path,
) -> None:
    graph = _CountingTrainingGraph(_ProviderProbe())
    service = _build_service(tmp_path, graph)
    session_id = str(
        service.create_session(
            "appendicitis_001",
            "empty-message-student",
        )["session_id"]
    )

    payload = service.handle_message(session_id, "")

    assert payload is not None
    session = service._get_session(session_id)
    assert session is not None
    assert session.student_turn_count == 1
    assert graph.provider.calls == ["message"]


@pytest.mark.parametrize("contract", RESOURCE_CONTRACTS)
def test_session_resource_limit_accepts_boundary_then_returns_fixed_409_without_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contract: _ResourceContract,
) -> None:
    provider = _ProviderProbe()
    graph = _CountingTrainingGraph(provider)
    service = _build_service(tmp_path, graph)
    client, student_id = _build_authenticated_client(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        service=service,
    )
    try:
        session_id = str(
            service.create_session("appendicitis_001", student_id)["session_id"]
        )
        _prime_one_below_limit(service, session_id, contract)

        accepted_response = _post_training_action(
            client,
            session_id,
            contract,
            accepted=True,
        )

        assert accepted_response.status_code == 200
        session_at_limit = service._get_session(session_id)
        assert session_at_limit is not None
        assert (
            getattr(session_at_limit, contract.counter_field)
            == contract.maximum
        )
        if contract.kind == "hypothesis":
            assert len(session_at_limit.student_hypotheses) == contract.maximum

        held_session, before_rejection = _snapshot(
            service,
            graph,
            session_id,
        )
        rejected_response = _post_training_action(
            client,
            session_id,
            contract,
            accepted=False,
        )

        assert rejected_response.status_code == 409
        assert rejected_response.json() == {
            "detail": contract.expected_detail,
        }
        assert len(rejected_response.content) < 256
        if contract.rejected_sentinel is not None:
            assert contract.rejected_sentinel not in rejected_response.text
        _assert_rejection_has_no_side_effects(
            service=service,
            graph=graph,
            session_id=session_id,
            held_session=held_session,
            before=before_rejection,
        )

        rebuilt_provider = _ProviderProbe()
        rebuilt_graph = _CountingTrainingGraph(rebuilt_provider)
        rebuilt_service = _build_service(tmp_path, rebuilt_graph)
        monkeypatch.setattr(main, "osce_session_service", rebuilt_service)
        rebuilt_held_session, rebuilt_before = _snapshot(
            rebuilt_service,
            rebuilt_graph,
            session_id,
        )

        rebuilt_response = _post_training_action(
            client,
            session_id,
            contract,
            accepted=False,
        )

        assert rebuilt_response.status_code == 409
        assert rebuilt_response.json() == {
            "detail": contract.expected_detail,
        }
        if contract.rejected_sentinel is not None:
            assert contract.rejected_sentinel not in rebuilt_response.text
        _assert_rejection_has_no_side_effects(
            service=rebuilt_service,
            graph=rebuilt_graph,
            session_id=session_id,
            held_session=rebuilt_held_session,
            before=rebuilt_before,
        )
    finally:
        client.close()


@pytest.mark.parametrize(
    "explicit_hypothesis_count",
    (
        MAX_HYPOTHESIS_RECORDS_PER_SESSION,
        MAX_HYPOTHESIS_RECORDS_PER_SESSION + 3,
    ),
    ids=("at-current-limit", "legacy-above-current-limit"),
)
def test_final_diagnosis_preserves_explicit_hypotheses_at_or_above_the_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    explicit_hypothesis_count: int,
) -> None:
    provider = _ProviderProbe()
    graph = _CountingTrainingGraph(provider)
    service = _build_service(tmp_path, graph)
    client, student_id = _build_authenticated_client(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        service=service,
    )
    try:
        session_id = str(
            service.create_session("appendicitis_001", student_id)["session_id"]
        )
        session = service._get_session(session_id)
        assert session is not None
        explicit_hypotheses = [
            f"显式诊断假设 {index + 1}"
            for index in range(explicit_hypothesis_count)
        ]
        session.student_hypotheses = list(explicit_hypotheses)
        session.hypothesis_record_count = explicit_hypothesis_count
        service._save_session(session)

        response = client.post(
            f"/api/sessions/{session_id}/submit-diagnosis",
            json={
                "diagnosis": "最终诊断",
                "reasoning": "已有病史、查体和检查证据支持最终诊断。",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["final_submission"] == {
            "diagnosis": "最终诊断",
            "reasoning": "已有病史、查体和检查证据支持最终诊断。",
        }
        assert payload["student_hypotheses"] == explicit_hypotheses
        assert len(payload["student_hypotheses"]) == explicit_hypothesis_count

        persisted = service.session_store.get_session_payload(session_id)
        assert persisted is not None
        assert persisted["final_submission"] == payload["final_submission"]
        assert persisted["student_hypotheses"] == explicit_hypotheses
        assert (
            persisted["hypothesis_record_count"]
            == explicit_hypothesis_count
        )
        assert graph.calls[-1] == "diagnosis"
        assert provider.calls[-1] == "diagnosis"
    finally:
        client.close()


def test_counterless_legacy_session_above_the_hypothesis_limit_keeps_its_history_on_submit(
    tmp_path: Path,
) -> None:
    initial_graph = _CountingTrainingGraph(_ProviderProbe())
    initial_service = _build_service(tmp_path, initial_graph)
    session_id = str(
        initial_service.create_session(
            "appendicitis_001",
            "legacy-over-limit-student",
        )["session_id"]
    )
    stored = initial_service.session_store.get_session(session_id)
    assert stored is not None
    explicit_hypotheses = [
        f"旧版显式诊断假设 {index + 1}"
        for index in range(MAX_HYPOTHESIS_RECORDS_PER_SESSION + 3)
    ]
    legacy_payload = deepcopy(stored.payload)
    legacy_payload["student_hypotheses"] = list(explicit_hypotheses)
    legacy_payload.pop("hypothesis_record_count", None)
    with sqlite3.connect(initial_service.session_store.database_path) as connection:
        connection.execute(
            "UPDATE osce_sessions SET session_json = ? WHERE session_id = ?",
            (json.dumps(legacy_payload, ensure_ascii=False), session_id),
        )

    rebuilt_graph = _CountingTrainingGraph(_ProviderProbe())
    rebuilt_service = _build_service(tmp_path, rebuilt_graph)
    payload = rebuilt_service.submit_diagnosis(
        session_id,
        "最终诊断",
        "旧会话的历史假设必须完整保留。",
    )

    assert payload is not None
    assert payload["student_hypotheses"] == explicit_hypotheses
    assert payload["final_submission"] == {
        "diagnosis": "最终诊断",
        "reasoning": "旧会话的历史假设必须完整保留。",
    }
    persisted = rebuilt_service.session_store.get_session_payload(session_id)
    assert persisted is not None
    assert persisted["student_hypotheses"] == explicit_hypotheses
    assert persisted["hypothesis_record_count"] == 0


@pytest.mark.parametrize(
    ("operation", "counter_field", "maximum"),
    (
        ("message", "student_turn_count", MAX_STUDENT_TURNS_PER_SESSION),
        ("hint", "hint_request_count", MAX_HINT_REQUESTS_PER_SESSION),
    ),
)
def test_failed_graph_request_does_not_consume_the_last_resource_slot(
    tmp_path: Path,
    operation: Literal["message", "hint"],
    counter_field: str,
    maximum: int,
) -> None:
    failing_provider = _ProviderProbe()
    failing_graph = _FailingTrainingGraph(failing_provider, operation)
    failing_service = _build_service(tmp_path, failing_graph)
    session_id = str(
        failing_service.create_session(
            "appendicitis_001",
            f"failing-{operation}-student",
        )["session_id"]
    )
    session = failing_service._get_session(session_id)
    assert session is not None
    setattr(session, counter_field, maximum - 1)
    failing_service._save_session(session)
    before = failing_service.session_store.get_session(session_id)
    assert before is not None

    with pytest.raises(RuntimeError, match=f"forced {operation} failure"):
        if operation == "message":
            failing_service.handle_message(session_id, "这次失败不能消耗最后一轮")
        else:
            failing_service.request_hint(session_id)

    after_failure = failing_service.session_store.get_session(session_id)
    assert after_failure == before
    live_after_failure = failing_service._get_session(session_id)
    assert live_after_failure is not None
    assert getattr(live_after_failure, counter_field) == maximum - 1
    assert failing_provider.calls == [operation]

    succeeding_graph = _CountingTrainingGraph(_ProviderProbe())
    succeeding_service = _build_service(tmp_path, succeeding_graph)
    if operation == "message":
        payload = succeeding_service.handle_message(
            session_id,
            "失败后仍可使用最后一轮",
        )
    else:
        payload = succeeding_service.request_hint(session_id)

    assert payload is not None
    persisted = succeeding_service.session_store.get_session(session_id)
    assert persisted is not None
    assert persisted.payload[counter_field] == maximum


@pytest.mark.parametrize("contract", RESOURCE_CONTRACTS)
def test_legacy_session_history_enforces_limits_without_counter_fields(
    tmp_path: Path,
    contract: _ResourceContract,
) -> None:
    initial_graph = _CountingTrainingGraph(_ProviderProbe())
    initial_service = _build_service(tmp_path, initial_graph)
    session_id = str(
        initial_service.create_session(
            "appendicitis_001",
            "legacy-student",
        )["session_id"]
    )
    stored = initial_service.session_store.get_session(session_id)
    assert stored is not None
    legacy_payload = deepcopy(stored.payload)
    for counter_field in (
        "student_turn_count",
        "hint_request_count",
        "hypothesis_record_count",
    ):
        legacy_payload.pop(counter_field, None)
    if contract.kind == "message":
        legacy_payload["messages"] = [
            {"role": "student", "content": f"历史问诊 {index + 1}"}
            for index in range(contract.maximum)
        ]
    elif contract.kind == "hint":
        legacy_payload["agent_turn_memory"] = [
            {
                "student_message": "请求提示",
                "current_intent": "socratic_hint",
                "turn_policy": "teaching_hint",
            }
            for _ in range(contract.maximum)
        ]
    else:
        legacy_payload["student_hypotheses"] = [
            f"历史假设 {index + 1}"
            for index in range(contract.maximum)
        ]
    with sqlite3.connect(initial_service.session_store.database_path) as connection:
        connection.execute(
            "UPDATE osce_sessions SET session_json = ? WHERE session_id = ?",
            (json.dumps(legacy_payload, ensure_ascii=False), session_id),
        )

    rebuilt_graph = _CountingTrainingGraph(_ProviderProbe())
    rebuilt_service = _build_service(tmp_path, rebuilt_graph)
    before = rebuilt_service.session_store.get_session(session_id)
    assert before is not None

    with pytest.raises(SessionResourceLimitError) as raised:
        _call_service_action(rebuilt_service, session_id, contract)

    assert raised.value.resource_kind == contract.kind
    assert rebuilt_graph.calls == []
    assert rebuilt_graph.provider.calls == []
    after = rebuilt_service.session_store.get_session(session_id)
    assert after == before


@pytest.mark.parametrize(
    ("resource_kind", "maximum", "event_type"),
    (
        ("message", MAX_STUDENT_TURNS_PER_SESSION, "history_message"),
        ("hint", MAX_HINT_REQUESTS_PER_SESSION, "hint_requested"),
        (
            "hypothesis",
            MAX_HYPOTHESIS_RECORDS_PER_SESSION,
            "hypothesis_recorded",
        ),
    ),
    ids=("student-turn-events", "hint-events", "hypothesis-events"),
)
def test_legacy_event_history_enforces_limits_without_counters_or_session_history(
    tmp_path: Path,
    resource_kind: ResourceKind,
    maximum: int,
    event_type: str,
) -> None:
    initial_graph = _CountingTrainingGraph(_ProviderProbe())
    initial_service = _build_service(tmp_path, initial_graph)
    session_id = str(
        initial_service.create_session(
            "appendicitis_001",
            f"legacy-{resource_kind}-event-student",
        )["session_id"]
    )
    stored = initial_service.session_store.get_session(session_id)
    assert stored is not None
    legacy_payload = deepcopy(stored.payload)
    for counter_field in (
        "student_turn_count",
        "hint_request_count",
        "hypothesis_record_count",
    ):
        legacy_payload.pop(counter_field, None)
    legacy_payload["messages"] = []
    legacy_payload["agent_turn_memory"] = []
    legacy_payload["student_hypotheses"] = []
    with sqlite3.connect(initial_service.session_store.database_path) as connection:
        connection.execute(
            "UPDATE osce_sessions SET session_json = ? WHERE session_id = ?",
            (json.dumps(legacy_payload, ensure_ascii=False), session_id),
        )
    for index in range(maximum):
        initial_service.training_event_store.append_event(
            session_id=session_id,
            case_id=str(legacy_payload["case_id"]),
            student_id=str(legacy_payload["student_id"]),
            event_type=event_type,
            payload={"legacy_sequence": index + 1},
        )

    rebuilt_graph = _CountingTrainingGraph(_ProviderProbe())
    rebuilt_service = _build_service(tmp_path, rebuilt_graph)
    with pytest.raises(SessionResourceLimitError) as raised:
        if resource_kind == "message":
            rebuilt_service.handle_message(
                session_id,
                "事件流已经证明旧会话没有剩余问诊轮次",
            )
        elif resource_kind == "hint":
            rebuilt_service.request_hint(session_id)
        else:
            rebuilt_service.record_hypothesis(
                session_id,
                "事件流已经证明旧会话没有剩余假设名额",
            )

    assert raised.value.resource_kind == resource_kind
    assert rebuilt_graph.calls == []
    assert rebuilt_graph.provider.calls == []


def test_two_services_compete_for_only_one_remaining_student_turn(
    tmp_path: Path,
) -> None:
    barrier = Barrier(2)
    first_graph = _BarrierTrainingGraph(_ProviderProbe(), barrier)
    second_graph = _BarrierTrainingGraph(_ProviderProbe(), barrier)
    first_service = _build_service(tmp_path, first_graph)
    second_service = _build_service(tmp_path, second_graph)
    session_id = str(
        first_service.create_session(
            "appendicitis_001",
            "concurrent-student",
        )["session_id"]
    )
    session = first_service._get_session(session_id)
    assert session is not None
    session.student_turn_count = MAX_STUDENT_TURNS_PER_SESSION - 1
    first_service._save_session(session)
    stale_second_session = second_service._get_session(session_id)
    assert stale_second_session is not None

    services = [first_service, second_service]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                service.handle_message,
                session_id,
                f"并发争用同一个问诊名额 {index + 1}",
            )
            for index, service in enumerate(services)
        ]
    outcomes: list[dict[str, Any] | BaseException | None] = []
    for future in futures:
        try:
            outcomes.append(future.result())
        except BaseException as exc:
            outcomes.append(exc)

    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert sum(
        isinstance(outcome, SessionWriteConflictError)
        for outcome in outcomes
    ) == 1
    conflict_index = next(
        index
        for index, outcome in enumerate(outcomes)
        if isinstance(outcome, SessionWriteConflictError)
    )
    conflict_service = services[conflict_index]
    conflict_held_session = (
        session if conflict_index == 0 else stale_second_session
    )
    assert conflict_held_session.student_turn_count == (
        MAX_STUDENT_TURNS_PER_SESSION - 1
    )
    with pytest.raises(SessionResourceLimitError) as raised:
        conflict_service.handle_message(session_id, "刷新后的重试")
    assert raised.value.resource_kind == "message"
    persisted = first_service.session_store.get_session(session_id)
    assert persisted is not None
    assert persisted.payload["student_turn_count"] == (
        MAX_STUDENT_TURNS_PER_SESSION
    )
