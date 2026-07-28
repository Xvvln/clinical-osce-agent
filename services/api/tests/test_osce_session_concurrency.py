from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, BrokenBarrierError, Event, Lock
from typing import Any

import pytest

from app.graph.osce_graph import build_osce_graph
from app.services.osce_session_service import OsceSessionService, SessionClosedError
from app.services.osce_session_store import (
    OsceSessionStore,
    SessionDeletedError,
    SessionWriteConflictError,
)
from app.services.report_store import ReportStore
from app.services.student_profile_store import StudentProfileStore
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_store import TrainingSkillStore


def _canonical_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


class _CoordinatedGraph:
    def __init__(
        self,
        *,
        first_message_entered: Event | None = None,
        second_message_entered: Event | None = None,
        release_first_message: Event | None = None,
        message_barrier: Barrier | None = None,
        diagnosis_entered: Event | None = None,
        release_diagnosis: Event | None = None,
    ) -> None:
        self._graph = build_osce_graph(patient_responder=_canonical_patient_responder)
        self._first_message_entered = first_message_entered
        self._second_message_entered = second_message_entered
        self._release_first_message = release_first_message
        self._message_barrier = message_barrier
        self._diagnosis_entered = diagnosis_entered
        self._release_diagnosis = release_diagnosis
        self._message_call_count = 0
        self._message_call_count_lock = Lock()

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("student_message"):
            with self._message_call_count_lock:
                self._message_call_count += 1
                message_call_number = self._message_call_count
            if message_call_number == 1 and self._first_message_entered is not None:
                self._first_message_entered.set()
                if self._release_first_message is not None:
                    assert self._release_first_message.wait(timeout=5)
            elif message_call_number == 2 and self._second_message_entered is not None:
                self._second_message_entered.set()
            if self._message_barrier is not None:
                try:
                    self._message_barrier.wait(timeout=5)
                except BrokenBarrierError as exc:  # pragma: no cover - assertion aid
                    raise AssertionError("different sessions did not enter the graph concurrently") from exc
        if state.get("submitted_diagnosis"):
            if self._diagnosis_entered is not None:
                self._diagnosis_entered.set()
            if self._release_diagnosis is not None:
                assert self._release_diagnosis.wait(timeout=5)
        return self._graph.invoke(state)


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


def _wait_for_attempts_to_start(start_barrier: Barrier) -> None:
    try:
        start_barrier.wait(timeout=5)
    except BrokenBarrierError as exc:  # pragma: no cover - assertion aid
        raise AssertionError("concurrent session operations did not start") from exc


def test_same_session_messages_are_serialized_without_lost_update(tmp_path: Path) -> None:
    first_message_entered = Event()
    second_message_entered = Event()
    release_first_message = Event()
    service = _build_service(
        tmp_path,
        _CoordinatedGraph(
            first_message_entered=first_message_entered,
            second_message_entered=second_message_entered,
            release_first_message=release_first_message,
        ),
    )
    session_id = str(service.create_session("appendicitis_001", "student-a")["session_id"])
    start_barrier = Barrier(3)
    call_attempted = {
        "什么时候开始疼的？": Event(),
        "疼痛在什么部位？": Event(),
    }

    def send(message: str) -> dict[str, Any] | None:
        _wait_for_attempts_to_start(start_barrier)
        call_attempted[message].set()
        return service.handle_message(session_id, message)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(send, "什么时候开始疼的？")
        second_future = executor.submit(send, "疼痛在什么部位？")
        _wait_for_attempts_to_start(start_barrier)
        assert all(attempt.wait(timeout=5) for attempt in call_attempted.values())
        assert first_message_entered.wait(timeout=5)
        try:
            assert not second_message_entered.wait(timeout=0.3)
        finally:
            release_first_message.set()
        assert first_future.result(timeout=10) is not None
        assert second_future.result(timeout=10) is not None

    persisted = service.session_store.get_session_payload(session_id)
    assert persisted is not None
    student_messages = [
        str(message.get("content"))
        for message in persisted["messages"]
        if message.get("role") == "student"
    ]
    assert len(student_messages) == 2
    assert set(student_messages) == {"什么时候开始疼的？", "疼痛在什么部位？"}
    assert service._session_locks.active_entry_count() == 0


def test_different_sessions_can_enter_graph_concurrently(tmp_path: Path) -> None:
    graph_barrier = Barrier(2)
    service = _build_service(tmp_path, _CoordinatedGraph(message_barrier=graph_barrier))
    first_session_id = str(service.create_session("appendicitis_001", "student-a")["session_id"])
    second_session_id = str(service.create_session("appendicitis_001", "student-b")["session_id"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            service.handle_message,
            first_session_id,
            "什么时候开始疼的？",
        )
        second_future = executor.submit(
            service.handle_message,
            second_session_id,
            "疼痛在什么部位？",
        )
        assert first_future.result(timeout=10) is not None
        assert second_future.result(timeout=10) is not None

    assert service._session_locks.active_entry_count() == 0


def test_request_waiting_behind_submission_is_rejected_as_closed(tmp_path: Path) -> None:
    diagnosis_entered = Event()
    release_diagnosis = Event()
    message_entered = Event()
    service = _build_service(
        tmp_path,
        _CoordinatedGraph(
            first_message_entered=message_entered,
            diagnosis_entered=diagnosis_entered,
            release_diagnosis=release_diagnosis,
        ),
    )
    session_id = str(service.create_session("appendicitis_001", "student-a")["session_id"])
    message_attempted = Event()

    def send_waiting_message() -> dict[str, Any] | None:
        message_attempted.set()
        return service.handle_message(session_id, "旧请求现在才进入服务。")

    with ThreadPoolExecutor(max_workers=2) as executor:
        submit_future = executor.submit(
            service.submit_diagnosis,
            session_id,
            "急性阑尾炎",
            "转移性右下腹痛支持诊断。",
        )
        assert diagnosis_entered.wait(timeout=5)
        message_future: Future[dict[str, Any] | None] = executor.submit(send_waiting_message)
        assert message_attempted.wait(timeout=5)
        try:
            assert not message_entered.wait(timeout=0.3)
        finally:
            release_diagnosis.set()
        assert submit_future.result(timeout=10) is not None
        with pytest.raises(SessionClosedError, match="训练已结束"):
            message_future.result(timeout=10)

    persisted = service.session_store.get_session_payload(session_id)
    assert persisted is not None
    assert persisted["final_submission"] == {
        "diagnosis": "急性阑尾炎",
        "reasoning": "转移性右下腹痛支持诊断。",
    }
    assert service._session_locks.active_entry_count() == 0


def test_submission_waits_for_older_message_and_cannot_be_overwritten(tmp_path: Path) -> None:
    message_entered = Event()
    release_message = Event()
    diagnosis_entered = Event()
    service = _build_service(
        tmp_path,
        _CoordinatedGraph(
            first_message_entered=message_entered,
            release_first_message=release_message,
            diagnosis_entered=diagnosis_entered,
        ),
    )
    session_id = str(service.create_session("appendicitis_001", "student-a")["session_id"])
    submit_attempted = Event()

    def submit_waiting_diagnosis() -> dict[str, Any] | None:
        submit_attempted.set()
        return service.submit_diagnosis(
            session_id,
            "急性阑尾炎",
            "转移性右下腹痛支持诊断。",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        message_future = executor.submit(
            service.handle_message,
            session_id,
            "什么时候开始疼的？",
        )
        assert message_entered.wait(timeout=5)
        submit_future = executor.submit(submit_waiting_diagnosis)
        assert submit_attempted.wait(timeout=5)
        try:
            assert not diagnosis_entered.wait(timeout=0.3)
        finally:
            release_message.set()
        assert message_future.result(timeout=10) is not None
        assert submit_future.result(timeout=10) is not None

    persisted = service.session_store.get_session_payload(session_id)
    assert persisted is not None
    assert persisted["final_submission"] == {
        "diagnosis": "急性阑尾炎",
        "reasoning": "转移性右下腹痛支持诊断。",
    }
    assert any(
        message.get("role") == "student" and message.get("content") == "什么时候开始疼的？"
        for message in persisted["messages"]
    )
    assert service._session_locks.active_entry_count() == 0


def test_delete_waits_for_active_session_write_and_cannot_be_resurrected(tmp_path: Path) -> None:
    message_entered = Event()
    release_message = Event()
    service = _build_service(
        tmp_path,
        _CoordinatedGraph(
            first_message_entered=message_entered,
            release_first_message=release_message,
        ),
    )
    session_id = str(service.create_session("appendicitis_001", "student-a")["session_id"])
    delete_attempted = Event()

    def delete_waiting_session() -> bool:
        delete_attempted.set()
        return service.delete_session(session_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        message_future = executor.submit(
            service.handle_message,
            session_id,
            "什么时候开始疼的？",
        )
        assert message_entered.wait(timeout=5)
        delete_future = executor.submit(delete_waiting_session)
        assert delete_attempted.wait(timeout=5)
        try:
            assert not delete_future.done()
        finally:
            release_message.set()
        assert message_future.result(timeout=10) is not None
        assert delete_future.result(timeout=10) is True

    assert service.get_session(session_id) is None
    assert service.session_store.get_session_payload(session_id) is None
    assert service._session_locks.active_entry_count() == 0


def test_missing_session_reads_do_not_grow_lock_registry(tmp_path: Path) -> None:
    service = _build_service(tmp_path, _CoordinatedGraph())

    for index in range(100):
        assert service.get_session(f"missing-{index}") is None

    assert service._session_locks.active_entry_count() == 0


def test_second_service_refreshes_a_stale_cached_object_in_place(tmp_path: Path) -> None:
    first_service = _build_service(tmp_path, _CoordinatedGraph())
    second_service = _build_service(tmp_path, _CoordinatedGraph())
    session_id = str(first_service.create_session("appendicitis_001", "student-a")["session_id"])
    held_session = second_service._get_session(session_id)
    assert held_session is not None

    first_service.record_hypothesis(session_id, "急性阑尾炎")
    refreshed_session = second_service._get_session(session_id)

    assert refreshed_session is held_session
    assert held_session.student_hypotheses == ["急性阑尾炎"]


def test_cross_service_stale_write_raises_conflict_without_lost_update(tmp_path: Path) -> None:
    message_entered = Event()
    release_message = Event()
    first_service = _build_service(tmp_path, _CoordinatedGraph())
    second_service = _build_service(
        tmp_path,
        _CoordinatedGraph(
            first_message_entered=message_entered,
            release_first_message=release_message,
        ),
    )
    session_id = str(first_service.create_session("appendicitis_001", "student-a")["session_id"])
    initial_record = first_service.session_store.get_session(session_id)
    assert initial_record is not None

    with ThreadPoolExecutor(max_workers=1) as executor:
        stale_write_future = executor.submit(
            second_service.handle_message,
            session_id,
            "什么时候开始疼的？",
        )
        assert message_entered.wait(timeout=5)
        first_service.record_hypothesis(session_id, "急性阑尾炎")
        release_message.set()
        with pytest.raises(SessionWriteConflictError):
            stale_write_future.result(timeout=10)

    assert session_id not in second_service._sessions
    persisted_after_conflict = first_service.session_store.get_session_payload(session_id)
    assert persisted_after_conflict is not None
    assert persisted_after_conflict["student_hypotheses"] == ["急性阑尾炎"]
    assert not any(
        message.get("role") == "student"
        and message.get("content") == "什么时候开始疼的？"
        for message in persisted_after_conflict["messages"]
    )

    retried = second_service.handle_message(session_id, "什么时候开始疼的？")
    assert retried is not None
    persisted_after_retry = first_service.session_store.get_session(session_id)
    assert persisted_after_retry is not None
    assert persisted_after_retry.revision == initial_record.revision + 2
    assert persisted_after_retry.payload["student_hypotheses"] == ["急性阑尾炎"]
    assert any(
        message.get("role") == "student"
        and message.get("content") == "什么时候开始疼的？"
        for message in persisted_after_retry.payload["messages"]
    )


def test_cross_service_delete_tombstone_blocks_in_flight_stale_write(tmp_path: Path) -> None:
    message_entered = Event()
    release_message = Event()
    first_service = _build_service(tmp_path, _CoordinatedGraph())
    second_service = _build_service(
        tmp_path,
        _CoordinatedGraph(
            first_message_entered=message_entered,
            release_first_message=release_message,
        ),
    )
    session_id = str(first_service.create_session("appendicitis_001", "student-a")["session_id"])

    with ThreadPoolExecutor(max_workers=1) as executor:
        stale_write_future = executor.submit(
            second_service.handle_message,
            session_id,
            "什么时候开始疼的？",
        )
        assert message_entered.wait(timeout=5)
        assert first_service.delete_session(session_id) is True
        release_message.set()
        with pytest.raises(SessionDeletedError):
            stale_write_future.result(timeout=10)

    assert session_id not in second_service._sessions
    assert first_service.session_store.get_session(session_id) is None
    assert second_service.get_session(session_id) is None
