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
        "teaching_effect_summary": build_teaching_effect_summary(
            report_list,
            skill_states=skill_states,
            reasoning_profile_summary=reasoning_profile_summary,
        ),
        "last_updated_from_report_count": len(report_list),
    }


TEACHING_EFFECT_AXIS_DEFINITIONS: dict[str, dict[str, str]] = {
    "problem_representation": {
        "label": "问题表征",
        "objective": "先把主诉整理成起病、部位、性质、程度、伴随症状和背景，再进入查体或检查。",
    },
    "hypothesis_testing": {
        "label": "假设验证",
        "objective": "提出初步诊断假设后，用查体和检查去验证支持证据、反证和危险排除点。",
    },
    "workflow_sequencing": {
        "label": "诊疗顺序",
        "objective": "按病史主线、重点查体、必要检查和诊断表达的顺序推进，避免用检查替代问诊。",
    },
    "differential_reasoning": {
        "label": "鉴别诊断",
        "objective": "至少说清一个相似诊断和一个危险诊断的支持点、排除点和仍不确定点。",
    },
    "evidence_synthesis": {
        "label": "证据整合",
        "objective": "把病史、查体和检查组织为支持证据、反证和待补证据，而不是只列结论。",
    },
    "evidence_chain": {
        "label": "证据链",
        "objective": "围绕诊断假设补齐关键证据链断点，先解释证据为什么支持或排除某个判断。",
    },
    "metacognition": {
        "label": "元认知监控",
        "objective": "在提交诊断前主动检查是否过早闭合，确认是否还有关键反证、危险诊断或不确定点未处理。",
    },
    "clinical_reasoning": {
        "label": "临床推理",
        "objective": "下一轮先说明自己的推理路径，再决定要补问、补查或提交诊断。",
    },
}


def build_teaching_effect_summary(
    reports: Iterable[Mapping[str, Any]],
    *,
    skill_states: Mapping[str, Mapping[str, Any]] | None = None,
    reasoning_profile_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report_list = list(reports)
    skill_states = skill_states or {}
    reasoning_profile_summary = reasoning_profile_summary or {}
    axis_snapshots = [_axis_snapshot_from_report(report) for report in report_list]
    axes = _teaching_effect_axes(axis_snapshots)

    if not report_list:
        return {
            "status": "not_started",
            "status_label": "尚未开始",
            "summary": "完成一次完整训练并生成报告后，系统会开始观察临床思维训练效果。",
            "ability_axes": [],
            "observed_changes": [],
            "next_teaching_objectives": ["先完成一次完整训练，形成可复盘的问诊、查体、检查和诊断轨迹。"],
            "evidence_boundary": _teaching_effect_boundary(),
            "skill_state_counts": _skill_state_counts(skill_states),
            "reasoning_focus_count": len(reasoning_profile_summary.get("recent_pattern_ids", []) or []),
        }

    if len(report_list) < 2:
        return {
            "status": "insufficient_samples",
            "status_label": "样本不足",
            "summary": "样本不足：目前只有 1 份训练报告，只能记录本轮暴露的临床思维问题，不能判断趋势。",
            "ability_axes": [
                {**axis, "state": "needs_observation", "state_label": "继续观察"} for axis in axes
            ],
            "observed_changes": [],
            "next_teaching_objectives": _next_teaching_objectives(axes),
            "evidence_boundary": _teaching_effect_boundary(),
            "skill_state_counts": _skill_state_counts(skill_states),
            "reasoning_focus_count": len(reasoning_profile_summary.get("recent_pattern_ids", []) or []),
        }

    persistent_axes = [axis for axis in axes if axis["state"] in {"persistent_gap", "emerging_gap"}]
    improving_axes = [axis for axis in axes if axis["state"] == "improving_signal"]
    if persistent_axes:
        status = "needs_practice"
        status_label = "仍需训练"
        summary = "近期仍能观察到反复出现的临床思维问题，应继续围绕同一能力轴做短目标训练。"
    elif improving_axes:
        status = "improving_observed"
        status_label = "观察到改善"
        summary = "近期报告中部分既往问题暂未再次出现，属于观察到改善信号；这不等于统计学证明，仍需后续病例验证。"
    else:
        status = "stable_or_unobserved"
        status_label = "继续观察"
        summary = "近期报告暂未形成明确反复问题或改善趋势，建议继续积累不同病例下的训练样本。"

    return {
        "status": status,
        "status_label": status_label,
        "summary": summary,
        "ability_axes": axes,
        "observed_changes": _observed_teaching_changes(axes),
        "next_teaching_objectives": _next_teaching_objectives(persistent_axes or improving_axes or axes),
        "evidence_boundary": _teaching_effect_boundary(),
        "skill_state_counts": _skill_state_counts(skill_states),
        "reasoning_focus_count": len(reasoning_profile_summary.get("recent_pattern_ids", []) or []),
    }


def _axis_snapshot_from_report(report: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    trace = report.get("clinical_reasoning_trace")
    if not isinstance(trace, Mapping):
        return {}
    axes: dict[str, list[dict[str, Any]]] = {}

    cognitive_patterns = trace.get("cognitive_patterns", [])
    if isinstance(cognitive_patterns, list):
        for pattern in cognitive_patterns:
            if not isinstance(pattern, Mapping):
                continue
            pattern_id = str(pattern.get("pattern_id") or "").strip()
            if not pattern_id:
                continue
            axis_id = str(pattern.get("category") or "clinical_reasoning").strip() or "clinical_reasoning"
            axes.setdefault(axis_id, []).append(
                {
                    "signal_id": pattern_id,
                    "label": str(pattern.get("label") or pattern_id),
                    "severity": str(pattern.get("severity") or "medium"),
                }
            )

    hypothesis_testing = trace.get("hypothesis_testing")
    if isinstance(hypothesis_testing, Mapping):
        sequence_flags = hypothesis_testing.get("sequence_flags", [])
        if isinstance(sequence_flags, list):
            for flag in sequence_flags:
                if not isinstance(flag, Mapping):
                    continue
                flag_id = str(flag.get("flag_id") or "").strip()
                if not flag_id:
                    continue
                axes.setdefault("workflow_sequencing", []).append(
                    {
                        "signal_id": flag_id,
                        "label": str(flag.get("label") or flag_id),
                        "severity": str(flag.get("severity") or "medium"),
                    }
                )

    breakpoints = trace.get("evidence_chain_breakpoints", [])
    if isinstance(breakpoints, list):
        for breakpoint in breakpoints:
            if not isinstance(breakpoint, Mapping):
                continue
            status = str(breakpoint.get("status") or "").strip()
            if status and status not in {"broken", "missing", "weak"}:
                continue
            breakpoint_id = str(breakpoint.get("breakpoint_id") or breakpoint.get("statement") or "").strip()
            if not breakpoint_id:
                continue
            axes.setdefault("evidence_chain", []).append(
                {
                    "signal_id": breakpoint_id,
                    "label": str(breakpoint.get("statement") or breakpoint_id),
                    "severity": "medium",
                }
            )

    return axes


def _teaching_effect_axes(axis_snapshots: list[dict[str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    if not axis_snapshots:
        return []
    latest_snapshot = axis_snapshots[0]
    historical_snapshots = axis_snapshots[1:]
    axis_ids = sorted(
        {
            axis_id
            for snapshot in axis_snapshots
            for axis_id, signals in snapshot.items()
            if signals
        },
        key=_axis_sort_key,
    )
    axes = []
    for axis_id in axis_ids:
        latest_signals = latest_snapshot.get(axis_id, [])
        historical_signals = [
            signal for snapshot in historical_snapshots for signal in snapshot.get(axis_id, [])
        ]
        latest_count = len(latest_signals)
        historical_count = len(historical_signals)
        state = _axis_state(latest_count, historical_count, has_history=bool(historical_snapshots))
        labels = _unique_strings([str(signal.get("label") or "") for signal in latest_signals + historical_signals])
        axes.append(
            {
                "axis_id": axis_id,
                "axis_label": _axis_definition(axis_id)["label"],
                "state": state,
                "state_label": _axis_state_label(state),
                "latest_count": latest_count,
                "historical_count": historical_count,
                "labels": labels[:5],
                "teaching_objective": _axis_definition(axis_id)["objective"],
            }
        )
    return axes


def _axis_sort_key(axis_id: str) -> tuple[int, str]:
    ordered_axis_ids = list(TEACHING_EFFECT_AXIS_DEFINITIONS)
    try:
        return (ordered_axis_ids.index(axis_id), axis_id)
    except ValueError:
        return (len(ordered_axis_ids), axis_id)


def _axis_state(latest_count: int, historical_count: int, *, has_history: bool) -> str:
    if not has_history:
        return "needs_observation"
    if latest_count > 0 and historical_count > 0:
        return "persistent_gap"
    if latest_count > 0:
        return "emerging_gap"
    if historical_count > 0:
        return "improving_signal"
    return "stable_or_unobserved"


def _axis_state_label(state: str) -> str:
    return {
        "needs_observation": "继续观察",
        "persistent_gap": "反复出现",
        "emerging_gap": "新近出现",
        "improving_signal": "近期暂未再现",
        "stable_or_unobserved": "暂无明显信号",
    }.get(state, "继续观察")


def _axis_definition(axis_id: str) -> dict[str, str]:
    if axis_id in TEACHING_EFFECT_AXIS_DEFINITIONS:
        return TEACHING_EFFECT_AXIS_DEFINITIONS[axis_id]
    return {
        "label": axis_id,
        "objective": "下一轮围绕该能力轴做一次短目标训练，并在报告中观察是否反复出现。",
    }


def _observed_teaching_changes(axes: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for axis in axes:
        state = str(axis.get("state") or "")
        if state == "improving_signal":
            changes.append(
                {
                    "axis_id": str(axis.get("axis_id") or ""),
                    "axis_label": str(axis.get("axis_label") or ""),
                    "direction": "improved_recently",
                    "description": f"{axis.get('axis_label')}相关问题在最新报告中暂未再次出现，需要后续病例继续验证。",
                }
            )
        elif state in {"persistent_gap", "emerging_gap"}:
            changes.append(
                {
                    "axis_id": str(axis.get("axis_id") or ""),
                    "axis_label": str(axis.get("axis_label") or ""),
                    "direction": "needs_practice",
                    "description": f"{axis.get('axis_label')}仍是当前训练重点，下一轮应采用更小的步骤练习。",
                }
            )
    return changes


def _next_teaching_objectives(axes: list[Mapping[str, Any]], *, limit: int = 2) -> list[str]:
    objectives = _unique_strings([str(axis.get("teaching_objective") or "") for axis in axes])
    if objectives:
        return objectives[:limit]
    return ["下一轮先完整完成一次病史、查体、检查和诊断表达，再根据报告观察可训练能力轴。"]


def _teaching_effect_boundary() -> str:
    return "教学效果观察只来自训练报告、临床思维轨迹和 Skill 应用痕迹；不改变病例事实、rubric、标准诊断或评分裁判，也不把小样本观察写成已证明提升。"


def _skill_state_counts(skill_states: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for state in skill_states.values():
        state_id = str(state.get("state") or "unknown")
        counts[state_id] = counts.get(state_id, 0) + 1
    return counts


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


def _unique_strings(values: Iterable[str]) -> list[str]:
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_values.append(normalized)
    return unique_values


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
