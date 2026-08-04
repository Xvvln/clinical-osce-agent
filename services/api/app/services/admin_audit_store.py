from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "admin_audit.sqlite3"


class AdminAuditStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def record(
        self,
        *,
        actor_user_id: str,
        actor_email: str,
        action: str,
        resource_type: str,
        resource_id: str,
        summary: str,
        before: Any = None,
        after: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._initialize()
        event = {
            "event_id": str(uuid4()),
            "actor_user_id": actor_user_id.strip(),
            "actor_email": actor_email.strip().lower(),
            "action": action.strip(),
            "resource_type": resource_type.strip(),
            "resource_id": resource_id.strip(),
            "summary": summary.strip(),
            "before": before,
            "after": after,
            "metadata": metadata or {},
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        }
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO admin_audit_events (
                    event_id, actor_user_id, actor_email, action,
                    resource_type, resource_id, summary, event_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["actor_user_id"],
                    event["actor_email"],
                    event["action"],
                    event["resource_type"],
                    event["resource_id"],
                    event["summary"],
                    json.dumps(event, ensure_ascii=False),
                    event["created_at"],
                ),
            )
        return event

    def list_events(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        query: str = "",
        resource_type: str = "",
        action: str = "",
    ) -> dict[str, Any]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        self._initialize()
        filters: list[str] = []
        parameters: list[object] = []
        normalized_query = query.strip().lower()
        if normalized_query:
            filters.append(
                "LOWER(actor_email || ' ' || action || ' ' || resource_type || ' ' || "
                "resource_id || ' ' || summary) LIKE ?"
            )
            parameters.append(f"%{normalized_query}%")
        if resource_type.strip():
            filters.append("resource_type = ?")
            parameters.append(resource_type.strip())
        if action.strip():
            filters.append("action = ?")
            parameters.append(action.strip())
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        with sqlite3.connect(self.database_path) as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM admin_audit_events {where_clause}",
                    tuple(parameters),
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT event_json
                FROM admin_audit_events
                {where_clause}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (*parameters, limit, offset),
            ).fetchall()
        return {
            "events": [json.loads(row[0]) for row in rows],
            "pagination": {"limit": limit, "offset": offset, "total": total},
        }

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    actor_user_id TEXT NOT NULL,
                    actor_email TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_admin_audit_resource
                ON admin_audit_events(resource_type, resource_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_admin_audit_created_at
                ON admin_audit_events(created_at)
                """
            )


admin_audit_store = AdminAuditStore()
