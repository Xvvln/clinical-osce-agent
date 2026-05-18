from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "rag_knowledge.sqlite3"


class RagKnowledgeStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def upsert_item(self, item: dict[str, Any], *, updated_by: str) -> dict[str, Any]:
        self._initialize()
        normalized_item = _normalize_item(item, updated_by=updated_by)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO rag_knowledge_items (
                    knowledge_id,
                    scope,
                    case_id,
                    visibility,
                    item_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(knowledge_id) DO UPDATE SET
                    scope = excluded.scope,
                    case_id = excluded.case_id,
                    visibility = excluded.visibility,
                    item_json = excluded.item_json,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_item["knowledge_id"],
                    normalized_item["scope"],
                    normalized_item["case_id"],
                    normalized_item["visibility"],
                    json.dumps(normalized_item, ensure_ascii=False),
                    normalized_item["updated_at"],
                ),
            )
        return normalized_item

    def get_item(self, knowledge_id: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT item_json FROM rag_knowledge_items WHERE knowledge_id = ?",
                (knowledge_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def list_items(
        self,
        *,
        scope: str = "",
        case_id: str = "",
        visibility: str = "",
    ) -> list[dict[str, Any]]:
        self._initialize()
        clauses: list[str] = []
        params: list[str] = []
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if case_id:
            clauses.append("case_id = ?")
            params.append(case_id)
        if visibility:
            clauses.append("visibility = ?")
            params.append(visibility)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT item_json
                FROM rag_knowledge_items
                {where_clause}
                ORDER BY id
                """,
                params,
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete_item(self, knowledge_id: str) -> bool:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            cursor = connection.execute(
                "DELETE FROM rag_knowledge_items WHERE knowledge_id = ?",
                (knowledge_id,),
            )
        return cursor.rowcount > 0

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_knowledge_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_id TEXT NOT NULL UNIQUE,
                    scope TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    item_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )


def _normalize_item(item: dict[str, Any], *, updated_by: str) -> dict[str, Any]:
    return {
        "knowledge_id": str(item["knowledge_id"]).strip(),
        "scope": str(item["scope"]).strip(),
        "case_id": str(item.get("case_id") or "").strip(),
        "content_kind": str(item["content_kind"]).strip(),
        "visibility": str(item["visibility"]).strip(),
        "allowed_agents": _string_list(item.get("allowed_agents", [])),
        "source_id": str(item.get("source_id") or "").strip(),
        "title": str(item["title"]).strip(),
        "text": str(item["text"]).strip(),
        "tags": _string_list(item.get("tags", [])),
        "version": int(item.get("version") or 1),
        "updated_by": updated_by,
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


rag_knowledge_store = RagKnowledgeStore()
