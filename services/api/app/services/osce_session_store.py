from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.osce_session_service import OsceSession

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "osce_sessions.sqlite3"


class OsceSessionStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def save_session(self, session: OsceSession) -> None:
        self._initialize()
        now = datetime.now(UTC).isoformat()
        payload = asdict(session)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO osce_sessions (session_id, user_id, case_id, stage, session_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    case_id = excluded.case_id,
                    stage = excluded.stage,
                    session_json = excluded.session_json,
                    updated_at = excluded.updated_at
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

    def get_session_payload(self, session_id: str) -> dict[str, object] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT session_json FROM osce_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def list_user_session_summaries(self, user_id: str) -> list[dict[str, object]]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT session_id, case_id, stage, created_at, updated_at
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
            }
            for row in rows
        ]

    def list_session_summaries(self) -> list[dict[str, object]]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT session_id, user_id, case_id, stage, created_at, updated_at
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
            }
            for row in rows
        ]

    def delete_session(self, session_id: str) -> bool:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            cursor = connection.execute("DELETE FROM osce_sessions WHERE session_id = ?", (session_id,))
        return cursor.rowcount > 0

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS osce_sessions (
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


osce_session_store = OsceSessionStore()
