from __future__ import annotations

from collections import Counter
from typing import Any

from app.services.training_event_store import TrainingEventStore, training_event_store
from app.services.training_report_event_normalizer import (
    latest_report_generated_event,
    normalize_report_events_by_session,
    unique_session_ids,
)


class TrainingSkillEffectService:
    def __init__(self, event_store: TrainingEventStore = training_event_store) -> None:
        self.event_store = event_store

    def summarize_sessions(self, session_ids: list[str], min_sessions_per_group: int = 2) -> dict[str, Any]:
        comparison = self.compare_sessions(session_ids)
        with_skill = comparison["with_skill"]
        without_skill = comparison["without_skill"]
        has_sufficient_samples = (
            with_skill["session_count"] >= min_sessions_per_group
            and without_skill["session_count"] >= min_sessions_per_group
        )
        score_delta = None
        if has_sufficient_samples:
            score_delta = round(with_skill["average_total_score"] - without_skill["average_total_score"], 2)
        return {
            "status": "descriptive_only" if has_sufficient_samples else "insufficient_samples",
            "label": "描述性对比" if has_sufficient_samples else "样本不足",
            "min_sessions_per_group": min_sessions_per_group,
            "score_delta": score_delta,
            **comparison,
        }

    def compare_sessions(self, session_ids: list[str]) -> dict[str, Any]:
        groups = {
            "with_skill": _empty_group(),
            "without_skill": _empty_group(),
        }
        normalized_session_ids = unique_session_ids(session_ids)
        events_by_session = normalize_report_events_by_session(
            normalized_session_ids,
            _list_events_by_session(self.event_store, normalized_session_ids),
        )
        for session_id in normalized_session_ids:
            events = events_by_session.get(session_id, [])
            skill_ids = [
                event["payload"]["skill_id"]
                for event in events
                if event["event_type"] == "training_skill_applied"
            ]
            report_event = latest_report_generated_event(events)
            if report_event is None:
                continue
            report_payload = report_event["payload"]
            group = groups["with_skill" if skill_ids else "without_skill"]
            group["session_count"] += 1
            group["total_scores"].append(report_payload["total_score"])
            group["missed_item_counter"].update(report_payload.get("missed_items", []))
            group["skill_id_counter"].update(skill_ids)
        return {
            group_name: _serialize_group(group)
            for group_name, group in groups.items()
        }


def _empty_group() -> dict[str, Any]:
    return {
        "session_count": 0,
        "total_scores": [],
        "missed_item_counter": Counter(),
        "skill_id_counter": Counter(),
    }


def _serialize_group(group: dict[str, Any]) -> dict[str, Any]:
    total_scores = group["total_scores"]
    average_total_score = sum(total_scores) / len(total_scores) if total_scores else 0.0
    return {
        "session_count": group["session_count"],
        "average_total_score": average_total_score,
        "missed_item_counts": dict(group["missed_item_counter"]),
        "skill_ids": sorted(group["skill_id_counter"]),
    }


training_skill_effect_service = TrainingSkillEffectService()


def _list_events_by_session(event_store: TrainingEventStore, session_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if hasattr(event_store, "list_events_for_sessions"):
        return event_store.list_events_for_sessions(session_ids)
    return {session_id: event_store.list_session_events(session_id) for session_id in session_ids}
