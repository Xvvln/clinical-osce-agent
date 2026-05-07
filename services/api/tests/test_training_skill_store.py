from app.services.training_skill_store import TrainingSkillStore


def _expected_action_plan(stage_scope: list[str], trigger_item_ids: list[str], suggested_strategy: str) -> list[dict[str, object]]:
    return [
        {
            "action_type": "hint_ladder",
            "level": 1,
            "stage_scope": stage_scope,
            "trigger_item_ids": trigger_item_ids,
            "message_template": suggested_strategy,
        },
        {
            "action_type": "reflection_prompt",
            "level": 1,
            "stage_scope": ["diagnosis_submission"],
            "trigger_item_ids": trigger_item_ids,
            "message_template": "训练结束后，请对照本轮反复漏掉的评分项复盘证据链，不补写标准答案或隐藏事实。",
        },
    ]


def _expected_policy() -> dict[str, object]:
    return {
        "forbid_main_diagnosis": True,
        "forbid_hidden_facts": True,
        "forbid_test_results": True,
        "forbid_treatment_plan": True,
        "forbid_dose": True,
        "allowed_scope": "teaching_strategy_only",
    }


def _expected_success_metrics() -> list[str]:
    return [
        "target_rubric_item_recovery_rate",
        "stage_completion_rate",
        "hint_after_skill_usage",
    ]


def test_training_skill_store_enables_approved_candidate_across_instances(tmp_path) -> None:
    database_path = tmp_path / "training_skills.sqlite3"
    candidate = {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "trigger_item_ids": ["reasoning_core", "rs_exclude"],
        "case_ids": ["appendicitis_001", "pneumonia_001"],
        "skill_type": "reasoning_bridge",
        "stage_scope": ["case_intro"],
        "effect_status": "insufficient_samples",
        "applies_when": {
            "case_ids": ["appendicitis_001", "pneumonia_001"],
            "stage_scope": ["case_intro"],
            "trigger_item_ids": ["reasoning_core", "rs_exclude"],
            "current_missing_evidence": [],
            "min_support_count": 2,
        },
        "title": "临床推理链纠偏提示",
        "description": "3 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001、pneumonia_001。",
        "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "source_report_count": 3,
        "support_count": 2,
        "related_recommendations": ["rubric:appendicitis_001_rubric.item.reasoning_core"],
        "review": {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "approved",
            "regression_passed": True,
            "reviewer_id": "teacher_demo",
        },
    }

    enabled = TrainingSkillStore(database_path).enable_candidate(candidate)
    loaded_skill = TrainingSkillStore(database_path).get_skill("skill_reasoning_core")

    assert enabled is True
    assert loaded_skill == {
        "skill_id": "skill_reasoning_core",
        "source_candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "trigger_item_ids": ["reasoning_core", "rs_exclude"],
        "case_ids": ["appendicitis_001", "pneumonia_001"],
        "skill_type": "reasoning_bridge",
        "stage_scope": ["case_intro"],
        "effect_status": "insufficient_samples",
        "applies_when": {
            "case_ids": ["appendicitis_001", "pneumonia_001"],
            "stage_scope": ["case_intro"],
            "trigger_item_ids": ["reasoning_core", "rs_exclude"],
            "current_missing_evidence": [],
            "min_support_count": 2,
        },
        "title": "临床推理链纠偏提示",
        "description": "3 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001、pneumonia_001。",
        "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "teaching_action_plan": _expected_action_plan(
            ["case_intro"],
            ["reasoning_core", "rs_exclude"],
            "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        ),
        "prohibited_content_policy": _expected_policy(),
        "success_metrics": _expected_success_metrics(),
        "status": "enabled",
        "source_report_count": 3,
        "support_count": 2,
        "related_recommendations": ["rubric:appendicitis_001_rubric.item.reasoning_core"],
    }


def test_training_skill_store_preserves_skill_policy_metadata(tmp_path) -> None:
    database_path = tmp_path / "training_skills.sqlite3"
    candidate = {
        "candidate_id": "skill_candidate_training_pattern_dxd_crohn_reasoning_core",
        "trigger_item_id": "training_pattern_dxd_crohn_reasoning_core",
        "trigger_item_ids": ["dxd_crohn", "reasoning_core"],
        "case_ids": ["appendicitis_001"],
        "skill_type": "differential_broadening",
        "stage_scope": ["case_intro", "diagnosis_submission"],
        "effect_status": "insufficient_samples",
        "applies_when": {
            "case_ids": ["appendicitis_001"],
            "stage_scope": ["case_intro", "diagnosis_submission"],
            "trigger_item_ids": ["dxd_crohn", "reasoning_core"],
            "current_missing_evidence": ["dxd_crohn", "reasoning_core"],
            "min_support_count": 2,
        },
        "title": "鉴别诊断拓展提示",
        "description": "多份报告中反复出现鉴别诊断与推理链漏项。",
        "suggested_strategy": "提交诊断前，提醒学生先复盘支持与排除证据，不透露标准答案。",
        "teaching_action_plan": [
            {
                "action_type": "hint_ladder",
                "level": 1,
                "stage_scope": ["case_intro", "diagnosis_submission"],
                "trigger_item_ids": ["dxd_crohn", "reasoning_core"],
                "message_template": "提交诊断前，提醒学生先复盘支持与排除证据，不透露标准答案。",
            }
        ],
        "prohibited_content_policy": {
            "forbid_main_diagnosis": True,
            "forbid_hidden_facts": True,
            "forbid_test_results": True,
            "forbid_treatment_plan": True,
            "forbid_dose": True,
            "allowed_scope": "teaching_strategy_only",
        },
        "success_metrics": ["target_rubric_item_recovery_rate"],
        "source_report_count": 3,
        "support_count": 2,
        "related_recommendations": ["rubric:appendicitis_001_rubric.item.reasoning_core"],
        "review": {"status": "approved", "regression_passed": True},
    }

    enabled = TrainingSkillStore(database_path).enable_candidate(candidate)
    loaded_skill = TrainingSkillStore(database_path).get_skill("skill_training_pattern_dxd_crohn_reasoning_core")

    assert enabled is True
    assert loaded_skill is not None
    assert loaded_skill["skill_type"] == "differential_broadening"
    assert loaded_skill["stage_scope"] == ["case_intro", "diagnosis_submission"]
    assert loaded_skill["effect_status"] == "insufficient_samples"
    assert loaded_skill["applies_when"] == {
        "case_ids": ["appendicitis_001"],
        "stage_scope": ["case_intro", "diagnosis_submission"],
        "trigger_item_ids": ["dxd_crohn", "reasoning_core"],
        "current_missing_evidence": ["dxd_crohn", "reasoning_core"],
        "min_support_count": 2,
    }
    assert loaded_skill["teaching_action_plan"] == candidate["teaching_action_plan"]
    assert loaded_skill["prohibited_content_policy"] == candidate["prohibited_content_policy"]
    assert loaded_skill["success_metrics"] == candidate["success_metrics"]


def test_training_skill_store_does_not_enable_unapproved_candidate(tmp_path) -> None:
    database_path = tmp_path / "training_skills.sqlite3"
    candidate = {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "临床推理链纠偏提示",
        "description": "3 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001、pneumonia_001。",
        "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "source_report_count": 3,
        "support_count": 2,
        "review": {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
        },
    }

    enabled = TrainingSkillStore(database_path).enable_candidate(candidate)

    assert enabled is False
    assert TrainingSkillStore(database_path).get_skill("skill_reasoning_core") is None


def test_training_skill_store_does_not_enable_case_incompatible_approved_candidate(tmp_path) -> None:
    database_path = tmp_path / "training_skills.sqlite3"
    candidate = {
        "candidate_id": "skill_candidate_training_pattern_dxd_ectopic",
        "trigger_item_id": "training_pattern_dxd_ectopic",
        "trigger_item_ids": ["dxd_ectopic", "dxd_urolith"],
        "case_ids": ["appendicitis_001"],
        "title": "急腹症鉴别诊断与全面评估逻辑训练",
        "description": "急腹症鉴别诊断反复遗漏，需补充妇科和泌尿系统排除。",
        "suggested_strategy": "面对急性腹痛患者时，请系统排除妇科、异位妊娠、泌尿科及肠道相关疾病。",
        "source_report_count": 7,
        "support_count": 7,
        "review": {"status": "approved", "regression_passed": True},
    }

    enabled = TrainingSkillStore(database_path).enable_candidate(candidate)

    assert enabled is False
    assert TrainingSkillStore(database_path).list_enabled_skills() == []


def test_training_skill_store_lists_enabled_skills_in_insert_order(tmp_path) -> None:
    database_path = tmp_path / "training_skills.sqlite3"
    store = TrainingSkillStore(database_path)
    store.enable_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "推理链反复遗漏。",
            "suggested_strategy": "提醒学生组织证据链，但不透露标准诊断或隐藏事实。",
            "source_report_count": 3,
            "support_count": 2,
            "review": {"status": "approved", "regression_passed": True},
        }
    )
    store.enable_candidate(
        {
            "candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "title": "疼痛部位追问提示",
            "description": "问诊部位反复遗漏。",
            "suggested_strategy": "提醒学生补充疼痛部位与转移问题。",
            "source_report_count": 4,
            "support_count": 2,
            "review": {"status": "approved", "regression_passed": True},
        }
    )

    skills = TrainingSkillStore(database_path).list_enabled_skills()

    assert skills == [
        {
            "skill_id": "skill_reasoning_core",
            "source_candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "trigger_item_ids": [],
            "case_ids": [],
            "skill_type": "reasoning_bridge",
            "stage_scope": ["case_intro"],
            "effect_status": "insufficient_samples",
            "applies_when": {
                "case_ids": [],
                "stage_scope": ["case_intro"],
                "trigger_item_ids": [],
                "current_missing_evidence": [],
                "min_support_count": 2,
            },
            "title": "临床推理链纠偏提示",
            "description": "推理链反复遗漏。",
            "suggested_strategy": "提醒学生组织证据链，但不透露标准诊断或隐藏事实。",
            "teaching_action_plan": _expected_action_plan(
                ["case_intro"],
                [],
                "提醒学生组织证据链，但不透露标准诊断或隐藏事实。",
            ),
            "prohibited_content_policy": _expected_policy(),
            "success_metrics": _expected_success_metrics(),
            "status": "enabled",
            "source_report_count": 3,
            "support_count": 2,
            "related_recommendations": [],
        },
        {
            "skill_id": "skill_ht_location",
            "source_candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "trigger_item_ids": [],
            "case_ids": [],
            "skill_type": "reasoning_bridge",
            "stage_scope": ["case_intro"],
            "effect_status": "insufficient_samples",
            "applies_when": {
                "case_ids": [],
                "stage_scope": ["case_intro"],
                "trigger_item_ids": [],
                "current_missing_evidence": [],
                "min_support_count": 2,
            },
            "title": "疼痛部位追问提示",
            "description": "问诊部位反复遗漏。",
            "suggested_strategy": "提醒学生补充疼痛部位与转移问题。",
            "teaching_action_plan": _expected_action_plan(
                ["case_intro"],
                [],
                "提醒学生补充疼痛部位与转移问题。",
            ),
            "prohibited_content_policy": _expected_policy(),
            "success_metrics": _expected_success_metrics(),
            "status": "enabled",
            "source_report_count": 4,
            "support_count": 2,
            "related_recommendations": [],
        },
    ]
