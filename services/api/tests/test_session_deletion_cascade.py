from pathlib import Path

import pytest

from app.graph.osce_graph import build_osce_graph
from app.services.osce_session_service import (
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

    assert service.delete_session(
        session_id,
        expected_student_id=student_id,
    ) is True
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
