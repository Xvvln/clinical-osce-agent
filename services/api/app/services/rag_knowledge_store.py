from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "rag_knowledge.sqlite3"
DEFAULT_SEED_PATH = ROOT_DIR / "data" / "rag_knowledge" / "default_items.json"
DEFAULT_SEED_UPDATED_BY = "system:default_rag_knowledge_seed"


class RagKnowledgeStore:
    def __init__(
        self,
        database_path: Path = DEFAULT_DATABASE_PATH,
        *,
        seed_defaults: bool = False,
        seed_path: Path = DEFAULT_SEED_PATH,
    ) -> None:
        self.database_path = database_path
        self.seed_defaults = seed_defaults
        self.seed_path = seed_path

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

    def list_document_items(self, document_id: str) -> list[dict[str, Any]]:
        normalized_document_id = document_id.strip()
        if not normalized_document_id:
            return []
        return [
            item
            for item in self.list_items()
            if str(item.get("document_id", "")).strip() == normalized_document_id
        ]

    def list_documents(self, *, scope: str = "", case_id: str = "") -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in self.list_items(scope=scope.strip(), case_id=case_id.strip()):
            document_id = str(item.get("document_id", "")).strip()
            if not document_id:
                continue
            groups.setdefault(document_id, []).append(item)
        return [
            _summarize_document_items(groups[document_id])
            for document_id in sorted(groups, key=lambda item_id: _latest_updated_at(groups[item_id]), reverse=True)
        ]

    def set_document_enabled(self, document_id: str, *, enabled: bool, updated_by: str) -> dict[str, Any] | None:
        self._initialize()
        items = self.list_document_items(document_id)
        if not items:
            return None
        updated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        with sqlite3.connect(self.database_path) as connection:
            for item in items:
                item["enabled"] = bool(enabled)
                item["updated_by"] = updated_by
                item["updated_at"] = updated_at
                connection.execute(
                    """
                    UPDATE rag_knowledge_items
                    SET item_json = ?,
                        updated_at = ?
                    WHERE knowledge_id = ?
                    """,
                    (
                        json.dumps(item, ensure_ascii=False),
                        updated_at,
                        item["knowledge_id"],
                    ),
                )
        return _summarize_document_items(self.list_document_items(document_id))

    def delete_document(self, document_id: str) -> int:
        self._initialize()
        normalized_document_id = document_id.strip()
        if not normalized_document_id:
            return 0
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute("SELECT knowledge_id, item_json FROM rag_knowledge_items").fetchall()
            knowledge_ids = [
                str(knowledge_id)
                for knowledge_id, item_json in rows
                if str(json.loads(item_json).get("document_id", "")).strip() == normalized_document_id
            ]
            for knowledge_id in knowledge_ids:
                connection.execute("DELETE FROM rag_knowledge_items WHERE knowledge_id = ?", (knowledge_id,))
        return len(knowledge_ids)

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
            if self.seed_defaults:
                _seed_default_items(connection, self.seed_path)


def _seed_default_items(connection: sqlite3.Connection, seed_path: Path) -> None:
    if not seed_path.exists():
        return
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return
    for item in payload:
        if not isinstance(item, dict):
            continue
        normalized_item = _normalize_item(item, updated_by=DEFAULT_SEED_UPDATED_BY)
        existing_row = connection.execute(
            "SELECT item_json FROM rag_knowledge_items WHERE knowledge_id = ?",
            (normalized_item["knowledge_id"],),
        ).fetchone()
        if existing_row is not None:
            existing_item = json.loads(existing_row[0])
            if existing_item.get("updated_by") != DEFAULT_SEED_UPDATED_BY:
                continue
            connection.execute(
                """
                UPDATE rag_knowledge_items
                SET scope = ?,
                    case_id = ?,
                    visibility = ?,
                    item_json = ?,
                    updated_at = ?
                WHERE knowledge_id = ?
                """,
                (
                    normalized_item["scope"],
                    normalized_item["case_id"],
                    normalized_item["visibility"],
                    json.dumps(normalized_item, ensure_ascii=False),
                    normalized_item["updated_at"],
                    normalized_item["knowledge_id"],
                ),
            )
            continue
        connection.execute(
            """
            INSERT OR IGNORE INTO rag_knowledge_items (
                knowledge_id,
                scope,
                case_id,
                visibility,
                item_json,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
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


def _normalize_item(item: dict[str, Any], *, updated_by: str) -> dict[str, Any]:
    page_number = item.get("page_number")
    normalized_item = {
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
    document_id = str(item.get("document_id") or "").strip()
    if document_id:
        normalized_item.update(
            {
                "document_id": document_id,
                "document_name": str(item.get("document_name") or "").strip(),
                "chunk_index": _optional_int(item.get("chunk_index")),
                "chunk_count": _optional_int(item.get("chunk_count")),
                "section_title": str(item.get("section_title") or "").strip(),
                "page_number": _optional_int(page_number) if page_number is not None else None,
                "source_location": str(item.get("source_location") or "").strip(),
                "chunking_strategy": str(item.get("chunking_strategy") or "").strip(),
                "chunk_categories": _string_list(item.get("chunk_categories", [])),
                "quality_warnings": _string_list(item.get("quality_warnings", [])),
                "risk_flags": _string_list(item.get("risk_flags", [])),
                "char_count": _optional_int(item.get("char_count")),
                "enabled": bool(item.get("enabled", True)),
            }
        )
    elif "enabled" in item:
        normalized_item["enabled"] = bool(item.get("enabled", True))
    return normalized_item


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _summarize_document_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_items = sorted(items, key=lambda item: int(item.get("chunk_index") or 0))
    first_item = sorted_items[0]
    return {
        "document_id": str(first_item.get("document_id", "")).strip(),
        "file_name": str(first_item.get("document_name", "")).strip(),
        "scope": str(first_item.get("scope", "")).strip(),
        "case_id": str(first_item.get("case_id", "")).strip(),
        "chunk_count": len(sorted_items),
        "enabled": all(bool(item.get("enabled", True)) for item in sorted_items),
        "visibility": str(first_item.get("visibility", "")).strip(),
        "allowed_agents": _string_list(first_item.get("allowed_agents", [])),
        "source_id": str(first_item.get("source_id", "")).strip(),
        "tags": sorted({tag for item in sorted_items for tag in _string_list(item.get("tags", []))}),
        "chunking_strategies": sorted(
            {
                str(item.get("chunking_strategy", "")).strip()
                for item in sorted_items
                if str(item.get("chunking_strategy", "")).strip()
            }
        ),
        "quality_warnings": sorted(
            {
                warning
                for item in sorted_items
                for warning in _string_list(item.get("quality_warnings", []))
            }
        ),
        "risk_flags": sorted(
            {
                flag
                for item in sorted_items
                for flag in _string_list(item.get("risk_flags", []))
            }
        ),
        "updated_by": str(first_item.get("updated_by", "")).strip(),
        "updated_at": _latest_updated_at(sorted_items),
    }


def _latest_updated_at(items: list[dict[str, Any]]) -> str:
    return max((str(item.get("updated_at", "")).strip() for item in items), default="")


rag_knowledge_store = RagKnowledgeStore(seed_defaults=True)
