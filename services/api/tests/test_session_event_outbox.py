from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event

import pytest

from app.graph.osce_graph import build_osce_graph
from app.services.osce_session_service import OsceSession, OsceSessionService
from app.services.osce_session_store import (
    OsceSessionStore,
    SessionCreatePreparationConflictError,
    SessionOutboxEvent,
    SessionOutboxItem,
    SessionWriteConflictError,
)
from app.services.report_store import ReportStore
from app.services.student_profile_store import StudentProfileStore
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_store import TrainingSkillStore


def _session(session_id: str = "session-outbox") -> OsceSession:
    return OsceSession(
        session_id=session_id,
        student_id="student-outbox",
        case_id="appendicitis_001",
        stage="history",
    )


def _event(event_type: str, **payload: object) -> SessionOutboxEvent:
    return SessionOutboxEvent(event_type=event_type, payload=payload)


def _canonical_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


def _build_service(tmp_path: Path) -> OsceSessionService:
    return OsceSessionService(
        report_store=ReportStore(tmp_path / "reports.sqlite3"),
        training_event_store=TrainingEventStore(
            tmp_path / "training_events.sqlite3"
        ),
        training_skill_store=TrainingSkillStore(
            tmp_path / "training_skills.sqlite3"
        ),
        training_skill_candidate_store=TrainingSkillCandidateStore(
            tmp_path / "training_skill_candidates.sqlite3"
        ),
        session_store=OsceSessionStore(tmp_path / "osce_sessions.sqlite3"),
        student_profile_store=StudentProfileStore(
            tmp_path / "student_profiles.sqlite3"
        ),
        graph=build_osce_graph(
            patient_responder=_canonical_patient_responder
        ),
    )


def _install_failing_outbox_insert_trigger(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_session_event_outbox_insert
            BEFORE INSERT ON osce_session_event_outbox
            BEGIN
                SELECT RAISE(ABORT, 'forced session outbox failure');
            END
            """
        )


def _session_events(
    service: OsceSessionService,
    session_id: str,
    event_type: str,
) -> list[dict[str, object]]:
    return [
        event
        for event in service.training_event_store.list_session_events(
            session_id
        )
        if event["event_type"] == event_type
    ]


def test_create_and_update_persist_state_and_outbox_in_fifo_order(
    tmp_path: Path,
) -> None:
    store = OsceSessionStore(tmp_path / "sessions.sqlite3")
    session = _session()

    assert store.create_session(
        session,
        outbox_events=[
            _event("session_created", stage="history"),
            _event("agent_decision_traced", decision="observe"),
        ],
    ) == 1

    updated_session = deepcopy(session)
    updated_session.stage = "physical_exam"
    stored = store.update_session_and_get(
        updated_session,
        expected_revision=1,
        outbox_events=[
            _event("stage_changed", stage="physical_exam"),
            _event("agent_decision_traced", decision="examine"),
        ],
    )

    assert stored.revision == 2
    assert stored.payload["stage"] == "physical_exam"
    pending = store.list_pending_event_outbox()
    assert all(isinstance(item, SessionOutboxItem) for item in pending)
    assert [item.event_type for item in pending] == [
        "session_created",
        "agent_decision_traced",
        "stage_changed",
        "agent_decision_traced",
    ]
    assert [item.session_revision for item in pending] == [1, 1, 2, 2]
    assert [item.event_index for item in pending] == [0, 1, 0, 1]
    assert [item.event_key for item in pending] == [
        "session:session-outbox:revision:1:event:0:session_created",
        "session:session-outbox:revision:1:event:1:agent_decision_traced",
        "session:session-outbox:revision:2:event:0:stage_changed",
        "session:session-outbox:revision:2:event:1:agent_decision_traced",
    ]
    assert pending[0].payload == {"stage": "history"}
    assert pending[2].payload == {"stage": "physical_exam"}

    assert store.acknowledge_event_outbox(pending[0].event_key) is True
    assert store.acknowledge_event_outbox(pending[0].event_key) is False
    assert [
        item.event_key
        for item in store.list_pending_event_outbox(limit=2)
    ] == [pending[1].event_key, pending[2].event_key]


def test_cas_loser_does_not_enqueue_outbox_events(tmp_path: Path) -> None:
    store = OsceSessionStore(tmp_path / "sessions.sqlite3")
    session = _session("session-cas")
    store.create_session(session)
    winning_update = deepcopy(session)
    winning_update.stage = "physical_exam"
    losing_update = deepcopy(session)
    losing_update.stage = "auxiliary_exam"

    store.update_session_and_get(
        winning_update,
        expected_revision=1,
        outbox_events=[_event("winner_event", stage="physical_exam")],
    )
    with pytest.raises(SessionWriteConflictError):
        store.update_session_and_get(
            losing_update,
            expected_revision=1,
            outbox_events=[_event("loser_event", stage="auxiliary_exam")],
        )

    stored = store.get_session(session.session_id)
    assert stored is not None
    assert stored.revision == 2
    assert stored.payload["stage"] == "physical_exam"
    assert [
        item.event_type
        for item in store.list_pending_event_outbox()
    ] == ["winner_event"]


def test_create_rolls_back_when_outbox_insert_fails(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite3"
    store = OsceSessionStore(database_path)
    assert store.list_pending_event_outbox() == []
    _install_failing_outbox_insert_trigger(database_path)
    session = _session("session-create-rollback")

    with pytest.raises(sqlite3.IntegrityError, match="forced session outbox"):
        store.create_session(
            session,
            outbox_events=[_event("session_created", stage="history")],
        )

    assert store.get_session(session.session_id) is None
    assert store.list_pending_event_outbox() == []


def test_create_rejects_stale_deleted_skill_ledger_preparation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite3"
    store = OsceSessionStore(database_path)
    session = _session("session-create-preparation")
    prepared = store.prepare_session_for_create(session)
    source_session_id = "deleted-source"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO osce_deleted_skill_sources (
                source_session_id,
                owner_user_id,
                personal_skill_id,
                personal_candidate_id,
                source_report_id,
                affected_global_skill_ids_json,
                affected_session_ids_json,
                deleted_at
            )
            VALUES (?, ?, ?, ?, ?, '[]', '[]', ?)
            """,
            (
                source_session_id,
                session.student_id,
                f"skill_personal_{source_session_id}",
                f"personal_skill_candidate_{source_session_id}",
                f"{source_session_id}_report",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    with pytest.raises(SessionCreatePreparationConflictError):
        store.create_session(
            session,
            outbox_events=[_event("session_created")],
            expected_deleted_skill_sources_version=(
                prepared.deleted_skill_sources_version
            ),
        )

    assert store.get_session(session.session_id) is None
    assert store.list_pending_event_outbox() == []


def test_update_rolls_back_when_outbox_insert_fails(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite3"
    store = OsceSessionStore(database_path)
    session = _session("session-update-rollback")
    store.create_session(session)
    before = store.get_session(session.session_id)
    _install_failing_outbox_insert_trigger(database_path)
    updated_session = deepcopy(session)
    updated_session.stage = "physical_exam"

    with pytest.raises(sqlite3.IntegrityError, match="forced session outbox"):
        store.update_session_and_get(
            updated_session,
            expected_revision=1,
            outbox_events=[_event("stage_changed", stage="physical_exam")],
        )

    assert store.get_session(session.session_id) == before
    assert store.list_pending_event_outbox() == []


def test_event_store_failure_does_not_rollback_session_and_recovers_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(tmp_path)
    session_id = str(
        service.create_session(
            "appendicitis_001",
            "student-event-failure",
        )["session_id"]
    )
    assert service.session_store.list_pending_event_outbox() == []
    original_append_event = service.training_event_store.append_event

    def unavailable_append_event(*_: object, **__: object) -> bool:
        raise RuntimeError("event database unavailable")

    def unavailable_event_count(*_: object, **__: object) -> int:
        raise RuntimeError("event database unavailable")

    monkeypatch.setattr(
        service.training_event_store,
        "append_event",
        unavailable_append_event,
    )
    monkeypatch.setattr(
        service.training_event_store,
        "count_session_events",
        unavailable_event_count,
    )
    response = service.record_hypothesis(session_id, "首先考虑急性阑尾炎")

    assert response is not None
    persisted = service.session_store.get_session_payload(session_id)
    assert persisted is not None
    assert persisted["student_hypotheses"] == ["首先考虑急性阑尾炎"]
    pending = service.session_store.list_pending_event_outbox()
    assert [item.event_type for item in pending] == [
        "hypothesis_recorded",
        "agent_decision_traced",
    ]

    monkeypatch.setattr(
        service.training_event_store,
        "append_event",
        original_append_event,
    )
    assert service.drain_session_event_outbox() == 2
    assert service.session_store.list_pending_event_outbox() == []
    assert len(_session_events(service, session_id, "hypothesis_recorded")) == 1
    assert len(_session_events(service, session_id, "agent_decision_traced")) == 2
    assert service.drain_session_event_outbox() == 0


def test_locked_event_database_only_adds_a_short_best_effort_delay(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path)
    session_id = str(
        service.create_session(
            "appendicitis_001",
            "student-event-lock",
        )["session_id"]
    )
    with sqlite3.connect(
        service.training_event_store.database_path,
        timeout=0,
    ) as blocking_connection:
        blocking_connection.execute("BEGIN EXCLUSIVE")
        started_at = time.monotonic()
        response = service.record_hypothesis(
            session_id,
            "事件库锁定期间仍保存假设",
        )
        elapsed_seconds = time.monotonic() - started_at

    assert response is not None
    assert elapsed_seconds < 2
    assert [
        item.event_type
        for item in service.session_store.list_pending_event_outbox(
            session_id=session_id
        )
    ] == ["hypothesis_recorded", "agent_decision_traced"]
    assert service.drain_session_event_outbox(session_id=session_id) == 2


def test_replay_after_event_insert_before_ack_is_exactly_once(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path)
    session_id = str(
        service.create_session(
            "appendicitis_001",
            "student-ack-failure",
        )["session_id"]
    )
    assert service.session_store.list_pending_event_outbox() == []
    with sqlite3.connect(service.session_store.database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_session_event_outbox_delete
            BEFORE DELETE ON osce_session_event_outbox
            BEGIN
                SELECT RAISE(ABORT, 'crash before outbox acknowledgement');
            END
            """
        )
    response = service.record_hypothesis(session_id, "考虑化脓性阑尾炎")

    assert response is not None
    assert [
        item.event_type
        for item in service.session_store.list_pending_event_outbox()
    ] == ["hypothesis_recorded", "agent_decision_traced"]
    assert len(_session_events(service, session_id, "hypothesis_recorded")) == 1
    assert len(_session_events(service, session_id, "agent_decision_traced")) == 1

    with sqlite3.connect(service.session_store.database_path) as connection:
        connection.execute("DROP TRIGGER fail_session_event_outbox_delete")
    assert service.drain_session_event_outbox() == 2
    assert service.session_store.list_pending_event_outbox() == []
    assert len(_session_events(service, session_id, "hypothesis_recorded")) == 1
    assert len(_session_events(service, session_id, "agent_decision_traced")) == 2
    assert service.drain_session_event_outbox() == 0


def test_session_creation_survives_event_store_failure_and_recovers_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(tmp_path)
    original_append_event = service.training_event_store.append_event

    def unavailable_append_event(*_: object, **__: object) -> bool:
        raise RuntimeError("event database unavailable")

    monkeypatch.setattr(
        service.training_event_store,
        "append_event",
        unavailable_append_event,
    )
    response = service.create_session(
        "appendicitis_001",
        "student-create-event-failure",
    )

    session_id = str(response["session_id"])
    assert service.session_store.get_session(session_id) is not None
    assert [
        item.event_type
        for item in service.session_store.list_pending_event_outbox(
            session_id=session_id
        )
    ] == ["session_created", "agent_decision_traced"]

    monkeypatch.setattr(
        service.training_event_store,
        "append_event",
        original_append_event,
    )
    assert service.drain_session_event_outbox(session_id=session_id) == 2
    events = service.training_event_store.list_session_events(session_id)
    assert [event["event_type"] for event in events] == [
        "session_created",
        "agent_decision_traced",
    ]
    assert all(event["event_key"] for event in events)


def test_create_accepts_a_legitimate_post_commit_revision_advance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(tmp_path)
    original_create_session = service.session_store.create_session

    def create_then_scrub(
        session: OsceSession,
        *,
        outbox_events: (
            tuple[SessionOutboxEvent, ...] | list[SessionOutboxEvent]
        ) = (),
        expected_deleted_skill_sources_version: int | None = None,
    ) -> int:
        revision = original_create_session(
            session,
            outbox_events=outbox_events,
            expected_deleted_skill_sources_version=(
                expected_deleted_skill_sources_version
            ),
        )
        stored = service.session_store.get_session(session.session_id)
        assert stored is not None
        service.session_store.update_session_and_get(
            OsceSession(**stored.payload),
            expected_revision=stored.revision,
        )
        return revision

    monkeypatch.setattr(
        service.session_store,
        "create_session",
        create_then_scrub,
    )

    response = service.create_session(
        "appendicitis_001",
        "student-post-create-race",
    )

    stored = service.session_store.get_session(str(response["session_id"]))
    assert stored is not None
    assert stored.revision == 2


def test_create_uses_one_skill_snapshot_for_session_and_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(tmp_path)
    first_candidate = {
        "candidate_id": "candidate-first-snapshot",
        "trigger_item_id": "ht_migration",
        "trigger_item_ids": ["ht_migration"],
        "case_ids": ["appendicitis_001"],
        "title": "首次快照技能",
        "description": "用于验证创建快照一致性。",
        "suggested_strategy": "按首次快照组织追问。",
        "source_report_count": 1,
        "support_count": 1,
        "review": {"status": "approved", "regression_passed": True},
        "approval_agent_review": {
            "agent_id": "skill_auto_approval_agent",
            "decision": "ready_for_human_review",
            "quality_review": {"passed": True, "failed_checks": []},
            "role_policy": {"passed": True},
        },
    }
    second_candidate = {
        "candidate_id": "candidate-second-snapshot",
        "trigger_item_id": "ht_onset",
        "trigger_item_ids": ["ht_onset"],
        "case_ids": ["appendicitis_001"],
        "title": "第二次读取技能",
        "description": "用于模拟并发启停后的技能列表。",
        "suggested_strategy": "按第二次读取组织追问。",
        "source_report_count": 1,
        "support_count": 1,
        "review": {"status": "approved", "regression_passed": True},
        "approval_agent_review": {
            "agent_id": "skill_auto_approval_agent",
            "decision": "ready_for_human_review",
            "quality_review": {"passed": True, "failed_checks": []},
            "role_policy": {"passed": True},
        },
    }
    assert service.training_skill_store.enable_candidate(first_candidate)
    assert service.training_skill_store.enable_candidate(second_candidate)
    first_skill = service.training_skill_store.get_skill(
        "skill_ht_migration"
    )
    second_skill = service.training_skill_store.get_skill("skill_ht_onset")
    assert first_skill is not None
    assert second_skill is not None
    reads = 0

    def changing_skill_snapshot() -> list[dict[str, object]]:
        nonlocal reads
        reads += 1
        return [first_skill] if reads == 1 else [second_skill]

    monkeypatch.setattr(
        service.training_skill_store,
        "list_enabled_skills",
        changing_skill_snapshot,
    )

    response = service.create_session(
        "appendicitis_001",
        "student-skill-snapshot",
    )

    session_id = str(response["session_id"])
    stored = service.session_store.get_session(session_id)
    assert stored is not None
    assert reads == 1
    assert [
        skill["skill_id"]
        for skill in stored.payload["active_skill_context"][
            "selected_skills"
        ]
    ] == ["skill_ht_migration"]
    assert [
        event["payload"]["skill_id"]
        for event in _session_events(
            service,
            session_id,
            "training_skill_applied",
        )
    ] == ["skill_ht_migration"]


@pytest.mark.parametrize(
    ("operation", "expected_event_types"),
    [
        ("message", ["history_message", "agent_decision_traced"]),
        ("physical_exam", ["physical_exam_requested", "agent_decision_traced"]),
        ("auxiliary_test", ["auxiliary_test_requested", "agent_decision_traced"]),
        ("hypothesis", ["hypothesis_recorded", "agent_decision_traced"]),
        ("hint", ["hint_requested", "agent_decision_traced"]),
        ("diagnosis", ["diagnosis_submitted", "agent_decision_traced"]),
        (
            "procedure_text",
            [
                "physical_exams_requested",
                "agent_decision_traced",
                "auxiliary_tests_requested",
                "agent_decision_traced",
                "procedure_free_text_requested",
            ],
        ),
    ],
)
def test_state_changing_operations_commit_ordered_outbox_when_delivery_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    expected_event_types: list[str],
) -> None:
    service = _build_service(tmp_path)
    session_id = str(
        service.create_session(
            "appendicitis_001",
            f"student-{operation}",
            training_difficulty=(
                "advanced" if operation == "procedure_text" else "beginner"
            ),
        )["session_id"]
    )
    original_append_event = service.training_event_store.append_event

    def unavailable_append_event(*_: object, **__: object) -> bool:
        raise RuntimeError("event database unavailable")

    def unavailable_event_count(*_: object, **__: object) -> int:
        raise RuntimeError("event database unavailable")

    monkeypatch.setattr(
        service.training_event_store,
        "append_event",
        unavailable_append_event,
    )
    monkeypatch.setattr(
        service.training_event_store,
        "count_session_events",
        unavailable_event_count,
    )
    if operation == "message":
        response = service.handle_message(session_id, "什么时候开始疼的？")
    elif operation == "physical_exam":
        response = service.request_physical_exam(
            session_id,
            "abd.palpation.rebound",
        )
    elif operation == "auxiliary_test":
        response = service.request_auxiliary_test(session_id, "lab.cbc")
    elif operation == "hypothesis":
        response = service.record_hypothesis(session_id, "急性阑尾炎")
    elif operation == "hint":
        response = service.request_hint(session_id)
    elif operation == "diagnosis":
        response = service.submit_diagnosis(
            session_id,
            "急性阑尾炎",
            "转移性右下腹痛支持诊断。",
        )
    else:
        response = service.request_procedure_text(
            session_id,
            "反跳痛和血常规",
        )

    assert response is not None
    assert [
        item.event_type
        for item in service.session_store.list_pending_event_outbox(
            session_id=session_id
        )
    ] == expected_event_types
    monkeypatch.setattr(
        service.training_event_store,
        "append_event",
        original_append_event,
    )
    assert service.drain_session_event_outbox(
        session_id=session_id
    ) == len(expected_event_types)
    assert [
        event["event_type"]
        for event in service.training_event_store.list_session_events(
            session_id
        )
    ][-len(expected_event_types):] == expected_event_types


def test_delivery_stops_at_first_failure_without_skipping_later_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(tmp_path)
    session = _session("session-strict-fifo")
    service.session_store.create_session(
        session,
        outbox_events=[
            _event("first"),
            _event("second"),
            _event("third"),
        ],
    )
    original_append_event = service.training_event_store.append_event
    attempted: list[str] = []

    def fail_second_event(*args: object, **kwargs: object) -> bool:
        event_type = str(kwargs["event_type"])
        attempted.append(event_type)
        if event_type == "second":
            raise RuntimeError("second event failed")
        return original_append_event(*args, **kwargs)

    monkeypatch.setattr(
        service.training_event_store,
        "append_event",
        fail_second_event,
    )

    assert service.drain_session_event_outbox(
        session_id=session.session_id
    ) == 1
    assert attempted == ["first", "second"]
    assert [
        item.event_type
        for item in service.session_store.list_pending_event_outbox(
            session_id=session.session_id
        )
    ] == ["second", "third"]

    monkeypatch.setattr(
        service.training_event_store,
        "append_event",
        original_append_event,
    )
    assert service.drain_session_event_outbox(
        session_id=session.session_id
    ) == 2
    assert [
        event["event_type"]
        for event in service.training_event_store.list_session_events(
            session.session_id
        )
    ] == ["first", "second", "third"]


def test_repeated_free_text_noop_survives_event_store_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(tmp_path)
    session_id = str(
        service.create_session(
            "appendicitis_001",
            "student-repeated-free-text",
            training_difficulty="advanced",
        )["session_id"]
    )
    first_response = service.request_procedure_text(
        session_id,
        "反跳痛和血常规",
    )
    assert first_response is not None
    before = service.session_store.get_session(session_id)
    assert before is not None

    def unavailable_append_event(*_: object, **__: object) -> bool:
        raise RuntimeError("event database unavailable")

    monkeypatch.setattr(
        service.training_event_store,
        "append_event",
        unavailable_append_event,
    )
    repeated_response = service.request_procedure_text(
        session_id,
        "反跳痛和血常规",
    )

    assert repeated_response is not None
    assert service.session_store.get_session(session_id) == before
    assert service.session_store.list_pending_event_outbox(
        session_id=session_id
    ) == []


def test_begin_deletion_purges_pending_session_outbox(tmp_path: Path) -> None:
    store = OsceSessionStore(tmp_path / "sessions.sqlite3")
    session = _session("session-delete-outbox")
    store.create_session(
        session,
        outbox_events=[_event("session_created")],
    )

    deletion = store.begin_session_deletion(
        session.session_id,
        session.student_id,
    )

    assert deletion is not None
    assert store.list_pending_event_outbox() == []
    assert store.get_session(session.session_id) is None


def test_delivery_transaction_serializes_with_session_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(tmp_path)
    student_id = "student-delivery-delete-race"
    session_id = str(
        service.create_session("appendicitis_001", student_id)["session_id"]
    )
    stored = service.session_store.get_session(session_id)
    assert stored is not None
    service.session_store.update_session_and_get(
        OsceSession(**stored.payload),
        expected_revision=stored.revision,
        outbox_events=[_event("race_probe")],
    )
    original_append_event = service.training_event_store.append_event
    delivery_entered = Event()
    release_delivery = Event()
    deletion_finished = Event()

    def paused_append_event(*args: object, **kwargs: object) -> bool:
        delivery_entered.set()
        assert release_delivery.wait(timeout=5)
        return original_append_event(*args, **kwargs)

    monkeypatch.setattr(
        service.training_event_store,
        "append_event",
        paused_append_event,
    )

    def delete() -> bool:
        try:
            return service.delete_session(
                session_id,
                expected_student_id=student_id,
            )
        finally:
            deletion_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        drain_future = executor.submit(
            service.drain_session_event_outbox,
            session_id=session_id,
        )
        assert delivery_entered.wait(timeout=5)
        delete_future = executor.submit(delete)
        try:
            assert not deletion_finished.wait(timeout=0.3)
        finally:
            release_delivery.set()
        assert drain_future.result(timeout=10) == 1
        assert delete_future.result(timeout=10) is True

    assert service.session_store.is_session_deleted(session_id) is True
    assert service.session_store.list_pending_event_outbox() == []
    assert service.training_event_store.list_session_events(session_id) == []
