import pytest

from app.services.classroom_store import (
    ClassroomNameConflictError,
    ClassroomStore,
)


def test_classroom_store_persists_membership_replacement_and_deletion(tmp_path) -> None:
    database_path = tmp_path / "classrooms.sqlite3"
    store = ClassroomStore(database_path)

    classroom = store.create_classroom(
        name="2026 级临床一班",
        description="春季 OSCE 训练班",
        member_user_ids=["student-a", "student-b", "student-a"],
        actor_user_id="admin-1",
    )

    assert classroom["name"] == "2026 级临床一班"
    assert classroom["member_user_ids"] == ["student-a", "student-b"]
    assert ClassroomStore(database_path).get_classroom(classroom["classroom_id"]) == classroom

    updated = store.update_classroom(
        classroom["classroom_id"],
        name="2026 级临床一班 A 组",
        description="调整后的综合训练组",
        member_user_ids=["student-b", "student-c"],
        actor_user_id="admin-2",
    )

    assert updated is not None
    assert updated["member_user_ids"] == ["student-b", "student-c"]
    assert updated["updated_by"] == "admin-2"
    assert store.delete_classroom(classroom["classroom_id"]) is True
    assert store.get_classroom(classroom["classroom_id"]) is None
    assert store.delete_classroom(classroom["classroom_id"]) is False


def test_classroom_store_rejects_case_insensitive_duplicate_names(tmp_path) -> None:
    store = ClassroomStore(tmp_path / "classrooms.sqlite3")
    store.create_classroom(
        name="Clinical A",
        description="",
        member_user_ids=[],
        actor_user_id="admin-1",
    )

    with pytest.raises(ClassroomNameConflictError):
        store.create_classroom(
            name="clinical a",
            description="",
            member_user_ids=[],
            actor_user_id="admin-1",
        )


def test_updating_unknown_classroom_does_not_create_memberships(tmp_path) -> None:
    store = ClassroomStore(tmp_path / "classrooms.sqlite3")

    assert (
        store.update_classroom(
            "missing-classroom",
            name="不应创建",
            description="",
            member_user_ids=["student-a"],
            actor_user_id="admin-1",
        )
        is None
    )
    assert store.list_classrooms() == []
