from __future__ import annotations

from app.services.training_skill_orchestrator_service import build_active_skill_context


def test_skill_orchestrator_filters_case_student_stage_missing_items_and_context_safety() -> None:
    context = build_active_skill_context(
        [
            {
                "skill_id": "skill_match",
                "title": "腹痛问诊链训练",
                "suggested_strategy": "先追问起病、部位、性质和迁移过程。",
                "case_ids": ["appendicitis_001"],
                "scope": "personal",
                "owner_student_id": "student-a",
                "stage_scope": ["case_intro"],
                "trigger_item_ids": ["ht_migration"],
                "support_count": 6,
            },
            {
                "skill_id": "skill_other_case",
                "title": "胸痛问诊训练",
                "suggested_strategy": "围绕胸痛诱因追问。",
                "case_ids": ["acs_001"],
                "stage_scope": ["case_intro"],
                "trigger_item_ids": ["ht_onset"],
            },
            {
                "skill_id": "skill_other_student",
                "title": "其他学生专属训练",
                "suggested_strategy": "这是另一个学生的个人策略。",
                "case_ids": ["appendicitis_001"],
                "scope": "personal",
                "owner_student_id": "student-b",
                "stage_scope": ["case_intro"],
                "trigger_item_ids": ["ht_migration"],
            },
            {
                "skill_id": "skill_wrong_stage",
                "title": "提交前证据整理",
                "suggested_strategy": "提交前整理支持与排除证据。",
                "case_ids": ["appendicitis_001"],
                "stage_scope": ["feedback"],
                "trigger_item_ids": ["ht_migration"],
            },
            {
                "skill_id": "skill_context_unsafe",
                "title": "妊娠相关鉴别训练",
                "suggested_strategy": "追问月经和妊娠相关信息。",
                "case_ids": ["appendicitis_001"],
                "stage_scope": ["case_intro"],
                "trigger_item_ids": ["ht_migration"],
            },
        ],
        case_id="appendicitis_001",
        student_id="student-a",
        stage="case_intro",
        rubric_item_ids=["ht_migration", "pe_tenderness"],
        current_missing_evidence=["ht_migration"],
        patient_profile={"gender": "男"},
    )

    assert [skill["skill_id"] for skill in context["selected_skills"]] == ["skill_match"]
    assert {item["skill_id"]: item["reason"] for item in context["skipped_reasons"]} == {
        "skill_other_case": "case_mismatch",
        "skill_other_student": "student_mismatch",
        "skill_wrong_stage": "stage_mismatch",
        "skill_context_unsafe": "context_safety_mismatch",
    }


def test_skill_orchestrator_ranks_profile_matches_before_generic_skills_and_limits() -> None:
    context = build_active_skill_context(
        [
            {
                "skill_id": "skill_generic_high_support",
                "title": "通用问诊训练",
                "suggested_strategy": "按常规顺序补齐问诊。",
                "case_ids": ["appendicitis_001"],
                "stage_scope": ["case_intro"],
                "trigger_item_ids": ["ht_onset"],
                "support_count": 20,
            },
            {
                "skill_id": "skill_recent_profile_gap",
                "title": "腹痛迁移追问训练",
                "suggested_strategy": "围绕疼痛迁移和加重过程追问。",
                "case_ids": ["appendicitis_001"],
                "stage_scope": ["case_intro"],
                "trigger_item_ids": ["ht_migration"],
                "support_count": 3,
            },
            {
                "skill_id": "skill_second_profile_gap",
                "title": "伴随症状追问训练",
                "suggested_strategy": "补齐恶心、呕吐、发热和腹泻等伴随症状。",
                "case_ids": ["appendicitis_001"],
                "stage_scope": ["case_intro"],
                "trigger_item_ids": ["ht_associated_symptoms"],
                "support_count": 2,
            },
        ],
        case_id="appendicitis_001",
        student_id="student-a",
        stage="case_intro",
        rubric_item_ids=["ht_onset", "ht_migration", "ht_associated_symptoms"],
        current_missing_evidence=["ht_migration", "ht_associated_symptoms"],
        student_profile={
            "recent_error_item_ids": ["ht_migration", "ht_associated_symptoms"],
            "skill_states": {
                "skill_generic_high_support": {"state": "active", "priority": 1},
                "skill_recent_profile_gap": {"state": "active", "priority": 8},
                "skill_second_profile_gap": {"state": "active", "priority": 6},
            },
        },
        limit=2,
    )

    assert [skill["skill_id"] for skill in context["selected_skills"]] == [
        "skill_recent_profile_gap",
        "skill_second_profile_gap",
    ]
    assert {item["skill_id"]: item["reason"] for item in context["skipped_reasons"]}[
        "skill_generic_high_support"
    ] == "not_selected_top_k"


def test_skill_orchestrator_skips_legacy_skill_without_real_trigger_items() -> None:
    context = build_active_skill_context(
        [
            {
                "skill_id": "skill_legacy_pattern_only",
                "title": "旧版训练模式 Skill",
                "suggested_strategy": "这是旧版训练模式聚合 Skill。",
                "case_ids": ["appendicitis_001"],
                "stage_scope": ["case_intro"],
                "trigger_item_id": "training_pattern_dxd_crohn_dxd_ectopic_plus_2",
                "trigger_item_ids": None,
                "support_count": 20,
            },
            {
                "skill_id": "skill_match",
                "title": "疼痛迁移追问训练",
                "suggested_strategy": "先围绕疼痛迁移过程追问。",
                "case_ids": ["appendicitis_001"],
                "stage_scope": ["case_intro"],
                "trigger_item_ids": ["ht_migration"],
                "support_count": 2,
            },
        ],
        case_id="appendicitis_001",
        student_id="student-a",
        stage="case_intro",
        rubric_item_ids=["ht_migration"],
        current_missing_evidence=["ht_migration"],
        patient_profile={"gender": "男"},
        limit=2,
    )

    assert [skill["skill_id"] for skill in context["selected_skills"]] == ["skill_match"]
    assert {item["skill_id"]: item["reason"] for item in context["skipped_reasons"]}[
        "skill_legacy_pattern_only"
    ] == "trigger_items_missing"


def test_skill_orchestrator_returns_compact_index_without_full_strategy_text() -> None:
    strategy = "这是一段完整教学策略，应该只在 selected_skills 中展开，而不是进入 Skill Index。"
    context = build_active_skill_context(
        [
            {
                "skill_id": "skill_index_only",
                "title": "腹痛问诊顺序训练",
                "suggested_strategy": strategy,
                "case_ids": ["appendicitis_001"],
                "stage_scope": ["case_intro"],
                "trigger_item_ids": ["ht_onset"],
                "support_count": 1,
            }
        ],
        case_id="appendicitis_001",
        student_id="student-a",
        stage="case_intro",
        rubric_item_ids=["ht_onset"],
        current_missing_evidence=["ht_onset"],
    )

    assert context["skill_index"] == [
        {
            "skill_id": "skill_index_only",
            "title": "腹痛问诊顺序训练",
            "scope": "global",
            "stage_scope": ["case_intro"],
            "trigger_item_ids": ["ht_onset"],
            "priority": 4,
            "why_candidate": "当前缺口命中 ht_onset",
        }
    ]
    assert context["skill_index"][0].get("suggested_strategy") is None
    assert context["selected_skills"][0]["suggested_strategy"] == strategy
