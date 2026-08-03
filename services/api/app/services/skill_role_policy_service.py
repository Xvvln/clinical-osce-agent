from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.training_skill_policy import (
    build_prohibited_content_policy,
    build_success_metrics,
)


SKILL_ROLE_POLICY_VERSION = "skill_role_policy.v1"

PATIENT_PRACTICE_FOCUS_BY_SKILL_TYPE = {
    "narrative_perspective": "当本轮事实支持时，自然表达生活影响、担忧或期待",
    "communication_structure": "自然回应学生的总结确认与理解校验",
    "ethics_consent": "自然回应知情同意、隐私和舒适度相关表达",
    "relationship_repair": "让当前已存在的患者情绪更容易被学生感知和回应",
}

PATIENT_ROLE_CONSTRAINTS = [
    "表达风格不得决定或新增病例事实",
    "情绪只能来自当前 patient_affect_state 和本轮可回答事实",
    "不得以患者口吻教导学生或暗示下一步",
]

TEACHER_ROLE_PRECEDENCE = [
    "case_fact_boundary",
    "current_hint_policy",
    "safety_boundary",
    "routed_skill_intervention",
]


def build_patient_skill_role_projection(active_skill_context: Any) -> dict[str, Any]:
    """Project active humanistic Skills into a fact-free patient style policy."""

    source_skill_ids: list[str] = []
    practice_focus: list[str] = []
    for skill in _selected_skills(active_skill_context):
        skill_type = str(skill.get("skill_type") or "").strip()
        focus = PATIENT_PRACTICE_FOCUS_BY_SKILL_TYPE.get(skill_type)
        if not focus:
            continue
        skill_id = str(skill.get("skill_id") or "").strip()
        _append_unique(source_skill_ids, skill_id)
        _append_unique(practice_focus, focus)

    active = bool(source_skill_ids and practice_focus)
    provider_policy: dict[str, Any] = {
        "version": SKILL_ROLE_POLICY_VERSION,
        "role": "patient",
        "active": active,
    }
    if active:
        provider_policy.update(
            {
                "practice_focus": practice_focus,
                "constraints": list(PATIENT_ROLE_CONSTRAINTS),
            }
        )
    return {
        "version": SKILL_ROLE_POLICY_VERSION,
        "role": "patient",
        "active": active,
        "source_skill_ids": source_skill_ids,
        "provider_policy": provider_policy,
    }


def build_teacher_skill_role_projection(
    active_skill_context: Any,
    selected_skill_ids: list[str],
) -> dict[str, Any]:
    """Project only the Skill Router's current selection into TeacherAgent policy."""

    selected_id_set = {
        str(skill_id).strip()
        for skill_id in selected_skill_ids
        if str(skill_id).strip()
    }
    source_skill_ids: list[str] = []
    interventions: list[dict[str, Any]] = []
    for skill in _selected_skills(active_skill_context):
        skill_id = str(skill.get("skill_id") or "").strip()
        if not skill_id or skill_id not in selected_id_set:
            continue
        intervention = skill.get("intervention")
        if not isinstance(intervention, Mapping):
            intervention = {}
        teaching_sop = intervention.get("teaching_sop")
        if not isinstance(teaching_sop, Mapping):
            teaching_sop = {}
        item = {
            "skill_id": skill_id,
            "title": str(skill.get("title") or "").strip(),
            "teaching_goal": str(intervention.get("teaching_goal") or "").strip(),
            "coach_strategy": str(
                intervention.get("coach_strategy")
                or skill.get("suggested_strategy")
                or ""
            ).strip(),
            "hint_ladder": _normalized_strings(intervention.get("hint_ladder"), limit=3),
            "completion_signal": str(teaching_sop.get("completion_signal") or "").strip(),
            "avoid": _normalized_strings(intervention.get("avoid"), limit=5),
        }
        interventions.append({key: value for key, value in item.items() if value not in ("", [])})
        source_skill_ids.append(skill_id)

    active = bool(interventions)
    provider_policy: dict[str, Any] = {
        "version": SKILL_ROLE_POLICY_VERSION,
        "role": "teacher",
        "active": active,
        "precedence": list(TEACHER_ROLE_PRECEDENCE),
    }
    if active:
        provider_policy["interventions"] = interventions
    return {
        "version": SKILL_ROLE_POLICY_VERSION,
        "role": "teacher",
        "active": active,
        "source_skill_ids": source_skill_ids,
        "provider_policy": provider_policy,
    }


def build_approval_skill_role_policy(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve and validate the immutable safety and outcome policy for ApprovalAgent."""

    raw_prohibited_policy = candidate.get("prohibited_content_policy")
    if isinstance(raw_prohibited_policy, Mapping) and raw_prohibited_policy:
        prohibited_policy = dict(raw_prohibited_policy)
        prohibited_policy_source = "candidate"
    else:
        prohibited_policy = build_prohibited_content_policy()
        prohibited_policy_source = "platform_default"

    raw_success_metrics = candidate.get("success_metrics")
    if isinstance(raw_success_metrics, list) and raw_success_metrics:
        success_metrics = _normalized_strings(raw_success_metrics)
        success_metrics_source = "candidate"
    else:
        success_metrics = build_success_metrics()
        success_metrics_source = "platform_default"

    required_prohibitions = build_prohibited_content_policy()
    failed_prohibitions = [
        key
        for key, required_value in required_prohibitions.items()
        if prohibited_policy.get(key) != required_value
    ]
    required_success_metrics = build_success_metrics()
    missing_success_metrics = [
        metric for metric in required_success_metrics if metric not in success_metrics
    ]
    checks = [
        {
            "check_id": "prohibited_content_policy_complete",
            "passed": not failed_prohibitions,
            "detail": (
                "病例答案、隐藏事实、检查结果、治疗和剂量边界完整"
                if not failed_prohibitions
                else f"不合格策略字段：{', '.join(failed_prohibitions)}"
            ),
        },
        {
            "check_id": "success_metrics_declared",
            "passed": not missing_success_metrics,
            "detail": (
                "已声明评分项恢复、阶段完成和提示使用变化指标"
                if not missing_success_metrics
                else f"缺少成效指标：{', '.join(missing_success_metrics)}"
            ),
        },
    ]
    failed_checks = [check["check_id"] for check in checks if not check["passed"]]
    return {
        "version": SKILL_ROLE_POLICY_VERSION,
        "role": "approval",
        "passed": not failed_checks,
        "prohibited_content_policy": prohibited_policy,
        "prohibited_content_policy_source": prohibited_policy_source,
        "success_metrics": success_metrics,
        "success_metrics_source": success_metrics_source,
        "checks": checks,
        "failed_checks": failed_checks,
    }


def _selected_skills(active_skill_context: Any) -> list[Mapping[str, Any]]:
    if not isinstance(active_skill_context, Mapping):
        return []
    selected_skills = active_skill_context.get("selected_skills")
    if not isinstance(selected_skills, list):
        return []
    return [skill for skill in selected_skills if isinstance(skill, Mapping)]


def _normalized_strings(value: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = [item for raw in value if (item := str(raw).strip())]
    return normalized if limit is None else normalized[:limit]


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)
