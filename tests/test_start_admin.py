from __future__ import annotations

import importlib.util
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType

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


def load_start_admin_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "start-admin.py"
    spec = importlib.util.spec_from_file_location("start_admin", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["start_admin"] = module
    spec.loader.exec_module(module)
    return module


def test_admin_script_does_not_start_a_second_api() -> None:
    start_admin = load_start_admin_module()

    assert not hasattr(start_admin, "_api_command")


def test_admin_command_starts_next_admin_app_on_3100() -> None:
    start_admin = load_start_admin_module()

    command = start_admin._admin_command()

    assert command[-6:] == ["next", "dev", "--hostname", "127.0.0.1", "--port", "3100"]


def test_child_processes_default_to_local_admin_email_and_api_url(monkeypatch) -> None:
    monkeypatch.delenv("CLINICAL_OSCE_ADMIN_EMAILS", raising=False)
    start_admin = load_start_admin_module()

    env = start_admin._process_env()

    assert env["CLINICAL_OSCE_ADMIN_EMAILS"] == "admin@example.test"
    assert env["CLINICAL_OSCE_ADMIN_API_URL"] == "http://127.0.0.1:8000"


def test_existing_admin_email_list_is_preserved_and_local_admin_is_added(monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_ADMIN_EMAILS", "teacher@example.test")
    start_admin = load_start_admin_module()

    env = start_admin._process_env()

    assert env["CLINICAL_OSCE_ADMIN_EMAILS"] == "teacher@example.test,admin@example.test"


def test_admin_script_uses_api_and_admin_ports_only() -> None:
    start_admin = load_start_admin_module()

    assert start_admin.API_HOST == "127.0.0.1"
    assert start_admin.ADMIN_HOST == "127.0.0.1"
    assert start_admin.API_URL == "http://127.0.0.1:8000"
    assert start_admin.ADMIN_URL == "http://127.0.0.1:3100"
    assert start_admin.DEV_PORTS == (3100,)
    assert start_admin.READINESS_ENDPOINTS == (("Admin", "http://127.0.0.1:3100"),)
    assert start_admin.ADMIN_DIR == start_admin.ROOT_DIR / "apps" / "admin"


def test_http_readiness_retries_admin_root_until_success() -> None:
    start_admin = load_start_admin_module()
    clock = FakeClock()
    attempts = 0
    process = SimpleNamespace(poll=lambda: None)

    def fake_urlopen(url: str, *, timeout: float) -> FakeHttpResponse:
        nonlocal attempts
        assert url == start_admin.ADMIN_URL
        assert 0 < timeout <= start_admin.READINESS_REQUEST_TIMEOUT_SECONDS
        attempts += 1
        if attempts == 1:
            raise OSError("not ready")
        return FakeHttpResponse()

    start_admin._wait_for_http_readiness(
        [process],
        start_admin.READINESS_ENDPOINTS,
        timeout_seconds=2,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        urlopen=fake_urlopen,
    )

    assert attempts == 2
    assert clock.now == start_admin.READINESS_POLL_INTERVAL_SECONDS


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

    load_start_admin_module()

    assert proxy_configs == [{}]


def test_http_readiness_times_out_without_real_network() -> None:
    start_admin = load_start_admin_module()
    clock = FakeClock()
    process = SimpleNamespace(poll=lambda: None)

    def unavailable_urlopen(url: str, *, timeout: float) -> FakeHttpResponse:
        raise OSError(f"{url} unavailable after {timeout}s")

    with pytest.raises(RuntimeError, match="Timed out after 1s waiting for: Admin"):
        start_admin._wait_for_http_readiness(
            [process],
            start_admin.READINESS_ENDPOINTS,
            timeout_seconds=1,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            urlopen=unavailable_urlopen,
        )

    assert clock.now == 1


def test_http_readiness_fails_when_admin_exits_early() -> None:
    start_admin = load_start_admin_module()
    requested_urls: list[str] = []
    process = SimpleNamespace(poll=lambda: 4)

    with pytest.raises(RuntimeError, match="exited with code 4 before Admin became ready"):
        start_admin._wait_for_http_readiness(
            [process],
            start_admin.READINESS_ENDPOINTS,
            urlopen=lambda url, timeout: requested_urls.append(url),
        )

    assert requested_urls == []


def test_main_opens_admin_only_after_readiness_and_cleans_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_admin = load_start_admin_module()
    process = SimpleNamespace()
    events: list[str] = []
    stopped_processes: list[object] = []

    monkeypatch.setattr(start_admin, "_stop_stale_dev_processes", lambda: None)
    monkeypatch.setattr(start_admin, "_start_process", lambda **kwargs: process)
    monkeypatch.setattr(
        start_admin,
        "_wait_for_http_readiness",
        lambda processes, endpoints: events.append("ready"),
    )
    monkeypatch.setattr(start_admin.webbrowser, "open", lambda url: events.append(f"open:{url}"))
    monkeypatch.setattr(start_admin, "_wait_for_process_exit", lambda processes: 0)
    monkeypatch.setattr(start_admin, "_stop_process", stopped_processes.append)

    assert start_admin.main() == 0
    assert events == ["ready", f"open:{start_admin.ADMIN_URL}"]
    assert stopped_processes == [process]


def test_main_returns_nonzero_for_runtime_admin_failure_and_cleans_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_admin = load_start_admin_module()
    process = SimpleNamespace(poll=lambda: 12)
    stopped_processes: list[object] = []

    monkeypatch.setattr(start_admin, "_stop_stale_dev_processes", lambda: None)
    monkeypatch.setattr(start_admin, "_start_process", lambda **kwargs: process)
    monkeypatch.setattr(start_admin, "_wait_for_http_readiness", lambda processes, endpoints: None)
    monkeypatch.setattr(start_admin.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(start_admin, "_stop_process", stopped_processes.append)

    assert start_admin.main() == 1
    assert stopped_processes == [process]


def test_runtime_admin_clean_exit_is_still_an_unexpected_failure() -> None:
    start_admin = load_start_admin_module()
    process = SimpleNamespace(poll=lambda: 0)

    assert start_admin._wait_for_process_exit([process], sleep=lambda seconds: None) == 1


def test_main_returns_zero_for_ctrl_c_and_cleans_admin_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_admin = load_start_admin_module()
    process = SimpleNamespace()
    stopped_processes: list[object] = []

    monkeypatch.setattr(start_admin, "_stop_stale_dev_processes", lambda: None)
    monkeypatch.setattr(start_admin, "_start_process", lambda **kwargs: process)
    monkeypatch.setattr(
        start_admin,
        "_wait_for_http_readiness",
        lambda processes, endpoints: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(start_admin.webbrowser, "open", lambda url: pytest.fail("browser opened too early"))
    monkeypatch.setattr(start_admin, "_stop_process", stopped_processes.append)

    assert start_admin.main() == 0
    assert stopped_processes == [process]
