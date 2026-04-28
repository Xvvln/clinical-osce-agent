from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
API_DIR = ROOT_DIR / "services" / "api"
WEB_DIR = ROOT_DIR / "apps" / "web"
API_URL = "http://127.0.0.1:8000"
WEB_URL = "http://127.0.0.1:3000"


def main() -> int:
    processes = [
        _start_process(
            name="clinical-osce-api",
            command=[
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--reload",
                "--reload-dir",
                str(API_DIR),
            ],
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
    return subprocess.Popen(command, cwd=cwd, env=os.environ.copy())


def _web_command() -> list[str]:
    if os.name == "nt":
        return ["cmd", "/c", "corepack", "pnpm", "dev", "--hostname", "127.0.0.1", "--port", "3000"]
    return ["corepack", "pnpm", "dev", "--hostname", "127.0.0.1", "--port", "3000"]


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
