import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pytest

from app.services.osce_session_service import OsceSession
from app.services.osce_session_store import (
    DATABASE_SCHEMA_VERSION,
    OsceSessionStore,
    SessionAlreadyExistsError,
    SessionDeletionRecord,
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
    )
    assert store.is_session_deleted("legacy-deleted") is True
    assert store.begin_session_deletion("legacy-deleted", "student-a") is None
    with sqlite3.connect(database_path) as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 3


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
