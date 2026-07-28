from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.services.admin_display_resolver import (
    enrich_training_insight_learning_recommendation,
    enrich_training_insight_missed_item,
    enrich_training_insight_source_reference,
    enrich_training_insight_turn_pattern,
)
from app.services.training_event_store import TrainingEventStore, training_event_store
from app.services.training_report_event_normalizer import (
    normalize_report_events_by_session,
    unique_session_ids,
)

HUMANISTIC_DIMENSION_LABELS = {
    "narrative_medicine": "叙事医学",
    "communication_skill": "沟通技巧",
    "medical_ethics": "医学伦理",
    "relationship_building": "关系建立",
}
HUMANISTIC_DIMENSION_ORDER = {
    dimension_id: index
    for index, dimension_id in enumerate(HUMANISTIC_DIMENSION_LABELS)
}
HUMANISTIC_SKILL_TYPES = {
    "narrative_perspective",
    "communication_structure",
    "ethics_consent",
    "relationship_repair",
}


class TrainingInsightService:
    def __init__(self, event_store: TrainingEventStore = training_event_store) -> None:
        self.event_store = event_store

    def summarize_sessions(self, session_ids: list[str]) -> dict[str, Any]:
        missed_item_counts: Counter[str] = Counter()
        missed_item_case_ids: dict[str, set[str]] = defaultdict(set)
        recommendation_counts: Counter[str] = Counter()
        recommendation_titles: dict[str, str] = {}
        source_reference_counts: Counter[str] = Counter()
        source_reference_case_ids: dict[str, set[str]] = defaultdict(set)
        source_reference_types: dict[str, str] = {}
        source_reference_titles: dict[str, str] = {}
        source_reference_metadata: dict[str, dict[str, Any]] = {}
        turn_pattern_counts: Counter[str] = Counter()
        turn_pattern_types: dict[str, str] = {}
        turn_pattern_titles: dict[str, str] = {}
        turn_pattern_trigger_item_ids: dict[str, list[str]] = {}
        turn_pattern_case_ids: dict[str, set[str]] = defaultdict(set)
        turn_pattern_session_ids: dict[str, set[str]] = defaultdict(set)
        turn_pattern_source_report_ids: dict[str, set[str]] = defaultdict(set)
        humanistic_reports: list[dict[str, Any]] = []
        report_count = 0

        normalized_session_ids = unique_session_ids(session_ids)
        events_by_session = normalize_report_events_by_session(
            normalized_session_ids,
            _list_events_by_session(self.event_store, normalized_session_ids),
        )
        for session_id in normalized_session_ids:
            events = events_by_session.get(session_id, [])
            session_report_ids = [
                str(event["payload"].get("report_id"))
                for event in events
                if event["event_type"] == "report_generated" and event["payload"].get("report_id")
            ]
            history_fact_disclosure_count = 0
            physical_exam_request_count = 0
            for event in events:
                if event["event_type"] != "report_generated":
                    for pattern in _turn_patterns_from_training_event(
                        event,
                        history_fact_disclosure_count,
                        physical_exam_request_count,
                    ):
                        pattern_id = pattern["pattern_id"]
                        turn_pattern_counts[pattern_id] += 1
                        turn_pattern_types[pattern_id] = pattern["pattern_type"]
                        turn_pattern_titles[pattern_id] = pattern["title"]
                        turn_pattern_trigger_item_ids[pattern_id] = list(pattern["trigger_item_ids"])
                        turn_pattern_case_ids[pattern_id].add(event["case_id"])
                        turn_pattern_session_ids[pattern_id].add(event["session_id"])
                        turn_pattern_source_report_ids[pattern_id].update(session_report_ids)
                    agent_turn = event["payload"].get("agent_turn")
                    if isinstance(agent_turn, dict) and agent_turn.get("turn_policy") == "history_fact_disclosure":
                        history_fact_disclosure_count += 1
                    if event["event_type"] == "physical_exam_requested":
                        physical_exam_request_count += 1
                    continue
                report_count += 1
                payload = event["payload"]
                case_id = event["case_id"]
                if _has_humanistic_payload(payload):
                    humanistic_reports.append(payload)
                for item_id in payload.get("missed_items", []):
                    missed_item_counts[item_id] += 1
                    missed_item_case_ids[item_id].add(case_id)
                for recommendation in payload.get("knowledge_recommendations", []):
                    reference = recommendation["reference"]
                    if reference.startswith("case:"):
                        continue
                    recommendation_counts[reference] += 1
                    recommendation_titles[reference] = recommendation["title"]
                for source_reference_item in payload.get("source_reference_items", []):
                    reference = source_reference_item["reference"]
                    source_reference_counts[reference] += 1
                    source_reference_case_ids[reference].add(case_id)
                    source_reference_types[reference] = source_reference_item["source_type"]
                    source_reference_titles[reference] = source_reference_item["title"]
                    source_reference_metadata[reference] = source_reference_item.get("metadata", {})

        return {
            "session_count": len(normalized_session_ids),
            "report_count": report_count,
            "frequent_missed_items": [
                enrich_training_insight_missed_item(
                    {
                        "item_id": item_id,
                        "count": count,
                        "case_ids": sorted(missed_item_case_ids[item_id]),
                    }
                )
                for item_id, count in sorted(missed_item_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "frequent_learning_recommendations": [
                enrich_training_insight_learning_recommendation(
                    {
                        "reference": reference,
                        "title": recommendation_titles[reference],
                        "count": count,
                    }
                )
                for reference, count in sorted(
                    recommendation_counts.items(),
                    key=lambda item: (-item[1], _recommendation_kind_rank(item[0]), item[0]),
                )
            ],
            "frequent_source_references": [
                enrich_training_insight_source_reference(
                    {
                        "reference": reference,
                        "source_type": source_reference_types[reference],
                        "title": source_reference_titles[reference],
                        "count": count,
                        "case_ids": sorted(source_reference_case_ids[reference]),
                        "metadata": source_reference_metadata[reference],
                    }
                )
                for reference, count in sorted(
                    source_reference_counts.items(),
                    key=lambda item: (-item[1], _source_reference_kind_rank(item[0]), item[0]),
                )
            ],
            "frequent_turn_patterns": [
                enrich_training_insight_turn_pattern(
                    {
                        "pattern_id": pattern_id,
                        "pattern_type": turn_pattern_types[pattern_id],
                        "title": turn_pattern_titles[pattern_id],
                        "count": count,
                        "trigger_item_ids": turn_pattern_trigger_item_ids[pattern_id],
                        "case_ids": sorted(turn_pattern_case_ids[pattern_id]),
                        "session_ids": sorted(turn_pattern_session_ids[pattern_id]),
                        "source_report_ids": sorted(turn_pattern_source_report_ids[pattern_id]),
                        "source_report_count": len(turn_pattern_source_report_ids[pattern_id]),
                    }
                )
                for pattern_id, count in sorted(turn_pattern_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "humanistic_communication": _summarize_humanistic_communication(humanistic_reports),
        }


def _recommendation_kind_rank(reference: str) -> int:
    if reference.startswith("rubric:"):
        return 0
    if reference.startswith("knowledge:"):
        return 1
    return 2


def _source_reference_kind_rank(reference: str) -> int:
    if reference.startswith("source:"):
        return 0
    if reference.startswith("case:"):
        return 1
    if reference.startswith("rubric:"):
        return 2
    if reference.startswith("evidence:"):
        return 3
    return 4


def _summarize_humanistic_communication(reports: list[dict[str, Any]]) -> dict[str, Any]:
    score_values: list[float] = []
    max_score = 30
    dimension_scores: dict[str, list[float]] = defaultdict(list)
    gap_counts: Counter[str] = Counter()
    gap_missing_score_totals: Counter[str] = Counter()
    gap_labels: dict[str, str] = {}
    gap_skill_types: dict[str, str] = {}
    missed_opportunity_counts: Counter[str] = Counter()
    missed_opportunity_expected_responses: dict[str, str] = {}
    anchor_candidate_status_counts: Counter[str] = Counter()

    for report in reports:
        score_group = _mapping(report.get("score_groups")).get("humanistic_communication")
        if isinstance(score_group, dict):
            score_values.append(_float_value(score_group.get("score")))
            max_score = int(_float_value(score_group.get("max_score")) or max_score)
        for dimension_id, score in _mapping(report.get("dimension_scores")).items():
            if dimension_id in HUMANISTIC_DIMENSION_LABELS:
                dimension_scores[dimension_id].append(_float_value(score))
        for gap in _mapping_list(report.get("training_gaps")):
            if not _is_humanistic_gap(gap):
                continue
            gap_type = str(gap.get("gap_type") or "unknown_humanistic_gap")
            gap_counts[gap_type] += 1
            gap_missing_score_totals[gap_type] += int(_float_value(gap.get("missing_score")))
            gap_labels.setdefault(gap_type, str(gap.get("label") or gap_type))
            gap_skill_types.setdefault(gap_type, str(gap.get("skill_type") or ""))
        for missed_opportunity in _mapping_list(report.get("missed_opportunities")):
            gap_type = str(missed_opportunity.get("gap_type") or "missed_opportunity")
            missed_opportunity_counts[gap_type] += 1
            missed_opportunity_expected_responses.setdefault(
                gap_type,
                str(missed_opportunity.get("expected_response") or ""),
            )
        for candidate in _mapping_list(report.get("humanistic_anchor_candidates")):
            status = str(candidate.get("status") or "candidate")
            anchor_candidate_status_counts[status] += 1

    return {
        "report_count": len(score_values),
        "average_score": _average_score(score_values),
        "max_score": max_score,
        "dimension_averages": [
            {
                "dimension_id": dimension_id,
                "dimension_label": HUMANISTIC_DIMENSION_LABELS[dimension_id],
                "average_score": _average_score(scores),
            }
            for dimension_id, scores in sorted(
                dimension_scores.items(),
                key=lambda item: (-_average_score(item[1]), HUMANISTIC_DIMENSION_ORDER.get(item[0], 99)),
            )
        ],
        "frequent_gaps": [
            {
                "gap_type": gap_type,
                "label": gap_labels.get(gap_type, gap_type),
                "count": count,
                "missing_score_total": gap_missing_score_totals[gap_type],
                "skill_type": gap_skill_types.get(gap_type, ""),
            }
            for gap_type, count in sorted(
                gap_counts.items(),
                key=lambda item: (-item[1], -gap_missing_score_totals[item[0]], item[0]),
            )
        ],
        "frequent_missed_opportunities": [
            {
                "gap_type": gap_type,
                "expected_response": missed_opportunity_expected_responses.get(gap_type, ""),
                "count": count,
            }
            for gap_type, count in sorted(missed_opportunity_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "anchor_candidate_count": sum(anchor_candidate_status_counts.values()),
        "anchor_candidates_by_status": [
            {"status": status, "count": count}
            for status, count in sorted(anchor_candidate_status_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "trend": _humanistic_score_trend(score_values),
    }


def _has_humanistic_payload(payload: dict[str, Any]) -> bool:
    score_groups = _mapping(payload.get("score_groups"))
    if "humanistic_communication" in score_groups:
        return True
    return any(dimension_id in HUMANISTIC_DIMENSION_LABELS for dimension_id in _mapping(payload.get("dimension_scores")))


def _is_humanistic_gap(gap: dict[str, Any]) -> bool:
    dimension_id = str(gap.get("dimension_id") or "")
    skill_type = str(gap.get("skill_type") or "")
    gap_type = str(gap.get("gap_type") or "")
    return (
        dimension_id in HUMANISTIC_DIMENSION_LABELS
        or skill_type in HUMANISTIC_SKILL_TYPES
        or gap_type.startswith(("narrative_", "communication_", "ethics_", "relationship_"))
    )


def _humanistic_score_trend(score_values: list[float]) -> dict[str, Any]:
    if not score_values:
        return {"previous_average_score": 0, "recent_average_score": 0, "delta": 0}
    if len(score_values) == 1:
        average = _average_score(score_values)
        return {"previous_average_score": average, "recent_average_score": average, "delta": 0}
    midpoint = max(1, len(score_values) // 2)
    previous_average = _average_score(score_values[:midpoint])
    recent_average = _average_score(score_values[midpoint:])
    return {
        "previous_average_score": previous_average,
        "recent_average_score": recent_average,
        "delta": _round_score(float(recent_average) - float(previous_average)),
    }


def _average_score(values: list[float]) -> float | int:
    if not values:
        return 0
    return _round_score(sum(values) / len(values))


def _round_score(value: float) -> float | int:
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _turn_patterns_from_training_event(
    event: dict[str, Any],
    history_fact_disclosure_count: int,
    physical_exam_request_count: int,
) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    payload = event.get("payload", {})
    agent_turn = payload.get("agent_turn") if isinstance(payload, dict) else None
    if isinstance(agent_turn, dict):
        current_intents = _current_intents_from_agent_turn(agent_turn)
        primary_intent = current_intents[0] if current_intents else "unknown_history_intent"
        turn_policy = str(agent_turn.get("turn_policy", ""))
        turn_analysis = agent_turn.get("turn_analysis", {})
        is_off_topic = isinstance(turn_analysis, dict) and bool(turn_analysis.get("is_off_topic"))
        if is_off_topic or (primary_intent == "unknown_history_intent" and turn_policy == "patient_context_redirect"):
            patterns.append(
                {
                    "pattern_id": "turn_pattern_off_topic_redirect",
                    "pattern_type": "off_topic_redirect",
                    "title": "偏题或寒暄后需要回到问诊目标",
                    "trigger_item_ids": [
                        "turn_intent:unknown_history_intent",
                        "turn_policy:patient_context_redirect",
                    ],
                }
            )
        if primary_intent == "answer_request_redirect" or turn_policy == "answer_boundary_redirect":
            patterns.append(
                {
                    "pattern_id": "turn_pattern_premature_answer_request",
                    "pattern_type": "premature_answer_request",
                    "title": "过早索要答案或诊断结论",
                    "trigger_item_ids": [
                        "turn_intent:answer_request_redirect",
                        "turn_policy:answer_boundary_redirect",
                    ],
                }
            )
        if primary_intent == "safety_boundary" or turn_policy == "safety_boundary_redirect":
            patterns.append(
                {
                    "pattern_id": "turn_pattern_safety_boundary_request",
                    "pattern_type": "safety_boundary_request",
                    "title": "请求真实诊疗建议或安全边界内容",
                    "trigger_item_ids": [
                        "turn_intent:safety_boundary",
                        "turn_policy:safety_boundary_redirect",
                    ],
                }
            )
    if history_fact_disclosure_count == 0 and event.get("event_type") == "physical_exam_requested":
        patterns.append(
            {
                "pattern_id": "turn_pattern_exam_before_history",
                "pattern_type": "exam_before_history",
                "title": "未完成核心病史前直接进入查体",
                "trigger_item_ids": ["event:physical_exam_requested", "sequence:before_history_fact_disclosure"],
            }
        )
    if history_fact_disclosure_count == 0 and event.get("event_type") == "auxiliary_test_requested":
        patterns.append(
            {
                "pattern_id": "turn_pattern_test_before_history",
                "pattern_type": "test_before_history",
                "title": "未完成核心病史前直接申请辅助检查",
                "trigger_item_ids": ["event:auxiliary_test_requested", "sequence:before_history_fact_disclosure"],
            }
        )
    elif (
        history_fact_disclosure_count > 0
        and physical_exam_request_count == 0
        and event.get("event_type") == "auxiliary_test_requested"
    ):
        patterns.append(
            {
                "pattern_id": "turn_pattern_auxiliary_test_before_physical_exam",
                "pattern_type": "auxiliary_test_before_physical_exam",
                "title": "有病史线索后跳过查体直接申请辅助检查",
                "trigger_item_ids": ["event:auxiliary_test_requested", "sequence:before_physical_exam"],
            }
        )
    return patterns


def _current_intents_from_agent_turn(agent_turn: dict[str, Any]) -> list[str]:
    raw_current_intents = agent_turn.get("current_intents")
    if isinstance(raw_current_intents, list):
        return [str(intent) for intent in raw_current_intents if intent and intent != "unknown_history_intent"]
    legacy_intent = str(agent_turn.get("current_intent", "") or "")
    if legacy_intent and legacy_intent != "unknown_history_intent":
        return [legacy_intent]
    return []


training_insight_service = TrainingInsightService()


def _list_events_by_session(event_store: TrainingEventStore, session_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if hasattr(event_store, "list_events_for_sessions"):
        return event_store.list_events_for_sessions(session_ids)
    return {session_id: event_store.list_session_events(session_id) for session_id in session_ids}
