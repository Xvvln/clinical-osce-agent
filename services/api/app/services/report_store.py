from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "reports.sqlite3"


class ReportStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def save_report(self, report: dict[str, Any]) -> None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO reports (session_id, report_json)
                VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET report_json = excluded.report_json
                """,
                (report["session_id"], json.dumps(report, ensure_ascii=False)),
            )

    def get_report(self, session_id: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT report_json FROM reports WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def list_reports(self) -> list[dict[str, Any]]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT report_json FROM reports ORDER BY rowid DESC",
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    session_id TEXT PRIMARY KEY,
                    report_json TEXT NOT NULL
                )
                """
            )


report_store = ReportStore()
