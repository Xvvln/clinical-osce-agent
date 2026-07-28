import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor, wait
from threading import Event

import pytest

import app.services.training_skill_store as training_skill_store_module
from app.services.training_skill_store import (
    TrainingSkillDeletedError,
    TrainingSkillOwnershipError,
    TrainingSkillSourceDeletedError,
    TrainingSkillStore,
)


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


def _without_memory_fields(skill: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in skill.items()
        if key
        not in {
            "memory_layer",
            "skill_memory_version",
            "problem_pattern",
            "router_index",
            "intervention",
            "effect_tracking",
        }
    }


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
    assert _without_memory_fields(loaded_skill) == {
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
        "student_visible_summary": "3 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001、pneumonia_001。",
        "learning_action": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "activation_summary": "适用于右下腹痛教学病例、发热咳嗽伴胸痛教学病例；训练开始时，当当前缺口命中 2 个关联训练点时触发。",
        "source_summary": "来自 3 份报告，累计支持 2 次。",
        "effect_status_label": "样本不足",
        "scope_label": "全局 Skill",
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
    assert loaded_skill["memory_layer"] == "procedural_teaching_skill"
    assert loaded_skill["skill_memory_version"] == "skill_memory_v1"
    assert loaded_skill["problem_pattern"] == {
        "pattern_id": "reasoning_core",
        "pattern_type": "reasoning_bridge",
        "clinical_reasoning_gap": "证据链整合与推理表达不足",
        "trigger_item_ids": ["reasoning_core", "rs_exclude"],
        "reasoning_pattern_ids": [],
        "reasoning_pattern_labels": [],
        "case_ids": ["appendicitis_001", "pneumonia_001"],
        "source_report_count": 3,
        "support_count": 2,
    }
    assert "suggested_strategy" not in loaded_skill["router_index"]
    assert loaded_skill["intervention"]["coach_strategy"] == candidate["suggested_strategy"]
    assert loaded_skill["intervention"]["focus_points"] == [
        "推理链覆盖感染症状、体征和影像证据",
        "推理表达覆盖关键排除依据",
    ]
    assert loaded_skill["intervention"]["hint_ladder"] == [
        "先让学生复盘已获得的症状、体征和检查线索，标出推理链覆盖感染症状、体征和影像证据、推理表达覆盖关键排除依据仍缺哪一环。",
        "再引导学生把每条证据写成“支持什么、排除什么、还缺什么”的链条，而不是只罗列事实。",
        "最后让学生用新增证据重新组织诊断假设和鉴别诊断，但不直接给出标准答案。",
    ]
    assert loaded_skill["effect_tracking"]["summary"] == "样本不足，仅记录应用痕迹，不宣称能力提升。"


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


def test_training_skill_store_hydrates_legacy_null_metadata_without_false_trigger(tmp_path) -> None:
    database_path = tmp_path / "training_skills.sqlite3"
    store = TrainingSkillStore(database_path)
    store._initialize()
    legacy_skill = {
        "skill_id": "skill_training_pattern_dxd_crohn_dxd_ectopic_plus_2",
        "source_candidate_id": "skill_candidate_training_pattern_dxd_crohn_dxd_ectopic_plus_2",
        "trigger_item_id": "training_pattern_dxd_crohn_dxd_ectopic_plus_2",
        "trigger_item_ids": None,
        "case_ids": None,
        "stage_scope": None,
        "applies_when": None,
        "teaching_action_plan": None,
        "related_recommendations": None,
        "title": "旧版急腹症训练 Skill",
        "description": "旧版库中缺少数组型元数据。",
        "suggested_strategy": "提醒学生完整复盘证据链，但不透露标准答案。",
        "status": "enabled",
        "source_report_count": 2,
        "support_count": 2,
    }
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO training_skills (skill_id, skill_json) VALUES (?, ?)",
            (legacy_skill["skill_id"], json.dumps(legacy_skill, ensure_ascii=False)),
        )

    [loaded_skill] = TrainingSkillStore(database_path).list_enabled_skills()

    assert loaded_skill["trigger_item_ids"] == []
    assert loaded_skill["case_ids"] == []
    assert loaded_skill["stage_scope"] == ["case_intro"]
    assert loaded_skill["applies_when"]["trigger_item_ids"] == []
    assert loaded_skill["teaching_action_plan"] == _expected_action_plan(
        ["case_intro"],
        [],
        "提醒学生完整复盘证据链，但不透露标准答案。",
    )
    assert "当训练状态匹配该 Skill 条件时触发" in loaded_skill["activation_summary"]


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

    assert [_without_memory_fields(skill) for skill in skills] == [
        {
            "skill_id": "skill_reasoning_core",
            "source_candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "trigger_item_ids": ["reasoning_core"],
            "case_ids": [],
            "skill_type": "reasoning_bridge",
            "stage_scope": ["case_intro"],
            "effect_status": "insufficient_samples",
            "applies_when": {
                "case_ids": [],
                "stage_scope": ["case_intro"],
                "trigger_item_ids": ["reasoning_core"],
                "current_missing_evidence": [],
                "min_support_count": 2,
            },
            "title": "临床推理链纠偏提示",
            "description": "推理链反复遗漏。",
            "suggested_strategy": "提醒学生组织证据链，但不透露标准诊断或隐藏事实。",
            "student_visible_summary": "推理链反复遗漏。",
            "learning_action": "提醒学生组织证据链，但不透露标准诊断或隐藏事实。",
            "activation_summary": "适用于所有当前开放病例；训练开始时，当当前缺口命中 1 个关联训练点时触发。",
            "source_summary": "来自 3 份报告，累计支持 2 次。",
            "effect_status_label": "样本不足",
            "scope_label": "全局 Skill",
            "teaching_action_plan": _expected_action_plan(
                ["case_intro"],
                ["reasoning_core"],
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
            "trigger_item_ids": ["ht_location"],
            "case_ids": [],
            "skill_type": "history_bundle",
            "stage_scope": ["case_intro"],
            "effect_status": "insufficient_samples",
            "applies_when": {
                "case_ids": [],
                "stage_scope": ["case_intro"],
                "trigger_item_ids": ["ht_location"],
                "current_missing_evidence": [],
                "min_support_count": 2,
            },
            "title": "疼痛部位追问提示",
            "description": "问诊部位反复遗漏。",
            "suggested_strategy": "提醒学生补充疼痛部位与转移问题。",
            "student_visible_summary": "问诊部位反复遗漏。",
            "learning_action": "提醒学生补充疼痛部位与转移问题。",
            "activation_summary": "适用于所有当前开放病例；训练开始时，当当前缺口命中 1 个关联训练点时触发。",
            "source_summary": "来自 4 份报告，累计支持 2 次。",
            "effect_status_label": "样本不足",
            "scope_label": "全局 Skill",
            "teaching_action_plan": _expected_action_plan(
                ["case_intro"],
                ["ht_location"],
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
    assert all(skill["memory_layer"] == "procedural_teaching_skill" for skill in skills)
    assert skills[0]["router_index"]["risk"] == "仅用于教学提示和复盘，不得透露标准诊断、隐藏事实或真实临床处理细节。"
    generated_memory_text = str(skills[0]["router_index"]) + str(skills[0]["intervention"])
    assert "治疗方案" not in generated_memory_text
    assert "用药剂量" not in generated_memory_text
    assert "手术方案" not in generated_memory_text


def test_global_skill_source_cleanup_marks_stale_disables_and_fences_late_enable(
    tmp_path,
) -> None:
    database_path = tmp_path / "training_skills.sqlite3"
    store = TrainingSkillStore(database_path)
    source_session_id = "source-session"
    source_report_id = f"{source_session_id}_report"

    def candidate(
        candidate_id: str,
        trigger_item_id: str,
        source_session_ids: list[str],
    ) -> dict[str, object]:
        return {
            "candidate_id": candidate_id,
            "trigger_item_id": trigger_item_id,
            "trigger_item_ids": [trigger_item_id],
            "case_ids": ["appendicitis_001"],
            "stage_scope": ["case_intro"],
            "title": candidate_id,
            "description": "derived skill",
            "suggested_strategy": "review evidence",
            "scope": "global",
            "source_session_ids": source_session_ids,
            "source_report_ids": [
                f"{session_id}_report" for session_id in source_session_ids
            ],
            "source_turn_patterns": [
                {
                    "pattern_id": trigger_item_id,
                    "count": len(source_session_ids),
                    "session_ids": source_session_ids,
                    "source_report_ids": [
                        f"{session_id}_report"
                        for session_id in source_session_ids
                    ],
                    "source_report_count": len(source_session_ids),
                }
            ],
            "source_report_count": len(source_session_ids),
            "support_count": len(source_session_ids),
            "review": {
                "candidate_id": candidate_id,
                "status": "approved",
                "regression_passed": True,
            },
        }

    affected_candidate = candidate(
        "candidate-affected",
        "affected-trigger",
        [source_session_id, "kept-session"],
    )
    unrelated_candidate = candidate(
        "candidate-unrelated",
        "unrelated-trigger",
        ["unrelated-session"],
    )
    assert store.enable_candidate(affected_candidate)
    assert store.enable_candidate(unrelated_candidate)

    cleanup = store.remove_global_source_contributions(
        source_session_id=source_session_id,
        owner_student_id="student-a",
        source_report_id=source_report_id,
        affected_candidate_ids=["candidate-affected"],
    )

    assert cleanup.affected_skill_ids == ("skill_affected-trigger",)
    stale = store.get_skill("skill_affected-trigger")
    assert stale is not None
    assert stale["status"] == "stale_requires_review"
    assert stale["source_session_ids"] == ["kept-session"]
    assert stale["source_report_ids"] == ["kept-session_report"]
    assert source_session_id not in str(stale)
    assert source_report_id not in str(stale)
    assert stale["support_count"] == 0
    assert stale["title"] == "来源证据已变化的训练 Skill"
    assert "derived skill" not in str(stale)
    assert [
        skill["skill_id"] for skill in store.list_enabled_skills()
    ] == ["skill_unrelated-trigger"]
    assert TrainingSkillStore(database_path).remove_global_source_contributions(
        source_session_id=source_session_id,
        owner_student_id="student-a",
        source_report_id=source_report_id,
        affected_candidate_ids=["candidate-affected"],
    ) == cleanup

    with pytest.raises(TrainingSkillSourceDeletedError):
        store.enable_candidate(affected_candidate)

    regenerated = {
        **affected_candidate,
        "source_provenance_schema_version": "training_candidate_sources.v1",
        "source_session_ids": ["kept-session"],
        "source_report_ids": ["kept-session_report"],
        "source_turn_patterns": [],
        "source_report_count": 1,
        "support_count": 1,
    }
    assert store.enable_candidate(regenerated)
    assert store.get_skill("skill_affected-trigger")["status"] == "enabled"

    with pytest.raises(TrainingSkillOwnershipError):
        store.remove_global_source_contributions(
            source_session_id=source_session_id,
            owner_student_id="student-b",
            source_report_id=source_report_id,
            affected_candidate_ids=["candidate-affected"],
        )


def test_skill_hydration_cannot_overwrite_concurrent_source_cleanup(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "training_skills.sqlite3"
    store = TrainingSkillStore(database_path)
    source_session_id = "source-race"
    candidate = {
        "candidate_id": "candidate-race",
        "trigger_item_id": "race-trigger",
        "trigger_item_ids": ["race-trigger"],
        "case_ids": ["appendicitis_001"],
        "stage_scope": ["case_intro"],
        "title": "race-derived title",
        "description": "race-derived description",
        "suggested_strategy": "race-derived strategy",
        "scope": "global",
        "source_provenance_schema_version": "training_candidate_sources.v1",
        "source_session_ids": [source_session_id],
        "source_report_ids": [f"{source_session_id}_report"],
        "source_report_count": 1,
        "support_count": 1,
        "review": {
            "candidate_id": "candidate-race",
            "status": "approved",
            "regression_passed": True,
        },
    }
    assert store.enable_candidate(candidate)

    hydrate_entered = Event()
    allow_hydrate = Event()
    original_hydrate = (
        training_skill_store_module._hydrate_skill_student_metadata
    )

    def paused_hydrate(skill):
        hydrate_entered.set()
        assert allow_hydrate.wait(timeout=5)
        return original_hydrate(skill)

    monkeypatch.setattr(
        training_skill_store_module,
        "_hydrate_skill_student_metadata",
        paused_hydrate,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        read_future = executor.submit(store.get_skill, "skill_race-trigger")
        assert hydrate_entered.wait(timeout=5)
        cleanup_future = executor.submit(
            store.remove_global_source_contributions,
            source_session_id=source_session_id,
            owner_student_id="student-a",
            source_report_id=f"{source_session_id}_report",
            affected_candidate_ids=["candidate-race"],
        )
        _done, pending = wait([cleanup_future], timeout=0.05)
        assert cleanup_future in pending
        allow_hydrate.set()
        assert read_future.result(timeout=5) is not None
        assert cleanup_future.result(timeout=5).affected_skill_ids == (
            "skill_race-trigger",
        )

    stale = TrainingSkillStore(database_path).get_skill(
        "skill_race-trigger"
    )
    assert stale is not None
    assert stale["status"] == "stale_requires_review"
    assert source_session_id not in str(stale)
    assert "race-derived" not in str(stale)


def test_personal_skill_delete_is_exact_idempotent_and_blocks_late_enable(tmp_path) -> None:
    database_path = tmp_path / "training_skills.sqlite3"
    store = TrainingSkillStore(database_path)
    target = _personal_skill_candidate(
        session_id="session_delete",
        owner_student_id="student_a",
    )
    other = _personal_skill_candidate(
        session_id="session_keep",
        owner_student_id="student_a",
    )
    global_candidate = {
        **_personal_skill_candidate(
            session_id="global_keep",
            owner_student_id="student_a",
        ),
        "candidate_id": "skill_candidate_global_keep",
        "trigger_item_id": "global_keep",
        "scope": "global",
        "owner_student_id": "",
        "source_session_id": "",
    }
    assert store.enable_candidate(target)
    assert store.enable_candidate(other)
    assert store.enable_candidate(global_candidate)

    with pytest.raises(TrainingSkillOwnershipError):
        store.delete_personal_skill(
            skill_id="skill_personal_session_delete",
            owner_student_id="student_b",
            source_session_id="session_delete",
            source_candidate_id="personal_skill_candidate_session_delete",
        )
    assert store.get_skill("skill_personal_session_delete") is not None

    assert store.delete_personal_skill(
        skill_id="skill_personal_session_delete",
        owner_student_id="student_a",
        source_session_id="session_delete",
        source_candidate_id="personal_skill_candidate_session_delete",
    ) is True
    assert TrainingSkillStore(database_path).delete_personal_skill(
        skill_id="skill_personal_session_delete",
        owner_student_id="student_a",
        source_session_id="session_delete",
        source_candidate_id="personal_skill_candidate_session_delete",
    ) is False
    assert store.get_skill("skill_personal_session_delete") is None
    assert store.get_skill("skill_personal_session_keep") is not None
    assert store.get_skill("skill_global_keep") is not None

    with pytest.raises(TrainingSkillDeletedError):
        store.enable_candidate(target)

    assert store.delete_personal_skill(
        skill_id="skill_personal_session_missing",
        owner_student_id="student_a",
        source_session_id="session_missing",
        source_candidate_id="personal_skill_candidate_session_missing",
    ) is False
    with pytest.raises(TrainingSkillDeletedError):
        store.enable_candidate(
            _personal_skill_candidate(
                session_id="session_missing",
                owner_student_id="student_a",
            )
        )


def test_personal_skill_delete_migrates_legacy_schema_and_never_deletes_global_skill(tmp_path) -> None:
    database_path = tmp_path / "training_skills.sqlite3"
    session_id = "session_global_conflict"
    skill_id = f"skill_personal_{session_id}"
    global_skill = {
        "skill_id": skill_id,
        "source_candidate_id": f"personal_skill_candidate_{session_id}",
        "scope": "global",
        "owner_student_id": "student_a",
        "source_session_id": session_id,
    }
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE training_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id TEXT NOT NULL UNIQUE,
                skill_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO training_skills (skill_id, skill_json)
            VALUES (?, ?)
            """,
            (skill_id, json.dumps(global_skill, ensure_ascii=False)),
        )

    store = TrainingSkillStore(database_path)
    with pytest.raises(TrainingSkillOwnershipError):
        store.delete_personal_skill(
            skill_id=skill_id,
            owner_student_id="student_a",
            source_session_id=session_id,
            source_candidate_id=f"personal_skill_candidate_{session_id}",
        )

    with sqlite3.connect(database_path) as connection:
        preserved = connection.execute(
            "SELECT skill_id FROM training_skills WHERE skill_id = ?",
            (skill_id,),
        ).fetchone()
        tombstone_table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'training_skill_tombstones'
            """
        ).fetchone()
        tombstone_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM training_skill_tombstones
            WHERE skill_id = ?
            """,
            (skill_id,),
        ).fetchone()[0]
    assert preserved == (skill_id,)
    assert tombstone_table == ("training_skill_tombstones",)
    assert tombstone_count == 0


def _personal_skill_candidate(
    *,
    session_id: str,
    owner_student_id: str,
) -> dict[str, object]:
    candidate_id = f"personal_skill_candidate_{session_id}"
    return {
        "candidate_id": candidate_id,
        "trigger_item_id": f"personal_{session_id}",
        "trigger_item_ids": ["reasoning_core"],
        "case_ids": ["appendicitis_001"],
        "stage_scope": ["case_intro"],
        "title": "个人复盘训练 Skill",
        "description": "根据本次训练生成的个人复盘建议。",
        "suggested_strategy": "提醒学生复盘证据链，不透露标准答案。",
        "scope": "personal",
        "owner_student_id": owner_student_id,
        "source_session_id": session_id,
        "source_session_ids": [session_id],
        "source_report_count": 1,
        "support_count": 1,
        "related_recommendations": [],
        "review": {
            "candidate_id": candidate_id,
            "status": "approved",
            "regression_passed": True,
        },
    }
