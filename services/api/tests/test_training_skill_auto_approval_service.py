from app.services import training_skill_auto_approval_service as auto_approval_module
from app.services import agent_rag_context_service as agent_rag_context_module
from app.services.rag_knowledge_store import RagKnowledgeStore
from app.services.retrieval_index import RetrievalDocument
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
    approval_review = reviewed_candidate["approval_agent_review"]
    assert approval_review["decision"] == "prepared_for_auto_apply"
    assert approval_review["quality_review"]["passed"] is True
    assert approval_review["role_policy"]["passed"] is True
    assert approval_review["role_policy"]["prohibited_content_policy_source"] == "platform_default"
    assert approval_review["role_policy"]["success_metrics_source"] == "platform_default"


def test_training_skill_approval_agent_blocks_explicitly_weakened_role_policy() -> None:
    candidate = {
        "candidate_id": "skill_candidate_weakened_policy",
        "trigger_item_id": "training_pattern_weakened_policy",
        "trigger_item_ids": ["ht_migration"],
        "case_ids": ["appendicitis_001"],
        "skill_type": "history_bundle",
        "stage_scope": ["history_taking"],
        "applies_when": {},
        "effect_status": "insufficient_samples",
        "title": "疼痛迁移问诊训练",
        "description": "学生需要建立疼痛演变时间线。",
        "suggested_strategy": "先追问起病部位和迁移过程。",
        "source_report_count": 2,
        "support_count": 2,
        "related_recommendations": [],
        "teaching_action_plan": [],
        "prohibited_content_policy": {
            "forbid_main_diagnosis": True,
            "forbid_hidden_facts": False,
            "forbid_test_results": True,
            "forbid_treatment_plan": True,
            "forbid_dose": True,
            "allowed_scope": "teaching_strategy_only",
        },
        "success_metrics": ["target_rubric_item_recovery_rate"],
    }

    reviewed_candidate = TrainingSkillApprovalAgent().review_candidate(candidate)
    approval_review = reviewed_candidate["approval_agent_review"]

    assert approval_review["decision"] == "blocked"
    assert approval_review["quality_review"]["passed"] is False
    assert approval_review["quality_review"]["failed_checks"] == [
        "prohibited_content_policy_complete",
        "success_metrics_declared",
    ]
    assert approval_review["role_policy"]["passed"] is False


def test_training_skill_approval_agent_rewrites_protected_diagnosis_without_answer_placeholder() -> None:
    candidate = {
        "candidate_id": "skill_candidate_answer_probe",
        "trigger_item_id": "training_pattern_answer_probe",
        "trigger_item_ids": ["reasoning_core"],
        "case_ids": ["appendicitis_001"],
        "skill_type": "reasoning_bridge",
        "stage_scope": ["diagnosis_submission"],
        "applies_when": {},
        "effect_status": "insufficient_samples",
        "title": "急性阑尾炎证据链训练",
        "description": "学生需要围绕急性阑尾炎建立证据链。",
        "suggested_strategy": "如果假设是本病例标准答案或急性阑尾炎，请补充支持与排除证据。",
        "source_report_count": 1,
        "support_count": 1,
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

    assert "急性阑尾炎" not in reviewed_text
    assert "本病例标准答案" not in reviewed_text
    assert "当前病例诊断假设" in reviewed_text


def test_training_skill_approval_agent_derives_and_removes_hidden_case_facts() -> None:
    candidate = {
        "candidate_id": "skill_candidate_hidden_fact_probe",
        "trigger_item_id": "training_pattern_hidden_fact_probe",
        "trigger_item_ids": ["ht_migration"],
        "case_ids": ["appendicitis_001"],
        "skill_type": "history_bundle",
        "stage_scope": ["history_taking"],
        "applies_when": {},
        "effect_status": "insufficient_samples",
        "title": "腹痛演变问诊训练",
        "description": "候选内容错误写入：开始在上腹部，大约 8 小时前转移并固定到右下腹。",
        "suggested_strategy": "请让学生自主重建疼痛时间线。",
        "source_report_count": 2,
        "support_count": 2,
        "related_recommendations": [],
        "teaching_action_plan": [],
        "prohibited_content_policy": {},
        "success_metrics": [],
    }

    reviewed_candidate = TrainingSkillApprovalAgent().review_candidate(candidate)

    assert "开始在上腹部，大约 8 小时前转移并固定到右下腹。" not in str(reviewed_candidate)
    quality_review = reviewed_candidate["approval_agent_review"]["quality_review"]
    assert quality_review["passed"] is True
    assert next(
        check for check in quality_review["checks"] if check["check_id"] == "case_facts_removed"
    )["passed"] is True


def test_training_skill_approval_agent_preserves_and_blocks_unsafe_protected_fields() -> None:
    candidate = {
        "candidate_id": "skill_candidate_protected_field_probe",
        "trigger_item_id": "training_pattern_protected_field_probe",
        "trigger_item_ids": ["reasoning_core"],
        "case_ids": ["appendicitis_001"],
        "skill_type": "reasoning_bridge",
        "stage_scope": ["diagnosis_submission"],
        "applies_when": {
            "case_ids": ["appendicitis_001"],
            "stage_scope": ["diagnosis_submission"],
            "trigger_item_ids": ["reasoning_core"],
            "current_missing_evidence": ["急性阑尾炎"],
            "min_support_count": 2,
        },
        "effect_status": "insufficient_samples",
        "title": "证据链训练",
        "description": "训练学生表达支持与排除证据。",
        "suggested_strategy": "请学生按证据类别完成复盘。",
        "source_report_count": 2,
        "support_count": 2,
        "related_recommendations": [],
        "teaching_action_plan": [],
        "prohibited_content_policy": {},
        "success_metrics": [],
    }
    protected_snapshot = {
        field: candidate.get(field)
        for field in auto_approval_module.PROTECTED_CANDIDATE_FIELDS
        if field in candidate
    }

    reviewed_candidate = TrainingSkillApprovalAgent().review_candidate(candidate)

    assert {
        field: reviewed_candidate.get(field)
        for field in auto_approval_module.PROTECTED_CANDIDATE_FIELDS
        if field in candidate
    } == protected_snapshot
    approval_review = reviewed_candidate["approval_agent_review"]
    assert approval_review["decision"] == "blocked"
    assert "protected_fields_content_safe" in approval_review["quality_review"]["failed_checks"]
    assert not {
        change["field"] for change in approval_review["changed_fields"]
    }.intersection(auto_approval_module.PROTECTED_CANDIDATE_FIELDS)


def test_training_skill_approval_agent_sanitizes_memory_and_analysis_fields() -> None:
    candidate = {
        "candidate_id": "skill_candidate_memory_probe",
        "trigger_item_id": "training_pattern_memory_probe",
        "trigger_item_ids": ["reasoning_core"],
        "case_ids": ["appendicitis_001"],
        "skill_type": "reasoning_bridge",
        "stage_scope": ["history_taking", "diagnosis_submission"],
        "applies_when": {},
        "effect_status": "insufficient_samples",
        "title": "证据链训练",
        "description": "围绕假设验证训练。",
        "suggested_strategy": "不要提前锁定急性阑尾炎。",
        "source_report_count": 1,
        "support_count": 1,
        "reasoning_pattern_ids": ["premature_closure"],
        "reasoning_pattern_labels": ["学生过早锁定急性阑尾炎。"],
        "teacher_analysis_context": {
            "clinical_thinking_profile": {
                "hypothesis_management": "学生直接围绕急性阑尾炎寻找阳性证据。",
            }
        },
        "problem_pattern": {
            "summary": "急性阑尾炎单向证实。",
            "reasoning_pattern_labels": ["急性阑尾炎证实偏差"],
        },
        "router_index": {
            "summary": "急性阑尾炎相关训练。",
        },
        "teaching_action_plan": [],
        "prohibited_content_policy": {},
        "success_metrics": [],
    }

    reviewed_candidate = TrainingSkillApprovalAgent().review_candidate(
        candidate,
        protected_terms=["急性阑尾炎"],
    )
    reviewed_text = str(reviewed_candidate)

    assert "急性阑尾炎" not in reviewed_text
    assert "本病例标准答案" not in reviewed_text
    assert "当前病例诊断假设" in reviewed_text


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
    monkeypatch.setattr(
        agent_rag_context_module,
        "search_retrieval_documents",
        lambda query, limit, *, allowed_references=None: [
            RetrievalDocument(
                reference="rag_knowledge:case:appendicitis_001:skill_review:pain_sequence",
                source_type="rag_knowledge",
                title="vector hit",
                snippet="vector hit",
                score=0.99,
            )
        ],
        raising=False,
    )
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
