from __future__ import annotations

from typing import Any

from app.services.training_skill_context_safety import candidate_context_safety_violations

APPROVAL_AGENT_ID = "skill_auto_approval_agent"
ACTIVATION_ALLOWED_APPROVAL_DECISIONS = {
    "prepared_for_auto_apply",
    "approved_for_auto_apply",
    "ready_for_human_review",
}


def approval_agent_review_violations(candidate: dict[str, Any]) -> list[str]:
    approval_review = candidate.get("approval_agent_review")
    if not isinstance(approval_review, dict):
        return ["approval_review_missing"]

    violations: list[str] = []
    if str(approval_review.get("agent_id") or "") != APPROVAL_AGENT_ID:
        violations.append("approval_agent_identity_invalid")
    if str(approval_review.get("decision") or "") == "blocked":
        violations.append("approval_decision_blocked")

    quality_review = approval_review.get("quality_review")
    if not isinstance(quality_review, dict) or quality_review.get("passed") is not True:
        violations.append("approval_quality_review_failed")
        failed_checks = (
            quality_review.get("failed_checks", [])
            if isinstance(quality_review, dict)
            else []
        )
        for failed_check in failed_checks:
            violation = f"approval_check:{str(failed_check).strip()}"
            if violation not in violations:
                violations.append(violation)

    role_policy = approval_review.get("role_policy")
    if not isinstance(role_policy, dict) or role_policy.get("passed") is not True:
        violations.append("approval_role_policy_failed")
    return violations


def candidate_activation_gate_violations(candidate: dict[str, Any]) -> list[str]:
    """Return fail-closed reasons before a candidate enters the enabled Skill store."""

    violations: list[str] = []
    review = candidate.get("review")
    if not isinstance(review, dict) or review.get("status") != "approved":
        violations.append("candidate_not_approved")
    if not isinstance(review, dict) or review.get("regression_passed") is not True:
        violations.append("candidate_regression_not_passed")

    approval_review = candidate.get("approval_agent_review")
    violations.extend(approval_agent_review_violations(candidate))
    if isinstance(approval_review, dict) and (
        str(approval_review.get("decision") or "")
        not in ACTIVATION_ALLOWED_APPROVAL_DECISIONS
    ):
        violations.append("approval_decision_not_accepted")

    if candidate_context_safety_violations(candidate):
        violations.append("candidate_context_unsafe")
    return violations


__all__ = [
    "ACTIVATION_ALLOWED_APPROVAL_DECISIONS",
    "APPROVAL_AGENT_ID",
    "approval_agent_review_violations",
    "candidate_activation_gate_violations",
]
