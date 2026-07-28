from app.services.student_profile_store import StudentProfileStore


def test_delete_profile_is_exact_and_idempotent(tmp_path) -> None:
    database_path = tmp_path / "student_profiles.sqlite3"
    store = StudentProfileStore(database_path)
    store.save_profile("student_delete", {"summary": "待删除"})
    store.save_profile("student_keep", {"summary": "保留"})

    assert store.delete_profile("student_delete") is True
    assert StudentProfileStore(database_path).delete_profile("student_delete") is False
    assert store.get_profile("student_delete") is None
    assert store.get_profile("student_keep") == {
        "student_id": "student_keep",
        "summary": "保留",
    }

