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


def test_classroom_store_assigns_teacher_archives_and_transfers_members(tmp_path) -> None:
    store = ClassroomStore(tmp_path / "classrooms.sqlite3")
    source = store.create_classroom(
        name="临床一班",
        description="",
        member_user_ids=["student-a", "student-b"],
        actor_user_id="admin-1",
        teacher_user_id="teacher-1",
    )
    target = store.create_classroom(
        name="临床二班",
        description="",
        member_user_ids=["student-c"],
        actor_user_id="admin-1",
    )

    transferred = store.transfer_members(
        source_classroom_id=source["classroom_id"],
        target_classroom_id=target["classroom_id"],
        member_user_ids=["student-b"],
        move=True,
        actor_user_id="admin-2",
    )
    archived = store.update_classroom(
        source["classroom_id"],
        name="临床一班",
        description="已结课",
        member_user_ids=["student-a"],
        actor_user_id="admin-2",
        teacher_user_id="teacher-1",
        status="archived",
    )

    assert transferred is not None
    transferred_source, transferred_target = transferred
    assert transferred_source["member_user_ids"] == ["student-a"]
    assert transferred_target["member_user_ids"] == ["student-c", "student-b"]
    assert archived is not None
    assert archived["teacher_user_id"] == "teacher-1"
    assert archived["status"] == "archived"


def test_classroom_store_imports_new_and_existing_classrooms_atomically(tmp_path) -> None:
    store = ClassroomStore(tmp_path / "classrooms.sqlite3")
    existing = store.create_classroom(
        name="临床一班",
        description="旧说明",
        member_user_ids=["student-a"],
        actor_user_id="admin-1",
    )

    imported = store.import_classrooms(
        [
            {
                "name": "临床一班",
                "description": "新说明",
                "teacher_user_id": "teacher-1",
                "status": "active",
                "member_user_ids": ["student-a", "student-b"],
            },
            {
                "name": "临床二班",
                "description": "新建班级",
                "teacher_user_id": "",
                "status": "archived",
                "member_user_ids": ["student-c"],
            },
        ],
        actor_user_id="admin-2",
    )

    assert imported[0]["classroom_id"] == existing["classroom_id"]
    assert imported[0]["member_user_ids"] == ["student-a", "student-b"]
    assert imported[0]["teacher_user_id"] == "teacher-1"
    assert imported[1]["status"] == "archived"
    assert len(store.list_classrooms()) == 2
