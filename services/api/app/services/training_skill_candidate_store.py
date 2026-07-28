from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.training_skill_context_safety import candidate_with_context_safety_review

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "training_skill_candidates.sqlite3"
DATABASE_SCHEMA_VERSION = 1


class TrainingSkillCandidateDeletedError(RuntimeError):
    def __init__(self, candidate_id: str) -> None:
        super().__init__(candidate_id)
        self.candidate_id = candidate_id


class TrainingSkillCandidateOwnershipError(RuntimeError):
    def __init__(self, candidate_id: str) -> None:
        super().__init__(candidate_id)
        self.candidate_id = candidate_id


class TrainingSkillCandidateStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def save_candidate(self, candidate: dict[str, Any], review: dict[str, Any]) -> None:
        self._initialize()
        payload = {**candidate, "review": review}
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            candidate_id = str(candidate["candidate_id"])
            if self._is_candidate_deleted(connection, candidate_id):
                raise TrainingSkillCandidateDeletedError(candidate_id)
            connection.execute(
                """
                INSERT INTO training_skill_candidates (candidate_id, candidate_json)
                VALUES (?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET candidate_json = excluded.candidate_json
                """,
                (candidate_id, json.dumps(payload, ensure_ascii=False)),
            )

    def save_candidate_unless_reviewed(self, candidate: dict[str, Any], review: dict[str, Any]) -> bool:
        existing_candidate = self.get_candidate(str(candidate["candidate_id"]))
        if existing_candidate is not None and existing_candidate["review"]["status"] in {"approved", "rejected"}:
            return False
        self.save_candidate(candidate, review)
        return True

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT candidate_json FROM training_skill_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def list_candidate_summaries(self) -> list[dict[str, Any]]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT candidate_json FROM training_skill_candidates ORDER BY id",
            ).fetchall()
        return [_candidate_summary(candidate_with_context_safety_review(json.loads(row[0]))) for row in rows]

    def approve_candidate(self, candidate_id: str, reviewer_id: str) -> bool:
        return self._set_review_status(candidate_id, reviewer_id, "approved")

    def reject_candidate(self, candidate_id: str, reviewer_id: str) -> bool:
        return self._set_review_status(candidate_id, reviewer_id, "rejected")

    def delete_personal_candidate(
        self,
        *,
        candidate_id: str,
        owner_student_id: str,
        source_session_id: str,
    ) -> bool:
        """Delete one deterministic personal candidate and persist a write fence."""

        _validate_personal_candidate_delete_identity(
            candidate_id=candidate_id,
            owner_student_id=owner_student_id,
            source_session_id=source_session_id,
        )
        self._initialize()
        deleted_at = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            tombstone = connection.execute(
                """
                SELECT scope, owner_student_id, source_session_id
                FROM training_skill_candidate_tombstones
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if tombstone is not None:
                if tuple(str(value) for value in tombstone) != (
                    "personal",
                    owner_student_id,
                    source_session_id,
                ):
                    raise TrainingSkillCandidateOwnershipError(candidate_id)
                return False

            row = connection.execute(
                """
                SELECT candidate_json
                FROM training_skill_candidates
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if row is not None:
                candidate = _decode_candidate(row[0], candidate_id=candidate_id)
                if (
                    str(candidate.get("candidate_id", "")) != candidate_id
                    or str(candidate.get("scope", "")) != "personal"
                    or str(candidate.get("owner_student_id", "")) != owner_student_id
                    or str(candidate.get("source_session_id", "")) != source_session_id
                ):
                    raise TrainingSkillCandidateOwnershipError(candidate_id)

            connection.execute(
                """
                INSERT INTO training_skill_candidate_tombstones (
                    candidate_id,
                    scope,
                    owner_student_id,
                    source_session_id,
                    deleted_at
                )
                VALUES (?, 'personal', ?, ?, ?)
                """,
                (candidate_id, owner_student_id, source_session_id, deleted_at),
            )
            cursor = connection.execute(
                """
                DELETE FROM training_skill_candidates
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            )
        return cursor.rowcount == 1

    def _set_review_status(self, candidate_id: str, reviewer_id: str, status: str) -> bool:
        candidate = self.get_candidate(candidate_id)
        if candidate is None or candidate["review"]["status"] != "ready_for_review":
            return False
        normalized_candidate = candidate_with_context_safety_review(candidate)
        if normalized_candidate["review"]["status"] != "ready_for_review":
            candidate = normalized_candidate
            with sqlite3.connect(self.database_path) as connection:
                connection.execute(
                    "UPDATE training_skill_candidates SET candidate_json = ? WHERE candidate_id = ?",
                    (json.dumps(candidate, ensure_ascii=False), candidate_id),
                )
            return False
        candidate["review"] = {**candidate["review"], "status": status, "reviewer_id": reviewer_id}
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE training_skill_candidates SET candidate_json = ? WHERE candidate_id = ?",
                (json.dumps(candidate, ensure_ascii=False), candidate_id),
            )
        return True

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_skill_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL UNIQUE,
                    candidate_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_skill_candidate_tombstones (
                    candidate_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    owner_student_id TEXT NOT NULL,
                    source_session_id TEXT NOT NULL,
                    deleted_at TEXT NOT NULL
                )
                """
            )
            connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")

    @staticmethod
    def _is_candidate_deleted(
        connection: sqlite3.Connection,
        candidate_id: str,
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM training_skill_candidate_tombstones
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        ).fetchone()
        return row is not None


def _validate_personal_candidate_delete_identity(
    *,
    candidate_id: str,
    owner_student_id: str,
    source_session_id: str,
) -> None:
    if (
        not owner_student_id
        or not source_session_id
        or candidate_id != f"personal_skill_candidate_{source_session_id}"
    ):
        raise TrainingSkillCandidateOwnershipError(candidate_id)


def _decode_candidate(value: str, *, candidate_id: str) -> dict[str, Any]:
    candidate = json.loads(value)
    if not isinstance(candidate, dict):
        raise TrainingSkillCandidateOwnershipError(candidate_id)
    return candidate


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    review = candidate["review"]
    return {
        "candidate_id": candidate["candidate_id"],
        "trigger_item_id": candidate["trigger_item_id"],
        "trigger_item_ids": list(candidate.get("trigger_item_ids", [])),
        "case_ids": list(candidate.get("case_ids", [])),
        "skill_type": str(candidate.get("skill_type", "")),
        "stage_scope": list(candidate.get("stage_scope", [])),
        "effect_status": str(candidate.get("effect_status", "")),
        "related_recommendations": list(candidate.get("related_recommendations", [])),
        "title": candidate["title"],
        "status": review["status"],
        "regression_passed": review["regression_passed"],
        "source_report_count": candidate["source_report_count"],
        "support_count": candidate["support_count"],
    }


training_skill_candidate_store = TrainingSkillCandidateStore()
