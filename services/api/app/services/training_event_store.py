from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "training_events.sqlite3"
DATABASE_SCHEMA_VERSION = 1
DATABASE_BUSY_TIMEOUT_MILLISECONDS = 10_000


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
                connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")
            self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=DATABASE_BUSY_TIMEOUT_MILLISECONDS / 1000,
        )
        connection.execute(f"PRAGMA busy_timeout = {DATABASE_BUSY_TIMEOUT_MILLISECONDS}")
        return connection


training_event_store = TrainingEventStore()
