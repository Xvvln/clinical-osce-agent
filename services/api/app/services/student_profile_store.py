from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "student_profiles.sqlite3"


class StudentProfileStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def save_profile(self, student_id: str, profile: dict[str, Any]) -> None:
        self._initialize()
        profile_payload = {**profile, "student_id": student_id}
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO student_profiles (student_id, profile_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(student_id) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    updated_at = excluded.updated_at
                """,
                (student_id, json.dumps(profile_payload, ensure_ascii=False), now),
            )

    def get_profile(self, student_id: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT profile_json FROM student_profiles WHERE student_id = ?",
                (student_id,),
            ).fetchone()
        if row is None:
            return None
        profile = json.loads(row[0])
        if not isinstance(profile, dict):
            return None
        profile["student_id"] = student_id
        return profile

    def delete_profile(self, student_id: str) -> bool:
        if not student_id:
            raise ValueError("student_id is required")
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            cursor = connection.execute(
                "DELETE FROM student_profiles WHERE student_id = ?",
                (student_id,),
            )
        return cursor.rowcount == 1

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS student_profiles (
                    student_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )


student_profile_store = StudentProfileStore()
