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
