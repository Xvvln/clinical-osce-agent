import json
from pathlib import Path

import yaml

from app.models.rubric import LlmRubricRequest, LlmRubricResponse, ScoreTrace
from app.services.humanistic_evaluator import (
    HumanisticSemanticReviewResponse,
    OpenAICompatibleHumanisticSemanticReviewer,
    SemanticReviewRequest,
    load_anchor_bank,
    semantic_anchor_match,
)
from app.services.osce_session_service import OsceSession
from app.services.rule_evaluator import evaluate_session_rules, score_rubric_item


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FakeHumanisticEmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def embed_texts(self, texts, *, task_type: str):  # type: ignore[no-untyped-def]
        normalized_texts = tuple(str(text) for text in texts)
        self.calls.append((normalized_texts, task_type))
        return [_fake_embedding_vector(text) for text in normalized_texts]


class FlatHumanisticEmbeddingClient:
    def embed_texts(self, texts, *, task_type: str):  # type: ignore[no-untyped-def]
        return [[1.0, 0.0] for _ in texts]


class BoundaryAcceptingReviewer:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def review(self, request: object) -> str:
        self.requests.append(request)
        return "accepted"


class BoundaryRejectingReviewer:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def review(self, request: object) -> str:
        self.requests.append(request)
        return "rejected"


class FakeHumanisticReviewClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete_json(self, **kwargs: object) -> HumanisticSemanticReviewResponse:
        self.calls.append(dict(kwargs))
        return HumanisticSemanticReviewResponse(status="accepted", rationale="语义覆盖患者视角。")


def _fake_embedding_vector(text: str) -> list[float]:
    normalized = text.lower()
    if "最担心" in normalized or "担心什么" in normalized or "放不下" in normalized or "就诊" in normalized:
        return [1.0, 0.0, 0.0]
    if "没事" in normalized or "不重要" in normalized:
        return [0.0, 1.0, 0.0]
    if "也许需要了解你的想法" in normalized:
        return [0.29, 0.0, 0.957]
    return [0.0, 0.0, 1.0]


def test_appendicitis_male_case_uses_sex_appropriate_differential_items() -> None:
    case_payload = json.loads((PROJECT_ROOT / "data/cases/appendicitis_001.json").read_text(encoding="utf-8"))
    rubric_payload = yaml.safe_load(
        (PROJECT_ROOT / "data/rubrics/appendicitis_001_rubric.yaml").read_text(encoding="utf-8")
    )
    searchable_content = "\n".join(
        [
            json.dumps(case_payload["diagnosis"], ensure_ascii=False),
            yaml.safe_dump(rubric_payload, allow_unicode=True, sort_keys=True),
        ]
    ).lower()

    assert case_payload["patient_profile"]["gender"] == "男"
    for forbidden_term in ["异位妊娠", "宫外孕", "ectopic", "pregnancy"]:
        assert forbidden_term not in searchable_content


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
    assert report["total_score"] == 22
    assert report["dimension_scores"] == {
        "history_taking": 2,
        "physical_exam": 4,
        "auxiliary_test": 3,
        "main_diagnosis": 10,
        "differential_diagnosis": 0,
        "reasoning": 3,
        "narrative_medicine": 0,
        "communication_skill": 0,
        "medical_ethics": 0,
        "relationship_building": 0,
    }
    assert report["score_groups"] == {
        "clinical_osce": {"score": 22, "max_score": 70},
        "humanistic_communication": {"score": 0, "max_score": 30},
    }
    assert report["rubric_scores"]["ht_onset"]["score"] == 2
    assert report["rubric_scores"]["ht_migration"]["score"] == 0
    assert report["rubric_scores"]["pe_rebound"]["score"] == 4
    assert report["rubric_scores"]["ax_cbc"]["score"] == 3
    assert report["rubric_scores"]["dx_main"]["score"] == 10
    assert report["rubric_scores"]["rs_support"]["score"] == 3
    assert "ht_migration" in report["missed_items"]
    assert report["feedback_summary"] == "已完成规则评分，LLM 评分维度将在后续阶段补充。"


def test_rule_evaluator_derives_score_group_maxima_from_current_rubric() -> None:
    session = OsceSession(
        session_id="session_acs",
        student_id="student_demo",
        case_id="acs_001",
        stage="diagnosis_submission",
    )

    report = evaluate_session_rules(session)

    assert report["total_score"] == 0
    assert report["score_groups"] == {
        "clinical_osce": {"score": 0, "max_score": 100},
        "humanistic_communication": {"score": 0, "max_score": 0},
    }


def test_intent_keyword_item_scores_when_expected_fact_was_revealed() -> None:
    session = OsceSession(
        session_id="session_demo",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="diagnosis_submission",
        asked_questions=["一开始疼在哪里，后来有没有换地方？"],
        revealed_facts=["appendicitis_001.hf_02"],
    )

    report = evaluate_session_rules(session)

    assert report["rubric_scores"]["ht_migration"]["score"] == 4
    assert "appendicitis_001.hf_02" in report["dimension_traces"]["history_taking"][1]["matched_evidence"]
    assert "ht_migration" not in report["missed_items"]


def test_diagnosis_concept_scores_differential_concepts_from_structured_reasoning() -> None:
    session = OsceSession(
        session_id="session_demo",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="diagnosis_submission",
        final_submission={
            "diagnosis": "急性阑尾炎",
            "reasoning": "\n".join(
                [
                    "鉴别诊断：右侧输尿管结石、克罗恩病回盲部受累、急性胃肠炎。",
                    "排除依据：无尿痛、尿频、肉眼血尿，尿常规阴性；无慢性腹泻或体重下降；没有明显腹泻，不像急性胃肠炎。",
                ]
            ),
        },
    )

    report = evaluate_session_rules(session)

    assert report["dimension_scores"]["differential_diagnosis"] == 10
    assert report["rubric_scores"]["dxd_urolith"]["score"] == 4
    assert report["rubric_scores"]["dxd_crohn"]["score"] == 3
    assert report["rubric_scores"]["dxd_gastroenteritis"]["score"] == 3
    assert "dxd_urolith" not in report["missed_items"]
    assert "dxd_crohn" not in report["missed_items"]
    assert "dxd_gastroenteritis" not in report["missed_items"]


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


def test_humanistic_dialogue_and_semantic_items_score_with_trace() -> None:
    session = OsceSession(
        session_id="session_humanistic",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="diagnosis_submission",
        messages=[
            {"role": "student", "content": "你好，我是今天接诊你的医生。你现在最担心的是什么？"},
            {"role": "patient", "content": "我很担心是不是很严重。"},
            {"role": "student", "content": "我理解你现在很担心，我们会一步步把原因弄清楚。"},
            {"role": "student", "content": "我需要检查一下你的腹部，可能会有些不舒服，可以吗？"},
        ],
        action_timeline=[
            {"turn_index": 4, "action_type": "physical_exam_requested", "source_id": "abd.palpation.tenderness"},
        ],
    )

    report = evaluate_session_rules(session)

    assert report["dimension_scores"]["narrative_medicine"] >= 3
    assert report["dimension_scores"]["communication_skill"] >= 2
    assert report["dimension_scores"]["medical_ethics"] >= 3
    assert report["dimension_scores"]["relationship_building"] >= 2
    assert report["score_groups"]["humanistic_communication"]["score"] >= 10
    empathy_trace = report["rubric_scores"]["rel_empathy_response"]["trace"]
    assert empathy_trace["match_kind"] == "triggered_response"
    assert empathy_trace["matched_evidence"] == ["我理解你现在很担心，我们会一步步把原因弄清楚。"]
    assert empathy_trace["anchor_bank_version"] == "humanistic_anchor_bank_v1"
    assert empathy_trace["semantic_score"] > 0
    consent_trace = report["rubric_scores"]["eth_exam_consent"]["trace"]
    assert consent_trace["timing_status"] == "before_action"
    assert consent_trace["matched_turn_index"] <= consent_trace["action_turn_index"]


def test_humanistic_semantic_scoring_uses_embedding_client_and_reuses_anchor_vectors() -> None:
    embedding_client = FakeHumanisticEmbeddingClient()
    session = OsceSession(
        session_id="session_embedding_humanistic",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="history_taking",
        messages=[
            {"role": "student", "content": "我想先听听你现在最担心什么。"},
            {"role": "student", "content": "你现在最担心的是什么？"},
        ],
    )

    report = evaluate_session_rules(session, humanistic_embedding_client=embedding_client)

    trace = report["rubric_scores"]["nm_patient_concern"]["trace"]
    assert report["rubric_scores"]["nm_patient_concern"]["score"] == 3
    assert trace["match_method"] == "embedding_anchor"
    assert trace["anchor_bank_version"] == "humanistic_anchor_bank_v1"
    assert trace["semantic_score"] > 0.95
    patient_concern_anchor_calls = [
        call
        for call in embedding_client.calls
        if call[1] == "RETRIEVAL_DOCUMENT" and "你现在最担心的是什么？" in call[0]
    ]
    assert len(patient_concern_anchor_calls) == 1
    assert len([call for call in embedding_client.calls if call[1] == "RETRIEVAL_QUERY"]) >= 1


def test_humanistic_trace_payload_exposes_training_contract_fields() -> None:
    embedding_client = FakeHumanisticEmbeddingClient()
    session = OsceSession(
        session_id="session_humanistic_trace_contract",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="history_taking",
        messages=[{"role": "student", "content": "我想先听听你现在最担心什么。"}],
    )

    report = evaluate_session_rules(session, humanistic_embedding_client=embedding_client)

    matched_trace = report["rubric_scores"]["nm_patient_concern"]["trace"]
    assert matched_trace["score"] == 3
    assert matched_trace["max_score"] == 3
    assert matched_trace["matched_evidence"] == ["我想先听听你现在最担心什么。"]
    assert matched_trace["stage"] == "history_taking"
    assert matched_trace["next_training_action"]
    assert matched_trace["match_method"] == "embedding_anchor"

    gap = next(item for item in report["training_gaps"] if item["rubric_item_id"] == "nm_life_impact")
    assert gap["source_trace"]["score"] == 0
    assert gap["source_trace"]["max_score"] == 3
    assert gap["source_trace"]["gap_type"] == "narrative_life_impact_missing"
    assert gap["source_trace"]["stage"] == "history_taking"
    assert gap["source_trace"]["next_training_action"]
    assert gap["source_trace"]["match_method"] == "embedding_anchor"


def test_humanistic_lexical_fallback_matches_clear_chinese_perspective_phrases() -> None:
    anchor_bank = load_anchor_bank()

    concern = semantic_anchor_match(
        "你好，我是今天接诊你的医生。你哪里不舒服？现在最担心什么？",
        "narrative_patient_concern",
        anchor_bank,
    )
    life_impact = semantic_anchor_match(
        "这个疼痛影响你学习或睡眠了吗？",
        "narrative_life_impact",
        anchor_bank,
    )
    negative = semantic_anchor_match(
        "生活影响先不用说。",
        "narrative_life_impact",
        anchor_bank,
    )

    assert concern["matched"] is True
    assert concern["match_method"] == "semantic_anchor"
    assert life_impact["matched"] is True
    assert life_impact["match_method"] == "semantic_anchor"
    assert negative["matched"] is False


def test_humanistic_embedding_miss_uses_trusted_lexical_fallback() -> None:
    session = OsceSession(
        session_id="session_humanistic_hybrid_fallback",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="history_taking",
        messages=[{"role": "student", "content": "你好，我是今天接诊你的医生。你哪里不舒服？现在最担心什么？"}],
    )

    report = evaluate_session_rules(session, humanistic_embedding_client=FlatHumanisticEmbeddingClient())

    trace = report["rubric_scores"]["nm_patient_concern"]["trace"]
    assert report["rubric_scores"]["nm_patient_concern"]["score"] == 3
    assert trace["match_method"] == "hybrid_lexical_fallback"
    assert trace["matched_evidence"] == ["你好，我是今天接诊你的医生。你哪里不舒服？现在最担心什么？"]
    assert trace["embedding_score"] == 0.2


def test_humanistic_semantic_boundary_calls_reviewer_and_records_status() -> None:
    embedding_client = FakeHumanisticEmbeddingClient()
    reviewer = BoundaryAcceptingReviewer()
    session = OsceSession(
        session_id="session_humanistic_reviewer",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="history_taking",
        messages=[
            {"role": "student", "content": "也许需要了解你的想法。"},
        ],
    )

    report = evaluate_session_rules(
        session,
        humanistic_embedding_client=embedding_client,
        humanistic_semantic_reviewer=reviewer,
    )

    trace = report["rubric_scores"]["nm_patient_concern"]["trace"]
    assert report["rubric_scores"]["nm_patient_concern"]["score"] == 3
    assert trace["llm_review_status"] == "accepted"
    assert len(reviewer.requests) == 1


def test_humanistic_semantic_boundary_uses_default_reviewer(monkeypatch) -> None:
    embedding_client = FakeHumanisticEmbeddingClient()
    reviewer = BoundaryRejectingReviewer()
    monkeypatch.setattr(
        "app.services.rule_evaluator.create_default_humanistic_semantic_reviewer",
        lambda: reviewer,
    )
    session = OsceSession(
        session_id="session_default_humanistic_reviewer",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="history_taking",
        messages=[
            {"role": "student", "content": "也许需要了解你的想法。"},
        ],
    )

    report = evaluate_session_rules(session, humanistic_embedding_client=embedding_client)

    trace = report["rubric_scores"]["nm_patient_concern"]["trace"]
    assert report["rubric_scores"]["nm_patient_concern"]["score"] == 0
    assert trace["llm_review_status"] == "rejected"
    assert len(reviewer.requests) == 1


def test_humanistic_boundary_review_records_anchor_candidate() -> None:
    embedding_client = FakeHumanisticEmbeddingClient()
    reviewer = BoundaryRejectingReviewer()
    session = OsceSession(
        session_id="session_humanistic_anchor_candidate",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="history_taking",
        messages=[
            {"role": "student", "content": "也许需要了解你的想法。"},
        ],
    )

    report = evaluate_session_rules(
        session,
        humanistic_embedding_client=embedding_client,
        humanistic_semantic_reviewer=reviewer,
    )

    candidate = report["humanistic_anchor_candidates"][0]
    assert candidate["rubric_item_id"] == "nm_patient_concern"
    assert candidate["anchor_id"] == "narrative_patient_concern"
    assert candidate["candidate_text"] == "也许需要了解你的想法。"
    assert candidate["review_status"] == "rejected"
    assert candidate["status"] == "reviewed"


def test_openai_humanistic_semantic_reviewer_sends_boundary_payload() -> None:
    fake_client = FakeHumanisticReviewClient()
    reviewer = OpenAICompatibleHumanisticSemanticReviewer(object(), client=fake_client)

    status = reviewer.review(
        SemanticReviewRequest(
            text="也许需要了解你的想法。",
            anchor_id="narrative_patient_concern",
            semantic_score=0.29,
            threshold=0.28,
            positive_anchor="你现在最担心的是什么？",
            negative_anchor="这个不重要，你不用想太多。",
            match_method="embedding_anchor",
        )
    )

    assert status == "accepted"
    call = fake_client.calls[0]
    assert call["response_model"] is HumanisticSemanticReviewResponse
    assert call["temperature"] == 0.0
    payload = call["payload"]
    assert isinstance(payload, dict)
    assert payload["student_text"] == "也许需要了解你的想法。"
    assert payload["anchor_id"] == "narrative_patient_concern"
    assert payload["match_method"] == "embedding_anchor"
    assert "不评价诊断正确性" in str(call["system_prompt"])


def test_humanistic_sequence_check_rejects_late_consent_and_generates_gap() -> None:
    session = OsceSession(
        session_id="session_late_consent",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="diagnosis_submission",
        messages=[
            {"role": "student", "content": "我先查一下腹部。"},
            {"role": "student", "content": "刚才查腹部是为了判断压痛，可以吗？"},
        ],
        action_timeline=[
            {"turn_index": 1, "action_type": "physical_exam_requested", "source_id": "abd.palpation.tenderness"},
        ],
    )

    report = evaluate_session_rules(session)

    assert report["rubric_scores"]["eth_exam_consent"]["score"] < report["rubric_scores"]["eth_exam_consent"]["max_score"]
    trace = report["rubric_scores"]["eth_exam_consent"]["trace"]
    assert trace["timing_status"] == "late"
    assert "eth_exam_consent" in report["missed_items"]
    consent_gap = next(gap for gap in report["training_gaps"] if gap["gap_type"] == "ethics_consent_missing")
    assert consent_gap["stage"] == "physical_exam"
    assert consent_gap["trigger_stage"] == "physical_exam"


def test_humanistic_sequence_check_uses_recent_student_turns_before_action() -> None:
    session = OsceSession(
        session_id="session_consent_with_patient_reply_gap",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="diagnosis_submission",
        messages=[
            {"role": "student", "content": "我需要检查你的腹部，可能会按压痛的地方，可以吗？"},
            {"role": "patient", "content": "可以。"},
            {"role": "coach", "content": "继续选择关键查体。"},
        ],
        action_timeline=[
            {
                "turn_index": 1,
                "message_turn_index": 4,
                "action_type": "physical_exam_requested",
                "source_id": "abd.palpation.rebound",
            },
        ],
    )

    report = evaluate_session_rules(session)

    trace = report["rubric_scores"]["eth_exam_consent"]["trace"]
    assert report["rubric_scores"]["eth_exam_consent"]["score"] == 3
    assert trace["timing_status"] == "before_action"
    assert trace["matched_evidence"] == ["我需要检查你的腹部，可能会按压痛的地方，可以吗？"]
    assert trace["matched_turn_index"] == 1
    assert trace["action_turn_index"] == 4


def test_humanistic_missed_opportunity_records_unanswered_patient_emotion() -> None:
    session = OsceSession(
        session_id="session_missed_opportunity",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="history_taking",
        messages=[
            {"role": "patient", "content": "我很担心是不是严重的病。"},
            {"role": "student", "content": "疼痛是从什么时候开始的？"},
        ],
    )

    report = evaluate_session_rules(session)

    assert report["missed_opportunities"] == [
        {
            "opportunity_id": "relationship_empathy_missing:1",
            "gap_type": "relationship_empathy_missing",
            "stage": "history_taking",
            "trigger_evidence": "我很担心是不是严重的病。",
            "expected_response": "患者表达担忧后，应先回应情绪，再继续医学问诊。",
            "next_training_action": "下一轮患者表达焦虑或担忧后，先用一句话承认情绪并说明会一起处理。",
        }
    ]
    missed_gap = next(
        gap
        for gap in report["training_gaps"]
        if gap["gap_source"] == "missed_opportunity"
        and gap["gap_type"] == "relationship_empathy_missing"
    )
    assert missed_gap["stage"] == "history_taking"
    assert missed_gap["trigger_stage"] == "history_taking"


def test_humanistic_scoring_ledger_prevents_repeated_empathy_score() -> None:
    session = OsceSession(
        session_id="session_repeated_empathy",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="history_taking",
        messages=[
            {"role": "patient", "content": "我很担心。"},
            {"role": "student", "content": "我理解你现在很担心。"},
            {"role": "patient", "content": "还是有点害怕。"},
            {"role": "student", "content": "我理解你现在很担心。"},
        ],
    )

    report = evaluate_session_rules(session)

    assert report["rubric_scores"]["rel_empathy_response"]["score"] == 2
    assert report["scoring_ledger"]["awarded_item_ids"].count("rel_empathy_response") == 1


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
        return LlmRubricResponse(
            score=5,
            covered_evidence=["appendicitis_001.rp_05"],
            missing_evidence=["appendicitis_001.rp_06"],
            rationale="覆盖尿常规排除依据，缺少性别相关排除依据。",
        )

    report = evaluate_session_rules(session, llm_scorer=fake_scorer)

    assert report["rubric_scores"]["rs_exclude"] | {"trace": "<omitted>"} == {
        "score": 4,
        "max_score": 4,
        "dimension_id": "reasoning",
        "description": "推理表达覆盖关键排除依据",
        "covered_evidence": ["appendicitis_001.rp_05"],
        "missing_evidence": ["appendicitis_001.rp_06"],
        "rationale": "覆盖尿常规排除依据，缺少性别相关排除依据。",
        "trace": "<omitted>",
    }


def test_llm_rubric_invalid_structured_response_degrades_to_zero_score() -> None:
    session = OsceSession(
        session_id="session_demo",
        student_id="student_demo",
        case_id="appendicitis_001",
        stage="diagnosis_submission",
        revealed_facts=["appendicitis_001.hf_02"],
        final_submission={
            "diagnosis": "急性阑尾炎",
            "reasoning": "转移性右下腹痛支持急性阑尾炎。",
        },
    )
    item = {
        "item_id": "rs_exclude",
        "description": "推理表达覆盖关键排除依据",
        "max_score": 5,
        "match_rule": {
            "kind": "llm_rubric",
            "spec": {"prompt_id": "reasoning_exclude_v1", "max_score": 5},
        },
        "evidence_expected": [
            "appendicitis_001.rp_05",
            "appendicitis_001.rp_06",
        ],
    }

    def invalid_scorer(request: LlmRubricRequest) -> LlmRubricResponse:
        return LlmRubricResponse.model_validate(
            {
                "score": 0,
                "rationale": "缺少排除诊断证据。",
            }
        )

    report = evaluate_session_rules(session, llm_scorer=invalid_scorer)

    assert report["rubric_scores"]["rs_exclude"] | {"trace": "<omitted>"} == {
        "score": 0,
        "max_score": 4,
        "dimension_id": "reasoning",
        "description": "推理表达覆盖关键排除依据",
        "covered_evidence": [],
        "missing_evidence": [
            "appendicitis_001.rp_05",
            "appendicitis_001.rp_06",
        ],
        "rationale": "模型评分输出结构不完整，已按未覆盖处理。",
        "trace": "<omitted>",
    }
    assert report["dimension_traces"]["reasoning"][1]["fallback_reason"] == "llm_rubric_invalid_response"


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

    assert trace.model_dump(exclude_none=True) == {
        "rubric_item_id": "reasoning_core",
        "awarded_score": 9,
        "max_score": 15,
        "match_kind": "llm_rubric",
        "matched_evidence": ["appendicitis_001.hf_02", "abd.palpation.rebound"],
        "llm_rationale": "覆盖腹痛迁移与反跳痛，缺少血常规证据。",
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

    assert report["dimension_traces"]["history_taking"][0] | {"llm_rationale": None, "fallback_reason": None} == {
        "rubric_item_id": "ht_onset",
        "awarded_score": 2,
        "score": 2,
        "max_score": 2,
        "match_kind": "intent_keyword",
        "matched_evidence": ["什么时候开始疼的？", "appendicitis_001.hf_01"],
        "llm_rationale": None,
        "fallback_reason": None,
    }
    assert report["dimension_traces"]["reasoning"][0] | {"llm_rationale": None, "fallback_reason": None} == {
        "rubric_item_id": "rs_support",
        "awarded_score": 3,
        "score": 3,
        "max_score": 8,
        "match_kind": "reasoning_coverage",
        "matched_evidence": ["abd.palpation.rebound", "lab.cbc"],
        "llm_rationale": None,
        "fallback_reason": None,
    }
    assert report["dimension_traces"]["reasoning"][1] | {"fallback_reason": None} == {
        "rubric_item_id": "rs_exclude",
        "awarded_score": 4,
        "score": 4,
        "max_score": 4,
        "match_kind": "llm_rubric",
        "matched_evidence": ["appendicitis_001.rp_05", "appendicitis_001.rp_06"],
        "llm_rationale": "覆盖部分关键证据，仍缺少完整论证。",
        "fallback_reason": None,
    }
