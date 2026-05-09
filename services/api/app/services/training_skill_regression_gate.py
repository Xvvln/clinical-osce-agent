from __future__ import annotations

import re
from typing import Any

from app.services.evaluation_runner import EvaluationBatchResult, EvaluationResult
from app.services.training_skill_context_safety import candidate_context_safety_violations

FORBIDDEN_CANDIDATE_TERMS = [
    "治疗方案",
    "用药剂量",
    "用药建议",
    "手术方案",
    "处置建议",
    "剂量",
    "处方",
    "阿莫西林",
    "头孢",
    "抗生素",
]

FORBIDDEN_CANDIDATE_PATTERNS = {
    "dose_expression": re.compile(r"\d+(?:\.\d+)?\s*(?:mg|g|ml|mL|ug|μg|iu|IU|片|粒|支|袋)", re.IGNORECASE),
    "dose_frequency": re.compile(r"(?<![A-Za-z0-9])(?:q\d+h|bid|tid|qid|qd|qn|prn|po|iv|im)(?![A-Za-z0-9])", re.IGNORECASE),
}


class TrainingSkillRegressionGate:
    def review_candidate(self, candidate: dict[str, Any], batch_result: EvaluationBatchResult) -> dict[str, Any]:
        safety_violations = _candidate_safety_violations(candidate)
        context_violations = candidate_context_safety_violations(candidate)
        regression_passed = batch_result.passed and not safety_violations and not context_violations
        review: dict[str, Any] = {
            "candidate_id": candidate["candidate_id"],
            "status": "ready_for_review" if regression_passed else "blocked_by_regression",
            "regression_passed": regression_passed,
            "evaluation_total_cases": batch_result.total_cases,
            "evaluation_passed_cases": batch_result.passed_cases,
            "evaluation_failed_cases": batch_result.failed_cases,
            "blocking_failures": [
                _blocking_failure(result)
                for result in batch_result.results
                if not result.passed
            ],
        }
        if safety_violations:
            review["candidate_safety_violations"] = safety_violations
        if context_violations:
            review["candidate_context_violations"] = context_violations
        return review


def _candidate_safety_violations(candidate: dict[str, Any]) -> list[str]:
    candidate_text = " ".join(
        str(candidate.get(field, ""))
        for field in ["title", "description", "suggested_strategy", "trigger_item_id"]
    )
    violations: list[str] = []
    for term in FORBIDDEN_CANDIDATE_TERMS:
        if term in candidate_text and not any(term in existing_term for existing_term in violations):
            violations.append(term)
    violations.extend(
        violation_id
        for violation_id, pattern in FORBIDDEN_CANDIDATE_PATTERNS.items()
        if pattern.search(candidate_text)
    )
    return violations


def _blocking_failure(result: EvaluationResult) -> dict[str, Any]:
    return {
        "session_id": result.session_id,
        "actual_total_score": result.actual_total_score,
        "expected_total_score": result.expected_total_score,
        "forbidden_term_violations": result.forbidden_term_violations,
    }


training_skill_regression_gate = TrainingSkillRegressionGate()
