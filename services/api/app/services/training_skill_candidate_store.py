from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "training_skill_candidates.sqlite3"


class TrainingSkillCandidateStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def save_candidate(self, candidate: dict[str, Any], review: dict[str, Any]) -> None:
        self._initialize()
        payload = {**candidate, "review": review}
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO training_skill_candidates (candidate_id, candidate_json)
                VALUES (?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET candidate_json = excluded.candidate_json
                """,
                (candidate["candidate_id"], json.dumps(payload, ensure_ascii=False)),
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
        return [_candidate_summary(json.loads(row[0])) for row in rows]

    def approve_candidate(self, candidate_id: str, reviewer_id: str) -> bool:
        return self._set_review_status(candidate_id, reviewer_id, "approved")

    def reject_candidate(self, candidate_id: str, reviewer_id: str) -> bool:
        return self._set_review_status(candidate_id, reviewer_id, "rejected")

    def _set_review_status(self, candidate_id: str, reviewer_id: str, status: str) -> bool:
        candidate = self.get_candidate(candidate_id)
        if candidate is None or candidate["review"]["status"] != "ready_for_review":
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


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    review = candidate["review"]
    return {
        "candidate_id": candidate["candidate_id"],
        "trigger_item_id": candidate["trigger_item_id"],
        "title": candidate["title"],
        "status": review["status"],
        "regression_passed": review["regression_passed"],
        "source_report_count": candidate["source_report_count"],
        "support_count": candidate["support_count"],
    }


training_skill_candidate_store = TrainingSkillCandidateStore()
