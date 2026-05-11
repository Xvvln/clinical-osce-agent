from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.services.training_event_store import TrainingEventStore, training_event_store


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
        report_count = 0

        for session_id in session_ids:
            events = self.event_store.list_session_events(session_id)
            session_report_ids = [
                str(event["payload"].get("report_id"))
                for event in events
                if event["event_type"] == "report_generated" and event["payload"].get("report_id")
            ]
            history_fact_disclosure_count = 0
            for event in events:
                if event["event_type"] != "report_generated":
                    for pattern in _turn_patterns_from_training_event(event, history_fact_disclosure_count):
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
                    continue
                report_count += 1
                payload = event["payload"]
                case_id = event["case_id"]
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
            "session_count": len(session_ids),
            "report_count": report_count,
            "frequent_missed_items": [
                {
                    "item_id": item_id,
                    "count": count,
                    "case_ids": sorted(missed_item_case_ids[item_id]),
                }
                for item_id, count in sorted(missed_item_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "frequent_learning_recommendations": [
                {
                    "reference": reference,
                    "title": recommendation_titles[reference],
                    "count": count,
                }
                for reference, count in sorted(
                    recommendation_counts.items(),
                    key=lambda item: (-item[1], _recommendation_kind_rank(item[0]), item[0]),
                )
            ],
            "frequent_source_references": [
                {
                    "reference": reference,
                    "source_type": source_reference_types[reference],
                    "title": source_reference_titles[reference],
                    "count": count,
                    "case_ids": sorted(source_reference_case_ids[reference]),
                    "metadata": source_reference_metadata[reference],
                }
                for reference, count in sorted(
                    source_reference_counts.items(),
                    key=lambda item: (-item[1], _source_reference_kind_rank(item[0]), item[0]),
                )
            ],
            "frequent_turn_patterns": [
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
                for pattern_id, count in sorted(turn_pattern_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
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


def _turn_patterns_from_training_event(
    event: dict[str, Any],
    history_fact_disclosure_count: int,
) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    payload = event.get("payload", {})
    agent_turn = payload.get("agent_turn") if isinstance(payload, dict) else None
    if isinstance(agent_turn, dict):
        current_intent = str(agent_turn.get("current_intent", ""))
        turn_policy = str(agent_turn.get("turn_policy", ""))
        turn_analysis = agent_turn.get("turn_analysis", {})
        is_off_topic = isinstance(turn_analysis, dict) and bool(turn_analysis.get("is_off_topic"))
        if is_off_topic or (current_intent == "unknown_history_intent" and turn_policy == "patient_context_redirect"):
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
        if current_intent == "answer_request_redirect" or turn_policy == "answer_boundary_redirect":
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
        if current_intent == "safety_boundary" or turn_policy == "safety_boundary_redirect":
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
    return patterns


training_insight_service = TrainingInsightService()
