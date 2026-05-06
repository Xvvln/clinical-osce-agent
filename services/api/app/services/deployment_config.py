from __future__ import annotations

import os

DEPLOYMENT_MODE_ENV_NAME = "CLINICAL_OSCE_DEPLOYMENT_MODE"
DEMO_ADMIN_ENABLED_ENV_NAME = "CLINICAL_OSCE_DEMO_ADMIN_ENABLED"
DEFAULT_DEPLOYMENT_MODE = "local-dev"
ALLOWED_DEPLOYMENT_MODES = ["local-dev", "local-demo", "single-node-prod", "vertex-prod"]
PRODUCTION_DEPLOYMENT_MODES = {"single-node-prod", "vertex-prod"}


def get_deployment_mode() -> str:
    mode = os.environ.get(DEPLOYMENT_MODE_ENV_NAME, DEFAULT_DEPLOYMENT_MODE).strip()
    return mode or DEFAULT_DEPLOYMENT_MODE


def is_known_deployment_mode(mode: str | None = None) -> bool:
    return (mode or get_deployment_mode()) in ALLOWED_DEPLOYMENT_MODES


def is_production_deployment_mode(mode: str | None = None) -> bool:
    return (mode or get_deployment_mode()) in PRODUCTION_DEPLOYMENT_MODES


def is_runtime_model_config_write_supported(mode: str | None = None) -> bool:
    return not is_production_deployment_mode(mode)


def is_demo_admin_effectively_enabled(mode: str | None = None) -> bool:
    configured_value = os.environ.get(DEMO_ADMIN_ENABLED_ENV_NAME)
    if configured_value is None:
        return not is_production_deployment_mode(mode)
    return _truthy(configured_value)


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "ALLOWED_DEPLOYMENT_MODES",
    "DEFAULT_DEPLOYMENT_MODE",
    "DEMO_ADMIN_ENABLED_ENV_NAME",
    "DEPLOYMENT_MODE_ENV_NAME",
    "PRODUCTION_DEPLOYMENT_MODES",
    "get_deployment_mode",
    "is_demo_admin_effectively_enabled",
    "is_known_deployment_mode",
    "is_production_deployment_mode",
    "is_runtime_model_config_write_supported",
]
