from app.services.admin_asset_version_store import AdminAssetVersionStore


def test_admin_asset_versions_persist_diff_and_paginate(tmp_path) -> None:
    store = AdminAssetVersionStore(tmp_path / "asset_versions.sqlite3")
    initial = store.ensure_initial_version(
        asset_type="case",
        asset_id="case-1",
        payload={"case": {"title": "初版", "facts": ["A"]}},
        actor_user_id="admin-1",
        actor_email="admin@example.test",
    )
    duplicate_initial = store.ensure_initial_version(
        asset_type="case",
        asset_id="case-1",
        payload={"case": {"title": "不会覆盖", "facts": []}},
        actor_user_id="admin-2",
        actor_email="other@example.test",
    )
    updated = store.save_version(
        asset_type="case",
        asset_id="case-1",
        payload={"case": {"title": "修订版", "facts": ["A", "B"]}},
        actor_user_id="admin-1",
        actor_email="admin@example.test",
        change_note="补充事实",
        review_status="approved",
        review_note="医学教师复核通过",
    )

    assert initial["version"] == 1
    assert duplicate_initial["payload"]["case"]["title"] == "初版"
    assert updated["version"] == 2
    assert store.get_latest_version(asset_type="case", asset_id="case-1") == updated

    page = store.list_versions(asset_type="case", asset_id="case-1", limit=1, offset=0)
    assert page["pagination"] == {"limit": 1, "offset": 0, "total": 2}
    assert page["versions"][0]["version"] == 2
    assert "payload" not in page["versions"][0]

    diff = store.diff_versions(
        asset_type="case",
        asset_id="case-1",
        from_version=1,
        to_version=2,
    )
    assert diff is not None
    assert diff["change_count"] == 2
    assert {change["path"] for change in diff["changes"]} == {
        "$.case.facts[1]",
        "$.case.title",
    }


def test_admin_asset_version_diff_requires_both_versions(tmp_path) -> None:
    store = AdminAssetVersionStore(tmp_path / "asset_versions.sqlite3")
    store.save_version(
        asset_type="source",
        asset_id="source-1",
        payload={"source_id": "source-1"},
        actor_user_id="admin-1",
        actor_email="admin@example.test",
        change_note="创建",
        review_status="unreviewed",
        review_note="",
    )

    assert store.diff_versions(
        asset_type="source",
        asset_id="source-1",
        from_version=1,
        to_version=9,
    ) is None
