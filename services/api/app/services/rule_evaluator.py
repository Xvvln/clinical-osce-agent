from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml

from app.models.rubric import LlmRubricRequest, LlmRubricResponse, ScoreTrace

ROOT_DIR = Path(__file__).resolve().parents[4]
RUBRICS_DIR = ROOT_DIR / "data" / "rubrics"


class RuleEvaluationSession(Protocol):
    session_id: str
    case_id: str
    asked_questions: list[str]
    requested_exams: list[str]
    requested_tests: list[str]
    final_submission: dict[str, str] | None
    revealed_facts: list[str]


LlmRubricScorer = Callable[[LlmRubricRequest], LlmRubricResponse]


@dataclass(frozen=True)
class RuleEvaluationReport:
    session_id: str
    case_id: str
    total_score: int
    dimension_scores: dict[str, int]
    dimension_traces: dict[str, list[ScoreTrace]]
    rubric_scores: dict[str, dict[str, Any]]
    missed_items: list[str]
    feedback_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "case_id": self.case_id,
            "total_score": self.total_score,
            "dimension_scores": self.dimension_scores,
            "dimension_traces": {
                dimension_id: [trace.model_dump() for trace in traces]
                for dimension_id, traces in self.dimension_traces.items()
            },
            "rubric_scores": self.rubric_scores,
            "missed_items": self.missed_items,
            "feedback_summary": self.feedback_summary,
        }


def evaluate_session_rules(
    session: RuleEvaluationSession,
    llm_scorer: LlmRubricScorer | None = None,
) -> dict[str, Any]:
    rubric = _load_rubric(session.case_id)
    dimension_scores: dict[str, int] = {}
    dimension_traces: dict[str, list[ScoreTrace]] = {}
    rubric_scores: dict[str, dict[str, Any]] = {}
    missed_items: list[str] = []

    for dimension in rubric["dimensions"]:
        dimension_id = dimension["dimension_id"]
        dimension_score = 0
        traces: list[ScoreTrace] = []
        for item in dimension["items"]:
            item_id = item["item_id"]
            item_result = evaluate_rubric_item(session, item, llm_scorer=llm_scorer)
            trace = item_result.pop("trace")
            score = trace.awarded_score
            max_score = int(item["max_score"])
            if score == 0:
                missed_items.append(item_id)
            dimension_score += score
            traces.append(trace)
            rubric_scores[item_id] = {
                "score": score,
                "max_score": max_score,
                "dimension_id": dimension_id,
                "description": item["description"],
                **item_result,
            }
        dimension_scores[dimension_id] = dimension_score
        dimension_traces[dimension_id] = traces

    return RuleEvaluationReport(
        session_id=session.session_id,
        case_id=session.case_id,
        total_score=sum(dimension_scores.values()),
        dimension_scores=dimension_scores,
        dimension_traces=dimension_traces,
        rubric_scores=rubric_scores,
        missed_items=missed_items,
        feedback_summary="已完成规则评分，LLM 评分维度将在后续阶段补充。",
    ).to_dict()


def _load_rubric(case_id: str) -> dict[str, Any]:
    rubric_path = RUBRICS_DIR / f"{case_id}_rubric.yaml"
    return yaml.safe_load(rubric_path.read_text(encoding="utf-8"))


def evaluate_rubric_item(
    session: RuleEvaluationSession,
    item: dict[str, Any],
    llm_scorer: LlmRubricScorer | None = None,
) -> dict[str, Any]:
    match_rule = item["match_rule"]
    kind = match_rule["kind"]
    spec = match_rule["spec"]
    max_score = int(item["max_score"])

    if kind == "intent_keyword":
        matched_keywords = [keyword for keyword in spec["any_of_keywords"] if keyword in "\n".join(session.asked_questions)]
        matched_questions = [question for question in session.asked_questions if any(keyword in question for keyword in matched_keywords)]
        score = max_score if matched_keywords else 0
        return {"trace": _build_score_trace(item, score, matched_questions)}
    if kind == "exam_code":
        matched_evidence = [spec["exam_code"]] if spec["exam_code"] in session.requested_exams else []
        score = max_score if matched_evidence else 0
        return {"trace": _build_score_trace(item, score, matched_evidence)}
    if kind == "test_code":
        matched_evidence = [spec["test_code"]] if spec["test_code"] in session.requested_tests else []
        score = max_score if matched_evidence else 0
        return {"trace": _build_score_trace(item, score, matched_evidence)}
    if kind == "diagnosis_concept":
        matched_evidence = [session.final_submission["diagnosis"]] if _diagnosis_matches(session, spec) and session.final_submission else []
        score = max_score if matched_evidence else 0
        return {"trace": _build_score_trace(item, score, matched_evidence)}
    if kind == "reasoning_coverage":
        score = _score_reasoning_coverage(session, spec, max_score)
        return {"trace": _build_score_trace(item, score, _covered_reasoning_evidence(session, spec["required_evidence"]))}
    if kind == "llm_rubric" and llm_scorer is not None:
        return _evaluate_llm_rubric(session, item, llm_scorer)
    return {"trace": _build_score_trace(item, 0, [])}


def score_rubric_item(
    session: RuleEvaluationSession,
    item: dict[str, Any],
    llm_scorer: LlmRubricScorer | None = None,
) -> int:
    return evaluate_rubric_item(session, item, llm_scorer=llm_scorer)["trace"].awarded_score


def _build_score_trace(
    item: dict[str, Any],
    awarded_score: int,
    matched_evidence: list[str],
    llm_rationale: str | None = None,
) -> ScoreTrace:
    return ScoreTrace(
        rubric_item_id=item["item_id"],
        awarded_score=awarded_score,
        max_score=int(item["max_score"]),
        match_kind=item["match_rule"]["kind"],
        matched_evidence=matched_evidence,
        llm_rationale=llm_rationale,
    )


def _diagnosis_matches(session: RuleEvaluationSession, spec: dict[str, Any]) -> bool:
    if not session.final_submission:
        return False
    diagnosis = session.final_submission["diagnosis"].lower()
    concepts = [spec["target"], *spec.get("synonyms", [])]
    return any(concept.lower() in diagnosis for concept in concepts)


def _evaluate_llm_rubric(
    session: RuleEvaluationSession,
    item: dict[str, Any],
    llm_scorer: LlmRubricScorer,
) -> dict[str, Any]:
    if not session.final_submission:
        return {"trace": _build_score_trace(item, 0, [])}
    response = llm_scorer(
        LlmRubricRequest(
            rubric_item_id=item["item_id"],
            description=item["description"],
            max_score=int(item["max_score"]),
            student_final_reasoning=session.final_submission["reasoning"],
            relevant_facts_revealed=session.revealed_facts,
            required_evidence=item.get("evidence_expected", []),
        )
    )
    score = min(response.score, int(item["max_score"]))
    return {
        "trace": _build_score_trace(item, score, response.covered_evidence, response.rationale),
        "covered_evidence": response.covered_evidence,
        "missing_evidence": response.missing_evidence,
        "rationale": response.rationale,
    }


def _score_reasoning_coverage(session: RuleEvaluationSession, spec: dict[str, Any], max_score: int) -> int:
    required_evidence = spec["required_evidence"]
    if not required_evidence:
        return 0
    covered_count = len(_covered_reasoning_evidence(session, required_evidence))
    coverage_ratio = covered_count / len(required_evidence)
    min_coverage_ratio = float(spec.get("min_coverage_ratio", 0.6))
    if coverage_ratio >= min_coverage_ratio:
        return max_score
    return int(max_score * coverage_ratio)


def _covered_reasoning_evidence(session: RuleEvaluationSession, required_evidence: list[str]) -> list[str]:
    return [evidence for evidence in required_evidence if _evidence_is_covered(session, evidence)]


def _evidence_is_covered(session: RuleEvaluationSession, evidence: str) -> bool:
    if evidence in session.requested_exams or evidence in session.requested_tests:
        return True
    if not session.final_submission:
        return False
    reasoning = session.final_submission["reasoning"]
    return evidence in reasoning
