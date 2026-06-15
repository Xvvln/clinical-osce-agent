from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml
from pydantic import ValidationError

from app.models.rubric import LlmRubricRequest, LlmRubricResponse, ScoreTrace
from app.services.humanistic_evaluator import (
    HumanisticEmbeddingClient,
    HumanisticSemanticReviewer,
    ScoringLedger,
    SemanticAnchorMatcher,
    TrainingEvent,
    build_humanistic_embedding_client_from_environment,
    build_training_event_stream,
    create_default_humanistic_semantic_reviewer,
    detect_missed_opportunities,
    event_key,
    load_anchor_bank,
)

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
    messages: list[dict[str, str]]
    action_timeline: list[dict[str, Any]]


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
    score_groups: dict[str, dict[str, int]]
    training_event_stream: list[dict[str, Any]]
    scoring_ledger: dict[str, Any]
    missed_opportunities: list[dict[str, Any]]
    training_gaps: list[dict[str, Any]]
    humanistic_anchor_candidates: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "case_id": self.case_id,
            "total_score": self.total_score,
            "dimension_scores": self.dimension_scores,
            "dimension_traces": {
                dimension_id: [trace.model_dump(exclude_none=True) for trace in traces]
                for dimension_id, traces in self.dimension_traces.items()
            },
            "rubric_scores": self.rubric_scores,
            "missed_items": self.missed_items,
            "feedback_summary": self.feedback_summary,
            "score_groups": self.score_groups,
            "training_event_stream": self.training_event_stream,
            "scoring_ledger": self.scoring_ledger,
            "missed_opportunities": self.missed_opportunities,
            "training_gaps": self.training_gaps,
            "humanistic_anchor_candidates": self.humanistic_anchor_candidates,
        }


def evaluate_session_rules(
    session: RuleEvaluationSession,
    llm_scorer: LlmRubricScorer | None = None,
    humanistic_embedding_client: HumanisticEmbeddingClient | None = None,
    humanistic_semantic_reviewer: HumanisticSemanticReviewer | None = None,
) -> dict[str, Any]:
    rubric = _load_rubric(session.case_id)
    dimension_scores: dict[str, int] = {}
    dimension_traces: dict[str, list[ScoreTrace]] = {}
    rubric_scores: dict[str, dict[str, Any]] = {}
    missed_items: list[str] = []
    training_gaps: list[dict[str, Any]] = []
    event_stream = build_training_event_stream(session)
    anchor_bank = load_anchor_bank()
    if humanistic_embedding_client is None:
        humanistic_embedding_client = build_humanistic_embedding_client_from_environment()
    if humanistic_semantic_reviewer is None:
        humanistic_semantic_reviewer = create_default_humanistic_semantic_reviewer()
    semantic_matcher = SemanticAnchorMatcher(
        anchor_bank,
        embedding_client=humanistic_embedding_client,
        reviewer=humanistic_semantic_reviewer,
    )
    scoring_ledger = ScoringLedger()

    for dimension in rubric["dimensions"]:
        dimension_id = dimension["dimension_id"]
        dimension_score = 0
        traces: list[ScoreTrace] = []
        for item in dimension["items"]:
            item_id = item["item_id"]
            item_result = evaluate_rubric_item(
                session,
                item,
                llm_scorer=llm_scorer,
                event_stream=event_stream,
                semantic_matcher=semantic_matcher,
                scoring_ledger=scoring_ledger,
            )
            trace = item_result.pop("trace")
            score = trace.awarded_score
            max_score = int(item["max_score"])
            if score < max_score:
                missed_items.append(item_id)
                training_gaps.append(_training_gap_from_trace(dimension_id, item, trace, gap_source="rubric_item"))
            dimension_score += score
            traces.append(trace)
            rubric_scores[item_id] = {
                "score": score,
                "max_score": max_score,
                "dimension_id": dimension_id,
                "description": item["description"],
                "trace": trace.model_dump(exclude_none=True),
                **item_result,
            }
        dimension_scores[dimension_id] = dimension_score
        dimension_traces[dimension_id] = traces

    missed_opportunities = detect_missed_opportunities(event_stream)
    for missed_opportunity in missed_opportunities:
        training_gaps.append(_training_gap_from_missed_opportunity(missed_opportunity))

    return RuleEvaluationReport(
        session_id=session.session_id,
        case_id=session.case_id,
        total_score=sum(dimension_scores.values()),
        dimension_scores=dimension_scores,
        dimension_traces=dimension_traces,
        rubric_scores=rubric_scores,
        missed_items=_unique_strings(missed_items),
        feedback_summary="已完成规则评分，LLM 评分维度将在后续阶段补充。",
        score_groups=_score_groups(dimension_scores),
        training_event_stream=[event.__dict__ for event in event_stream],
        scoring_ledger=scoring_ledger.to_dict(),
        missed_opportunities=missed_opportunities,
        training_gaps=training_gaps,
        humanistic_anchor_candidates=_humanistic_anchor_candidates(dimension_traces),
    ).to_dict()


def _load_rubric(case_id: str) -> dict[str, Any]:
    rubric_path = RUBRICS_DIR / f"{case_id}_rubric.yaml"
    return yaml.safe_load(rubric_path.read_text(encoding="utf-8"))


def evaluate_rubric_item(
    session: RuleEvaluationSession,
    item: dict[str, Any],
    llm_scorer: LlmRubricScorer | None = None,
    event_stream: list[TrainingEvent] | None = None,
    semantic_matcher: SemanticAnchorMatcher | None = None,
    scoring_ledger: ScoringLedger | None = None,
) -> dict[str, Any]:
    item_id = item["item_id"]
    match_rule = item["match_rule"]
    kind = match_rule["kind"]
    spec = match_rule["spec"]
    max_score = int(item["max_score"])

    if kind == "intent_keyword":
        matched_keywords = [keyword for keyword in spec["any_of_keywords"] if keyword in "\n".join(session.asked_questions)]
        matched_questions = [question for question in session.asked_questions if any(keyword in question for keyword in matched_keywords)]
        matched_revealed_facts = _matched_revealed_expected_evidence(session, item)
        matched_evidence = [*matched_questions, *matched_revealed_facts]
        score = max_score if matched_keywords or matched_revealed_facts else 0
        return {"trace": _build_score_trace(item, score, matched_evidence)}
    if kind == "exam_code":
        matched_evidence = [spec["exam_code"]] if spec["exam_code"] in session.requested_exams else []
        score = max_score if matched_evidence else 0
        return {"trace": _build_score_trace(item, score, matched_evidence)}
    if kind == "test_code":
        matched_evidence = [spec["test_code"]] if spec["test_code"] in session.requested_tests else []
        score = max_score if matched_evidence else 0
        return {"trace": _build_score_trace(item, score, matched_evidence)}
    if kind == "diagnosis_concept":
        matched_evidence = _matched_diagnosis_concept_evidence(session, item_id, spec)
        score = max_score if matched_evidence else 0
        return {"trace": _build_score_trace(item, score, matched_evidence)}
    if kind == "reasoning_coverage":
        score = _score_reasoning_coverage(session, spec, max_score)
        return {"trace": _build_score_trace(item, score, _covered_reasoning_evidence(session, spec["required_evidence"]))}
    if kind == "llm_rubric" and llm_scorer is not None:
        return _evaluate_llm_rubric(session, item, llm_scorer)
    if kind == "dialogue_act":
        return _evaluate_dialogue_act(item, spec, event_stream or [], scoring_ledger)
    if kind == "semantic_anchor":
        return _evaluate_semantic_anchor(
            item,
            spec,
            event_stream or [],
            semantic_matcher or SemanticAnchorMatcher(load_anchor_bank()),
            scoring_ledger,
        )
    if kind == "sequence_check":
        return _evaluate_sequence_check(
            item,
            spec,
            event_stream or [],
            semantic_matcher or SemanticAnchorMatcher(load_anchor_bank()),
            scoring_ledger,
        )
    if kind == "triggered_response":
        return _evaluate_triggered_response(
            item,
            spec,
            event_stream or [],
            semantic_matcher or SemanticAnchorMatcher(load_anchor_bank()),
            scoring_ledger,
        )
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
    fallback_reason: str | None = None,
    **extra: Any,
) -> ScoreTrace:
    return ScoreTrace(
        rubric_item_id=item["item_id"],
        awarded_score=awarded_score,
        max_score=int(item["max_score"]),
        match_kind=item["match_rule"]["kind"],
        matched_evidence=matched_evidence,
        llm_rationale=llm_rationale,
        fallback_reason=fallback_reason,
        gap_type=item.get("gap_type") if awarded_score < int(item["max_score"]) else None,
        stage=item.get("stage"),
        next_training_action=item.get("next_training_action"),
        ethics_principle=item.get("ethics_principle"),
        **extra,
    )


def _evaluate_dialogue_act(
    item: dict[str, Any],
    spec: dict[str, Any],
    event_stream: list[TrainingEvent],
    scoring_ledger: ScoringLedger | None,
) -> dict[str, Any]:
    keywords = [str(keyword) for keyword in spec.get("any_of_keywords", []) if str(keyword)]
    for event in _student_events(event_stream):
        if not any(keyword in event.content for keyword in keywords):
            continue
        key = event_key(event)
        if scoring_ledger and not scoring_ledger.can_award(str(item["item_id"]), key):
            continue
        if scoring_ledger:
            scoring_ledger.award(str(item["item_id"]), key)
        return {
            "trace": _build_score_trace(
                item,
                int(item["max_score"]),
                [event.content],
                match_method="dialogue_act",
                matched_turn_index=event.turn_index,
            )
        }
    return {"trace": _build_score_trace(item, 0, [], match_method="dialogue_act")}


def _evaluate_semantic_anchor(
    item: dict[str, Any],
    spec: dict[str, Any],
    event_stream: list[TrainingEvent],
    semantic_matcher: SemanticAnchorMatcher,
    scoring_ledger: ScoringLedger | None,
) -> dict[str, Any]:
    anchor_id = str(spec["anchor_id"])
    best: tuple[TrainingEvent, dict[str, Any]] | None = None
    for event in _student_events(event_stream):
        result = semantic_matcher.match(event.content, anchor_id)
        if best is None or float(result["semantic_score"]) > float(best[1]["semantic_score"]):
            best = (event, result)
    if best is None:
        return {"trace": _build_score_trace(item, 0, [], match_method="semantic_anchor")}
    event, result = best
    score = int(item["max_score"]) if result["matched"] else 0
    key = event_key(event)
    if score and scoring_ledger and not scoring_ledger.can_award(str(item["item_id"]), key):
        score = 0
    elif score and scoring_ledger:
        scoring_ledger.award(str(item["item_id"]), key)
    return {
        "trace": _build_score_trace(
            item,
            score,
            [event.content] if score else [],
            match_method=str(result["match_method"]),
            semantic_score=float(result["semantic_score"]),
            anchor_id=anchor_id,
            positive_anchor=result.get("positive_anchor"),
            negative_anchor=result.get("negative_anchor"),
            candidate_evidence=event.content,
            anchor_bank_version=str(result.get("anchor_bank_version") or ""),
            llm_review_status=result.get("llm_review_status"),
            matched_turn_index=event.turn_index if score else None,
        )
    }


def _evaluate_sequence_check(
    item: dict[str, Any],
    spec: dict[str, Any],
    event_stream: list[TrainingEvent],
    semantic_matcher: SemanticAnchorMatcher,
    scoring_ledger: ScoringLedger | None,
) -> dict[str, Any]:
    action_types = {str(action_type) for action_type in spec.get("action_types", []) if str(action_type)}
    actions = [event for event in event_stream if event.event_type in action_types]
    if not actions:
        return {"trace": _build_score_trace(item, 0, [], match_method="sequence_check", timing_status="missing_action")}
    action = actions[0]
    window = int(spec.get("window_student_turns", 2))
    before_events = [
        event for event in _student_events(event_stream)
        if action.turn_index - window <= event.turn_index <= action.turn_index
    ]
    after_events = [
        event for event in _student_events(event_stream)
        if action.turn_index < event.turn_index <= action.turn_index + window
    ]
    before_events = _events_matching_required_keywords(before_events, spec)
    after_events = _events_matching_required_keywords(after_events, spec)
    before_match = _best_semantic_event(before_events, str(spec["anchor_id"]), semantic_matcher)
    if before_match and before_match[1]["matched"]:
        event, result = before_match
        key = event_key(event)
        if scoring_ledger and scoring_ledger.can_award(str(item["item_id"]), key):
            scoring_ledger.award(str(item["item_id"]), key)
            return {
                "trace": _build_score_trace(
                    item,
                    int(item["max_score"]),
                    [event.content],
                    match_method="sequence_check",
                    semantic_score=float(result["semantic_score"]),
                    anchor_id=str(spec["anchor_id"]),
                    positive_anchor=result.get("positive_anchor"),
                    negative_anchor=result.get("negative_anchor"),
                    candidate_evidence=event.content,
                    anchor_bank_version=str(result.get("anchor_bank_version") or ""),
                    llm_review_status=result.get("llm_review_status"),
                    timing_status="before_action",
                    required_before_action=action.event_type,
                    matched_turn_index=event.turn_index,
                    action_turn_index=action.turn_index,
                )
            }
    after_match = _best_semantic_event(after_events, str(spec["anchor_id"]), semantic_matcher)
    if after_match and after_match[1]["matched"]:
        event, result = after_match
        return {
            "trace": _build_score_trace(
                item,
                max(0, int(item["max_score"]) // 2),
                [event.content],
                match_method="sequence_check",
                semantic_score=float(result["semantic_score"]),
                anchor_id=str(spec["anchor_id"]),
                positive_anchor=result.get("positive_anchor"),
                negative_anchor=result.get("negative_anchor"),
                candidate_evidence=event.content,
                anchor_bank_version=str(result.get("anchor_bank_version") or ""),
                llm_review_status=result.get("llm_review_status"),
                timing_status="late",
                required_before_action=action.event_type,
                matched_turn_index=event.turn_index,
                action_turn_index=action.turn_index,
                timing_gap_type=str(item.get("gap_type") or ""),
            )
        }
    return {
        "trace": _build_score_trace(
            item,
            0,
            [],
            match_method="sequence_check",
            timing_status="missing",
            required_before_action=action.event_type,
            action_turn_index=action.turn_index,
            timing_gap_type=str(item.get("gap_type") or ""),
        )
    }


def _evaluate_triggered_response(
    item: dict[str, Any],
    spec: dict[str, Any],
    event_stream: list[TrainingEvent],
    semantic_matcher: SemanticAnchorMatcher,
    scoring_ledger: ScoringLedger | None,
) -> dict[str, Any]:
    triggers = [str(keyword) for keyword in spec.get("trigger_keywords", []) if str(keyword)]
    window = int(spec.get("response_window_turns", 2))
    for trigger_event in event_stream:
        if trigger_event.role != "patient" or not any(keyword in trigger_event.content for keyword in triggers):
            continue
        candidate_events = [
            event for event in _student_events(event_stream)
            if trigger_event.turn_index < event.turn_index <= trigger_event.turn_index + window
        ]
        match = _best_semantic_event(candidate_events, str(spec["anchor_id"]), semantic_matcher)
        if not match or not match[1]["matched"]:
            continue
        event, result = match
        key = f"{trigger_event.turn_index}->{event_key(event)}"
        if scoring_ledger and not scoring_ledger.can_award(str(item["item_id"]), key):
            continue
        if scoring_ledger:
            scoring_ledger.award(str(item["item_id"]), key)
        return {
            "trace": _build_score_trace(
                item,
                int(item["max_score"]),
                [event.content],
                match_method="triggered_response",
                semantic_score=float(result["semantic_score"]),
                anchor_id=str(spec["anchor_id"]),
                positive_anchor=result.get("positive_anchor"),
                negative_anchor=result.get("negative_anchor"),
                candidate_evidence=event.content,
                anchor_bank_version=str(result.get("anchor_bank_version") or ""),
                llm_review_status=result.get("llm_review_status"),
                matched_turn_index=event.turn_index,
            )
        }
    return {"trace": _build_score_trace(item, 0, [], match_method="triggered_response")}


def _best_semantic_event(
    events: list[TrainingEvent],
    anchor_id: str,
    semantic_matcher: SemanticAnchorMatcher,
) -> tuple[TrainingEvent, dict[str, Any]] | None:
    best: tuple[TrainingEvent, dict[str, Any]] | None = None
    for event in events:
        result = semantic_matcher.match(event.content, anchor_id)
        if best is None or float(result["semantic_score"]) > float(best[1]["semantic_score"]):
            best = (event, result)
    return best


def _student_events(event_stream: list[TrainingEvent]) -> list[TrainingEvent]:
    return [event for event in event_stream if event.role == "student" and event.event_type == "student_utterance"]


def _events_matching_required_keywords(events: list[TrainingEvent], spec: dict[str, Any]) -> list[TrainingEvent]:
    keywords = [str(keyword) for keyword in spec.get("required_keywords_any", []) if str(keyword)]
    if not keywords:
        return events
    return [event for event in events if any(keyword in event.content for keyword in keywords)]


def _matched_revealed_expected_evidence(
    session: RuleEvaluationSession,
    item: dict[str, Any],
) -> list[str]:
    expected_evidence = item.get("evidence_expected", [])
    if not isinstance(expected_evidence, list):
        return []
    revealed_fact_ids = set(session.revealed_facts)
    return [str(evidence) for evidence in expected_evidence if str(evidence) in revealed_fact_ids]


def _matched_diagnosis_concept_evidence(
    session: RuleEvaluationSession,
    item_id: str,
    spec: dict[str, Any],
) -> list[str]:
    if not session.final_submission:
        return []
    concepts = [spec["target"], *spec.get("synonyms", [])]
    source_texts = [session.final_submission["diagnosis"]]
    if item_id.startswith("dxd_"):
        source_texts.append(session.final_submission["reasoning"])
    return [text for text in source_texts if _text_contains_any_concept(text, concepts)]


def _text_contains_any_concept(text: str, concepts: list[str]) -> bool:
    normalized_text = text.lower()
    return any(concept.lower() in normalized_text for concept in concepts)


def _evaluate_llm_rubric(
    session: RuleEvaluationSession,
    item: dict[str, Any],
    llm_scorer: LlmRubricScorer,
) -> dict[str, Any]:
    if not session.final_submission:
        return {"trace": _build_score_trace(item, 0, [])}
    request = LlmRubricRequest(
        rubric_item_id=item["item_id"],
        description=item["description"],
        max_score=int(item["max_score"]),
        student_final_reasoning=session.final_submission["reasoning"],
        relevant_facts_revealed=session.revealed_facts,
        required_evidence=item.get("evidence_expected", []),
    )
    try:
        response = llm_scorer(request)
    except ValidationError:
        missing_evidence = list(request.required_evidence)
        rationale = "模型评分输出结构不完整，已按未覆盖处理。"
        return {
            "trace": _build_score_trace(
                item,
                0,
                [],
                rationale,
                fallback_reason="llm_rubric_invalid_response",
            ),
            "covered_evidence": [],
            "missing_evidence": missing_evidence,
            "rationale": rationale,
        }
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


CLINICAL_DIMENSIONS = {
    "history_taking",
    "physical_exam",
    "auxiliary_test",
    "main_diagnosis",
    "differential_diagnosis",
    "reasoning",
}
HUMANISTIC_DIMENSIONS = {
    "narrative_medicine",
    "communication_skill",
    "medical_ethics",
    "relationship_building",
}


def _score_groups(dimension_scores: dict[str, int]) -> dict[str, dict[str, int]]:
    return {
        "clinical_osce": {
            "score": sum(score for dimension_id, score in dimension_scores.items() if dimension_id in CLINICAL_DIMENSIONS),
            "max_score": 70,
        },
        "humanistic_communication": {
            "score": sum(score for dimension_id, score in dimension_scores.items() if dimension_id in HUMANISTIC_DIMENSIONS),
            "max_score": 30,
        },
    }


def _training_gap_from_trace(
    dimension_id: str,
    item: dict[str, Any],
    trace: ScoreTrace,
    *,
    gap_source: str,
) -> dict[str, Any]:
    missing_score = max(0, trace.max_score - trace.awarded_score)
    gap_type = trace.gap_type or str(item.get("gap_type") or f"{item['item_id']}_missing")
    return {
        "dimension_id": dimension_id,
        "rubric_item_id": str(item["item_id"]),
        "gap_type": gap_type,
        "label": str(item.get("description") or item["item_id"]),
        "stage": str(trace.stage or item.get("stage") or ""),
        "trigger_stage": str(trace.stage or item.get("stage") or ""),
        "missing_score": missing_score,
        "severity": _gap_severity(missing_score, trace.max_score, dimension_id),
        "evidence_summary": _gap_evidence_summary(trace),
        "next_training_action": str(item.get("next_training_action") or "下一轮训练中补齐该评分点。"),
        "skill_type": str(item.get("skill_type") or _default_skill_type(dimension_id)),
        "gap_source": gap_source,
        "source_trace": trace.model_dump(exclude_none=True),
        "recovered": False,
    }


def _training_gap_from_missed_opportunity(missed_opportunity: dict[str, Any]) -> dict[str, Any]:
    return {
        "dimension_id": "relationship_building",
        "rubric_item_id": "",
        "gap_type": str(missed_opportunity.get("gap_type") or "missed_opportunity"),
        "label": "错失患者沟通信号",
        "stage": str(missed_opportunity.get("stage") or ""),
        "trigger_stage": str(missed_opportunity.get("stage") or ""),
        "missing_score": 2,
        "severity": "medium",
        "evidence_summary": str(missed_opportunity.get("trigger_evidence") or ""),
        "next_training_action": str(missed_opportunity.get("next_training_action") or ""),
        "skill_type": "relationship_repair",
        "gap_source": "missed_opportunity",
        "source_trace": dict(missed_opportunity),
        "recovered": False,
    }


def _humanistic_anchor_candidates(dimension_traces: dict[str, list[ScoreTrace]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for dimension_id, traces in dimension_traces.items():
        if dimension_id not in HUMANISTIC_DIMENSIONS:
            continue
        for trace in traces:
            if not trace.anchor_id or not trace.llm_review_status:
                continue
            candidate_text = trace.candidate_evidence or (trace.matched_evidence[0] if trace.matched_evidence else "")
            if not candidate_text:
                continue
            candidates.append(
                {
                    "candidate_id": f"{trace.rubric_item_id}:{trace.anchor_id}:{trace.matched_turn_index or 'unknown'}",
                    "dimension_id": dimension_id,
                    "rubric_item_id": trace.rubric_item_id,
                    "anchor_id": trace.anchor_id,
                    "candidate_text": candidate_text,
                    "semantic_score": trace.semantic_score,
                    "review_status": trace.llm_review_status,
                    "status": "candidate" if trace.llm_review_status == "uncertain" else "reviewed",
                    "positive_anchor": trace.positive_anchor,
                    "negative_anchor": trace.negative_anchor,
                    "match_method": trace.match_method,
                    "anchor_bank_version": trace.anchor_bank_version,
                }
            )
    return candidates


def _gap_evidence_summary(trace: ScoreTrace) -> str:
    if trace.matched_evidence:
        return "；".join(trace.matched_evidence)
    if trace.timing_status == "late":
        return "相关表达发生在动作之后，不能作为事前沟通满分证据。"
    return "评分轨迹未找到足够证据。"


def _gap_severity(missing_score: int, max_score: int, dimension_id: str) -> str:
    if dimension_id == "medical_ethics":
        return "high"
    if missing_score >= max_score:
        return "medium"
    return "low"


def _default_skill_type(dimension_id: str) -> str:
    return {
        "narrative_medicine": "narrative_perspective",
        "communication_skill": "communication_structure",
        "medical_ethics": "ethics_consent",
        "relationship_building": "relationship_repair",
    }.get(dimension_id, "reasoning_bridge")


def _unique_strings(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    return unique_values
