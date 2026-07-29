from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import Sequence

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.auth_store import (  # noqa: E402
    DEFAULT_DATABASE_PATH,
    AuthStore,
)

AUTH_EMAIL_MAX_CHARS = 254
AUTH_PASSWORD_MIN_CHARS = 12
AUTH_PASSWORD_MAX_CHARS = 256
DISPLAY_NAME_MAX_CHARS = 120


class UserAlreadyProvisionedError(RuntimeError):
    pass


def provision_user(
    *,
    database_path: Path,
    email: str,
    password: str,
    display_name: str = "",
    rotate_password: bool = False,
) -> str:
    normalized_email = _validate_email(email)
    _validate_password(password)
    normalized_display_name = _validate_display_name(display_name)
    store = AuthStore(database_path)
    existing = store.get_user_by_email(normalized_email)
    if existing is not None and not rotate_password:
        raise UserAlreadyProvisionedError(
            "user already exists; pass --rotate-password to replace credentials"
        )
    if existing is None:
        created = store.create_user(
            normalized_email,
            password,
            normalized_display_name or normalized_email,
        )
        if created is None:
            raise UserAlreadyProvisionedError("user was provisioned concurrently")
        return "created"

    store.upsert_user_password(
        email=normalized_email,
        password=password,
        display_name=normalized_display_name or existing["display_name"],
    )
    return "rotated"


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Provision a persistent OSCE user without putting the password "
            "in command arguments or environment variables."
        )
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", default="")
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"Auth SQLite path (default: {DEFAULT_DATABASE_PATH})",
    )
    parser.add_argument(
        "--rotate-password",
        action="store_true",
        help="Replace an existing user's password and revoke its active sessions.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        parser.error("password confirmation does not match")
    try:
        action = provision_user(
            database_path=args.database,
            email=args.email,
            password=password,
            display_name=args.display_name,
            rotate_password=args.rotate_password,
        )
    except (ValueError, UserAlreadyProvisionedError) as exc:
        parser.error(str(exc))
    print(f"Persistent user {args.email.strip().lower()} {action}.")
    return 0


def _validate_email(email: str) -> str:
    normalized = email.strip().lower()
    if (
        not normalized
        or len(normalized) > AUTH_EMAIL_MAX_CHARS
        or normalized.count("@") != 1
    ):
        raise ValueError("a valid email is required")
    local_part, domain = normalized.split("@", maxsplit=1)
    if not local_part or not domain or any(character.isspace() for character in normalized):
        raise ValueError("a valid email is required")
    return normalized


def _validate_password(password: str) -> None:
    if not AUTH_PASSWORD_MIN_CHARS <= len(password) <= AUTH_PASSWORD_MAX_CHARS:
        raise ValueError(
            "password must contain between "
            f"{AUTH_PASSWORD_MIN_CHARS} and {AUTH_PASSWORD_MAX_CHARS} characters"
        )


def _validate_display_name(display_name: str) -> str:
    normalized = display_name.strip()
    if len(normalized) > DISPLAY_NAME_MAX_CHARS:
        raise ValueError(
            f"display name must not exceed {DISPLAY_NAME_MAX_CHARS} characters"
        )
    return normalized


if __name__ == "__main__":
    raise SystemExit(main())
