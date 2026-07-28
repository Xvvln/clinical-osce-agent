from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, Lock

import pytest

from app.graph.osce_graph import build_osce_graph
from app.services.osce_session_service import OsceSessionService
from app.services.osce_session_store import OsceSessionStore, SessionWriteConflictError
from app.services.report_store import ReportStore
from app.services.student_profile_store import StudentProfileStore
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_candidate_service import TrainingSkillCandidateGenerationError
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_store import TrainingSkillStore


def _canonical_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


def _approved_personal_skill_payload() -> dict[str, object]:
    return {
        "personal_skill_candidate": {
            "status": "approved",
            "scope": "personal",
            "candidate_id": "personal_candidate_outbox",
            "skill_id": "skill_personal_outbox",
            "review": {"status": "approved"},
            "rag_evidence_items": [],
            "web_check_status": "not_configured",
            "external_evidence_checks": [],
        },
        "ai_reflection_review": {
            "status": "generated",
            "summary": "个人训练增强已完成。",
        },
    }


class _SuccessfulPersonalSkillService:
    def __init__(self) -> None:
        self.call_count = 0
        self._lock = Lock()

    def generate_for_completed_session(self, **_: object) -> dict[str, object]:
        with self._lock:
            self.call_count += 1
        return _approved_personal_skill_payload()


class _BlockingPersonalSkillService(_SuccessfulPersonalSkillService):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def generate_for_completed_session(self, **_: object) -> dict[str, object]:
        with self._lock:
            self.call_count += 1
        self.started.set()
        assert self.release.wait(timeout=5)
        return _approved_personal_skill_payload()


class _FlakyPersonalSkillService(_SuccessfulPersonalSkillService):
    def generate_for_completed_session(self, **_: object) -> dict[str, object]:
        with self._lock:
            self.call_count += 1
            attempt = self.call_count
        if attempt == 1:
            raise TrainingSkillCandidateGenerationError("temporary provider failure")
        return _approved_personal_skill_payload()


def _build_service(tmp_path, personal_skill_service: object) -> OsceSessionService:
    return OsceSessionService(
        report_store=ReportStore(tmp_path / "reports.sqlite3"),
        training_event_store=TrainingEventStore(tmp_path / "training_events.sqlite3"),
        training_skill_store=TrainingSkillStore(tmp_path / "training_skills.sqlite3"),
        training_skill_candidate_store=TrainingSkillCandidateStore(
            tmp_path / "training_skill_candidates.sqlite3"
        ),
        session_store=OsceSessionStore(tmp_path / "osce_sessions.sqlite3"),
        student_profile_store=StudentProfileStore(tmp_path / "student_profiles.sqlite3"),
        personal_skill_service=personal_skill_service,
        graph=build_osce_graph(patient_responder=_canonical_patient_responder),
    )


def _prepare_completed_session(service: OsceSessionService) -> str:
    session_id = str(
        service.create_session(
            case_id="appendicitis_001",
            student_id="student_report_outbox",
        )["session_id"]
    )
    submitted = service.submit_diagnosis(
        session_id,
        diagnosis="急性阑尾炎",
        reasoning="转移性右下腹痛支持诊断。",
    )
    assert submitted is not None
    return session_id


def test_base_report_and_enrichment_emit_distinct_idempotent_events(tmp_path) -> None:
    personal_skill_service = _SuccessfulPersonalSkillService()
    service = _build_service(tmp_path, personal_skill_service)
    session_id = _prepare_completed_session(service)

    base_report = service.get_report(session_id, include_optional_agents=False)

    assert base_report is not None
    assert base_report["personal_skill_candidate"]["status"] == "generation_pending"
    base_stored = service.report_store.get_stored_report(session_id)
    assert base_stored is not None
    assert base_stored.revision == 1
    assert base_stored.enrichment_status == "pending"
    base_events = service.training_event_store.list_session_events(session_id)
    generated_events = [event for event in base_events if event["event_type"] == "report_generated"]
    assert len(generated_events) == 1
    assert generated_events[0]["payload"]["report_id"] == base_report["report_id"]
    assert generated_events[0]["payload"]["report_revision"] == 1
    assert generated_events[0]["payload"]["report"] == base_report

    enriched_report = service.enrich_report_optional_agents(session_id)
    replayed_report = service.enrich_report_optional_agents(session_id)

    assert enriched_report is not None
    assert replayed_report == enriched_report
    assert personal_skill_service.call_count == 1
    assert enriched_report["personal_skill_candidate"]["status"] == "approved"
    enriched_stored = service.report_store.get_stored_report(session_id)
    assert enriched_stored is not None
    assert enriched_stored.revision == 3
    assert enriched_stored.enrichment_status == "completed"
    events = service.training_event_store.list_session_events(session_id)
    assert len([event for event in events if event["event_type"] == "report_generated"]) == 1
    enriched_events = [event for event in events if event["event_type"] == "report_enriched"]
    assert len(enriched_events) == 1
    assert enriched_events[0]["payload"]["report_revision"] == 3
    assert enriched_events[0]["payload"]["report"] == enriched_report
    assert service.report_store.list_pending_outbox() == []


def test_two_service_instances_share_one_enrichment_lease(tmp_path) -> None:
    personal_skill_service = _BlockingPersonalSkillService()
    bootstrap_service = _build_service(tmp_path, personal_skill_service)
    session_id = _prepare_completed_session(bootstrap_service)
    base_report = bootstrap_service.get_report(session_id, include_optional_agents=False)
    assert base_report is not None

    first_service = _build_service(tmp_path, personal_skill_service)
    second_service = _build_service(tmp_path, personal_skill_service)
    with ThreadPoolExecutor(max_workers=2) as executor:
        winner_future = executor.submit(first_service.enrich_report_optional_agents, session_id)
        assert personal_skill_service.started.wait(timeout=5)
        loser_future = executor.submit(second_service.enrich_report_optional_agents, session_id)
        loser_report = loser_future.result(timeout=5)
        personal_skill_service.release.set()
        winner_report = winner_future.result(timeout=5)

    assert loser_report is not None
    assert loser_report["personal_skill_candidate"]["status"] == "generation_pending"
    assert winner_report is not None
    assert winner_report["personal_skill_candidate"]["status"] == "approved"
    assert personal_skill_service.call_count == 1
    assert second_service.get_report(session_id)["personal_skill_candidate"]["status"] == "approved"
    events = second_service.training_event_store.list_session_events(session_id)
    assert len([event for event in events if event["event_type"] == "report_enriched"]) == 1


def test_saved_base_report_survives_event_delivery_failure_and_retries(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(tmp_path, _SuccessfulPersonalSkillService())
    session_id = _prepare_completed_session(service)
    original_append_event = service.training_event_store.append_event

    def unavailable_append_event(*_: object, **__: object) -> bool:
        raise RuntimeError("event database unavailable")

    monkeypatch.setattr(service.training_event_store, "append_event", unavailable_append_event)
    report = service.get_report(session_id, include_optional_agents=False)

    assert report is not None
    assert service.report_store.get_report(session_id) == report
    assert len(service.report_store.list_pending_outbox()) == 1

    monkeypatch.setattr(service.training_event_store, "append_event", original_append_event)
    assert service.drain_report_outbox() == 1
    assert service.report_store.list_pending_outbox() == []
    events = service.training_event_store.list_session_events(session_id)
    assert len([event for event in events if event["event_type"] == "report_generated"]) == 1


def test_outbox_replay_after_insert_before_ack_keeps_one_training_event(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(tmp_path, _SuccessfulPersonalSkillService())
    session_id = _prepare_completed_session(service)
    original_acknowledge = service.report_store.acknowledge_outbox

    def fail_acknowledge(*_: object, **__: object) -> bool:
        raise RuntimeError("crash before outbox ack")

    monkeypatch.setattr(service.report_store, "acknowledge_outbox", fail_acknowledge)
    report = service.get_report(session_id, include_optional_agents=False)

    assert report is not None
    assert len(service.report_store.list_pending_outbox()) == 1
    events_after_crash = service.training_event_store.list_session_events(session_id)
    assert len([event for event in events_after_crash if event["event_type"] == "report_generated"]) == 1

    monkeypatch.setattr(service.report_store, "acknowledge_outbox", original_acknowledge)
    assert service.drain_report_outbox() == 1
    assert service.report_store.list_pending_outbox() == []
    events_after_replay = service.training_event_store.list_session_events(session_id)
    assert len([event for event in events_after_replay if event["event_type"] == "report_generated"]) == 1


def test_failed_enrichment_is_retryable_on_next_normal_open(tmp_path) -> None:
    personal_skill_service = _FlakyPersonalSkillService()
    service = _build_service(tmp_path, personal_skill_service)
    session_id = _prepare_completed_session(service)
    base_report = service.get_report(session_id, include_optional_agents=False)
    assert base_report is not None

    failed_report = service.get_report(session_id)
    retried_report = service.get_report(session_id)

    assert failed_report is not None
    assert failed_report["personal_skill_candidate"]["status"] == "generation_failed"
    assert retried_report is not None
    assert retried_report["personal_skill_candidate"]["status"] == "approved"
    assert personal_skill_service.call_count == 2
    stored = service.report_store.get_stored_report(session_id)
    assert stored is not None
    assert stored.enrichment_status == "completed"
    events = service.training_event_store.list_session_events(session_id)
    assert len([event for event in events if event["event_type"] == "report_enrichment_failed"]) == 1
    assert len([event for event in events if event["event_type"] == "report_enriched"]) == 1
    assert len([event for event in events if event["event_type"] == "report_generated"]) == 1


def test_expired_enrichment_claim_is_recovered_on_normal_open(tmp_path) -> None:
    personal_skill_service = _SuccessfulPersonalSkillService()
    service = _build_service(tmp_path, personal_skill_service)
    session_id = _prepare_completed_session(service)
    base_report = service.get_report(session_id, include_optional_agents=False)
    assert base_report is not None
    abandoned_claim = service.report_store.claim_report_enrichment(
        session_id,
        lease_seconds=1,
        now=datetime(2020, 1, 1, tzinfo=UTC),
    )
    assert abandoned_claim is not None

    recovered_report = service.get_report(session_id)

    assert recovered_report is not None
    assert recovered_report["personal_skill_candidate"]["status"] == "approved"
    assert personal_skill_service.call_count == 1
    stored = service.report_store.get_stored_report(session_id)
    assert stored is not None
    assert stored.enrichment_status == "completed"
    assert stored.enrichment_retry_count == 1


def test_session_cas_conflict_after_completion_does_not_regress_report(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service(tmp_path, _SuccessfulPersonalSkillService())
    session_id = _prepare_completed_session(service)
    base_report = service.get_report(session_id, include_optional_agents=False)
    assert base_report is not None

    def reject_session_sync(_: object) -> None:
        raise SessionWriteConflictError(
            session_id,
            expected_revision=1,
            current_revision=2,
        )

    monkeypatch.setattr(service, "_save_session", reject_session_sync)
    enriched_report = service.enrich_report_optional_agents(session_id)

    assert enriched_report is not None
    assert enriched_report["personal_skill_candidate"]["status"] == "approved"
    stored = service.report_store.get_stored_report(session_id)
    assert stored is not None
    assert stored.enrichment_status == "completed"
    assert stored.payload == enriched_report
