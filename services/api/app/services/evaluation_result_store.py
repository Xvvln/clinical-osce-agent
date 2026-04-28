from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.services.evaluation_runner import EvaluationBatchResult

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "evaluation_results.sqlite3"


class EvaluationResultStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def save_batch_result(self, batch_id: str, batch_result: EvaluationBatchResult) -> None:
        self._initialize()
        payload = _serialize_batch_result(batch_id, batch_result)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO evaluation_results (batch_id, result_json)
                VALUES (?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET result_json = excluded.result_json
                """,
                (batch_id, json.dumps(payload, ensure_ascii=False)),
            )

    def get_batch_result(self, batch_id: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT result_json FROM evaluation_results WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def list_batch_summaries(self) -> list[dict[str, Any]]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT result_json FROM evaluation_results ORDER BY id",
            ).fetchall()
        return [
            {
                "batch_id": result["batch_id"],
                "total_cases": result["total_cases"],
                "passed_cases": result["passed_cases"],
                "failed_cases": result["failed_cases"],
                "passed": result["passed"],
            }
            for result in (json.loads(row[0]) for row in rows)
        ]

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evaluation_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL UNIQUE,
                    result_json TEXT NOT NULL
                )
                """
            )


def _serialize_batch_result(batch_id: str, batch_result: EvaluationBatchResult) -> dict[str, Any]:
    return {"batch_id": batch_id, **asdict(batch_result)}


evaluation_result_store = EvaluationResultStore()
