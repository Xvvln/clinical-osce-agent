from app.models.rubric import LlmRubricRequest, LlmRubricResponse, ScoreTrace
from app.services.osce_session_service import OsceSession
from app.services.rule_evaluator import evaluate_session_rules, score_rubric_item


def test_rule_evaluator_scores_deterministic_rubric_items() -> None:
    session = OsceSession(
        session_id="session_demo",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="diagnosis_submission",
        asked_questions=["什么时候开始疼的？"],
        revealed_facts=["appendicitis_001.hf_01"],
        requested_exams=["abd.palpation.rebound"],
        requested_tests=["lab.cbc"],
        final_submission={
            "diagnosis": "急性阑尾炎",
            "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
        },
    )

    report = evaluate_session_rules(session)

    assert report["session_id"] == "session_demo"
    assert report["case_id"] == "appendicitis_001"
    assert report["total_score"] == 55
    assert report["dimension_scores"] == {
        "history_taking": 10,
        "physical_exam": 15,
        "auxiliary_test": 15,
        "main_diagnosis": 15,
        "differential_diagnosis": 0,
        "reasoning": 0,
    }
    assert report["rubric_scores"]["ht_onset"]["score"] == 10
    assert report["rubric_scores"]["ht_location"]["score"] == 0
    assert report["rubric_scores"]["pe_rebound"]["score"] == 15
    assert report["rubric_scores"]["at_cbc"]["score"] == 15
    assert report["rubric_scores"]["dx_appendicitis"]["score"] == 15
    assert "ht_location" in report["missed_items"]
    assert report["feedback_summary"] == "已完成规则评分，LLM 评分维度将在后续阶段补充。"


def test_reasoning_coverage_scores_full_score_when_evidence_coverage_meets_threshold() -> None:
    session = OsceSession(
        session_id="session_demo",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="diagnosis_submission",
        requested_exams=["abd.palpation.rebound"],
        requested_tests=["lab.cbc"],
        final_submission={
            "diagnosis": "急性阑尾炎",
            "reasoning": "右下腹反跳痛和白细胞升高支持诊断。",
        },
    )
    item = {
        "item_id": "reasoning_core",
        "description": "推理覆盖关键证据",
        "max_score": 15,
        "match_rule": {
            "kind": "reasoning_coverage",
            "spec": {
                "required_evidence": [
                    "appendicitis_001.hf_02",
                    "abd.palpation.rebound",
                    "lab.cbc",
                ],
                "min_coverage_ratio": 0.6,
            },
        },
        "evidence_expected": [
            "appendicitis_001.hf_02",
            "abd.palpation.rebound",
            "lab.cbc",
        ],
    }

    assert score_rubric_item(session, item) == 15


def test_llm_rubric_uses_injected_scorer_contract() -> None:
    session = OsceSession(
        session_id="session_demo",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="diagnosis_submission",
        revealed_facts=["appendicitis_001.hf_02", "abd.palpation.rebound"],
        final_submission={
            "diagnosis": "急性阑尾炎",
            "reasoning": "转移性右下腹痛和反跳痛支持急性阑尾炎。",
        },
    )
    item = {
        "item_id": "reasoning_quality",
        "description": "推理链覆盖关键证据并能自圆其说",
        "max_score": 15,
        "match_rule": {
            "kind": "llm_rubric",
            "spec": {"prompt_id": "reasoning_quality_v1", "max_score": 15},
        },
        "evidence_expected": [
            "appendicitis_001.hf_02",
            "abd.palpation.rebound",
            "lab.cbc",
        ],
    }
    captured_requests: list[LlmRubricRequest] = []

    def fake_scorer(request: LlmRubricRequest) -> LlmRubricResponse:
        captured_requests.append(request)
        return LlmRubricResponse(
            score=10,
            covered_evidence=["appendicitis_001.hf_02", "abd.palpation.rebound"],
            missing_evidence=["lab.cbc"],
            rationale="覆盖腹痛迁移与反跳痛，缺少血常规证据。",
        )

    assert score_rubric_item(session, item, llm_scorer=fake_scorer) == 10
    assert captured_requests == [
        LlmRubricRequest(
            rubric_item_id="reasoning_quality",
            description="推理链覆盖关键证据并能自圆其说",
            max_score=15,
            student_final_reasoning="转移性右下腹痛和反跳痛支持急性阑尾炎。",
            relevant_facts_revealed=["appendicitis_001.hf_02", "abd.palpation.rebound"],
            required_evidence=[
                "appendicitis_001.hf_02",
                "abd.palpation.rebound",
                "lab.cbc",
            ],
        )
    ]


def test_evaluate_session_rules_records_llm_rubric_trace() -> None:
    session = OsceSession(
        session_id="session_demo",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="diagnosis_submission",
        asked_questions=["什么时候开始疼的？"],
        revealed_facts=["appendicitis_001.hf_02", "abd.palpation.rebound"],
        requested_exams=["abd.palpation.rebound"],
        requested_tests=["lab.cbc"],
        final_submission={
            "diagnosis": "急性阑尾炎",
            "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
        },
    )

    def fake_scorer(request: LlmRubricRequest) -> LlmRubricResponse:
        if request.rubric_item_id == "reasoning_core":
            return LlmRubricResponse(
                score=9,
                covered_evidence=["appendicitis_001.hf_02", "abd.palpation.rebound"],
                missing_evidence=["lab.cbc"],
                rationale="覆盖腹痛迁移与反跳痛，缺少血常规证据。",
            )
        return LlmRubricResponse(
            score=12,
            covered_evidence=["appendicitis_001.rp_01"],
            missing_evidence=[],
            rationale="鉴别诊断表述基本合理。",
        )

    report = evaluate_session_rules(session, llm_scorer=fake_scorer)

    assert report["rubric_scores"]["reasoning_core"] == {
        "score": 9,
        "max_score": 15,
        "dimension_id": "reasoning",
        "description": "推理链覆盖关键证据并能自圆其说",
        "covered_evidence": ["appendicitis_001.hf_02", "abd.palpation.rebound"],
        "missing_evidence": ["lab.cbc"],
        "rationale": "覆盖腹痛迁移与反跳痛，缺少血常规证据。",
    }


def test_llm_rubric_without_final_submission_returns_zero_trace() -> None:
    session = OsceSession(
        session_id="session_demo",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="diagnosis_submission",
        final_submission=None,
    )
    item = {
        "item_id": "reasoning_quality",
        "description": "推理链覆盖关键证据并能自圆其说",
        "max_score": 15,
        "match_rule": {
            "kind": "llm_rubric",
            "spec": {"prompt_id": "reasoning_quality_v1", "max_score": 15},
        },
        "evidence_expected": [
            "appendicitis_001.hf_02",
            "abd.palpation.rebound",
            "lab.cbc",
        ],
    }

    def fake_scorer(request: LlmRubricRequest) -> LlmRubricResponse:
        raise AssertionError("缺少最终提交时不应调用 LLM 评分器")

    assert score_rubric_item(session, item, llm_scorer=fake_scorer) == 0


def test_score_trace_model_matches_development_document_contract() -> None:
    trace = ScoreTrace(
        rubric_item_id="reasoning_core",
        awarded_score=9,
        max_score=15,
        match_kind="llm_rubric",
        matched_evidence=["appendicitis_001.hf_02", "abd.palpation.rebound"],
        llm_rationale="覆盖腹痛迁移与反跳痛，缺少血常规证据。",
    )

    assert trace.model_dump() == {
        "rubric_item_id": "reasoning_core",
        "awarded_score": 9,
        "max_score": 15,
        "match_kind": "llm_rubric",
        "matched_evidence": ["appendicitis_001.hf_02", "abd.palpation.rebound"],
        "llm_rationale": "覆盖腹痛迁移与反跳痛，缺少血常规证据。",
        "fallback_reason": None,
    }


def test_evaluate_session_rules_outputs_dimension_score_traces() -> None:
    session = OsceSession(
        session_id="session_demo",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="diagnosis_submission",
        asked_questions=["什么时候开始疼的？"],
        revealed_facts=["appendicitis_001.hf_01", "appendicitis_001.hf_02"],
        requested_exams=["abd.palpation.rebound"],
        requested_tests=["lab.cbc"],
        final_submission={
            "diagnosis": "急性阑尾炎",
            "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
        },
    )

    def fake_scorer(request: LlmRubricRequest) -> LlmRubricResponse:
        return LlmRubricResponse(
            score=9,
            covered_evidence=request.required_evidence[:2],
            missing_evidence=request.required_evidence[2:],
            rationale="覆盖部分关键证据，仍缺少完整论证。",
        )

    report = evaluate_session_rules(session, llm_scorer=fake_scorer)

    assert report["dimension_traces"]["history_taking"][0] == {
        "rubric_item_id": "ht_onset",
        "awarded_score": 10,
        "max_score": 10,
        "match_kind": "intent_keyword",
        "matched_evidence": ["什么时候开始疼的？"],
        "llm_rationale": None,
        "fallback_reason": None,
    }
    assert report["dimension_traces"]["reasoning"][0] == {
        "rubric_item_id": "reasoning_core",
        "awarded_score": 9,
        "max_score": 15,
        "match_kind": "llm_rubric",
        "matched_evidence": ["appendicitis_001.rp_01", "appendicitis_001.rp_02"],
        "llm_rationale": "覆盖部分关键证据，仍缺少完整论证。",
        "fallback_reason": None,
    }
