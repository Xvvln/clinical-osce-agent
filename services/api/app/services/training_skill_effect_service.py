from __future__ import annotations

from collections import Counter
from typing import Any

from app.services.training_event_store import TrainingEventStore, training_event_store


class TrainingSkillEffectService:
    def __init__(self, event_store: TrainingEventStore = training_event_store) -> None:
        self.event_store = event_store

    def compare_sessions(self, session_ids: list[str]) -> dict[str, Any]:
        groups = {
            "with_skill": _empty_group(),
            "without_skill": _empty_group(),
        }
        for session_id in session_ids:
            events = self.event_store.list_session_events(session_id)
            skill_ids = [
                event["payload"]["skill_id"]
                for event in events
                if event["event_type"] == "training_skill_applied"
            ]
            report_payload = next(
                (event["payload"] for event in events if event["event_type"] == "report_generated"),
                None,
            )
            if report_payload is None:
                continue
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
