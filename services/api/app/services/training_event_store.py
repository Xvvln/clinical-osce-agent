from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "training_events.sqlite3"
DATABASE_SCHEMA_VERSION = 4
DATABASE_BUSY_TIMEOUT_MILLISECONDS = 10_000


class TrainingEventStreamDeletedError(RuntimeError):
    def __init__(self, session_id: str) -> None:
        super().__init__(session_id)
        self.session_id = session_id


class TrainingEventDeletedSkillSourceError(RuntimeError):
    def __init__(self, source_session_id: str) -> None:
        super().__init__(source_session_id)
        self.source_session_id = source_session_id


class TrainingEventReferenceOwnershipError(RuntimeError):
    def __init__(self, source_session_id: str) -> None:
        super().__init__(source_session_id)
        self.source_session_id = source_session_id


class TrainingEventStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path
        self._initialization_lock = Lock()
        self._initialized = False

    def append_event(
        self,
        session_id: str,
        case_id: str,
        student_id: str,
        event_type: str,
        payload: dict[str, Any],
        event_key: str | None = None,
    ) -> bool:
        """Return True for a new row; False means a keyed replay was already persisted."""
        self._initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._is_stream_deleted(connection, session_id):
                raise TrainingEventStreamDeletedError(session_id)
            if self._raise_if_deleted_skill_source(
                connection,
                student_id=student_id,
                event_type=event_type,
                payload=payload,
            ):
                return False
            cursor = connection.execute(
                """
                INSERT INTO training_events (
                    session_id,
                    case_id,
                    student_id,
                    event_type,
                    event_key,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_key) WHERE event_key IS NOT NULL DO NOTHING
                """,
                (
                    session_id,
                    case_id,
                    student_id,
                    event_type,
                    event_key,
                    json.dumps(payload, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return cursor.rowcount == 1

    def delete_event_streams(self, session_ids: list[str]) -> int:
        """Fence and delete the exact event streams in one transaction."""

        unique_session_ids = list(
            dict.fromkeys(
                str(session_id)
                for session_id in session_ids
                if str(session_id)
            )
        )
        if not unique_session_ids:
            return 0

        self._initialize()
        deleted_at = datetime.now(UTC).isoformat()
        deleted_count = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """
                INSERT INTO training_event_stream_tombstones (session_id, deleted_at)
                VALUES (?, ?)
                ON CONFLICT(session_id) DO NOTHING
                """,
                [(session_id, deleted_at) for session_id in unique_session_ids],
            )
            for start in range(0, len(unique_session_ids), 900):
                chunk = unique_session_ids[start:start + 900]
                placeholders = ",".join("?" for _ in chunk)
                cursor = connection.execute(
                    f"DELETE FROM training_events WHERE session_id IN ({placeholders})",
                    chunk,
                )
                deleted_count += cursor.rowcount
        return deleted_count

    def validate_skill_source_references(
        self,
        *,
        source_session_id: str,
        owner_student_id: str,
        personal_skill_id: str,
    ) -> None:
        _validate_deleted_skill_source_identity(
            source_session_id=source_session_id,
            owner_student_id=owner_student_id,
            personal_skill_id=personal_skill_id,
        )
        self._initialize()
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT owner_student_id, personal_skill_id
                FROM training_deleted_skill_sources
                WHERE source_session_id = ?
                """,
                (source_session_id,),
            ).fetchone()
            if existing is not None and tuple(str(value) for value in existing) != (
                owner_student_id,
                personal_skill_id,
            ):
                raise TrainingEventReferenceOwnershipError(source_session_id)
            rows = connection.execute(
                """
                SELECT student_id, payload_json
                FROM training_events
                ORDER BY id
                """
            ).fetchall()
        for raw_student_id, raw_payload in rows:
            payload = _decode_event_payload(raw_payload)
            if personal_skill_id not in _payload_referenced_skill_ids(
                payload,
                skill_ids={personal_skill_id},
            ):
                continue
            _validate_personal_skill_event_owner(
                source_session_id=source_session_id,
                owner_student_id=owner_student_id,
                event_student_id=str(raw_student_id),
                payload=payload,
            )

    def delete_skill_source_references(
        self,
        *,
        source_session_id: str,
        owner_student_id: str,
        personal_skill_id: str,
        affected_global_skill_ids: list[str] | None = None,
    ) -> int:
        _validate_deleted_skill_source_identity(
            source_session_id=source_session_id,
            owner_student_id=owner_student_id,
            personal_skill_id=personal_skill_id,
        )
        normalized_global_skill_ids = _normalized_skill_ids(
            affected_global_skill_ids,
            excluded_skill_id=personal_skill_id,
        )
        global_skill_id_set = set(normalized_global_skill_ids)

        self._initialize()
        deleted_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT
                    owner_student_id,
                    personal_skill_id,
                    affected_global_skill_ids_json
                FROM training_deleted_skill_sources
                WHERE source_session_id = ?
                """,
                (source_session_id,),
            ).fetchone()
            if existing is not None:
                if (
                    tuple(str(value) for value in existing[:2])
                    != (
                        owner_student_id,
                        personal_skill_id,
                    )
                    or _decode_string_list(existing[2])
                    != normalized_global_skill_ids
                ):
                    raise TrainingEventReferenceOwnershipError(source_session_id)
                return 0

            rows = connection.execute(
                """
                SELECT id, student_id, event_type, payload_json
                FROM training_events
                ORDER BY id
                """
            ).fetchall()
            event_ids_to_delete: list[int] = []
            for (
                raw_event_id,
                raw_student_id,
                _raw_event_type,
                raw_payload,
            ) in rows:
                payload = _decode_event_payload(raw_payload)
                blocked_global_skill_ids = {
                    skill_id
                    for skill_id in global_skill_id_set
                    if not _event_payload_has_explicit_remaining_skill_source(
                        payload,
                        skill_id=skill_id,
                        source_session_id=source_session_id,
                        source_report_id=f"{source_session_id}_report",
                    )
                }
                referenced_skill_ids = _payload_referenced_skill_ids(
                    payload,
                    skill_ids={
                        personal_skill_id,
                        *blocked_global_skill_ids,
                    },
                )
                if not referenced_skill_ids:
                    continue
                if personal_skill_id in referenced_skill_ids:
                    _validate_personal_skill_event_owner(
                        source_session_id=source_session_id,
                        owner_student_id=owner_student_id,
                        event_student_id=str(raw_student_id),
                        payload=payload,
                    )
                event_ids_to_delete.append(int(raw_event_id))

            connection.execute(
                """
                INSERT INTO training_deleted_skill_sources (
                    source_session_id,
                    owner_student_id,
                    personal_skill_id,
                    affected_global_skill_ids_json,
                    deleted_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    source_session_id,
                    owner_student_id,
                    personal_skill_id,
                    json.dumps(normalized_global_skill_ids),
                    deleted_at,
                ),
            )
            if not event_ids_to_delete:
                return 0
            placeholders = ",".join("?" for _ in event_ids_to_delete)
            cursor = connection.execute(
                f"DELETE FROM training_events WHERE id IN ({placeholders})",
                event_ids_to_delete,
            )
        return cursor.rowcount

    def list_session_events(self, session_id: str) -> list[dict[str, Any]]:
        self._initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, case_id, student_id, event_type, event_key, payload_json, created_at
                FROM training_events
                WHERE session_id = ?
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
        return [
            {
                "session_id": row[0],
                "case_id": row[1],
                "student_id": row[2],
                "event_type": row[3],
                "event_key": row[4],
                "payload": json.loads(row[5]),
                "created_at": row[6],
            }
            for row in rows
        ]

    def count_session_events(
        self,
        session_id: str,
        *,
        event_types: list[str],
    ) -> int:
        normalized_event_types = list(
            dict.fromkeys(
                str(event_type)
                for event_type in event_types
                if str(event_type)
            )
        )
        if not normalized_event_types:
            return 0
        self._initialize()
        placeholders = ",".join("?" for _ in normalized_event_types)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM training_events
                WHERE session_id = ?
                  AND event_type IN ({placeholders})
                """,
                (session_id, *normalized_event_types),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def list_events_for_sessions(self, session_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        self._initialize()
        unique_session_ids = list(dict.fromkeys(str(session_id) for session_id in session_ids if str(session_id)))
        events_by_session: dict[str, list[dict[str, Any]]] = {session_id: [] for session_id in unique_session_ids}
        if not unique_session_ids:
            return events_by_session

        rows: list[tuple[str, str, str, str, str | None, str, str]] = []
        with self._connect() as connection:
            for start in range(0, len(unique_session_ids), 900):
                chunk = unique_session_ids[start:start + 900]
                placeholders = ",".join("?" for _ in chunk)
                rows.extend(
                    connection.execute(
                        f"""
                        SELECT session_id, case_id, student_id, event_type, event_key, payload_json, created_at
                        FROM training_events
                        WHERE session_id IN ({placeholders})
                        ORDER BY id
                        """,
                        chunk,
                    ).fetchall()
                )
        for row in rows:
            events_by_session.setdefault(row[0], []).append(
                {
                    "session_id": row[0],
                    "case_id": row[1],
                    "student_id": row[2],
                    "event_type": row[3],
                    "event_key": row[4],
                    "payload": json.loads(row[5]),
                    "created_at": row[6],
                }
            )
        return events_by_session

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
                    CREATE TABLE IF NOT EXISTS training_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        case_id TEXT NOT NULL,
                        student_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        event_key TEXT,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(training_events)").fetchall()
                }
                if "event_key" not in columns:
                    connection.execute("ALTER TABLE training_events ADD COLUMN event_key TEXT")
                connection.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS training_events_event_key_unique
                    ON training_events(event_key)
                    WHERE event_key IS NOT NULL
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS training_event_stream_tombstones (
                        session_id TEXT PRIMARY KEY,
                        deleted_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS training_deleted_skill_sources (
                        source_session_id TEXT PRIMARY KEY,
                        owner_student_id TEXT NOT NULL,
                        personal_skill_id TEXT NOT NULL,
                        affected_global_skill_ids_json TEXT NOT NULL DEFAULT '[]',
                        deleted_at TEXT NOT NULL
                    )
                    """
                )
                deleted_skill_source_columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(training_deleted_skill_sources)"
                    ).fetchall()
                }
                if (
                    "affected_global_skill_ids_json"
                    not in deleted_skill_source_columns
                ):
                    connection.execute(
                        """
                        ALTER TABLE training_deleted_skill_sources
                        ADD COLUMN affected_global_skill_ids_json
                            TEXT NOT NULL DEFAULT '[]'
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
    def _is_stream_deleted(
        connection: sqlite3.Connection,
        session_id: str,
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM training_event_stream_tombstones
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _raise_if_deleted_skill_source(
        connection: sqlite3.Connection,
        *,
        student_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> bool:
        rows = connection.execute(
            """
            SELECT
                source_session_id,
                owner_student_id,
                personal_skill_id,
                affected_global_skill_ids_json
            FROM training_deleted_skill_sources
            """
        ).fetchall()
        for row in rows:
            deleted_source_session_id = str(row[0])
            deleted_owner_student_id = str(row[1])
            deleted_personal_skill_id = str(row[2])
            affected_global_skill_ids = set(_decode_string_list(row[3]))
            blocked_global_skill_ids = {
                skill_id
                for skill_id in affected_global_skill_ids
                if not _event_payload_has_explicit_remaining_skill_source(
                    payload,
                    skill_id=skill_id,
                    source_session_id=deleted_source_session_id,
                    source_report_id=(
                        f"{deleted_source_session_id}_report"
                    ),
                )
            }
            referenced_skill_ids = _payload_referenced_skill_ids(
                payload,
                skill_ids={
                    deleted_personal_skill_id,
                    *blocked_global_skill_ids,
                },
            )
            if not referenced_skill_ids:
                continue
            if deleted_personal_skill_id in referenced_skill_ids:
                _validate_personal_skill_event_owner(
                    source_session_id=deleted_source_session_id,
                    owner_student_id=deleted_owner_student_id,
                    event_student_id=student_id,
                    payload=payload,
                )
            if event_type == "training_skill_applied":
                raise TrainingEventDeletedSkillSourceError(
                    deleted_source_session_id
                )
            return True
        return False


def _validate_deleted_skill_source_identity(
    *,
    source_session_id: str,
    owner_student_id: str,
    personal_skill_id: str,
) -> None:
    if (
        not source_session_id
        or not owner_student_id
        or personal_skill_id != f"skill_personal_{source_session_id}"
    ):
        raise TrainingEventReferenceOwnershipError(source_session_id)


def _validate_personal_skill_event_owner(
    *,
    source_session_id: str,
    owner_student_id: str,
    event_student_id: str,
    payload: dict[str, Any],
) -> None:
    payload_owner = str(payload.get("owner_student_id", ""))
    payload_source_session_id = str(payload.get("source_session_id", ""))
    if (
        event_student_id != owner_student_id
        or (payload_owner and payload_owner != owner_student_id)
        or (
            payload_source_session_id
            and payload_source_session_id != source_session_id
        )
    ):
        raise TrainingEventReferenceOwnershipError(source_session_id)


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


def _decode_string_list(value: object) -> list[str]:
    decoded = json.loads(str(value))
    if not isinstance(decoded, list):
        return []
    return sorted(str(item) for item in decoded if str(item))


def _event_payload_has_explicit_remaining_skill_source(
    payload: dict[str, Any],
    *,
    skill_id: str,
    source_session_id: str,
    source_report_id: str,
) -> bool:
    explicit_references = [
        reference
        for reference in _skill_reference_mappings(
            payload,
            skill_id=skill_id,
        )
        if str(reference.get("source_provenance_schema_version", ""))
        == "training_candidate_sources.v1"
    ]
    return bool(explicit_references) and all(
        _skill_reference_has_explicit_remaining_source(
            reference,
            source_session_id=source_session_id,
            source_report_id=source_report_id,
        )
        for reference in explicit_references
    )


def _skill_reference_mappings(
    value: object,
    *,
    skill_id: str,
) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        matches = (
            [value]
            if str(value.get("skill_id", "")) == skill_id
            else []
        )
        for nested_value in value.values():
            matches.extend(
                _skill_reference_mappings(
                    nested_value,
                    skill_id=skill_id,
                )
            )
        return matches
    if isinstance(value, list):
        matches: list[dict[str, Any]] = []
        for nested_value in value:
            matches.extend(
                _skill_reference_mappings(
                    nested_value,
                    skill_id=skill_id,
                )
            )
        return matches
    return []


def _skill_reference_has_explicit_remaining_source(
    value: dict[str, Any],
    *,
    source_session_id: str,
    source_report_id: str,
) -> bool:
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


def _payload_referenced_skill_ids(
    value: object,
    *,
    skill_ids: set[str],
) -> set[str]:
    if not skill_ids:
        return set()
    if isinstance(value, dict):
        referenced: set[str] = set()
        for nested_value in value.values():
            referenced.update(
                _payload_referenced_skill_ids(
                    nested_value,
                    skill_ids=skill_ids,
                )
            )
        return referenced
    if isinstance(value, list):
        referenced = set()
        for nested_value in value:
            referenced.update(
                _payload_referenced_skill_ids(
                    nested_value,
                    skill_ids=skill_ids,
                )
            )
        return referenced
    normalized = str(value) if value is not None else ""
    return {normalized} if normalized in skill_ids else set()


def _decode_event_payload(value: object) -> dict[str, Any]:
    payload = json.loads(str(value))
    if not isinstance(payload, dict):
        return {}
    return payload


training_event_store = TrainingEventStore()
