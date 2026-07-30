from __future__ import annotations

import importlib.util
import inspect
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType
from urllib.parse import urlsplit

import pytest


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeHttpResponse:
    status = 200

    def __enter__(self) -> FakeHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


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
    if start_dev.platform.system() == "Windows":
        assert command[:3] == ["cmd", "/c", "uv"]
        assert command[3:7] == ["run", "python", "-m", "uvicorn"]
        assert command[7] == "app.main:app"
    else:
        assert command[:4] == ["uv", "run", "python", "-m"]
        assert command[4] == "uvicorn"
        assert command[5] == "app.main:app"
    assert "--reload-dir" in command
    assert str(start_dev.API_DIR) in command


def test_child_processes_use_shared_api_and_admin_defaults() -> None:
    start_dev = load_start_dev_module()

    env = start_dev._process_env()

    assert env["CLINICAL_OSCE_ADMIN_API_URL"] == "http://127.0.0.1:8000"
    assert env["NEXT_PUBLIC_CLINICAL_OSCE_ADMIN_URL"] == "http://127.0.0.1:3100"
    assert "admin@example.test" in env["CLINICAL_OSCE_ADMIN_EMAILS"].split(",")


def test_child_processes_inject_local_demo_login_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in [
        "CLINICAL_OSCE_DEPLOYMENT_MODE",
        "CLINICAL_OSCE_DEMO_ADMIN_ENABLED",
        "CLINICAL_OSCE_DEMO_ADMIN_EMAIL",
        "CLINICAL_OSCE_DEMO_ADMIN_PASSWORD",
        "CLINICAL_OSCE_DEMO_STUDENT_ENABLED",
        "CLINICAL_OSCE_DEMO_STUDENT_EMAIL",
        "CLINICAL_OSCE_DEMO_STUDENT_PASSWORD",
    ]:
        monkeypatch.delenv(name, raising=False)
    start_dev = load_start_dev_module()

    env = start_dev._process_env()

    assert env["CLINICAL_OSCE_DEPLOYMENT_MODE"] == "local-dev"
    assert env["CLINICAL_OSCE_DEMO_ADMIN_ENABLED"] == "true"
    assert env["CLINICAL_OSCE_DEMO_ADMIN_EMAIL"] == "admin@example.test"
    assert env["CLINICAL_OSCE_DEMO_ADMIN_PASSWORD"] == "admin"
    assert env["CLINICAL_OSCE_DEMO_STUDENT_ENABLED"] == "true"
    assert env["CLINICAL_OSCE_DEMO_STUDENT_EMAIL"] == "student@example.test"
    assert env["CLINICAL_OSCE_DEMO_STUDENT_PASSWORD"] == "student"


def test_child_processes_allow_explicit_local_demo_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_EMAIL", "teacher@example.test")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_PASSWORD", "teacher-password")
    start_dev = load_start_dev_module()

    env = start_dev._process_env()

    assert env["CLINICAL_OSCE_DEMO_ADMIN_EMAIL"] == "teacher@example.test"
    assert env["CLINICAL_OSCE_DEMO_ADMIN_PASSWORD"] == "teacher-password"
    assert env["CLINICAL_OSCE_DEMO_ADMIN_ENABLED"] == "true"


def test_web_and_admin_processes_receive_their_own_local_auto_login_credentials() -> None:
    start_dev = load_start_dev_module()

    web_env = start_dev._process_env(cwd=start_dev.WEB_DIR)
    admin_env = start_dev._process_env(cwd=start_dev.ADMIN_DIR)

    assert web_env["NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE"] == "local-dev"
    assert web_env["NEXT_PUBLIC_CLINICAL_OSCE_AUTO_LOGIN_EMAIL"] == "student@example.test"
    assert web_env["NEXT_PUBLIC_CLINICAL_OSCE_AUTO_LOGIN_PASSWORD"] == "student"
    assert admin_env["NEXT_PUBLIC_CLINICAL_OSCE_AUTO_LOGIN_EMAIL"] == "admin@example.test"
    assert admin_env["NEXT_PUBLIC_CLINICAL_OSCE_AUTO_LOGIN_PASSWORD"] == "admin"


def test_web_command_starts_next_with_default_webpack_and_polling_config() -> None:
    start_dev = load_start_dev_module()

    command = start_dev._web_command()

    assert command[-6:] == ["next", "dev", "--hostname", "localhost", "--port", "3000"]
    assert "--webpack" not in command
    assert "--turbo" not in command
    assert "--turbopack" not in command


def test_admin_command_starts_next_admin_app_against_shared_api() -> None:
    start_dev = load_start_dev_module()

    command = start_dev._admin_command()

    assert command[-6:] == ["next", "dev", "--hostname", "127.0.0.1", "--port", "3100"]


def test_unified_dev_script_uses_single_api_for_web_and_admin() -> None:
    start_dev = load_start_dev_module()

    assert start_dev.API_URL == "http://127.0.0.1:8000"
    assert start_dev.WEB_URL == "http://localhost:3000"
    assert start_dev.ADMIN_URL == "http://127.0.0.1:3100"
    assert start_dev.DEV_ENDPOINTS == (
        ("127.0.0.1", 8000),
        ("localhost", 3000),
        ("127.0.0.1", 3100),
    )
    assert start_dev.DEV_PORTS == (8000, 3000, 3100)
    assert start_dev.READINESS_ENDPOINTS == (
        ("API", "http://127.0.0.1:8000/health"),
        ("Web", "http://localhost:3000"),
        ("Admin", "http://127.0.0.1:3100"),
    )
    assert start_dev.ADMIN_DIR == start_dev.ROOT_DIR / "apps" / "admin"


def test_student_and_admin_urls_use_distinct_hosts_for_host_only_cookie_isolation() -> None:
    start_dev = load_start_dev_module()

    student_url = urlsplit(start_dev.WEB_URL)
    admin_url = urlsplit(start_dev.ADMIN_URL)

    assert student_url.scheme == admin_url.scheme == "http"
    assert student_url.hostname == start_dev.WEB_HOST == "localhost"
    assert admin_url.hostname == start_dev.ADMIN_HOST == "127.0.0.1"
    assert student_url.hostname != admin_url.hostname


def test_main_stops_project_owned_stale_processes_before_starting_services() -> None:
    start_dev = load_start_dev_module()
    main_source = inspect.getsource(start_dev.main)

    assert main_source.index("_stop_stale_dev_processes()") < main_source.index("_start_process(")
    assert 'name="clinical-osce-api"' in main_source
    assert 'name="clinical-osce-web"' in main_source
    assert 'name="clinical-osce-admin"' in main_source


def test_main_reuses_a_healthy_project_stack_without_opening_browser_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_dev = load_start_dev_module()
    browser_urls: list[str] = []

    monkeypatch.setattr(start_dev, "_is_healthy_project_dev_stack_running", lambda: True)
    monkeypatch.setattr(start_dev, "_stop_stale_dev_processes", lambda: pytest.fail("healthy stack should be reused"))
    monkeypatch.setattr(start_dev, "_start_process", lambda **kwargs: pytest.fail("healthy stack should be reused"))
    monkeypatch.setattr(start_dev.webbrowser, "open", browser_urls.append)

    assert start_dev.main() == 0
    assert browser_urls == []


def test_http_readiness_retries_until_every_service_succeeds() -> None:
    start_dev = load_start_dev_module()
    clock = FakeClock()
    attempts: dict[str, int] = {}
    requested_urls: list[str] = []
    process = SimpleNamespace(poll=lambda: None)

    def fake_urlopen(url: str, *, timeout: float) -> FakeHttpResponse:
        assert 0 < timeout <= start_dev.READINESS_REQUEST_TIMEOUT_SECONDS
        requested_urls.append(url)
        attempts[url] = attempts.get(url, 0) + 1
        if attempts[url] == 1:
            raise OSError("not ready")
        return FakeHttpResponse()

    start_dev._wait_for_http_readiness(
        [process],
        start_dev.READINESS_ENDPOINTS,
        timeout_seconds=2,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        urlopen=fake_urlopen,
    )

    assert set(requested_urls) == {url for _, url in start_dev.READINESS_ENDPOINTS}
    assert all(attempts[url] == 2 for _, url in start_dev.READINESS_ENDPOINTS)
    assert clock.now == start_dev.READINESS_POLL_INTERVAL_SECONDS


def test_default_http_readiness_opener_explicitly_disables_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_build_opener = urllib.request.build_opener
    proxy_configs: list[dict[str, str]] = []

    def capture_build_opener(*handlers: object) -> urllib.request.OpenerDirector:
        proxy_configs.extend(
            handler.proxies
            for handler in handlers
            if isinstance(handler, urllib.request.ProxyHandler)
        )
        return original_build_opener(*handlers)

    monkeypatch.setattr(urllib.request, "build_opener", capture_build_opener)

    load_start_dev_module()

    assert proxy_configs == [{}]


def test_http_readiness_times_out_without_real_network() -> None:
    start_dev = load_start_dev_module()
    clock = FakeClock()
    process = SimpleNamespace(poll=lambda: None)

    def unavailable_urlopen(url: str, *, timeout: float) -> FakeHttpResponse:
        raise OSError(f"{url} unavailable after {timeout}s")

    with pytest.raises(RuntimeError, match="Timed out after 1s waiting for: API, Web, Admin"):
        start_dev._wait_for_http_readiness(
            [process],
            start_dev.READINESS_ENDPOINTS,
            timeout_seconds=1,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            urlopen=unavailable_urlopen,
        )

    assert clock.now == 1


def test_http_readiness_fails_when_child_exits_before_all_targets_are_ready() -> None:
    start_dev = load_start_dev_module()
    requested_urls: list[str] = []
    process = SimpleNamespace(poll=lambda: 7)

    with pytest.raises(RuntimeError, match="exited with code 7 before all services became ready"):
        start_dev._wait_for_http_readiness(
            [process],
            start_dev.READINESS_ENDPOINTS,
            urlopen=lambda url, timeout: requested_urls.append(url),
        )

    assert requested_urls == []


def test_main_opens_browsers_only_after_readiness_and_cleans_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_dev = load_start_dev_module()
    processes = [SimpleNamespace(), SimpleNamespace(), SimpleNamespace()]
    process_iterator = iter(processes)
    events: list[str] = []
    stopped_processes: list[object] = []

    monkeypatch.setattr(start_dev, "_is_healthy_project_dev_stack_running", lambda: False)
    monkeypatch.setattr(start_dev, "_stop_stale_dev_processes", lambda: None)
    monkeypatch.setattr(start_dev, "_start_process", lambda **kwargs: next(process_iterator))
    monkeypatch.setattr(
        start_dev,
        "_wait_for_http_readiness",
        lambda actual_processes, endpoints: events.append("ready"),
    )
    monkeypatch.setattr(start_dev.webbrowser, "open", lambda url: events.append(f"open:{url}"))
    monkeypatch.setattr(start_dev, "_wait_for_process_exit", lambda actual_processes: 0)
    monkeypatch.setattr(start_dev, "_stop_process", stopped_processes.append)

    assert start_dev.main() == 0
    assert events == [
        "ready",
        f"open:{start_dev.WEB_URL}",
        f"open:{start_dev.ADMIN_URL}",
    ]
    assert stopped_processes == processes


def test_main_returns_nonzero_for_runtime_child_failure_and_cleans_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_dev = load_start_dev_module()
    processes = [
        SimpleNamespace(poll=lambda: None),
        SimpleNamespace(poll=lambda: 9),
        SimpleNamespace(poll=lambda: None),
    ]
    process_iterator = iter(processes)
    stopped_processes: list[object] = []

    monkeypatch.setattr(start_dev, "_is_healthy_project_dev_stack_running", lambda: False)
    monkeypatch.setattr(start_dev, "_stop_stale_dev_processes", lambda: None)
    monkeypatch.setattr(start_dev, "_start_process", lambda **kwargs: next(process_iterator))
    monkeypatch.setattr(start_dev, "_wait_for_http_readiness", lambda processes, endpoints: None)
    monkeypatch.setattr(start_dev.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(start_dev, "_stop_process", stopped_processes.append)

    assert start_dev.main() == 1
    assert stopped_processes == processes


def test_runtime_child_clean_exit_is_still_an_unexpected_stack_failure() -> None:
    start_dev = load_start_dev_module()
    processes = [
        SimpleNamespace(poll=lambda: 0),
        SimpleNamespace(poll=lambda: None),
    ]

    assert start_dev._wait_for_process_exit(processes, sleep=lambda seconds: None) == 1


def test_main_returns_zero_for_ctrl_c_and_cleans_started_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_dev = load_start_dev_module()
    processes = [SimpleNamespace(), SimpleNamespace(), SimpleNamespace()]
    process_iterator = iter(processes)
    stopped_processes: list[object] = []

    monkeypatch.setattr(start_dev, "_is_healthy_project_dev_stack_running", lambda: False)
    monkeypatch.setattr(start_dev, "_stop_stale_dev_processes", lambda: None)
    monkeypatch.setattr(start_dev, "_start_process", lambda **kwargs: next(process_iterator))
    monkeypatch.setattr(
        start_dev,
        "_wait_for_http_readiness",
        lambda actual_processes, endpoints: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(start_dev.webbrowser, "open", lambda url: pytest.fail("browser opened too early"))
    monkeypatch.setattr(start_dev, "_stop_process", stopped_processes.append)

    assert start_dev.main() == 0
    assert stopped_processes == processes


def test_project_owned_stale_web_processes_are_terminated_until_port_is_free(monkeypatch: pytest.MonkeyPatch) -> None:
    start_dev = load_start_dev_module()
    terminated_process_ids: list[int] = []
    stale_web_process_ids = iter([25580, 25581, None])

    def fake_listening_process_id(host: str, port: int) -> int | None:
        assert host == ("localhost" if port == 3000 else "127.0.0.1")
        return next(stale_web_process_ids) if port == 3000 else None

    monkeypatch.setattr(start_dev, "_get_listening_process_id", fake_listening_process_id, raising=False)
    monkeypatch.setattr(start_dev, "_get_process_command_line", lambda process_id: str(start_dev.WEB_DIR), raising=False)
    monkeypatch.setattr(start_dev, "_terminate_process_tree", terminated_process_ids.append, raising=False)
    monkeypatch.setattr(start_dev.time, "sleep", lambda seconds: None)

    start_dev._stop_stale_dev_processes()

    assert terminated_process_ids == [25580, 25581]


def test_project_owned_process_can_be_identified_from_cwd_when_command_is_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    start_dev = load_start_dev_module()

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        if command[:3] == ["ps", "-p", "68464"]:
            return SimpleNamespace(stdout="next-server (v15.5.15)\n")
        if command[:4] == ["lsof", "-a", "-p", "68464"]:
            return SimpleNamespace(stdout=f"p68464\nfcwd\nn{start_dev.WEB_DIR}\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(start_dev.subprocess, "run", fake_run, raising=False)

    command_line = start_dev._get_process_command_line(68464)

    assert start_dev._is_project_owned_process(command_line)


def test_unrelated_port_owner_is_not_terminated(monkeypatch: pytest.MonkeyPatch) -> None:
    start_dev = load_start_dev_module()
    terminated_process_ids: list[int] = []

    monkeypatch.setattr(start_dev, "_get_listening_process_id", lambda host, port: 31000 if port == 3000 else None, raising=False)
    monkeypatch.setattr(start_dev, "_get_process_command_line", lambda process_id: "C:/other-project/node.exe", raising=False)
    monkeypatch.setattr(start_dev, "_terminate_process_tree", terminated_process_ids.append, raising=False)

    with pytest.raises(RuntimeError, match="localhost:3000"):
        start_dev._stop_stale_dev_processes()

    assert terminated_process_ids == []
