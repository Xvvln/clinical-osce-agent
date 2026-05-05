from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "auth.sqlite3"
PASSWORD_HASH_ITERATIONS = 210_000
SESSION_TTL_DAYS = 7


class AuthStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def create_user(self, email: str, password: str, display_name: str | None = None) -> dict[str, str] | None:
        self._initialize()
        normalized_email = _normalize_email(email)
        password_salt = secrets.token_hex(16)
        password_hash = _hash_password(password, password_salt)
        user = {
            "user_id": str(uuid4()),
            "email": normalized_email,
            "display_name": display_name.strip() if display_name and display_name.strip() else normalized_email,
            "created_at": datetime.now(UTC).isoformat(),
        }
        try:
            with sqlite3.connect(self.database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO users (user_id, email, display_name, password_hash, password_salt, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user["user_id"],
                        user["email"],
                        user["display_name"],
                        password_hash,
                        password_salt,
                        user["created_at"],
                    ),
                )
        except sqlite3.IntegrityError:
            return None
        return user

    def upsert_user_password(self, email: str, password: str, display_name: str | None = None) -> dict[str, str]:
        self._initialize()
        normalized_email = _normalize_email(email)
        password_salt = secrets.token_hex(16)
        password_hash = _hash_password(password, password_salt)
        now = datetime.now(UTC).isoformat()
        next_display_name = display_name.strip() if display_name and display_name.strip() else normalized_email
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT user_id, email, display_name, password_hash, password_salt, created_at
                FROM users
                WHERE email = ?
                """,
                (normalized_email,),
            ).fetchone()
            if row is None:
                user_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO users (user_id, email, display_name, password_hash, password_salt, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, normalized_email, next_display_name, password_hash, password_salt, now),
                )
                row = (user_id, normalized_email, next_display_name, password_hash, password_salt, now)
            else:
                connection.execute(
                    """
                    UPDATE users
                    SET display_name = ?, password_hash = ?, password_salt = ?
                    WHERE email = ?
                    """,
                    (next_display_name, password_hash, password_salt, normalized_email),
                )
                row = (row[0], row[1], next_display_name, password_hash, password_salt, row[5])
        return _user_from_row(row)

    def authenticate_user(self, email: str, password: str) -> dict[str, str] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT user_id, email, display_name, password_hash, password_salt, created_at
                FROM users
                WHERE email = ?
                """,
                (_normalize_email(email),),
            ).fetchone()
        if row is None:
            return None
        password_hash = _hash_password(password, row[4])
        if not secrets.compare_digest(password_hash, row[3]):
            return None
        return _user_from_row(row)

    def create_session(self, user_id: str) -> str:
        self._initialize()
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        with sqlite3.connect(self.database_path) as connection:
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
                SELECT users.user_id, users.email, users.display_name, users.created_at, auth_sessions.expires_at
                FROM auth_sessions
                JOIN users ON users.user_id = auth_sessions.user_id
                WHERE auth_sessions.token_hash = ? AND auth_sessions.revoked_at IS NULL
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
        }

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
                    created_at TEXT NOT NULL
                )
                """
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


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    ).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _user_from_row(row: Any) -> dict[str, str]:
    return {
        "user_id": row[0],
        "email": row[1],
        "display_name": row[2],
        "created_at": row[5],
    }


auth_store = AuthStore()
