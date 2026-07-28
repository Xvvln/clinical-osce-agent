import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.graph.osce_graph import build_osce_graph
from app.main import _app_lifespan
from app.services.osce_session_service import (
    OsceSession,
    OsceSessionService,
    SessionDeletionConflictError,
)
from app.services.osce_session_store import OsceSessionStore, SessionNotFoundError
from app.services.report_store import (
    ReportDeletedError,
    ReportOutboxEvent,
    ReportStore,
)
from app.services.student_profile_store import StudentProfileStore
from app.services.training_event_store import (
    TrainingEventStore,
    TrainingEventStreamDeletedError,
)
from app.services.training_skill_candidate_store import (
    TrainingSkillCandidateDeletedError,
    TrainingSkillCandidateStore,
)
from app.services.training_skill_store import (
    TrainingSkillDeletedError,
    TrainingSkillStore,
)


def _canonical_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


def _build_service(tmp_path: Path) -> OsceSessionService:
    return OsceSessionService(
        report_store=ReportStore(tmp_path / "reports.sqlite3"),
        training_event_store=TrainingEventStore(tmp_path / "training_events.sqlite3"),
        training_skill_store=TrainingSkillStore(tmp_path / "training_skills.sqlite3"),
        training_skill_candidate_store=TrainingSkillCandidateStore(
            tmp_path / "training_skill_candidates.sqlite3"
        ),
        session_store=OsceSessionStore(tmp_path / "osce_sessions.sqlite3"),
        student_profile_store=StudentProfileStore(tmp_path / "student_profiles.sqlite3"),
        graph=build_osce_graph(patient_responder=_canonical_patient_responder),
    )


def _personal_candidate(*, session_id: str, student_id: str) -> dict[str, object]:
    candidate_id = f"personal_skill_candidate_{session_id}"
    return {
        "candidate_id": candidate_id,
        "trigger_item_id": f"personal_{session_id}",
        "trigger_item_ids": ["reasoning_core"],
        "case_ids": ["appendicitis_001"],
        "stage_scope": ["case_intro"],
        "title": "个人复盘训练 Skill",
        "description": "根据本次训练生成的个人复盘建议。",
        "suggested_strategy": "提醒学生复盘证据链，不透露标准答案。",
        "scope": "personal",
        "owner_student_id": student_id,
        "source_session_id": session_id,
        "source_session_ids": [session_id],
        "source_report_ids": [f"{session_id}_report"],
        "source_report_count": 1,
        "support_count": 1,
        "related_recommendations": [],
        "review": {
            "candidate_id": candidate_id,
            "status": "approved",
            "regression_passed": True,
        },
    }


def _global_candidate() -> dict[str, object]:
    return {
        "candidate_id": "global_skill_candidate_keep",
        "trigger_item_id": "global_keep",
        "trigger_item_ids": ["reasoning_core"],
        "case_ids": ["appendicitis_001"],
        "stage_scope": ["case_intro"],
        "title": "全局训练 Skill",
        "description": "应在删除个人会话后继续保留。",
        "suggested_strategy": "提醒学生复盘证据链。",
        "scope": "global",
        "source_report_count": 2,
        "support_count": 2,
        "related_recommendations": [],
        "review": {
            "candidate_id": "global_skill_candidate_keep",
            "status": "approved",
            "regression_passed": True,
        },
    }


def _save_candidate_and_skill(
    service: OsceSessionService,
    candidate: dict[str, object],
) -> None:
    review = dict(candidate["review"])
    service.training_skill_candidate_store.save_candidate(candidate, review)
    assert service.training_skill_store.enable_candidate(candidate) is True


def _seed_report_with_outbox(
    service: OsceSessionService,
    *,
    session_id: str,
    student_id: str,
) -> dict[str, object]:
    report = {
        "report_id": f"{session_id}_report",
        "session_id": session_id,
        "case_id": "appendicitis_001",
        "student_id": student_id,
        "total_score": 80,
        "missed_items": [],
    }
    service.report_store.create_base_report(
        report,
        enrichment_required=False,
        outbox_event=ReportOutboxEvent(
            case_id="appendicitis_001",
            student_id=student_id,
            event_type="report_generated",
            payload={"report": report},
        ),
    )
    return report


def _make_tombstone_ownerless(
    service: OsceSessionService,
    session_id: str,
) -> None:
    assert service.session_store.delete_session(session_id) is True
    with sqlite3.connect(service.session_store.database_path) as connection:
        connection.execute(
            """
            UPDATE osce_session_tombstones
            SET user_id = '', case_id = '', cleanup_status = 'completed',
                cleanup_completed_at = deleted_at
            WHERE session_id = ?
            """,
            (session_id,),
        )


def test_delete_session_cascades_all_personal_artifacts_and_preserves_unrelated_data(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path)
    student_id = "student-delete"
    other_student_id = "student-other"
    target_id = str(
        service.create_session("appendicitis_001", student_id)["session_id"]
    )
    kept_session_id = str(
        service.create_session("appendicitis_001", student_id)["session_id"]
    )
    other_student_session_id = str(
        service.create_session("appendicitis_001", other_student_id)["session_id"]
    )

    target_candidate = _personal_candidate(
        session_id=target_id,
        student_id=student_id,
    )
    kept_candidate = _personal_candidate(
        session_id=kept_session_id,
        student_id=student_id,
    )
    global_candidate = _global_candidate()
    _save_candidate_and_skill(service, target_candidate)
    _save_candidate_and_skill(service, kept_candidate)
    _save_candidate_and_skill(service, global_candidate)
    target_report = _seed_report_with_outbox(
        service,
        session_id=target_id,
        student_id=student_id,
    )
    _seed_report_with_outbox(
        service,
        session_id=kept_session_id,
        student_id=student_id,
    )
    service.training_event_store.append_event(
        session_id=target_id,
        case_id="appendicitis_001",
        student_id=student_id,
        event_type="session_started",
        payload={},
    )
    target_candidate_id = f"personal_skill_candidate_{target_id}"
    service.training_event_store.append_event(
        session_id=target_candidate_id,
        case_id="appendicitis_001",
        student_id=student_id,
        event_type="personal_skill_candidate_generated",
        payload={},
    )
    service.training_event_store.append_event(
        session_id=kept_session_id,
        case_id="appendicitis_001",
        student_id=student_id,
        event_type="session_started",
        payload={},
    )
    service.student_profile_store.save_profile(student_id, {"marker": "stale"})
    service.student_profile_store.save_profile(
        other_student_id,
        {"marker": "other-profile"},
    )
    with service._message_processing_status_lock:
        service._message_processing_statuses[target_id] = {"status": "processing"}

    assert service.delete_session(
        target_id,
        expected_student_id=student_id,
    ) is True

    deletion = service.session_store.get_session_deletion(target_id)
    assert deletion is not None
    assert deletion.cleanup_status == "completed"
    assert service.session_store.get_session(target_id) is None
    assert service.report_store.get_report(target_id) is None
    pending_outbox_session_ids = {
        item.session_id for item in service.report_store.list_pending_outbox()
    }
    assert target_id not in pending_outbox_session_ids
    assert kept_session_id in pending_outbox_session_ids
    assert service.training_event_store.list_session_events(target_id) == []
    assert (
        service.training_event_store.list_session_events(target_candidate_id)
        == []
    )
    assert (
        service.training_skill_candidate_store.get_candidate(target_candidate_id)
        is None
    )
    assert (
        service.training_skill_store.get_skill(f"skill_personal_{target_id}")
        is None
    )
    assert target_id not in service._sessions
    with service._message_processing_status_lock:
        assert target_id not in service._message_processing_statuses

    assert service.session_store.get_session(kept_session_id) is not None
    assert service.session_store.get_session(other_student_session_id) is not None
    assert (
        service.training_skill_candidate_store.get_candidate(
            f"personal_skill_candidate_{kept_session_id}"
        )
        is not None
    )
    assert (
        service.training_skill_store.get_skill(
            f"skill_personal_{kept_session_id}"
        )
        is not None
    )
    assert (
        service.training_skill_candidate_store.get_candidate(
            "global_skill_candidate_keep"
        )
        is not None
    )
    assert service.training_skill_store.get_skill("skill_global_keep") is not None
    assert service.training_event_store.list_session_events(kept_session_id)
    assert {
        str(report["session_id"]) for report in service.report_store.list_reports()
    } == {kept_session_id}

    rebuilt_profile = service.student_profile_store.get_profile(student_id)
    assert rebuilt_profile is not None
    assert rebuilt_profile["last_updated_from_report_count"] == 1
    assert service.student_profile_store.get_profile(other_student_id) == {
        "marker": "other-profile",
        "student_id": other_student_id,
    }

    with pytest.raises(ReportDeletedError):
        service.report_store.save_report(target_report)
    with pytest.raises(TrainingEventStreamDeletedError):
        service.training_event_store.append_event(
            session_id=target_id,
            case_id="appendicitis_001",
            student_id=student_id,
            event_type="late_event",
            payload={},
        )
    with pytest.raises(TrainingEventStreamDeletedError):
        service.training_event_store.append_event(
            session_id=target_candidate_id,
            case_id="appendicitis_001",
            student_id=student_id,
            event_type="late_candidate_event",
            payload={},
        )
    with pytest.raises(TrainingSkillCandidateDeletedError):
        service.training_skill_candidate_store.save_candidate(
            target_candidate,
            dict(target_candidate["review"]),
        )
    with pytest.raises(TrainingSkillDeletedError):
        service.training_skill_store.enable_candidate(target_candidate)


def test_delete_session_failure_stays_pending_and_same_owner_retry_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(tmp_path)
    student_id = "student-retry"
    session_id = str(
        service.create_session("appendicitis_001", student_id)["session_id"]
    )
    _seed_report_with_outbox(
        service,
        session_id=session_id,
        student_id=student_id,
    )
    service.student_profile_store.save_profile(student_id, {"marker": "stale"})
    with service._message_processing_status_lock:
        service._message_processing_statuses[session_id] = {"status": "processing"}

    original_delete_report = service.report_store.delete_session_report
    attempts = 0

    def fail_once(target_session_id: str) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected report cleanup failure")
        return original_delete_report(target_session_id)

    monkeypatch.setattr(
        service.report_store,
        "delete_session_report",
        fail_once,
    )

    with pytest.raises(RuntimeError, match="injected report cleanup failure"):
        service.delete_session(
            session_id,
            expected_student_id=student_id,
        )

    pending = service.session_store.get_session_deletion(session_id)
    assert pending is not None
    assert pending.cleanup_status == "pending"
    assert service.session_store.get_session(session_id) is None
    assert service.report_store.get_report(session_id) is not None
    assert service.get_report(session_id) is None
    assert session_id not in service._sessions
    with service._message_processing_status_lock:
        assert session_id not in service._message_processing_statuses

    with pytest.raises(SessionNotFoundError):
        service.delete_session(
            session_id,
            expected_student_id="student-other",
        )

    assert service.resume_pending_session_deletions() == {
        "scanned": 1,
        "adopted": 0,
        "completed": 1,
        "failed": 0,
        "skipped": 0,
    }
    completed = service.session_store.get_session_deletion(session_id)
    assert completed is not None
    assert completed.cleanup_status == "completed"
    assert service.report_store.get_report(session_id) is None
    assert service.student_profile_store.get_profile(student_id) is not None

    assert service.delete_session(
        session_id,
        expected_student_id=student_id,
    ) is True
    with pytest.raises(SessionNotFoundError):
        service.delete_session(session_id)


def test_delete_session_fails_closed_on_personal_artifact_ownership_conflict(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path)
    student_id = "student-owner"
    session_id = str(
        service.create_session("appendicitis_001", student_id)["session_id"]
    )
    conflicting_candidate = {
        **_personal_candidate(
            session_id=session_id,
            student_id="student-other",
        ),
    }
    service.training_skill_candidate_store.save_candidate(
        conflicting_candidate,
        dict(conflicting_candidate["review"]),
    )

    with pytest.raises(SessionDeletionConflictError, match="归属冲突"):
        service.delete_session(
            session_id,
            expected_student_id=student_id,
        )

    assert service.session_store.get_session(session_id) is not None
    assert service.session_store.get_session_deletion(session_id) is None
    assert (
        service.training_skill_candidate_store.get_candidate(
            f"personal_skill_candidate_{session_id}"
        )
        is not None
    )


def test_legacy_tombstone_is_adopted_only_by_residual_authoritative_owner(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path)
    student_id = "student-legacy"
    session_id = str(
        service.create_session("appendicitis_001", student_id)["session_id"]
    )
    _seed_report_with_outbox(
        service,
        session_id=session_id,
        student_id=student_id,
    )
    _make_tombstone_ownerless(service, session_id)

    with pytest.raises(SessionNotFoundError):
        service.delete_session(
            session_id,
            expected_student_id="student-other",
        )
    unclaimed = service.session_store.get_session_deletion(session_id)
    assert unclaimed is not None
    assert unclaimed.user_id == ""
    assert service.report_store.get_report(session_id) is not None
    assert service.training_event_store.list_session_events(session_id)

    assert service.resume_pending_session_deletions() == {
        "scanned": 1,
        "adopted": 1,
        "completed": 1,
        "failed": 0,
        "skipped": 0,
    }
    completed = service.session_store.get_session_deletion(session_id)
    assert completed is not None
    assert completed.user_id == student_id
    assert completed.case_id == "appendicitis_001"
    assert completed.cleanup_status == "completed"
    assert service.report_store.get_report(session_id) is None
    assert service.training_event_store.list_session_events(session_id) == []


def test_legacy_tombstone_ownership_conflict_and_missing_evidence_fail_closed(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path)
    conflicted_id = str(
        service.create_session("appendicitis_001", "student-report")["session_id"]
    )
    _seed_report_with_outbox(
        service,
        session_id=conflicted_id,
        student_id="student-report",
    )
    service.training_event_store.append_event(
        session_id=conflicted_id,
        case_id="appendicitis_001",
        student_id="student-conflict",
        event_type="conflicting_legacy_owner",
        payload={},
    )
    _make_tombstone_ownerless(service, conflicted_id)

    for alleged_owner in ("student-report", "student-conflict"):
        with pytest.raises(SessionNotFoundError):
            service.delete_session(
                conflicted_id,
                expected_student_id=alleged_owner,
            )
    conflicted_deletion = service.session_store.get_session_deletion(conflicted_id)
    assert conflicted_deletion is not None
    assert conflicted_deletion.user_id == ""
    assert service.report_store.get_report(conflicted_id) is not None

    no_evidence_id = str(
        service.create_session("appendicitis_001", "student-no-evidence")[
            "session_id"
        ]
    )
    service.training_event_store.delete_event_streams([no_evidence_id])
    _make_tombstone_ownerless(service, no_evidence_id)

    with pytest.raises(SessionNotFoundError):
        service.delete_session(
            no_evidence_id,
            expected_student_id="student-no-evidence",
        )
    no_evidence_deletion = service.session_store.get_session_deletion(
        no_evidence_id
    )
    assert no_evidence_deletion is not None
    assert no_evidence_deletion.user_id == ""
    assert service.resume_pending_session_deletions() == {
        "scanned": 2,
        "adopted": 0,
        "completed": 0,
        "failed": 0,
        "skipped": 2,
    }


def test_process_startup_resumes_pending_session_deletion_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_service = _build_service(tmp_path)
    student_id = "student-startup-recovery"
    session_id = str(
        first_service.create_session("appendicitis_001", student_id)[
            "session_id"
        ]
    )
    _seed_report_with_outbox(
        first_service,
        session_id=session_id,
        student_id=student_id,
    )

    def fail_report_cleanup(_: str) -> bool:
        raise RuntimeError("injected process interruption")

    monkeypatch.setattr(
        first_service.report_store,
        "delete_session_report",
        fail_report_cleanup,
    )
    with pytest.raises(RuntimeError, match="process interruption"):
        first_service.delete_session(
            session_id,
            expected_student_id=student_id,
        )
    pending = first_service.session_store.get_session_deletion(session_id)
    assert pending is not None
    assert pending.cleanup_status == "pending"

    legacy_student_id = "student-startup-legacy"
    legacy_session_id = str(
        first_service.create_session("appendicitis_001", legacy_student_id)[
            "session_id"
        ]
    )
    _seed_report_with_outbox(
        first_service,
        session_id=legacy_session_id,
        student_id=legacy_student_id,
    )
    _make_tombstone_ownerless(first_service, legacy_session_id)

    restarted_service = _build_service(tmp_path)
    recovery_app = FastAPI(lifespan=_app_lifespan)
    recovery_app.state.session_deletion_recovery_service = restarted_service
    with TestClient(recovery_app):
        pass

    assert recovery_app.state.session_deletion_recovery_stats == {
        "scanned": 2,
        "adopted": 1,
        "completed": 2,
        "failed": 0,
        "skipped": 0,
    }
    completed = restarted_service.session_store.get_session_deletion(session_id)
    assert completed is not None
    assert completed.cleanup_status == "completed"
    assert restarted_service.report_store.get_report(session_id) is None
    legacy_completed = restarted_service.session_store.get_session_deletion(
        legacy_session_id
    )
    assert legacy_completed is not None
    assert legacy_completed.user_id == legacy_student_id
    assert legacy_completed.cleanup_status == "completed"
    assert restarted_service.report_store.get_report(legacy_session_id) is None


def test_pending_deletion_recovery_isolates_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_service = _build_service(tmp_path)
    student_id = "student-recovery-batch"
    failing_id = str(
        first_service.create_session("appendicitis_001", student_id)["session_id"]
    )
    successful_id = str(
        first_service.create_session("appendicitis_001", student_id)["session_id"]
    )
    for session_id in (failing_id, successful_id):
        _seed_report_with_outbox(
            first_service,
            session_id=session_id,
            student_id=student_id,
        )
        deletion = first_service.session_store.begin_session_deletion(
            session_id,
            student_id,
        )
        assert deletion is not None

    restarted_service = _build_service(tmp_path)
    original_delete_report = restarted_service.report_store.delete_session_report

    def fail_one_report_cleanup(session_id: str) -> bool:
        if session_id == failing_id:
            raise RuntimeError("one cleanup failed")
        return original_delete_report(session_id)

    monkeypatch.setattr(
        restarted_service.report_store,
        "delete_session_report",
        fail_one_report_cleanup,
    )

    assert restarted_service.resume_pending_session_deletions() == {
        "scanned": 2,
        "adopted": 0,
        "completed": 1,
        "failed": 1,
        "skipped": 0,
    }
    failed = restarted_service.session_store.get_session_deletion(failing_id)
    completed = restarted_service.session_store.get_session_deletion(
        successful_id
    )
    assert failed is not None
    assert failed.cleanup_status == "pending"
    assert restarted_service.report_store.get_report(failing_id) is not None
    assert completed is not None
    assert completed.cleanup_status == "completed"
    assert restarted_service.report_store.get_report(successful_id) is None


def test_pending_deletion_recovery_does_not_starve_items_after_first_hundred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_service = _build_service(tmp_path)
    student_id = "student-large-recovery"
    session_ids: list[str] = []
    for index in range(105):
        session = OsceSession(
            session_id=f"pending-session-{index:03d}",
            student_id=student_id,
            case_id="appendicitis_001",
            stage="history",
        )
        first_service.session_store.create_session(session)
        deletion = first_service.session_store.begin_session_deletion(
            session.session_id,
            student_id,
        )
        assert deletion is not None
        session_ids.append(session.session_id)

    restarted_service = _build_service(tmp_path)
    failing_session_ids = set(session_ids[:3])
    original_delete_report = restarted_service.report_store.delete_session_report

    def fail_early_items(session_id: str) -> bool:
        if session_id in failing_session_ids:
            raise RuntimeError("persistent early cleanup failure")
        return original_delete_report(session_id)

    monkeypatch.setattr(
        restarted_service.report_store,
        "delete_session_report",
        fail_early_items,
    )
    monkeypatch.setattr(
        restarted_service,
        "_refresh_student_profile",
        lambda _: None,
    )

    assert restarted_service.resume_pending_session_deletions() == {
        "scanned": 105,
        "adopted": 0,
        "completed": 102,
        "failed": 3,
        "skipped": 0,
    }
    last_deletion = restarted_service.session_store.get_session_deletion(
        session_ids[-1]
    )
    assert last_deletion is not None
    assert last_deletion.cleanup_status == "completed"
    for session_id in failing_session_ids:
        failed_deletion = restarted_service.session_store.get_session_deletion(
            session_id
        )
        assert failed_deletion is not None
        assert failed_deletion.cleanup_status == "pending"
