from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.services.osce_session_store import OsceSessionStore, osce_session_store
from app.services.report_store import ReportStore, report_store

HUMANISTIC_DIMENSIONS = {
    "narrative_medicine",
    "communication_skill",
    "medical_ethics",
    "relationship_building",
}
HUMANISTIC_GAP_PREFIXES = ("narrative_", "communication_", "ethics_", "relationship_")


class AdminLearningAnalyticsService:
    def __init__(
        self,
        *,
        session_store: OsceSessionStore = osce_session_store,
        report_store: ReportStore = report_store,
    ) -> None:
        self.session_store = session_store
        self.report_store = report_store

    def summarize(
        self,
        *,
        session_ids: list[str] | None = None,
        case_id: str = "",
        student_id: str = "",
        limit: int | None = None,
    ) -> dict[str, Any]:
        session_filter = set(session_ids or [])
        sessions = [
            session
            for session in self.session_store.list_session_summaries()
            if (not session_filter or str(session.get("session_id")) in session_filter)
            and (not case_id or str(session.get("case_id")) == case_id)
            and (not student_id or str(session.get("student_id")) == student_id)
        ]
        if limit is not None:
            sessions = sessions[: max(0, limit)]

        reports_by_session_id = {
            str(report.get("session_id")): report
            for report in self.report_store.list_reports()
            if isinstance(report, dict)
        }
        session_payloads = {
            str(session.get("session_id")): self.session_store.get_session_payload(str(session.get("session_id"))) or {}
            for session in sessions
        }
        case_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        student_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for session in sessions:
            normalized_session = dict(session)
            session_id = str(normalized_session.get("session_id") or "")
            normalized_session["report"] = reports_by_session_id.get(session_id)
            normalized_session["payload"] = session_payloads.get(session_id, {})
            case_groups[str(normalized_session.get("case_id") or "")].append(normalized_session)
            student_groups[str(normalized_session.get("student_id") or "")].append(normalized_session)

        case_analytics = [
            _build_case_analytics(case_id_value, grouped_sessions)
            for case_id_value, grouped_sessions in case_groups.items()
            if case_id_value
        ]
        student_analytics = [
            _build_student_analytics(student_id_value, grouped_sessions)
            for student_id_value, grouped_sessions in student_groups.items()
            if student_id_value
        ]

        case_analytics.sort(key=lambda item: (-int(item["report_count"]), -float(item["average_total_score"]), item["case_id"]))
        student_analytics.sort(key=lambda item: (-int(item["report_count"]), -float(item["average_total_score"]), item["student_id"]))
        report_count = sum(1 for session in sessions if isinstance(session_payload_report(session, reports_by_session_id), dict))
        return {
            "summary": {
                "session_count": len(sessions),
                "report_count": report_count,
                "case_count": len(case_analytics),
                "student_count": len(student_analytics),
            },
            "cohort_analytics": _build_cohort_analytics(
                [session for grouped_sessions in case_groups.values() for session in grouped_sessions]
            ),
            "case_analytics": case_analytics,
            "student_analytics": student_analytics,
        }


def session_payload_report(session: dict[str, Any], reports_by_session_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    return reports_by_session_id.get(str(session.get("session_id") or ""))


def _build_cohort_analytics(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    reports = _reports_from_sessions(sessions)
    affect_signals = _affect_signal_summary(sessions)
    frequent_humanistic_gaps = _frequent_humanistic_gaps(reports)
    frequent_missed_opportunities = _frequent_missed_opportunities(reports)
    return {
        "scope": "all_users",
        "scope_label": "全用户",
        "session_count": len(sessions),
        "report_count": len(reports),
        "case_count": len({str(session.get("case_id") or "") for session in sessions if session.get("case_id")}),
        "student_count": len({str(session.get("student_id") or "") for session in sessions if session.get("student_id")}),
        "average_total_score": _average([_float_value(report.get("total_score")) for report in reports]),
        "average_clinical_score": _average([_score_group_value(report, "clinical_osce") for report in reports]),
        "average_humanistic_score": _average([_score_group_value(report, "humanistic_communication") for report in reports]),
        "frequent_missed_items": _frequent_missed_items(reports),
        "frequent_humanistic_gaps": frequent_humanistic_gaps,
        "frequent_missed_opportunities": frequent_missed_opportunities,
        "affect_signals": affect_signals,
        "teaching_actions": _cohort_teaching_actions(frequent_humanistic_gaps, frequent_missed_opportunities, affect_signals),
    }


def _build_case_analytics(case_id: str, sessions: list[dict[str, Any]]) -> dict[str, Any]:
    reports = _reports_from_sessions(sessions)
    affect_signals = _affect_signal_summary(sessions)
    frequent_humanistic_gaps = _frequent_humanistic_gaps(reports)
    frequent_missed_opportunities = _frequent_missed_opportunities(reports)
    return {
        "case_id": case_id,
        "case_title": _first_text(sessions, "case_title") or case_id,
        "session_count": len(sessions),
        "report_count": len(reports),
        "average_total_score": _average([_float_value(report.get("total_score")) for report in reports]),
        "average_clinical_score": _average([_score_group_value(report, "clinical_osce") for report in reports]),
        "average_humanistic_score": _average([_score_group_value(report, "humanistic_communication") for report in reports]),
        "frequent_missed_items": _frequent_missed_items(reports),
        "frequent_humanistic_gaps": frequent_humanistic_gaps,
        "frequent_missed_opportunities": frequent_missed_opportunities,
        "affect_signals": affect_signals,
        "teaching_actions": _case_teaching_actions(frequent_humanistic_gaps, frequent_missed_opportunities, affect_signals),
    }


def _build_student_analytics(student_id: str, sessions: list[dict[str, Any]]) -> dict[str, Any]:
    reports = _reports_from_sessions(sessions)
    frequent_humanistic_gaps = _frequent_humanistic_gaps(reports)
    current_humanistic_gaps = _humanistic_gaps_from_report(reports[0]) if reports else []
    affect_response = _affect_signal_summary(sessions)
    case_titles = sorted({str(session.get("case_title") or session.get("case_id") or "") for session in sessions if session.get("case_id")})
    return {
        "student_id": student_id,
        "session_count": len(sessions),
        "report_count": len(reports),
        "average_total_score": _average([_float_value(report.get("total_score")) for report in reports]),
        "average_clinical_score": _average([_score_group_value(report, "clinical_osce") for report in reports]),
        "average_humanistic_score": _average([_score_group_value(report, "humanistic_communication") for report in reports]),
        "case_titles": case_titles,
        "persistent_gaps": frequent_humanistic_gaps,
        "current_humanistic_gaps": current_humanistic_gaps,
        "affect_response": affect_response,
        "recommended_next_actions": _student_next_actions(current_humanistic_gaps, frequent_humanistic_gaps, affect_response),
    }


def _reports_from_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reports = [session.get("report") for session in sessions]
    return [dict(report) for report in reports if isinstance(report, dict)]


def _frequent_missed_items(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for report in reports:
        for item_id in _string_list(report.get("missed_items")):
            counts[item_id] += 1
    return [
        {"item_id": item_id, "count": count}
        for item_id, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _frequent_humanistic_gaps(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    missing_score_totals: Counter[str] = Counter()
    labels: dict[str, str] = {}
    next_actions: dict[str, str] = {}
    latest_rank: dict[str, int] = {}
    for rank, report in enumerate(reports):
        seen_in_report: set[str] = set()
        for gap in _humanistic_gaps_from_report(report):
            gap_type = str(gap.get("gap_type") or "")
            if not gap_type or gap_type in seen_in_report:
                continue
            seen_in_report.add(gap_type)
            counts[gap_type] += 1
            missing_score_totals[gap_type] += int(_float_value(gap.get("missing_score")))
            labels.setdefault(gap_type, str(gap.get("label") or gap_type))
            if gap.get("next_training_action"):
                next_actions.setdefault(gap_type, str(gap.get("next_training_action")))
            latest_rank.setdefault(gap_type, rank)
    return [
        {
            "gap_type": gap_type,
            "label": labels.get(gap_type, gap_type),
            "count": count,
            "missing_score_total": missing_score_totals[gap_type],
            "next_training_action": next_actions.get(gap_type, ""),
        }
        for gap_type, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], latest_rank.get(item[0], 999), item[0]),
        )
    ]


def _humanistic_gaps_from_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    gaps = [dict(gap) for gap in _mapping_list(report.get("training_gaps")) if _is_humanistic_gap(gap)]
    deep_plan = _mapping(_mapping(report.get("deep_report_analysis")).get("next_training_plan"))
    for gap in _mapping_list(deep_plan.get("linked_training_gaps")):
        if _is_humanistic_gap(gap):
            gaps.append(dict(gap))
    for goal in _mapping_list(deep_plan.get("top_goals")):
        if _is_humanistic_gap(goal):
            gaps.append(dict(goal))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for gap in gaps:
        key = str(gap.get("gap_type") or gap.get("rubric_item_id") or gap.get("label") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(gap)
    return deduped


def _frequent_missed_opportunities(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    expected_responses: dict[str, str] = {}
    for report in reports:
        for missed_opportunity in _mapping_list(report.get("missed_opportunities")):
            gap_type = str(missed_opportunity.get("gap_type") or "missed_opportunity")
            counts[gap_type] += 1
            expected_responses.setdefault(gap_type, str(missed_opportunity.get("expected_response") or ""))
    return [
        {
            "gap_type": gap_type,
            "count": count,
            "expected_response": expected_responses.get(gap_type, ""),
        }
        for gap_type, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _affect_signal_summary(sessions: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for session in sessions:
        for event in _affect_events_from_session(session):
            event_name = str(event.get("event") or "")
            if event_name == "patient_signal_detected":
                counts["signal_count"] += 1
            elif event_name in {"emotion_repaired", "patient_relief_observed"}:
                counts["repaired_count"] += 1
            elif event_name == "emotion_ignored":
                counts["ignored_count"] += 1
    return {
        "signal_count": counts["signal_count"],
        "repaired_count": counts["repaired_count"],
        "ignored_count": counts["ignored_count"],
    }


def _affect_events_from_session(session: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _mapping(session.get("payload"))
    affect_state = _mapping(payload.get("patient_affect_state"))
    events: list[dict[str, Any]] = [dict(item) for item in _mapping_list(affect_state.get("trajectory"))]
    for turn in _mapping_list(payload.get("agent_turn_memory")):
        transition = _mapping(turn.get("patient_affect_transition"))
        if transition:
            events.append(dict(transition))
    for action in _mapping_list(payload.get("action_timeline")):
        metadata = _mapping(action.get("metadata"))
        if metadata:
            events.append(dict(metadata))
    return _dedupe_affect_events(events)


def _dedupe_affect_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        key = (str(event.get("event") or ""), str(event.get("turn_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


def _case_teaching_actions(
    gaps: list[dict[str, Any]],
    missed_opportunities: list[dict[str, Any]],
    affect_signals: dict[str, int],
) -> list[str]:
    actions: list[str] = []
    if gaps and gaps[0].get("next_training_action"):
        actions.append(str(gaps[0]["next_training_action"]))
    elif gaps:
        actions.append(f"围绕「{gaps[0].get('label') or gaps[0].get('gap_type')}」设计下一轮训练。")
    if missed_opportunities:
        actions.append("把反复错失机会加入病例复盘，要求学生说出触发信号和应该回应的话术。")
    if affect_signals.get("ignored_count", 0) > 0:
        actions.append("患者情绪信号被忽略时，教师应观察学生是否先回应情绪再继续推进问诊或查体。")
    return actions[:3]


def _cohort_teaching_actions(
    gaps: list[dict[str, Any]],
    missed_opportunities: list[dict[str, Any]],
    affect_signals: dict[str, int],
) -> list[str]:
    actions: list[str] = []
    if gaps:
        gap_label = str(gaps[0].get("label") or gaps[0].get("gap_type") or "人文沟通缺口")
        gap_action = str(gaps[0].get("next_training_action") or "").strip()
        if gap_action:
            actions.append(f"全用户高频问题集中在「{gap_label}」，下一轮群体训练可采用：{gap_action}")
        else:
            actions.append(f"全用户高频问题集中在「{gap_label}」，建议纳入下一轮群体训练复盘。")
    if missed_opportunities:
        actions.append("全用户反复错失机会需要进入教师共性讲评，要求学生说出触发信号和应答句式。")
    if affect_signals.get("ignored_count", 0) > 0:
        actions.append("全用户训练中出现患者情绪信号被忽略时，应把情绪识别和回应作为班级共性训练目标。")
    if not actions:
        actions.append("全用户暂无稳定高频缺口，继续积累报告后再形成群体教学动作。")
    return actions[:3]


def _student_next_actions(
    current_gaps: list[dict[str, Any]],
    frequent_gaps: list[dict[str, Any]],
    affect_response: dict[str, int],
) -> list[str]:
    actions: list[str] = []
    for gap in [*current_gaps, *frequent_gaps]:
        action = str(gap.get("next_training_action") or "").strip()
        if action and action not in actions:
            actions.append(action)
        if len(actions) >= 2:
            break
    if affect_response.get("ignored_count", 0) > affect_response.get("repaired_count", 0):
        actions.append("下一轮患者表达担忧时，先承认情绪，再继续医学问诊或查体。")
    return actions[:3]


def _score_group_value(report: dict[str, Any], group_id: str) -> float:
    return _float_value(_mapping(_mapping(report.get("score_groups")).get(group_id)).get("score"))


def _is_humanistic_gap(gap: dict[str, Any]) -> bool:
    dimension_id = str(gap.get("dimension_id") or "")
    gap_type = str(gap.get("gap_type") or "")
    return dimension_id in HUMANISTIC_DIMENSIONS or gap_type.startswith(HUMANISTIC_GAP_PREFIXES)


def _first_text(items: list[dict[str, Any]], key: str) -> str:
    for item in items:
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _average(values: list[float]) -> float | int:
    non_zero_values = [value for value in values if value or value == 0]
    if not non_zero_values:
        return 0
    rounded = round(sum(non_zero_values) / len(non_zero_values), 2)
    return int(rounded) if rounded.is_integer() else rounded


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


__all__ = ["AdminLearningAnalyticsService"]
