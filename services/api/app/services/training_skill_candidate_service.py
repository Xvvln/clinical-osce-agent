from __future__ import annotations

from typing import Any


class TrainingSkillCandidateService:
    def propose_candidates(self, insights: dict[str, Any], min_count: int = 2) -> list[dict[str, Any]]:
        source_report_count = insights.get("report_count", 0)
        related_recommendations = [
            recommendation["reference"]
            for recommendation in insights.get("frequent_learning_recommendations", [])
        ]
        candidates: list[dict[str, Any]] = []

        for missed_item in insights.get("frequent_missed_items", []):
            support_count = missed_item["count"]
            if support_count < min_count:
                continue
            candidates.append(
                _build_candidate(
                    item_id=missed_item["item_id"],
                    support_count=support_count,
                    case_ids=missed_item["case_ids"],
                    source_report_count=source_report_count,
                    related_recommendations=related_recommendations,
                )
            )
        return candidates


def _build_candidate(
    item_id: str,
    support_count: int,
    case_ids: list[str],
    source_report_count: int,
    related_recommendations: list[str],
) -> dict[str, Any]:
    if item_id == "reasoning_core":
        return {
            "candidate_id": f"skill_candidate_{item_id}",
            "trigger_item_id": item_id,
            "title": "临床推理链纠偏提示",
            "description": _candidate_description(item_id, support_count, case_ids, source_report_count),
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": source_report_count,
            "support_count": support_count,
            "related_recommendations": related_recommendations,
        }
    return {
        "candidate_id": f"skill_candidate_{item_id}",
        "trigger_item_id": item_id,
        "title": "OSCE 漏项纠偏提示",
        "description": _candidate_description(item_id, support_count, case_ids, source_report_count),
        "suggested_strategy": "在不透露标准答案的前提下，提醒学生回顾本轮训练中反复遗漏的问诊、查体、检查或推理要点。",
        "status": "draft",
        "source_report_count": source_report_count,
        "support_count": support_count,
        "related_recommendations": related_recommendations,
    }


def _candidate_description(item_id: str, support_count: int, case_ids: list[str], source_report_count: int) -> str:
    return f"{source_report_count} 份报告中有 {support_count} 次漏掉 {item_id}，涉及病例：{'、'.join(case_ids)}。"


training_skill_candidate_service = TrainingSkillCandidateService()
