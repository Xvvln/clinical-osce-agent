from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "admin_asset_versions.sqlite3"


class AdminAssetVersionStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def ensure_initial_version(
        self,
        *,
        asset_type: str,
        asset_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
        actor_email: str,
    ) -> dict[str, Any]:
        normalized_type = asset_type.strip()
        normalized_id = asset_id.strip()
        if not normalized_type or not normalized_id:
            raise ValueError("asset type and id are required")
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT MAX(version) FROM admin_asset_versions
                WHERE asset_type = ? AND asset_id = ?
                """,
                (normalized_type, normalized_id),
            ).fetchone()
            if row is not None and row[0] is not None:
                existing_version = int(row[0])
            else:
                existing_version = 0
                connection.execute(
                    """
                    INSERT INTO admin_asset_versions (
                        asset_type, asset_id, version, payload_json, payload_hash,
                        change_note, review_status, review_note,
                        actor_user_id, actor_email, created_at
                    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_type,
                        normalized_id,
                        payload_json,
                        payload_hash,
                        "初始化版本快照",
                        "unreviewed",
                        "",
                        actor_user_id.strip(),
                        actor_email.strip().lower(),
                        created_at,
                    ),
                )
        if existing_version:
            current = self.get_version(
                asset_type=normalized_type,
                asset_id=normalized_id,
                version=existing_version,
            )
            if current is None:  # pragma: no cover - defensive consistency guard.
                raise RuntimeError("asset version disappeared after initialization")
            return current
        created = self.get_version(
            asset_type=normalized_type,
            asset_id=normalized_id,
            version=1,
        )
        if created is None:  # pragma: no cover - defensive consistency guard.
            raise RuntimeError("asset initial version was not persisted")
        return created

    def save_version(
        self,
        *,
        asset_type: str,
        asset_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
        actor_email: str,
        change_note: str,
        review_status: str,
        review_note: str,
    ) -> dict[str, Any]:
        normalized_type = asset_type.strip()
        normalized_id = asset_id.strip()
        if not normalized_type or not normalized_id:
            raise ValueError("asset type and id are required")
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT COALESCE(MAX(version), 0)
                FROM admin_asset_versions
                WHERE asset_type = ? AND asset_id = ?
                """,
                (normalized_type, normalized_id),
            ).fetchone()
            version = int(row[0]) + 1
            connection.execute(
                """
                INSERT INTO admin_asset_versions (
                    asset_type, asset_id, version, payload_json, payload_hash,
                    change_note, review_status, review_note,
                    actor_user_id, actor_email, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_type,
                    normalized_id,
                    version,
                    payload_json,
                    payload_hash,
                    change_note.strip(),
                    review_status.strip() or "unreviewed",
                    review_note.strip(),
                    actor_user_id.strip(),
                    actor_email.strip().lower(),
                    created_at,
                ),
            )
        return {
            "asset_type": normalized_type,
            "asset_id": normalized_id,
            "version": version,
            "payload": json.loads(payload_json),
            "payload_hash": payload_hash,
            "change_note": change_note.strip(),
            "review_status": review_status.strip() or "unreviewed",
            "review_note": review_note.strip(),
            "actor_user_id": actor_user_id.strip(),
            "actor_email": actor_email.strip().lower(),
            "created_at": created_at,
        }

    def list_versions(
        self,
        *,
        asset_type: str,
        asset_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            total = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM admin_asset_versions
                    WHERE asset_type = ? AND asset_id = ?
                    """,
                    (asset_type.strip(), asset_id.strip()),
                ).fetchone()[0]
            )
            rows = connection.execute(
                """
                SELECT version, payload_hash, change_note, review_status,
                       review_note, actor_user_id, actor_email, created_at
                FROM admin_asset_versions
                WHERE asset_type = ? AND asset_id = ?
                ORDER BY version DESC
                LIMIT ? OFFSET ?
                """,
                (asset_type.strip(), asset_id.strip(), limit, offset),
            ).fetchall()
        return {
            "versions": [
                {
                    "asset_type": asset_type.strip(),
                    "asset_id": asset_id.strip(),
                    "version": int(row[0]),
                    "payload_hash": row[1],
                    "change_note": row[2],
                    "review_status": row[3],
                    "review_note": row[4],
                    "actor_user_id": row[5],
                    "actor_email": row[6],
                    "created_at": row[7],
                }
                for row in rows
            ],
            "pagination": {"limit": limit, "offset": offset, "total": total},
        }

    def get_version(
        self,
        *,
        asset_type: str,
        asset_id: str,
        version: int,
    ) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT payload_json, payload_hash, change_note, review_status,
                       review_note, actor_user_id, actor_email, created_at
                FROM admin_asset_versions
                WHERE asset_type = ? AND asset_id = ? AND version = ?
                """,
                (asset_type.strip(), asset_id.strip(), version),
            ).fetchone()
        if row is None:
            return None
        return {
            "asset_type": asset_type.strip(),
            "asset_id": asset_id.strip(),
            "version": version,
            "payload": json.loads(row[0]),
            "payload_hash": row[1],
            "change_note": row[2],
            "review_status": row[3],
            "review_note": row[4],
            "actor_user_id": row[5],
            "actor_email": row[6],
            "created_at": row[7],
        }

    def get_latest_version(
        self,
        *,
        asset_type: str,
        asset_id: str,
    ) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT MAX(version) FROM admin_asset_versions
                WHERE asset_type = ? AND asset_id = ?
                """,
                (asset_type.strip(), asset_id.strip()),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return self.get_version(
            asset_type=asset_type,
            asset_id=asset_id,
            version=int(row[0]),
        )

    def diff_versions(
        self,
        *,
        asset_type: str,
        asset_id: str,
        from_version: int,
        to_version: int,
        max_changes: int = 500,
    ) -> dict[str, Any] | None:
        before = self.get_version(
            asset_type=asset_type,
            asset_id=asset_id,
            version=from_version,
        )
        after = self.get_version(
            asset_type=asset_type,
            asset_id=asset_id,
            version=to_version,
        )
        if before is None or after is None:
            return None
        changes: list[dict[str, Any]] = []
        _collect_json_changes(
            before["payload"],
            after["payload"],
            path="$",
            changes=changes,
            max_changes=max_changes,
        )
        return {
            "asset_type": asset_type.strip(),
            "asset_id": asset_id.strip(),
            "from_version": from_version,
            "to_version": to_version,
            "changes": changes,
            "change_count": len(changes),
            "truncated": len(changes) >= max_changes,
        }

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_asset_versions (
                    asset_type TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    change_note TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    review_note TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    actor_email TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (asset_type, asset_id, version)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_admin_asset_versions_created_at
                ON admin_asset_versions(created_at)
                """
            )


def _collect_json_changes(
    before: Any,
    after: Any,
    *,
    path: str,
    changes: list[dict[str, Any]],
    max_changes: int,
) -> None:
    if len(changes) >= max_changes or before == after:
        return
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            if len(changes) >= max_changes:
                return
            child_path = f"{path}.{key}"
            if key not in before:
                changes.append({"path": child_path, "change": "added", "before": None, "after": after[key]})
            elif key not in after:
                changes.append({"path": child_path, "change": "removed", "before": before[key], "after": None})
            else:
                _collect_json_changes(
                    before[key],
                    after[key],
                    path=child_path,
                    changes=changes,
                    max_changes=max_changes,
                )
        return
    if isinstance(before, list) and isinstance(after, list):
        for index in range(max(len(before), len(after))):
            if len(changes) >= max_changes:
                return
            child_path = f"{path}[{index}]"
            if index >= len(before):
                changes.append({"path": child_path, "change": "added", "before": None, "after": after[index]})
            elif index >= len(after):
                changes.append({"path": child_path, "change": "removed", "before": before[index], "after": None})
            else:
                _collect_json_changes(
                    before[index],
                    after[index],
                    path=child_path,
                    changes=changes,
                    max_changes=max_changes,
                )
        return
    changes.append({"path": path, "change": "changed", "before": before, "after": after})


admin_asset_version_store = AdminAssetVersionStore()
