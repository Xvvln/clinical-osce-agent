from app.services.skill_role_policy_service import (
    build_approval_skill_role_policy,
    build_patient_skill_role_projection,
    build_teacher_skill_role_projection,
)
from app.services.training_skill_policy import (
    build_prohibited_content_policy,
    build_success_metrics,
)


def _active_context() -> dict[str, object]:
    return {
        "selected_skills": [
            {
                "skill_id": "skill_relationship_repair",
                "skill_type": "relationship_repair",
                "title": "患者情绪回应训练",
                "suggested_strategy": "先识别情绪，再继续问诊。",
                "intervention": {
                    "teaching_goal": "识别并回应患者当前情绪。",
                    "coach_strategy": "先用一句话承认情绪，再继续医学问诊。",
                    "hint_ladder": ["先识别情绪。", "用支持性语言回应。", "再继续聚焦问诊。", "多余第四层。"],
                    "teaching_sop": {"completion_signal": "先回应情绪后继续问诊。"},
                    "avoid": ["不得虚构患者情绪。"],
                },
            },
            {
                "skill_id": "skill_reasoning_bridge",
                "skill_type": "reasoning_bridge",
                "title": "证据链训练",
                "intervention": {"coach_strategy": "整理支持与排除证据。"},
            },
        ]
    }


def test_patient_projection_uses_only_fact_free_humanistic_practice_focus() -> None:
    projection = build_patient_skill_role_projection(_active_context())

    assert projection["active"] is True
    assert projection["source_skill_ids"] == ["skill_relationship_repair"]
    provider_policy = projection["provider_policy"]
    assert provider_policy["role"] == "patient"
    assert provider_policy["practice_focus"] == [
        "让当前已存在的患者情绪更容易被学生感知和回应"
    ]
    provider_text = str(provider_policy)
    assert "skill_relationship_repair" not in provider_text
    assert "先用一句话承认情绪" not in provider_text
    assert "整理支持与排除证据" not in provider_text


def test_teacher_projection_contains_only_router_selected_intervention() -> None:
    projection = build_teacher_skill_role_projection(
        _active_context(),
        ["skill_reasoning_bridge"],
    )

    assert projection["active"] is True
    assert projection["source_skill_ids"] == ["skill_reasoning_bridge"]
    policy = projection["provider_policy"]
    assert policy["precedence"][:3] == [
        "case_fact_boundary",
        "current_hint_policy",
        "safety_boundary",
    ]
    assert policy["interventions"] == [
        {
            "skill_id": "skill_reasoning_bridge",
            "title": "证据链训练",
            "coach_strategy": "整理支持与排除证据。",
        }
    ]
    assert "患者情绪回应训练" not in str(policy)


def test_approval_projection_uses_platform_defaults_for_legacy_empty_fields() -> None:
    policy = build_approval_skill_role_policy(
        {"prohibited_content_policy": {}, "success_metrics": []}
    )

    assert policy["passed"] is True
    assert policy["prohibited_content_policy"] == build_prohibited_content_policy()
    assert policy["prohibited_content_policy_source"] == "platform_default"
    assert policy["success_metrics"] == build_success_metrics()
    assert policy["success_metrics_source"] == "platform_default"


def test_approval_projection_blocks_explicitly_weakened_boundary_or_metrics() -> None:
    weakened_policy = build_prohibited_content_policy()
    weakened_policy["forbid_hidden_facts"] = False

    policy = build_approval_skill_role_policy(
        {
            "prohibited_content_policy": weakened_policy,
            "success_metrics": ["target_rubric_item_recovery_rate"],
        }
    )

    assert policy["passed"] is False
    assert policy["failed_checks"] == [
        "prohibited_content_policy_complete",
        "success_metrics_declared",
    ]
