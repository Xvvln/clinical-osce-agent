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
        report_count = 0

        for session_id in session_ids:
            for event in self.event_store.list_session_events(session_id):
                if event["event_type"] != "report_generated":
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


training_insight_service = TrainingInsightService()
