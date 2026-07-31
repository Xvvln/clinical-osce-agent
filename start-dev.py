from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import time
import urllib.request
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent
API_DIR = ROOT_DIR / "services" / "api"
WEB_DIR = ROOT_DIR / "apps" / "web"
ADMIN_DIR = ROOT_DIR / "apps" / "admin"
AGENT_ENV_DIR = Path(os.environ.get("CLINICAL_OSCE_AGENT_ENV_DIR", "D:/Anaconda3/envs/agent"))
API_HOST = "127.0.0.1"
WEB_HOST = "localhost"
ADMIN_HOST = "127.0.0.1"
API_URL = f"http://{API_HOST}:8000"
WEB_URL = f"http://{WEB_HOST}:3000"
ADMIN_URL = f"http://{ADMIN_HOST}:3100"
DEV_ENDPOINTS = ((API_HOST, 8000), (WEB_HOST, 3000), (ADMIN_HOST, 3100))
DEV_PORTS = (8000, 3000, 3100)
READINESS_ENDPOINTS = (
    ("API", f"{API_URL}/health"),
    ("Web", WEB_URL),
    ("Admin", ADMIN_URL),
)
READINESS_TIMEOUT_SECONDS = 60.0
READINESS_POLL_INTERVAL_SECONDS = 0.25
READINESS_REQUEST_TIMEOUT_SECONDS = 1.0
PROCESS_POLL_INTERVAL_SECONDS = 0.25
DIRECT_HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LOCAL_ADMIN_EMAIL = "admin@example.test"
LOCAL_ADMIN_PASSWORD = "admin"
LOCAL_STUDENT_EMAIL = "student@example.test"
LOCAL_STUDENT_PASSWORD = "student"
ADMIN_EMAILS_ENV_NAME = "CLINICAL_OSCE_ADMIN_EMAILS"
ADMIN_API_URL_ENV_NAME = "CLINICAL_OSCE_ADMIN_API_URL"
WEB_ADMIN_URL_ENV_NAME = "NEXT_PUBLIC_CLINICAL_OSCE_ADMIN_URL"
WEB_DEPLOYMENT_MODE_ENV_NAME = "NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE"
WEB_AUTO_LOGIN_EMAIL_ENV_NAME = "NEXT_PUBLIC_CLINICAL_OSCE_AUTO_LOGIN_EMAIL"
WEB_AUTO_LOGIN_PASSWORD_ENV_NAME = "NEXT_PUBLIC_CLINICAL_OSCE_AUTO_LOGIN_PASSWORD"
DEPLOYMENT_MODE_ENV_NAME = "CLINICAL_OSCE_DEPLOYMENT_MODE"
DEMO_ADMIN_ENABLED_ENV_NAME = "CLINICAL_OSCE_DEMO_ADMIN_ENABLED"
DEMO_ADMIN_EMAIL_ENV_NAME = "CLINICAL_OSCE_DEMO_ADMIN_EMAIL"
DEMO_ADMIN_PASSWORD_ENV_NAME = "CLINICAL_OSCE_DEMO_ADMIN_PASSWORD"
DEMO_STUDENT_ENABLED_ENV_NAME = "CLINICAL_OSCE_DEMO_STUDENT_ENABLED"
DEMO_STUDENT_EMAIL_ENV_NAME = "CLINICAL_OSCE_DEMO_STUDENT_EMAIL"
DEMO_STUDENT_PASSWORD_ENV_NAME = "CLINICAL_OSCE_DEMO_STUDENT_PASSWORD"
OPEN_BROWSER_ENV_NAME = "CLINICAL_OSCE_OPEN_BROWSER"


def main() -> int:
    processes: list[subprocess.Popen[bytes]] = []
    exit_code = 0
    try:
        if _is_healthy_project_dev_stack_running():
            print("API, Web, and Admin are already running; not opening duplicate browser tabs.")
            print(f"API: {API_URL}")
            print(f"Web: {WEB_URL}")
            print(f"Admin: {ADMIN_URL}")
            return 0
        _stop_stale_dev_processes()
        processes.append(
            _start_process(
                name="clinical-osce-api",
                command=_api_command(),
                cwd=API_DIR,
            )
        )
        processes.append(
            _start_process(
                name="clinical-osce-web",
                command=_web_command(),
                cwd=WEB_DIR,
            )
        )
        processes.append(
            _start_process(
                name="clinical-osce-admin",
                command=_admin_command(),
                cwd=ADMIN_DIR,
            )
        )
        print(f"API: {API_URL}")
        print(f"Web: {WEB_URL}")
        print(f"Admin: {ADMIN_URL}")
        print("Development hot reload is enabled for API, Web, and Admin.")
        print("Waiting for API, Web, and Admin to become ready...")
        _wait_for_http_readiness(processes, READINESS_ENDPOINTS)
        if _should_open_browser():
            webbrowser.open(WEB_URL)
            webbrowser.open(ADMIN_URL)
        else:
            print(
                f"Browser auto-open is disabled; set {OPEN_BROWSER_ENV_NAME}=1 "
                "to open both pages after readiness."
            )
        print("Press Ctrl+C here to stop all services.")
        exit_code = _wait_for_process_exit(processes)
    except KeyboardInterrupt:
        print("Stopping services...")
        exit_code = 0
    except Exception as exc:
        print(f"Development services failed: {exc}")
        exit_code = 1
    finally:
        for process in processes:
            _stop_process(process)
    return exit_code


def _should_open_browser() -> bool:
    return os.environ.get(OPEN_BROWSER_ENV_NAME, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _wait_for_http_readiness(
    processes: Sequence[subprocess.Popen[bytes]],
    endpoints: Sequence[tuple[str, str]],
    *,
    timeout_seconds: float = READINESS_TIMEOUT_SECONDS,
    poll_interval_seconds: float = READINESS_POLL_INTERVAL_SECONDS,
    request_timeout_seconds: float = READINESS_REQUEST_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
    urlopen: Callable[..., Any] | None = None,
) -> None:
    clock = monotonic or time.monotonic
    pause = sleep or time.sleep
    open_url = urlopen or DIRECT_HTTP_OPENER.open
    deadline = clock() + timeout_seconds
    pending = dict(endpoints)

    while pending:
        _raise_if_process_exited(processes, before_ready=True)
        for name, url in list(pending.items()):
            remaining_seconds = deadline - clock()
            if remaining_seconds <= 0:
                break
            try:
                with open_url(
                    url,
                    timeout=min(request_timeout_seconds, remaining_seconds),
                ) as response:
                    status = getattr(response, "status", None)
                    if status is None:
                        status = response.getcode()
                    if int(status) >= 400:
                        continue
            except Exception:
                continue
            del pending[name]
            print(f"{name} is ready: {url}")

        _raise_if_process_exited(processes, before_ready=True)
        if not pending:
            return
        remaining_seconds = deadline - clock()
        if remaining_seconds <= 0:
            names = ", ".join(pending)
            raise RuntimeError(
                f"Timed out after {timeout_seconds:g}s waiting for: {names}."
            )
        pause(min(poll_interval_seconds, remaining_seconds))


def _wait_for_process_exit(
    processes: Sequence[subprocess.Popen[bytes]],
    *,
    poll_interval_seconds: float = PROCESS_POLL_INTERVAL_SECONDS,
    sleep: Callable[[float], None] | None = None,
) -> int:
    pause = sleep or time.sleep
    while True:
        exit_codes = [process.poll() for process in processes]
        exited_codes = [code for code in exit_codes if code is not None]
        if exited_codes:
            return 1
        pause(poll_interval_seconds)


def _raise_if_process_exited(
    processes: Sequence[subprocess.Popen[bytes]],
    *,
    before_ready: bool,
) -> None:
    for index, process in enumerate(processes, start=1):
        exit_code = process.poll()
        if exit_code is not None:
            stage = "before all services became ready" if before_ready else "while running"
            raise RuntimeError(f"Child process {index} exited with code {exit_code} {stage}.")


def _start_process(name: str, command: list[str], cwd: Path) -> subprocess.Popen[bytes]:
    print(f"Starting {name} in {cwd}")
    return subprocess.Popen(command, cwd=cwd, env=_process_env(cwd=cwd))


def _stop_stale_dev_processes() -> None:
    for host, port in DEV_ENDPOINTS:
        _stop_stale_port_processes(host, port)


def _is_healthy_project_dev_stack_running() -> bool:
    for host, port in DEV_ENDPOINTS:
        process_id = _get_listening_process_id(host, port)
        if process_id is None or not _is_project_owned_process(_get_process_command_line(process_id)):
            return False

    for _, url in READINESS_ENDPOINTS:
        try:
            with DIRECT_HTTP_OPENER.open(url, timeout=READINESS_REQUEST_TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", None)
                if status is None:
                    status = response.getcode()
                if int(status) >= 400:
                    return False
        except Exception:
            return False
    return True


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

    command = ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)

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
    command_result = subprocess.run(
        ["ps", "-p", str(process_id), "-o", "command="],
        capture_output=True,
        text=True,
        check=False,
    )
    cwd = _get_process_working_directory(process_id)
    return "\n".join(part for part in [command_result.stdout.strip(), cwd] if part)


def _get_process_working_directory(process_id: int) -> str:
    result = subprocess.run(
        ["lsof", "-a", "-p", str(process_id), "-d", "cwd", "-Fn"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            return line[1:].strip()
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


def _process_env(*, cwd: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if AGENT_ENV_DIR.exists():
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
    # The unified development launcher always runs locally and gives the
    # student and admin UIs immediately usable demo identities.  Explicit
    # values exported by the developer still win over these local defaults.
    env[DEPLOYMENT_MODE_ENV_NAME] = "local-dev"
    env[DEMO_ADMIN_ENABLED_ENV_NAME] = "true"
    env.setdefault(DEMO_ADMIN_EMAIL_ENV_NAME, LOCAL_ADMIN_EMAIL)
    env.setdefault(DEMO_ADMIN_PASSWORD_ENV_NAME, LOCAL_ADMIN_PASSWORD)
    env[DEMO_STUDENT_ENABLED_ENV_NAME] = "true"
    env.setdefault(DEMO_STUDENT_EMAIL_ENV_NAME, LOCAL_STUDENT_EMAIL)
    env.setdefault(DEMO_STUDENT_PASSWORD_ENV_NAME, LOCAL_STUDENT_PASSWORD)
    env[ADMIN_EMAILS_ENV_NAME] = _admin_email_list(
        env.get(ADMIN_EMAILS_ENV_NAME, "")
    )
    env[ADMIN_API_URL_ENV_NAME] = API_URL
    env[WEB_ADMIN_URL_ENV_NAME] = ADMIN_URL
    env[WEB_DEPLOYMENT_MODE_ENV_NAME] = "local-dev"
    if cwd == WEB_DIR:
        env[WEB_AUTO_LOGIN_EMAIL_ENV_NAME] = env[DEMO_STUDENT_EMAIL_ENV_NAME]
        env[WEB_AUTO_LOGIN_PASSWORD_ENV_NAME] = env[DEMO_STUDENT_PASSWORD_ENV_NAME]
    elif cwd == ADMIN_DIR:
        env[WEB_AUTO_LOGIN_EMAIL_ENV_NAME] = env[DEMO_ADMIN_EMAIL_ENV_NAME]
        env[WEB_AUTO_LOGIN_PASSWORD_ENV_NAME] = env[DEMO_ADMIN_PASSWORD_ENV_NAME]
    return env


def _admin_email_list(existing_value: str) -> str:
    emails = [email.strip() for email in existing_value.split(",") if email.strip()]
    if LOCAL_ADMIN_EMAIL.lower() not in {email.lower() for email in emails}:
        emails.append(LOCAL_ADMIN_EMAIL)
    return ",".join(emails)


def _api_command() -> list[str]:
    command = [
        "uv",
        "run",
        "python",
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        API_HOST,
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
    command = [*_pnpm_command(), "exec", "next", "dev", "--hostname", WEB_HOST, "--port", "3000"]
    if platform.system() == "Windows":
        return ["cmd", "/c", *command]
    return command


def _admin_command() -> list[str]:
    command = [*_pnpm_command(), "exec", "next", "dev", "--hostname", ADMIN_HOST, "--port", "3100"]
    if platform.system() == "Windows":
        return ["cmd", "/c", *command]
    return command


def _pnpm_command() -> list[str]:
    if shutil.which("corepack"):
        return ["corepack", "pnpm"]
    return ["pnpm"]


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
