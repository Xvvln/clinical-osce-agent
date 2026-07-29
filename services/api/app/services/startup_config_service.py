from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.deployment_config import (
    ADMIN_EMAILS_ENV_NAME,
    ALLOWED_DEPLOYMENT_MODES,
    DEMO_ADMIN_ENABLED_ENV_NAME,
    DEMO_ADMIN_EMAIL_ENV_NAME,
    DEMO_ADMIN_PASSWORD_ENV_NAME,
    DEMO_STUDENT_ENABLED_ENV_NAME,
    DEMO_STUDENT_EMAIL_ENV_NAME,
    DEMO_STUDENT_PASSWORD_ENV_NAME,
    DEPLOYMENT_MODE_ENV_NAME,
    get_deployment_mode,
    is_demo_student_admin_role_conflict,
    is_demo_admin_effectively_enabled,
    is_demo_student_effectively_enabled,
    is_known_deployment_mode,
    is_production_deployment_mode,
    is_account_registration_supported,
    is_runtime_model_config_write_supported,
)
from app.services.browser_origin_policy import (
    TRUSTED_BROWSER_ORIGINS_ENV_NAME,
    resolve_trusted_browser_origin_config,
)
from app.services.model_config_service import build_admin_model_config
from app.services.runtime_model_config_store import runtime_model_config_store

TRAINING_MODEL_CONFIG_REQUIRED_ENV_NAME = "OSCE_REQUIRE_RUNTIME_MODEL_CONFIG_FOR_TRAINING"
TRAINING_MODEL_PROVIDER_IDS = frozenset(
    {
        "anthropic",
        "gemini_patient_api",
        "gemini_patient_vertex",
        "openai_compatible",
    }
)


@dataclass(frozen=True)
class SQLiteReadinessTarget:
    database_path: Path
    required_tables: tuple[str, ...]


def build_startup_config_self_check(
    *,
    include_retrieval_manifest: bool = True,
) -> dict[str, Any]:
    mode = get_deployment_mode()
    production = is_production_deployment_mode(mode)
    browser_origin_config = resolve_trusted_browser_origin_config(mode)
    runtime_status = runtime_model_config_store.public_status()
    model_config = build_admin_model_config(
        include_retrieval_manifest=include_retrieval_manifest,
    )
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
            "trusted_browser_origins": sorted(browser_origin_config.origins),
            "trusted_browser_origins_explicit": browser_origin_config.explicit,
        },
        "providers": model_config["providers"],
        "issues": issues,
    }


def build_readiness_self_check(
    *,
    writable_directories: Iterable[Path],
    sqlite_targets: Iterable[SQLiteReadinessTarget],
    admin_account_ready: bool = True,
    startup_persistence_ready: bool = True,
    startup_recovery_ready: bool = True,
) -> dict[str, Any]:
    """Build the public, redacted readiness result.

    Detailed configuration diagnostics remain behind the administrator-only
    endpoint.  This payload deliberately exposes only stable issue categories:
    neither filesystem paths, environment names, provider endpoints, nor raw
    exception text are returned to an unauthenticated caller.
    """

    try:
        config_ready = (
            build_startup_config_self_check(
                include_retrieval_manifest=False,
            )["overall_status"]
            == "ok"
        )
    except Exception:
        config_ready = False
    persistence_ready = (
        startup_persistence_ready
        and _persistence_is_ready(
            writable_directories=writable_directories,
            sqlite_targets=sqlite_targets,
        )
    )
    issues: list[dict[str, str]] = []
    if not config_ready:
        issues.append({"code": "startup_config_invalid"})
    if not admin_account_ready:
        issues.append({"code": "admin_account_unavailable"})
    if not persistence_ready:
        issues.append({"code": "persistence_unavailable"})
    if not startup_recovery_ready:
        issues.append({"code": "startup_recovery_incomplete"})
    ready = not issues
    return {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "configuration": "ok" if config_ready else "fail",
            "admin_account": "ok" if admin_account_ready else "fail",
            "persistence": "ok" if persistence_ready else "fail",
            "startup_recovery": "ok" if startup_recovery_ready else "fail",
        },
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

    browser_origin_config = resolve_trusted_browser_origin_config(mode)
    if browser_origin_config.invalid_values:
        issues.append(
            _issue(
                code="invalid_trusted_browser_origins",
                message=(
                    f"{TRUSTED_BROWSER_ORIGINS_ENV_NAME} must contain exact browser origins "
                    "without wildcards, paths, credentials, or null values; production origins must use HTTPS."
                ),
                missing_env=[],
            )
        )
    elif production and not browser_origin_config.explicit:
        issues.append(
            _issue(
                code="missing_trusted_browser_origins",
                message=f"{TRUSTED_BROWSER_ORIGINS_ENV_NAME} is required in production deployment modes.",
                missing_env=[TRUSTED_BROWSER_ORIGINS_ENV_NAME],
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

    if (
        production
        and _training_model_config_is_required()
        and not any(
            provider.get("provider_id") in TRAINING_MODEL_PROVIDER_IDS
            and provider.get("configured") is True
            for provider in providers
        )
    ):
        issues.append(
            _issue(
                code="missing_training_model_provider",
                message=(
                    "Production training requires at least one configured "
                    "server-managed model provider."
                ),
                missing_env=[],
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

    if is_demo_student_admin_role_conflict(mode):
        issues.append(
            _issue(
                code="demo_role_email_overlap",
                message=(
                    "The configured demo student email must not also be a demo "
                    "administrator or appear in CLINICAL_OSCE_ADMIN_EMAILS."
                ),
                missing_env=[],
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


def _training_model_config_is_required() -> bool:
    value = _env(TRAINING_MODEL_CONFIG_REQUIRED_ENV_NAME).lower()
    return value not in {"0", "false", "no", "off"}


def _persistence_is_ready(
    *,
    writable_directories: Iterable[Path],
    sqlite_targets: Iterable[SQLiteReadinessTarget],
) -> bool:
    try:
        directories = tuple(dict.fromkeys(Path(path) for path in writable_directories))
        targets = tuple(sqlite_targets)
        if not directories or not targets:
            return False
        if not all(_directory_is_writable(path) for path in directories):
            return False
        return all(_sqlite_target_is_ready(target) for target in targets)
    except Exception:
        return False


def _directory_is_writable(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK | os.X_OK)


def _sqlite_target_is_ready(target: SQLiteReadinessTarget) -> bool:
    try:
        if (
            not target.database_path.is_file()
            or not os.access(target.database_path, os.R_OK | os.W_OK)
        ):
            return False
        database_uri = f"{target.database_path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(
            database_uri,
            timeout=0.5,
            uri=True,
        ) as connection:
            table_names = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            connection.execute("SELECT 1").fetchone()
        return set(target.required_tables).issubset(table_names)
    except (OSError, sqlite3.Error):
        return False


__all__ = [
    "SQLiteReadinessTarget",
    "TRAINING_MODEL_CONFIG_REQUIRED_ENV_NAME",
    "build_readiness_self_check",
    "build_startup_config_self_check",
]
