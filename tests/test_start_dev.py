from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType

import pytest


def load_start_dev_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "start-dev.py"
    spec = importlib.util.spec_from_file_location("start_dev", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["start_dev"] = module
    spec.loader.exec_module(module)
    return module


def test_api_command_uses_project_uv_environment() -> None:
    start_dev = load_start_dev_module()

    command = start_dev._api_command()

    assert sys.executable not in command
    assert command[:3] == ["cmd", "/c", "uv"]
    assert command[3:6] == ["run", "uvicorn", "app.main:app"]
    assert "--reload-dir" in command
    assert str(start_dev.API_DIR) in command


def test_child_processes_use_agent_conda_environment() -> None:
    start_dev = load_start_dev_module()

    env = start_dev._process_env()
    path_entries = env["PATH"].split(start_dev.os.pathsep)

    assert env["CONDA_PREFIX"] == str(start_dev.AGENT_ENV_DIR)
    assert env["VIRTUAL_ENV"] == str(start_dev.AGENT_ENV_DIR)
    assert path_entries[:3] == [
        str(start_dev.AGENT_ENV_DIR),
        str(start_dev.AGENT_ENV_DIR / "Scripts"),
        str(start_dev.AGENT_ENV_DIR / "Library" / "bin"),
    ]


def test_web_command_starts_next_with_default_webpack_and_polling_config() -> None:
    start_dev = load_start_dev_module()

    command = start_dev._web_command()

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
        "3000",
    ]
    assert "--webpack" not in command
    assert "--turbo" not in command
    assert "--turbopack" not in command


def test_main_stops_project_owned_stale_processes_before_starting_services() -> None:
    start_dev = load_start_dev_module()
    main_source = inspect.getsource(start_dev.main)

    assert main_source.index("_stop_stale_dev_processes()") < main_source.index("processes = [")


def test_project_owned_stale_web_processes_are_terminated_until_port_is_free(monkeypatch: pytest.MonkeyPatch) -> None:
    start_dev = load_start_dev_module()
    terminated_process_ids: list[int] = []
    stale_web_process_ids = iter([25580, 25581, None])

    def fake_listening_process_id(host: str, port: int) -> int | None:
        assert host == "127.0.0.1"
        return next(stale_web_process_ids) if port == 3000 else None

    monkeypatch.setattr(start_dev, "_get_listening_process_id", fake_listening_process_id, raising=False)
    monkeypatch.setattr(start_dev, "_get_process_command_line", lambda process_id: str(start_dev.WEB_DIR), raising=False)
    monkeypatch.setattr(start_dev, "_terminate_process_tree", terminated_process_ids.append, raising=False)
    monkeypatch.setattr(start_dev.time, "sleep", lambda seconds: None)

    start_dev._stop_stale_dev_processes()

    assert terminated_process_ids == [25580, 25581]


def test_unrelated_port_owner_is_not_terminated(monkeypatch: pytest.MonkeyPatch) -> None:
    start_dev = load_start_dev_module()
    terminated_process_ids: list[int] = []

    monkeypatch.setattr(start_dev, "_get_listening_process_id", lambda host, port: 31000 if port == 3000 else None, raising=False)
    monkeypatch.setattr(start_dev, "_get_process_command_line", lambda process_id: "C:/other-project/node.exe", raising=False)
    monkeypatch.setattr(start_dev, "_terminate_process_tree", terminated_process_ids.append, raising=False)

    with pytest.raises(RuntimeError, match="127.0.0.1:3000"):
        start_dev._stop_stale_dev_processes()

    assert terminated_process_ids == []
