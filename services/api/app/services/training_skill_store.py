from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "training_skills.sqlite3"


class TrainingSkillStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def enable_candidate(self, candidate: dict[str, Any]) -> bool:
        if candidate.get("review", {}).get("status") != "approved":
            return False
        self._initialize()
        skill = _skill_from_candidate(candidate)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO training_skills (skill_id, skill_json)
                VALUES (?, ?)
                ON CONFLICT(skill_id) DO UPDATE SET skill_json = excluded.skill_json
                """,
                (skill["skill_id"], json.dumps(skill, ensure_ascii=False)),
            )
        return True

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT skill_json FROM training_skills WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def list_enabled_skills(self) -> list[dict[str, Any]]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute("SELECT skill_json FROM training_skills ORDER BY id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL UNIQUE,
                    skill_json TEXT NOT NULL
                )
                """
            )


def _skill_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "skill_id": f"skill_{candidate['trigger_item_id']}",
        "source_candidate_id": candidate["candidate_id"],
        "trigger_item_id": candidate["trigger_item_id"],
        "title": candidate["title"],
        "description": candidate["description"],
        "suggested_strategy": candidate["suggested_strategy"],
        "status": "enabled",
        "source_report_count": candidate["source_report_count"],
        "support_count": candidate["support_count"],
    }


training_skill_store = TrainingSkillStore()
