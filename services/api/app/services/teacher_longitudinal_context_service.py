from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.services.admin_display_resolver import rubric_item_labels


TEACHER_LONGITUDINAL_CONTEXT_SCHEMA_VERSION = "teacher_longitudinal_context_v1"
MAX_LONGITUDINAL_REPORTS = 3
MAX_CURRENT_GAPS = 12
MAX_RECOVERED_GAPS = 8
MAX_APPLIED_PERSONAL_SKILLS = 6


def build_teacher_longitudinal_context(
    report_entries: Sequence[Mapping[str, Any]],
    *,
    events_by_session: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build a compact, post-submit teaching history without raw dialogue.

    ``report_entries`` must be ordered newest first. The current report is the
    first item; at most two earlier completed reports are retained. Session IDs
    are used only to join explicit ``training_skill_applied`` events and are not
    copied into the returned provider-safe context.
    """

    recent_entries = [
        entry
        for entry in report_entries
        if isinstance(entry.get("report"), Mapping)
    ][:MAX_LONGITUDINAL_REPORTS]
    if not recent_entries:
        return _empty_longitudinal_context()

    gap_maps = [_active_gap_map(entry) for entry in recent_entries]
    current_gaps = gap_maps[0]
    previous_gaps = gap_maps[1] if len(gap_maps) > 1 else {}
    older_gaps = gap_maps[2] if len(gap_maps) > 2 else {}

    current_gap_statuses: list[dict[str, str]] = []
    for gap_key, gap in current_gaps.items():
        if gap_key in older_gaps and gap_key not in previous_gaps:
            status = "reactivated_after_improvement"
        elif gap_key in previous_gaps:
            status = "repeated"
        else:
            status = "first_seen_current_window"
        current_gap_statuses.append({**gap, "status": status})

    recovered_gaps = [
        {**gap, "status": "recovered_since_previous_report"}
        for gap_key, gap in previous_gaps.items()
        if gap_key not in current_gaps
    ]

    return {
        "schema_version": TEACHER_LONGITUDINAL_CONTEXT_SCHEMA_VERSION,
        "report_window_size": len(recent_entries),
        "score_trend": _score_trend(recent_entries),
        "current_gap_statuses": current_gap_statuses[:MAX_CURRENT_GAPS],
        "recovered_gaps": recovered_gaps[:MAX_RECOVERED_GAPS],
        "gap_status_counts": _gap_status_counts(current_gap_statuses, recovered_gaps),
        "applied_personal_skills": _applied_personal_skills(
            recent_entries,
            events_by_session or {},
        ),
        "evidence_boundary": (
            "仅基于最近三份已完成训练报告与显式 training_skill_applied 事件；"
            "不包含完整对话、学生身份、未披露病例事实，也不证明 Skill 已产生效果。"
        ),
    }


def _empty_longitudinal_context() -> dict[str, Any]:
    return {
        "schema_version": TEACHER_LONGITUDINAL_CONTEXT_SCHEMA_VERSION,
        "report_window_size": 0,
        "score_trend": {
            "order": "oldest_to_newest",
            "direction": "insufficient_history",
            "points": [],
        },
        "current_gap_statuses": [],
        "recovered_gaps": [],
        "gap_status_counts": {
            "first_seen_current_window": 0,
            "repeated": 0,
            "reactivated_after_improvement": 0,
            "recovered_since_previous_report": 0,
        },
        "applied_personal_skills": [],
        "evidence_boundary": (
            "尚无可用的已完成训练报告；不从完整对话或未披露病例事实推断纵向结论。"
        ),
    }


def _active_gap_map(entry: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    report = entry.get("report")
    if not isinstance(report, Mapping):
        return {}
    case_id = str(report.get("case_id") or entry.get("case_id") or "").strip()
    result: dict[str, dict[str, str]] = {}

    raw_missed_items = report.get("missed_items")
    missed_items = raw_missed_items if isinstance(raw_missed_items, list | tuple) else []
    for raw_item_id in missed_items:
        item_id = str(raw_item_id).strip()
        if not item_id:
            continue
        label = _rubric_label(item_id, case_id)
        result[f"rubric:{item_id}"] = {
            "gap_id": item_id,
            "gap_type": "rubric_item",
            "label": label,
        }

    trace = report.get("clinical_reasoning_trace")
    trace_mapping = trace if isinstance(trace, Mapping) else {}
    raw_patterns = trace_mapping.get("cognitive_patterns")
    patterns = raw_patterns if isinstance(raw_patterns, list | tuple) else []
    for pattern in patterns:
        if not isinstance(pattern, Mapping):
            continue
        pattern_id = str(pattern.get("pattern_id") or "").strip()
        if not pattern_id:
            continue
        label = str(pattern.get("label") or pattern_id).strip()
        result[f"reasoning:{pattern_id}"] = {
            "gap_id": pattern_id,
            "gap_type": "reasoning_pattern",
            "label": label,
        }
    return result


def _rubric_label(item_id: str, case_id: str) -> str:
    if not case_id:
        return item_id
    try:
        labels = rubric_item_labels([item_id], [case_id])
    except Exception:
        return item_id
    return str(labels[0]).strip() if labels else item_id


def _score_trend(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    for report_offset, entry in reversed(list(enumerate(entries))):
        report = entry.get("report")
        if not isinstance(report, Mapping):
            continue
        total_score = _number(report.get("total_score"))
        max_score = _number(report.get("max_score"))
        percentage = (
            round(total_score * 100 / max_score, 1)
            if total_score is not None and max_score is not None and max_score > 0
            else None
        )
        point: dict[str, Any] = {
            "report_offset": report_offset,
            "case_id": str(report.get("case_id") or entry.get("case_id") or ""),
        }
        training_difficulty = str(entry.get("training_difficulty") or "").strip()
        if training_difficulty:
            point["training_difficulty"] = training_difficulty
        if total_score is not None:
            point["total_score"] = total_score
        if max_score is not None:
            point["max_score"] = max_score
        if percentage is not None:
            point["score_percent"] = percentage
        points.append(point)

    percentages = [
        float(point["score_percent"])
        for point in points
        if isinstance(point.get("score_percent"), int | float)
    ]
    case_ids = {str(point.get("case_id") or "") for point in points if point.get("case_id")}
    training_difficulties = {
        str(point.get("training_difficulty") or "")
        for point in points
        if point.get("training_difficulty")
    }
    if len(percentages) < 2:
        direction = "insufficient_history"
    elif len(case_ids) > 1 or len(training_difficulties) > 1:
        direction = "mixed_context_not_directly_comparable"
    else:
        delta = percentages[-1] - percentages[0]
        direction = "improving" if delta >= 5 else "declining" if delta <= -5 else "stable"
    return {
        "order": "oldest_to_newest",
        "direction": direction,
        "points": points,
    }


def _gap_status_counts(
    current_gap_statuses: Sequence[Mapping[str, str]],
    recovered_gaps: Sequence[Mapping[str, str]],
) -> dict[str, int]:
    counts = {
        "first_seen_current_window": 0,
        "repeated": 0,
        "reactivated_after_improvement": 0,
        "recovered_since_previous_report": len(recovered_gaps),
    }
    for gap in current_gap_statuses:
        status = str(gap.get("status") or "")
        if status in counts:
            counts[status] += 1
    return counts


def _applied_personal_skills(
    entries: Sequence[Mapping[str, Any]],
    events_by_session: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    for report_offset, entry in enumerate(entries):
        session_id = str(entry.get("session_id") or "").strip()
        if not session_id:
            continue
        for event in events_by_session.get(session_id, []):
            if str(event.get("event_type") or "") != "training_skill_applied":
                continue
            payload = event.get("payload")
            if not isinstance(payload, Mapping):
                continue
            skill_id = str(payload.get("skill_id") or "").strip()
            scope = str(payload.get("scope") or "global").strip()
            if scope != "personal" and not skill_id.startswith("skill_personal_"):
                continue
            title = str(payload.get("title") or "个人训练 Skill").strip()
            skill_type = str(payload.get("skill_type") or "reasoning_bridge").strip()
            dedupe_key = (report_offset, title, skill_type)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            result.append(
                {
                    "report_offset": report_offset,
                    "title": title,
                    "skill_type": skill_type,
                    "effect_status": str(payload.get("effect_status") or "insufficient_samples"),
                    "evidence": "training_skill_applied_event",
                }
            )
            if len(result) >= MAX_APPLIED_PERSONAL_SKILLS:
                return result
    return result


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value


__all__ = [
    "MAX_LONGITUDINAL_REPORTS",
    "TEACHER_LONGITUDINAL_CONTEXT_SCHEMA_VERSION",
    "build_teacher_longitudinal_context",
]
