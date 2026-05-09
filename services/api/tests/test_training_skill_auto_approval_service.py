from app.services.training_skill_auto_approval_service import TrainingSkillApprovalAgent, TrainingSkillAutoApprovalSettingsStore


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


def test_training_skill_approval_agent_removes_dose_and_drug_variants() -> None:
    candidate = {
        "candidate_id": "skill_candidate_probe",
        "trigger_item_id": "training_pattern_probe",
        "trigger_item_ids": ["rs_exclude"],
        "case_ids": ["appendicitis_001"],
        "skill_type": "reasoning_bridge",
        "stage_scope": ["case_intro", "diagnosis_submission"],
        "applies_when": {
            "case_ids": ["appendicitis_001"],
            "stage_scope": ["case_intro", "diagnosis_submission"],
            "trigger_item_ids": ["rs_exclude"],
            "current_missing_evidence": ["rs_exclude"],
            "min_support_count": 2,
        },
        "effect_status": "insufficient_samples",
        "title": "剂量表达测试",
        "description": "提醒学生不要直接写阿莫西林500mg q8h。",
        "suggested_strategy": "如果学生漏项，提示阿莫西林500mg q8h并说明下一步处理。",
        "source_report_count": 2,
        "support_count": 2,
        "related_recommendations": [],
        "teaching_action_plan": [],
        "prohibited_content_policy": {},
        "success_metrics": [],
    }

    reviewed_candidate = TrainingSkillApprovalAgent().review_candidate(candidate)
    reviewed_text = " ".join(
        [
            reviewed_candidate["title"],
            reviewed_candidate["description"],
            reviewed_candidate["suggested_strategy"],
            str(reviewed_candidate["teaching_action_plan"]),
        ]
    )

    assert "阿莫西林" not in reviewed_text
    assert "500mg" not in reviewed_text
    assert "q8h" not in reviewed_text
    assert "剂量" not in reviewed_text
    assert reviewed_candidate["candidate_id"] == candidate["candidate_id"]
    assert reviewed_candidate["trigger_item_ids"] == candidate["trigger_item_ids"]
