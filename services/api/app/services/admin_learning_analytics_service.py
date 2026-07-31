from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.services.admin_display_resolver import rubric_item_label
from app.services.osce_session_store import OsceSessionStore, osce_session_store
from app.services.report_score_metrics import aggregate_score_metrics, score_group_metric
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
    frequent_missed_items = _frequent_missed_items(reports)
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
        **_score_analytics_fields(reports),
        "frequent_missed_items": frequent_missed_items,
        "frequent_humanistic_gaps": frequent_humanistic_gaps,
        "frequent_missed_opportunities": frequent_missed_opportunities,
        "affect_signals": affect_signals,
        "teaching_actions": _cohort_teaching_actions(frequent_humanistic_gaps, frequent_missed_opportunities, affect_signals),
        "training_drills": _build_training_drills(
            scope="all_users",
            scope_id="",
            clinical_missed_items=_clinical_missed_items_for_drills(reports, frequent_missed_items),
            gaps=frequent_humanistic_gaps,
            missed_opportunities=frequent_missed_opportunities,
            affect_signals=affect_signals,
        ),
    }


def _build_case_analytics(case_id: str, sessions: list[dict[str, Any]]) -> dict[str, Any]:
    reports = _reports_from_sessions(sessions)
    affect_signals = _affect_signal_summary(sessions)
    frequent_missed_items = _frequent_missed_items(reports)
    frequent_humanistic_gaps = _frequent_humanistic_gaps(reports)
    frequent_missed_opportunities = _frequent_missed_opportunities(reports)
    return {
        "case_id": case_id,
        "case_title": _first_text(sessions, "case_title") or case_id,
        "session_count": len(sessions),
        "report_count": len(reports),
        "average_total_score": _average([_float_value(report.get("total_score")) for report in reports]),
        **_score_analytics_fields(reports),
        "frequent_missed_items": frequent_missed_items,
        "frequent_humanistic_gaps": frequent_humanistic_gaps,
        "frequent_missed_opportunities": frequent_missed_opportunities,
        "affect_signals": affect_signals,
        "teaching_actions": _case_teaching_actions(frequent_humanistic_gaps, frequent_missed_opportunities, affect_signals),
        "training_drills": _build_training_drills(
            scope="case",
            scope_id=case_id,
            clinical_missed_items=_clinical_missed_items_for_drills(reports, frequent_missed_items),
            gaps=frequent_humanistic_gaps,
            missed_opportunities=frequent_missed_opportunities,
            affect_signals=affect_signals,
        ),
    }


def _build_student_analytics(student_id: str, sessions: list[dict[str, Any]]) -> dict[str, Any]:
    reports = _reports_from_sessions(sessions)
    frequent_missed_items = _frequent_missed_items(reports)
    frequent_humanistic_gaps = _frequent_humanistic_gaps(reports)
    persistent_humanistic_gaps = _persistent_humanistic_gaps(frequent_humanistic_gaps)
    current_humanistic_gaps = _humanistic_gaps_from_report(reports[0]) if reports else []
    affect_response = _affect_signal_summary(sessions)
    case_titles = sorted({str(session.get("case_title") or session.get("case_id") or "") for session in sessions if session.get("case_id")})
    return {
        "student_id": student_id,
        "session_count": len(sessions),
        "report_count": len(reports),
        "average_total_score": _average([_float_value(report.get("total_score")) for report in reports]),
        **_score_analytics_fields(reports),
        "case_titles": case_titles,
        "persistent_gaps": persistent_humanistic_gaps,
        "current_humanistic_gaps": current_humanistic_gaps,
        "affect_response": affect_response,
        "recommended_next_actions": _student_next_actions(
            current_humanistic_gaps,
            persistent_humanistic_gaps,
            affect_response,
        ),
        "training_drills": _build_training_drills(
            scope="student",
            scope_id=student_id,
            clinical_missed_items=_clinical_missed_items_for_drills(reports, frequent_missed_items),
            gaps=[*current_humanistic_gaps, *persistent_humanistic_gaps],
            missed_opportunities=[],
            affect_signals=affect_response,
        ),
    }


def _reports_from_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reports = [session.get("report") for session in sessions]
    return [dict(report) for report in reports if isinstance(report, dict)]


def _frequent_missed_items(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for report in reports:
        for item_id in set(_string_list(report.get("missed_items"))):
            counts[item_id] += 1
    return [
        {"item_id": item_id, "count": count}
        for item_id, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _clinical_missed_items_for_drills(
    reports: list[dict[str, Any]],
    frequent_missed_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    case_ids_by_item: dict[str, set[str]] = defaultdict(set)
    for report in reports:
        case_id = str(report.get("case_id") or "").strip()
        for item_id in set(_string_list(report.get("missed_items"))):
            if case_id:
                case_ids_by_item[item_id].add(case_id)
    return [
        {
            **item,
            "item_label": rubric_item_label(
                str(item.get("item_id") or ""),
                sorted(case_ids_by_item.get(str(item.get("item_id") or ""), set())),
            ),
        }
        for item in frequent_missed_items
    ]


def _frequent_humanistic_gaps(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    missing_score_totals: Counter[str] = Counter()
    labels: dict[str, str] = {}
    next_actions: dict[str, str] = {}
    latest_rank: dict[str, int] = {}
    explicitly_persistent: set[str] = set()
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
            if str(gap.get("status") or "").strip().lower() == "persistent":
                explicitly_persistent.add(gap_type)
            latest_rank.setdefault(gap_type, rank)
    return [
        {
            "gap_type": gap_type,
            "label": labels.get(gap_type, gap_type),
            "count": count,
            "missing_score_total": missing_score_totals[gap_type],
            "next_training_action": next_actions.get(gap_type, ""),
            **({"status": "persistent"} if gap_type in explicitly_persistent else {}),
        }
        for gap_type, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], latest_rank.get(item[0], 999), item[0]),
        )
    ]


def _persistent_humanistic_gaps(frequent_gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    persistent_gaps: list[dict[str, Any]] = []
    for gap in frequent_gaps:
        report_count = int(_float_value(gap.get("count")))
        has_explicit_status = str(gap.get("status") or "").strip().lower() == "persistent"
        if report_count < 2 and not has_explicit_status:
            continue
        persistent_gaps.append(
            {
                **gap,
                "status": "persistent",
                "persistence_evidence": "repeated_reports" if report_count >= 2 else "explicit_status",
            }
        )
    return persistent_gaps


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
    gap_index_by_key: dict[str, int] = {}
    for gap in gaps:
        key = str(gap.get("gap_type") or gap.get("rubric_item_id") or gap.get("label") or "")
        if not key:
            continue
        existing_index = gap_index_by_key.get(key)
        if existing_index is None:
            gap_index_by_key[key] = len(deduped)
            deduped.append(gap)
            continue
        existing = deduped[existing_index]
        for field, value in gap.items():
            if value not in (None, "", [], {}) and existing.get(field) in (None, "", [], {}):
                existing[field] = value
        if str(gap.get("status") or "").strip().lower() == "persistent":
            existing["status"] = "persistent"
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


def _build_training_drills(
    *,
    scope: str,
    scope_id: str,
    clinical_missed_items: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    missed_opportunities: list[dict[str, Any]],
    affect_signals: dict[str, int],
) -> list[dict[str, Any]]:
    drills: list[dict[str, Any]] = []
    seen_targets: set[tuple[str, str]] = set()

    for missed_item in clinical_missed_items[:2]:
        _append_unique_drill(
            drills,
            seen_targets,
            _clinical_missed_item_training_drill(
                scope=scope,
                scope_id=scope_id,
                missed_item=missed_item,
            ),
        )

    for gap in gaps:
        drill = _gap_training_drill(scope=scope, scope_id=scope_id, gap=gap)
        if _append_unique_drill(drills, seen_targets, drill) and len(drills) >= 3:
            break

    for missed_opportunity in missed_opportunities:
        drill = _missed_opportunity_training_drill(
            scope=scope,
            scope_id=scope_id,
            missed_opportunity=missed_opportunity,
        )
        _append_unique_drill(drills, seen_targets, drill)

    if affect_signals.get("ignored_count", 0) > 0:
        _append_unique_drill(
            drills,
            seen_targets,
            _affect_response_training_drill(scope=scope, scope_id=scope_id, affect_signals=affect_signals),
        )

    drills.sort(key=lambda item: (-int(item.get("priority") or 0), str(item.get("drill_id") or "")))
    return drills[:4]


def _clinical_missed_item_training_drill(
    *,
    scope: str,
    scope_id: str,
    missed_item: dict[str, Any],
) -> dict[str, Any]:
    item_id = str(missed_item.get("item_id") or "clinical_training_gap")
    label = str(missed_item.get("item_label") or item_id)
    contract = _clinical_training_drill_contract(item_id, label)
    source_count = int(_float_value(missed_item.get("count") or 1))
    return {
        "drill_id": _training_drill_id(scope, scope_id, "clinical", item_id),
        "scope": scope,
        "scope_id": scope_id,
        "source": "clinical_missed_item",
        "priority": source_count * 3 + contract["priority_bonus"],
        "title": f"{label}训练",
        "target_gap_type": item_id,
        "target_label": label,
        "trigger_stage": contract["trigger_stage"],
        "trigger_signal": contract["trigger_signal"],
        "student_action": contract["student_action"],
        "success_signal": contract["success_signal"],
        "source_count": source_count,
    }


def _clinical_training_drill_contract(item_id: str, label: str) -> dict[str, Any]:
    normalized_item_id = item_id.lower()
    if normalized_item_id.startswith(("ht_", "hx_", "history_")):
        return {
            "trigger_stage": "病史采集阶段",
            "trigger_signal": f"进入与「{label}」相关的问诊时",
            "student_action": f"围绕「{label}」完成有目的的追问，并说明答案如何改变下一步判断。",
            "success_signal": "学生获得对应病史证据，并能把证据连到鉴别诊断或后续动作。",
            "priority_bonus": 1,
        }
    if normalized_item_id.startswith("pe_"):
        return {
            "trigger_stage": "查体阶段",
            "trigger_signal": f"根据病史需要查找「{label}」对应体征时",
            "student_action": f"选择并执行与「{label}」对应的重点查体，再说明结果支持或削弱哪个假设。",
            "success_signal": "学生完成目标查体，并把体征结果用于鉴别诊断。",
            "priority_bonus": 2,
        }
    if normalized_item_id.startswith(("at_", "ax_", "lab_", "img_", "test_")):
        return {
            "trigger_stage": "辅助检查阶段",
            "trigger_signal": f"需要用「{label}」回答已明确的临床问题时",
            "student_action": f"申请与「{label}」对应的检查，先说明检查目的和预期影响的判断。",
            "success_signal": "学生能说出检查目的，并根据结果更新主要诊断或鉴别路径。",
            "priority_bonus": 2,
        }
    if normalized_item_id.startswith(("dx_", "dxd_", "diagnosis_")):
        return {
            "trigger_stage": "诊断提交前",
            "trigger_signal": f"整理「{label}」对应的主诊断或鉴别诊断时",
            "student_action": f"补齐「{label}」，并用本轮病史、查体和检查证据说明支持与排除依据。",
            "success_signal": "学生提交的诊断包含关键依据和至少一条有意义的排除路径。",
            "priority_bonus": 3,
        }
    return {
        "trigger_stage": "诊断提交前",
        "trigger_signal": f"需要用已收集证据完成「{label}」时",
        "student_action": f"围绕「{label}」按“结论—支持证据—排除证据—下一步”表达。",
        "success_signal": "学生的结论有本轮真实证据支撑，并表达了排除路径或下一步。",
        "priority_bonus": 4,
    }


def _append_unique_drill(
    drills: list[dict[str, Any]],
    seen_targets: set[tuple[str, str]],
    drill: dict[str, Any],
) -> bool:
    key = (str(drill.get("source") or ""), str(drill.get("target_gap_type") or ""))
    if not key[1] or key in seen_targets:
        return False
    seen_targets.add(key)
    drills.append(drill)
    return True


def _gap_training_drill(*, scope: str, scope_id: str, gap: dict[str, Any]) -> dict[str, Any]:
    gap_type = _gap_identifier(gap)
    label = _training_gap_label(gap)
    contract = _training_drill_contract(gap_type)
    source_count = int(_float_value(gap.get("count") or 1))
    missing_score = int(_float_value(gap.get("missing_score_total") or gap.get("missing_score")))
    student_action = str(gap.get("next_training_action") or contract["student_action"])
    priority = missing_score + source_count * 2 + _training_drill_priority_bonus(gap_type)
    return {
        "drill_id": _training_drill_id(scope, scope_id, "gap", gap_type),
        "scope": scope,
        "scope_id": scope_id,
        "source": "humanistic_gap",
        "priority": priority,
        "title": f"{label}训练",
        "target_gap_type": gap_type,
        "target_label": label,
        "trigger_stage": contract["trigger_stage"],
        "trigger_signal": contract["trigger_signal"],
        "student_action": student_action,
        "success_signal": contract["success_signal"],
        "source_count": source_count,
    }


def _missed_opportunity_training_drill(
    *,
    scope: str,
    scope_id: str,
    missed_opportunity: dict[str, Any],
) -> dict[str, Any]:
    gap_type = str(missed_opportunity.get("gap_type") or "missed_opportunity")
    label = _training_gap_label(missed_opportunity)
    contract = _training_drill_contract(gap_type)
    source_count = int(_float_value(missed_opportunity.get("count") or 1))
    expected_response = str(missed_opportunity.get("expected_response") or contract["student_action"])
    return {
        "drill_id": _training_drill_id(scope, scope_id, "missed", gap_type),
        "scope": scope,
        "scope_id": scope_id,
        "source": "missed_opportunity",
        "priority": source_count * 3 + _training_drill_priority_bonus(gap_type),
        "title": f"{label}错失机会复盘",
        "target_gap_type": gap_type,
        "target_label": label,
        "trigger_stage": contract["trigger_stage"],
        "trigger_signal": contract["trigger_signal"],
        "student_action": expected_response,
        "success_signal": contract["success_signal"],
        "source_count": source_count,
    }


def _affect_response_training_drill(
    *,
    scope: str,
    scope_id: str,
    affect_signals: dict[str, int],
) -> dict[str, Any]:
    ignored_count = int(affect_signals.get("ignored_count", 0))
    signal_count = int(affect_signals.get("signal_count", 0))
    return {
        "drill_id": _training_drill_id(scope, scope_id, "affect", "patient_affect_response_ignored"),
        "scope": scope,
        "scope_id": scope_id,
        "source": "affect_response",
        "priority": ignored_count * 2 + signal_count,
        "title": "患者情绪信号回应训练",
        "target_gap_type": "patient_affect_response_ignored",
        "target_label": "患者情绪信号回应",
        "trigger_stage": "问诊或查体推进前",
        "trigger_signal": "患者表达焦虑、担忧、疼痛、困惑或迟疑",
        "student_action": "先识别并回应患者情绪，再继续医学问诊或查体。",
        "success_signal": "学生能在患者情绪信号后的下一轮先回应情绪，并观察到患者情绪缓解或不再升级。",
        "source_count": ignored_count,
    }


def _training_drill_contract(gap_type: str) -> dict[str, str]:
    if gap_type.startswith("ethics_") or "consent" in gap_type:
        return {
            "trigger_stage": "查体或检查前",
            "trigger_signal": "学生准备进行查体、申请检查或推进可能影响患者自主性的动作",
            "student_action": "说明动作目的、关注隐私和舒适度，并征得患者同意。",
            "success_signal": "学生能在动作前完成目的说明、隐私舒适度说明和同意确认。",
        }
    if gap_type.startswith("relationship_") or "empathy" in gap_type:
        return {
            "trigger_stage": "问诊中",
            "trigger_signal": "患者表达焦虑、担忧、疼痛、困惑或对诊疗不信任",
            "student_action": "先承认患者情绪，表达会一起处理，再继续医学问诊。",
            "success_signal": "学生能先回应情绪，再推进医学问题，患者情绪不再升级。",
        }
    if gap_type.startswith("narrative_") or "perspective" in gap_type:
        return {
            "trigger_stage": "病史采集阶段",
            "trigger_signal": "患者描述症状、生活影响、担心或期待",
            "student_action": "追问患者担忧、期待和生活影响，并复述患者视角。",
            "success_signal": "学生能说出患者最担心什么、症状如何影响生活，以及患者期待。",
        }
    if gap_type.startswith("communication_") or "summary" in gap_type:
        return {
            "trigger_stage": "阶段转换前",
            "trigger_signal": "学生准备结束问诊、转入查体/检查，或患者表示不理解",
            "student_action": "阶段性总结已获得信息，并确认患者理解是否准确。",
            "success_signal": "学生能用简短总结确认理解，再进入下一阶段。",
        }
    return {
        "trigger_stage": "下一轮相关训练阶段",
        "trigger_signal": "再次出现同类训练缺口或患者给出相关信号",
        "student_action": "补齐当前训练缺口，并说明这样做如何影响下一步判断。",
        "success_signal": "学生能在正确阶段补齐动作，并把动作与后续推理连接起来。",
    }


def _training_drill_priority_bonus(gap_type: str) -> int:
    if gap_type.startswith("ethics_") or "consent" in gap_type:
        return 4
    if gap_type.startswith("relationship_") or "empathy" in gap_type:
        return 3
    if gap_type.startswith("communication_"):
        return 2
    if gap_type.startswith("narrative_"):
        return 1
    return 0


def _training_gap_label(gap: dict[str, Any]) -> str:
    label = str(gap.get("label") or "").strip()
    if label:
        return label
    gap_type = _gap_identifier(gap)
    labels = {
        "ethics_consent_missing": "查体/检查前同意",
        "relationship_empathy_missing": "患者情绪回应",
        "narrative_patient_perspective_missing": "患者视角叙事",
        "communication_summary_missing": "阶段性总结确认",
    }
    return labels.get(gap_type, gap_type.replace("_", " ") or "训练缺口")


def _gap_identifier(gap: dict[str, Any]) -> str:
    return str(gap.get("gap_type") or gap.get("item_id") or gap.get("rubric_item_id") or "training_gap")


def _training_drill_id(scope: str, scope_id: str, source: str, target: str) -> str:
    normalized_scope_id = scope_id or "all"
    return f"{scope}:{normalized_scope_id}:{source}:{target}"


def _score_analytics_fields(reports: list[dict[str, Any]]) -> dict[str, Any]:
    clinical_score = aggregate_score_metrics(
        metric
        for report in reports
        if (metric := score_group_metric(report, "clinical_osce")) is not None
    )
    humanistic_score = aggregate_score_metrics(
        metric
        for report in reports
        if (metric := score_group_metric(report, "humanistic_communication")) is not None
    )
    return {
        "average_clinical_score": clinical_score["average_score"],
        "average_humanistic_score": humanistic_score["average_score"],
        "clinical_score": clinical_score,
        "humanistic_score": humanistic_score,
    }


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
