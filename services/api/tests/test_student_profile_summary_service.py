from __future__ import annotations

from app.services.student_profile_summary_service import build_skill_profile_summary


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
