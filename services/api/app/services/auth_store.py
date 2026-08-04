from __future__ import annotations

import hashlib
import secrets
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "auth.sqlite3"
PASSWORD_HASH_ITERATIONS = 210_000
SESSION_TTL_DAYS = 7
AUTH_USER_ROLES = frozenset({"student", "teacher", "admin"})
AUTH_USER_STATUSES = frozenset({"active", "disabled", "deleted"})


class AuthStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def create_user(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
        *,
        role: str = "student",
    ) -> dict[str, str] | None:
        self._initialize()
        normalized_email = _normalize_email(email)
        normalized_role = _normalize_role(role)
        password_salt = secrets.token_hex(16)
        password_hash = _hash_password(password, password_salt)
        now = datetime.now(UTC).isoformat()
        user = {
            "user_id": str(uuid4()),
            "email": normalized_email,
            "display_name": display_name.strip() if display_name and display_name.strip() else normalized_email,
            "created_at": now,
            "role": normalized_role,
            "status": "active",
            "updated_at": now,
        }
        try:
            with sqlite3.connect(self.database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO users (
                        user_id, email, display_name, password_hash, password_salt,
                        created_at, role, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user["user_id"],
                        user["email"],
                        user["display_name"],
                        password_hash,
                        password_salt,
                        user["created_at"],
                        user["role"],
                        user["status"],
                        user["updated_at"],
                    ),
                )
        except sqlite3.IntegrityError:
            return None
        return user

    def upsert_user_password(self, email: str, password: str, display_name: str | None = None) -> dict[str, str]:
        self._initialize()
        normalized_email = _normalize_email(email)
        next_display_name = display_name.strip() if display_name and display_name.strip() else normalized_email
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = datetime.now(UTC).isoformat()
            row = connection.execute(
                """
                SELECT user_id, email, display_name, password_hash, password_salt,
                       created_at, role, status, updated_at
                FROM users
                WHERE email = ?
                """,
                (normalized_email,),
            ).fetchone()
            if row is None:
                password_salt = secrets.token_hex(16)
                password_hash = _hash_password(password, password_salt)
                user_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO users (
                        user_id, email, display_name, password_hash, password_salt,
                        created_at, role, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'student', 'active', ?)
                    """,
                    (
                        user_id,
                        normalized_email,
                        next_display_name,
                        password_hash,
                        password_salt,
                        now,
                        now,
                    ),
                )
                row = (
                    user_id,
                    normalized_email,
                    next_display_name,
                    password_hash,
                    password_salt,
                    now,
                    "student",
                    "active",
                    now,
                )
            else:
                password_changed = not secrets.compare_digest(
                    _hash_password(password, row[4]),
                    row[3],
                )
                if password_changed:
                    password_salt = secrets.token_hex(16)
                    password_hash = _hash_password(password, password_salt)
                    connection.execute(
                        """
                        UPDATE users
                        SET display_name = ?, password_hash = ?, password_salt = ?,
                            updated_at = ?
                        WHERE email = ?
                        """,
                        (
                            next_display_name,
                            password_hash,
                            password_salt,
                            now,
                            normalized_email,
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE auth_sessions
                        SET revoked_at = ?
                        WHERE user_id = ? AND revoked_at IS NULL
                        """,
                        (now, row[0]),
                    )
                    row = (
                        row[0],
                        row[1],
                        next_display_name,
                        password_hash,
                        password_salt,
                        row[5],
                        row[6],
                        row[7],
                        now,
                    )
                else:
                    connection.execute(
                        """
                        UPDATE users
                        SET display_name = ?, updated_at = ?
                        WHERE email = ?
                        """,
                        (next_display_name, now, normalized_email),
                    )
                    row = (
                        row[0],
                        row[1],
                        next_display_name,
                        row[3],
                        row[4],
                        row[5],
                        row[6],
                        row[7],
                        now,
                    )
        return _user_from_row(row)

    def authenticate_user(self, email: str, password: str) -> dict[str, str] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT user_id, email, display_name, password_hash, password_salt,
                       created_at, role, status, updated_at
                FROM users
                WHERE email = ?
                """,
                (_normalize_email(email),),
            ).fetchone()
        if row is None:
            return None
        if str(row[7]) != "active":
            return None
        password_hash = _hash_password(password, row[4])
        if not secrets.compare_digest(password_hash, row[3]):
            return None
        return _user_from_row(row)

    def get_user_by_email(self, email: str) -> dict[str, str] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT user_id, email, display_name, password_hash, password_salt,
                       created_at, role, status, updated_at
                FROM users
                WHERE email = ?
                """,
                (_normalize_email(email),),
            ).fetchone()
        return None if row is None else _user_from_row(row)

    def get_user_by_id(self, user_id: str) -> dict[str, str] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT user_id, email, display_name, password_hash, password_salt,
                       created_at, role, status, updated_at
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return None if row is None else _user_from_row(row)

    def list_users(self) -> list[dict[str, str]]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT user_id, email, display_name, password_hash, password_salt,
                       created_at, role, status, updated_at
                FROM users
                ORDER BY display_name COLLATE NOCASE ASC, email COLLATE NOCASE ASC
                """
            ).fetchall()
        return [_user_from_row(row) for row in rows]

    def has_any_user(self, emails: Iterable[str]) -> bool:
        normalized_emails = {
            _normalize_email(email)
            for email in emails
            if _normalize_email(email)
        }
        if not normalized_emails:
            return False
        if not self.database_path.is_file():
            return False
        database_uri = f"{self.database_path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(database_uri, uri=True) as connection:
            return any(
                connection.execute(
                    "SELECT 1 FROM users WHERE email = ? AND status = 'active'",
                    (email,),
                ).fetchone()
                is not None
                for email in normalized_emails
            )

    def create_session(self, user_id: str) -> str:
        self._initialize()
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        with sqlite3.connect(self.database_path) as connection:
            active_user = connection.execute(
                "SELECT 1 FROM users WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchone()
            if active_user is None:
                raise ValueError("active user is required")
            connection.execute(
                """
                INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (
                    _hash_token(token),
                    user_id,
                    now.isoformat(),
                    (now + timedelta(days=SESSION_TTL_DAYS)).isoformat(),
                ),
            )
        return token

    def get_user_by_session_token(self, token: str) -> dict[str, str] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT users.user_id, users.email, users.display_name,
                       users.created_at, auth_sessions.expires_at,
                       users.role, users.status, users.updated_at
                FROM auth_sessions
                JOIN users ON users.user_id = auth_sessions.user_id
                WHERE auth_sessions.token_hash = ?
                  AND auth_sessions.revoked_at IS NULL
                  AND users.status = 'active'
                """,
                (_hash_token(token),),
            ).fetchone()
        if row is None:
            return None
        expires_at = datetime.fromisoformat(row[4])
        if expires_at <= datetime.now(UTC):
            return None
        return {
            "user_id": row[0],
            "email": row[1],
            "display_name": row[2],
            "created_at": row[3],
            "role": row[5],
            "status": row[6],
            "updated_at": row[7],
        }

    def update_user(
        self,
        user_id: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> dict[str, str] | None:
        self._initialize()
        current = self.get_user_by_id(user_id)
        if current is None:
            return None
        next_email = _normalize_email(email) if email is not None else current["email"]
        next_display_name = (
            display_name.strip()
            if display_name is not None and display_name.strip()
            else current["display_name"]
        )
        next_role = _normalize_role(role) if role is not None else current["role"]
        next_status = (
            _normalize_status(status) if status is not None else current["status"]
        )
        now = datetime.now(UTC).isoformat()
        try:
            with sqlite3.connect(self.database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                result = connection.execute(
                    """
                    UPDATE users
                    SET email = ?, display_name = ?, role = ?, status = ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        next_email,
                        next_display_name,
                        next_role,
                        next_status,
                        now,
                        user_id,
                    ),
                )
                if result.rowcount == 0:
                    return None
                if next_status != "active":
                    _revoke_user_sessions(connection, user_id, now)
        except sqlite3.IntegrityError:
            return None
        return self.get_user_by_id(user_id)

    def reset_password(self, user_id: str, password: str) -> dict[str, str] | None:
        self._initialize()
        password_salt = secrets.token_hex(16)
        password_hash = _hash_password(password, password_salt)
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = connection.execute(
                """
                UPDATE users
                SET password_hash = ?, password_salt = ?, updated_at = ?
                WHERE user_id = ? AND status != 'deleted'
                """,
                (password_hash, password_salt, now, user_id),
            )
            if result.rowcount == 0:
                return None
            _revoke_user_sessions(connection, user_id, now)
        return self.get_user_by_id(user_id)

    def delete_user(self, user_id: str) -> dict[str, str] | None:
        return self.update_user(user_id, status="deleted")

    def revoke_session(self, token: str) -> None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = ?
                WHERE token_hash = ?
                """,
                (datetime.now(UTC).isoformat(), _hash_token(token)),
            )

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'student',
                    status TEXT NOT NULL DEFAULT 'active',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "role" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'student'"
                )
            if "status" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
                )
            if "updated_at" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                "UPDATE users SET updated_at = created_at WHERE updated_at = ''"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
                """
            )


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_role(role: str) -> str:
    normalized_role = role.strip().lower()
    if normalized_role not in AUTH_USER_ROLES:
        raise ValueError("unsupported user role")
    return normalized_role


def _normalize_status(status: str) -> str:
    normalized_status = status.strip().lower()
    if normalized_status not in AUTH_USER_STATUSES:
        raise ValueError("unsupported user status")
    return normalized_status


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    ).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _revoke_user_sessions(
    connection: sqlite3.Connection,
    user_id: str,
    revoked_at: str,
) -> None:
    connection.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = ?
        WHERE user_id = ? AND revoked_at IS NULL
        """,
        (revoked_at, user_id),
    )


def _user_from_row(row: Any) -> dict[str, str]:
    return {
        "user_id": row[0],
        "email": row[1],
        "display_name": row[2],
        "created_at": row[5],
        "role": row[6],
        "status": row[7],
        "updated_at": row[8],
    }


auth_store = AuthStore()
