from pathlib import Path

from fastapi.testclient import TestClient
import yaml

from app import main
from app.services.auth_store import AuthStore
from app.services.runtime_model_config_store import runtime_model_config_store


def test_startup_config_self_check_reports_missing_required_env(monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")
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

    with TestClient(main.app) as client:
        response = client.get("/api/health/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deployment"] == {
        "mode": "single-node-prod",
        "production": True,
        "allowed_modes": ["local-dev", "local-demo", "single-node-prod", "vertex-prod"],
    }
    assert payload["overall_status"] == "fail"
    assert payload["runtime_config"]["active"] is False
    assert payload["runtime_config"]["write_supported"] is False
    assert payload["policy"]["demo_admin_effective_enabled"] is False

    issue_codes = {issue["code"] for issue in payload["issues"]}
    assert {
        "missing_admin_emails",
        "openai_missing_env",
        "vertex_missing_project",
        "chroma_missing_env",
    }.issubset(issue_codes)

    providers = {provider["provider_id"]: provider for provider in payload["providers"]}
    assert providers["openai_compatible"]["enabled"] is True
    assert providers["openai_compatible"]["configured"] is False
    assert providers["openai_compatible"]["missing_env"] == ["OSCE_OPENAI_API_KEY", "OSCE_OPENAI_MODEL"]
    assert providers["vertex_rubric_scorer"]["missing_env"] == ["OSCE_VERTEX_PROJECT"]
    assert providers["chroma_retrieval"]["missing_env"] == ["CHROMA_PERSIST_DIRECTORY", "OSCE_CHROMA_COLLECTION"]


def test_production_mode_disables_demo_admin_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "single-node-prod")
    monkeypatch.delenv("CLINICAL_OSCE_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("CLINICAL_OSCE_DEMO_ADMIN_ENABLED", raising=False)
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/auth/login",
            json={"email": "admin-demo@example.test", "password": "safe-admin-password"},
        )

    assert response.status_code == 401


def test_runtime_model_config_not_exposed_in_production_ui(monkeypatch) -> None:
    runtime_model_config_store.clear()
    monkeypatch.setenv("CLINICAL_OSCE_DEPLOYMENT_MODE", "vertex-prod")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/model-config/runtime",
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
    api_service = compose_payload["services"]["api"]
    web_service = compose_payload["services"]["web"]
    api_healthcheck = api_service["healthcheck"]["test"]

    assert any("http://127.0.0.1:8000/health" in str(part) for part in api_healthcheck)
    assert api_service["environment"]["CLINICAL_OSCE_DEPLOYMENT_MODE"] == "local-demo"
    assert api_service["environment"]["CLINICAL_OSCE_DEMO_ADMIN_ENABLED"] == "true"
    assert web_service["build"]["args"]["NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE"] == "local-demo"
    assert web_service["environment"]["NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE"] == "local-demo"
    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
