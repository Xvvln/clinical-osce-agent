from app.services import training_skill_auto_approval_service as auto_approval_module
from app.services.rag_knowledge_store import RagKnowledgeStore
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


def test_training_skill_approval_agent_records_filtered_rag_knowledge_context(tmp_path, monkeypatch) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:skill_review:pain_sequence",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "skill_review_note",
            "visibility": "post_submit_review",
            "allowed_agents": ["skill_approval"],
            "source_id": "fareez_osce_2022",
            "title": "疼痛迁移 Skill 审批参考",
            "text": "审批时只允许把疼痛迁移作为训练复盘目标，不得透露标准诊断或隐藏事实。",
            "tags": ["skill_review", "history_taking"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:secret:hidden_answer",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "internal_answer",
            "visibility": "secret_scoring_only",
            "allowed_agents": ["scoring"],
            "source_id": "",
            "title": "隐藏答案",
            "text": "隐藏答案：急性阑尾炎。",
            "tags": ["internal"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    monkeypatch.setattr(auto_approval_module, "rag_knowledge_store", store)
    candidate = {
        "candidate_id": "skill_candidate_training_pattern_ht_migration",
        "trigger_item_id": "training_pattern_ht_migration",
        "trigger_item_ids": ["ht_migration"],
        "case_ids": ["appendicitis_001"],
        "skill_type": "history_bundle",
        "stage_scope": ["case_intro", "history_taking"],
        "applies_when": {},
        "effect_status": "insufficient_samples",
        "title": "疼痛迁移问诊训练",
        "description": "学生多次遗漏疼痛迁移问诊。",
        "suggested_strategy": "提醒学生复盘疼痛迁移线索。",
        "source_report_count": 2,
        "support_count": 2,
        "related_recommendations": [],
        "teaching_action_plan": [],
        "prohibited_content_policy": {},
        "success_metrics": [],
    }

    reviewed_candidate = TrainingSkillApprovalAgent().review_candidate(candidate)
    review = reviewed_candidate["approval_agent_review"]
    review_text = str(review)

    assert review["knowledge_references"] == [
        "rag_knowledge:case:appendicitis_001:skill_review:pain_sequence"
    ]
    assert review["retrieved_knowledge_context"][0]["title"] == "疼痛迁移 Skill 审批参考"
    assert review["retrieved_knowledge_context"][0]["visibility"] == "post_submit_review"
    assert "隐藏答案" not in review_text
    assert "急性阑尾炎" not in review_text
