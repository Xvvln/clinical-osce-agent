from __future__ import annotations

import os
import platform
import socket
import subprocess
import time
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
API_DIR = ROOT_DIR / "services" / "api"
WEB_DIR = ROOT_DIR / "apps" / "web"
AGENT_ENV_DIR = Path("D:/Anaconda3/envs/agent")
API_URL = "http://127.0.0.1:8000"
WEB_URL = "http://127.0.0.1:3000"
DEV_HOST = "127.0.0.1"
DEV_PORTS = (8000, 3000)


def main() -> int:
    _stop_stale_dev_processes()
    processes = [
        _start_process(
            name="clinical-osce-api",
            command=_api_command(),
            cwd=API_DIR,
        ),
        _start_process(
            name="clinical-osce-web",
            command=_web_command(),
            cwd=WEB_DIR,
        ),
    ]
    print(f"API: {API_URL}")
    print(f"Web: {WEB_URL}")
    print("Development hot reload is enabled for both API and Web.")
    print("Wait a few seconds for services to compile, then the browser will open.")
    time.sleep(5)
    webbrowser.open(WEB_URL)
    print("Press Ctrl+C here to stop both services.")
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping services...")
    finally:
        for process in processes:
            _stop_process(process)
    return 0


def _start_process(name: str, command: list[str], cwd: Path) -> subprocess.Popen[bytes]:
    print(f"Starting {name} in {cwd}")
    return subprocess.Popen(command, cwd=cwd, env=_process_env())


def _stop_stale_dev_processes() -> None:
    for port in DEV_PORTS:
        _stop_stale_port_processes(DEV_HOST, port)


def _stop_stale_port_processes(host: str, port: int) -> None:
    deadline = time.monotonic() + 10
    while True:
        process_id = _get_listening_process_id(host, port)
        if process_id is None:
            return

        command_line = _get_process_command_line(process_id)
        if not _is_project_owned_process(command_line):
            raise RuntimeError(
                f"{host}:{port} is already in use by process {process_id}, "
                "but it does not look like this project's dev server. Stop it manually before starting."
            )

        print(f"Stopping stale clinical-osce-agent process {process_id} on {host}:{port}")
        _terminate_process_tree(process_id)
        time.sleep(0.2)
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{host}:{port} is still in use after stopping stale project processes.")


def _get_listening_process_id(host: str, port: int) -> int | None:
    if platform.system() == "Windows":
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-NetTCPConnection -LocalAddress {host} -LocalPort {port} -State Listen -ErrorAction SilentlyContinue).OwningProcess",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                return int(line)
        return None

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        if probe.connect_ex((host, port)) != 0:
            return None
    return None


def _get_process_command_line(process_id: int) -> str:
    if platform.system() == "Windows":
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {process_id}').CommandLine",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return result.stdout.strip()
    return ""


def _is_project_owned_process(command_line: str) -> bool:
    normalized_command = command_line.replace("\\", "/").lower()
    normalized_root = str(ROOT_DIR).replace("\\", "/").lower()
    return normalized_root in normalized_command


def _terminate_process_tree(process_id: int) -> None:
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/PID", str(process_id), "/T", "/F"], check=False)
        return
    subprocess.run(["kill", str(process_id)], check=False)


def _process_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CONDA_PREFIX"] = str(AGENT_ENV_DIR)
    env["VIRTUAL_ENV"] = str(AGENT_ENV_DIR)
    env["PATH"] = os.pathsep.join(
        [
            str(AGENT_ENV_DIR),
            str(AGENT_ENV_DIR / "Scripts"),
            str(AGENT_ENV_DIR / "Library" / "bin"),
            env.get("PATH", ""),
        ]
    )
    return env


def _api_command() -> list[str]:
    command = [
        "uv",
        "run",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--reload",
        "--reload-dir",
        str(API_DIR),
    ]
    if platform.system() == "Windows":
        return ["cmd", "/c", *command]
    return command


def _web_command() -> list[str]:
    command = ["corepack", "pnpm", "exec", "next", "dev", "--hostname", "127.0.0.1", "--port", "3000"]
    if platform.system() == "Windows":
        return ["cmd", "/c", *command]
    return command


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
