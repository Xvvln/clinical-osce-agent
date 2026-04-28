from __future__ import annotations

from typing import Any

from app.services.evaluation_runner import EvaluationBatchResult, EvaluationResult


class TrainingSkillRegressionGate:
    def review_candidate(self, candidate: dict[str, Any], batch_result: EvaluationBatchResult) -> dict[str, Any]:
        regression_passed = batch_result.passed
        return {
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


def _blocking_failure(result: EvaluationResult) -> dict[str, Any]:
    return {
        "session_id": result.session_id,
        "actual_total_score": result.actual_total_score,
        "expected_total_score": result.expected_total_score,
        "forbidden_term_violations": result.forbidden_term_violations,
    }


training_skill_regression_gate = TrainingSkillRegressionGate()
