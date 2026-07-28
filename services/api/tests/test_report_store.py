from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest

from app.services.report_store import (
    ReportAlreadyExistsError,
    ReportClaimLostError,
    ReportOutboxEvent,
    ReportStore,
)


def test_report_store_persists_report_across_instances(tmp_path) -> None:
    database_path = tmp_path / "reports.sqlite3"
    report = {
        "report_id": "session_demo_report",
        "session_id": "session_demo",
        "case_id": "appendicitis_001",
        "total_score": 55,
        "feedback_summary": "已根据评分轨迹生成教学反馈，内容仅用于 OSCE 训练复盘。",
    }

    ReportStore(database_path).save_report(report)
    loaded_report = ReportStore(database_path).get_report("session_demo")

    assert loaded_report == report


def test_report_store_lists_reports_newest_first(tmp_path) -> None:
    database_path = tmp_path / "reports.sqlite3"
    first_report = {
        "report_id": "report_first",
        "session_id": "session_first",
        "case_id": "appendicitis_001",
        "student_id": "student_first",
        "total_score": 72,
    }
    second_report = {
        "report_id": "report_second",
        "session_id": "session_second",
        "case_id": "appendicitis_002",
        "student_id": "student_second",
        "total_score": 86,
    }

    store = ReportStore(database_path)
    store.save_report(first_report)
    store.save_report(second_report)

    assert ReportStore(database_path).list_reports() == [second_report, first_report]


def test_create_base_report_is_idempotent_but_rejects_different_snapshot(tmp_path) -> None:
    store = ReportStore(tmp_path / "reports.sqlite3")
    pending_report = _report("session_base", status="generation_pending", total_score=70)

    first = store.create_base_report(pending_report)
    second = store.create_base_report(dict(pending_report))

    assert first == second
    assert first.revision == 1
    assert first.enrichment_status == "pending"
    assert "revision" not in first.payload

    with pytest.raises(ReportAlreadyExistsError):
        store.create_base_report(_report("session_base", status="generation_pending", total_score=71))


def test_base_report_retry_backfills_one_stable_outbox_event(tmp_path) -> None:
    database_path = tmp_path / "reports.sqlite3"
    store = ReportStore(database_path)
    report = _report("session_base_outbox", status="generation_pending")
    event = ReportOutboxEvent(
        case_id="appendicitis_001",
        student_id="student_base",
        event_type="report_generated",
        payload={"report_id": "session_base_outbox_report", "total_score": 80},
    )

    store.create_base_report(report)
    assert store.list_pending_outbox() == []

    backfilled = ReportStore(database_path).create_base_report(report, outbox_event=event)
    replayed = store.create_base_report(report, outbox_event=event)

    assert backfilled.revision == 1
    assert replayed.revision == 1
    pending_items = store.list_pending_outbox()
    assert len(pending_items) == 1
    assert pending_items[0].event_key == ReportStore.build_base_outbox_event_key(
        session_id="session_base_outbox",
        event_type="report_generated",
    )
    assert pending_items[0].report_revision == 1
    assert pending_items[0].payload == event.payload
    with sqlite3.connect(database_path) as connection:
        outbox_count = connection.execute("SELECT COUNT(*) FROM report_outbox").fetchone()[0]
    assert outbox_count == 1


def test_base_report_and_outbox_insert_roll_back_together(tmp_path) -> None:
    database_path = tmp_path / "reports.sqlite3"
    store = ReportStore(database_path)
    store.list_pending_outbox()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_base_report_outbox
            BEFORE INSERT ON report_outbox
            BEGIN
                SELECT RAISE(ABORT, 'base outbox unavailable');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="base outbox unavailable"):
        store.create_base_report(
            _report("session_base_atomic", status="generation_pending"),
            outbox_event=ReportOutboxEvent(
                case_id="appendicitis_001",
                student_id="student_base_atomic",
                event_type="report_generated",
                payload={"report_id": "session_base_atomic_report"},
            ),
        )

    assert store.get_report("session_base_atomic") is None
    assert store.list_pending_outbox() == []


def test_legacy_reports_table_is_migrated_without_changing_business_json(tmp_path) -> None:
    database_path = tmp_path / "reports.sqlite3"
    legacy_report = _report("session_legacy", status="generation_pending", total_score=64)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE reports (
                session_id TEXT PRIMARY KEY,
                report_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO reports (session_id, report_json) VALUES (?, ?)",
            (
                legacy_report["session_id"],
                json.dumps(legacy_report, ensure_ascii=False),
            ),
        )

    store = ReportStore(database_path)
    stored = store.get_stored_report("session_legacy")

    assert stored is not None
    assert stored.payload == legacy_report
    assert stored.revision == 1
    assert stored.enrichment_status == "pending"
    assert stored.enrichment_retry_count == 0
    assert store.get_report("session_legacy") == legacy_report
    assert store.list_reports() == [legacy_report]

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(reports)").fetchall()
        }
        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert {"revision", "enrichment_status", "enrichment_retry_count"} <= columns
    assert schema_version == 2


def test_only_one_store_claims_enrichment_and_stale_pending_cannot_replace_approved(tmp_path) -> None:
    database_path = tmp_path / "reports.sqlite3"
    first_store = ReportStore(database_path)
    second_store = ReportStore(database_path)
    pending_report = _report("session_race", status="generation_pending", total_score=77)
    first_store.create_base_report(pending_report)
    start = Barrier(3)
    claimed_at = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)

    def claim(store: ReportStore):
        start.wait(timeout=5)
        return store.claim_report_enrichment(
            "session_race",
            lease_seconds=60,
            now=claimed_at,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(claim, first_store)
        second_future = executor.submit(claim, second_store)
        start.wait(timeout=5)
        claims = [first_future.result(timeout=5), second_future.result(timeout=5)]

    successful_claims = [claim for claim in claims if claim is not None]
    assert len(successful_claims) == 1
    winner = successful_claims[0]
    assert winner.expected_revision == 2
    assert winner.retry_count == 0

    approved_report = _report("session_race", status="approved", total_score=77)
    completed = first_store.complete_report_enrichment(
        "session_race",
        approved_report,
        expected_revision=winner.expected_revision,
        claim_token=winner.claim_token,
        case_id="appendicitis_001",
        student_id="student_race",
        event_type="report_generated",
        event_payload={"status": "approved"},
        now=claimed_at + timedelta(seconds=1),
    )
    assert completed.revision == 3
    assert completed.enrichment_status == "completed"

    second_store.save_report(pending_report)

    after_stale_save = first_store.get_stored_report("session_race")
    assert after_stale_save is not None
    assert after_stale_save.revision == 3
    assert after_stale_save.payload["personal_skill_candidate"]["status"] == "approved"


def test_expired_lease_can_be_reclaimed_and_old_claim_cannot_complete(tmp_path) -> None:
    store = ReportStore(tmp_path / "reports.sqlite3")
    store.create_base_report(_report("session_lease", status="generation_pending"))
    claimed_at = datetime(2026, 7, 28, 11, 0, tzinfo=UTC)

    first_claim = store.claim_report_enrichment(
        "session_lease",
        lease_seconds=60,
        now=claimed_at,
    )
    assert first_claim is not None
    assert first_claim.retry_count == 0
    assert store.claim_report_enrichment(
        "session_lease",
        lease_seconds=60,
        now=claimed_at + timedelta(seconds=59),
    ) is None

    second_claim = ReportStore(store.database_path).claim_report_enrichment(
        "session_lease",
        lease_seconds=60,
        now=claimed_at + timedelta(seconds=60),
    )

    assert second_claim is not None
    assert second_claim.claim_token != first_claim.claim_token
    assert second_claim.expected_revision == first_claim.expected_revision + 1
    assert second_claim.retry_count == 1

    with pytest.raises(ReportClaimLostError) as exc_info:
        store.complete_report_enrichment(
            "session_lease",
            _report("session_lease", status="approved"),
            expected_revision=first_claim.expected_revision,
            claim_token=first_claim.claim_token,
            case_id="appendicitis_001",
            student_id="student_lease",
            event_type="report_generated",
            event_payload={"status": "approved"},
            now=claimed_at + timedelta(seconds=61),
        )

    assert exc_info.value.expected_revision == first_claim.expected_revision
    assert exc_info.value.current_revision == second_claim.expected_revision


def test_failed_claim_can_retry_and_stale_revision_cannot_fail_new_claim(tmp_path) -> None:
    store = ReportStore(tmp_path / "reports.sqlite3")
    store.create_base_report(_report("session_retry", status="generation_pending"))
    claimed_at = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    first_claim = store.claim_report_enrichment("session_retry", now=claimed_at)
    assert first_claim is not None

    failed = store.fail_report_enrichment(
        "session_retry",
        expected_revision=first_claim.expected_revision,
        claim_token=first_claim.claim_token,
        error_message="provider unavailable",
        case_id="appendicitis_001",
        student_id="student_retry",
        event_type="report_enrichment_failed",
        event_payload={"error_type": "provider_unavailable"},
        failed_report=_report("session_retry", status="generation_failed"),
        now=claimed_at + timedelta(seconds=1),
    )
    assert failed.revision == first_claim.expected_revision + 1
    assert failed.enrichment_status == "failed"
    assert failed.enrichment_last_error == "provider unavailable"

    retry_claim = store.claim_report_enrichment(
        "session_retry",
        now=claimed_at + timedelta(seconds=2),
    )
    assert retry_claim is not None
    assert retry_claim.retry_count == 1

    with pytest.raises(ReportClaimLostError):
        store.fail_report_enrichment(
            "session_retry",
            expected_revision=first_claim.expected_revision,
            claim_token=first_claim.claim_token,
            error_message="late failure",
            case_id="appendicitis_001",
            student_id="student_retry",
            event_type="report_enrichment_failed",
            event_payload={"error_type": "late_failure"},
            now=claimed_at + timedelta(seconds=3),
        )

    current = store.get_stored_report("session_retry")
    assert current is not None
    assert current.revision == retry_claim.expected_revision
    assert current.enrichment_status == "claimed"
    assert current.enrichment_claim_token == retry_claim.claim_token
    failure_events = store.list_pending_outbox()
    assert len(failure_events) == 1
    assert failure_events[0].event_type == "report_enrichment_failed"
    assert failure_events[0].payload == {"error_type": "provider_unavailable"}


def test_report_completion_and_outbox_upsert_are_one_transaction(tmp_path) -> None:
    database_path = tmp_path / "reports.sqlite3"
    store = ReportStore(database_path)
    pending_report = _report("session_atomic", status="generation_pending")
    store.create_base_report(pending_report)
    claim = store.claim_report_enrichment("session_atomic")
    assert claim is not None

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_report_outbox
            BEFORE INSERT ON report_outbox
            BEGIN
                SELECT RAISE(ABORT, 'outbox unavailable');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="outbox unavailable"):
        store.complete_report_enrichment(
            "session_atomic",
            _report("session_atomic", status="approved"),
            expected_revision=claim.expected_revision,
            claim_token=claim.claim_token,
            case_id="appendicitis_001",
            student_id="student_atomic",
            event_type="report_generated",
            event_payload={"status": "approved"},
        )

    after_failure = store.get_stored_report("session_atomic")
    assert after_failure is not None
    assert after_failure.revision == claim.expected_revision
    assert after_failure.enrichment_status == "claimed"
    assert after_failure.payload == pending_report
    assert store.list_pending_outbox() == []


def test_completed_report_creates_stable_pending_outbox_and_ack_is_idempotent(tmp_path) -> None:
    store = ReportStore(tmp_path / "reports.sqlite3")
    store.create_base_report(_report("session_outbox", status="generation_pending"))
    claim = store.claim_report_enrichment("session_outbox")
    assert claim is not None
    event_payload = {
        "score_groups": {
            "clinical": {"score": 60, "max_score": 70},
            "humanistic": {"score": 24, "max_score": 30},
        }
    }

    completed = store.complete_report_enrichment(
        "session_outbox",
        _report("session_outbox", status="approved", total_score=84),
        expected_revision=claim.expected_revision,
        claim_token=claim.claim_token,
        case_id="appendicitis_001",
        student_id="student_outbox",
        event_type="report_generated",
        event_payload=event_payload,
    )

    pending_items = ReportStore(store.database_path).list_pending_outbox()
    assert len(pending_items) == 1
    item = pending_items[0]
    assert item.event_key == ReportStore.build_outbox_event_key(
        session_id="session_outbox",
        event_type="report_generated",
        report_revision=completed.revision,
    )
    assert item.session_id == "session_outbox"
    assert item.case_id == "appendicitis_001"
    assert item.student_id == "student_outbox"
    assert item.report_revision == completed.revision
    assert item.payload == event_payload

    assert store.acknowledge_outbox(item.event_key)
    assert not store.acknowledge_outbox(item.event_key)
    assert store.list_pending_outbox() == []


def _report(
    session_id: str,
    *,
    status: str,
    total_score: int = 80,
) -> dict[str, object]:
    return {
        "report_id": f"{session_id}_report",
        "session_id": session_id,
        "case_id": "appendicitis_001",
        "total_score": total_score,
        "personal_skill_candidate": {
            "status": status,
            "scope": "personal",
        },
    }
