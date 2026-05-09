from app.services.training_skill_auto_approval_service import TrainingSkillAutoApprovalSettingsStore


def test_training_skill_auto_approval_settings_default_to_manual_review(tmp_path) -> None:
    store = TrainingSkillAutoApprovalSettingsStore(tmp_path / "training_skill_auto_approval.sqlite3")

    settings = store.get_settings()

    assert settings == {
        "auto_apply_enabled": False,
        "approval_agent_id": "skill_auto_approval_agent",
        "updated_by": "",
        "updated_at": None,
    }


def test_training_skill_auto_approval_settings_persist_across_instances(tmp_path) -> None:
    database_path = tmp_path / "training_skill_auto_approval.sqlite3"

    TrainingSkillAutoApprovalSettingsStore(database_path).update_settings(
        auto_apply_enabled=True,
        updated_by="admin@example.test",
    )
    settings = TrainingSkillAutoApprovalSettingsStore(database_path).get_settings()

    assert settings["auto_apply_enabled"] is True
    assert settings["approval_agent_id"] == "skill_auto_approval_agent"
    assert settings["updated_by"] == "admin@example.test"
    assert isinstance(settings["updated_at"], str)
