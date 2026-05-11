from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.runtime_model_config_store import RuntimeModelConfig

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "user_model_configs.sqlite3"


class UserModelConfigStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def save_runtime_config(self, user_id: str, config: RuntimeModelConfig) -> None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO user_runtime_model_configs (
                    user_id, provider, api_key, model, base_url, proxy_url, project, location, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    provider = excluded.provider,
                    api_key = excluded.api_key,
                    model = excluded.model,
                    base_url = excluded.base_url,
                    proxy_url = excluded.proxy_url,
                    project = excluded.project,
                    location = excluded.location,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    config.provider,
                    config.api_key,
                    config.model,
                    config.base_url,
                    config.proxy_url,
                    config.project,
                    config.location,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def get_runtime_config(self, user_id: str) -> RuntimeModelConfig | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT provider, api_key, model, base_url, proxy_url, project, location
                FROM user_runtime_model_configs
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return _runtime_config_from_row(row)

    def clear_all(self) -> None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("DELETE FROM user_runtime_model_configs")

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_runtime_model_configs (
                    user_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    model TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    proxy_url TEXT NOT NULL,
                    project TEXT NOT NULL,
                    location TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )


def _runtime_config_from_row(row: Any) -> RuntimeModelConfig:
    return RuntimeModelConfig(
        provider=str(row[0]),
        api_key=str(row[1]),
        model=str(row[2]),
        base_url=str(row[3]),
        proxy_url=str(row[4]),
        project=str(row[5]),
        location=str(row[6] or "global"),
    )


user_model_config_store = UserModelConfigStore()


__all__ = [
    "UserModelConfigStore",
    "user_model_config_store",
]
