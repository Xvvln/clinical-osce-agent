from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.osce_session_service import OsceSessionService


@dataclass(frozen=True)
class EvaluationStep:
    kind: str
    value: str
    reasoning: str = ""


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    student_id: str
    steps: list[EvaluationStep]
    expected_total_score: int
    forbidden_terms: list[str]


@dataclass(frozen=True)
class EvaluationResult:
    session_id: str
    actual_total_score: int
    expected_total_score: int
    forbidden_term_violations: list[str]
    passed: bool
    duration_ms: int = 0


@dataclass(frozen=True)
class EvaluationBatchResult:
    total_cases: int
    passed_cases: int
    failed_cases: int
    results: list[EvaluationResult]
    passed: bool
    total_duration_ms: int = 0


def load_evaluation_cases(file_path: Path) -> list[EvaluationCase]:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    return [_evaluation_case_from_payload(item) for item in payload]


def run_evaluation_cases(evaluation_cases: list[EvaluationCase], service: OsceSessionService) -> EvaluationBatchResult:
    results = [run_evaluation_case(evaluation_case, service) for evaluation_case in evaluation_cases]
    passed_cases = sum(1 for result in results if result.passed)
    total_cases = len(results)
    return EvaluationBatchResult(
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=total_cases - passed_cases,
        results=results,
        passed=passed_cases == total_cases,
        total_duration_ms=sum(result.duration_ms for result in results),
    )


def run_evaluation_case(evaluation_case: EvaluationCase, service: OsceSessionService) -> EvaluationResult:
    started_at = time.perf_counter()
    session = service.create_session(case_id=evaluation_case.case_id, student_id=evaluation_case.student_id)
    session_id = session["session_id"]
    for step in evaluation_case.steps:
        if step.kind == "message":
            service.handle_message(session_id, step.value)
        elif step.kind == "physical_exam":
            service.request_physical_exam(session_id, step.value)
        elif step.kind == "auxiliary_test":
            service.request_auxiliary_test(session_id, step.value)
        elif step.kind == "submit_diagnosis":
            service.submit_diagnosis(session_id, step.value, step.reasoning)

    report = service.get_report(session_id) or {}
    actual_total_score = int(report.get("total_score", 0))
    evaluation_text = f"{report} {evaluation_case.steps}"
    forbidden_term_violations = [term for term in evaluation_case.forbidden_terms if term in evaluation_text]
    passed = actual_total_score == evaluation_case.expected_total_score and not forbidden_term_violations
    return EvaluationResult(
        session_id=session_id,
        actual_total_score=actual_total_score,
        expected_total_score=evaluation_case.expected_total_score,
        forbidden_term_violations=forbidden_term_violations,
        passed=passed,
        duration_ms=int((time.perf_counter() - started_at) * 1000),
    )


def _evaluation_case_from_payload(payload: dict[str, Any]) -> EvaluationCase:
    return EvaluationCase(
        case_id=payload["case_id"],
        student_id=payload["student_id"],
        steps=[
            EvaluationStep(
                kind=step["kind"],
                value=step["value"],
                reasoning=step.get("reasoning", ""),
            )
            for step in payload["steps"]
        ],
        expected_total_score=payload["expected_total_score"],
        forbidden_terms=payload["forbidden_terms"],
    )
