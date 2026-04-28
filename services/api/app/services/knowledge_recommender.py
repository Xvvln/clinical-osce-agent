from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.retrieval_index import search_retrieval_documents

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"


def recommend_knowledge_items(report: dict[str, Any]) -> list[dict[str, str]]:
    case_id = report["case_id"]
    rubric_scores = report.get("rubric_scores", {})
    recommendations: list[dict[str, str]] = []
    for item_id in report.get("missed_items", []):
        item_score = rubric_scores.get(item_id)
        if not item_score:
            continue
        recommendations.append(
            {
                "reference": f"rubric:{case_id}_rubric.item.{item_id}",
                "title": item_score["description"],
                "reason": _recommendation_reason(item_score.get("dimension_id", "")),
            }
        )
        recommendations.extend(_recommend_missing_evidence(item_score))
    recommendations.extend(_recommend_similar_cases(case_id))
    return _deduplicate_recommendations(recommendations)


def _recommend_missing_evidence(item_score: dict[str, Any]) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    for evidence in item_score.get("missing_evidence", []):
        for document in search_retrieval_documents(evidence, limit=5):
            if document.source_type != "knowledge" or document.reference != f"knowledge:{evidence}":
                continue
            recommendations.append(
                {
                    "reference": document.reference,
                    "title": document.title,
                    "reason": f"关联本轮缺失证据：{document.snippet}",
                }
            )
            break
    return recommendations


def _recommend_similar_cases(case_id: str) -> list[dict[str, str]]:
    current_case = _load_case_payload(case_id)
    current_module = current_case.get("course_module", "")
    candidates = [
        payload
        for payload in _load_case_payloads()
        if payload["case_id"] != case_id
    ]
    same_module_candidates = [payload for payload in candidates if payload.get("course_module") == current_module]
    if same_module_candidates:
        return [
            {
                "reference": f"case:{payload['case_id']}",
                "title": payload["case_title"],
                "reason": f"与当前病例同属{current_module}模块，可用于下一轮相似场景训练。",
            }
            for payload in same_module_candidates[:2]
        ]
    return [
        {
            "reference": f"case:{payload['case_id']}",
            "title": payload["case_title"],
            "reason": "病例库暂无同模块病例，推荐用于下一轮对照训练。",
        }
        for payload in candidates[:2]
    ]


def _load_case_payload(case_id: str) -> dict[str, Any]:
    return json.loads((CASES_DIR / f"{case_id}.json").read_text(encoding="utf-8"))


def _load_case_payloads() -> list[dict[str, Any]]:
    return [json.loads(case_path.read_text(encoding="utf-8")) for case_path in sorted(CASES_DIR.glob("*.json"))]


def _recommendation_reason(dimension_id: str) -> str:
    if dimension_id in {"differential_diagnosis", "reasoning"}:
        return "本轮评分未找到足够证据，建议复习该临床推理要点。"
    return "本轮评分未找到足够证据，建议复习该问诊要点。"


def _deduplicate_recommendations(recommendations: list[dict[str, str]]) -> list[dict[str, str]]:
    deduplicated: list[dict[str, str]] = []
    seen_references: set[str] = set()
    for recommendation in recommendations:
        reference = recommendation["reference"]
        if reference in seen_references:
            continue
        seen_references.add(reference)
        deduplicated.append(recommendation)
    return deduplicated
