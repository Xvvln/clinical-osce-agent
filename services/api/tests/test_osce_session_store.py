import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pytest

from app.services.osce_session_service import OsceSession
from app.services.osce_session_store import (
    DATABASE_SCHEMA_VERSION,
    SESSION_DELETION_CLEANUP_VERSION,
    OsceSessionStore,
    SessionAlreadyExistsError,
    SessionDeletionRecord,
    SessionDerivedReferenceOwnershipError,
    SessionDeletedError,
    SessionNotFoundError,
    SessionWriteConflictError,
)


def _session(session_id: str = "session-a") -> OsceSession:
    return OsceSession(
        session_id=session_id,
        student_id="student-a",
        case_id="appendicitis_001",
        stage="history",
    )


def _create_legacy_database(database_path: Path, session: OsceSession) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE osce_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                session_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO osce_sessions (
                session_id,
                user_id,
                case_id,
                stage,
                session_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.student_id,
                session.case_id,
                session.stage,
                json.dumps(asdict(session), ensure_ascii=False),
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )


def _create_v2_tombstone_database(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE osce_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                session_json TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE osce_session_tombstones (
                session_id TEXT PRIMARY KEY,
                deleted_revision INTEGER NOT NULL,
                deleted_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO osce_session_tombstones (
                session_id,
                deleted_revision,
                deleted_at
            )
            VALUES (?, ?, ?)
            """,
            ("legacy-deleted", 7, "2026-01-02T00:00:00+00:00"),
        )
        connection.execute("PRAGMA user_version = 2")


def test_legacy_schema_migrates_once_under_concurrent_initialization(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite3"
    legacy_session = _session("legacy-session")
    _create_legacy_database(database_path, legacy_session)
    first_store = OsceSessionStore(database_path)
    second_store = OsceSessionStore(database_path)
    stores = [first_store, second_store, first_store, second_store]

    with ThreadPoolExecutor(max_workers=4) as executor:
        records = list(
            executor.map(
                lambda store: store.get_session(legacy_session.session_id),
                stores,
            )
        )

    assert all(record is not None and record.revision == 1 for record in records)
    assert all(record is not None and record.payload == asdict(legacy_session) for record in records)
    with sqlite3.connect(database_path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(osce_sessions)").fetchall()
        }
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        tombstone_table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'osce_session_tombstones'
            """
        ).fetchone()
        tombstone_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(osce_session_tombstones)"
            ).fetchall()
        }

    assert "revision" in columns
    assert schema_version == DATABASE_SCHEMA_VERSION
    assert tombstone_table == ("osce_session_tombstones",)
    assert {
        "session_id",
        "user_id",
        "case_id",
        "deleted_revision",
        "deleted_at",
        "cleanup_status",
        "cleanup_completed_at",
        "cleanup_version",
    } <= tombstone_columns


def test_v2_tombstones_migrate_as_completed_without_inventing_ownership(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite3"
    _create_v2_tombstone_database(database_path)
    store = OsceSessionStore(database_path)

    assert store.get_session_deletion("legacy-deleted") == SessionDeletionRecord(
        session_id="legacy-deleted",
        user_id="",
        case_id="",
        deleted_revision=7,
        deleted_at="2026-01-02T00:00:00+00:00",
        cleanup_status="completed",
        cleanup_completed_at="2026-01-02T00:00:00+00:00",
        cleanup_version=1,
    )
    assert store.is_session_deleted("legacy-deleted") is True
    assert store.begin_session_deletion("legacy-deleted", "student-a") is None
    assert store.list_ownerless_legacy_deletions() == [
        store.get_session_deletion("legacy-deleted")
    ]
    with sqlite3.connect(database_path) as connection:
        assert (
            int(connection.execute("PRAGMA user_version").fetchone()[0])
            == DATABASE_SCHEMA_VERSION
        )


def test_legacy_tombstone_adoption_is_atomic_and_becomes_pending(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite3"
    _create_v2_tombstone_database(database_path)
    store = OsceSessionStore(database_path)

    adopted = store.adopt_legacy_session_deletion(
        "legacy-deleted",
        user_id="student-a",
        case_id="appendicitis_001",
    )

    assert adopted == SessionDeletionRecord(
        session_id="legacy-deleted",
        user_id="student-a",
        case_id="appendicitis_001",
        deleted_revision=7,
        deleted_at="2026-01-02T00:00:00+00:00",
        cleanup_status="pending",
        cleanup_completed_at=None,
        cleanup_version=SESSION_DELETION_CLEANUP_VERSION,
    )
    assert store.list_pending_deletions() == [adopted]
    assert (
        store.adopt_legacy_session_deletion(
            "legacy-deleted",
            user_id="student-b",
            case_id="other-case",
        )
        is None
    )
    assert store.get_session_deletion("legacy-deleted") == adopted
    assert store.list_ownerless_legacy_deletions() == []

    completed = store.mark_session_deletion_complete("legacy-deleted")
    assert completed is not None
    assert completed.cleanup_status == "completed"
    assert store.list_pending_deletions() == []


def test_pending_deletion_listing_is_bounded_and_ordered(tmp_path: Path) -> None:
    store = OsceSessionStore(tmp_path / "sessions.sqlite3")
    first = _session("session-first")
    second = _session("session-second")
    store.create_session(first)
    store.create_session(second)
    first_deletion = store.begin_session_deletion(
        first.session_id,
        first.student_id,
    )
    second_deletion = store.begin_session_deletion(
        second.session_id,
        second.student_id,
    )

    assert first_deletion is not None
    assert second_deletion is not None
    assert len(store.list_pending_deletions(limit=1)) == 1
    assert {
        deletion.session_id for deletion in store.list_pending_deletions()
    } == {first.session_id, second.session_id}
    assert store.list_pending_deletions(limit=0) == []


def test_revision_is_internal_stable_on_reads_and_monotonic_on_updates(tmp_path: Path) -> None:
    store = OsceSessionStore(tmp_path / "sessions.sqlite3")
    session = _session()

    assert store.create_session(session) == 1
    first_record = store.get_session(session.session_id)
    assert first_record is not None
    assert first_record.revision == 1
    assert "revision" not in first_record.payload

    assert store.get_session_payload(session.session_id) == first_record.payload
    assert store.list_user_session_summaries(session.student_id)
    assert store.list_session_summaries()
    unchanged_record = store.get_session(session.session_id)
    assert unchanged_record is not None
    assert unchanged_record.revision == 1

    session.student_hypotheses.append("急性阑尾炎")
    assert store.update_session(session, expected_revision=1) == 2
    second_record = store.get_session(session.session_id)
    assert second_record is not None
    assert second_record.revision == 2
    assert second_record.payload["student_hypotheses"] == ["急性阑尾炎"]
    assert "revision" not in second_record.payload


def test_create_rejects_an_existing_active_session_id(tmp_path: Path) -> None:
    store = OsceSessionStore(tmp_path / "sessions.sqlite3")
    session = _session()
    store.create_session(session)

    with pytest.raises(SessionAlreadyExistsError):
        store.create_session(_session())

    record = store.get_session(session.session_id)
    assert record is not None
    assert record.revision == 1


def test_stale_revision_cannot_overwrite_a_newer_worker(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite3"
    first_store = OsceSessionStore(database_path)
    second_store = OsceSessionStore(database_path)
    first_store.create_session(_session())
    first_record = first_store.get_session("session-a")
    second_record = second_store.get_session("session-a")
    assert first_record is not None
    assert second_record is not None
    first_worker_session = OsceSession(**first_record.payload)
    second_worker_session = OsceSession(**second_record.payload)

    first_worker_session.student_hypotheses.append("worker-a")
    assert first_store.update_session(
        first_worker_session,
        expected_revision=first_record.revision,
    ) == 2
    second_worker_session.requested_exams.append("worker-b")

    with pytest.raises(SessionWriteConflictError) as exc_info:
        second_store.update_session(
            second_worker_session,
            expected_revision=second_record.revision,
        )

    assert exc_info.value.expected_revision == 1
    assert exc_info.value.current_revision == 2
    persisted = first_store.get_session("session-a")
    assert persisted is not None
    assert persisted.payload["student_hypotheses"] == ["worker-a"]
    assert persisted.payload["requested_exams"] == []


def test_tombstone_blocks_stale_save_recreation_and_summaries(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite3"
    first_store = OsceSessionStore(database_path)
    second_store = OsceSessionStore(database_path)
    session = _session()
    first_store.create_session(session)
    stale_record = second_store.get_session(session.session_id)
    assert stale_record is not None
    stale_session = OsceSession(**stale_record.payload)

    assert first_store.delete_session(session.session_id) is True
    assert first_store.get_session(session.session_id) is None
    assert first_store.get_session_payload(session.session_id) is None
    assert first_store.list_user_session_summaries(session.student_id) == []
    assert first_store.list_session_summaries() == []
    assert second_store.delete_session(session.session_id) is False

    stale_session.messages.append({"role": "student", "content": "late"})
    with pytest.raises(SessionDeletedError):
        second_store.update_session(
            stale_session,
            expected_revision=stale_record.revision,
        )
    with pytest.raises(SessionAlreadyExistsError):
        second_store.create_session(_session())

    with sqlite3.connect(database_path) as connection:
        active_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM osce_sessions WHERE session_id = ?",
                (session.session_id,),
            ).fetchone()[0]
        )
        tombstone_revision = int(
            connection.execute(
                """
                SELECT deleted_revision
                FROM osce_session_tombstones
                WHERE session_id = ?
                """,
                (session.session_id,),
            ).fetchone()[0]
        )

    assert active_count == 0
    assert tombstone_revision == 2
    deletion = first_store.get_session_deletion(session.session_id)
    assert deletion is not None
    assert deletion.user_id == session.student_id
    assert deletion.case_id == session.case_id
    assert deletion.cleanup_status == "completed"
    assert deletion.cleanup_completed_at == deletion.deleted_at


def test_begin_session_deletion_is_owner_scoped_and_idempotent(tmp_path: Path) -> None:
    store = OsceSessionStore(tmp_path / "sessions.sqlite3")
    session = _session()
    store.create_session(session)

    assert store.begin_session_deletion(session.session_id, "other-student") is None
    assert store.get_session(session.session_id) is not None
    assert store.is_session_deleted(session.session_id) is False

    deletion = store.begin_session_deletion(session.session_id, session.student_id)
    assert deletion is not None
    assert deletion.session_id == session.session_id
    assert deletion.user_id == session.student_id
    assert deletion.case_id == session.case_id
    assert deletion.deleted_revision == 2
    assert deletion.cleanup_status == "pending"
    assert deletion.cleanup_completed_at is None
    assert store.get_session(session.session_id) is None
    assert store.is_session_deleted(session.session_id) is True

    assert store.begin_session_deletion(session.session_id, "other-student") is None
    assert (
        store.begin_session_deletion(session.session_id, session.student_id)
        == deletion
    )


def test_session_deletion_transitions_from_pending_to_completed_once(
    tmp_path: Path,
) -> None:
    store = OsceSessionStore(tmp_path / "sessions.sqlite3")
    session = _session()
    store.create_session(session)
    pending = store.begin_session_deletion(session.session_id, session.student_id)
    assert pending is not None

    completed = store.mark_session_deletion_complete(session.session_id)
    assert completed is not None
    assert completed.cleanup_status == "completed"
    assert completed.cleanup_completed_at is not None
    assert completed.deleted_at == pending.deleted_at
    assert completed.deleted_revision == pending.deleted_revision
    assert store.get_session_deletion(session.session_id) == completed
    assert store.mark_session_deletion_complete(session.session_id) == completed
    assert store.mark_session_deletion_complete("missing") is None


def test_missing_session_update_is_typed_and_delete_keeps_boolean_contract(tmp_path: Path) -> None:
    store = OsceSessionStore(tmp_path / "sessions.sqlite3")
    missing_session = _session("missing")

    with pytest.raises(SessionNotFoundError):
        store.update_session(missing_session, expected_revision=1)
    assert store.delete_session(missing_session.session_id) is False


def test_deleted_skill_source_scrubs_dependent_sessions_and_blocks_stale_reintroduction(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite3"
    store = OsceSessionStore(database_path)
    source_session_id = "source-session"
    personal_skill_id = f"skill_personal_{source_session_id}"
    personal_candidate_id = f"personal_skill_candidate_{source_session_id}"
    source_report_id = f"{source_session_id}_report"
    affected_global_skill_id = "skill_global_affected"
    follow_up = _session("follow-up")
    follow_up.active_skill_context = {
        "skill_index": [
            {"skill_id": personal_skill_id, "title": "deleted"},
            {"skill_id": affected_global_skill_id, "title": "global deleted"},
            {"skill_id": "skill_keep", "title": "keep"},
        ],
        "selected_skills": [
            {
                "skill_id": personal_skill_id,
                "title": "deleted",
                "suggested_strategy": "deleted strategy",
            },
            {
                "skill_id": affected_global_skill_id,
                "title": "global deleted",
                "suggested_strategy": "global deleted strategy",
            },
            {
                "skill_id": "skill_keep",
                "title": "keep",
                "suggested_strategy": "keep strategy",
            },
        ],
        "skipped_reasons": [
            {"skill_id": personal_skill_id, "reason": "not selected"},
        ],
    }
    follow_up.evolution_candidates = [
        "deleted：deleted strategy",
        "global deleted：global deleted strategy",
        "keep：keep strategy",
    ]
    follow_up.agent_turn_memory = [
        {
            "selected_skill_ids": [
                personal_skill_id,
                affected_global_skill_id,
                "skill_keep",
            ],
        }
    ]
    follow_up.pedagogy_state = {
        "skill_context_ids": [
            personal_skill_id,
            affected_global_skill_id,
        ],
        "coaching_mode": "skill_guided",
    }
    follow_up.agent_decision_trace = [
        {
            "skill_context_ids": [
                personal_skill_id,
                affected_global_skill_id,
            ],
            "coaching_mode": "skill_guided",
        }
    ]
    store.create_session(follow_up)
    stale_record = store.get_session(follow_up.session_id)
    assert stale_record is not None

    assert store.delete_skill_source_references(
        source_session_id=source_session_id,
        owner_user_id=follow_up.student_id,
        personal_skill_id=personal_skill_id,
        personal_candidate_id=personal_candidate_id,
        source_report_id=source_report_id,
        affected_global_skill_ids=[affected_global_skill_id],
    ) == [follow_up.session_id]

    scrubbed = store.get_session(follow_up.session_id)
    assert scrubbed is not None
    assert scrubbed.revision == 2
    assert personal_skill_id not in str(scrubbed.payload)
    assert affected_global_skill_id not in str(scrubbed.payload)
    assert scrubbed.payload["evolution_candidates"] == [
        "keep：keep strategy"
    ]
    assert scrubbed.payload["pedagogy_state"]["skill_context_ids"] == []
    assert scrubbed.payload["pedagogy_state"]["coaching_mode"] == "socratic"
    assert scrubbed.payload["agent_turn_memory"] == []
    assert scrubbed.payload["agent_decision_trace"] == []
    assert OsceSessionStore(database_path).delete_skill_source_references(
        source_session_id=source_session_id,
        owner_user_id=follow_up.student_id,
        personal_skill_id=personal_skill_id,
        personal_candidate_id=personal_candidate_id,
        source_report_id=source_report_id,
        affected_global_skill_ids=[affected_global_skill_id],
    ) == [follow_up.session_id]

    stale_session = OsceSession(**stale_record.payload)
    with pytest.raises(SessionWriteConflictError):
        store.update_session(
            stale_session,
            expected_revision=stale_record.revision,
        )

    latest_session = OsceSession(**scrubbed.payload)
    latest_session.active_skill_context["selected_skills"].append(
        {
            "skill_id": personal_skill_id,
            "title": "late",
            "suggested_strategy": "late strategy",
        }
    )
    assert store.update_session(
        latest_session,
        expected_revision=scrubbed.revision,
    ) == 3
    persisted_after_late_update = store.get_session(follow_up.session_id)
    assert persisted_after_late_update is not None
    assert personal_skill_id not in str(persisted_after_late_update.payload)

    late_created = _session("late-created")
    late_created.active_skill_context = {
        "skill_index": [{"skill_id": personal_skill_id}],
        "selected_skills": [
            {
                "skill_id": personal_skill_id,
                "title": "late",
                "suggested_strategy": "late strategy",
            }
        ],
        "skipped_reasons": [],
    }
    late_created.evolution_candidates = ["late：late strategy"]
    store.create_session(late_created)
    persisted_late_created = store.get_session(late_created.session_id)
    assert persisted_late_created is not None
    assert personal_skill_id not in str(persisted_late_created.payload)
    assert persisted_late_created.payload["evolution_candidates"] == []

    wrong_owner_late_create = _session("wrong-owner-late-create")
    wrong_owner_late_create.student_id = "student-b"
    wrong_owner_late_create.active_skill_context = {
        "skill_index": [{"skill_id": personal_skill_id}],
        "selected_skills": [{"skill_id": personal_skill_id}],
        "skipped_reasons": [],
    }
    with pytest.raises(SessionDerivedReferenceOwnershipError):
        store.create_session(wrong_owner_late_create)
    assert store.get_session(wrong_owner_late_create.session_id) is None

    global_late_create = _session("global-late-create")
    global_late_create.student_id = "student-b"
    global_late_create.active_skill_context = {
        "skill_index": [{"skill_id": affected_global_skill_id}],
        "selected_skills": [
            {
                "skill_id": affected_global_skill_id,
                "title": "late global",
                "suggested_strategy": "late strategy",
            }
        ],
        "skipped_reasons": [],
    }
    global_late_create.evolution_candidates = ["late global：late strategy"]
    store.create_session(global_late_create)
    persisted_global_late_create = store.get_session(
        global_late_create.session_id
    )
    assert persisted_global_late_create is not None
    assert affected_global_skill_id not in str(
        persisted_global_late_create.payload
    )


def test_deleted_skill_source_owner_conflict_preserves_other_users_session(
    tmp_path: Path,
) -> None:
    store = OsceSessionStore(tmp_path / "sessions.sqlite3")
    source_session_id = "source-conflict"
    personal_skill_id = f"skill_personal_{source_session_id}"
    other_owner = _session("other-owner-follow-up")
    other_owner.student_id = "student-b"
    other_owner.active_skill_context = {
        "skill_index": [{"skill_id": personal_skill_id}],
        "selected_skills": [{"skill_id": personal_skill_id}],
        "skipped_reasons": [],
    }
    store.create_session(other_owner)

    with pytest.raises(SessionDerivedReferenceOwnershipError):
        store.delete_skill_source_references(
            source_session_id=source_session_id,
            owner_user_id="student-a",
            personal_skill_id=personal_skill_id,
            personal_candidate_id=(
                f"personal_skill_candidate_{source_session_id}"
            ),
            source_report_id=f"{source_session_id}_report",
        )

    preserved = store.get_session(other_owner.session_id)
    assert preserved is not None
    assert personal_skill_id in str(preserved.payload)
