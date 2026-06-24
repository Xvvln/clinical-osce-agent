from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

DEFAULT_API_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


def load_api_env_file(env_file: Path = DEFAULT_API_ENV_FILE) -> bool:
    if not env_file.exists():
        return False
    return bool(load_dotenv(env_file, override=False))


__all__ = ["DEFAULT_API_ENV_FILE", "load_api_env_file"]
