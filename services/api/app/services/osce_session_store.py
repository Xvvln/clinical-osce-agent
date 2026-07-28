from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.osce_session_service import OsceSession

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "osce_sessions.sqlite3"
DATABASE_SCHEMA_VERSION = 3
DATABASE_BUSY_TIMEOUT_MILLISECONDS = 10_000
SESSION_DELETION_PENDING = "pending"
SESSION_DELETION_COMPLETED = "completed"


class SessionPersistenceError(RuntimeError):
    def __init__(self, session_id: str) -> None:
        super().__init__(session_id)
        self.session_id = session_id


class SessionAlreadyExistsError(SessionPersistenceError):
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


@dataclass(frozen=True)
class StoredSession:
    payload: dict[str, object]
    revision: int


@dataclass(frozen=True)
class SessionDeletionRecord:
    session_id: str
    user_id: str
    case_id: str
    deleted_revision: int
    deleted_at: str
    cleanup_status: str
    cleanup_completed_at: str | None


class OsceSessionStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path
        self._initialization_lock = Lock()
        self._initialized = False

    def create_session(self, session: OsceSession) -> int:
        self._initialize()
        now = datetime.now(UTC).isoformat()
        payload = asdict(session)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._tombstone_revision(connection, session.session_id) is not None:
                raise SessionAlreadyExistsError(session.session_id)
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
        return 1

    def update_session(self, session: OsceSession, *, expected_revision: int) -> int:
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        self._initialize()
        now = datetime.now(UTC).isoformat()
        payload = asdict(session)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
                return expected_revision + 1
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
                    cleanup_completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    case_id = excluded.case_id,
                    deleted_revision = MAX(
                        osce_session_tombstones.deleted_revision,
                        excluded.deleted_revision
                    ),
                    deleted_at = excluded.deleted_at,
                    cleanup_status = excluded.cleanup_status,
                    cleanup_completed_at = excluded.cleanup_completed_at
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
                    cleanup_completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deletion.session_id,
                    deletion.user_id,
                    deletion.case_id,
                    deletion.deleted_revision,
                    deletion.deleted_at,
                    deletion.cleanup_status,
                    deletion.cleanup_completed_at,
                ),
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

    def get_session_deletion(self, session_id: str) -> SessionDeletionRecord | None:
        self._initialize()
        with self._connect() as connection:
            return self._tombstone_record(connection, session_id)

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
            if deletion.cleanup_status != SESSION_DELETION_COMPLETED:
                connection.execute(
                    """
                    UPDATE osce_session_tombstones
                    SET cleanup_status = ?, cleanup_completed_at = ?
                    WHERE session_id = ?
                    """,
                    (SESSION_DELETION_COMPLETED, completed_at, session_id),
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
                        cleanup_completed_at TEXT
                    )
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
                cleanup_completed_at
            FROM osce_session_tombstones
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return SessionDeletionRecord(
            session_id=str(row[0]),
            user_id=str(row[1]),
            case_id=str(row[2]),
            deleted_revision=int(row[3]),
            deleted_at=str(row[4]),
            cleanup_status=str(row[5]),
            cleanup_completed_at=None if row[6] is None else str(row[6]),
        )


osce_session_store = OsceSessionStore()


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
