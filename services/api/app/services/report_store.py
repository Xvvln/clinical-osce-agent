from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Literal, cast
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "reports.sqlite3"
DATABASE_SCHEMA_VERSION = 2
DATABASE_BUSY_TIMEOUT_MILLISECONDS = 10_000
DEFAULT_ENRICHMENT_LEASE_SECONDS = 300

EnrichmentStatus = Literal["pending", "claimed", "completed", "failed"]


class ReportPersistenceError(RuntimeError):
    def __init__(self, session_id: str) -> None:
        super().__init__(session_id)
        self.session_id = session_id


class ReportAlreadyExistsError(ReportPersistenceError):
    pass


class ReportNotFoundError(ReportPersistenceError):
    pass


class ReportWriteConflictError(ReportPersistenceError):
    def __init__(self, session_id: str, *, expected_revision: int, current_revision: int) -> None:
        super().__init__(session_id)
        self.expected_revision = expected_revision
        self.current_revision = current_revision


class ReportClaimLostError(ReportWriteConflictError):
    pass


@dataclass(frozen=True)
class StoredReport:
    payload: dict[str, Any]
    revision: int
    enrichment_status: EnrichmentStatus
    enrichment_retry_count: int
    enrichment_claim_token: str | None
    enrichment_lease_expires_at: str | None
    enrichment_last_error: str | None


@dataclass(frozen=True)
class ReportEnrichmentClaim:
    session_id: str
    report: dict[str, Any]
    expected_revision: int
    claim_token: str
    lease_expires_at: str
    retry_count: int


@dataclass(frozen=True)
class ReportOutboxEvent:
    case_id: str
    student_id: str
    event_type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ReportOutboxItem:
    event_key: str
    session_id: str
    case_id: str
    student_id: str
    event_type: str
    payload: dict[str, Any]
    report_revision: int
    created_at: str
    updated_at: str
    acknowledged_at: str | None


@dataclass(frozen=True)
class _SerializedOutboxEvent:
    case_id: str
    student_id: str
    event_type: str
    payload_json: str


class ReportStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path
        self._initialization_lock = Lock()
        self._initialized = False

    def create_base_report(
        self,
        report: dict[str, Any],
        *,
        enrichment_required: bool | None = None,
        outbox_event: ReportOutboxEvent | None = None,
    ) -> StoredReport:
        """Create the immutable base snapshot, or return an identical existing one.

        A different report for the same session is a persistence conflict. Callers
        must use the claim/CAS completion flow for optional enrichment.
        """

        session_id, report_json = _serialize_report(report)
        initial_status = _initial_enrichment_status(report, enrichment_required=enrichment_required)
        serialized_event = _serialize_outbox_event(report, outbox_event)
        self._initialize()
        now = _utc_iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select_stored_report(connection, session_id)
            if row is not None:
                stored = _stored_report_from_row(row)
                if stored.payload == report:
                    if serialized_event is not None:
                        self._upsert_outbox(
                            connection,
                            event_key=self.build_base_outbox_event_key(
                                session_id=session_id,
                                event_type=serialized_event.event_type,
                            ),
                            session_id=session_id,
                            case_id=serialized_event.case_id,
                            student_id=serialized_event.student_id,
                            event_type=serialized_event.event_type,
                            payload_json=serialized_event.payload_json,
                            report_revision=1,
                            now=now,
                        )
                    return stored
                raise ReportAlreadyExistsError(session_id)
            connection.execute(
                """
                INSERT INTO reports (
                    session_id,
                    report_json,
                    revision,
                    enrichment_status,
                    enrichment_retry_count,
                    enrichment_claim_token,
                    enrichment_lease_expires_at,
                    enrichment_last_error,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, 1, ?, 0, NULL, NULL, NULL, ?, ?)
                """,
                (session_id, report_json, initial_status, now, now),
            )
            if serialized_event is not None:
                self._upsert_outbox(
                    connection,
                    event_key=self.build_base_outbox_event_key(
                        session_id=session_id,
                        event_type=serialized_event.event_type,
                    ),
                    session_id=session_id,
                    case_id=serialized_event.case_id,
                    student_id=serialized_event.student_id,
                    event_type=serialized_event.event_type,
                    payload_json=serialized_event.payload_json,
                    report_revision=1,
                    now=now,
                )
            created = self._select_stored_report(connection, session_id)
        assert created is not None
        return _stored_report_from_row(created)

    def save_report(self, report: dict[str, Any]) -> None:
        """Compatibility writer for existing callers.

        New enrichment code should use ``create_base_report`` followed by the
        claim/CAS methods below. This writer deliberately ignores a stale pending
        snapshot when a terminal enriched report is already stored.
        """

        session_id, report_json = _serialize_report(report)
        incoming_status = _inferred_enrichment_status(report)
        self._initialize()
        now = _utc_iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select_stored_report(connection, session_id)
            if row is None:
                connection.execute(
                    """
                    INSERT INTO reports (
                        session_id,
                        report_json,
                        revision,
                        enrichment_status,
                        enrichment_retry_count,
                        enrichment_claim_token,
                        enrichment_lease_expires_at,
                        enrichment_last_error,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, 1, ?, 0, NULL, NULL, NULL, ?, ?)
                    """,
                    (session_id, report_json, incoming_status, now, now),
                )
                return

            stored = _stored_report_from_row(row)
            if stored.payload == report:
                return
            if _would_regress_enrichment(stored, incoming_status, report):
                return
            connection.execute(
                """
                UPDATE reports
                SET
                    report_json = ?,
                    revision = revision + 1,
                    enrichment_status = ?,
                    enrichment_claim_token = NULL,
                    enrichment_lease_expires_at = NULL,
                    enrichment_last_error = CASE WHEN ? = 'failed'
                        THEN enrichment_last_error
                        ELSE NULL
                    END,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (report_json, incoming_status, incoming_status, now, session_id),
            )

    def get_stored_report(self, session_id: str) -> StoredReport | None:
        self._initialize()
        with self._connect() as connection:
            row = self._select_stored_report(connection, session_id)
        return None if row is None else _stored_report_from_row(row)

    def get_report(self, session_id: str) -> dict[str, Any] | None:
        stored = self.get_stored_report(session_id)
        return None if stored is None else stored.payload

    def list_reports(self) -> list[dict[str, Any]]:
        self._initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT report_json FROM reports ORDER BY rowid DESC",
            ).fetchall()
        return [_decode_json_object(row[0], context="persisted report") for row in rows]

    def claim_report_enrichment(
        self,
        session_id: str,
        *,
        lease_seconds: int = DEFAULT_ENRICHMENT_LEASE_SECONDS,
        now: datetime | None = None,
    ) -> ReportEnrichmentClaim | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        claimed_at = _as_utc(now)
        claimed_at_iso = claimed_at.isoformat()
        lease_expires_at = (claimed_at + timedelta(seconds=lease_seconds)).isoformat()
        claim_token = uuid4().hex
        self._initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select_stored_report(connection, session_id)
            if row is None:
                return None
            stored = _stored_report_from_row(row)
            if stored.enrichment_status == "completed":
                return None
            if (
                stored.enrichment_status == "claimed"
                and stored.enrichment_lease_expires_at is not None
                and stored.enrichment_lease_expires_at > claimed_at_iso
            ):
                return None

            is_retry = stored.enrichment_status in {"claimed", "failed"}
            retry_count = stored.enrichment_retry_count + int(is_retry)
            cursor = connection.execute(
                """
                UPDATE reports
                SET
                    revision = revision + 1,
                    enrichment_status = 'claimed',
                    enrichment_retry_count = ?,
                    enrichment_claim_token = ?,
                    enrichment_lease_expires_at = ?,
                    enrichment_last_error = NULL,
                    updated_at = ?
                WHERE session_id = ?
                  AND revision = ?
                  AND enrichment_status != 'completed'
                  AND (
                      enrichment_status != 'claimed'
                      OR enrichment_lease_expires_at IS NULL
                      OR enrichment_lease_expires_at <= ?
                  )
                """,
                (
                    retry_count,
                    claim_token,
                    lease_expires_at,
                    claimed_at_iso,
                    session_id,
                    stored.revision,
                    claimed_at_iso,
                ),
            )
            if cursor.rowcount != 1:
                return None
            expected_revision = stored.revision + 1
        return ReportEnrichmentClaim(
            session_id=session_id,
            report=stored.payload,
            expected_revision=expected_revision,
            claim_token=claim_token,
            lease_expires_at=lease_expires_at,
            retry_count=retry_count,
        )

    def complete_report_enrichment(
        self,
        session_id: str,
        report: dict[str, Any],
        *,
        expected_revision: int,
        claim_token: str,
        case_id: str,
        student_id: str,
        event_type: str,
        event_payload: dict[str, Any],
        now: datetime | None = None,
    ) -> StoredReport:
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        if not claim_token:
            raise ValueError("claim_token is required")
        if not case_id:
            raise ValueError("case_id is required")
        if not student_id:
            raise ValueError("student_id is required")
        if not event_type:
            raise ValueError("event_type is required")
        serialized_session_id, report_json = _serialize_report(report)
        if serialized_session_id != session_id:
            raise ValueError("report session_id does not match")
        if _inferred_enrichment_status(report) != "completed":
            raise ValueError("completed enrichment must contain a terminal report")
        event_payload_json = _serialize_json_object(event_payload, context="outbox event payload")
        completed_at = _utc_iso(now)
        completed_revision = expected_revision + 1
        event_key = self.build_outbox_event_key(
            session_id=session_id,
            event_type=event_type,
            report_revision=completed_revision,
        )
        self._initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE reports
                SET
                    report_json = ?,
                    revision = revision + 1,
                    enrichment_status = 'completed',
                    enrichment_claim_token = NULL,
                    enrichment_lease_expires_at = NULL,
                    enrichment_last_error = NULL,
                    updated_at = ?
                WHERE session_id = ?
                  AND revision = ?
                  AND enrichment_status = 'claimed'
                  AND enrichment_claim_token = ?
                """,
                (report_json, completed_at, session_id, expected_revision, claim_token),
            )
            if cursor.rowcount != 1:
                self._raise_claim_conflict(
                    connection,
                    session_id,
                    expected_revision=expected_revision,
                )
            self._upsert_outbox(
                connection,
                event_key=event_key,
                session_id=session_id,
                case_id=case_id,
                student_id=student_id,
                event_type=event_type,
                payload_json=event_payload_json,
                report_revision=completed_revision,
                now=completed_at,
            )
            row = self._select_stored_report(connection, session_id)
        assert row is not None
        return _stored_report_from_row(row)

    def fail_report_enrichment(
        self,
        session_id: str,
        *,
        expected_revision: int,
        claim_token: str,
        error_message: str,
        case_id: str,
        student_id: str,
        event_type: str,
        event_payload: dict[str, Any],
        failed_report: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> StoredReport:
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        if not claim_token:
            raise ValueError("claim_token is required")
        if not case_id:
            raise ValueError("case_id is required")
        if not student_id:
            raise ValueError("student_id is required")
        if not event_type:
            raise ValueError("event_type is required")
        failed_report_json: str | None = None
        if failed_report is not None:
            serialized_session_id, failed_report_json = _serialize_report(failed_report)
            if serialized_session_id != session_id:
                raise ValueError("report session_id does not match")
        event_payload_json = _serialize_json_object(event_payload, context="outbox event payload")
        failed_at = _utc_iso(now)
        failed_revision = expected_revision + 1
        event_key = self.build_outbox_event_key(
            session_id=session_id,
            event_type=event_type,
            report_revision=failed_revision,
        )
        self._initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE reports
                SET
                    report_json = COALESCE(?, report_json),
                    revision = revision + 1,
                    enrichment_status = 'failed',
                    enrichment_claim_token = NULL,
                    enrichment_lease_expires_at = NULL,
                    enrichment_last_error = ?,
                    updated_at = ?
                WHERE session_id = ?
                  AND revision = ?
                  AND enrichment_status = 'claimed'
                  AND enrichment_claim_token = ?
                """,
                (
                    failed_report_json,
                    error_message,
                    failed_at,
                    session_id,
                    expected_revision,
                    claim_token,
                ),
            )
            if cursor.rowcount != 1:
                self._raise_claim_conflict(
                    connection,
                    session_id,
                    expected_revision=expected_revision,
                )
            self._upsert_outbox(
                connection,
                event_key=event_key,
                session_id=session_id,
                case_id=case_id,
                student_id=student_id,
                event_type=event_type,
                payload_json=event_payload_json,
                report_revision=failed_revision,
                now=failed_at,
            )
            row = self._select_stored_report(connection, session_id)
        assert row is not None
        return _stored_report_from_row(row)

    def list_pending_outbox(self, *, limit: int = 100) -> list[ReportOutboxItem]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        self._initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    event_key,
                    session_id,
                    case_id,
                    student_id,
                    event_type,
                    payload_json,
                    report_revision,
                    created_at,
                    updated_at,
                    acknowledged_at
                FROM report_outbox
                WHERE acknowledged_at IS NULL
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_outbox_item_from_row(row) for row in rows]

    def acknowledge_outbox(
        self,
        event_key: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        if not event_key:
            raise ValueError("event_key is required")
        acknowledged_at = _utc_iso(now)
        self._initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE report_outbox
                SET acknowledged_at = ?, updated_at = ?
                WHERE event_key = ? AND acknowledged_at IS NULL
                """,
                (acknowledged_at, acknowledged_at, event_key),
            )
        return cursor.rowcount == 1

    @staticmethod
    def build_base_outbox_event_key(
        *,
        session_id: str,
        event_type: str,
    ) -> str:
        if not session_id:
            raise ValueError("session_id is required")
        if not event_type:
            raise ValueError("event_type is required")
        return f"report:{session_id}:{event_type}:base"

    @staticmethod
    def build_outbox_event_key(
        *,
        session_id: str,
        event_type: str,
        report_revision: int,
    ) -> str:
        if not session_id:
            raise ValueError("session_id is required")
        if not event_type:
            raise ValueError("event_type is required")
        if report_revision < 1:
            raise ValueError("report_revision must be positive")
        return f"report:{session_id}:{event_type}:revision:{report_revision}"

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._initialization_lock:
            if self._initialized:
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            now = _utc_iso()
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS reports (
                        session_id TEXT PRIMARY KEY,
                        report_json TEXT NOT NULL,
                        revision INTEGER NOT NULL DEFAULT 1,
                        enrichment_status TEXT NOT NULL DEFAULT 'completed',
                        enrichment_retry_count INTEGER NOT NULL DEFAULT 0,
                        enrichment_claim_token TEXT,
                        enrichment_lease_expires_at TEXT,
                        enrichment_last_error TEXT,
                        created_at TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(reports)").fetchall()
                }
                status_was_added = "enrichment_status" not in columns
                migrations = {
                    "revision": "INTEGER NOT NULL DEFAULT 1",
                    "enrichment_status": "TEXT NOT NULL DEFAULT 'completed'",
                    "enrichment_retry_count": "INTEGER NOT NULL DEFAULT 0",
                    "enrichment_claim_token": "TEXT",
                    "enrichment_lease_expires_at": "TEXT",
                    "enrichment_last_error": "TEXT",
                    "created_at": "TEXT NOT NULL DEFAULT ''",
                    "updated_at": "TEXT NOT NULL DEFAULT ''",
                }
                for column, definition in migrations.items():
                    if column not in columns:
                        connection.execute(f"ALTER TABLE reports ADD COLUMN {column} {definition}")
                connection.execute(
                    """
                    UPDATE reports
                    SET
                        created_at = CASE WHEN created_at = '' THEN ? ELSE created_at END,
                        updated_at = CASE WHEN updated_at = '' THEN ? ELSE updated_at END
                    """,
                    (now, now),
                )
                if status_was_added:
                    for session_id, report_json in connection.execute(
                        "SELECT session_id, report_json FROM reports"
                    ).fetchall():
                        report = _decode_json_object(
                            report_json,
                            context=f"persisted report for {session_id}",
                        )
                        connection.execute(
                            """
                            UPDATE reports
                            SET enrichment_status = ?
                            WHERE session_id = ?
                            """,
                            (_inferred_enrichment_status(report), session_id),
                        )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS report_outbox (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_key TEXT NOT NULL UNIQUE,
                        session_id TEXT NOT NULL,
                        case_id TEXT NOT NULL,
                        student_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        report_revision INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        acknowledged_at TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS report_outbox_pending_idx
                    ON report_outbox (acknowledged_at, id)
                    """
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
    def _select_stored_report(
        connection: sqlite3.Connection,
        session_id: str,
    ) -> tuple[Any, ...] | None:
        return connection.execute(
            """
            SELECT
                report_json,
                revision,
                enrichment_status,
                enrichment_retry_count,
                enrichment_claim_token,
                enrichment_lease_expires_at,
                enrichment_last_error
            FROM reports
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

    @staticmethod
    def _raise_claim_conflict(
        connection: sqlite3.Connection,
        session_id: str,
        *,
        expected_revision: int,
    ) -> None:
        row = connection.execute(
            "SELECT revision FROM reports WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise ReportNotFoundError(session_id)
        raise ReportClaimLostError(
            session_id,
            expected_revision=expected_revision,
            current_revision=int(row[0]),
        )

    @staticmethod
    def _upsert_outbox(
        connection: sqlite3.Connection,
        *,
        event_key: str,
        session_id: str,
        case_id: str,
        student_id: str,
        event_type: str,
        payload_json: str,
        report_revision: int,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO report_outbox (
                event_key,
                session_id,
                case_id,
                student_id,
                event_type,
                payload_json,
                report_revision,
                created_at,
                updated_at,
                acknowledged_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(event_key) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            WHERE
                report_outbox.acknowledged_at IS NULL
                AND report_outbox.session_id = excluded.session_id
                AND report_outbox.case_id = excluded.case_id
                AND report_outbox.student_id = excluded.student_id
                AND report_outbox.event_type = excluded.event_type
                AND report_outbox.report_revision = excluded.report_revision
            """,
            (
                event_key,
                session_id,
                case_id,
                student_id,
                event_type,
                payload_json,
                report_revision,
                now,
                now,
            ),
        )


report_store = ReportStore()


def _serialize_report(report: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(report, dict):
        raise TypeError("report must be a dict")
    session_id = str(report.get("session_id") or "")
    if not session_id:
        raise ValueError("report session_id is required")
    return session_id, _serialize_json_object(report, context="report")


def _serialize_json_object(value: dict[str, Any], *, context: str) -> str:
    if not isinstance(value, dict):
        raise TypeError(f"{context} must be a dict")
    return json.dumps(value, ensure_ascii=False)


def _serialize_outbox_event(
    report: dict[str, Any],
    outbox_event: ReportOutboxEvent | None,
) -> _SerializedOutboxEvent | None:
    if outbox_event is None:
        return None
    if not outbox_event.case_id:
        raise ValueError("outbox event case_id is required")
    if not outbox_event.student_id:
        raise ValueError("outbox event student_id is required")
    if not outbox_event.event_type:
        raise ValueError("outbox event event_type is required")
    report_case_id = str(report.get("case_id") or "")
    if report_case_id and report_case_id != outbox_event.case_id:
        raise ValueError("outbox event case_id does not match report")
    report_student_id = str(report.get("student_id") or "")
    if report_student_id and report_student_id != outbox_event.student_id:
        raise ValueError("outbox event student_id does not match report")
    return _SerializedOutboxEvent(
        case_id=outbox_event.case_id,
        student_id=outbox_event.student_id,
        event_type=outbox_event.event_type,
        payload_json=_serialize_json_object(
            outbox_event.payload,
            context="outbox event payload",
        ),
    )


def _decode_json_object(value: str, *, context: str) -> dict[str, Any]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError(f"{context} must be a JSON object")
    return decoded


def _stored_report_from_row(row: tuple[Any, ...]) -> StoredReport:
    status = str(row[2])
    if status not in {"pending", "claimed", "completed", "failed"}:
        raise ValueError(f"invalid report enrichment status: {status}")
    return StoredReport(
        payload=_decode_json_object(row[0], context="persisted report"),
        revision=int(row[1]),
        enrichment_status=cast(EnrichmentStatus, status),
        enrichment_retry_count=int(row[3]),
        enrichment_claim_token=None if row[4] is None else str(row[4]),
        enrichment_lease_expires_at=None if row[5] is None else str(row[5]),
        enrichment_last_error=None if row[6] is None else str(row[6]),
    )


def _outbox_item_from_row(row: tuple[Any, ...]) -> ReportOutboxItem:
    return ReportOutboxItem(
        event_key=str(row[0]),
        session_id=str(row[1]),
        case_id=str(row[2]),
        student_id=str(row[3]),
        event_type=str(row[4]),
        payload=_decode_json_object(row[5], context=f"outbox event {row[0]}"),
        report_revision=int(row[6]),
        created_at=str(row[7]),
        updated_at=str(row[8]),
        acknowledged_at=None if row[9] is None else str(row[9]),
    )


def _initial_enrichment_status(
    report: dict[str, Any],
    *,
    enrichment_required: bool | None,
) -> EnrichmentStatus:
    inferred = _inferred_enrichment_status(report)
    if enrichment_required is None:
        return inferred
    candidate = report.get("personal_skill_candidate")
    candidate_status = candidate.get("status") if isinstance(candidate, dict) else None
    if enrichment_required and candidate_status in {"approved", "generated", "rejected"}:
        raise ValueError("terminal report cannot require enrichment")
    return "pending" if enrichment_required else "completed"


def _inferred_enrichment_status(report: dict[str, Any]) -> EnrichmentStatus:
    candidate = report.get("personal_skill_candidate")
    candidate_status = candidate.get("status") if isinstance(candidate, dict) else None
    if candidate_status == "generation_pending":
        return "pending"
    if candidate_status == "generation_failed":
        return "failed"
    return "completed"


def _would_regress_enrichment(
    stored: StoredReport,
    incoming_status: EnrichmentStatus,
    incoming_report: dict[str, Any],
) -> bool:
    if stored.enrichment_status == "claimed":
        return True
    if stored.enrichment_status == "completed" and incoming_status != "completed":
        return True
    stored_candidate = stored.payload.get("personal_skill_candidate")
    incoming_candidate = incoming_report.get("personal_skill_candidate")
    stored_candidate_status = stored_candidate.get("status") if isinstance(stored_candidate, dict) else None
    incoming_candidate_status = (
        incoming_candidate.get("status") if isinstance(incoming_candidate, dict) else None
    )
    terminal_candidate_statuses = {"approved", "generated", "rejected"}
    return (
        stored_candidate_status in terminal_candidate_statuses
        and incoming_candidate_status not in terminal_candidate_statuses
    )


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


def _utc_iso(value: datetime | None = None) -> str:
    return _as_utc(value).isoformat()
