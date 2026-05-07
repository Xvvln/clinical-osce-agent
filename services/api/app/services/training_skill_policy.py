from __future__ import annotations

from typing import Any

REFLECTION_PROMPT_TEMPLATE = "训练结束后，请对照本轮反复漏掉的评分项复盘证据链，不补写标准答案或隐藏事实。"


def build_teaching_action_plan(
    *,
    stage_scope: list[str],
    trigger_item_ids: list[str],
    suggested_strategy: str,
) -> list[dict[str, Any]]:
    diagnosis_stage_scope = [stage for stage in stage_scope if stage == "diagnosis_submission"]
    if not diagnosis_stage_scope:
        diagnosis_stage_scope = ["diagnosis_submission"]
    return [
        {
            "action_type": "hint_ladder",
            "level": 1,
            "stage_scope": list(stage_scope),
            "trigger_item_ids": list(trigger_item_ids),
            "message_template": suggested_strategy,
        },
        {
            "action_type": "reflection_prompt",
            "level": 1,
            "stage_scope": diagnosis_stage_scope,
            "trigger_item_ids": list(trigger_item_ids),
            "message_template": REFLECTION_PROMPT_TEMPLATE,
        },
    ]


def build_prohibited_content_policy() -> dict[str, Any]:
    return {
        "forbid_main_diagnosis": True,
        "forbid_hidden_facts": True,
        "forbid_test_results": True,
        "forbid_treatment_plan": True,
        "forbid_dose": True,
        "allowed_scope": "teaching_strategy_only",
    }


def build_success_metrics() -> list[str]:
    return [
        "target_rubric_item_recovery_rate",
        "stage_completion_rate",
        "hint_after_skill_usage",
    ]
