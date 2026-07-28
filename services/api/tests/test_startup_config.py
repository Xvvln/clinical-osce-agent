import os
from pathlib import Path

from fastapi.testclient import TestClient
import yaml

from app import main
from app.main import AUTH_COOKIE_NAME
from app.services.auth_store import AuthStore
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.startup_config_service import build_startup_config_self_check


def test_startup_config_self_check_reports_missing_required_env(monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")
    monkeypatch.delenv("CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS", raising=False)
    monkeypatch.delenv("CLINICAL_OSCE_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("CLINICAL_OSCE_DEMO_ADMIN_ENABLED", raising=False)
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "true")
    monkeypatch.delenv("OSCE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OSCE_OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OSCE_VERTEX_ENABLED", "true")
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "true")
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", "")
    monkeypatch.setenv("OSCE_CHROMA_COLLECTION", "")

    payload = build_startup_config_self_check()
    assert payload["deployment"] == {
        "mode": "single-node-prod",
        "production": True,
        "allowed_modes": ["local-dev", "local-demo", "single-node-prod", "vertex-prod"],
    }
    assert payload["overall_status"] == "fail"
    assert payload["runtime_config"]["active"] is False
    assert payload["runtime_config"]["write_supported"] is False
    assert payload["policy"]["demo_admin_effective_enabled"] is False
    assert payload["policy"]["demo_student_effective_enabled"] is False
    assert payload["policy"]["account_registration_supported"] is False

    issue_codes = {issue["code"] for issue in payload["issues"]}
    assert {
        "missing_admin_emails",
        "missing_trusted_browser_origins",
        "openai_missing_env",
        "vertex_missing_auth",
        "chroma_missing_env",
    }.issubset(issue_codes)

    providers = {provider["provider_id"]: provider for provider in payload["providers"]}
    assert providers["openai_compatible"]["enabled"] is True
    assert providers["openai_compatible"]["configured"] is False
    assert providers["openai_compatible"]["missing_env"] == ["OSCE_OPENAI_API_KEY", "OSCE_OPENAI_MODEL"]
    assert providers["vertex_rubric_scorer"]["missing_env"] == ["OSCE_VERTEX_PROJECT 或 OSCE_VERTEX_API_KEY"]
    assert providers["chroma_retrieval"]["missing_env"] == [
        "向量模型配置",
        "CHROMA_PERSIST_DIRECTORY",
        "OSCE_CHROMA_COLLECTION",
    ]


def test_production_mode_disables_demo_admin_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")
    monkeypatch.setenv("CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS", "https://osce.example")
    monkeypatch.delenv("CLINICAL_OSCE_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("CLINICAL_OSCE_DEMO_ADMIN_ENABLED", raising=False)
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/auth/login",
            headers={"Origin": "https://osce.example", "Sec-Fetch-Site": "same-origin"},
            json={"email": "admin@osce.test", "password": "admin"},
        )

    assert response.status_code == 401


def test_startup_config_accepts_server_managed_openai_gateway_without_unused_gemini_env(monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")
    monkeypatch.setenv("CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS", "https://osce.example")
    monkeypatch.setenv("CLINICAL_OSCE_ADMIN_EMAILS", "admin@osce.test")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_ENABLED", "true")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_EMAIL", "admin@osce.test")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_PASSWORD", "configured-admin-password")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_ENABLED", "true")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_EMAIL", "student@osce.test")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_PASSWORD", "configured-student-password")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "true")
    monkeypatch.setenv("OSCE_OPENAI_API_KEY", "configured")
    monkeypatch.setenv("OSCE_OPENAI_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "false")
    monkeypatch.setenv("OSCE_VERTEX_ENABLED", "false")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_USE_VERTEX", "false")
    monkeypatch.delenv("OSCE_GEMINI_PATIENT_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    payload = build_startup_config_self_check()
    issue_codes = {issue["code"] for issue in payload["issues"]}
    demo_issue = next(issue for issue in payload["issues"] if issue["code"] == "demo_admin_enabled_in_production")
    student_issue = next(issue for issue in payload["issues"] if issue["code"] == "demo_student_enabled_in_production")
    assert payload["overall_status"] == "ok"
    assert payload["policy"]["demo_admin_effective_enabled"] is False
    assert payload["policy"]["demo_student_effective_enabled"] is False
    assert payload["policy"]["trusted_browser_origins"] == ["https://osce.example"]
    assert payload["policy"]["trusted_browser_origins_explicit"] is True
    assert "gemini_missing_env" not in issue_codes
    assert demo_issue["severity"] == "warning"
    assert student_issue["severity"] == "warning"


def test_local_demo_accounts_are_disabled_without_complete_explicit_config(monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_ENABLED", "true")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_EMAIL", "admin@osce.test")
    monkeypatch.delenv("CLINICAL_OSCE_DEMO_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_ENABLED", "true")
    monkeypatch.delenv("CLINICAL_OSCE_DEMO_STUDENT_EMAIL", raising=False)
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_PASSWORD", "configured-student-password")
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "false")

    payload = build_startup_config_self_check()
    assert payload["overall_status"] == "fail"
    assert payload["policy"]["demo_admin_effective_enabled"] is False
    assert payload["policy"]["demo_student_effective_enabled"] is False
    issues = {issue["code"]: issue for issue in payload["issues"]}
    assert issues["demo_admin_incomplete"]["missing_env"] == ["CLINICAL_OSCE_DEMO_ADMIN_PASSWORD"]
    assert issues["demo_student_incomplete"]["missing_env"] == ["CLINICAL_OSCE_DEMO_STUDENT_EMAIL"]


def test_startup_config_rejects_invalid_trusted_browser_origins(monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")
    monkeypatch.setenv("CLINICAL_OSCE_ADMIN_EMAILS", "admin@example.test")
    monkeypatch.setenv(
        "CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS",
        "http://osce.example,https://*.example,https://osce.example/path",
    )
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "false")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "false")
    monkeypatch.setenv("OSCE_VERTEX_ENABLED", "false")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_USE_VERTEX", "false")

    payload = build_startup_config_self_check()

    issues = {issue["code"]: issue for issue in payload["issues"]}
    assert payload["overall_status"] == "fail"
    assert issues["invalid_trusted_browser_origins"]["severity"] == "error"
    assert issues["invalid_trusted_browser_origins"]["missing_env"] == []


def test_startup_config_rejects_demo_student_admin_email_overlap(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "local-demo")
    monkeypatch.setenv("CLINICAL_OSCE_ADMIN_EMAILS", "shared-role@example.test")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_ENABLED", "true")
    monkeypatch.setenv(
        "CLINICAL_OSCE_DEMO_ADMIN_EMAIL",
        "configured-admin@example.test",
    )
    monkeypatch.setenv(
        "CLINICAL_OSCE_DEMO_ADMIN_PASSWORD",
        "configured-admin-password",
    )
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_ENABLED", "true")
    monkeypatch.setenv(
        "CLINICAL_OSCE_DEMO_STUDENT_EMAIL",
        "SHARED-ROLE@example.test",
    )
    monkeypatch.setenv(
        "CLINICAL_OSCE_DEMO_STUDENT_PASSWORD",
        "configured-student-password",
    )

    payload = build_startup_config_self_check()

    issues = {issue["code"]: issue for issue in payload["issues"]}
    assert payload["overall_status"] == "fail"
    assert issues["demo_role_email_overlap"]["severity"] == "error"
    assert issues["demo_role_email_overlap"]["missing_env"] == []


def test_public_health_is_redacted_and_detailed_config_requires_admin(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_ADMIN_EMAILS", "health-admin@example.test")
    monkeypatch.setenv("OSCE_VERTEX_PROJECT", "synthetic-private-project")
    monkeypatch.setenv(
        "OSCE_OPENAI_PROXY_URL",
        "http://synthetic-private-proxy.internal:7897",
    )
    auth_store = AuthStore(tmp_path / "health-auth.sqlite3")
    monkeypatch.setattr(main, "auth_store", auth_store, raising=False)
    student = auth_store.create_user(
        "health-student@example.test",
        "safe-password-123",
        "学生",
    )
    admin = auth_store.create_user(
        "health-admin@example.test",
        "safe-password-456",
        "管理员",
    )
    assert student is not None
    assert admin is not None

    with TestClient(main.app) as client:
        public_response = client.get("/api/health")
        anonymous_detail_response = client.get("/api/health/config")

        client.cookies.set(
            AUTH_COOKIE_NAME,
            auth_store.create_session(student["user_id"]),
        )
        student_detail_response = client.get("/api/health/config")

        client.cookies.set(
            AUTH_COOKIE_NAME,
            auth_store.create_session(admin["user_id"]),
        )
        admin_detail_response = client.get("/api/health/config")

    assert public_response.status_code == 200
    assert public_response.json() == {"status": "ok"}
    assert "synthetic-private-project" not in public_response.text
    assert "synthetic-private-proxy.internal" not in public_response.text
    assert anonymous_detail_response.status_code == 401
    assert student_detail_response.status_code == 403
    assert admin_detail_response.status_code == 200
    assert "providers" in admin_detail_response.json()


def test_runtime_model_config_not_exposed_in_production_ui(tmp_path, monkeypatch) -> None:
    runtime_model_config_store.clear()
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "vertex-prod")
    monkeypatch.setenv("CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS", "https://osce.example")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(main, "auth_store", auth_store, raising=False)
    user = auth_store.create_user("student@example.test", "safe-password-123", "学生甲")
    assert user is not None
    token = auth_store.create_session(user["user_id"])

    with TestClient(main.app) as client:
        client.cookies.set(AUTH_COOKIE_NAME, token)
        response = client.post(
            "/api/model-config/runtime",
            headers={"Origin": "https://osce.example", "Sec-Fetch-Site": "same-origin"},
            json={
                "provider": "openai_compatible",
                "api_key": "student-openai-secret",
                "model": "gpt-4.1-mini",
                "base_url": "https://api.openai.com/v1",
                "proxy_url": "",
            },
        )
        status_response = client.get("/api/model-config/runtime")

    assert response.status_code == 403
    assert response.json() == {"detail": "runtime model config is disabled in production deployment mode"}
    assert status_response.status_code == 200
    assert status_response.json()["runtime_write_supported"] is False
    assert status_response.json()["deployment_mode"] == "vertex-prod"
    assert status_response.json()["active"] is False


def test_compose_health_path_remains_valid() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    compose_payload = yaml.safe_load((repo_root / "docker-compose.yml").read_text(encoding="utf-8"))
    api_dockerfile_source = (repo_root / "services" / "api" / "Dockerfile").read_text(encoding="utf-8")
    api_service = compose_payload["services"]["api"]
    web_service = compose_payload["services"]["web"]
    admin_service = compose_payload["services"]["admin"]
    api_healthcheck = api_service["healthcheck"]["test"]
    web_healthcheck = web_service["healthcheck"]["test"]
    admin_healthcheck = admin_service["healthcheck"]["test"]

    assert any("http://127.0.0.1:8000/health" in str(part) for part in api_healthcheck)
    assert web_healthcheck[:2] == ["CMD", "node"]
    assert admin_healthcheck[:2] == ["CMD", "node"]
    assert any("http://127.0.0.1:3000/" in str(part) for part in web_healthcheck)
    assert any("http://127.0.0.1:3000/" in str(part) for part in admin_healthcheck)
    assert web_service["depends_on"] == {"api": {"condition": "service_healthy"}}
    assert admin_service["depends_on"] == {"api": {"condition": "service_healthy"}}
    assert '"--no-server-header"' in api_dockerfile_source
    assert (
        api_service["environment"]["CLINICAL_OSCE_DEPLOYMENT_MODE"]
        == "${CLINICAL_OSCE_DEPLOYMENT_MODE:-local-demo}"
    )
    assert (
        api_service["environment"]["CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS"]
        == (
            "${CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS:-"
            "http://localhost:3000,http://127.0.0.1:3001,http://127.0.0.1:8000}"
        )
    )
    assert (
        api_service["environment"]["CLINICAL_OSCE_SERVER_MANAGED_MODEL_CONFIG"]
        == "${CLINICAL_OSCE_SERVER_MANAGED_MODEL_CONFIG:-true}"
    )
    assert (
        api_service["environment"]["CLINICAL_OSCE_ACCOUNT_MODEL_ALLOWED_HOSTS"]
        == "${CLINICAL_OSCE_ACCOUNT_MODEL_ALLOWED_HOSTS:-api.openai.com,api.anthropic.com,generativelanguage.googleapis.com}"
    )
    assert (
        api_service["environment"]["CLINICAL_OSCE_ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS"]
        == "${CLINICAL_OSCE_ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS:-false}"
    )
    assert (
        api_service["environment"]["CLINICAL_OSCE_DEMO_ADMIN_ENABLED"]
        == "${CLINICAL_OSCE_DEMO_ADMIN_ENABLED:-false}"
    )
    assert (
        api_service["environment"]["CLINICAL_OSCE_DEMO_ADMIN_PASSWORD"]
        == "${CLINICAL_OSCE_DEMO_ADMIN_PASSWORD:-}"
    )
    assert (
        api_service["environment"]["CLINICAL_OSCE_DEMO_STUDENT_ENABLED"]
        == "${CLINICAL_OSCE_DEMO_STUDENT_ENABLED:-false}"
    )
    assert (
        api_service["environment"]["CLINICAL_OSCE_DEMO_STUDENT_EMAIL"]
        == "${CLINICAL_OSCE_DEMO_STUDENT_EMAIL:-}"
    )
    assert (
        api_service["environment"]["CLINICAL_OSCE_DEMO_STUDENT_PASSWORD"]
        == "${CLINICAL_OSCE_DEMO_STUDENT_PASSWORD:-}"
    )
    assert (
        api_service["environment"]["OSCE_CHROMA_COLLECTION"]
        == "${OSCE_CHROMA_COLLECTION:-clinical_osce_retrieval}"
    )
    assert api_service["environment"]["OSCE_CHROMA_SEARCH_EF"] == "${OSCE_CHROMA_SEARCH_EF:-500}"
    assert api_service["ports"] == ["${CLINICAL_OSCE_BIND_HOST:-127.0.0.1}:8000:8000"]
    assert web_service["ports"] == ["${CLINICAL_OSCE_BIND_HOST:-127.0.0.1}:3000:3000"]
    assert admin_service["ports"] == ["${CLINICAL_OSCE_BIND_HOST:-127.0.0.1}:3001:3000"]
    assert (
        web_service["build"]["args"]["NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE"]
        == "${NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE:-local-demo}"
    )
    assert (
        web_service["environment"]["NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE"]
        == "${NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE:-local-demo}"
    )
    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_env_example_defaults_to_server_managed_local_demo_without_demo_admin_password() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    env_example_source = (repo_root / ".env.example").read_text(encoding="utf-8")
    env_example_lines = set(env_example_source.splitlines())

    assert "CLINICAL_OSCE_DEPLOYMENT_MODE=local-demo" in env_example_source
    assert (
        "CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS="
        "http://localhost:3000,http://127.0.0.1:3001,"
        "http://127.0.0.1:3100,http://127.0.0.1:8000"
    ) in env_example_source
    assert "CLINICAL_OSCE_SERVER_MANAGED_MODEL_CONFIG=true" in env_example_source
    assert (
        "CLINICAL_OSCE_ACCOUNT_MODEL_ALLOWED_HOSTS=api.openai.com,api.anthropic.com,generativelanguage.googleapis.com"
        in env_example_source
    )
    assert (
        "CLINICAL_OSCE_ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS=false"
        in env_example_source
    )
    assert "CLINICAL_OSCE_BIND_HOST=127.0.0.1" in env_example_source
    assert "CLINICAL_OSCE_DEMO_ADMIN_ENABLED=false" in env_example_source
    assert "CLINICAL_OSCE_DEMO_ADMIN_PASSWORD=" in env_example_lines
    assert "CLINICAL_OSCE_DEMO_ADMIN_PASSWORD=admin" not in env_example_source
    assert "CLINICAL_OSCE_DEMO_STUDENT_ENABLED=false" in env_example_source
    assert "CLINICAL_OSCE_DEMO_STUDENT_EMAIL=" in env_example_lines
    assert "CLINICAL_OSCE_DEMO_STUDENT_PASSWORD=" in env_example_lines
    assert "CLINICAL_OSCE_DEMO_STUDENT_PASSWORD=student" not in env_example_source
    assert "OSCE_OPENAI_MODEL=gemini-3.5-flash" in env_example_source
    assert "OSCE_OPENAI_FALLBACK_MODEL=mimo-v2.5-pro" in env_example_source
    assert "OSCE_VERTEX_EMBEDDING_MODEL=gemini-embedding-001" in env_example_source
    assert "OSCE_LOCAL_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5" in env_example_source
    assert "OSCE_GEMINI_PATIENT_MODEL=gemini-3.1-flash-lite-preview" not in env_example_source
    assert "OSCE_VERTEX_MODEL=gemini-3.1-flash-lite-preview" not in env_example_source
    assert "OSCE_VERTEX_SKILL_CANDIDATE_MODEL=gemini-3.1-flash-lite-preview" not in env_example_source


def test_api_env_file_loader_applies_services_env_without_overriding_existing_env(tmp_path, monkeypatch) -> None:
    from app.services.env_file_loader import load_api_env_file

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "CLINICAL_OSCE_DEPLOYMENT_MODE=local-demo",
                "OSCE_OPENAI_MODEL=gemini-3.5-flash",
                "OSCE_OPENAI_API_KEY=from-env-file",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("CLINICAL_OSCE_DEPLOYMENT_MODE", raising=False)
    monkeypatch.delenv("OSCE_OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OSCE_OPENAI_API_KEY", "already-set")

    loaded = load_api_env_file(env_file)

    assert loaded is True
    assert os.environ["CLINICAL_OSCE_DEPLOYMENT_MODE"] == "local-demo"
    assert os.environ["OSCE_OPENAI_MODEL"] == "gemini-3.5-flash"
    assert os.environ["OSCE_OPENAI_API_KEY"] == "already-set"
