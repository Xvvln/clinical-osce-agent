from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.services.clinical_reasoning_trace_service import (
    evidence_chain_focus_from_reports,
    pattern_counts_from_reports,
    sequence_issue_counts_from_reports,
)
from app.services.admin_display_resolver import effect_status_label, rubric_item_label, trigger_item_labels


def build_skill_profile_summary(
    *,
    reports: Iterable[Mapping[str, Any]],
    enabled_skills: Iterable[Mapping[str, Any]],
    recent_error_limit: int = 8,
    current_focus_limit: int = 3,
) -> dict[str, Any]:
    report_list = list(reports)
    recent_error_items = _recent_error_items(report_list, limit=recent_error_limit)
    recent_error_item_ids = [item["item_id"] for item in recent_error_items]
    current_focus_items = recent_error_items[:current_focus_limit]
    recent_error_set = set(recent_error_item_ids)
    recent_error_item_by_id = {item["item_id"]: item for item in recent_error_items}
    reasoning_profile_summary = _reasoning_profile_summary(report_list, limit=recent_error_limit)
    recent_reasoning_pattern_ids = reasoning_profile_summary["recent_pattern_ids"]
    recent_reasoning_pattern_set = set(recent_reasoning_pattern_ids)
    recent_reasoning_pattern_by_id = {
        item["pattern_id"]: item for item in reasoning_profile_summary["recent_patterns"]
    }
    skill_states = {
        str(skill.get("skill_id")): _skill_state(
            skill,
            recent_error_item_ids,
            recent_error_set,
            recent_error_item_by_id,
            recent_reasoning_pattern_ids,
            recent_reasoning_pattern_set,
            recent_reasoning_pattern_by_id,
            report_list,
        )
        for skill in enabled_skills
        if str(skill.get("skill_id", "")).strip()
    }
    return {
        "recent_error_item_ids": recent_error_item_ids,
        "recent_error_items": recent_error_items,
        "current_focus_item_ids": recent_error_item_ids[:current_focus_limit],
        "current_focus_items": current_focus_items,
        "reasoning_profile_summary": reasoning_profile_summary,
        "skill_states": skill_states,
        "last_updated_from_report_count": len(report_list),
    }


def _recent_error_items(reports: Iterable[Mapping[str, Any]], *, limit: int) -> list[dict[str, str]]:
    recent_items: list[dict[str, str]] = []
    seen: set[str] = set()
    for report in reports:
        case_id = str(report.get("case_id", "")).strip()
        missed_items = report.get("missed_items", [])
        if not isinstance(missed_items, list):
            continue
        for item_id in missed_items:
            normalized_item_id = str(item_id).strip()
            if not normalized_item_id or normalized_item_id in seen:
                continue
            seen.add(normalized_item_id)
            recent_items.append(
                {
                    "item_id": normalized_item_id,
                    "label": rubric_item_label(normalized_item_id, [case_id] if case_id else ()),
                }
            )
            if len(recent_items) >= limit:
                return recent_items
    return recent_items


def _skill_state(
    skill: Mapping[str, Any],
    recent_error_item_ids: list[str],
    recent_error_set: set[str],
    recent_error_item_by_id: Mapping[str, Mapping[str, str]],
    recent_reasoning_pattern_ids: list[str],
    recent_reasoning_pattern_set: set[str],
    recent_reasoning_pattern_by_id: Mapping[str, Mapping[str, Any]],
    reports: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    trigger_item_ids = _trigger_item_ids(skill)
    matched_recent_error_item_ids = [item_id for item_id in recent_error_item_ids if item_id in set(trigger_item_ids)]
    matched_recent_error_items = [
        {
            "item_id": item_id,
            "label": str(recent_error_item_by_id.get(item_id, {}).get("label") or item_id),
        }
        for item_id in matched_recent_error_item_ids
    ]
    reasoning_pattern_ids = _reasoning_pattern_ids(skill)
    matched_recent_reasoning_pattern_ids = [
        pattern_id for pattern_id in recent_reasoning_pattern_ids if pattern_id in set(reasoning_pattern_ids)
    ]
    matched_recent_reasoning_patterns = [
        {
            "pattern_id": pattern_id,
            "label": str(recent_reasoning_pattern_by_id.get(pattern_id, {}).get("label") or pattern_id),
        }
        for pattern_id in matched_recent_reasoning_pattern_ids
    ]
    effect_status = str(skill.get("effect_status", "insufficient_samples"))
    state = _state_for_skill(
        effect_status,
        matched_recent_error_item_ids,
        trigger_item_ids,
        reports or [],
        skill,
        matched_recent_reasoning_pattern_ids=matched_recent_reasoning_pattern_ids,
        reasoning_pattern_ids=reasoning_pattern_ids,
    )
    priority = _priority_for_skill(
        skill,
        state=state,
        matched_recent_error_item_ids=matched_recent_error_item_ids,
        matched_recent_reasoning_pattern_ids=matched_recent_reasoning_pattern_ids,
        recent_error_set=recent_error_set,
        recent_reasoning_pattern_set=recent_reasoning_pattern_set,
    )
    return {
        "state": state,
        "state_label": _state_label(state),
        "priority": priority,
        "trigger_item_ids": trigger_item_ids,
        "trigger_item_labels": trigger_item_labels(trigger_item_ids, _case_ids(skill)),
        "reasoning_pattern_ids": reasoning_pattern_ids,
        "reasoning_pattern_labels": _reasoning_pattern_labels(skill, reasoning_pattern_ids),
        "matched_recent_reasoning_pattern_ids": matched_recent_reasoning_pattern_ids,
        "matched_recent_reasoning_patterns": matched_recent_reasoning_patterns,
        "matched_recent_error_item_ids": matched_recent_error_item_ids,
        "matched_recent_error_items": matched_recent_error_items,
        "effect_status": effect_status,
        "effect_status_label": effect_status_label(effect_status),
        "selection_reason": _selection_reason(
            matched_recent_error_items,
            state,
            matched_recent_reasoning_patterns=matched_recent_reasoning_patterns,
        ),
    }


def _trigger_item_ids(skill: Mapping[str, Any]) -> list[str]:
    trigger_item_ids = _normalized_string_list(skill.get("trigger_item_ids"))
    if trigger_item_ids:
        return trigger_item_ids
    trigger_item_id = str(skill.get("trigger_item_id", "")).strip()
    if not _is_concrete_trigger_item_id(trigger_item_id):
        return []
    return [trigger_item_id] if trigger_item_id else []


def _state_for_skill(
    effect_status: str,
    matched_recent_error_item_ids: list[str],
    trigger_item_ids: list[str],
    reports: list[Mapping[str, Any]],
    skill: Mapping[str, Any],
    *,
    matched_recent_reasoning_pattern_ids: list[str],
    reasoning_pattern_ids: list[str],
) -> str:
    if not trigger_item_ids and not reasoning_pattern_ids:
        return "inactive"
    lifecycle_state = _lifecycle_state_from_reports(trigger_item_ids, reports, skill)
    if lifecycle_state:
        return lifecycle_state
    if matched_recent_error_item_ids or matched_recent_reasoning_pattern_ids:
        return "active"
    if effect_status == "improving":
        return "cooldown"
    if effect_status == "retired":
        return "retired"
    return "available"


def _state_label(state: str) -> str:
    return {
        "active": "正在生效",
        "available": "可用未命中",
        "inactive": "缺少触发项",
        "cooldown": "冷却观察",
        "reactivated": "重新激活",
        "retired": "已退休",
    }.get(state, "状态待观察")


def _selection_reason(
    matched_recent_error_items: list[dict[str, str]],
    state: str,
    *,
    matched_recent_reasoning_patterns: list[dict[str, str]] | None = None,
) -> str:
    matched_recent_reasoning_patterns = matched_recent_reasoning_patterns or []
    if state == "cooldown":
        return "近期已补上该 Skill 训练点，暂进入冷却观察。"
    if state == "retired":
        return "近期连续覆盖该 Skill 训练点，默认不再进入本轮提示。"
    if state == "reactivated" and matched_recent_error_items:
        labels = [item["label"] for item in matched_recent_error_items[:3]]
        return f"近期又出现该 Skill 相关缺口：{'、'.join(labels)}。"
    if matched_recent_reasoning_patterns:
        labels = [item["label"] for item in matched_recent_reasoning_patterns[:3]]
        if matched_recent_error_items:
            item_labels = [item["label"] for item in matched_recent_error_items[:2]]
            return f"近期画像命中思维模式：{'、'.join(labels)}；关联训练点：{'、'.join(item_labels)}。"
        return f"近期画像命中思维模式：{'、'.join(labels)}。"
    if matched_recent_error_items:
        labels = [item["label"] for item in matched_recent_error_items[:3]]
        return f"近期画像命中：{'、'.join(labels)}。"
    if state == "available":
        return "近期未命中该 Skill 训练点，仅作为备用教学策略。"
    return "该 Skill 缺少可匹配训练点，需管理员复核后再进入提示编排。"


def _case_ids(skill: Mapping[str, Any]) -> list[str]:
    case_ids = _normalized_string_list(skill.get("case_ids"))
    if case_ids:
        return case_ids
    applies_when = skill.get("applies_when")
    if isinstance(applies_when, Mapping):
        return [str(case_id).strip() for case_id in applies_when.get("case_ids", []) if str(case_id).strip()]
    return []


def _priority_for_skill(
    skill: Mapping[str, Any],
    *,
    state: str,
    matched_recent_error_item_ids: list[str],
    matched_recent_reasoning_pattern_ids: list[str],
    recent_error_set: set[str],
    recent_reasoning_pattern_set: set[str],
) -> int:
    if state in {"cooldown", "retired", "inactive"}:
        return -100
    if state == "available":
        return 0
    priority = 0
    if matched_recent_error_item_ids:
        priority += 8
    if matched_recent_reasoning_pattern_ids:
        priority += 6
    if set(_trigger_item_ids(skill)) & recent_error_set:
        priority += min(int(skill.get("support_count") or 0), 3)
    if set(_reasoning_pattern_ids(skill)) & recent_reasoning_pattern_set:
        priority += min(int(skill.get("support_count") or 0), 3)
    return priority


def _lifecycle_state_from_reports(
    trigger_item_ids: list[str],
    reports: list[Mapping[str, Any]],
    skill: Mapping[str, Any],
    *,
    stable_coverage_window: int = 3,
) -> str:
    relevant_reports = [
        report for report in reports if _report_relevant_to_skill(report, skill)
    ]
    if not relevant_reports:
        return ""
    recent_reports = relevant_reports[:stable_coverage_window]
    latest_report = relevant_reports[0]
    if _report_misses_any(latest_report, trigger_item_ids):
        previous_stable_reports = relevant_reports[1 : stable_coverage_window + 1]
        older_reports = relevant_reports[stable_coverage_window + 1 :]
        if (
            len(previous_stable_reports) >= stable_coverage_window
            and all(not _report_misses_any(report, trigger_item_ids) for report in previous_stable_reports)
            and any(_report_misses_any(report, trigger_item_ids) for report in older_reports)
        ):
            return "reactivated"
        return "active"
    historical_miss_count = sum(1 for report in relevant_reports if _report_misses_any(report, trigger_item_ids))
    if historical_miss_count == 0:
        return ""
    if len(recent_reports) >= stable_coverage_window and all(
        not _report_misses_any(report, trigger_item_ids) for report in recent_reports
    ):
        return "retired"
    return "cooldown"


def _report_relevant_to_skill(report: Mapping[str, Any], skill: Mapping[str, Any]) -> bool:
    case_ids = _case_ids(skill)
    if not case_ids:
        return True
    return str(report.get("case_id", "")).strip() in set(case_ids)


def _report_misses_any(report: Mapping[str, Any], trigger_item_ids: list[str]) -> bool:
    if not trigger_item_ids:
        return False
    missed_items = report.get("missed_items", [])
    if not isinstance(missed_items, list):
        return False
    missed_item_set = {str(item_id).strip() for item_id in missed_items if str(item_id).strip()}
    return bool(set(trigger_item_ids) & missed_item_set)


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw_item).strip() for raw_item in value) if item]


def _reasoning_profile_summary(reports: list[Mapping[str, Any]], *, limit: int) -> dict[str, Any]:
    sequence_issue_counts = sequence_issue_counts_from_reports(reports, limit=limit)
    evidence_chain_focus = evidence_chain_focus_from_reports(reports, limit=limit)
    recent_patterns = _merged_reasoning_patterns(
        pattern_counts_from_reports(reports),
        sequence_issue_counts,
        evidence_chain_focus,
        limit=limit,
    )
    recent_pattern_ids = [pattern["pattern_id"] for pattern in recent_patterns]
    return {
        "recent_pattern_ids": recent_pattern_ids,
        "recent_patterns": recent_patterns,
        "dominant_patterns": recent_patterns[:3],
        "current_reasoning_focus": recent_patterns[:3],
        "profile_axes": _profile_axes(recent_patterns),
        "sequence_issue_counts": sequence_issue_counts,
        "evidence_chain_focus": evidence_chain_focus,
    }


def _merged_reasoning_patterns(
    cognitive_patterns: list[Mapping[str, Any]],
    sequence_issue_counts: list[Mapping[str, Any]],
    evidence_chain_focus: list[Mapping[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern in cognitive_patterns:
        pattern_id = str(pattern.get("pattern_id") or "").strip()
        if not pattern_id or pattern_id in seen:
            continue
        seen.add(pattern_id)
        patterns.append(dict(pattern))
    for sequence_issue in sequence_issue_counts:
        pattern_id = str(sequence_issue.get("flag_id") or "").strip()
        if not pattern_id or pattern_id in seen:
            continue
        seen.add(pattern_id)
        patterns.append(
            {
                "pattern_id": pattern_id,
                "label": str(sequence_issue.get("label") or pattern_id),
                "category": "workflow_sequencing",
                "severity": str(sequence_issue.get("severity") or "medium"),
                "count": int(sequence_issue.get("count") or 1),
            }
        )
    for breakpoint in evidence_chain_focus:
        breakpoint_id = str(breakpoint.get("breakpoint_id") or breakpoint.get("statement") or "").strip()
        if not breakpoint_id:
            continue
        pattern_id = f"evidence_chain_{_safe_pattern_id_fragment(breakpoint_id)}"
        if pattern_id in seen:
            continue
        seen.add(pattern_id)
        patterns.append(
            {
                "pattern_id": pattern_id,
                "label": str(breakpoint.get("statement") or breakpoint_id),
                "category": "evidence_chain",
                "severity": "medium",
                "count": int(breakpoint.get("count") or 1),
            }
        )
    return patterns[:limit]


def _safe_pattern_id_fragment(value: str) -> str:
    normalized = "".join(character if character.isalnum() or character == "_" else "_" for character in value)
    normalized = "_".join(part for part in normalized.split("_") if part)
    return normalized[:96] or "unknown"


def _profile_axes(recent_patterns: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    axes: dict[str, dict[str, Any]] = {}
    for pattern in recent_patterns:
        category = str(pattern.get("category") or "clinical_reasoning")
        axis = axes.setdefault(
            category,
            {
                "category": category,
                "count": 0,
                "pattern_ids": [],
                "labels": [],
            },
        )
        axis["count"] += int(pattern.get("count") or 1)
        pattern_id = str(pattern.get("pattern_id") or "")
        label = str(pattern.get("label") or pattern_id)
        if pattern_id and pattern_id not in axis["pattern_ids"]:
            axis["pattern_ids"].append(pattern_id)
        if label and label not in axis["labels"]:
            axis["labels"].append(label)
    return axes


def _reasoning_pattern_ids(skill: Mapping[str, Any]) -> list[str]:
    pattern_ids = _normalized_string_list(skill.get("reasoning_pattern_ids"))
    if pattern_ids:
        return pattern_ids
    applies_when = skill.get("applies_when")
    if isinstance(applies_when, Mapping):
        return _normalized_string_list(applies_when.get("reasoning_pattern_ids"))
    return []


def _reasoning_pattern_labels(skill: Mapping[str, Any], reasoning_pattern_ids: list[str]) -> list[str]:
    labels = _normalized_string_list(skill.get("reasoning_pattern_labels"))
    if labels:
        return labels
    return list(reasoning_pattern_ids)


def _is_concrete_trigger_item_id(value: str) -> bool:
    if not value:
        return False
    return not value.startswith(("training_pattern_", "turn_pattern_", "personal_skill_candidate_"))
