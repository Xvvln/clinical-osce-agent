from app.services.admin_audit_store import AdminAuditStore


def test_admin_audit_store_persists_filters_and_paginates(tmp_path) -> None:
    database_path = tmp_path / "admin-audit.sqlite3"
    store = AdminAuditStore(database_path)
    first = store.record(
        actor_user_id="admin-1",
        actor_email="admin@example.test",
        action="user.created",
        resource_type="user",
        resource_id="student-1",
        summary="创建学生账号",
        after={"email": "student@example.test"},
    )
    second = store.record(
        actor_user_id="admin-1",
        actor_email="admin@example.test",
        action="classroom.updated",
        resource_type="classroom",
        resource_id="classroom-1",
        summary="更新临床一班",
        before={"member_count": 1},
        after={"member_count": 2},
    )

    page = AdminAuditStore(database_path).list_events(limit=1, offset=0)
    filtered = store.list_events(
        limit=20,
        resource_type="user",
        query="student-1",
    )

    assert page["pagination"] == {"limit": 1, "offset": 0, "total": 2}
    assert page["events"][0]["event_id"] == second["event_id"]
    assert filtered["pagination"]["total"] == 1
    assert filtered["events"][0]["event_id"] == first["event_id"]
    assert filtered["events"][0]["after"] == {"email": "student@example.test"}
