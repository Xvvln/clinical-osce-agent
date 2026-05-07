from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"

FEMALE_REPRODUCTIVE_TERMS = [
    "妇科",
    "妊娠",
    "怀孕",
    "宫外孕",
    "异位妊娠",
    "孕产",
    "月经",
    "停经",
    "阴道",
    "ectopic",
    "pregnancy",
    "pregnant",
    "gynecologic",
    "gynecology",
    "obstetric",
]


def candidate_context_safety_violations(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    matched_terms = _matching_terms(candidate, FEMALE_REPRODUCTIVE_TERMS)
    if not matched_terms:
        return []

    violations: list[dict[str, Any]] = []
    for case_id in _candidate_case_ids(candidate):
        if _case_gender(case_id) == "男":
            violations.append(
                {
                    "case_id": case_id,
                    "reason": "male_patient_incompatible_reproductive_content",
                    "terms": matched_terms,
                }
            )
    return violations


def candidate_with_context_safety_review(candidate: dict[str, Any]) -> dict[str, Any]:
    violations = candidate_context_safety_violations(candidate)
    if not violations:
        return candidate

    normalized_candidate = deepcopy(candidate)
    review = dict(normalized_candidate.get("review", {}))
    review["status"] = "blocked_by_regression"
    review["regression_passed"] = False
    review["candidate_context_violations"] = violations
    normalized_candidate["review"] = review
    return normalized_candidate


def _candidate_case_ids(candidate: dict[str, Any]) -> list[str]:
    case_ids = {str(case_id) for case_id in candidate.get("case_ids", []) if str(case_id)}
    applies_when = candidate.get("applies_when")
    if isinstance(applies_when, dict):
        case_ids.update(str(case_id) for case_id in applies_when.get("case_ids", []) if str(case_id))

    for reference in candidate.get("related_recommendations", []):
        reference_text = str(reference)
        if reference_text.startswith("case:"):
            case_ids.add(reference_text.split("case:", 1)[1])
        if reference_text.startswith("rubric:") and "_rubric" in reference_text:
            case_ids.add(reference_text.split("rubric:", 1)[1].split("_rubric", 1)[0])
    return sorted(case_ids)


def _case_gender(case_id: str) -> str | None:
    case_path = CASES_DIR / f"{case_id}.json"
    if not case_path.exists():
        return None
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    patient_profile = payload.get("patient_profile", {})
    if not isinstance(patient_profile, dict):
        return None
    gender = patient_profile.get("gender")
    return str(gender) if gender is not None else None


def _matching_terms(value: Any, terms: list[str]) -> list[str]:
    matched_terms: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, str):
            normalized = item.lower()
            matched_terms.update(term for term in terms if term.lower() in normalized)
            return
        if isinstance(item, dict):
            for key, nested_value in item.items():
                visit(key)
                visit(nested_value)
            return
        if isinstance(item, list):
            for nested_item in item:
                visit(nested_item)

    visit(value)
    return [term for term in terms if term in matched_terms]
