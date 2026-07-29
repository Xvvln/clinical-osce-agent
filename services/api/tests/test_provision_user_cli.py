from __future__ import annotations

from pathlib import Path

import pytest

from app.services.auth_store import AuthStore
from scripts import provision_user as provision_module
from scripts.provision_user import (
    UserAlreadyProvisionedError,
    provision_user,
)


def test_provision_user_creates_a_persistent_login(tmp_path: Path) -> None:
    database_path = tmp_path / "auth.sqlite3"

    action = provision_user(
        database_path=database_path,
        email=" Admin@Example.Test ",
        password="a-secure-password",
        display_name="生产管理员",
    )

    store = AuthStore(database_path)
    assert action == "created"
    user = store.authenticate_user("admin@example.test", "a-secure-password")
    assert user is not None
    assert user["display_name"] == "生产管理员"
    assert store.has_any_user(
        {"missing@example.test", "ADMIN@example.test"}
    ) is True


def test_existing_user_requires_explicit_rotation_and_keeps_old_password(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "auth.sqlite3"
    provision_user(
        database_path=database_path,
        email="student@example.test",
        password="first-password",
    )

    with pytest.raises(UserAlreadyProvisionedError):
        provision_user(
            database_path=database_path,
            email="student@example.test",
            password="second-password",
        )

    store = AuthStore(database_path)
    assert store.authenticate_user(
        "student@example.test",
        "first-password",
    ) is not None
    assert store.authenticate_user(
        "student@example.test",
        "second-password",
    ) is None


def test_explicit_password_rotation_revokes_existing_sessions(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "auth.sqlite3"
    provision_user(
        database_path=database_path,
        email="student@example.test",
        password="first-password",
        display_name="学生甲",
    )
    store = AuthStore(database_path)
    user = store.authenticate_user("student@example.test", "first-password")
    assert user is not None
    token = store.create_session(user["user_id"])

    action = provision_user(
        database_path=database_path,
        email="student@example.test",
        password="second-password",
        rotate_password=True,
    )

    assert action == "rotated"
    assert store.authenticate_user(
        "student@example.test",
        "first-password",
    ) is None
    assert store.authenticate_user(
        "student@example.test",
        "second-password",
    ) is not None
    assert store.get_user_by_session_token(token) is None
    assert store.get_user_by_email("student@example.test")["display_name"] == (
        "学生甲"
    )


def test_cli_prompts_for_password_without_echoing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "not-printed-password"
    responses = iter([secret, secret])
    monkeypatch.setattr(
        provision_module.getpass,
        "getpass",
        lambda _: next(responses),
    )

    result = provision_module.main(
        [
            "--database",
            str(tmp_path / "auth.sqlite3"),
            "--email",
            "operator@example.test",
            "--display-name",
            "运维账号",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "operator@example.test" in captured.out
    assert secret not in captured.out
    assert secret not in captured.err
