from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.services.clinical_reasoning_trace_service import (
    evidence_chain_focus_from_reports,
    pattern_counts_from_reports,
    sequence_issue_counts_from_reports,
)
from app.services.admin_display_resolver import effect_status_label, rubric_item_label, trigger_item_labels


HUMANISTIC_DIMENSIONS = {
    "narrative_medicine",
    "communication_skill",
    "medical_ethics",
    "relationship_building",
}

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
    "ethics_consent_missing": "查体/检查前同意缺失",
    "ethics_privacy_comfort_missing": "隐私与舒适度说明缺失",
    "ethics_autonomy_missing": "尊重患者自主表达不足",
    "relationship_empathy_missing": "患者情绪回应缺失",
}


def build_skill_profile_summary(
    *,
    reports: Iterable[Mapping[str, Any]],
    enabled_skills: Iterable[Mapping[str, Any]],
    recent_error_limit: int = 8,
    current_focus_limit: int = 3,
) -> dict[str, Any]:
    report_list = list(reports)
    recent_error_items = _recent_error_items(report_list, limit=recent_error_limit)
    all_training_gaps = _recent_training_gaps(report_list, limit=None)
    recent_training_gaps = all_training_gaps[:recent_error_limit]
    active_training_gaps = [
        gap
        for gap in all_training_gaps
        if gap["latest_present"] and gap["status"] in {"current", "persistent"}
    ]
    current_training_gaps = active_training_gaps[:current_focus_limit]
    current_humanistic_gaps = [
        gap for gap in current_training_gaps if gap["is_humanistic"]
    ][:current_focus_limit]
    recent_training_gap_types = [gap["gap_type"] for gap in recent_training_gaps]
    recent_training_skill_types = _unique_strings(
        [gap["skill_type"] for gap in recent_training_gaps if gap["skill_type"]]
    )
    recent_error_item_ids = [item["item_id"] for item in recent_error_items]
    current_focus_items = _current_focus_items(
        recent_error_items,
        active_training_gaps,
        limit=current_focus_limit,
    )
    current_focus_item_ids = [item["item_id"] for item in current_focus_items]
    recent_error_set = set(recent_error_item_ids)
    recent_error_item_by_id = {item["item_id"]: item for item in recent_error_items}
    recent_training_gap_type_set = set(recent_training_gap_types)
    recent_training_gap_by_type = {gap["gap_type"]: gap for gap in recent_training_gaps}
    recent_training_skill_type_set = set(recent_training_skill_types)
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
            recent_training_gap_types,
            recent_training_gap_type_set,
            recent_training_gap_by_type,
            recent_training_skill_type_set,
            report_list,
        )
        for skill in enabled_skills
        if str(skill.get("skill_id", "")).strip()
    }
    return {
        "recent_error_item_ids": recent_error_item_ids,
        "recent_error_items": recent_error_items,
        "current_focus_item_ids": current_focus_item_ids,
        "current_focus_items": current_focus_items,
        "recent_training_gap_types": recent_training_gap_types,
        "recent_training_skill_types": recent_training_skill_types,
        "recent_training_gaps": recent_training_gaps,
        "current_training_gaps": current_training_gaps,
        "current_humanistic_gaps": current_humanistic_gaps,
        "humanistic_gap_summary": _humanistic_gap_summary(recent_training_gaps, current_humanistic_gaps),
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
        axis_id = str(axis.get("axis_id") or "")
        axis_label = str(axis.get("axis_label") or _axis_definition(axis_id)["label"])
        latest_count = int(axis.get("latest_count") or 0)
        historical_count = int(axis.get("historical_count") or 0)
        objective = str(axis.get("teaching_objective") or _axis_definition(axis_id)["objective"])
        signal_text = _observed_signal_text(axis)
        if state == "improving_signal":
            changes.append(
                {
                    "axis_id": axis_id,
                    "axis_label": axis_label,
                    "direction": "improved_recently",
                    "description": (
                        f"最新报告暂未再出现{axis_label}相关信号，历史累计 {historical_count} 个；"
                        f"后续病例仍要验证是否能保持：{objective}{signal_text}"
                    ),
                }
            )
        elif state == "persistent_gap":
            changes.append(
                {
                    "axis_id": axis_id,
                    "axis_label": axis_label,
                    "direction": "needs_practice",
                    "description": (
                        f"{axis_label}在最新报告仍出现 {latest_count} 个信号，历史累计 {historical_count} 个，"
                        f"属于反复问题；下一轮重点：{objective}{signal_text}"
                    ),
                }
            )
        elif state == "emerging_gap":
            changes.append(
                {
                    "axis_id": axis_id,
                    "axis_label": axis_label,
                    "direction": "needs_practice",
                    "description": (
                        f"{axis_label}是最新报告新暴露的问题，出现 {latest_count} 个信号；"
                        f"下一轮先按这个目标拆小练习：{objective}{signal_text}"
                    ),
                }
            )
    return changes


def _observed_signal_text(axis: Mapping[str, Any], *, limit: int = 2) -> str:
    labels = _unique_strings([str(label) for label in axis.get("labels", []) if str(label).strip()])
    if not labels:
        return ""
    return f" 重点信号：{'、'.join(labels[:limit])}。"


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


def _current_focus_items(
    recent_error_items: Iterable[Mapping[str, Any]],
    active_training_gaps: Iterable[Mapping[str, Any]],
    *,
    limit: int,
) -> list[dict[str, str]]:
    active_item_ids = {
        str(gap.get("rubric_item_id") or "").strip()
        for gap in active_training_gaps
        if bool(gap.get("latest_present")) and str(gap.get("status") or "") in {"current", "persistent"}
    }
    current_items: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in recent_error_items:
        item_id = str(item.get("item_id") or "").strip()
        if not item_id or item_id not in active_item_ids or item_id in seen:
            continue
        seen.add(item_id)
        current_items.append(
            {
                "item_id": item_id,
                "label": str(item.get("label") or "").strip() or rubric_item_label(item_id, ()),
            }
        )
        if len(current_items) >= limit:
            break
    return current_items


def _recent_training_gaps(
    reports: Iterable[Mapping[str, Any]],
    *,
    limit: int | None,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    report_list = list(reports)
    for report_index, report in enumerate(report_list):
        case_id = str(report.get("case_id", "")).strip()
        report_id = str(report.get("report_id") or report.get("session_id") or "").strip()
        for gap in _report_training_gaps(report):
            gap_type = str(gap.get("gap_type") or "").strip()
            rubric_item_id = str(gap.get("rubric_item_id") or "").strip()
            key = gap_type or rubric_item_id
            if not key:
                continue
            label = _gap_label(gap, case_id)
            entry = grouped.setdefault(
                key,
                {
                    "gap_type": gap_type or key,
                    "rubric_item_id": rubric_item_id,
                    "label": label,
                    "dimension_id": str(gap.get("dimension_id") or ""),
                    "skill_type": str(gap.get("skill_type") or ""),
                    "gap_source": str(gap.get("gap_source") or "score_trace"),
                    "severity": str(gap.get("severity") or "medium"),
                    "trigger_stage": str(gap.get("stage") or gap.get("trigger_stage") or ""),
                    "next_training_action": str(gap.get("next_training_action") or ""),
                    "evidence_summary": str(gap.get("evidence_summary") or ""),
                    "missing_score": 0,
                    "priority_floor": 0,
                    "repeat_count": 0,
                    "latest_present": False,
                    "latest_report_index": report_index,
                    "source_report_ids": [],
                    "is_humanistic": _is_humanistic_gap(gap),
                },
            )
            entry["repeat_count"] = int(entry["repeat_count"]) + 1
            entry["missing_score"] = max(int(entry["missing_score"]), _int_value(gap.get("missing_score")))
            entry["priority_floor"] = max(int(entry["priority_floor"]), _int_value(gap.get("priority")))
            entry["is_humanistic"] = bool(entry["is_humanistic"]) or _is_humanistic_gap(gap)
            if report_index == 0:
                entry["latest_present"] = True
            entry["latest_report_index"] = min(int(entry["latest_report_index"]), report_index)
            if report_id and report_id not in entry["source_report_ids"]:
                entry["source_report_ids"].append(report_id)
            if not entry["next_training_action"]:
                entry["next_training_action"] = str(gap.get("next_training_action") or "")
            if not entry["trigger_stage"]:
                entry["trigger_stage"] = str(gap.get("stage") or gap.get("trigger_stage") or "")

    gaps = [_finalize_training_gap(entry) for entry in grouped.values()]
    gaps.sort(key=lambda item: (-int(item["priority"]), int(item["latest_report_index"]), item["label"]))
    return gaps if limit is None else gaps[:limit]


def _report_training_gaps(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    gaps_by_key: dict[str, dict[str, Any]] = {}

    gaps = report.get("training_gaps", [])
    if isinstance(gaps, list):
        for gap in gaps:
            if isinstance(gap, Mapping):
                _merge_report_training_gap(gaps_by_key, gap)

    deep_report_analysis = report.get("deep_report_analysis")
    if isinstance(deep_report_analysis, Mapping):
        next_training_plan = deep_report_analysis.get("next_training_plan")
        if isinstance(next_training_plan, Mapping):
            top_goals = _top_goals_by_gap_type(next_training_plan.get("top_goals"))
            linked_gaps = next_training_plan.get("linked_training_gaps", [])
            if isinstance(linked_gaps, list):
                for gap in linked_gaps:
                    if not isinstance(gap, Mapping):
                        continue
                    gap_type = str(gap.get("gap_type") or "").strip()
                    _merge_report_training_gap(
                        gaps_by_key,
                        gap,
                        top_goal=top_goals.get(gap_type, {}),
                    )
            for goal in top_goals.values():
                _merge_report_training_gap(gaps_by_key, goal, gap_source="deep_report_next_training_plan")

    return list(gaps_by_key.values())


def _merge_report_training_gap(
    gaps_by_key: dict[str, dict[str, Any]],
    gap: Mapping[str, Any],
    *,
    top_goal: Mapping[str, Any] | None = None,
    gap_source: str = "",
) -> None:
    gap_type = str(gap.get("gap_type") or "").strip()
    rubric_item_id = str(gap.get("rubric_item_id") or "").strip()
    key = gap_type or rubric_item_id
    if not key:
        return
    top_goal = top_goal or {}
    incoming = dict(gap)
    if top_goal:
        for field_name in (
            "label",
            "dimension_id",
            "severity",
            "next_training_action",
            "success_signal",
            "skill_type",
            "gap_source",
        ):
            if not str(incoming.get(field_name) or "").strip() and str(top_goal.get(field_name) or "").strip():
                incoming[field_name] = top_goal[field_name]
        if not str(incoming.get("trigger_stage") or incoming.get("stage") or "").strip():
            incoming["trigger_stage"] = top_goal.get("trigger_stage") or top_goal.get("stage")
        incoming["priority"] = max(_int_value(incoming.get("priority")), _int_value(top_goal.get("priority")))
    if gap_source and not str(incoming.get("gap_source") or "").strip():
        incoming["gap_source"] = gap_source
    if not str(incoming.get("gap_source") or "").strip():
        incoming["gap_source"] = "score_trace"

    existing = gaps_by_key.get(key)
    if existing is None:
        gaps_by_key[key] = incoming
        return
    for field_name, field_value in incoming.items():
        if field_name in {"missing_score", "priority"}:
            existing[field_name] = max(_int_value(existing.get(field_name)), _int_value(field_value))
            continue
        if not str(existing.get(field_name) or "").strip() and str(field_value or "").strip():
            existing[field_name] = field_value


def _top_goals_by_gap_type(value: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        return {}
    goals: dict[str, Mapping[str, Any]] = {}
    for goal in value:
        if not isinstance(goal, Mapping):
            continue
        gap_type = str(goal.get("gap_type") or "").strip()
        if not gap_type:
            continue
        current = goals.get(gap_type)
        if current is None or _int_value(goal.get("priority")) > _int_value(current.get("priority")):
            goals[gap_type] = goal
    return goals


def _finalize_training_gap(entry: Mapping[str, Any]) -> dict[str, Any]:
    missing_score = int(entry.get("missing_score") or 0)
    repeat_count = int(entry.get("repeat_count") or 0)
    gap_source = str(entry.get("gap_source") or "")
    skill_type = str(entry.get("skill_type") or "")
    dimension_id = str(entry.get("dimension_id") or "")
    latest_present = bool(entry.get("latest_present"))
    ethics_or_safety_bonus = 3 if (
        dimension_id == "medical_ethics"
        or skill_type == "ethics_consent"
        or "ethics" in str(entry.get("gap_type") or "")
        or "safety" in str(entry.get("gap_type") or "")
    ) else 0
    missed_opportunity_bonus = 3 if gap_source == "missed_opportunity" else 0
    recent_recovery_bonus = 4 if not latest_present else 0
    priority = max(
        missing_score + repeat_count * 2 + ethics_or_safety_bonus + missed_opportunity_bonus - recent_recovery_bonus,
        _int_value(entry.get("priority_floor")),
    )
    status = "persistent" if latest_present and repeat_count >= 2 else "current" if latest_present else "recovered"
    trigger_stage = str(entry.get("trigger_stage") or "")
    gap_type = str(entry.get("gap_type") or "")
    return {
        "gap_type": gap_type,
        "rubric_item_id": str(entry.get("rubric_item_id") or ""),
        "label": str(entry.get("label") or _gap_type_label(gap_type)),
        "dimension_id": dimension_id,
        "skill_type": skill_type,
        "gap_source": gap_source,
        "severity": str(entry.get("severity") or "medium"),
        "trigger_stage": trigger_stage,
        "trigger_stage_label": _stage_label(trigger_stage),
        "next_training_action": str(entry.get("next_training_action") or "下一轮围绕该缺口做一次短目标训练。"),
        "success_signal": _success_signal_for_gap(gap_type),
        "evidence_summary": str(entry.get("evidence_summary") or ""),
        "missing_score": missing_score,
        "repeat_count": repeat_count,
        "latest_present": latest_present,
        "priority": priority,
        "status": status,
        "status_label": {"persistent": "反复出现", "current": "当前缺口", "recovered": "近期恢复"}.get(status, "待观察"),
        "source_report_ids": list(entry.get("source_report_ids") or []),
        "latest_report_index": int(entry.get("latest_report_index") or 0),
        "is_humanistic": bool(entry.get("is_humanistic")),
        "priority_components": {
            "missing_score": missing_score,
            "repeat_bonus": repeat_count * 2,
            "ethics_or_safety_bonus": ethics_or_safety_bonus,
            "missed_opportunity_bonus": missed_opportunity_bonus,
            "recent_recovery_bonus": recent_recovery_bonus,
        },
    }


def _gap_label(gap: Mapping[str, Any], case_id: str) -> str:
    label = str(gap.get("label") or "").strip()
    if label:
        return label
    rubric_item_id = str(gap.get("rubric_item_id") or "").strip()
    if rubric_item_id:
        return rubric_item_label(rubric_item_id, [case_id] if case_id else ())
    return _gap_type_label(str(gap.get("gap_type") or ""))


def _gap_type_label(gap_type: str) -> str:
    return GAP_TYPE_LABELS.get(str(gap_type or ""), str(gap_type or "") or "未记录训练缺口")


def _stage_label(stage: str) -> str:
    return {
        "case_intro": "训练开始",
        "history_taking": "问诊阶段",
        "physical_exam": "查体阶段",
        "auxiliary_test": "辅助检查阶段",
        "auxiliary_testing": "辅助检查阶段",
        "diagnosis_submission": "诊断提交前",
        "feedback": "复盘阶段",
    }.get(str(stage or ""), str(stage or "") or "未记录阶段")


def _success_signal_for_gap(gap_type: str) -> str:
    return {
        "narrative_patient_perspective_missing": "问诊中主动询问患者担忧、期待或生活影响。",
        "communication_summary_missing": "阶段转换前总结已获得信息并请患者确认。",
        "communication_confirm_understanding_missing": "解释判断或检查目的后确认患者是否理解。",
        "ethics_consent_missing": "查体或检查前先说明目的并征得同意。",
        "ethics_privacy_comfort_missing": "查体前主动说明隐私保护和不适反馈方式。",
        "ethics_autonomy_missing": "说明选择理由后邀请患者表达顾虑并共同决定。",
        "relationship_empathy_missing": "患者表达焦虑或担忧后，先回应情绪再继续推进。",
    }.get(str(gap_type or ""), "下一轮能在对应阶段主动补齐该训练动作。")


def _humanistic_gap_summary(
    recent_training_gaps: list[Mapping[str, Any]],
    current_humanistic_gaps: list[Mapping[str, Any]],
) -> dict[str, Any]:
    humanistic_gaps = [gap for gap in recent_training_gaps if gap.get("is_humanistic")]
    return {
        "recent_count": len(humanistic_gaps),
        "current_count": len(current_humanistic_gaps),
        "top_gap_type": str(current_humanistic_gaps[0].get("gap_type") or "") if current_humanistic_gaps else "",
        "top_next_training_action": str(current_humanistic_gaps[0].get("next_training_action") or "") if current_humanistic_gaps else "",
    }


def _is_humanistic_gap(gap: Mapping[str, Any]) -> bool:
    dimension_id = str(gap.get("dimension_id") or "")
    skill_type = str(gap.get("skill_type") or "")
    gap_type = str(gap.get("gap_type") or "")
    return (
        dimension_id in HUMANISTIC_DIMENSIONS
        or skill_type in HUMANISTIC_SKILL_TYPES
        or gap_type.startswith(("narrative_", "communication_", "ethics_", "relationship_"))
    )


def _int_value(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _skill_state(
    skill: Mapping[str, Any],
    recent_error_item_ids: list[str],
    recent_error_set: set[str],
    recent_error_item_by_id: Mapping[str, Mapping[str, str]],
    recent_reasoning_pattern_ids: list[str],
    recent_reasoning_pattern_set: set[str],
    recent_reasoning_pattern_by_id: Mapping[str, Mapping[str, Any]],
    recent_training_gap_types: list[str],
    recent_training_gap_type_set: set[str],
    recent_training_gap_by_type: Mapping[str, Mapping[str, Any]],
    recent_training_skill_type_set: set[str],
    reports: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    trigger_item_ids = _trigger_item_ids(skill)
    trigger_gap_types = _trigger_gap_types(skill)
    skill_type = str(skill.get("skill_type") or "").strip()
    matched_recent_error_item_ids = [item_id for item_id in recent_error_item_ids if item_id in set(trigger_item_ids)]
    matched_recent_error_items = [
        {
            "item_id": item_id,
            "label": str(recent_error_item_by_id.get(item_id, {}).get("label") or item_id),
        }
        for item_id in matched_recent_error_item_ids
    ]
    matched_recent_training_gap_types = [
        gap_type for gap_type in recent_training_gap_types if gap_type in set(trigger_gap_types)
    ]
    matched_recent_training_gaps = [
        {
            "gap_type": gap_type,
            "label": str(recent_training_gap_by_type.get(gap_type, {}).get("label") or _gap_type_label(gap_type)),
        }
        for gap_type in matched_recent_training_gap_types
    ]
    matched_recent_training_skill_types = (
        [skill_type]
        if skill_type in HUMANISTIC_SKILL_TYPES and skill_type in recent_training_skill_type_set
        else []
    )
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
        matched_recent_training_gap_types=matched_recent_training_gap_types,
        trigger_gap_types=trigger_gap_types,
        matched_recent_training_skill_types=matched_recent_training_skill_types,
        skill_type=skill_type,
    )
    priority = _priority_for_skill(
        skill,
        state=state,
        matched_recent_error_item_ids=matched_recent_error_item_ids,
        matched_recent_reasoning_pattern_ids=matched_recent_reasoning_pattern_ids,
        matched_recent_training_gap_types=matched_recent_training_gap_types,
        matched_recent_training_skill_types=matched_recent_training_skill_types,
        recent_error_set=recent_error_set,
        recent_reasoning_pattern_set=recent_reasoning_pattern_set,
        recent_training_gap_type_set=recent_training_gap_type_set,
        recent_training_skill_type_set=recent_training_skill_type_set,
    )
    return {
        "state": state,
        "state_label": _state_label(state),
        "priority": priority,
        "trigger_item_ids": trigger_item_ids,
        "trigger_item_labels": trigger_item_labels(trigger_item_ids, _case_ids(skill)),
        "trigger_gap_types": trigger_gap_types,
        "matched_recent_training_gap_types": matched_recent_training_gap_types,
        "matched_recent_training_gaps": matched_recent_training_gaps,
        "matched_recent_training_skill_types": matched_recent_training_skill_types,
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
            matched_recent_training_gaps=matched_recent_training_gaps,
            matched_recent_training_skill_types=matched_recent_training_skill_types,
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


def _trigger_gap_types(skill: Mapping[str, Any]) -> list[str]:
    gap_types = _normalized_string_list(skill.get("trigger_gap_types"))
    if gap_types:
        return gap_types
    gap_types = _normalized_string_list(skill.get("gap_types"))
    if gap_types:
        return gap_types
    applies_when = skill.get("applies_when")
    if isinstance(applies_when, Mapping):
        return _normalized_string_list(applies_when.get("gap_types") or applies_when.get("trigger_gap_types"))
    return []


def _state_for_skill(
    effect_status: str,
    matched_recent_error_item_ids: list[str],
    trigger_item_ids: list[str],
    reports: list[Mapping[str, Any]],
    skill: Mapping[str, Any],
    *,
    matched_recent_reasoning_pattern_ids: list[str],
    reasoning_pattern_ids: list[str],
    matched_recent_training_gap_types: list[str],
    trigger_gap_types: list[str],
    matched_recent_training_skill_types: list[str],
    skill_type: str,
) -> str:
    if not trigger_item_ids and not reasoning_pattern_ids and not trigger_gap_types and not skill_type:
        return "inactive"
    lifecycle_state = _lifecycle_state_from_reports(
        trigger_item_ids,
        reports,
        skill,
        trigger_gap_types=trigger_gap_types,
        skill_type=skill_type if skill_type in HUMANISTIC_SKILL_TYPES else "",
    )
    if lifecycle_state:
        return lifecycle_state
    if (
        matched_recent_error_item_ids
        or matched_recent_reasoning_pattern_ids
        or matched_recent_training_gap_types
        or matched_recent_training_skill_types
    ):
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
    matched_recent_training_gaps: list[dict[str, str]] | None = None,
    matched_recent_training_skill_types: list[str] | None = None,
) -> str:
    matched_recent_reasoning_patterns = matched_recent_reasoning_patterns or []
    matched_recent_training_gaps = matched_recent_training_gaps or []
    matched_recent_training_skill_types = matched_recent_training_skill_types or []
    if state == "cooldown":
        return "近期已补上该 Skill 训练点，暂进入冷却观察。"
    if state == "retired":
        return "近期连续覆盖该 Skill 训练点，默认不再进入本轮提示。"
    if state == "reactivated" and matched_recent_error_items:
        labels = [item["label"] for item in matched_recent_error_items[:3]]
        return f"近期又出现该 Skill 相关缺口：{'、'.join(labels)}。"
    if matched_recent_training_gaps:
        labels = [item["label"] for item in matched_recent_training_gaps[:3]]
        return f"近期训练缺口命中：{'、'.join(labels)}。"
    if matched_recent_training_skill_types:
        labels = [_skill_type_label(skill_type) for skill_type in matched_recent_training_skill_types[:3]]
        return f"近期人文沟通 Skill 类型命中：{'、'.join(labels)}。"
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
    matched_recent_training_gap_types: list[str],
    matched_recent_training_skill_types: list[str],
    recent_error_set: set[str],
    recent_reasoning_pattern_set: set[str],
    recent_training_gap_type_set: set[str],
    recent_training_skill_type_set: set[str],
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
    if matched_recent_training_gap_types:
        priority += 8
    if matched_recent_training_skill_types:
        priority += 6
    if set(_trigger_item_ids(skill)) & recent_error_set:
        priority += min(int(skill.get("support_count") or 0), 3)
    if set(_reasoning_pattern_ids(skill)) & recent_reasoning_pattern_set:
        priority += min(int(skill.get("support_count") or 0), 3)
    if set(_trigger_gap_types(skill)) & recent_training_gap_type_set:
        priority += min(int(skill.get("support_count") or 0), 3)
    skill_type = str(skill.get("skill_type") or "").strip()
    if skill_type in HUMANISTIC_SKILL_TYPES and skill_type in recent_training_skill_type_set:
        priority += min(int(skill.get("support_count") or 0), 3)
    return priority


def _lifecycle_state_from_reports(
    trigger_item_ids: list[str],
    reports: list[Mapping[str, Any]],
    skill: Mapping[str, Any],
    *,
    trigger_gap_types: list[str] | None = None,
    skill_type: str = "",
    stable_coverage_window: int = 3,
) -> str:
    relevant_reports = [
        report for report in reports if _report_relevant_to_skill(report, skill)
    ]
    if not relevant_reports:
        return ""
    recent_reports = relevant_reports[:stable_coverage_window]
    latest_report = relevant_reports[0]
    if _report_matches_skill_gap(latest_report, trigger_item_ids, trigger_gap_types or [], skill_type):
        previous_stable_reports = relevant_reports[1 : stable_coverage_window + 1]
        older_reports = relevant_reports[stable_coverage_window + 1 :]
        if (
            len(previous_stable_reports) >= stable_coverage_window
            and all(not _report_matches_skill_gap(report, trigger_item_ids, trigger_gap_types or [], skill_type) for report in previous_stable_reports)
            and any(_report_matches_skill_gap(report, trigger_item_ids, trigger_gap_types or [], skill_type) for report in older_reports)
        ):
            return "reactivated"
        return "active"
    historical_miss_count = sum(
        1 for report in relevant_reports if _report_matches_skill_gap(report, trigger_item_ids, trigger_gap_types or [], skill_type)
    )
    if historical_miss_count == 0:
        return ""
    if len(recent_reports) >= stable_coverage_window and all(
        not _report_matches_skill_gap(report, trigger_item_ids, trigger_gap_types or [], skill_type) for report in recent_reports
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


def _report_matches_skill_gap(
    report: Mapping[str, Any],
    trigger_item_ids: list[str],
    trigger_gap_types: list[str],
    skill_type: str,
) -> bool:
    if trigger_item_ids and _report_misses_any(report, trigger_item_ids):
        return True
    gaps = _report_training_gaps(report)
    if not gaps:
        return False
    if trigger_gap_types:
        gap_type_set = {str(gap.get("gap_type") or "").strip() for gap in gaps}
        if set(trigger_gap_types) & gap_type_set:
            return True
    if skill_type:
        return any(str(gap.get("skill_type") or "").strip() == skill_type for gap in gaps)
    return False


def _skill_type_label(skill_type: str) -> str:
    return {
        "narrative_perspective": "患者叙事与视角训练",
        "communication_structure": "沟通结构训练",
        "ethics_consent": "知情同意训练",
        "relationship_repair": "医患关系修复训练",
    }.get(str(skill_type or ""), str(skill_type or "") or "未分类 Skill")


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
