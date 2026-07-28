from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.services.deployment_config import (
    get_deployment_mode,
    is_known_deployment_mode,
    is_production_deployment_mode,
)

TRUSTED_BROWSER_ORIGINS_ENV_NAME = "CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS"
DEFAULT_LOCAL_TRUSTED_BROWSER_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3100",
    "http://127.0.0.1:8000",
)
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class TrustedBrowserOriginConfig:
    origins: frozenset[str]
    invalid_values: tuple[str, ...]
    explicit: bool
    known_mode: bool
    production: bool

    @property
    def valid(self) -> bool:
        return self.known_mode and not self.invalid_values and (not self.production or self.explicit)


def resolve_trusted_browser_origin_config(mode: str | None = None) -> TrustedBrowserOriginConfig:
    effective_mode = mode or get_deployment_mode()
    known_mode = is_known_deployment_mode(effective_mode)
    production = is_production_deployment_mode(effective_mode)
    configured_values = [
        value
        for value in os.environ.get(TRUSTED_BROWSER_ORIGINS_ENV_NAME, "").split(",")
        if value.strip()
    ]
    explicit = bool(configured_values)

    if not explicit and known_mode and not production:
        return TrustedBrowserOriginConfig(
            origins=frozenset(DEFAULT_LOCAL_TRUSTED_BROWSER_ORIGINS),
            invalid_values=(),
            explicit=False,
            known_mode=True,
            production=False,
        )

    origins: set[str] = set()
    invalid_values: list[str] = []
    for value in configured_values:
        normalized_origin = normalize_browser_origin(value)
        if (
            normalized_origin is None
            or (production and not normalized_origin.startswith("https://"))
        ):
            invalid_values.append(value.strip())
            continue
        origins.add(normalized_origin)

    return TrustedBrowserOriginConfig(
        origins=frozenset(origins),
        invalid_values=tuple(invalid_values),
        explicit=explicit,
        known_mode=known_mode,
        production=production,
    )


def browser_state_change_request_rejection_reason(
    *,
    method: str,
    path: str,
    origin: str | None,
    referer: str | None,
    sec_fetch_site: str | None,
    mode: str | None = None,
) -> str | None:
    if not _requires_browser_origin_check(method, path):
        return None

    config = resolve_trusted_browser_origin_config(mode)
    if not config.valid:
        return "trusted_browser_origins_misconfigured"

    normalized_fetch_site = str(sec_fetch_site or "").strip().lower()
    if normalized_fetch_site == "cross-site":
        return "cross_origin_fetch_site"

    if origin is not None:
        normalized_origin = normalize_browser_origin(origin)
        if normalized_origin is None or normalized_origin not in config.origins:
            return "untrusted_origin"
        return None

    if referer is not None:
        normalized_referer_origin = normalize_browser_origin(referer, allow_path=True)
        if normalized_referer_origin is None or normalized_referer_origin not in config.origins:
            return "untrusted_referer"
        return None

    if normalized_fetch_site == "same-site":
        return "cross_origin_fetch_site"
    if config.production:
        return "missing_browser_origin"
    return None


def normalize_browser_origin(value: str, *, allow_path: bool = False) -> str | None:
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        return None
    candidate = value.strip()
    if not candidate or candidate.lower() == "null" or any(character.isspace() for character in candidate):
        return None

    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc or parsed.hostname is None:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if not allow_path and parsed.path:
        return None
    if not allow_path and (parsed.query or parsed.fragment or "?" in candidate or "#" in candidate):
        return None

    hostname = parsed.hostname.lower()
    if "*" in hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    rendered_hostname = f"[{hostname}]" if ":" in hostname else hostname
    rendered_port = f":{port}" if port is not None else ""
    return f"{scheme}://{rendered_hostname}{rendered_port}"


def _requires_browser_origin_check(method: str, path: str) -> bool:
    normalized_method = method.upper()
    return normalized_method in UNSAFE_METHODS and (path == "/api" or path.startswith("/api/"))


__all__ = [
    "DEFAULT_LOCAL_TRUSTED_BROWSER_ORIGINS",
    "TRUSTED_BROWSER_ORIGINS_ENV_NAME",
    "TrustedBrowserOriginConfig",
    "browser_state_change_request_rejection_reason",
    "normalize_browser_origin",
    "resolve_trusted_browser_origin_config",
]
