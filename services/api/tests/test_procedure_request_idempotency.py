from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import pytest

from app.graph.osce_graph import build_osce_graph
from app.services.osce_session_service import (
    InvalidProcedureRequestError,
    MAX_REQUESTED_PROCEDURES_PER_KIND,
    OsceSessionService,
    ProcedureRequestLimitError,
    UnknownProcedureCodeError,
    _standardize_procedure_request_text,
)
from app.services.osce_session_store import (
    OsceSessionStore,
    SessionWriteConflictError,
)
from app.services.report_store import ReportStore
from app.services.student_profile_store import StudentProfileStore
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_store import TrainingSkillStore


ProcedureKind = Literal["physical_exam", "auxiliary_test"]


@dataclass(frozen=True)
class _ProcedurePath:
    kind: ProcedureKind
    single_method: str
    batch_method: str
    requested_field: str
    code_field: str
    batch_result_field: str
    old_code: str
    new_code: str
    unknown_code: str


PROCEDURE_PATHS = (
    pytest.param(
        _ProcedurePath(
            kind="physical_exam",
            single_method="request_physical_exam",
            batch_method="request_physical_exams",
            requested_field="requested_exams",
            code_field="exam_code",
            batch_result_field="exam_results",
            old_code="abd.palpation.rebound",
            new_code="vital.blood_pressure",
            unknown_code="unknown.exam",
        ),
        id="physical-exam",
    ),
    pytest.param(
        _ProcedurePath(
            kind="auxiliary_test",
            single_method="request_auxiliary_test",
            batch_method="request_auxiliary_tests",
            requested_field="requested_tests",
            code_field="test_code",
            batch_result_field="test_results",
            old_code="lab.cbc",
            new_code="ecg.st_segment",
            unknown_code="unknown.test",
        ),
        id="auxiliary-test",
    ),
)


def test_abdominal_exam_request_does_not_overmatch_abdominal_ct() -> None:
    standardized = _standardize_procedure_request_text(
        "测量体温；进行腹部视诊；检查右下腹 McBurney 点压痛、反跳痛和肌紧张，并检查 Rovsing 征。"
    )

    assert standardized["matched_exam_codes"] == [
        "vital.temperature",
        "abd.inspection",
        "abd.palpation.tenderness",
        "abd.palpation.rebound",
        "abd.palpation.guarding",
        "abd.special.rovsing",
    ]
    assert standardized["matched_test_codes"] == []
    assert standardized["unmatched_requests"] == []


def _canonical_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


class _CountingProcedureGraph:
    def __init__(self) -> None:
        self._graph = build_osce_graph(patient_responder=_canonical_patient_responder)
        self.exam_codes: list[str] = []
        self.test_codes: list[str] = []
        self.call_order: list[tuple[ProcedureKind, str]] = []
        self.fail_kind: ProcedureKind | None = None
        self.fail_on_call: int | None = None

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        exam_code = str(state.get("exam_code") or "")
        test_code = str(state.get("test_code") or "")
        if exam_code:
            self.exam_codes.append(exam_code)
            self.call_order.append(("physical_exam", exam_code))
            if self.fail_kind == "physical_exam" and len(self.exam_codes) == self.fail_on_call:
                raise RuntimeError("injected procedure graph failure")
        if test_code:
            self.test_codes.append(test_code)
            self.call_order.append(("auxiliary_test", test_code))
            if self.fail_kind == "auxiliary_test" and len(self.test_codes) == self.fail_on_call:
                raise RuntimeError("injected procedure graph failure")
        return self._graph.invoke(state)

    def calls_for(self, kind: ProcedureKind) -> list[str]:
        return list(self.exam_codes if kind == "physical_exam" else self.test_codes)


@dataclass(frozen=True)
class _SessionSnapshot:
    in_memory: dict[str, Any]
    persisted: dict[str, object]
    revision: int
    events: list[dict[str, Any]]


def _build_service(tmp_path: Path, graph: object) -> OsceSessionService:
    return OsceSessionService(
        report_store=ReportStore(tmp_path / "reports.sqlite3"),
        training_event_store=TrainingEventStore(tmp_path / "training_events.sqlite3"),
        training_skill_store=TrainingSkillStore(tmp_path / "training_skills.sqlite3"),
        training_skill_candidate_store=TrainingSkillCandidateStore(
            tmp_path / "training_skill_candidates.sqlite3"
        ),
        session_store=OsceSessionStore(tmp_path / "osce_sessions.sqlite3"),
        student_profile_store=StudentProfileStore(tmp_path / "student_profiles.sqlite3"),
        graph=graph,
    )


@pytest.fixture
def procedure_service(tmp_path: Path) -> tuple[OsceSessionService, _CountingProcedureGraph]:
    graph = _CountingProcedureGraph()
    return _build_service(tmp_path, graph), graph


def _create_session(service: OsceSessionService) -> str:
    return str(service.create_session("appendicitis_001", "student-a")["session_id"])


def _session_snapshot(service: OsceSessionService, session_id: str) -> _SessionSnapshot:
    session = service._get_session(session_id)
    stored = service.session_store.get_session(session_id)
    assert session is not None
    assert stored is not None
    return _SessionSnapshot(
        in_memory=asdict(session),
        persisted=deepcopy(stored.payload),
        revision=stored.revision,
        events=deepcopy(service.training_event_store.list_session_events(session_id)),
    )


def _request_single(
    service: OsceSessionService,
    path: _ProcedurePath,
    session_id: str,
    code: str,
) -> dict[str, Any]:
    payload = getattr(service, path.single_method)(session_id, code)
    assert payload is not None
    return payload


def _request_batch(
    service: OsceSessionService,
    path: _ProcedurePath,
    session_id: str,
    codes: list[str],
) -> dict[str, Any]:
    payload = getattr(service, path.batch_method)(session_id, codes)
    assert payload is not None
    return payload


@pytest.mark.parametrize("path", PROCEDURE_PATHS)
def test_unknown_single_request_is_rejected_without_side_effects(
    procedure_service: tuple[OsceSessionService, _CountingProcedureGraph],
    path: _ProcedurePath,
) -> None:
    service, graph = procedure_service
    session_id = _create_session(service)
    held_session = service._get_session(session_id)
    assert held_session is not None
    before = _session_snapshot(service, session_id)

    with pytest.raises(UnknownProcedureCodeError):
        getattr(service, path.single_method)(session_id, path.unknown_code)

    assert graph.calls_for(path.kind) == []
    assert asdict(held_session) == before.in_memory
    assert _session_snapshot(service, session_id) == before


@pytest.mark.parametrize("path", PROCEDURE_PATHS)
def test_unknown_batch_item_rejects_the_entire_batch_before_graph_execution(
    procedure_service: tuple[OsceSessionService, _CountingProcedureGraph],
    path: _ProcedurePath,
) -> None:
    service, graph = procedure_service
    session_id = _create_session(service)
    held_session = service._get_session(session_id)
    assert held_session is not None
    before = _session_snapshot(service, session_id)

    with pytest.raises(UnknownProcedureCodeError):
        getattr(service, path.batch_method)(
            session_id,
            [path.old_code, path.unknown_code],
        )

    assert graph.calls_for(path.kind) == []
    assert asdict(held_session) == before.in_memory
    assert _session_snapshot(service, session_id) == before


@pytest.mark.parametrize("path", PROCEDURE_PATHS)
def test_repeated_single_request_is_a_strict_no_op(
    procedure_service: tuple[OsceSessionService, _CountingProcedureGraph],
    path: _ProcedurePath,
) -> None:
    service, graph = procedure_service
    session_id = _create_session(service)
    first_payload = _request_single(service, path, session_id, path.old_code)
    after_first = _session_snapshot(service, session_id)

    repeated_payload = _request_single(service, path, session_id, path.old_code)

    assert repeated_payload[path.code_field] == first_payload[path.code_field]
    assert repeated_payload["result"] == first_payload["result"]
    assert graph.calls_for(path.kind) == [path.old_code]
    assert _session_snapshot(service, session_id) == after_first


@pytest.mark.parametrize("path", PROCEDURE_PATHS)
def test_repeated_batch_request_is_a_strict_no_op(
    procedure_service: tuple[OsceSessionService, _CountingProcedureGraph],
    path: _ProcedurePath,
) -> None:
    service, graph = procedure_service
    session_id = _create_session(service)
    codes = [path.old_code, path.new_code]
    first_payload = _request_batch(service, path, session_id, codes)
    after_first = _session_snapshot(service, session_id)

    repeated_payload = _request_batch(service, path, session_id, codes)

    assert repeated_payload[path.batch_result_field] == first_payload[path.batch_result_field]
    assert graph.calls_for(path.kind) == codes
    assert _session_snapshot(service, session_id) == after_first


@pytest.mark.parametrize("path", PROCEDURE_PATHS)
def test_mixed_batch_executes_only_new_items(
    procedure_service: tuple[OsceSessionService, _CountingProcedureGraph],
    path: _ProcedurePath,
) -> None:
    service, graph = procedure_service
    session_id = _create_session(service)
    _request_single(service, path, session_id, path.old_code)
    before_batch = _session_snapshot(service, session_id)

    payload = _request_batch(
        service,
        path,
        session_id,
        [path.old_code, path.new_code, path.old_code],
    )
    after_batch = _session_snapshot(service, session_id)

    assert [
        item[path.code_field]
        for item in payload[path.batch_result_field]
    ] == [path.old_code, path.new_code]
    assert graph.calls_for(path.kind) == [path.old_code, path.new_code]
    assert after_batch.in_memory[path.requested_field] == [path.old_code, path.new_code]
    assert len(after_batch.in_memory["action_timeline"]) == (
        len(before_batch.in_memory["action_timeline"]) + 1
    )
    assert after_batch.revision == before_batch.revision + 1
    assert len(after_batch.events) > len(before_batch.events)


@pytest.mark.parametrize("path", PROCEDURE_PATHS)
def test_batch_second_graph_failure_rolls_back_memory_and_persistence(
    procedure_service: tuple[OsceSessionService, _CountingProcedureGraph],
    path: _ProcedurePath,
) -> None:
    service, graph = procedure_service
    session_id = _create_session(service)
    held_session = service._get_session(session_id)
    assert held_session is not None
    before = _session_snapshot(service, session_id)
    graph.fail_kind = path.kind
    graph.fail_on_call = 2

    with pytest.raises(RuntimeError, match="injected procedure graph failure"):
        getattr(service, path.batch_method)(
            session_id,
            [path.old_code, path.new_code],
        )

    assert graph.calls_for(path.kind) == [path.old_code, path.new_code]
    assert asdict(held_session) == before.in_memory
    assert _session_snapshot(service, session_id) == before


@pytest.mark.parametrize("path", PROCEDURE_PATHS)
def test_session_write_conflict_does_not_publish_procedure_working_copy(
    procedure_service: tuple[OsceSessionService, _CountingProcedureGraph],
    path: _ProcedurePath,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, graph = procedure_service
    session_id = _create_session(service)
    held_session = service._get_session(session_id)
    assert held_session is not None
    before = _session_snapshot(service, session_id)

    def raise_write_conflict(
        _session: object,
        *,
        expected_revision: int,
        outbox_events: Any = (),
    ) -> Any:
        raise SessionWriteConflictError(
            session_id,
            expected_revision=expected_revision,
            current_revision=expected_revision + 1,
        )

    monkeypatch.setattr(
        service.session_store,
        "update_session_and_get",
        raise_write_conflict,
    )

    with pytest.raises(SessionWriteConflictError):
        getattr(service, path.single_method)(
            session_id,
            path.new_code,
        )

    assert graph.calls_for(path.kind) == [path.new_code]
    assert asdict(held_session) == before.in_memory
    assert session_id not in service._sessions

    stored_after_conflict = service.session_store.get_session(session_id)
    assert stored_after_conflict is not None
    assert stored_after_conflict.revision == before.revision
    assert stored_after_conflict.payload == before.persisted
    assert service.training_event_store.list_session_events(session_id) == before.events


def test_successful_cas_uses_its_atomic_snapshot_when_another_service_writes_next(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_graph = _CountingProcedureGraph()
    second_graph = _CountingProcedureGraph()
    first_service = _build_service(tmp_path, first_graph)
    second_service = _build_service(tmp_path, second_graph)
    session_id = _create_session(first_service)
    before = _session_snapshot(first_service, session_id)
    update_session_and_get = first_service.session_store.update_session_and_get
    interleaved = False

    def update_then_interleave(
        session: Any,
        *,
        expected_revision: int,
        outbox_events: Any = (),
    ) -> Any:
        nonlocal interleaved
        stored_session = update_session_and_get(
            session,
            expected_revision=expected_revision,
            outbox_events=outbox_events,
        )
        if not interleaved:
            interleaved = True
            second_payload = second_service.request_auxiliary_test(
                session_id,
                "lab.cbc",
            )
            assert second_payload is not None
        return stored_session

    monkeypatch.setattr(
        first_service.session_store,
        "update_session_and_get",
        update_then_interleave,
    )

    first_payload = first_service.request_physical_exam(
        session_id,
        "abd.palpation.rebound",
    )

    assert first_payload is not None
    assert first_payload["requested_exams"] == ["abd.palpation.rebound"]
    assert first_payload["requested_tests"] == []
    persisted = first_service.session_store.get_session(session_id)
    assert persisted is not None
    assert persisted.revision == before.revision + 2
    assert persisted.payload["requested_exams"] == ["abd.palpation.rebound"]
    assert persisted.payload["requested_tests"] == ["lab.cbc"]
    refreshed = first_service._get_session(session_id)
    assert refreshed is not None
    assert refreshed.requested_exams == ["abd.palpation.rebound"]
    assert refreshed.requested_tests == ["lab.cbc"]


@pytest.mark.parametrize("path", PROCEDURE_PATHS)
@pytest.mark.parametrize(
    ("request_kind", "invalid_codes"),
    [
        pytest.param("single", [""], id="empty-single"),
        pytest.param("single", ["x" * 65], id="single-code-too-long"),
        pytest.param("batch", ["item"] * 65, id="batch-too-large"),
    ],
)
def test_invalid_procedure_requests_are_rejected_without_side_effects(
    procedure_service: tuple[OsceSessionService, _CountingProcedureGraph],
    path: _ProcedurePath,
    request_kind: str,
    invalid_codes: list[str],
) -> None:
    service, graph = procedure_service
    session_id = _create_session(service)
    held_session = service._get_session(session_id)
    assert held_session is not None
    before = _session_snapshot(service, session_id)

    with pytest.raises(InvalidProcedureRequestError):
        if request_kind == "single":
            getattr(service, path.single_method)(session_id, invalid_codes[0])
        else:
            getattr(service, path.batch_method)(session_id, invalid_codes)

    assert graph.calls_for(path.kind) == []
    assert asdict(held_session) == before.in_memory
    assert _session_snapshot(service, session_id) == before


@pytest.mark.parametrize("path", PROCEDURE_PATHS)
def test_procedure_limit_rejects_new_code_but_keeps_repeated_code_as_no_op(
    procedure_service: tuple[OsceSessionService, _CountingProcedureGraph],
    path: _ProcedurePath,
) -> None:
    service, graph = procedure_service
    session_id = _create_session(service)
    held_session = service._get_session(session_id)
    assert held_session is not None
    existing_codes = [
        path.old_code,
        *[
            f"legacy.{path.kind}.{index}"
            for index in range(MAX_REQUESTED_PROCEDURES_PER_KIND - 1)
        ],
    ]
    setattr(held_session, path.requested_field, existing_codes)
    service._save_session(held_session)
    at_limit = _session_snapshot(service, session_id)

    repeated_payload = _request_single(
        service,
        path,
        session_id,
        path.old_code,
    )

    assert repeated_payload[path.code_field] == path.old_code
    assert graph.calls_for(path.kind) == []
    assert _session_snapshot(service, session_id) == at_limit

    with pytest.raises(ProcedureRequestLimitError):
        getattr(service, path.single_method)(
            session_id,
            path.new_code,
        )

    assert graph.calls_for(path.kind) == []
    assert _session_snapshot(service, session_id) == at_limit


def test_combined_free_text_procedure_failure_rolls_back_both_kinds(
    procedure_service: tuple[OsceSessionService, _CountingProcedureGraph],
) -> None:
    service, graph = procedure_service
    session_id = str(
        service.create_session(
            "appendicitis_001",
            "student-a",
            training_difficulty="advanced",
        )["session_id"]
    )
    held_session = service._get_session(session_id)
    assert held_session is not None
    before = _session_snapshot(service, session_id)
    graph.fail_kind = "auxiliary_test"
    graph.fail_on_call = 1

    with pytest.raises(RuntimeError, match="injected procedure graph failure"):
        service.request_procedure_text(
            session_id,
            "反跳痛和血常规",
        )

    assert graph.call_order == [
        ("physical_exam", "abd.palpation.rebound"),
        ("auxiliary_test", "lab.cbc"),
    ]
    assert asdict(held_session) == before.in_memory
    assert _session_snapshot(service, session_id) == before


def test_combined_free_text_procedure_commits_both_kinds_with_one_cas(
    procedure_service: tuple[OsceSessionService, _CountingProcedureGraph],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, graph = procedure_service
    session_id = str(
        service.create_session(
            "appendicitis_001",
            "student-a",
            training_difficulty="advanced",
        )["session_id"]
    )
    before = _session_snapshot(service, session_id)
    update_session_and_get = service.session_store.update_session_and_get
    expected_revisions: list[int] = []

    def counting_update_session_and_get(
        session: Any,
        *,
        expected_revision: int,
        outbox_events: Any = (),
    ) -> Any:
        expected_revisions.append(expected_revision)
        return update_session_and_get(
            session,
            expected_revision=expected_revision,
            outbox_events=outbox_events,
        )

    monkeypatch.setattr(
        service.session_store,
        "update_session_and_get",
        counting_update_session_and_get,
    )

    payload = service.request_procedure_text(
        session_id,
        "反跳痛和血常规",
    )

    assert payload is not None
    assert graph.call_order == [
        ("physical_exam", "abd.palpation.rebound"),
        ("auxiliary_test", "lab.cbc"),
    ]
    assert expected_revisions == [before.revision]
    after = _session_snapshot(service, session_id)
    assert after.revision == before.revision + 1
    assert after.persisted["requested_exams"] == ["abd.palpation.rebound"]
    assert after.persisted["requested_tests"] == ["lab.cbc"]
    assert payload["requested_exams"] == ["abd.palpation.rebound"]
    assert payload["requested_tests"] == ["lab.cbc"]
    assert payload["standardized_request"]["matched_exam_codes"] == [
        "abd.palpation.rebound"
    ]
    assert payload["standardized_request"]["matched_test_codes"] == ["lab.cbc"]
    event_types = [str(event["event_type"]) for event in after.events]
    assert event_types.count("physical_exams_requested") == 1
    assert event_types.count("auxiliary_tests_requested") == 1
    assert event_types.count("procedure_free_text_requested") == 1
    assert [
        event["event_type"]
        for event in after.events[len(before.events):]
    ] == [
        "physical_exams_requested",
        "agent_decision_traced",
        "auxiliary_tests_requested",
        "agent_decision_traced",
        "procedure_free_text_requested",
    ]
    before_agent_event_count = sum(
        event["event_type"] == "agent_decision_traced"
        for event in before.events
    )
    agent_events = [
        event
        for event in after.events
        if event["event_type"] == "agent_decision_traced"
    ]
    assert len(agent_events) == before_agent_event_count + 2
    before_trace_count = len(before.in_memory["agent_decision_trace"])
    new_traces = after.persisted["agent_decision_trace"][before_trace_count:]
    assert len(new_traces) == 2
    assert [
        event["payload"]["latest_decision"]
        for event in agent_events[-2:]
    ] == new_traces
