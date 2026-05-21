from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


FEMALE_REPRODUCTIVE_TERMS = (
    "妇科",
    "妊娠",
    "怀孕",
    "宫外孕",
    "异位妊娠",
    "孕产",
    "月经",
    "停经",
    "阴道",
    "ectopic",
    "pregnancy",
    "pregnant",
    "gynecologic",
)


def build_active_skill_context(
    skills: Iterable[Mapping[str, Any]],
    *,
    case_id: str,
    student_id: str,
    stage: str,
    rubric_item_ids: Iterable[str] = (),
    current_missing_evidence: Iterable[str] = (),
    student_profile: Mapping[str, Any] | None = None,
    patient_profile: Mapping[str, Any] | None = None,
    limit: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Select a compact, safe Skill context for the current training turn."""

    rubric_item_set = {str(item_id) for item_id in rubric_item_ids}
    missing_item_set = {str(item_id) for item_id in current_missing_evidence}
    profile = student_profile or {}
    skill_states = profile.get("skill_states", {})
    if not isinstance(skill_states, Mapping):
        skill_states = {}
    recent_error_item_ids = {
        str(item_id)
        for item_id in profile.get("recent_error_item_ids", [])
        if str(item_id)
    }

    candidates: list[dict[str, Any]] = []
    skipped_reasons: list[dict[str, str]] = []
    for skill in skills:
        skill_id = str(skill.get("skill_id", "")).strip()
        if not skill_id:
            continue
        skip_reason = _skip_reason(
            skill,
            case_id=case_id,
            student_id=student_id,
            stage=stage,
            rubric_item_ids=rubric_item_set,
            current_missing_evidence=missing_item_set,
            patient_profile=patient_profile or {},
        )
        if skip_reason:
            skipped_reasons.append({"skill_id": skill_id, "reason": skip_reason})
            continue
        trigger_item_ids = _trigger_item_ids(skill)
        priority = _skill_priority(
            skill_id=skill_id,
            trigger_item_ids=trigger_item_ids,
            current_missing_evidence=missing_item_set,
            recent_error_item_ids=recent_error_item_ids,
            skill_states=skill_states,
        )
        candidates.append(
            {
                "skill": dict(skill),
                "priority": priority,
                "trigger_item_ids": trigger_item_ids,
                "why_candidate": _why_candidate(trigger_item_ids, missing_item_set, recent_error_item_ids),
            }
        )

    candidates.sort(
        key=lambda item: (
            -int(item["priority"]),
            -int(item["skill"].get("support_count") or 0),
            str(item["skill"].get("title", "")),
        )
    )
    selected_candidates = candidates[: max(limit, 0)]
    for candidate in candidates[max(limit, 0) :]:
        skipped_reasons.append({"skill_id": str(candidate["skill"]["skill_id"]), "reason": "not_selected_top_k"})

    return {
        "skill_index": [_serialize_skill_index(candidate) for candidate in selected_candidates],
        "selected_skills": [_serialize_selected_skill(candidate) for candidate in selected_candidates],
        "skipped_reasons": skipped_reasons,
    }


def _skip_reason(
    skill: Mapping[str, Any],
    *,
    case_id: str,
    student_id: str,
    stage: str,
    rubric_item_ids: set[str],
    current_missing_evidence: set[str],
    patient_profile: Mapping[str, Any],
) -> str:
    if not _applies_to_case(skill, case_id, rubric_item_ids):
        return "case_mismatch"
    if not _applies_to_student(skill, student_id):
        return "student_mismatch"
    if not _applies_to_stage(skill, stage):
        return "stage_mismatch"
    if not _trigger_item_ids(skill):
        return "trigger_items_missing"
    if not _matches_missing_evidence(skill, rubric_item_ids, current_missing_evidence):
        return "missing_evidence_mismatch"
    if _context_safety_mismatch(skill, patient_profile):
        return "context_safety_mismatch"
    return ""


def _applies_to_case(skill: Mapping[str, Any], case_id: str, rubric_item_ids: set[str]) -> bool:
    case_ids = _normalized_string_list(skill.get("case_ids"))
    if case_ids:
        return case_id in case_ids
    related_recommendations = _normalized_string_list(skill.get("related_recommendations"))
    if related_recommendations:
        rubric_prefix = f"rubric:{case_id}_rubric."
        return any(reference.startswith(rubric_prefix) or reference == f"case:{case_id}" for reference in related_recommendations)
    trigger_item_ids = _trigger_item_ids(skill)
    if trigger_item_ids:
        return bool(set(trigger_item_ids) & rubric_item_ids)
    return True


def _applies_to_student(skill: Mapping[str, Any], student_id: str) -> bool:
    if str(skill.get("scope", "global")) != "personal":
        return True
    return bool(student_id) and str(skill.get("owner_student_id", "")) == student_id


def _applies_to_stage(skill: Mapping[str, Any], stage: str) -> bool:
    stage_scope = _stage_scope(skill)
    if stage == "history_taking" and "case_intro" in stage_scope:
        return True
    return not stage_scope or "any" in stage_scope or stage in stage_scope


def _matches_missing_evidence(
    skill: Mapping[str, Any],
    rubric_item_ids: set[str],
    current_missing_evidence: set[str],
) -> bool:
    if not current_missing_evidence:
        return True
    trigger_item_ids = _trigger_item_ids(skill)
    if not trigger_item_ids:
        return True
    trigger_item_set = set(trigger_item_ids)
    return bool(trigger_item_set & current_missing_evidence) or bool(trigger_item_set & rubric_item_ids)


def _context_safety_mismatch(skill: Mapping[str, Any], patient_profile: Mapping[str, Any]) -> bool:
    if str(patient_profile.get("gender", "")) != "男":
        return False
    serialized_skill = json.dumps(skill, ensure_ascii=False).lower()
    return any(term.lower() in serialized_skill for term in FEMALE_REPRODUCTIVE_TERMS)


def _skill_priority(
    *,
    skill_id: str,
    trigger_item_ids: list[str],
    current_missing_evidence: set[str],
    recent_error_item_ids: set[str],
    skill_states: Mapping[str, Any],
) -> int:
    priority = 0
    if set(trigger_item_ids) & current_missing_evidence:
        priority += 4
    if set(trigger_item_ids) & recent_error_item_ids:
        priority += 4
    state = skill_states.get(skill_id, {})
    if isinstance(state, Mapping):
        raw_priority = state.get("priority", 0)
        if isinstance(raw_priority, int):
            priority += raw_priority
        elif isinstance(raw_priority, str) and raw_priority.isdigit():
            priority += int(raw_priority)
        if state.get("state") in {"cooldown", "retired"}:
            priority -= 100
    return priority


def _serialize_skill_index(candidate: Mapping[str, Any]) -> dict[str, Any]:
    skill = candidate["skill"]
    return {
        "skill_id": str(skill["skill_id"]),
        "title": str(skill.get("title", "")),
        "scope": str(skill.get("scope", "global")),
        "stage_scope": _stage_scope(skill),
        "trigger_item_ids": list(candidate["trigger_item_ids"]),
        "priority": int(candidate["priority"]),
        "why_candidate": str(candidate["why_candidate"]),
    }


def _serialize_selected_skill(candidate: Mapping[str, Any]) -> dict[str, Any]:
    skill = candidate["skill"]
    return {
        "skill_id": str(skill["skill_id"]),
        "title": str(skill.get("title", "")),
        "suggested_strategy": str(skill.get("suggested_strategy", "")),
        "skill_type": str(skill.get("skill_type", "reasoning_bridge")),
        "stage_scope": _stage_scope(skill),
        "trigger_item_ids": list(candidate["trigger_item_ids"]),
        "priority": int(candidate["priority"]),
        "why_candidate": str(candidate["why_candidate"]),
        "effect_status": str(skill.get("effect_status", "insufficient_samples")),
    }


def _trigger_item_ids(skill: Mapping[str, Any]) -> list[str]:
    trigger_item_ids = _normalized_string_list(skill.get("trigger_item_ids"))
    if trigger_item_ids:
        return trigger_item_ids
    trigger_item_id = str(skill.get("trigger_item_id", "")).strip()
    if not _is_concrete_trigger_item_id(trigger_item_id):
        return []
    return [trigger_item_id] if trigger_item_id else []


def _stage_scope(skill: Mapping[str, Any]) -> list[str]:
    applies_when = skill.get("applies_when", {})
    if not isinstance(applies_when, Mapping):
        applies_when = {}
    return _normalized_string_list(skill.get("stage_scope")) or _normalized_string_list(applies_when.get("stage_scope"))


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw_item).strip() for raw_item in value) if item]


def _is_concrete_trigger_item_id(value: str) -> bool:
    if not value:
        return False
    return not value.startswith(("training_pattern_", "turn_pattern_", "personal_skill_candidate_"))


def _why_candidate(
    trigger_item_ids: list[str],
    current_missing_evidence: set[str],
    recent_error_item_ids: set[str],
) -> str:
    missing_hits = [item_id for item_id in trigger_item_ids if item_id in current_missing_evidence]
    if missing_hits:
        return f"当前缺口命中 {', '.join(missing_hits)}"
    recent_hits = [item_id for item_id in trigger_item_ids if item_id in recent_error_item_ids]
    if recent_hits:
        return f"近期画像命中 {', '.join(recent_hits)}"
    if trigger_item_ids:
        return f"适用训练点 {', '.join(trigger_item_ids)}"
    return "通用教学策略"
