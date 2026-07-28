from __future__ import annotations

import os

DEPLOYMENT_MODE_ENV_NAME = "CLINICAL_OSCE_DEPLOYMENT_MODE"
DEMO_ADMIN_ENABLED_ENV_NAME = "CLINICAL_OSCE_DEMO_ADMIN_ENABLED"
DEMO_ADMIN_EMAIL_ENV_NAME = "CLINICAL_OSCE_DEMO_ADMIN_EMAIL"
DEMO_ADMIN_PASSWORD_ENV_NAME = "CLINICAL_OSCE_DEMO_ADMIN_PASSWORD"
DEMO_STUDENT_ENABLED_ENV_NAME = "CLINICAL_OSCE_DEMO_STUDENT_ENABLED"
DEMO_STUDENT_EMAIL_ENV_NAME = "CLINICAL_OSCE_DEMO_STUDENT_EMAIL"
DEMO_STUDENT_PASSWORD_ENV_NAME = "CLINICAL_OSCE_DEMO_STUDENT_PASSWORD"
SERVER_MANAGED_MODEL_CONFIG_ENV_NAME = "CLINICAL_OSCE_SERVER_MANAGED_MODEL_CONFIG"
DEFAULT_DEPLOYMENT_MODE = "local-dev"
ALLOWED_DEPLOYMENT_MODES = ["local-dev", "local-demo", "single-node-prod", "vertex-prod"]
PRODUCTION_DEPLOYMENT_MODES = {"single-node-prod", "vertex-prod"}
LOCAL_DEMO_ACCOUNT_MODES = {"local-dev", "local-demo"}


def get_deployment_mode() -> str:
    mode = os.environ.get(DEPLOYMENT_MODE_ENV_NAME, DEFAULT_DEPLOYMENT_MODE).strip()
    return mode or DEFAULT_DEPLOYMENT_MODE


def is_known_deployment_mode(mode: str | None = None) -> bool:
    return (mode or get_deployment_mode()) in ALLOWED_DEPLOYMENT_MODES


def is_production_deployment_mode(mode: str | None = None) -> bool:
    return (mode or get_deployment_mode()) in PRODUCTION_DEPLOYMENT_MODES


def is_runtime_model_config_write_supported(mode: str | None = None) -> bool:
    return not is_production_deployment_mode(mode) and not _truthy(os.environ.get(SERVER_MANAGED_MODEL_CONFIG_ENV_NAME))


def is_account_registration_supported(mode: str | None = None) -> bool:
    return False


def is_demo_admin_effectively_enabled(mode: str | None = None) -> bool:
    return _is_demo_account_effectively_enabled(
        mode=mode,
        enabled_env_name=DEMO_ADMIN_ENABLED_ENV_NAME,
        email_env_name=DEMO_ADMIN_EMAIL_ENV_NAME,
        password_env_name=DEMO_ADMIN_PASSWORD_ENV_NAME,
    )


def is_demo_student_effectively_enabled(mode: str | None = None) -> bool:
    return _is_demo_account_effectively_enabled(
        mode=mode,
        enabled_env_name=DEMO_STUDENT_ENABLED_ENV_NAME,
        email_env_name=DEMO_STUDENT_EMAIL_ENV_NAME,
        password_env_name=DEMO_STUDENT_PASSWORD_ENV_NAME,
    )


def _is_demo_account_effectively_enabled(
    *,
    mode: str | None,
    enabled_env_name: str,
    email_env_name: str,
    password_env_name: str,
) -> bool:
    effective_mode = mode or get_deployment_mode()
    if effective_mode not in LOCAL_DEMO_ACCOUNT_MODES:
        return False
    return (
        _truthy(os.environ.get(enabled_env_name))
        and bool(os.environ.get(email_env_name, "").strip())
        and bool(os.environ.get(password_env_name, "").strip())
    )


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "ALLOWED_DEPLOYMENT_MODES",
    "DEFAULT_DEPLOYMENT_MODE",
    "DEMO_ADMIN_ENABLED_ENV_NAME",
    "DEMO_ADMIN_EMAIL_ENV_NAME",
    "DEMO_ADMIN_PASSWORD_ENV_NAME",
    "DEMO_STUDENT_ENABLED_ENV_NAME",
    "DEMO_STUDENT_EMAIL_ENV_NAME",
    "DEMO_STUDENT_PASSWORD_ENV_NAME",
    "DEPLOYMENT_MODE_ENV_NAME",
    "LOCAL_DEMO_ACCOUNT_MODES",
    "PRODUCTION_DEPLOYMENT_MODES",
    "SERVER_MANAGED_MODEL_CONFIG_ENV_NAME",
    "get_deployment_mode",
    "is_account_registration_supported",
    "is_demo_admin_effectively_enabled",
    "is_demo_student_effectively_enabled",
    "is_known_deployment_mode",
    "is_production_deployment_mode",
    "is_runtime_model_config_write_supported",
]
