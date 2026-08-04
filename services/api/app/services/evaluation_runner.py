from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
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
class EvaluationThresholds:
    maximum_score_delta: int = 0
    minimum_batch_pass_rate: float = 1.0
    minimum_rag_explanation_coverage_ratio: float = 1.0
    minimum_rag_evidence_coverage_ratio: float = 1.0
    require_rag_source_coverage: bool = True
    maximum_case_duration_ms: int = 0


@dataclass(frozen=True)
class EvaluationResult:
    session_id: str
    actual_total_score: int
    expected_total_score: int
    forbidden_term_violations: list[str]
    passed: bool
    source_reference_count: int = 0
    source_reference_types: list[str] = field(default_factory=list)
    rag_source_coverage_passed: bool = False
    rag_rubric_reference_coverage_ratio: float = 0.0
    missing_rubric_references: list[str] = field(default_factory=list)
    rag_explanation_coverage_passed: bool = False
    rag_explanation_coverage_ratio: float = 0.0
    missing_explanation_references: list[str] = field(default_factory=list)
    rag_evidence_coverage_passed: bool = False
    rag_evidence_coverage_ratio: float = 0.0
    missing_evidence_references: list[str] = field(default_factory=list)
    rag_knowledge_safety_passed: bool = True
    forbidden_rag_knowledge_references: list[str] = field(default_factory=list)
    rag_score_isolation_passed: bool = True
    rag_score_isolation_violations: list[str] = field(default_factory=list)
    rag_agent_grounding_passed: bool = True
    missing_agent_knowledge_references: list[str] = field(default_factory=list)
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


def run_evaluation_cases(
    evaluation_cases: list[EvaluationCase],
    service: OsceSessionService,
    thresholds: EvaluationThresholds | None = None,
) -> EvaluationBatchResult:
    effective_thresholds = thresholds or EvaluationThresholds()
    results = [
        run_evaluation_case(evaluation_case, service, effective_thresholds)
        for evaluation_case in evaluation_cases
    ]
    passed_cases = sum(1 for result in results if result.passed)
    total_cases = len(results)
    pass_rate = passed_cases / total_cases if total_cases else 0.0
    return EvaluationBatchResult(
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=total_cases - passed_cases,
        results=results,
        passed=total_cases > 0 and pass_rate >= effective_thresholds.minimum_batch_pass_rate,
        total_duration_ms=sum(result.duration_ms for result in results),
    )


def run_evaluation_case(
    evaluation_case: EvaluationCase,
    service: OsceSessionService,
    thresholds: EvaluationThresholds | None = None,
) -> EvaluationResult:
    effective_thresholds = thresholds or EvaluationThresholds()
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

    report = service.generate_report(session_id, include_optional_agents=True) or {}
    session_payload = _evaluation_session_payload(service, session_id)
    actual_total_score = int(report.get("total_score", 0))
    source_reference_items = _valid_source_reference_items(report.get("source_reference_items", []))
    source_reference_types = _source_reference_types(source_reference_items)
    missing_rubric_references = _missing_rubric_references(evaluation_case.case_id, report, source_reference_items)
    rag_rubric_reference_coverage_ratio = _rubric_reference_coverage_ratio(report, missing_rubric_references)
    missing_explanation_references = _missing_explanation_references(evaluation_case.case_id, report, source_reference_items)
    rag_explanation_coverage_ratio = _explanation_reference_coverage_ratio(report, missing_explanation_references)
    missing_evidence_references = _missing_evidence_references(report, source_reference_items)
    rag_evidence_coverage_ratio = _evidence_reference_coverage_ratio(report, missing_evidence_references)
    rag_source_coverage_passed = len(source_reference_items) > 0 and not missing_rubric_references
    rag_explanation_coverage_passed = not missing_explanation_references
    rag_evidence_coverage_passed = not missing_evidence_references
    forbidden_rag_knowledge_references = _forbidden_rag_knowledge_references(report)
    rag_score_isolation_violations = _rag_score_isolation_violations(report)
    missing_agent_knowledge_references = _missing_agent_knowledge_references(report)
    for missing_reference in _missing_agent_knowledge_references({"session": session_payload}):
        _append_unique(missing_agent_knowledge_references, missing_reference)
    rag_knowledge_safety_passed = not forbidden_rag_knowledge_references
    rag_score_isolation_passed = not rag_score_isolation_violations
    rag_agent_grounding_passed = not missing_agent_knowledge_references
    evaluation_text = f"{report} {evaluation_case.steps}"
    forbidden_term_violations = [term for term in evaluation_case.forbidden_terms if term in evaluation_text]
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    duration_passed = (
        effective_thresholds.maximum_case_duration_ms <= 0
        or duration_ms <= effective_thresholds.maximum_case_duration_ms
    )
    passed = (
        abs(actual_total_score - evaluation_case.expected_total_score)
        <= effective_thresholds.maximum_score_delta
        and not forbidden_term_violations
        and (rag_source_coverage_passed or not effective_thresholds.require_rag_source_coverage)
        and rag_explanation_coverage_ratio
        >= effective_thresholds.minimum_rag_explanation_coverage_ratio
        and rag_evidence_coverage_ratio
        >= effective_thresholds.minimum_rag_evidence_coverage_ratio
        and rag_knowledge_safety_passed
        and rag_score_isolation_passed
        and rag_agent_grounding_passed
        and duration_passed
    )
    return EvaluationResult(
        session_id=session_id,
        actual_total_score=actual_total_score,
        expected_total_score=evaluation_case.expected_total_score,
        forbidden_term_violations=forbidden_term_violations,
        source_reference_count=len(source_reference_items),
        source_reference_types=source_reference_types,
        rag_source_coverage_passed=rag_source_coverage_passed,
        rag_rubric_reference_coverage_ratio=rag_rubric_reference_coverage_ratio,
        missing_rubric_references=missing_rubric_references,
        rag_explanation_coverage_passed=rag_explanation_coverage_passed,
        rag_explanation_coverage_ratio=rag_explanation_coverage_ratio,
        missing_explanation_references=missing_explanation_references,
        rag_evidence_coverage_passed=rag_evidence_coverage_passed,
        rag_evidence_coverage_ratio=rag_evidence_coverage_ratio,
        missing_evidence_references=missing_evidence_references,
        rag_knowledge_safety_passed=rag_knowledge_safety_passed,
        forbidden_rag_knowledge_references=forbidden_rag_knowledge_references,
        rag_score_isolation_passed=rag_score_isolation_passed,
        rag_score_isolation_violations=rag_score_isolation_violations,
        rag_agent_grounding_passed=rag_agent_grounding_passed,
        missing_agent_knowledge_references=missing_agent_knowledge_references,
        passed=passed,
        duration_ms=duration_ms,
    )


def _valid_source_reference_items(source_reference_items: Any) -> list[dict[str, Any]]:
    if not isinstance(source_reference_items, list):
        return []
    return [
        item
        for item in source_reference_items
        if isinstance(item, dict) and isinstance(item.get("reference"), str) and item["reference"]
    ]


def _source_reference_types(source_reference_items: Any) -> list[str]:
    source_types: list[str] = []
    for item in source_reference_items:
        if not isinstance(item, dict):
            continue
        source_type = item.get("source_type")
        if isinstance(source_type, str) and source_type not in source_types:
            source_types.append(source_type)
    return source_types


FORBIDDEN_RAG_VISIBILITIES = {"secret_scoring_only", "admin_only"}
RAG_SCORING_USAGES = {"score", "scoring", "rubric_decision", "diagnosis_decision", "standard_diagnosis"}
RAG_SCORING_REFERENCE_KEYS = {
    "score_source_references",
    "scoring_source_references",
    "rubric_decision_source_references",
    "diagnosis_decision_source_references",
}


def _forbidden_rag_knowledge_references(report: dict[str, Any]) -> list[str]:
    references: list[str] = []
    for item in _iter_reference_dicts(report):
        reference = item.get("reference")
        if not isinstance(reference, str) or not reference.startswith("rag_knowledge:"):
            continue
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        visibility = str(item.get("visibility") or metadata.get("visibility") or "").strip()
        if visibility in FORBIDDEN_RAG_VISIBILITIES:
            _append_unique(references, reference)
    return references


def _rag_score_isolation_violations(report: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    _collect_rag_scoring_violations(report, [], violations)
    return violations


def _missing_agent_knowledge_references(report: dict[str, Any]) -> list[str]:
    missing_references: list[str] = []
    _collect_agent_knowledge_reference_violations(report, [], missing_references)
    return missing_references


def _evaluation_session_payload(service: OsceSessionService, session_id: str) -> dict[str, Any]:
    get_session = getattr(service, "get_session", None)
    if not callable(get_session):
        return {}
    try:
        payload = get_session(session_id)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _collect_agent_knowledge_reference_violations(
    payload: Any,
    path: list[str],
    missing_references: list[str],
) -> None:
    if isinstance(payload, dict):
        knowledge_references = [
            reference
            for reference in _string_values(payload.get("knowledge_references", []))
            if reference.startswith("rag_knowledge:")
        ]
        if knowledge_references:
            grounded_references = {
                item["reference"]
                for item in payload.get("retrieved_knowledge_context", [])
                if isinstance(item, dict) and isinstance(item.get("reference"), str)
            }
            reference_path = ".".join([*path, "knowledge_references"])
            for reference in knowledge_references:
                if reference not in grounded_references:
                    _append_unique(missing_references, f"{reference_path}:{reference}")
        for key, value in payload.items():
            _collect_agent_knowledge_reference_violations(value, [*path, str(key)], missing_references)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            _collect_agent_knowledge_reference_violations(item, [*path, str(index)], missing_references)


def _collect_rag_scoring_violations(payload: Any, path: list[str], violations: list[str]) -> None:
    if isinstance(payload, dict):
        reference = payload.get("reference")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        usage = str(payload.get("usage") or payload.get("used_for") or metadata.get("usage") or metadata.get("used_for") or "").strip()
        if isinstance(reference, str) and reference.startswith("rag_knowledge:") and usage in RAG_SCORING_USAGES:
            _append_unique(violations, f"{'.'.join(path) or 'report'}:{reference}")
        for key, value in payload.items():
            next_path = [*path, str(key)]
            if key in RAG_SCORING_REFERENCE_KEYS:
                for reference_value in _string_values(value):
                    if reference_value.startswith("rag_knowledge:"):
                        _append_unique(violations, f"{'.'.join(next_path)}:{reference_value}")
            _collect_rag_scoring_violations(value, next_path, violations)
    elif isinstance(payload, list):
        for item in payload:
            _collect_rag_scoring_violations(item, path, violations)


def _iter_reference_dicts(payload: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if isinstance(payload.get("reference"), str):
            items.append(payload)
        for value in payload.values():
            items.extend(_iter_reference_dicts(value))
    elif isinstance(payload, list):
        for item in payload:
            items.extend(_iter_reference_dicts(item))
    return items


def _string_values(payload: Any) -> list[str]:
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, str)]
    return []


def _missing_rubric_references(case_id: str, report: dict[str, Any], source_reference_items: Any) -> list[str]:
    covered_references = {
        item["reference"]
        for item in source_reference_items
        if isinstance(item, dict) and isinstance(item.get("reference"), str)
    }
    expected_references = [
        f"rubric:{case_id}_rubric.item.{item_id}"
        for item_id in report.get("missed_items", [])
        if isinstance(item_id, str)
    ]
    return [reference for reference in expected_references if reference not in covered_references]


def _rubric_reference_coverage_ratio(report: dict[str, Any], missing_rubric_references: list[str]) -> float:
    missed_items = [item_id for item_id in report.get("missed_items", []) if isinstance(item_id, str)]
    if not missed_items:
        return 1.0
    covered_count = len(missed_items) - len(missing_rubric_references)
    return covered_count / len(missed_items)


def _missing_explanation_references(case_id: str, report: dict[str, Any], source_reference_items: Any) -> list[str]:
    covered_references = {
        item["reference"]
        for item in source_reference_items
        if isinstance(item, dict) and isinstance(item.get("reference"), str)
    }
    expected_explanations = _expected_missing_explanation_references(report)
    explanation_source_items = report.get("explanation_source_items", [])
    if not isinstance(explanation_source_items, list) or not explanation_source_items:
        if expected_explanations:
            return expected_explanations
        return []

    missing_references: list[str] = []
    covered_explanations: list[str] = []
    for item in explanation_source_items:
        if not isinstance(item, dict):
            missing_references.append("explanation:invalid:item")
            continue
        kind = item.get("kind") if isinstance(item.get("kind"), str) else "unknown"
        rubric_item_id = item.get("rubric_item_id")
        if not isinstance(rubric_item_id, str) or not rubric_item_id:
            missing_references.append(f"explanation:{kind}:missing_rubric_item_id")
            continue
        explanation_reference = f"explanation:{kind}:{rubric_item_id}"
        expected_reference = f"rubric:{case_id}_rubric.item.{rubric_item_id}"
        source_references = item.get("source_references", [])
        if not isinstance(source_references, list):
            source_references = []
        if expected_reference not in source_references or expected_reference not in covered_references:
            missing_references.append(explanation_reference)
        else:
            covered_explanations.append(explanation_reference)

    for expected_explanation in expected_explanations:
        if expected_explanation not in covered_explanations and expected_explanation not in missing_references:
            missing_references.append(expected_explanation)
    return missing_references


def _explanation_reference_coverage_ratio(report: dict[str, Any], missing_explanation_references: list[str]) -> float:
    explanation_source_items = report.get("explanation_source_items", [])
    expected_count = len(_expected_missing_explanation_references(report))
    if expected_count > 0:
        total_count = expected_count
    elif isinstance(explanation_source_items, list) and explanation_source_items:
        total_count = len(explanation_source_items)
    elif _report_has_explanation_text(report):
        return 0.0
    else:
        return 1.0
    covered_count = max(total_count - len(missing_explanation_references), 0)
    return covered_count / total_count


def _missing_evidence_references(report: dict[str, Any], source_reference_items: Any) -> list[str]:
    covered_references = {
        item["reference"]
        for item in source_reference_items
        if isinstance(item, dict) and isinstance(item.get("reference"), str)
    }
    expected_by_rubric_item = _expected_evidence_references_by_rubric_item(report)
    explanation_source_items = report.get("explanation_source_items", [])
    if not isinstance(explanation_source_items, list) or not explanation_source_items:
        return _expected_evidence_references(report)

    missing_references: list[str] = []
    covered_rubric_items: list[str] = []
    for item in explanation_source_items:
        if not isinstance(item, dict):
            continue
        rubric_item_id = item.get("rubric_item_id")
        if not isinstance(rubric_item_id, str) or not rubric_item_id:
            continue
        covered_rubric_items.append(rubric_item_id)
        source_references = item.get("source_references", [])
        if not isinstance(source_references, list):
            source_references = []
        for expected_reference in expected_by_rubric_item.get(rubric_item_id, []):
            if expected_reference not in source_references or expected_reference not in covered_references:
                _append_unique(missing_references, expected_reference)

    for rubric_item_id, expected_references in expected_by_rubric_item.items():
        if rubric_item_id in covered_rubric_items:
            continue
        for expected_reference in expected_references:
            _append_unique(missing_references, expected_reference)
    return missing_references


def _evidence_reference_coverage_ratio(report: dict[str, Any], missing_evidence_references: list[str]) -> float:
    expected_references = _expected_evidence_references(report)
    if not expected_references:
        return 1.0
    covered_count = max(len(expected_references) - len(missing_evidence_references), 0)
    return covered_count / len(expected_references)


def _expected_evidence_references(report: dict[str, Any]) -> list[str]:
    expected_references: list[str] = []
    for references in _expected_evidence_references_by_rubric_item(report).values():
        for reference in references:
            _append_unique(expected_references, reference)
    return expected_references


def _expected_evidence_references_by_rubric_item(report: dict[str, Any]) -> dict[str, list[str]]:
    expected_by_rubric_item: dict[str, list[str]] = {}
    dimension_traces = report.get("dimension_traces", {})
    if isinstance(dimension_traces, dict):
        for traces in dimension_traces.values():
            if not isinstance(traces, list):
                continue
            for trace in traces:
                if not isinstance(trace, dict) or trace.get("match_kind") == "intent_keyword":
                    continue
                rubric_item_id = trace.get("rubric_item_id")
                if not isinstance(rubric_item_id, str) or not rubric_item_id:
                    continue
                _append_evidence_references(expected_by_rubric_item, rubric_item_id, trace.get("matched_evidence", []))

    rubric_scores = report.get("rubric_scores", {})
    if isinstance(rubric_scores, dict):
        for item_id, item_score in rubric_scores.items():
            if not isinstance(item_id, str) or not isinstance(item_score, dict):
                continue
            _append_evidence_references(expected_by_rubric_item, item_id, item_score.get("covered_evidence", []))
    return expected_by_rubric_item


def _append_evidence_references(
    expected_by_rubric_item: dict[str, list[str]],
    rubric_item_id: str,
    evidence_items: Any,
) -> None:
    if not isinstance(evidence_items, list):
        return
    for evidence in evidence_items:
        if not isinstance(evidence, str) or not evidence:
            continue
        _append_unique(expected_by_rubric_item.setdefault(rubric_item_id, []), f"evidence:{evidence}")


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def _report_has_explanation_text(report: dict[str, Any]) -> bool:
    return bool(report.get("strengths") or report.get("reasoning_errors") or report.get("llm_reasoning_feedback"))


def _expected_missing_explanation_references(report: dict[str, Any]) -> list[str]:
    expected_references: list[str] = []
    rubric_scores = report.get("rubric_scores", {})
    if not isinstance(rubric_scores, dict):
        return expected_references
    for item_id, item_score in rubric_scores.items():
        if not isinstance(item_id, str) or not isinstance(item_score, dict):
            continue
        if item_score.get("score", 0) > 0:
            expected_references.append(f"explanation:strength:{item_id}")
        if (
            item_score.get("dimension_id") in {"differential_diagnosis", "reasoning"}
            and item_score.get("score", 0) < item_score.get("max_score", 0)
        ):
            expected_references.append(f"explanation:reasoning_error:{item_id}")
        if "rationale" in item_score:
            expected_references.append(f"explanation:llm_reasoning_feedback:{item_id}")
    return expected_references


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
