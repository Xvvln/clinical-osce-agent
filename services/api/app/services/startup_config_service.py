from __future__ import annotations

import os
from typing import Any

from app.services.deployment_config import (
    ALLOWED_DEPLOYMENT_MODES,
    DEMO_ADMIN_ENABLED_ENV_NAME,
    DEMO_ADMIN_EMAIL_ENV_NAME,
    DEMO_ADMIN_PASSWORD_ENV_NAME,
    DEMO_STUDENT_ENABLED_ENV_NAME,
    DEMO_STUDENT_EMAIL_ENV_NAME,
    DEMO_STUDENT_PASSWORD_ENV_NAME,
    DEPLOYMENT_MODE_ENV_NAME,
    get_deployment_mode,
    is_demo_admin_effectively_enabled,
    is_demo_student_effectively_enabled,
    is_known_deployment_mode,
    is_production_deployment_mode,
    is_account_registration_supported,
    is_runtime_model_config_write_supported,
)
from app.services.model_config_service import build_admin_model_config
from app.services.runtime_model_config_store import runtime_model_config_store

ADMIN_EMAILS_ENV_NAME = "CLINICAL_OSCE_ADMIN_EMAILS"


def build_startup_config_self_check() -> dict[str, Any]:
    mode = get_deployment_mode()
    production = is_production_deployment_mode(mode)
    runtime_status = runtime_model_config_store.public_status()
    model_config = build_admin_model_config()
    issues = _build_startup_config_issues(mode, production, model_config["providers"])
    overall_status = "fail" if any(issue["severity"] == "error" for issue in issues) else "ok"

    return {
        "overall_status": overall_status,
        "deployment": {
            "mode": mode,
            "production": production,
            "allowed_modes": list(ALLOWED_DEPLOYMENT_MODES),
        },
        "runtime_config": {
            "active": bool(runtime_status["active"]),
            "provider": runtime_status["provider"],
            "model": runtime_status["model"],
            "write_supported": is_runtime_model_config_write_supported(mode),
            "persistence": "runtime_memory_only",
        },
        "policy": {
            "demo_admin_effective_enabled": is_demo_admin_effectively_enabled(mode),
            "demo_student_effective_enabled": is_demo_student_effectively_enabled(mode),
            "runtime_write_supported": is_runtime_model_config_write_supported(mode),
            "account_registration_supported": is_account_registration_supported(mode),
            "configuration_source": "environment_only" if production else "environment_or_runtime_memory",
        },
        "providers": model_config["providers"],
        "issues": issues,
    }


def _build_startup_config_issues(
    mode: str,
    production: bool,
    providers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not is_known_deployment_mode(mode):
        issues.append(
            _issue(
                code="invalid_deployment_mode",
                message=f"{DEPLOYMENT_MODE_ENV_NAME} must be one of {', '.join(ALLOWED_DEPLOYMENT_MODES)}.",
                missing_env=[],
            )
        )

    if production and not _env(ADMIN_EMAILS_ENV_NAME) and not is_demo_admin_effectively_enabled(mode):
        issues.append(
            _issue(
                code="missing_admin_emails",
                message=f"{ADMIN_EMAILS_ENV_NAME} is required when demo admin is disabled in production modes.",
                missing_env=[ADMIN_EMAILS_ENV_NAME],
            )
        )

    if production and _truthy_env(DEMO_ADMIN_ENABLED_ENV_NAME):
        issues.append(
            _issue(
                code="demo_admin_enabled_in_production",
                severity="warning",
                message=f"{DEMO_ADMIN_ENABLED_ENV_NAME}=true is ignored in production deployment modes.",
                missing_env=[],
            )
        )
    elif _truthy_env(DEMO_ADMIN_ENABLED_ENV_NAME):
        missing_demo_admin_env = _missing_env(
            DEMO_ADMIN_EMAIL_ENV_NAME,
            DEMO_ADMIN_PASSWORD_ENV_NAME,
        )
        if missing_demo_admin_env:
            issues.append(
                _issue(
                    code="demo_admin_incomplete",
                    message="Demo admin is enabled but its explicit email or password is missing.",
                    missing_env=missing_demo_admin_env,
                )
            )

    if production and _truthy_env(DEMO_STUDENT_ENABLED_ENV_NAME):
        issues.append(
            _issue(
                code="demo_student_enabled_in_production",
                severity="warning",
                message=f"{DEMO_STUDENT_ENABLED_ENV_NAME}=true is ignored in production deployment modes.",
                missing_env=[],
            )
        )
    elif _truthy_env(DEMO_STUDENT_ENABLED_ENV_NAME):
        missing_demo_student_env = _missing_env(
            DEMO_STUDENT_EMAIL_ENV_NAME,
            DEMO_STUDENT_PASSWORD_ENV_NAME,
        )
        if missing_demo_student_env:
            issues.append(
                _issue(
                    code="demo_student_incomplete",
                    message="Demo student is enabled but its explicit email or password is missing.",
                    missing_env=missing_demo_student_env,
                )
            )

    for provider in providers:
        if not provider.get("enabled"):
            continue
        missing_env = [str(name) for name in provider.get("missing_env", [])]
        if not missing_env:
            continue
        issue_code = _provider_issue_code(str(provider["provider_id"]))
        issues.append(
            _issue(
                code=issue_code,
                message=f"{provider['label']} is enabled but missing required configuration.",
                missing_env=missing_env,
                provider_id=str(provider["provider_id"]),
            )
        )
    return issues


def _provider_issue_code(provider_id: str) -> str:
    if provider_id == "openai_compatible":
        return "openai_missing_env"
    if provider_id == "chroma_retrieval":
        return "chroma_missing_env"
    if provider_id.startswith("vertex_") or provider_id == "gemini_patient_vertex":
        return "vertex_missing_auth"
    if provider_id == "gemini_patient_api":
        return "gemini_missing_env"
    return "provider_missing_env"


def _issue(
    *,
    code: str,
    severity: str = "error",
    message: str,
    missing_env: list[str],
    provider_id: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "provider_id": provider_id,
        "missing_env": missing_env,
    }


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _truthy_env(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


def _missing_env(*names: str) -> list[str]:
    return [name for name in names if not _env(name)]


__all__ = ["build_startup_config_self_check"]
