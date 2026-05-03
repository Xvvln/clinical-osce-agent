from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_start_admin_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "start-admin.py"
    spec = importlib.util.spec_from_file_location("start_admin", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["start_admin"] = module
    spec.loader.exec_module(module)
    return module


def test_api_command_starts_admin_api_on_8001() -> None:
    start_admin = load_start_admin_module()

    command = start_admin._api_command()

    assert command == [
        "cmd",
        "/c",
        "uv",
        "run",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8001",
        "--reload",
        "--reload-dir",
        str(start_admin.API_DIR),
    ]


def test_admin_command_starts_next_admin_app_on_3100() -> None:
    start_admin = load_start_admin_module()

    command = start_admin._admin_command()

    assert command == [
        "cmd",
        "/c",
        "corepack",
        "pnpm",
        "exec",
        "next",
        "dev",
        "--hostname",
        "127.0.0.1",
        "--port",
        "3100",
    ]


def test_child_processes_default_to_local_admin_email_and_api_url() -> None:
    start_admin = load_start_admin_module()

    env = start_admin._process_env()

    assert env["CLINICAL_OSCE_ADMIN_EMAILS"] == "admin@example.test"
    assert env["CLINICAL_OSCE_ADMIN_API_URL"] == "http://127.0.0.1:8001"


def test_existing_admin_email_list_is_preserved_and_local_admin_is_added(monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_ADMIN_EMAILS", "teacher@example.test")
    start_admin = load_start_admin_module()

    env = start_admin._process_env()

    assert env["CLINICAL_OSCE_ADMIN_EMAILS"] == "teacher@example.test,admin@example.test"


def test_admin_script_uses_api_and_admin_ports_only() -> None:
    start_admin = load_start_admin_module()

    assert start_admin.API_URL == "http://127.0.0.1:8001"
    assert start_admin.ADMIN_URL == "http://127.0.0.1:3100"
    assert start_admin.DEV_PORTS == (8001, 3100)
    assert start_admin.ADMIN_DIR == start_admin.ROOT_DIR / "apps" / "admin"
