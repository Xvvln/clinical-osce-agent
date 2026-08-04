from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "classrooms.sqlite3"
CLASSROOM_STATUSES = frozenset({"active", "archived"})


class ClassroomNameConflictError(Exception):
    """Raised when a classroom name already exists."""


class ClassroomStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def list_classrooms(self) -> list[dict[str, Any]]:
        self._initialize()
        with self._connect() as connection:
            classroom_rows = connection.execute(
                """
                SELECT classroom_id, name, description, created_by, created_at,
                       updated_by, updated_at, teacher_user_id, status
                FROM classrooms
                ORDER BY status ASC, name COLLATE NOCASE ASC, created_at ASC
                """
            ).fetchall()
            membership_rows = connection.execute(
                """
                SELECT classroom_id, user_id
                FROM classroom_memberships
                ORDER BY added_at ASC, rowid ASC
                """
            ).fetchall()
        member_ids_by_classroom: dict[str, list[str]] = {}
        for classroom_id, user_id in membership_rows:
            member_ids_by_classroom.setdefault(str(classroom_id), []).append(
                str(user_id)
            )
        return [
            _classroom_from_row(
                row,
                member_user_ids=member_ids_by_classroom.get(str(row[0]), []),
            )
            for row in classroom_rows
        ]

    def get_classroom(self, classroom_id: str) -> dict[str, Any] | None:
        self._initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT classroom_id, name, description, created_by, created_at,
                       updated_by, updated_at, teacher_user_id, status
                FROM classrooms
                WHERE classroom_id = ?
                """,
                (classroom_id,),
            ).fetchone()
            if row is None:
                return None
            membership_rows = connection.execute(
                """
                SELECT user_id
                FROM classroom_memberships
                WHERE classroom_id = ?
                ORDER BY added_at ASC, rowid ASC
                """,
                (classroom_id,),
            ).fetchall()
        return _classroom_from_row(
            row,
            member_user_ids=[str(member_row[0]) for member_row in membership_rows],
        )

    def create_classroom(
        self,
        *,
        name: str,
        description: str,
        member_user_ids: list[str],
        actor_user_id: str,
        teacher_user_id: str = "",
        status: str = "active",
    ) -> dict[str, Any]:
        self._initialize()
        classroom_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        normalized_status = _normalize_classroom_status(status)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO classrooms (
                        classroom_id, name, description, created_by, created_at,
                        updated_by, updated_at, teacher_user_id, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        classroom_id,
                        name.strip(),
                        description.strip(),
                        actor_user_id,
                        now,
                        actor_user_id,
                        now,
                        teacher_user_id.strip(),
                        normalized_status,
                    ),
                )
                self._replace_memberships(
                    connection,
                    classroom_id=classroom_id,
                    member_user_ids=member_user_ids,
                    added_at=now,
                )
        except sqlite3.IntegrityError as exc:
            if "classrooms.name" in str(exc):
                raise ClassroomNameConflictError(name.strip()) from exc
            raise
        classroom = self.get_classroom(classroom_id)
        if classroom is None:  # pragma: no cover - defensive persistence guard.
            raise RuntimeError("created classroom could not be read back")
        return classroom

    def update_classroom(
        self,
        classroom_id: str,
        *,
        name: str,
        description: str,
        member_user_ids: list[str],
        actor_user_id: str,
        teacher_user_id: str = "",
        status: str = "active",
    ) -> dict[str, Any] | None:
        self._initialize()
        now = datetime.now(UTC).isoformat()
        normalized_status = _normalize_classroom_status(status)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                result = connection.execute(
                    """
                    UPDATE classrooms
                    SET name = ?, description = ?, updated_by = ?, updated_at = ?,
                        teacher_user_id = ?, status = ?
                    WHERE classroom_id = ?
                    """,
                    (
                        name.strip(),
                        description.strip(),
                        actor_user_id,
                        now,
                        teacher_user_id.strip(),
                        normalized_status,
                        classroom_id,
                    ),
                )
                if result.rowcount == 0:
                    return None
                self._replace_memberships(
                    connection,
                    classroom_id=classroom_id,
                    member_user_ids=member_user_ids,
                    added_at=now,
                )
        except sqlite3.IntegrityError as exc:
            if "classrooms.name" in str(exc):
                raise ClassroomNameConflictError(name.strip()) from exc
            raise
        return self.get_classroom(classroom_id)

    def delete_classroom(self, classroom_id: str) -> bool:
        self._initialize()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = connection.execute(
                "DELETE FROM classrooms WHERE classroom_id = ?",
                (classroom_id,),
            )
        return result.rowcount > 0

    def transfer_members(
        self,
        *,
        source_classroom_id: str,
        target_classroom_id: str,
        member_user_ids: list[str],
        move: bool,
        actor_user_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        self._initialize()
        if source_classroom_id == target_classroom_id:
            raise ValueError("source and target classrooms must differ")
        requested_user_ids = list(dict.fromkeys(member_user_ids))
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            classrooms = {
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT classroom_id
                    FROM classrooms
                    WHERE classroom_id IN (?, ?)
                    """,
                    (source_classroom_id, target_classroom_id),
                ).fetchall()
            }
            if classrooms != {source_classroom_id, target_classroom_id}:
                return None
            source_members = {
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT user_id
                    FROM classroom_memberships
                    WHERE classroom_id = ?
                    """,
                    (source_classroom_id,),
                ).fetchall()
            }
            if any(user_id not in source_members for user_id in requested_user_ids):
                raise ValueError("all transferred members must belong to source classroom")
            connection.executemany(
                """
                INSERT OR IGNORE INTO classroom_memberships (
                    classroom_id, user_id, added_at
                ) VALUES (?, ?, ?)
                """,
                [
                    (target_classroom_id, user_id, now)
                    for user_id in requested_user_ids
                ],
            )
            if move:
                connection.executemany(
                    """
                    DELETE FROM classroom_memberships
                    WHERE classroom_id = ? AND user_id = ?
                    """,
                    [
                        (source_classroom_id, user_id)
                        for user_id in requested_user_ids
                    ],
                )
            connection.executemany(
                """
                UPDATE classrooms
                SET updated_by = ?, updated_at = ?
                WHERE classroom_id = ?
                """,
                [
                    (actor_user_id, now, source_classroom_id),
                    (actor_user_id, now, target_classroom_id),
                ],
            )
        source = self.get_classroom(source_classroom_id)
        target = self.get_classroom(target_classroom_id)
        if source is None or target is None:  # pragma: no cover - defensive guard.
            raise RuntimeError("transferred classrooms could not be read back")
        return source, target

    def import_classrooms(
        self,
        records: list[dict[str, Any]],
        *,
        actor_user_id: str,
    ) -> list[dict[str, Any]]:
        self._initialize()
        now = datetime.now(UTC).isoformat()
        classroom_ids: list[str] = []
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                for record in records:
                    name = str(record["name"]).strip()
                    existing = connection.execute(
                        """
                        SELECT classroom_id, created_by, created_at
                        FROM classrooms
                        WHERE name = ? COLLATE NOCASE
                        """,
                        (name,),
                    ).fetchone()
                    if existing is None:
                        classroom_id = str(uuid4())
                        connection.execute(
                            """
                            INSERT INTO classrooms (
                                classroom_id, name, description, created_by,
                                created_at, updated_by, updated_at,
                                teacher_user_id, status
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                classroom_id,
                                name,
                                str(record.get("description") or "").strip(),
                                actor_user_id,
                                now,
                                actor_user_id,
                                now,
                                str(record.get("teacher_user_id") or "").strip(),
                                _normalize_classroom_status(
                                    str(record.get("status") or "active")
                                ),
                            ),
                        )
                    else:
                        classroom_id = str(existing[0])
                        connection.execute(
                            """
                            UPDATE classrooms
                            SET name = ?, description = ?, updated_by = ?,
                                updated_at = ?, teacher_user_id = ?, status = ?
                            WHERE classroom_id = ?
                            """,
                            (
                                name,
                                str(record.get("description") or "").strip(),
                                actor_user_id,
                                now,
                                str(record.get("teacher_user_id") or "").strip(),
                                _normalize_classroom_status(
                                    str(record.get("status") or "active")
                                ),
                                classroom_id,
                            ),
                        )
                    self._replace_memberships(
                        connection,
                        classroom_id=classroom_id,
                        member_user_ids=[
                            str(user_id)
                            for user_id in record.get("member_user_ids", [])
                        ],
                        added_at=now,
                    )
                    classroom_ids.append(classroom_id)
        except sqlite3.IntegrityError as exc:
            if "classrooms.name" in str(exc):
                raise ClassroomNameConflictError("import") from exc
            raise
        classrooms: list[dict[str, Any]] = []
        for classroom_id in classroom_ids:
            classroom = self.get_classroom(classroom_id)
            if classroom is None:  # pragma: no cover - defensive guard.
                raise RuntimeError("imported classroom could not be read back")
            classrooms.append(classroom)
        return classrooms

    def _replace_memberships(
        self,
        connection: sqlite3.Connection,
        *,
        classroom_id: str,
        member_user_ids: list[str],
        added_at: str,
    ) -> None:
        connection.execute(
            "DELETE FROM classroom_memberships WHERE classroom_id = ?",
            (classroom_id,),
        )
        connection.executemany(
            """
            INSERT INTO classroom_memberships (classroom_id, user_id, added_at)
            VALUES (?, ?, ?)
            """,
            [
                (classroom_id, user_id, added_at)
                for user_id in dict.fromkeys(member_user_ids)
            ],
        )

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS classrooms (
                    classroom_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    description TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    teacher_user_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS classroom_memberships (
                    classroom_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (classroom_id, user_id),
                    FOREIGN KEY (classroom_id) REFERENCES classrooms(classroom_id)
                        ON DELETE CASCADE
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(classrooms)"
                ).fetchall()
            }
            if "teacher_user_id" not in columns:
                connection.execute(
                    """
                    ALTER TABLE classrooms
                    ADD COLUMN teacher_user_id TEXT NOT NULL DEFAULT ''
                    """
                )
            if "status" not in columns:
                connection.execute(
                    """
                    ALTER TABLE classrooms
                    ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
                    """
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_classroom_memberships_user_id
                ON classroom_memberships(user_id)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _classroom_from_row(
    row: Any,
    *,
    member_user_ids: list[str],
) -> dict[str, Any]:
    return {
        "classroom_id": str(row[0]),
        "name": str(row[1]),
        "description": str(row[2]),
        "created_by": str(row[3]),
        "created_at": str(row[4]),
        "updated_by": str(row[5]),
        "updated_at": str(row[6]),
        "teacher_user_id": str(row[7]),
        "status": str(row[8]),
        "member_user_ids": member_user_ids,
    }


def _normalize_classroom_status(status: str) -> str:
    normalized_status = status.strip().lower()
    if normalized_status not in CLASSROOM_STATUSES:
        raise ValueError("unsupported classroom status")
    return normalized_status


classroom_store = ClassroomStore()
