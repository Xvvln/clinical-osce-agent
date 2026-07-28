from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from app.services.admin_display_resolver import trigger_item_labels


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

HUMANISTIC_SKILL_TYPES = {
    "narrative_perspective",
    "communication_structure",
    "ethics_consent",
    "relationship_repair",
}

GAP_TYPE_LABELS = {
    "narrative_patient_perspective_missing": "患者视角与担忧期待缺失",
    "communication_summary_missing": "阶段性总结与确认缺失",
    "communication_confirm_understanding_missing": "确认患者理解缺失",
    "ethics_consent_missing": "查体或检查前说明目的并征得同意",
    "ethics_privacy_comfort_missing": "隐私与舒适度说明缺失",
    "ethics_autonomy_missing": "尊重患者自主表达不足",
    "relationship_empathy_missing": "患者情绪回应缺失",
}


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
    recent_training_gap_types = {
        str(gap_type)
        for gap_type in profile.get("recent_training_gap_types", [])
        if str(gap_type)
    }
    recent_training_skill_types = {
        str(skill_type)
        for skill_type in profile.get("recent_training_skill_types", [])
        if str(skill_type)
    }
    current_training_gaps = _normalized_gap_list(profile.get("current_training_gaps", []))
    humanistic_training_goals = _normalized_gap_list(profile.get("current_humanistic_gaps", []))
    training_gap_labels = {
        str(gap.get("gap_type") or ""): str(gap.get("label") or _gap_type_label(str(gap.get("gap_type") or "")))
        for gap in [*current_training_gaps, *humanistic_training_goals]
        if str(gap.get("gap_type") or "")
    }
    reasoning_pattern_labels = _reasoning_pattern_labels(profile)
    recent_reasoning_pattern_ids = set(reasoning_pattern_labels.keys())

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
            recent_reasoning_pattern_ids=recent_reasoning_pattern_ids,
            recent_training_gap_types=recent_training_gap_types,
            recent_training_skill_types=recent_training_skill_types,
            patient_profile=patient_profile or {},
        )
        if skip_reason:
            skipped_reasons.append({"skill_id": skill_id, "reason": skip_reason})
            continue
        profile_state = _profile_skill_state(skill_id, skill_states)
        if profile_state in {"cooldown", "retired"}:
            skipped_reasons.append({"skill_id": skill_id, "reason": f"profile_state_{profile_state}"})
            continue
        trigger_item_ids = _trigger_item_ids(skill)
        reasoning_pattern_ids = _skill_reasoning_pattern_ids(skill)
        trigger_gap_types = _skill_gap_types(skill)
        reasoning_pattern_hits = [
            pattern_id for pattern_id in reasoning_pattern_ids if pattern_id in recent_reasoning_pattern_ids
        ]
        training_gap_hits = [gap_type for gap_type in trigger_gap_types if gap_type in recent_training_gap_types]
        training_skill_type_hits = _skill_type_hits(skill, recent_training_skill_types)
        priority = _skill_priority(
            skill_id=skill_id,
            trigger_item_ids=trigger_item_ids,
            reasoning_pattern_ids=reasoning_pattern_ids,
            trigger_gap_types=trigger_gap_types,
            skill_type_hits=training_skill_type_hits,
            current_missing_evidence=missing_item_set,
            recent_error_item_ids=recent_error_item_ids,
            recent_reasoning_pattern_ids=recent_reasoning_pattern_ids,
            recent_training_gap_types=recent_training_gap_types,
            skill_states=skill_states,
        )
        candidates.append(
            {
                "skill": dict(skill),
                "priority": priority,
                "trigger_item_ids": trigger_item_ids,
                "reasoning_pattern_ids": reasoning_pattern_ids,
                "reasoning_pattern_hits": reasoning_pattern_hits,
                "reasoning_pattern_labels": [
                    reasoning_pattern_labels.get(pattern_id, pattern_id) for pattern_id in reasoning_pattern_hits
                ],
                "trigger_gap_types": trigger_gap_types,
                "training_gap_hits": training_gap_hits,
                "training_gap_labels": [
                    training_gap_labels.get(gap_type, _gap_type_label(gap_type)) for gap_type in training_gap_hits
                ],
                "training_skill_type_hits": training_skill_type_hits,
                "why_candidate": _why_candidate(
                    trigger_item_ids,
                    missing_item_set,
                    recent_error_item_ids,
                    reasoning_pattern_hits=reasoning_pattern_hits,
                    reasoning_pattern_labels=reasoning_pattern_labels,
                    training_gap_hits=training_gap_hits,
                    training_gap_labels=training_gap_labels,
                    training_skill_type_hits=training_skill_type_hits,
                ),
                "why_selected_label": _why_selected_label(
                    trigger_item_ids,
                    current_missing_evidence=missing_item_set,
                    recent_error_item_ids=recent_error_item_ids,
                    reasoning_pattern_hits=reasoning_pattern_hits,
                    reasoning_pattern_labels=reasoning_pattern_labels,
                    training_gap_hits=training_gap_hits,
                    training_gap_labels=training_gap_labels,
                    training_skill_type_hits=training_skill_type_hits,
                    case_id=case_id,
                ),
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
        "current_training_gaps": current_training_gaps[:3],
        "humanistic_training_goals": humanistic_training_goals[:3],
    }


def _skip_reason(
    skill: Mapping[str, Any],
    *,
    case_id: str,
    student_id: str,
    stage: str,
    rubric_item_ids: set[str],
    current_missing_evidence: set[str],
    recent_reasoning_pattern_ids: set[str],
    recent_training_gap_types: set[str],
    recent_training_skill_types: set[str],
    patient_profile: Mapping[str, Any],
) -> str:
    if not _applies_to_case(skill, case_id, rubric_item_ids):
        return "case_mismatch"
    if not _applies_to_student(skill, student_id):
        return "student_mismatch"
    if not _applies_to_stage(skill, stage):
        return "stage_mismatch"
    if not _trigger_item_ids(skill) and not _skill_reasoning_pattern_ids(skill) and not _skill_gap_types(skill) and not _skill_type_hits(skill, recent_training_skill_types):
        return "trigger_items_missing"
    if not _matches_missing_evidence(
        skill,
        rubric_item_ids,
        current_missing_evidence,
        recent_reasoning_pattern_ids,
        recent_training_gap_types,
        recent_training_skill_types,
    ):
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
    recent_reasoning_pattern_ids: set[str],
    recent_training_gap_types: set[str],
    recent_training_skill_types: set[str],
) -> bool:
    if set(_skill_reasoning_pattern_ids(skill)) & recent_reasoning_pattern_ids:
        return True
    if set(_skill_gap_types(skill)) & recent_training_gap_types:
        return True
    if _skill_type_hits(skill, recent_training_skill_types):
        return True
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
    reasoning_pattern_ids: list[str],
    trigger_gap_types: list[str],
    skill_type_hits: list[str],
    current_missing_evidence: set[str],
    recent_error_item_ids: set[str],
    recent_reasoning_pattern_ids: set[str],
    recent_training_gap_types: set[str],
    skill_states: Mapping[str, Any],
) -> int:
    priority = 0
    if set(trigger_item_ids) & current_missing_evidence:
        priority += 4
    if set(trigger_item_ids) & recent_error_item_ids:
        priority += 4
    if set(reasoning_pattern_ids) & recent_reasoning_pattern_ids:
        priority += 8
    if set(trigger_gap_types) & recent_training_gap_types:
        priority += 8
    if skill_type_hits:
        priority += 6
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


def _profile_skill_state(skill_id: str, skill_states: Mapping[str, Any]) -> str:
    state = skill_states.get(skill_id, {})
    if not isinstance(state, Mapping):
        return ""
    return str(state.get("state", "")).strip()


def _serialize_skill_index(candidate: Mapping[str, Any]) -> dict[str, Any]:
    skill = candidate["skill"]
    trigger_items = list(candidate["trigger_item_ids"])
    router_index = skill.get("router_index")
    if not isinstance(router_index, Mapping):
        router_index = {}
    payload = {
        "skill_id": str(skill["skill_id"]),
        "title": str(skill.get("title", "")),
        "scope": str(skill.get("scope", "global")),
        "stage_scope": _stage_scope(skill),
        "trigger_item_ids": trigger_items,
        "trigger_item_labels": trigger_item_labels(trigger_items, _case_ids(skill)),
        "priority": int(candidate["priority"]),
        "why_candidate": str(candidate["why_candidate"]),
        "why_selected_label": str(candidate["why_selected_label"]),
    }
    for field_name in ("summary", "when_to_use", "when_not_to_use", "risk"):
        field_value = str(router_index.get(field_name) or "").strip()
        if field_value:
            payload[field_name] = field_value
    reasoning_pattern_ids = list(candidate.get("reasoning_pattern_ids", []))
    if reasoning_pattern_ids:
        payload["reasoning_pattern_ids"] = reasoning_pattern_ids
        payload["reasoning_pattern_labels"] = list(candidate.get("reasoning_pattern_labels", []))
    trigger_gap_types = list(candidate.get("trigger_gap_types", []))
    if trigger_gap_types:
        payload["trigger_gap_types"] = trigger_gap_types
        payload["training_gap_labels"] = list(candidate.get("training_gap_labels", []))
    _add_skill_source_provenance(payload, skill)
    return payload


def _serialize_selected_skill(candidate: Mapping[str, Any]) -> dict[str, Any]:
    skill = candidate["skill"]
    trigger_items = list(candidate["trigger_item_ids"])
    router_index = skill.get("router_index")
    if not isinstance(router_index, Mapping):
        router_index = {}
    payload = {
        "skill_id": str(skill["skill_id"]),
        "title": str(skill.get("title", "")),
        "suggested_strategy": str(skill.get("suggested_strategy", "")),
        "skill_type": str(skill.get("skill_type", "reasoning_bridge")),
        "stage_scope": _stage_scope(skill),
        "trigger_item_ids": trigger_items,
        "trigger_item_labels": trigger_item_labels(trigger_items, _case_ids(skill)),
        "priority": int(candidate["priority"]),
        "why_candidate": str(candidate["why_candidate"]),
        "why_selected_label": str(candidate["why_selected_label"]),
        "effect_status": str(skill.get("effect_status", "insufficient_samples")),
    }
    intervention = skill.get("intervention")
    if isinstance(intervention, Mapping):
        payload["intervention"] = dict(intervention)
    for field_name in ("summary", "when_to_use", "when_not_to_use", "risk"):
        field_value = str(router_index.get(field_name) or "").strip()
        if field_value:
            payload[field_name] = field_value
    reasoning_pattern_ids = list(candidate.get("reasoning_pattern_ids", []))
    if reasoning_pattern_ids:
        payload["reasoning_pattern_ids"] = reasoning_pattern_ids
        payload["reasoning_pattern_labels"] = list(candidate.get("reasoning_pattern_labels", []))
    trigger_gap_types = list(candidate.get("trigger_gap_types", []))
    if trigger_gap_types:
        payload["trigger_gap_types"] = trigger_gap_types
        payload["training_gap_labels"] = list(candidate.get("training_gap_labels", []))
    _add_skill_source_provenance(payload, skill)
    return payload


def _add_skill_source_provenance(
    payload: dict[str, Any],
    skill: Mapping[str, Any],
) -> None:
    schema_version = str(
        skill.get("source_provenance_schema_version", "")
    ).strip()
    if schema_version != "training_candidate_sources.v1":
        return
    payload["source_provenance_schema_version"] = schema_version
    payload["source_session_ids"] = _normalized_string_list(
        skill.get("source_session_ids")
    )
    payload["source_report_ids"] = _normalized_string_list(
        skill.get("source_report_ids")
    )


def _trigger_item_ids(skill: Mapping[str, Any]) -> list[str]:
    trigger_item_ids = _normalized_string_list(skill.get("trigger_item_ids"))
    if trigger_item_ids:
        return trigger_item_ids
    trigger_item_id = str(skill.get("trigger_item_id", "")).strip()
    if not _is_concrete_trigger_item_id(trigger_item_id):
        return []
    return [trigger_item_id] if trigger_item_id else []


def _skill_reasoning_pattern_ids(skill: Mapping[str, Any]) -> list[str]:
    return _normalized_string_list(skill.get("reasoning_pattern_ids"))


def _skill_gap_types(skill: Mapping[str, Any]) -> list[str]:
    gap_types = _normalized_string_list(skill.get("trigger_gap_types"))
    if gap_types:
        return gap_types
    gap_types = _normalized_string_list(skill.get("gap_types"))
    if gap_types:
        return gap_types
    applies_when = skill.get("applies_when", {})
    if not isinstance(applies_when, Mapping):
        return []
    return _normalized_string_list(applies_when.get("trigger_gap_types") or applies_when.get("gap_types"))


def _skill_type_hits(skill: Mapping[str, Any], recent_training_skill_types: set[str]) -> list[str]:
    skill_type = str(skill.get("skill_type") or "").strip()
    if skill_type in HUMANISTIC_SKILL_TYPES and skill_type in recent_training_skill_types:
        return [skill_type]
    return []


def _stage_scope(skill: Mapping[str, Any]) -> list[str]:
    applies_when = skill.get("applies_when", {})
    if not isinstance(applies_when, Mapping):
        applies_when = {}
    return _normalized_string_list(skill.get("stage_scope")) or _normalized_string_list(applies_when.get("stage_scope"))


def _case_ids(skill: Mapping[str, Any]) -> list[str]:
    case_ids = _normalized_string_list(skill.get("case_ids"))
    if case_ids:
        return case_ids
    applies_when = skill.get("applies_when", {})
    if not isinstance(applies_when, Mapping):
        return []
    return _normalized_string_list(applies_when.get("case_ids"))


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
    *,
    reasoning_pattern_hits: list[str] | None = None,
    reasoning_pattern_labels: Mapping[str, str] | None = None,
    training_gap_hits: list[str] | None = None,
    training_gap_labels: Mapping[str, str] | None = None,
    training_skill_type_hits: list[str] | None = None,
) -> str:
    gap_hits = list(training_gap_hits or [])
    if gap_hits:
        labels = _labels_for_training_gaps(gap_hits, training_gap_labels or {})
        return f"近期训练缺口命中 {', '.join(labels)}"
    skill_type_hits = list(training_skill_type_hits or [])
    if skill_type_hits:
        labels = [_skill_type_label(skill_type) for skill_type in skill_type_hits]
        return f"近期人文沟通类型命中 {', '.join(labels)}"
    pattern_hits = list(reasoning_pattern_hits or [])
    if pattern_hits:
        labels = _labels_for_reasoning_patterns(pattern_hits, reasoning_pattern_labels or {})
        return f"近期思维模式命中 {', '.join(labels)}"
    missing_hits = [item_id for item_id in trigger_item_ids if item_id in current_missing_evidence]
    if missing_hits:
        return f"当前缺口命中 {', '.join(missing_hits)}"
    recent_hits = [item_id for item_id in trigger_item_ids if item_id in recent_error_item_ids]
    if recent_hits:
        return f"近期画像命中 {', '.join(recent_hits)}"
    if trigger_item_ids:
        return f"适用训练点 {', '.join(trigger_item_ids)}"
    return "通用教学策略"


def _why_selected_label(
    trigger_item_ids: list[str],
    *,
    current_missing_evidence: set[str],
    recent_error_item_ids: set[str],
    reasoning_pattern_hits: list[str] | None = None,
    reasoning_pattern_labels: Mapping[str, str] | None = None,
    training_gap_hits: list[str] | None = None,
    training_gap_labels: Mapping[str, str] | None = None,
    training_skill_type_hits: list[str] | None = None,
    case_id: str,
) -> str:
    gap_hits = list(training_gap_hits or [])
    if gap_hits:
        labels = _labels_for_training_gaps(gap_hits, training_gap_labels or {})
        return f"近期训练缺口命中：{'、'.join(labels)}。"
    skill_type_hits = list(training_skill_type_hits or [])
    if skill_type_hits:
        labels = [_skill_type_label(skill_type) for skill_type in skill_type_hits]
        return f"近期人文沟通类型命中：{'、'.join(labels)}。"
    pattern_hits = list(reasoning_pattern_hits or [])
    if pattern_hits:
        labels = _labels_for_reasoning_patterns(pattern_hits, reasoning_pattern_labels or {})
        return f"近期思维模式命中：{'、'.join(labels)}。"
    missing_hits = [item_id for item_id in trigger_item_ids if item_id in current_missing_evidence]
    if missing_hits:
        return f"当前缺口命中：{'、'.join(trigger_item_labels(missing_hits, [case_id]))}。"
    recent_hits = [item_id for item_id in trigger_item_ids if item_id in recent_error_item_ids]
    if recent_hits:
        return f"近期画像命中：{'、'.join(trigger_item_labels(recent_hits, [case_id]))}。"
    if trigger_item_ids:
        return f"适用训练点：{'、'.join(trigger_item_labels(trigger_item_ids, [case_id]))}。"
    return "通用教学策略。"


def _reasoning_pattern_labels(profile: Mapping[str, Any]) -> dict[str, str]:
    summary = profile.get("reasoning_profile_summary")
    if not isinstance(summary, Mapping):
        return {}
    labels: dict[str, str] = {}
    for pattern_id in _normalized_string_list(summary.get("recent_pattern_ids")):
        labels[pattern_id] = pattern_id
    for key in ("recent_patterns", "dominant_patterns"):
        patterns = summary.get(key, [])
        if not isinstance(patterns, list):
            continue
        for pattern in patterns:
            if not isinstance(pattern, Mapping):
                continue
            pattern_id = str(pattern.get("pattern_id") or "").strip()
            if not pattern_id:
                continue
            labels[pattern_id] = str(pattern.get("label") or pattern_id).strip()
    return labels


def _labels_for_reasoning_patterns(pattern_ids: list[str], labels_by_pattern_id: Mapping[str, str]) -> list[str]:
    return [str(labels_by_pattern_id.get(pattern_id) or pattern_id) for pattern_id in pattern_ids]


def _labels_for_training_gaps(gap_types: list[str], labels_by_gap_type: Mapping[str, str]) -> list[str]:
    return [str(labels_by_gap_type.get(gap_type) or _gap_type_label(gap_type)) for gap_type in gap_types]


def _gap_type_label(gap_type: str) -> str:
    return GAP_TYPE_LABELS.get(str(gap_type or ""), str(gap_type or "") or "未记录训练缺口")


def _skill_type_label(skill_type: str) -> str:
    return {
        "narrative_perspective": "患者叙事与视角训练",
        "communication_structure": "沟通结构训练",
        "ethics_consent": "知情同意训练",
        "relationship_repair": "医患关系修复训练",
    }.get(str(skill_type or ""), str(skill_type or "") or "未分类 Skill")


def _normalized_gap_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]
