from app.services.training_skill_store import TrainingSkillStore


def test_training_skill_store_enables_approved_candidate_across_instances(tmp_path) -> None:
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
        "title": "临床推理链纠偏提示",
        "description": "3 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001、pneumonia_001。",
        "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "status": "enabled",
        "source_report_count": 3,
        "support_count": 2,
    }


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
            "title": "临床推理链纠偏提示",
            "description": "推理链反复遗漏。",
            "suggested_strategy": "提醒学生组织证据链，但不透露标准诊断或隐藏事实。",
            "status": "enabled",
            "source_report_count": 3,
            "support_count": 2,
        },
        {
            "skill_id": "skill_ht_location",
            "source_candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "title": "疼痛部位追问提示",
            "description": "问诊部位反复遗漏。",
            "suggested_strategy": "提醒学生补充疼痛部位与转移问题。",
            "status": "enabled",
            "source_report_count": 4,
            "support_count": 2,
        },
    ]
