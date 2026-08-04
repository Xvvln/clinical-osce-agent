from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "admin_evaluation_config.sqlite3"


class AdminEvaluationConfigStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def ensure_defaults(
        self,
        *,
        evaluation_case: dict[str, Any],
        suite: dict[str, Any],
    ) -> None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO admin_evaluation_cases (case_key, payload_json, is_builtin, updated_at) VALUES (?, ?, 1, ?)",
                (
                    evaluation_case["case_key"],
                    json.dumps(evaluation_case, ensure_ascii=False),
                    _utc_now(),
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO admin_evaluation_suites (suite_id, payload_json, is_builtin, updated_at) VALUES (?, ?, 1, ?)",
                (
                    suite["suite_id"],
                    json.dumps(suite, ensure_ascii=False),
                    _utc_now(),
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO admin_evaluation_schedule (schedule_id, payload_json, updated_at) VALUES ('default', ?, ?)",
                (
                    json.dumps(_default_schedule(str(suite["suite_id"])), ensure_ascii=False),
                    _utc_now(),
                ),
            )

    def list_cases(self) -> list[dict[str, Any]]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT payload_json, is_builtin, updated_at FROM admin_evaluation_cases ORDER BY id",
            ).fetchall()
        return [_with_store_metadata(row) for row in rows]

    def get_case(self, case_key: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT payload_json, is_builtin, updated_at FROM admin_evaluation_cases WHERE case_key = ?",
                (case_key,),
            ).fetchone()
        return _with_store_metadata(row) if row is not None else None

    def upsert_case(self, payload: dict[str, Any], *, updated_by: str) -> dict[str, Any]:
        self._initialize()
        case_key = str(payload["case_key"])
        now = _utc_now()
        saved_payload = {**payload, "updated_by": updated_by, "updated_at": now}
        with sqlite3.connect(self.database_path) as connection:
            existing = connection.execute(
                "SELECT is_builtin FROM admin_evaluation_cases WHERE case_key = ?",
                (case_key,),
            ).fetchone()
            is_builtin = int(existing[0]) if existing is not None else 0
            connection.execute(
                """
                INSERT INTO admin_evaluation_cases (case_key, payload_json, is_builtin, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(case_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (case_key, json.dumps(saved_payload, ensure_ascii=False), is_builtin, now),
            )
        return {**saved_payload, "is_builtin": bool(is_builtin)}

    def delete_case(self, case_key: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload_json, is_builtin, updated_at FROM admin_evaluation_cases WHERE case_key = ?",
                (case_key,),
            ).fetchone()
            if row is None:
                return None
            if bool(row[1]):
                raise ValueError("built-in evaluation case cannot be deleted")
            for suite_row in connection.execute(
                "SELECT payload_json FROM admin_evaluation_suites",
            ).fetchall():
                suite = json.loads(suite_row[0])
                if case_key in suite.get("case_keys", []):
                    raise ValueError("evaluation case is used by a suite")
            connection.execute(
                "DELETE FROM admin_evaluation_cases WHERE case_key = ?",
                (case_key,),
            )
        return _with_store_metadata(row)

    def list_suites(self) -> list[dict[str, Any]]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT payload_json, is_builtin, updated_at FROM admin_evaluation_suites ORDER BY id",
            ).fetchall()
        return [_with_store_metadata(row) for row in rows]

    def get_suite(self, suite_id: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT payload_json, is_builtin, updated_at FROM admin_evaluation_suites WHERE suite_id = ?",
                (suite_id,),
            ).fetchone()
        return _with_store_metadata(row) if row is not None else None

    def upsert_suite(self, payload: dict[str, Any], *, updated_by: str) -> dict[str, Any]:
        self._initialize()
        suite_id = str(payload["suite_id"])
        now = _utc_now()
        saved_payload = {**payload, "updated_by": updated_by, "updated_at": now}
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT is_builtin FROM admin_evaluation_suites WHERE suite_id = ?",
                (suite_id,),
            ).fetchone()
            is_builtin = int(existing[0]) if existing is not None else 0
            known_case_keys = {
                str(row[0])
                for row in connection.execute("SELECT case_key FROM admin_evaluation_cases").fetchall()
            }
            unknown_case_keys = sorted(set(payload.get("case_keys", [])) - known_case_keys)
            if unknown_case_keys:
                raise ValueError(f"unknown evaluation cases: {', '.join(unknown_case_keys)}")
            connection.execute(
                """
                INSERT INTO admin_evaluation_suites (suite_id, payload_json, is_builtin, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(suite_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (suite_id, json.dumps(saved_payload, ensure_ascii=False), is_builtin, now),
            )
        return {**saved_payload, "is_builtin": bool(is_builtin)}

    def delete_suite(self, suite_id: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload_json, is_builtin, updated_at FROM admin_evaluation_suites WHERE suite_id = ?",
                (suite_id,),
            ).fetchone()
            if row is None:
                return None
            if bool(row[1]):
                raise ValueError("built-in evaluation suite cannot be deleted")
            schedule_row = connection.execute(
                "SELECT payload_json FROM admin_evaluation_schedule WHERE schedule_id = 'default'",
            ).fetchone()
            if schedule_row is not None:
                schedule = json.loads(schedule_row[0])
                if schedule.get("enabled") and schedule.get("suite_id") == suite_id:
                    raise ValueError("evaluation suite is used by the active schedule")
            connection.execute(
                "DELETE FROM admin_evaluation_suites WHERE suite_id = ?",
                (suite_id,),
            )
        return _with_store_metadata(row)

    def get_schedule(self, default_suite_id: str = "default_regression") -> dict[str, Any]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM admin_evaluation_schedule WHERE schedule_id = 'default'",
            ).fetchone()
            if row is None:
                schedule = _default_schedule(default_suite_id)
                connection.execute(
                    "INSERT INTO admin_evaluation_schedule (schedule_id, payload_json, updated_at) VALUES ('default', ?, ?)",
                    (json.dumps(schedule, ensure_ascii=False), _utc_now()),
                )
                return schedule
        return json.loads(row[0])

    def update_schedule(self, payload: dict[str, Any], *, updated_by: str) -> dict[str, Any]:
        self._initialize()
        now = datetime.now(UTC).replace(microsecond=0)
        suite_id = str(payload["suite_id"])
        interval_minutes = int(payload["interval_minutes"])
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            suite_exists = connection.execute(
                "SELECT 1 FROM admin_evaluation_suites WHERE suite_id = ?",
                (suite_id,),
            ).fetchone()
            if suite_exists is None:
                raise ValueError("evaluation suite not found")
            before_row = connection.execute(
                "SELECT payload_json FROM admin_evaluation_schedule WHERE schedule_id = 'default'",
            ).fetchone()
            before = json.loads(before_row[0]) if before_row is not None else {}
            schedule = {
                **_default_schedule(suite_id),
                **before,
                **payload,
                "suite_id": suite_id,
                "interval_minutes": interval_minutes,
                "updated_by": updated_by,
                "updated_at": now.isoformat(),
                "status": "scheduled" if payload["enabled"] else "disabled",
                "next_run_at": (
                    (now + timedelta(minutes=interval_minutes)).isoformat()
                    if payload["enabled"]
                    else ""
                ),
                "lease_until": "",
            }
            connection.execute(
                """
                INSERT INTO admin_evaluation_schedule (schedule_id, payload_json, updated_at)
                VALUES ('default', ?, ?)
                ON CONFLICT(schedule_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (json.dumps(schedule, ensure_ascii=False), schedule["updated_at"]),
            )
        return schedule

    def claim_due_schedule(self, now: datetime) -> dict[str, Any] | None:
        self._initialize()
        normalized_now = now.astimezone(UTC).replace(microsecond=0)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload_json FROM admin_evaluation_schedule WHERE schedule_id = 'default'",
            ).fetchone()
            if row is None:
                return None
            schedule = json.loads(row[0])
            if not schedule.get("enabled"):
                return None
            next_run_at = _parse_datetime(schedule.get("next_run_at"))
            lease_until = _parse_datetime(schedule.get("lease_until"))
            if next_run_at is None or next_run_at > normalized_now:
                return None
            if schedule.get("status") == "running" and lease_until is not None and lease_until > normalized_now:
                return None
            interval_minutes = int(schedule.get("interval_minutes") or 1440)
            schedule.update(
                {
                    "status": "running",
                    "last_started_at": normalized_now.isoformat(),
                    "next_run_at": (normalized_now + timedelta(minutes=interval_minutes)).isoformat(),
                    "lease_until": (normalized_now + timedelta(hours=2)).isoformat(),
                }
            )
            connection.execute(
                "UPDATE admin_evaluation_schedule SET payload_json = ?, updated_at = ? WHERE schedule_id = 'default'",
                (json.dumps(schedule, ensure_ascii=False), normalized_now.isoformat()),
            )
        return schedule

    def complete_schedule_run(
        self,
        *,
        batch_id: str,
        error: str = "",
    ) -> dict[str, Any]:
        self._initialize()
        now = _utc_now()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload_json FROM admin_evaluation_schedule WHERE schedule_id = 'default'",
            ).fetchone()
            if row is None:
                raise ValueError("evaluation schedule not found")
            schedule = json.loads(row[0])
            schedule.update(
                {
                    "status": "failed" if error else "scheduled",
                    "last_completed_at": now,
                    "last_batch_id": batch_id,
                    "last_error": error[:500],
                    "lease_until": "",
                }
            )
            connection.execute(
                "UPDATE admin_evaluation_schedule SET payload_json = ?, updated_at = ? WHERE schedule_id = 'default'",
                (json.dumps(schedule, ensure_ascii=False), now),
            )
        return schedule

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_evaluation_cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_evaluation_suites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    suite_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_evaluation_schedule (
                    schedule_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )


def _with_store_metadata(row: tuple[Any, ...]) -> dict[str, Any]:
    payload = json.loads(str(row[0]))
    payload["is_builtin"] = bool(row[1])
    payload.setdefault("updated_at", str(row[2]))
    return payload


def _default_schedule(suite_id: str) -> dict[str, Any]:
    return {
        "enabled": False,
        "suite_id": suite_id,
        "interval_minutes": 1440,
        "status": "disabled",
        "next_run_at": "",
        "last_started_at": "",
        "last_completed_at": "",
        "last_batch_id": "",
        "last_error": "",
        "lease_until": "",
        "updated_by": "system",
        "updated_at": _utc_now(),
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


admin_evaluation_config_store = AdminEvaluationConfigStore()
