import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

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
from app.services.osce_session_store import (
    SESSION_DELETION_CLEANUP_VERSION,
    OsceSessionStore,
    SessionNotFoundError,
    SessionOutboxEvent,
)
from app.services.report_store import (
    ReportDeletedError,
    ReportOutboxEvent,
    ReportStore,
)
from app.services.student_profile_store import StudentProfileStore
from app.services.training_event_store import (
    TrainingEventDeletedSkillSourceError,
    TrainingEventStore,
    TrainingEventStreamDeletedError,
)
from app.services.training_skill_candidate_store import (
    TrainingSkillCandidateDeletedError,
    TrainingSkillCandidateSourceDeletedError,
    TrainingSkillCandidateStore,
)
from app.services.training_skill_store import (
    TrainingSkillDeletedError,
    TrainingSkillSourceDeletedError,
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


def _source_global_candidate(
    *,
    candidate_id: str,
    trigger_item_id: str,
    source_session_id: str,
    review_status: str,
) -> dict[str, object]:
    source_report_id = f"{source_session_id}_report"
    return {
        "candidate_id": candidate_id,
        "trigger_item_id": trigger_item_id,
        "trigger_item_ids": [trigger_item_id],
        "case_ids": ["appendicitis_001"],
        "stage_scope": ["case_intro"],
        "title": f"source-derived-marker {candidate_id}",
        "description": "source-derived-marker description",
        "suggested_strategy": "source-derived-marker strategy",
        "scope": "global",
        "source_provenance_schema_version": "training_candidate_sources.v1",
        "source_session_ids": [source_session_id, "remaining-source"],
        "source_report_ids": [
            source_report_id,
            "remaining-source_report",
        ],
        "source_turn_patterns": [
            {
                "pattern_id": trigger_item_id,
                "count": 2,
                "session_ids": [source_session_id, "remaining-source"],
                "source_report_ids": [
                    source_report_id,
                    "remaining-source_report",
                ],
                "source_report_count": 2,
            }
        ],
        "source_report_count": 2,
        "support_count": 2,
        "related_recommendations": ["source-derived-marker recommendation"],
        "review": {
            "candidate_id": candidate_id,
            "status": review_status,
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


def test_delete_session_cleans_personal_and_global_derivatives_across_follow_up_sessions(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path)
    student_id = "student-derived-owner"
    other_student_id = "student-derived-other"
    source_session_id = str(
        service.create_session("appendicitis_001", student_id)[
            "session_id"
        ]
    )
    personal_candidate = _personal_candidate(
        session_id=source_session_id,
        student_id=student_id,
    )
    _save_candidate_and_skill(service, personal_candidate)

    reviewed_global = _source_global_candidate(
        candidate_id="candidate_global_affected",
        trigger_item_id="global_affected",
        source_session_id=source_session_id,
        review_status="approved",
    )
    unreviewed_global = _source_global_candidate(
        candidate_id="candidate_global_unreviewed",
        trigger_item_id="global_unreviewed",
        source_session_id=source_session_id,
        review_status="ready_for_review",
    )
    unrelated_global = {
        **_global_candidate(),
        "source_provenance_schema_version": "training_candidate_sources.v1",
        "source_session_ids": ["unrelated-source"],
        "source_report_ids": ["unrelated-source_report"],
    }
    _save_candidate_and_skill(service, reviewed_global)
    service.training_skill_candidate_store.save_candidate(
        unreviewed_global,
        dict(unreviewed_global["review"]),
    )
    _save_candidate_and_skill(service, unrelated_global)

    owner_follow_up_id = str(
        service.create_session("appendicitis_001", student_id)[
            "session_id"
        ]
    )
    other_follow_up_id = str(
        service.create_session("appendicitis_001", other_student_id)[
            "session_id"
        ]
    )
    personal_skill_id = f"skill_personal_{source_session_id}"
    affected_global_skill_id = "skill_global_affected"
    unrelated_global_skill_id = "skill_global_keep"
    owner_before = service.session_store.get_session(owner_follow_up_id)
    other_before = service.session_store.get_session(other_follow_up_id)
    assert owner_before is not None
    assert other_before is not None
    assert personal_skill_id in str(owner_before.payload)
    assert affected_global_skill_id in str(owner_before.payload)
    assert affected_global_skill_id in str(other_before.payload)
    assert any(
        event["payload"].get("skill_id") == affected_global_skill_id
        for event in service.training_event_store.list_session_events(
            other_follow_up_id
        )
        if event["event_type"] == "training_skill_applied"
    )

    assert service.delete_session(
        source_session_id,
        expected_student_id=student_id,
    )

    for follow_up_id in (owner_follow_up_id, other_follow_up_id):
        stored = service.session_store.get_session(follow_up_id)
        assert stored is not None
        serialized = str(stored.payload)
        assert source_session_id not in serialized
        assert personal_skill_id not in serialized
        assert affected_global_skill_id not in serialized
        assert unrelated_global_skill_id in serialized
        remaining_events = (
            service.training_event_store.list_session_events(follow_up_id)
        )
        assert all(
            personal_skill_id not in str(event["payload"])
            and affected_global_skill_id not in str(event["payload"])
            and source_session_id not in str(event["payload"])
            for event in remaining_events
        )
        assert any(
            event["payload"].get("skill_id")
            == unrelated_global_skill_id
            for event in remaining_events
            if event["event_type"] == "training_skill_applied"
        )

    assert (
        service.training_skill_candidate_store.get_candidate(
            "candidate_global_unreviewed"
        )
        is None
    )
    stale_candidate = (
        service.training_skill_candidate_store.get_candidate(
            "candidate_global_affected"
        )
    )
    assert stale_candidate is not None
    assert stale_candidate["review"]["status"] == "stale_requires_review"
    assert source_session_id not in str(stale_candidate)
    assert "source-derived-marker" not in str(stale_candidate)
    stale_skill = service.training_skill_store.get_skill(
        affected_global_skill_id
    )
    assert stale_skill is not None
    assert stale_skill["status"] == "stale_requires_review"
    assert source_session_id not in str(stale_skill)
    assert "source-derived-marker" not in str(stale_skill)
    assert affected_global_skill_id not in {
        skill["skill_id"]
        for skill in service.training_skill_store.list_enabled_skills()
    }
    assert (
        service.training_skill_candidate_store.get_candidate(
            "global_skill_candidate_keep"
        )
        is not None
    )
    assert service.training_skill_store.get_skill(
        unrelated_global_skill_id
    ) is not None

    restarted_service = _build_service(tmp_path)
    assert restarted_service.delete_session(
        source_session_id,
        expected_student_id=student_id,
    )
    completed = restarted_service.session_store.get_session_deletion(
        source_session_id
    )
    assert completed is not None
    assert completed.cleanup_status == "completed"
    assert (
        completed.cleanup_version
        == SESSION_DELETION_CLEANUP_VERSION
    )

    with pytest.raises(TrainingEventDeletedSkillSourceError):
        restarted_service.training_event_store.append_event(
            session_id="late-global-application",
            case_id="appendicitis_001",
            student_id=other_student_id,
            event_type="training_skill_applied",
            payload={"skill_id": affected_global_skill_id},
        )
    with pytest.raises(TrainingSkillCandidateSourceDeletedError):
        restarted_service.training_skill_candidate_store.save_candidate(
            reviewed_global,
            dict(reviewed_global["review"]),
        )
    with pytest.raises(TrainingSkillSourceDeletedError):
        restarted_service.training_skill_store.enable_candidate(
            reviewed_global
        )

    regenerated_global = {
        **reviewed_global,
        "title": "基于剩余来源重新生成的全局 Skill",
        "description": "仅使用 remaining-source 重新生成。",
        "suggested_strategy": "使用剩余证据继续训练。",
        "source_session_ids": ["remaining-source"],
        "source_report_ids": ["remaining-source_report"],
        "source_turn_patterns": [
            {
                "pattern_id": "global_affected",
                "count": 1,
                "session_ids": ["remaining-source"],
                "source_report_ids": ["remaining-source_report"],
                "source_report_count": 1,
            }
        ],
        "source_report_count": 1,
        "support_count": 1,
    }
    restarted_service.training_skill_candidate_store.save_candidate(
        regenerated_global,
        dict(regenerated_global["review"]),
    )
    assert restarted_service.training_skill_store.enable_candidate(
        regenerated_global
    )
    regenerated_session_id = str(
        restarted_service.create_session(
            "appendicitis_001",
            other_student_id,
        )["session_id"]
    )
    regenerated_session = restarted_service.session_store.get_session(
        regenerated_session_id
    )
    assert regenerated_session is not None
    assert affected_global_skill_id in str(regenerated_session.payload)
    assert source_session_id not in str(regenerated_session.payload)
    assert "remaining-source" in str(regenerated_session.payload)
    regenerated_events = (
        restarted_service.training_event_store.list_session_events(
            regenerated_session_id
        )
    )
    regenerated_application = next(
        event
        for event in regenerated_events
        if event["event_type"] == "training_skill_applied"
        and event["payload"].get("skill_id") == affected_global_skill_id
    )
    assert regenerated_application["payload"][
        "source_provenance_schema_version"
    ] == "training_candidate_sources.v1"
    assert regenerated_application["payload"]["source_session_ids"] == [
        "remaining-source"
    ]
    assert source_session_id not in str(regenerated_application["payload"])


def test_concurrent_late_session_create_is_scrubbed_without_partial_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creating_service = _build_service(tmp_path)
    student_id = "student-late-create-race"
    source_session_id = str(
        creating_service.create_session(
            "appendicitis_001",
            student_id,
        )["session_id"]
    )
    personal_candidate = _personal_candidate(
        session_id=source_session_id,
        student_id=student_id,
    )
    _save_candidate_and_skill(creating_service, personal_candidate)
    personal_skill_id = f"skill_personal_{source_session_id}"

    create_reached_store = Event()
    allow_create_to_continue = Event()
    original_create_session = (
        creating_service.session_store.create_session
    )

    def paused_create_session(
        session: OsceSession,
        *,
        outbox_events: (
            tuple[SessionOutboxEvent, ...] | list[SessionOutboxEvent]
        ) = (),
        expected_deleted_skill_sources_version: int | None = None,
    ) -> int:
        create_reached_store.set()
        assert allow_create_to_continue.wait(timeout=5)
        return original_create_session(
            session,
            outbox_events=outbox_events,
            expected_deleted_skill_sources_version=(
                expected_deleted_skill_sources_version
            ),
        )

    monkeypatch.setattr(
        creating_service.session_store,
        "create_session",
        paused_create_session,
    )
    deleting_service = _build_service(tmp_path)
    with ThreadPoolExecutor(max_workers=1) as executor:
        create_future = executor.submit(
            creating_service.create_session,
            "appendicitis_001",
            student_id,
        )
        assert create_reached_store.wait(timeout=5)
        try:
            assert deleting_service.delete_session(
                source_session_id,
                expected_student_id=student_id,
            )
        finally:
            allow_create_to_continue.set()
        created_payload = create_future.result(timeout=5)

    created_session_id = str(created_payload["session_id"])
    stored = creating_service.session_store.get_session(
        created_session_id
    )
    assert stored is not None
    assert personal_skill_id not in str(stored.payload)
    assert source_session_id not in str(stored.payload)
    events = creating_service.training_event_store.list_session_events(
        created_session_id
    )
    assert events
    assert all(
        personal_skill_id not in str(event["payload"])
        and source_session_id not in str(event["payload"])
        for event in events
    )
    assert all(
        not (
            event["event_type"] == "training_skill_applied"
            and event["payload"].get("skill_id") == personal_skill_id
        )
        for event in events
    )


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


def test_delete_session_preflights_cross_owner_derived_reference_before_tombstoning_source(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path)
    source_owner = "student-source-owner"
    source_session_id = str(
        service.create_session("appendicitis_001", source_owner)[
            "session_id"
        ]
    )
    personal_skill_id = f"skill_personal_{source_session_id}"
    conflicting_follow_up = OsceSession(
        session_id="cross-owner-derived-reference",
        student_id="student-other-owner",
        case_id="appendicitis_001",
        stage="case_intro",
        active_skill_context={
            "skill_index": [{"skill_id": personal_skill_id}],
            "selected_skills": [{"skill_id": personal_skill_id}],
            "skipped_reasons": [],
        },
    )
    service.session_store.create_session(conflicting_follow_up)

    with pytest.raises(SessionDeletionConflictError, match="归属冲突"):
        service.delete_session(
            source_session_id,
            expected_student_id=source_owner,
        )

    assert service.session_store.get_session(source_session_id) is not None
    assert (
        service.session_store.get_session_deletion(source_session_id)
        is None
    )
    preserved = service.session_store.get_session(
        conflicting_follow_up.session_id
    )
    assert preserved is not None
    assert personal_skill_id in str(preserved.payload)


@pytest.mark.parametrize(
    ("conflict_store", "completed_cleanup_version"),
    [
        ("session", None),
        ("event", SESSION_DELETION_CLEANUP_VERSION - 1),
    ],
)
def test_deletion_recovery_preflights_cross_owner_references_before_global_cleanup(
    tmp_path: Path,
    conflict_store: str,
    completed_cleanup_version: int | None,
) -> None:
    service = _build_service(tmp_path)
    source_owner = "student-recovery-source"
    source_session_id = str(
        service.create_session("appendicitis_001", source_owner)[
            "session_id"
        ]
    )
    reviewed_global = _source_global_candidate(
        candidate_id="candidate_recovery_global",
        trigger_item_id="recovery_global",
        source_session_id=source_session_id,
        review_status="approved",
    )
    _save_candidate_and_skill(service, reviewed_global)
    global_candidate_id = str(reviewed_global["candidate_id"])
    global_skill_id = "skill_recovery_global"
    personal_skill_id = f"skill_personal_{source_session_id}"
    candidate_before = (
        service.training_skill_candidate_store.get_candidate(
            global_candidate_id
        )
    )
    skill_before = service.training_skill_store.get_skill(global_skill_id)
    assert candidate_before is not None
    assert skill_before is not None

    deletion = service.session_store.begin_session_deletion(
        source_session_id,
        source_owner,
    )
    assert deletion is not None
    if completed_cleanup_version is not None:
        with sqlite3.connect(service.session_store.database_path) as connection:
            connection.execute(
                """
                UPDATE osce_session_tombstones
                SET
                    cleanup_status = 'completed',
                    cleanup_completed_at = deleted_at,
                    cleanup_version = ?
                WHERE session_id = ?
                """,
                (completed_cleanup_version, source_session_id),
            )

    cross_owner_session_id = "cross-owner-recovery-reference"
    if conflict_store == "session":
        service.session_store.create_session(
            OsceSession(
                session_id=cross_owner_session_id,
                student_id="student-recovery-other",
                case_id="appendicitis_001",
                stage="case_intro",
                active_skill_context={
                    "skill_index": [{"skill_id": personal_skill_id}],
                    "selected_skills": [{"skill_id": personal_skill_id}],
                    "skipped_reasons": [],
                },
            )
        )
    else:
        service.training_event_store.append_event(
            session_id=cross_owner_session_id,
            case_id="appendicitis_001",
            student_id="student-recovery-other",
            event_type="training_skill_applied",
            payload={
                "skill_id": personal_skill_id,
                "owner_student_id": "student-recovery-other",
                "source_session_id": source_session_id,
            },
        )

    with pytest.raises(SessionDeletionConflictError, match="归属冲突"):
        service.delete_session(
            source_session_id,
            expected_student_id=source_owner,
        )

    assert (
        service.training_skill_candidate_store.get_candidate(
            global_candidate_id
        )
        == candidate_before
    )
    assert service.training_skill_store.get_skill(global_skill_id) == skill_before
    if conflict_store == "session":
        assert service.session_store.get_session(cross_owner_session_id) is not None
    else:
        assert service.training_event_store.list_session_events(
            cross_owner_session_id
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
    with sqlite3.connect(first_service.session_store.database_path) as connection:
        connection.execute(
            """
            INSERT INTO osce_session_event_outbox (
                event_key,
                session_id,
                session_revision,
                event_index,
                case_id,
                student_id,
                event_type,
                payload_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"session:{legacy_session_id}:revision:99:event:0:stale_deleted",
                legacy_session_id,
                99,
                0,
                "appendicitis_001",
                legacy_student_id,
                "stale_deleted",
                "{}",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    live_session_id = str(
        first_service.create_session(
            "appendicitis_001",
            "student-startup-live",
        )["session_id"]
    )
    live_record = first_service.session_store.get_session(live_session_id)
    assert live_record is not None
    first_service.session_store.update_session_and_get(
        OsceSession(**live_record.payload),
        expected_revision=live_record.revision,
        outbox_events=(
            SessionOutboxEvent(
                event_type="startup_delivery_probe",
                payload={"source": "startup"},
            ),
        ),
    )

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
    assert recovery_app.state.session_event_outbox_recovered == 1
    assert restarted_service.session_store.list_pending_event_outbox() == []
    assert [
        event["event_type"]
        for event in restarted_service.training_event_store.list_session_events(
            live_session_id
        )
        if event["event_type"] == "startup_delivery_probe"
    ] == ["startup_delivery_probe"]
    assert restarted_service.training_event_store.list_session_events(
        legacy_session_id
    ) == []
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


def test_process_startup_drains_more_than_one_outbox_batch() -> None:
    class _BatchedRecoveryService:
        def __init__(self) -> None:
            self.drain_limits: list[int] = []
            self._batch_sizes = iter((1_000, 1))

        @staticmethod
        def resume_pending_session_deletions() -> dict[str, int]:
            return {
                "scanned": 0,
                "adopted": 0,
                "completed": 0,
                "failed": 0,
                "skipped": 0,
            }

        def drain_session_event_outbox(self, *, limit: int) -> int:
            self.drain_limits.append(limit)
            return next(self._batch_sizes)

    recovery_service = _BatchedRecoveryService()
    recovery_app = FastAPI(lifespan=_app_lifespan)
    recovery_app.state.session_deletion_recovery_service = recovery_service

    with TestClient(recovery_app):
        pass

    assert recovery_service.drain_limits == [1_000, 1_000]
    assert recovery_app.state.session_event_outbox_recovered == 1_001


def test_restart_upgrades_completed_legacy_cleanup_and_removes_derived_references(
    tmp_path: Path,
) -> None:
    first_service = _build_service(tmp_path)
    student_id = "student-cleanup-upgrade"
    source_session_id = str(
        first_service.create_session("appendicitis_001", student_id)[
            "session_id"
        ]
    )
    personal_candidate = _personal_candidate(
        session_id=source_session_id,
        student_id=student_id,
    )
    _save_candidate_and_skill(first_service, personal_candidate)
    follow_up_id = str(
        first_service.create_session("appendicitis_001", student_id)[
            "session_id"
        ]
    )
    personal_skill_id = f"skill_personal_{source_session_id}"
    before = first_service.session_store.get_session(follow_up_id)
    assert before is not None
    assert personal_skill_id in str(before.payload)

    assert first_service.session_store.delete_session(source_session_id)
    with sqlite3.connect(first_service.session_store.database_path) as connection:
        connection.execute(
            """
            UPDATE osce_session_tombstones
            SET cleanup_version = ?
            WHERE session_id = ?
            """,
            (
                SESSION_DELETION_CLEANUP_VERSION - 1,
                source_session_id,
            ),
        )
    legacy_completed = first_service.session_store.get_session_deletion(
        source_session_id
    )
    assert legacy_completed is not None
    assert legacy_completed.cleanup_status == "completed"
    assert (
        legacy_completed.cleanup_version
        < SESSION_DELETION_CLEANUP_VERSION
    )

    restarted_service = _build_service(tmp_path)
    assert restarted_service.resume_pending_session_deletions() == {
        "scanned": 1,
        "adopted": 0,
        "completed": 1,
        "failed": 0,
        "skipped": 0,
    }

    upgraded = restarted_service.session_store.get_session_deletion(
        source_session_id
    )
    assert upgraded is not None
    assert upgraded.cleanup_status == "completed"
    assert (
        upgraded.cleanup_version
        == SESSION_DELETION_CLEANUP_VERSION
    )
    after = restarted_service.session_store.get_session(follow_up_id)
    assert after is not None
    assert personal_skill_id not in str(after.payload)
    assert all(
        personal_skill_id not in str(event["payload"])
        for event in restarted_service.training_event_store.list_session_events(
            follow_up_id
        )
    )


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
