from __future__ import annotations

from app.services.student_profile_summary_service import build_skill_profile_summary
from app.services.student_profile_store import StudentProfileStore


def test_student_profile_store_persists_latest_profile_snapshot(tmp_path) -> None:
    store = StudentProfileStore(tmp_path / "student_profiles.sqlite3")

    store.save_profile(
        "student-a",
        {
            "recent_error_item_ids": ["ht_migration"],
            "skill_states": {"skill_ht_migration": {"state": "active", "priority": 8}},
        },
    )

    assert store.get_profile("student-a") == {
        "student_id": "student-a",
        "recent_error_item_ids": ["ht_migration"],
        "skill_states": {"skill_ht_migration": {"state": "active", "priority": 8}},
    }


def test_skill_profile_marks_unmatched_skill_as_available_not_active() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {
                "case_id": "appendicitis_001",
                "missed_items": ["ht_migration"],
            }
        ],
        enabled_skills=[
            {
                "skill_id": "skill_unmatched_history",
                "title": "既往史追问训练",
                "trigger_item_ids": ["ht_past_medical"],
                "effect_status": "insufficient_samples",
                "support_count": 5,
            }
        ],
    )

    state = summary["skill_states"]["skill_unmatched_history"]

    assert state["state"] == "available"
    assert state["state_label"] == "可用未命中"
    assert state["priority"] == 0
    assert state["selection_reason"] == "近期未命中该 Skill 训练点，仅作为备用教学策略。"


def test_profile_summary_cools_down_skill_after_recent_improvement() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {"case_id": "appendicitis_001", "missed_items": []},
            {"case_id": "appendicitis_001", "missed_items": ["ht_migration"]},
        ],
        enabled_skills=[
            {
                "skill_id": "skill_ht_migration",
                "title": "疼痛迁移追问训练",
                "trigger_item_ids": ["ht_migration"],
                "case_ids": ["appendicitis_001"],
                "effect_status": "insufficient_samples",
            }
        ],
    )

    state = summary["skill_states"]["skill_ht_migration"]
    assert state["state"] == "cooldown"
    assert state["state_label"] == "冷却观察"
    assert state["priority"] < 0
    assert state["selection_reason"] == "近期已补上该 Skill 训练点，暂进入冷却观察。"


def test_profile_summary_retires_skill_after_stable_recent_coverage() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {"case_id": "appendicitis_001", "missed_items": []},
            {"case_id": "appendicitis_001", "missed_items": []},
            {"case_id": "appendicitis_001", "missed_items": []},
            {"case_id": "appendicitis_001", "missed_items": ["ht_migration"]},
        ],
        enabled_skills=[
            {
                "skill_id": "skill_ht_migration",
                "title": "疼痛迁移追问训练",
                "trigger_item_ids": ["ht_migration"],
                "case_ids": ["appendicitis_001"],
                "effect_status": "insufficient_samples",
            }
        ],
    )

    state = summary["skill_states"]["skill_ht_migration"]
    assert state["state"] == "retired"
    assert state["state_label"] == "已退休"
    assert state["priority"] < 0
    assert state["selection_reason"] == "近期连续覆盖该 Skill 训练点，默认不再进入本轮提示。"


def test_profile_summary_reactivates_skill_when_retired_gap_reappears() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {"case_id": "appendicitis_001", "missed_items": ["ht_migration"]},
            {"case_id": "appendicitis_001", "missed_items": []},
            {"case_id": "appendicitis_001", "missed_items": []},
            {"case_id": "appendicitis_001", "missed_items": []},
            {"case_id": "appendicitis_001", "missed_items": ["ht_migration"]},
        ],
        enabled_skills=[
            {
                "skill_id": "skill_ht_migration",
                "case_ids": ["appendicitis_001"],
                "trigger_item_ids": ["ht_migration"],
                "support_count": 4,
            }
        ],
    )

    state = summary["skill_states"]["skill_ht_migration"]
    assert state["state"] == "reactivated"
    assert state["state_label"] == "重新激活"
    assert state["priority"] > 0
    assert state["selection_reason"] == "近期又出现该 Skill 相关缺口：追问疼痛部位及转移特征。"


def test_profile_summary_aggregates_reasoning_patterns_beyond_missed_items() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {
                "case_id": "appendicitis_001",
                "missed_items": ["ht_migration"],
                "clinical_reasoning_trace": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "cognitive_patterns": [
                        {
                            "pattern_id": "weak_problem_representation",
                            "label": "问题表征薄弱",
                            "category": "problem_representation",
                            "severity": "high",
                            "source_signal_ids": ["ht_migration", "ht_character"],
                        },
                        {
                            "pattern_id": "thin_differential_reasoning",
                            "label": "鉴别诊断过窄",
                            "category": "differential_reasoning",
                            "severity": "medium",
                            "source_signal_ids": ["dxd_urolith"],
                        },
                    ],
                },
            }
        ],
        enabled_skills=[
            {
                "skill_id": "skill_reasoning_trace",
                "case_ids": ["appendicitis_001"],
                "trigger_item_ids": ["ht_migration"],
                "reasoning_pattern_ids": ["weak_problem_representation"],
                "reasoning_pattern_labels": ["问题表征薄弱"],
                "support_count": 2,
            }
        ],
    )

    reasoning_summary = summary["reasoning_profile_summary"]
    assert reasoning_summary["recent_pattern_ids"][:2] == [
        "weak_problem_representation",
        "thin_differential_reasoning",
    ]
    assert reasoning_summary["current_reasoning_focus"][0]["label"] == "问题表征薄弱"
    assert reasoning_summary["profile_axes"]["problem_representation"]["count"] == 1

    state = summary["skill_states"]["skill_reasoning_trace"]
    assert state["reasoning_pattern_ids"] == ["weak_problem_representation"]
    assert state["matched_recent_reasoning_patterns"] == [
        {"pattern_id": "weak_problem_representation", "label": "问题表征薄弱"}
    ]
    assert "思维模式" in state["selection_reason"]


def test_teaching_effect_change_descriptions_are_axis_specific() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {
                "case_id": "appendicitis_001",
                "missed_items": [],
                "clinical_reasoning_trace": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "cognitive_patterns": [
                        {
                            "pattern_id": "weak_problem_representation",
                            "label": "问题表征薄弱",
                            "category": "problem_representation",
                            "severity": "high",
                        },
                        {
                            "pattern_id": "thin_differential_reasoning",
                            "label": "鉴别诊断过窄",
                            "category": "differential_reasoning",
                            "severity": "medium",
                        },
                    ],
                    "evidence_chain_breakpoints": [
                        {
                            "breakpoint_id": "rp_migration_support",
                            "statement": "迁移痛推理点",
                            "status": "broken",
                        }
                    ],
                },
            },
            {
                "case_id": "appendicitis_001",
                "missed_items": [],
                "clinical_reasoning_trace": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "cognitive_patterns": [
                        {
                            "pattern_id": "weak_problem_representation",
                            "label": "问题表征薄弱",
                            "category": "problem_representation",
                            "severity": "high",
                        },
                        {
                            "pattern_id": "thin_differential_reasoning",
                            "label": "鉴别诊断过窄",
                            "category": "differential_reasoning",
                            "severity": "medium",
                        },
                    ],
                    "evidence_chain_breakpoints": [
                        {
                            "breakpoint_id": "rp_migration_support",
                            "statement": "迁移痛推理点",
                            "status": "broken",
                        }
                    ],
                },
            },
        ],
        enabled_skills=[],
    )

    changes = summary["teaching_effect_summary"]["observed_changes"]
    descriptions = [change["description"] for change in changes]

    assert len(descriptions) >= 3
    assert len(set(descriptions)) == len(descriptions)
    assert any("起病、部位、性质" in description for description in descriptions)
    assert any("相似诊断" in description for description in descriptions)
    assert any("关键证据链断点" in description for description in descriptions)


def test_profile_summary_aggregates_sequence_and_evidence_chain_breakpoints() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {
                "case_id": "appendicitis_001",
                "missed_items": ["ht_migration"],
                "clinical_reasoning_trace": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "cognitive_patterns": [
                        {
                            "pattern_id": "premature_testing_before_exam",
                            "label": "检查顺序前置",
                            "category": "hypothesis_testing",
                            "severity": "medium",
                            "source_signal_ids": ["sequence:auxiliary_before_physical_exam"],
                        }
                    ],
                    "hypothesis_testing": {
                        "sequence_flags": [
                            {
                                "flag_id": "premature_testing_before_exam",
                                "label": "辅助检查早于关键查体",
                                "severity": "medium",
                                "evidence": "先申请血常规，再补做右下腹压痛。",
                            }
                        ]
                    },
                    "evidence_chain_breakpoints": [
                        {
                            "breakpoint_id": "rp_migration_support",
                            "statement": "迁移痛推理点",
                            "kind": "support",
                            "status": "broken",
                            "missing_evidence": ["appendicitis_001.hf_02"],
                            "missing_evidence_labels": ["追问疼痛部位及转移特征"],
                            "teacher_action": "先补齐疼痛部位和转移过程，再决定查体与检查。",
                        }
                    ],
                },
            },
            {
                "case_id": "appendicitis_001",
                "missed_items": ["pe_tenderness"],
                "clinical_reasoning_trace": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "hypothesis_testing": {
                        "sequence_flags": [
                            {
                                "flag_id": "premature_testing_before_exam",
                                "label": "辅助检查早于关键查体",
                                "severity": "medium",
                                "evidence": "检查申请早于腹部重点查体。",
                            }
                        ]
                    },
                    "evidence_chain_breakpoints": [
                        {
                            "breakpoint_id": "rp_migration_support",
                            "statement": "迁移痛推理点",
                            "kind": "support",
                            "status": "broken",
                            "missing_evidence": ["appendicitis_001.hf_02"],
                            "missing_evidence_labels": ["追问疼痛部位及转移特征"],
                            "teacher_action": "先补齐疼痛部位和转移过程，再决定查体与检查。",
                        }
                    ],
                },
            },
        ],
        enabled_skills=[
            {
                "skill_id": "skill_evidence_chain_bridge",
                "case_ids": ["appendicitis_001"],
                "trigger_item_ids": [],
                "reasoning_pattern_ids": ["evidence_chain_rp_migration_support"],
                "reasoning_pattern_labels": ["迁移痛推理点"],
                "support_count": 2,
            }
        ],
    )

    reasoning_summary = summary["reasoning_profile_summary"]

    assert reasoning_summary["sequence_issue_counts"][0]["flag_id"] == "premature_testing_before_exam"
    assert reasoning_summary["sequence_issue_counts"][0]["count"] == 2
    assert reasoning_summary["evidence_chain_focus"][0]["breakpoint_id"] == "rp_migration_support"
    assert reasoning_summary["evidence_chain_focus"][0]["count"] == 2
    assert reasoning_summary["evidence_chain_focus"][0]["missing_evidence_labels"] == ["追问疼痛部位及转移特征"]
    assert "evidence_chain_rp_migration_support" in reasoning_summary["recent_pattern_ids"]

    state = summary["skill_states"]["skill_evidence_chain_bridge"]
    assert state["state"] == "active"
    assert state["matched_recent_reasoning_patterns"] == [
        {"pattern_id": "evidence_chain_rp_migration_support", "label": "迁移痛推理点"}
    ]


def test_teaching_effect_summary_reports_insufficient_samples_without_claiming_improvement() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {
                "case_id": "appendicitis_001",
                "missed_items": ["ht_migration"],
                "clinical_reasoning_trace": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "cognitive_patterns": [
                        {
                            "pattern_id": "weak_problem_representation",
                            "label": "问题表征薄弱",
                            "category": "problem_representation",
                            "severity": "high",
                        }
                    ],
                },
            }
        ],
        enabled_skills=[],
    )

    teaching_effect = summary["teaching_effect_summary"]

    assert teaching_effect["status"] == "insufficient_samples"
    assert "样本不足" in teaching_effect["summary"]
    assert "证明" not in teaching_effect["summary"]
    assert teaching_effect["ability_axes"][0]["axis_id"] == "problem_representation"
    assert teaching_effect["ability_axes"][0]["state"] == "needs_observation"


def test_teaching_effect_summary_marks_repeated_reasoning_gap_as_needs_practice() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {
                "case_id": "appendicitis_001",
                "missed_items": ["ht_migration"],
                "clinical_reasoning_trace": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "cognitive_patterns": [
                        {
                            "pattern_id": "weak_problem_representation",
                            "label": "问题表征薄弱",
                            "category": "problem_representation",
                            "severity": "high",
                        }
                    ],
                },
            },
            {
                "case_id": "acs_001",
                "missed_items": ["ht_onset"],
                "clinical_reasoning_trace": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "cognitive_patterns": [
                        {
                            "pattern_id": "weak_problem_representation",
                            "label": "问题表征薄弱",
                            "category": "problem_representation",
                            "severity": "high",
                        }
                    ],
                },
            },
        ],
        enabled_skills=[],
    )

    teaching_effect = summary["teaching_effect_summary"]

    assert teaching_effect["status"] == "needs_practice"
    assert teaching_effect["ability_axes"][0]["axis_id"] == "problem_representation"
    assert teaching_effect["ability_axes"][0]["state"] == "persistent_gap"
    assert teaching_effect["ability_axes"][0]["latest_count"] == 1
    assert teaching_effect["ability_axes"][0]["historical_count"] == 1
    assert teaching_effect["next_teaching_objectives"][0] == "先把主诉整理成起病、部位、性质、程度、伴随症状和背景，再进入查体或检查。"


def test_teaching_effect_summary_observes_recent_improvement_without_claiming_proof() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {
                "case_id": "appendicitis_001",
                "missed_items": [],
                "clinical_reasoning_trace": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "cognitive_patterns": [],
                },
            },
            {
                "case_id": "appendicitis_001",
                "missed_items": ["ht_migration"],
                "clinical_reasoning_trace": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "cognitive_patterns": [
                        {
                            "pattern_id": "weak_problem_representation",
                            "label": "问题表征薄弱",
                            "category": "problem_representation",
                            "severity": "high",
                        }
                    ],
                },
            },
        ],
        enabled_skills=[],
    )

    teaching_effect = summary["teaching_effect_summary"]

    assert teaching_effect["status"] == "improving_observed"
    assert "不等于统计学证明" in teaching_effect["summary"]
    assert teaching_effect["ability_axes"][0]["axis_id"] == "problem_representation"
    assert teaching_effect["ability_axes"][0]["state"] == "improving_signal"
    assert teaching_effect["observed_changes"][0]["direction"] == "improved_recently"


def test_teaching_effect_summary_labels_metacognition_axis_for_students() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {
                "case_id": "appendicitis_001",
                "missed_items": [],
                "clinical_reasoning_trace": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "cognitive_patterns": [
                        {
                            "pattern_id": "premature_closure_risk",
                            "label": "过早闭合风险",
                            "category": "metacognition",
                            "severity": "medium",
                        }
                    ],
                },
            },
            {
                "case_id": "appendicitis_001",
                "missed_items": [],
                "clinical_reasoning_trace": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "cognitive_patterns": [],
                },
            },
        ],
        enabled_skills=[],
    )

    teaching_effect = summary["teaching_effect_summary"]
    metacognition_axis = next(axis for axis in teaching_effect["ability_axes"] if axis["axis_id"] == "metacognition")

    assert metacognition_axis["axis_label"] == "元认知监控"
    assert "metacognition" not in teaching_effect["observed_changes"][0]["description"]
