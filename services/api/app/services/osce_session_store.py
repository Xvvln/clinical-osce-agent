from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.osce_session_service import OsceSession

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "osce_sessions.sqlite3"
DATABASE_SCHEMA_VERSION = 6
DATABASE_BUSY_TIMEOUT_MILLISECONDS = 10_000
SESSION_DELETION_PENDING = "pending"
SESSION_DELETION_COMPLETED = "completed"
SESSION_DELETION_CLEANUP_VERSION = 3


class SessionPersistenceError(RuntimeError):
    def __init__(self, session_id: str) -> None:
        super().__init__(session_id)
        self.session_id = session_id


class SessionAlreadyExistsError(SessionPersistenceError):
    pass


class SessionCreatePreparationConflictError(SessionPersistenceError):
    pass


class SessionWriteConflictError(SessionPersistenceError):
    def __init__(self, session_id: str, *, expected_revision: int, current_revision: int) -> None:
        super().__init__(session_id)
        self.expected_revision = expected_revision
        self.current_revision = current_revision


class SessionDeletedError(SessionPersistenceError):
    pass


class SessionNotFoundError(SessionPersistenceError):
    pass


class SessionDerivedReferenceOwnershipError(SessionPersistenceError):
    pass


@dataclass(frozen=True)
class StoredSession:
    payload: dict[str, object]
    revision: int


@dataclass(frozen=True)
class PreparedSession:
    payload: dict[str, object]
    deleted_skill_sources_version: int


@dataclass(frozen=True)
class SessionOutboxEvent:
    event_type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class SessionOutboxItem:
    event_key: str
    session_id: str
    session_revision: int
    event_index: int
    case_id: str
    student_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class SessionDeletionRecord:
    session_id: str
    user_id: str
    case_id: str
    deleted_revision: int
    deleted_at: str
    cleanup_status: str
    cleanup_completed_at: str | None
    cleanup_version: int


class OsceSessionStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path
        self._initialization_lock = Lock()
        self._initialized = False

    def prepare_session_for_create(
        self,
        session: OsceSession,
    ) -> PreparedSession:
        """Return a scrubbed snapshot plus the append-only deletion-ledger version."""

        self._initialize()
        payload = asdict(session)
        with self._connect() as connection:
            connection.execute("BEGIN")
            deleted_skill_sources_version = (
                self._deleted_skill_sources_version(connection)
            )
            payload = _scrub_payload_for_deleted_skill_sources(
                connection,
                payload,
                user_id=session.student_id,
            )
        return PreparedSession(
            payload=payload,
            deleted_skill_sources_version=deleted_skill_sources_version,
        )

    def create_session(
        self,
        session: OsceSession,
        *,
        outbox_events: Sequence[SessionOutboxEvent] = (),
        expected_deleted_skill_sources_version: int | None = None,
    ) -> int:
        self._initialize()
        now = datetime.now(UTC).isoformat()
        payload = asdict(session)
        serialized_events = _serialize_outbox_events(outbox_events)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if (
                expected_deleted_skill_sources_version is not None
                and self._deleted_skill_sources_version(connection)
                != expected_deleted_skill_sources_version
            ):
                raise SessionCreatePreparationConflictError(
                    session.session_id
                )
            if self._tombstone_revision(connection, session.session_id) is not None:
                raise SessionAlreadyExistsError(session.session_id)
            if expected_deleted_skill_sources_version is None:
                payload = _scrub_payload_for_deleted_skill_sources(
                    connection,
                    payload,
                    user_id=session.student_id,
                )
            try:
                connection.execute(
                    """
                    INSERT INTO osce_sessions (
                        session_id,
                        user_id,
                        case_id,
                        stage,
                        session_json,
                        revision,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        session.session_id,
                        session.student_id,
                        session.case_id,
                        session.stage,
                        json.dumps(payload, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise SessionAlreadyExistsError(session.session_id) from exc
            self._insert_event_outbox(
                connection,
                session_id=session.session_id,
                session_revision=1,
                case_id=session.case_id,
                student_id=session.student_id,
                serialized_events=serialized_events,
                created_at=now,
            )
        return 1

    def update_session(
        self,
        session: OsceSession,
        *,
        expected_revision: int,
        outbox_events: Sequence[SessionOutboxEvent] = (),
    ) -> int:
        return self.update_session_and_get(
            session,
            expected_revision=expected_revision,
            outbox_events=outbox_events,
        ).revision

    def update_session_and_get(
        self,
        session: OsceSession,
        *,
        expected_revision: int,
        outbox_events: Sequence[SessionOutboxEvent] = (),
    ) -> StoredSession:
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        self._initialize()
        now = datetime.now(UTC).isoformat()
        payload = asdict(session)
        serialized_events = _serialize_outbox_events(outbox_events)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            payload = _scrub_payload_for_deleted_skill_sources(
                connection,
                payload,
                user_id=session.student_id,
            )
            cursor = connection.execute(
                """
                UPDATE osce_sessions
                SET
                    user_id = ?,
                    case_id = ?,
                    stage = ?,
                    session_json = ?,
                    revision = revision + 1,
                    updated_at = ?
                WHERE session_id = ?
                  AND revision = ?
                """,
                (
                    session.student_id,
                    session.case_id,
                    session.stage,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    session.session_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount == 1:
                new_revision = expected_revision + 1
                self._insert_event_outbox(
                    connection,
                    session_id=session.session_id,
                    session_revision=new_revision,
                    case_id=session.case_id,
                    student_id=session.student_id,
                    serialized_events=serialized_events,
                    created_at=now,
                )
                row = connection.execute(
                    """
                    SELECT session_json, revision
                    FROM osce_sessions
                    WHERE session_id = ?
                    """,
                    (session.session_id,),
                ).fetchone()
                if row is None:
                    raise SessionNotFoundError(session.session_id)
                stored_payload = json.loads(row[0])
                if not isinstance(stored_payload, dict):
                    raise ValueError(
                        f"invalid persisted session payload: {session.session_id}"
                    )
                return StoredSession(
                    payload=stored_payload,
                    revision=int(row[1]),
                )
            deleted_revision = self._tombstone_revision(connection, session.session_id)
            if deleted_revision is not None:
                raise SessionDeletedError(session.session_id)
            row = connection.execute(
                "SELECT revision FROM osce_sessions WHERE session_id = ?",
                (session.session_id,),
            ).fetchone()
            if row is None:
                raise SessionNotFoundError(session.session_id)
            raise SessionWriteConflictError(
                session.session_id,
                expected_revision=expected_revision,
                current_revision=int(row[0]),
            )

    def list_pending_event_outbox(
        self,
        *,
        limit: int = 100,
        session_id: str | None = None,
    ) -> list[SessionOutboxItem]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        self._initialize()
        where_clause = "" if session_id is None else "WHERE session_id = ?"
        parameters: tuple[object, ...] = (
            (limit,)
            if session_id is None
            else (session_id, limit)
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    event_key,
                    session_id,
                    session_revision,
                    event_index,
                    case_id,
                    student_id,
                    event_type,
                    payload_json,
                    created_at
                FROM osce_session_event_outbox
                {where_clause}
                ORDER BY id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [_session_outbox_item_from_row(row) for row in rows]

    def acknowledge_event_outbox(self, event_key: str) -> bool:
        if not event_key:
            raise ValueError("event_key is required")
        self._initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM osce_session_event_outbox WHERE event_key = ?",
                (event_key,),
            )
        return cursor.rowcount == 1

    def deliver_next_event_outbox(
        self,
        deliver: Callable[[SessionOutboxItem], None],
        *,
        session_id: str | None = None,
    ) -> bool:
        """Deliver and acknowledge one FIFO item while fencing session deletion."""

        self._initialize()
        where_clause = "" if session_id is None else "WHERE session_id = ?"
        parameters: tuple[object, ...] = (
            () if session_id is None else (session_id,)
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""
                SELECT
                    event_key,
                    session_id,
                    session_revision,
                    event_index,
                    case_id,
                    student_id,
                    event_type,
                    payload_json,
                    created_at
                FROM osce_session_event_outbox
                {where_clause}
                ORDER BY id
                LIMIT 1
                """,
                parameters,
            ).fetchone()
            if row is None:
                return False
            item = _session_outbox_item_from_row(row)
            if self._tombstone_revision(connection, item.session_id) is None:
                deliver(item)
            cursor = connection.execute(
                """
                DELETE FROM osce_session_event_outbox
                WHERE event_key = ?
                """,
                (item.event_key,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"session outbox acknowledgement lost: {item.event_key}"
                )
        return True

    def get_session(self, session_id: str) -> StoredSession | None:
        self._initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT session_json, revision FROM osce_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        if not isinstance(payload, dict):
            raise ValueError(f"invalid persisted session payload: {session_id}")
        return StoredSession(payload=payload, revision=int(row[1]))

    def get_session_payload(self, session_id: str) -> dict[str, object] | None:
        stored_session = self.get_session(session_id)
        return None if stored_session is None else stored_session.payload

    def list_user_session_summaries(self, user_id: str) -> list[dict[str, object]]:
        self._initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, case_id, stage, created_at, updated_at, session_json
                FROM osce_sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "session_id": row[0],
                "case_id": row[1],
                "stage": row[2],
                "created_at": row[3],
                "updated_at": row[4],
                **_session_completion_summary(row[5], row[2], row[1]),
            }
            for row in rows
        ]

    def list_session_summaries(self) -> list[dict[str, object]]:
        self._initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, user_id, case_id, stage, created_at, updated_at, session_json
                FROM osce_sessions
                ORDER BY updated_at DESC
                """,
            ).fetchall()
        return [
            {
                "session_id": row[0],
                "student_id": row[1],
                "case_id": row[2],
                "stage": row[3],
                "created_at": row[4],
                "updated_at": row[5],
                **_session_completion_summary(row[6], row[3], row[2]),
            }
            for row in rows
        ]

    def delete_session(self, session_id: str) -> bool:
        self._initialize()
        deleted_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT revision, user_id, case_id
                FROM osce_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    "DELETE FROM osce_session_event_outbox WHERE session_id = ?",
                    (session_id,),
                )
                return False
            deleted_revision = int(row[0]) + 1
            connection.execute(
                """
                INSERT INTO osce_session_tombstones (
                    session_id,
                    user_id,
                    case_id,
                    deleted_revision,
                    deleted_at,
                    cleanup_status,
                    cleanup_completed_at,
                    cleanup_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    case_id = excluded.case_id,
                    deleted_revision = MAX(
                        osce_session_tombstones.deleted_revision,
                        excluded.deleted_revision
                    ),
                    deleted_at = excluded.deleted_at,
                    cleanup_status = excluded.cleanup_status,
                    cleanup_completed_at = excluded.cleanup_completed_at,
                    cleanup_version = excluded.cleanup_version
                """,
                (
                    session_id,
                    str(row[1]),
                    str(row[2]),
                    deleted_revision,
                    deleted_at,
                    SESSION_DELETION_COMPLETED,
                    deleted_at,
                ),
            )
            connection.execute(
                "DELETE FROM osce_session_event_outbox WHERE session_id = ?",
                (session_id,),
            )
            cursor = connection.execute(
                "DELETE FROM osce_sessions WHERE session_id = ? AND revision = ?",
                (session_id, int(row[0])),
            )
            if cursor.rowcount != 1:
                raise SessionWriteConflictError(
                    session_id,
                    expected_revision=int(row[0]),
                    current_revision=int(row[0]),
                )
        return True

    def begin_session_deletion(
        self,
        session_id: str,
        expected_user_id: str,
    ) -> SessionDeletionRecord | None:
        self._initialize()
        deleted_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_deletion = self._tombstone_record(connection, session_id)
            if existing_deletion is not None:
                if existing_deletion.user_id != expected_user_id:
                    return None
                connection.execute(
                    "DELETE FROM osce_session_event_outbox WHERE session_id = ?",
                    (session_id,),
                )
                return existing_deletion

            row = connection.execute(
                """
                SELECT revision, user_id, case_id
                FROM osce_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None or str(row[1]) != expected_user_id:
                return None

            current_revision = int(row[0])
            deletion = SessionDeletionRecord(
                session_id=session_id,
                user_id=str(row[1]),
                case_id=str(row[2]),
                deleted_revision=current_revision + 1,
                deleted_at=deleted_at,
                cleanup_status=SESSION_DELETION_PENDING,
                cleanup_completed_at=None,
                cleanup_version=SESSION_DELETION_CLEANUP_VERSION,
            )
            connection.execute(
                """
                INSERT INTO osce_session_tombstones (
                    session_id,
                    user_id,
                    case_id,
                    deleted_revision,
                    deleted_at,
                    cleanup_status,
                    cleanup_completed_at,
                    cleanup_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deletion.session_id,
                    deletion.user_id,
                    deletion.case_id,
                    deletion.deleted_revision,
                    deletion.deleted_at,
                    deletion.cleanup_status,
                    deletion.cleanup_completed_at,
                    deletion.cleanup_version,
                ),
            )
            connection.execute(
                "DELETE FROM osce_session_event_outbox WHERE session_id = ?",
                (session_id,),
            )
            cursor = connection.execute(
                """
                DELETE FROM osce_sessions
                WHERE session_id = ?
                  AND revision = ?
                  AND user_id = ?
                """,
                (session_id, current_revision, expected_user_id),
            )
            if cursor.rowcount != 1:
                current_row = connection.execute(
                    "SELECT revision FROM osce_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                raise SessionWriteConflictError(
                    session_id,
                    expected_revision=current_revision,
                    current_revision=(
                        current_revision if current_row is None else int(current_row[0])
                    ),
                )
            return deletion

    def adopt_legacy_session_deletion(
        self,
        session_id: str,
        *,
        user_id: str,
        case_id: str,
    ) -> SessionDeletionRecord | None:
        """Claim an ownerless legacy tombstone without overwriting owned data.

        Ownership evidence lives in the report/event stores, so callers must
        validate it before asking this store to persist the recovered owner.
        The conditional update keeps that validation safe under concurrent
        adoption attempts.
        """

        normalized_user_id = user_id.strip()
        normalized_case_id = case_id.strip()
        if not normalized_user_id or not normalized_case_id:
            return None

        self._initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active_row = connection.execute(
                "SELECT 1 FROM osce_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if active_row is not None:
                return None
            cursor = connection.execute(
                """
                UPDATE osce_session_tombstones
                SET
                    user_id = ?,
                    case_id = ?,
                    cleanup_status = ?,
                    cleanup_completed_at = NULL,
                    cleanup_version = ?
                WHERE session_id = ?
                  AND user_id = ''
                """,
                (
                    normalized_user_id,
                    normalized_case_id,
                    SESSION_DELETION_PENDING,
                    SESSION_DELETION_CLEANUP_VERSION,
                    session_id,
                ),
            )
            if cursor.rowcount != 1:
                return None
            connection.execute(
                "DELETE FROM osce_session_event_outbox WHERE session_id = ?",
                (session_id,),
            )
            return self._tombstone_record(connection, session_id)

    def get_session_deletion(self, session_id: str) -> SessionDeletionRecord | None:
        self._initialize()
        with self._connect() as connection:
            return self._tombstone_record(connection, session_id)

    def list_pending_deletions(
        self,
        *,
        limit: int | None = None,
    ) -> list[SessionDeletionRecord]:
        self._initialize()
        if limit is not None and limit <= 0:
            return []
        limit_clause = "" if limit is None else "LIMIT ?"
        parameters: tuple[object, ...] = (
            (SESSION_DELETION_PENDING, SESSION_DELETION_CLEANUP_VERSION)
            if limit is None
            else (
                SESSION_DELETION_PENDING,
                SESSION_DELETION_CLEANUP_VERSION,
                limit,
            )
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    session_id,
                    user_id,
                    case_id,
                    deleted_revision,
                    deleted_at,
                    cleanup_status,
                    cleanup_completed_at,
                    cleanup_version
                FROM osce_session_tombstones
                WHERE cleanup_status = ?
                   OR cleanup_version < ?
                ORDER BY deleted_at, session_id
                {limit_clause}
                """,
                parameters,
            ).fetchall()
        return [_session_deletion_record_from_row(row) for row in rows]

    def list_ownerless_legacy_deletions(
        self,
        *,
        limit: int | None = None,
    ) -> list[SessionDeletionRecord]:
        self._initialize()
        if limit is not None and limit <= 0:
            return []
        limit_clause = "" if limit is None else "LIMIT ?"
        parameters: tuple[object, ...] = () if limit is None else (limit,)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    session_id,
                    user_id,
                    case_id,
                    deleted_revision,
                    deleted_at,
                    cleanup_status,
                    cleanup_completed_at,
                    cleanup_version
                FROM osce_session_tombstones
                WHERE user_id = ''
                ORDER BY deleted_at, session_id
                {limit_clause}
                """,
                parameters,
            ).fetchall()
        return [_session_deletion_record_from_row(row) for row in rows]

    def validate_skill_source_references(
        self,
        *,
        source_session_id: str,
        owner_user_id: str,
        personal_skill_id: str,
        personal_candidate_id: str,
        source_report_id: str,
    ) -> None:
        _validate_deleted_skill_source_identity(
            source_session_id=source_session_id,
            owner_user_id=owner_user_id,
            personal_skill_id=personal_skill_id,
            personal_candidate_id=personal_candidate_id,
            source_report_id=source_report_id,
        )
        self._initialize()
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT
                    owner_user_id,
                    personal_skill_id,
                    personal_candidate_id,
                    source_report_id
                FROM osce_deleted_skill_sources
                WHERE source_session_id = ?
                """,
                (source_session_id,),
            ).fetchone()
            if existing is not None and tuple(str(value) for value in existing) != (
                owner_user_id,
                personal_skill_id,
                personal_candidate_id,
                source_report_id,
            ):
                raise SessionDerivedReferenceOwnershipError(source_session_id)
            rows = connection.execute(
                """
                SELECT session_id, user_id, session_json
                FROM osce_sessions
                ORDER BY created_at, session_id
                """
            ).fetchall()
        for raw_session_id, raw_user_id, raw_payload in rows:
            payload = _decode_session_payload(
                raw_payload,
                session_id=str(raw_session_id),
            )
            if (
                _session_payload_references_applied_skill_id(
                    payload,
                    skill_id=personal_skill_id,
                )
                and (
                    str(raw_user_id) != owner_user_id
                    or str(payload.get("student_id", "")) != owner_user_id
                )
            ):
                raise SessionDerivedReferenceOwnershipError(source_session_id)

    def delete_skill_source_references(
        self,
        *,
        source_session_id: str,
        owner_user_id: str,
        personal_skill_id: str,
        personal_candidate_id: str,
        source_report_id: str,
        affected_global_skill_ids: list[str] | None = None,
    ) -> list[str]:
        _validate_deleted_skill_source_identity(
            source_session_id=source_session_id,
            owner_user_id=owner_user_id,
            personal_skill_id=personal_skill_id,
            personal_candidate_id=personal_candidate_id,
            source_report_id=source_report_id,
        )
        normalized_global_skill_ids = _normalized_skill_ids(
            affected_global_skill_ids,
            excluded_skill_id=personal_skill_id,
        )
        self._initialize()
        deleted_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT
                    owner_user_id,
                    personal_skill_id,
                    personal_candidate_id,
                    source_report_id,
                    affected_global_skill_ids_json,
                    affected_session_ids_json
                FROM osce_deleted_skill_sources
                WHERE source_session_id = ?
                """,
                (source_session_id,),
            ).fetchone()
            if existing is not None:
                if (
                    tuple(str(value) for value in existing[:4])
                    != (
                        owner_user_id,
                        personal_skill_id,
                        personal_candidate_id,
                        source_report_id,
                    )
                    or _decode_string_list(existing[4])
                    != normalized_global_skill_ids
                ):
                    raise SessionDerivedReferenceOwnershipError(
                        source_session_id
                    )
                return _decode_string_list(existing[5])

            rows = connection.execute(
                """
                SELECT session_id, user_id, session_json, revision
                FROM osce_sessions
                ORDER BY created_at, session_id
                """
            ).fetchall()
            updates: list[tuple[str, str, int, str]] = []
            for raw_session_id, raw_user_id, raw_payload, raw_revision in rows:
                session_id = str(raw_session_id)
                payload = _decode_session_payload(
                    raw_payload,
                    session_id=session_id,
                )
                blocked_global_skill_ids = (
                    _blocked_global_skill_ids_for_session_payload(
                        payload,
                        skill_ids=set(normalized_global_skill_ids),
                        source_session_id=source_session_id,
                        source_report_id=source_report_id,
                    )
                )
                referenced_skill_ids = _session_payload_referenced_skill_ids(
                    payload,
                    skill_ids={
                        personal_skill_id,
                        *blocked_global_skill_ids,
                    },
                )
                if not referenced_skill_ids:
                    continue
                if (
                    _session_payload_references_applied_skill_id(
                        payload,
                        skill_id=personal_skill_id,
                    )
                    and (
                        str(raw_user_id) != owner_user_id
                        or str(payload.get("student_id", ""))
                        != owner_user_id
                    )
                ):
                    raise SessionDerivedReferenceOwnershipError(
                        source_session_id
                    )
                sanitized = _remove_skill_ids_from_session_payload(
                    payload,
                    skill_ids=referenced_skill_ids,
                )
                updates.append(
                    (
                        session_id,
                        json.dumps(sanitized, ensure_ascii=False),
                        int(raw_revision),
                        str(raw_user_id),
                    )
                )

            affected_session_ids = sorted(
                session_id for session_id, _, _, _ in updates
            )
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_session_id,
                    owner_user_id,
                    personal_skill_id,
                    personal_candidate_id,
                    source_report_id,
                    json.dumps(normalized_global_skill_ids),
                    json.dumps(affected_session_ids),
                    deleted_at,
                ),
            )
            for session_id, serialized_payload, revision, session_user_id in updates:
                cursor = connection.execute(
                    """
                    UPDATE osce_sessions
                    SET
                        session_json = ?,
                        revision = revision + 1,
                        updated_at = ?
                    WHERE session_id = ?
                      AND revision = ?
                      AND user_id = ?
                    """,
                    (
                        serialized_payload,
                        deleted_at,
                        session_id,
                        revision,
                        session_user_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise SessionWriteConflictError(
                        session_id,
                        expected_revision=revision,
                        current_revision=revision,
                    )
        return affected_session_ids

    def mark_session_deletion_complete(
        self,
        session_id: str,
    ) -> SessionDeletionRecord | None:
        self._initialize()
        completed_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            deletion = self._tombstone_record(connection, session_id)
            if deletion is None:
                return None
            connection.execute(
                "DELETE FROM osce_session_event_outbox WHERE session_id = ?",
                (session_id,),
            )
            if (
                deletion.cleanup_status != SESSION_DELETION_COMPLETED
                or deletion.cleanup_version < SESSION_DELETION_CLEANUP_VERSION
            ):
                connection.execute(
                    """
                    UPDATE osce_session_tombstones
                    SET
                        cleanup_status = ?,
                        cleanup_completed_at = ?,
                        cleanup_version = ?
                    WHERE session_id = ?
                    """,
                    (
                        SESSION_DELETION_COMPLETED,
                        completed_at,
                        SESSION_DELETION_CLEANUP_VERSION,
                        session_id,
                    ),
                )
            return self._tombstone_record(connection, session_id)

    def is_session_deleted(self, session_id: str) -> bool:
        self._initialize()
        with self._connect() as connection:
            return self._tombstone_revision(connection, session_id) is not None

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._initialization_lock:
            if self._initialized:
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS osce_sessions (
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
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(osce_sessions)").fetchall()
                }
                if "revision" not in columns:
                    connection.execute(
                        """
                        ALTER TABLE osce_sessions
                        ADD COLUMN revision INTEGER NOT NULL DEFAULT 1
                        """
                    )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS osce_session_tombstones (
                        session_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL DEFAULT '',
                        case_id TEXT NOT NULL DEFAULT '',
                        deleted_revision INTEGER NOT NULL,
                        deleted_at TEXT NOT NULL,
                        cleanup_status TEXT NOT NULL DEFAULT 'completed'
                            CHECK(cleanup_status IN ('pending', 'completed')),
                        cleanup_completed_at TEXT,
                        cleanup_version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS osce_session_event_outbox (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_key TEXT NOT NULL UNIQUE,
                        session_id TEXT NOT NULL,
                        session_revision INTEGER NOT NULL
                            CHECK(session_revision >= 1),
                        event_index INTEGER NOT NULL
                            CHECK(event_index >= 0),
                        case_id TEXT NOT NULL,
                        student_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(session_id, session_revision, event_index)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS osce_session_event_outbox_pending_idx
                    ON osce_session_event_outbox(id)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS osce_session_event_outbox_session_idx
                    ON osce_session_event_outbox(session_id)
                    """
                )
                tombstone_columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(osce_session_tombstones)"
                    ).fetchall()
                }
                if "user_id" not in tombstone_columns:
                    connection.execute(
                        """
                        ALTER TABLE osce_session_tombstones
                        ADD COLUMN user_id TEXT NOT NULL DEFAULT ''
                        """
                    )
                if "case_id" not in tombstone_columns:
                    connection.execute(
                        """
                        ALTER TABLE osce_session_tombstones
                        ADD COLUMN case_id TEXT NOT NULL DEFAULT ''
                        """
                    )
                if "cleanup_status" not in tombstone_columns:
                    connection.execute(
                        """
                        ALTER TABLE osce_session_tombstones
                        ADD COLUMN cleanup_status TEXT NOT NULL DEFAULT 'completed'
                        """
                    )
                if "cleanup_completed_at" not in tombstone_columns:
                    connection.execute(
                        """
                        ALTER TABLE osce_session_tombstones
                        ADD COLUMN cleanup_completed_at TEXT
                        """
                    )
                if "cleanup_version" not in tombstone_columns:
                    connection.execute(
                        """
                        ALTER TABLE osce_session_tombstones
                        ADD COLUMN cleanup_version INTEGER NOT NULL DEFAULT 1
                        """
                    )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS osce_deleted_skill_sources (
                        source_session_id TEXT PRIMARY KEY,
                        owner_user_id TEXT NOT NULL,
                        personal_skill_id TEXT NOT NULL,
                        personal_candidate_id TEXT NOT NULL,
                        source_report_id TEXT NOT NULL,
                        affected_global_skill_ids_json TEXT NOT NULL DEFAULT '[]',
                        affected_session_ids_json TEXT NOT NULL,
                        deleted_at TEXT NOT NULL
                    )
                    """
                )
                deleted_skill_source_columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(osce_deleted_skill_sources)"
                    ).fetchall()
                }
                if (
                    "affected_global_skill_ids_json"
                    not in deleted_skill_source_columns
                ):
                    connection.execute(
                        """
                        ALTER TABLE osce_deleted_skill_sources
                        ADD COLUMN affected_global_skill_ids_json
                            TEXT NOT NULL DEFAULT '[]'
                        """
                    )
                connection.execute(
                    """
                    UPDATE osce_session_tombstones
                    SET cleanup_completed_at = deleted_at
                    WHERE cleanup_status = ?
                      AND cleanup_completed_at IS NULL
                    """,
                    (SESSION_DELETION_COMPLETED,),
                )
                connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")
            self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=DATABASE_BUSY_TIMEOUT_MILLISECONDS / 1000,
        )
        connection.execute(f"PRAGMA busy_timeout = {DATABASE_BUSY_TIMEOUT_MILLISECONDS}")
        return connection

    @staticmethod
    def _insert_event_outbox(
        connection: sqlite3.Connection,
        *,
        session_id: str,
        session_revision: int,
        case_id: str,
        student_id: str,
        serialized_events: Sequence[tuple[str, str]],
        created_at: str,
    ) -> None:
        for event_index, (event_type, payload_json) in enumerate(serialized_events):
            event_key = (
                f"session:{session_id}:revision:{session_revision}:"
                f"event:{event_index}:{event_type}"
            )
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
                    event_key,
                    session_id,
                    session_revision,
                    event_index,
                    case_id,
                    student_id,
                    event_type,
                    payload_json,
                    created_at,
                ),
            )

    @staticmethod
    def _deleted_skill_sources_version(
        connection: sqlite3.Connection,
    ) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(rowid), 0) FROM osce_deleted_skill_sources"
        ).fetchone()
        return 0 if row is None else int(row[0])

    @staticmethod
    def _tombstone_revision(connection: sqlite3.Connection, session_id: str) -> int | None:
        row = connection.execute(
            "SELECT deleted_revision FROM osce_session_tombstones WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return None if row is None else int(row[0])

    @staticmethod
    def _tombstone_record(
        connection: sqlite3.Connection,
        session_id: str,
    ) -> SessionDeletionRecord | None:
        row = connection.execute(
            """
            SELECT
                session_id,
                user_id,
                case_id,
                deleted_revision,
                deleted_at,
                cleanup_status,
                cleanup_completed_at,
                cleanup_version
            FROM osce_session_tombstones
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return _session_deletion_record_from_row(row)


osce_session_store = OsceSessionStore()


def _serialize_outbox_events(
    events: Sequence[SessionOutboxEvent],
) -> tuple[tuple[str, str], ...]:
    serialized: list[tuple[str, str]] = []
    for event in events:
        event_type = event.event_type.strip()
        if not event_type:
            raise ValueError("outbox event_type is required")
        if not isinstance(event.payload, dict):
            raise ValueError("outbox event payload must be an object")
        serialized.append(
            (
                event_type,
                json.dumps(event.payload, ensure_ascii=False),
            )
        )
    return tuple(serialized)


def _session_outbox_item_from_row(
    row: tuple[object, ...],
) -> SessionOutboxItem:
    payload = json.loads(str(row[7]))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid session outbox payload: {row[0]}")
    return SessionOutboxItem(
        event_key=str(row[0]),
        session_id=str(row[1]),
        session_revision=int(row[2]),
        event_index=int(row[3]),
        case_id=str(row[4]),
        student_id=str(row[5]),
        event_type=str(row[6]),
        payload=payload,
        created_at=str(row[8]),
    )


def _session_deletion_record_from_row(
    row: tuple[object, ...],
) -> SessionDeletionRecord:
    return SessionDeletionRecord(
        session_id=str(row[0]),
        user_id=str(row[1]),
        case_id=str(row[2]),
        deleted_revision=int(row[3]),
        deleted_at=str(row[4]),
        cleanup_status=str(row[5]),
        cleanup_completed_at=None if row[6] is None else str(row[6]),
        cleanup_version=int(row[7]),
    )


def _decode_string_list(value: object) -> list[str]:
    decoded = json.loads(str(value))
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded if str(item)]


def _decode_session_payload(
    value: object,
    *,
    session_id: str,
) -> dict[str, object]:
    payload = json.loads(str(value))
    if not isinstance(payload, dict):
        raise SessionDerivedReferenceOwnershipError(session_id)
    return payload


def _validate_deleted_skill_source_identity(
    *,
    source_session_id: str,
    owner_user_id: str,
    personal_skill_id: str,
    personal_candidate_id: str,
    source_report_id: str,
) -> None:
    if (
        not source_session_id
        or not owner_user_id
        or personal_skill_id != f"skill_personal_{source_session_id}"
        or personal_candidate_id
        != f"personal_skill_candidate_{source_session_id}"
        or source_report_id != f"{source_session_id}_report"
    ):
        raise SessionDerivedReferenceOwnershipError(source_session_id)


def _normalized_skill_ids(
    value: object,
    *,
    excluded_skill_id: str = "",
) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(
        {
            str(item)
            for item in value
            if str(item) and str(item) != excluded_skill_id
        }
    )


def _scrub_payload_for_deleted_skill_sources(
    connection: sqlite3.Connection,
    payload: dict[str, object],
    *,
    user_id: str,
) -> dict[str, object]:
    rows = connection.execute(
        """
        SELECT
            source_session_id,
            owner_user_id,
            personal_skill_id,
            source_report_id,
            affected_global_skill_ids_json
        FROM osce_deleted_skill_sources
        """,
    ).fetchall()
    sanitized = dict(payload)
    for row in rows:
        source_session_id = str(row[0])
        source_owner_user_id = str(row[1])
        personal_skill_id = str(row[2])
        source_report_id = str(row[3])
        global_skill_ids = _blocked_global_skill_ids_for_session_payload(
            sanitized,
            skill_ids=set(_decode_string_list(row[4])),
            source_session_id=source_session_id,
            source_report_id=source_report_id,
        )
        if _session_payload_references_skill_ids(
            sanitized,
            skill_ids={personal_skill_id},
        ):
            if (
                source_owner_user_id != user_id
                and _session_payload_references_applied_skill_id(
                    sanitized,
                    skill_id=personal_skill_id,
                )
            ):
                raise SessionDerivedReferenceOwnershipError(
                    source_session_id
                )
            sanitized = _remove_skill_ids_from_session_payload(
                sanitized,
                skill_ids={personal_skill_id},
            )
        if global_skill_ids:
            sanitized = _remove_skill_ids_from_session_payload(
                sanitized,
                skill_ids=global_skill_ids,
            )
    return sanitized


def _blocked_global_skill_ids_for_session_payload(
    payload: dict[str, object],
    *,
    skill_ids: set[str],
    source_session_id: str,
    source_report_id: str,
) -> set[str]:
    return {
        skill_id
        for skill_id in skill_ids
        if not _session_payload_has_explicit_remaining_skill_source(
            payload,
            skill_id=skill_id,
            source_session_id=source_session_id,
            source_report_id=source_report_id,
        )
    }


def _session_payload_has_explicit_remaining_skill_source(
    payload: dict[str, object],
    *,
    skill_id: str,
    source_session_id: str,
    source_report_id: str,
) -> bool:
    active_skill_context = payload.get("active_skill_context")
    if not isinstance(active_skill_context, dict):
        return False
    matching_items: list[dict[str, object]] = []
    for field_name in ("skill_index", "selected_skills"):
        items = active_skill_context.get(field_name)
        if not isinstance(items, list):
            continue
        matching_items.extend(
            item
            for item in items
            if isinstance(item, dict)
            and str(item.get("skill_id", "")) == skill_id
        )
    return bool(matching_items) and all(
        _skill_reference_has_explicit_remaining_source(
            item,
            source_session_id=source_session_id,
            source_report_id=source_report_id,
        )
        for item in matching_items
    )


def _skill_reference_has_explicit_remaining_source(
    value: dict[str, object],
    *,
    source_session_id: str,
    source_report_id: str,
) -> bool:
    if (
        str(value.get("source_provenance_schema_version", ""))
        != "training_candidate_sources.v1"
    ):
        return False
    source_session_ids = _normalized_reference_ids(
        value.get("source_session_ids")
    )
    source_report_ids = _normalized_reference_ids(
        value.get("source_report_ids")
    )
    return bool(source_session_ids or source_report_ids) and (
        source_session_id not in source_session_ids
        and source_report_id not in source_report_ids
    )


def _normalized_reference_ids(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        normalized
        for item in value
        if (normalized := str(item).strip())
    }


def _session_payload_references_skill_ids(
    payload: dict[str, object],
    *,
    skill_ids: set[str],
) -> bool:
    return bool(
        _session_payload_referenced_skill_ids(
            payload,
            skill_ids=skill_ids,
        )
    )


def _session_payload_references_applied_skill_id(
    payload: dict[str, object],
    *,
    skill_id: str,
) -> bool:
    active_skill_context = payload.get("active_skill_context")
    if isinstance(active_skill_context, dict):
        for field_name in ("skill_index", "selected_skills"):
            items = active_skill_context.get(field_name)
            if not isinstance(items, list):
                continue
            if any(
                isinstance(item, dict)
                and str(item.get("skill_id", "")) == skill_id
                for item in items
            ):
                return True
    return any(
        _nested_referenced_skill_ids(
            payload.get(field_name),
            skill_ids={skill_id},
        )
        for field_name in (
            "agent_turn_memory",
            "pedagogy_state",
            "agent_decision_trace",
            "teacher_decision_records",
        )
    )


def _session_payload_referenced_skill_ids(
    payload: dict[str, object],
    *,
    skill_ids: set[str],
) -> set[str]:
    if not skill_ids:
        return set()
    referenced_skill_ids: set[str] = set()
    active_skill_context = payload.get("active_skill_context")
    if isinstance(active_skill_context, dict):
        for field_name in ("skill_index", "selected_skills", "skipped_reasons"):
            items = active_skill_context.get(field_name)
            if not isinstance(items, list):
                continue
            referenced_skill_ids.update(
                str(item.get("skill_id", ""))
                for item in items
                if isinstance(item, dict)
                and str(item.get("skill_id", "")) in skill_ids
            )
    referenced_skill_ids.update(
        _nested_referenced_skill_ids(
            payload.get("agent_turn_memory"),
            skill_ids=skill_ids,
        )
    )
    referenced_skill_ids.update(
        _nested_referenced_skill_ids(
            payload.get("pedagogy_state"),
            skill_ids=skill_ids,
        )
    )
    referenced_skill_ids.update(
        _nested_referenced_skill_ids(
            payload.get("agent_decision_trace"),
            skill_ids=skill_ids,
        )
    )
    referenced_skill_ids.update(
        _nested_referenced_skill_ids(
            payload.get("teacher_decision_records"),
            skill_ids=skill_ids,
        )
    )
    return referenced_skill_ids


def _remove_skill_ids_from_session_payload(
    payload: dict[str, object],
    *,
    skill_ids: set[str],
) -> dict[str, object]:
    referenced_skill_ids = _session_payload_referenced_skill_ids(
        payload,
        skill_ids=skill_ids,
    )
    if not referenced_skill_ids:
        return payload
    sanitized = dict(payload)
    active_skill_context = payload.get("active_skill_context")
    if isinstance(active_skill_context, dict):
        next_context = dict(active_skill_context)
        for field_name in ("skill_index", "selected_skills", "skipped_reasons"):
            items = active_skill_context.get(field_name)
            if not isinstance(items, list):
                continue
            next_context[field_name] = [
                item
                for item in items
                if not (
                    isinstance(item, dict)
                    and str(item.get("skill_id", ""))
                    in referenced_skill_ids
                )
            ]
        sanitized["active_skill_context"] = next_context
        sanitized["evolution_candidates"] = (
            _skill_prompts_from_selected_context(
                next_context.get("selected_skills", [])
            )
        )
    for field_name in ("agent_turn_memory", "agent_decision_trace", "teacher_decision_records"):
        items = sanitized.get(field_name)
        if not isinstance(items, list):
            continue
        sanitized[field_name] = [
            item
            for item in items
            if not _nested_referenced_skill_ids(
                item,
                skill_ids=referenced_skill_ids,
            )
        ]
    pedagogy_state = sanitized.get("pedagogy_state")
    if isinstance(pedagogy_state, dict) and _nested_referenced_skill_ids(
        pedagogy_state,
        skill_ids=referenced_skill_ids,
    ):
        next_pedagogy_state = _remove_skill_ids_from_nested_value(
            pedagogy_state,
            skill_ids=referenced_skill_ids,
        )
        assert isinstance(next_pedagogy_state, dict)
        for key in (
            "teaching_plan",
            "next_best_action",
            "active_learning_goal",
        ):
            next_pedagogy_state.pop(key, None)
        next_pedagogy_state["skill_context_ids"] = []
        next_pedagogy_state["coaching_mode"] = "socratic"
        sanitized["pedagogy_state"] = next_pedagogy_state
    if not isinstance(active_skill_context, dict) and (
        "evolution_candidates" in sanitized
    ):
        sanitized["evolution_candidates"] = []
    return sanitized


def _nested_referenced_skill_ids(
    value: object,
    *,
    skill_ids: set[str],
) -> set[str]:
    if isinstance(value, dict):
        found: set[str] = set()
        for nested_value in value.values():
            found.update(
                _nested_referenced_skill_ids(
                    nested_value,
                    skill_ids=skill_ids,
                )
            )
        return found
    if isinstance(value, list):
        found = set()
        for nested_value in value:
            found.update(
                _nested_referenced_skill_ids(
                    nested_value,
                    skill_ids=skill_ids,
                )
            )
        return found
    normalized = str(value) if value is not None else ""
    return {normalized} if normalized in skill_ids else set()


def _remove_skill_ids_from_nested_value(
    value: object,
    *,
    skill_ids: set[str],
) -> object:
    if isinstance(value, dict):
        sanitized = {
            key: _remove_skill_ids_from_nested_value(
                nested_value,
                skill_ids=skill_ids,
            )
            for key, nested_value in value.items()
            if str(key) not in skill_ids and str(nested_value) not in skill_ids
        }
        skill_context_ids = sanitized.get("skill_context_ids")
        if (
            isinstance(skill_context_ids, list)
            and not skill_context_ids
            and sanitized.get("coaching_mode") == "skill_guided"
        ):
            sanitized["coaching_mode"] = "socratic"
        return sanitized
    if isinstance(value, list):
        return [
            _remove_skill_ids_from_nested_value(
                nested_value,
                skill_ids=skill_ids,
            )
            for nested_value in value
            if str(nested_value) not in skill_ids
        ]
    return value


def _remove_personal_skill_from_session_payload(
    payload: dict[str, object],
    *,
    personal_skill_id: str,
) -> dict[str, object]:
    return _remove_skill_ids_from_session_payload(
        payload,
        skill_ids={personal_skill_id},
    )


def _skill_prompts_from_selected_context(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    prompts: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        strategy = str(item.get("suggested_strategy", "")).strip()
        if title and strategy:
            prompts.append(f"{title}：{strategy}")
        elif title:
            prompts.append(title)
        elif strategy:
            prompts.append(strategy)
    return prompts


def _session_completion_summary(session_json: str, stage: str, case_id: str) -> dict[str, object]:
    try:
        payload = json.loads(session_json)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    final_submission = payload.get("final_submission")
    feedback_report = payload.get("feedback_report")
    case_title = payload.get("case_title")
    training_difficulty = payload.get("training_difficulty")
    has_report = bool(feedback_report)
    has_final_submission = bool(final_submission)
    stage_is_closed = stage in {"diagnosis_submission", "feedback"}
    is_completed = has_report or has_final_submission or stage_is_closed
    if has_report or stage == "feedback":
        completion_status = "report_ready"
    elif has_final_submission or stage == "diagnosis_submission":
        completion_status = "diagnosis_submitted"
    else:
        completion_status = "in_progress"
    return {
        "case_title": case_title if isinstance(case_title, str) and case_title.strip() else _case_title_for_case_id(case_id),
        "training_difficulty": (
            training_difficulty
            if isinstance(training_difficulty, str) and training_difficulty in {"beginner", "intermediate", "advanced"}
            else "beginner"
        ),
        "is_completed": is_completed,
        "can_continue": not is_completed,
        "has_report": has_report,
        "completion_status": completion_status,
        "active_skill_context": payload.get("active_skill_context") if isinstance(payload.get("active_skill_context"), dict) else {},
    }


@lru_cache(maxsize=128)
def _case_title_for_case_id(case_id: str) -> str:
    normalized_case_id = str(case_id or "").strip()
    if not normalized_case_id:
        return ""
    case_path = ROOT_DIR / "data" / "cases" / f"{normalized_case_id}.json"
    try:
        payload = json.loads(case_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return normalized_case_id
    title = payload.get("case_title") if isinstance(payload, dict) else None
    return title if isinstance(title, str) and title.strip() else normalized_case_id
