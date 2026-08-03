from app.services.evaluation_runner import EvaluationBatchResult, EvaluationResult
from app.services.training_skill_regression_gate import TrainingSkillRegressionGate


def test_training_skill_regression_gate_marks_candidate_ready_when_batch_passes() -> None:
    candidate = {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "临床推理链纠偏提示",
        "status": "draft",
    }
    batch_result = EvaluationBatchResult(
        total_cases=2,
        passed_cases=2,
        failed_cases=0,
        results=[
            EvaluationResult(
                session_id="session_one",
                actual_total_score=55,
                expected_total_score=55,
                forbidden_term_violations=[],
                passed=True,
                duration_ms=10,
            ),
            EvaluationResult(
                session_id="session_two",
                actual_total_score=68,
                expected_total_score=68,
                forbidden_term_violations=[],
                passed=True,
                duration_ms=12,
            ),
        ],
        passed=True,
        total_duration_ms=22,
    )

    review = TrainingSkillRegressionGate().review_candidate(candidate, batch_result)

    assert review == {
        "candidate_id": "skill_candidate_reasoning_core",
        "status": "ready_for_review",
        "regression_passed": True,
        "evaluation_total_cases": 2,
        "evaluation_passed_cases": 2,
        "evaluation_failed_cases": 0,
        "blocking_failures": [],
    }


def test_training_skill_regression_gate_blocks_candidate_with_forbidden_medical_content() -> None:
    candidate = {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "临床推理链纠偏提示",
        "description": "提醒学生按证据链梳理诊断。",
        "suggested_strategy": "直接告诉学生治疗方案和用药剂量。",
        "status": "draft",
    }
    batch_result = EvaluationBatchResult(
        total_cases=1,
        passed_cases=1,
        failed_cases=0,
        results=[
            EvaluationResult(
                session_id="session_one",
                actual_total_score=55,
                expected_total_score=55,
                forbidden_term_violations=[],
                passed=True,
                duration_ms=10,
            )
        ],
        passed=True,
        total_duration_ms=10,
    )

    review = TrainingSkillRegressionGate().review_candidate(candidate, batch_result)

    assert review == {
        "candidate_id": "skill_candidate_reasoning_core",
        "status": "blocked_by_regression",
        "regression_passed": False,
        "evaluation_total_cases": 1,
        "evaluation_passed_cases": 1,
        "evaluation_failed_cases": 0,
        "blocking_failures": [],
        "candidate_safety_violations": ["治疗方案", "用药剂量"],
    }


def test_training_skill_regression_gate_blocks_dose_and_drug_variants() -> None:
    candidate = {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "剂量表达测试",
        "description": "提醒学生不要直接写阿莫西林500mg q8h。",
        "suggested_strategy": "提示学生给出处方。",
        "status": "draft",
    }
    batch_result = EvaluationBatchResult(
        total_cases=1,
        passed_cases=1,
        failed_cases=0,
        results=[
            EvaluationResult(
                session_id="session_one",
                actual_total_score=55,
                expected_total_score=55,
                forbidden_term_violations=[],
                passed=True,
                duration_ms=10,
            )
        ],
        passed=True,
        total_duration_ms=10,
    )

    review = TrainingSkillRegressionGate().review_candidate(candidate, batch_result)

    assert review["status"] == "blocked_by_regression"
    assert review["regression_passed"] is False
    assert review["candidate_safety_violations"] == [
        "剂量",
        "处方",
        "阿莫西林",
        "dose_expression",
        "dose_frequency",
    ]


def test_training_skill_regression_gate_blocks_case_incompatible_candidate_content() -> None:
    candidate = {
        "candidate_id": "skill_candidate_training_pattern_dxd_ectopic",
        "trigger_item_id": "training_pattern_dxd_ectopic",
        "trigger_item_ids": ["dxd_ectopic", "dxd_urolith"],
        "case_ids": ["appendicitis_001"],
        "title": "急腹症鉴别诊断与全面评估逻辑训练",
        "description": "急腹症鉴别诊断反复遗漏，需补充妇科和泌尿系统排除。",
        "suggested_strategy": "面对急性腹痛患者时，请系统排除妇科、异位妊娠、泌尿科及肠道相关疾病。",
        "status": "draft",
    }
    batch_result = EvaluationBatchResult(
        total_cases=1,
        passed_cases=1,
        failed_cases=0,
        results=[
            EvaluationResult(
                session_id="session_one",
                actual_total_score=55,
                expected_total_score=55,
                forbidden_term_violations=[],
                passed=True,
                duration_ms=10,
            )
        ],
        passed=True,
        total_duration_ms=10,
    )

    review = TrainingSkillRegressionGate().review_candidate(candidate, batch_result)

    assert review["status"] == "blocked_by_regression"
    assert review["regression_passed"] is False
    assert review["candidate_context_violations"][0]["case_id"] == "appendicitis_001"
    assert review["candidate_context_violations"][0]["reason"] == "male_patient_incompatible_reproductive_content"
    assert "妇科" in review["candidate_context_violations"][0]["terms"]
    assert "异位妊娠" in review["candidate_context_violations"][0]["terms"]
    assert "ectopic" in review["candidate_context_violations"][0]["terms"]


def test_training_skill_regression_gate_prefers_explicit_case_ids_over_related_recommendations() -> None:
    candidate = {
        "candidate_id": "skill_candidate_hyperthyroid_personal",
        "trigger_item_id": "personal_hyperthyroid",
        "trigger_item_ids": ["ht_family_history"],
        "case_ids": ["hyperthyroid_001"],
        "related_recommendations": ["case:appendicitis_001"],
        "title": "甲状腺病史采集训练",
        "description": "女性甲状腺病例中需要追问月经变化和家族史。",
        "suggested_strategy": "追问月经变化、怕热多汗和家族史，但不透露诊断答案。",
        "status": "draft",
    }
    batch_result = EvaluationBatchResult(
        total_cases=1,
        passed_cases=1,
        failed_cases=0,
        results=[
            EvaluationResult(
                session_id="session_one",
                actual_total_score=55,
                expected_total_score=55,
                forbidden_term_violations=[],
                passed=True,
                duration_ms=10,
            )
        ],
        passed=True,
        total_duration_ms=10,
    )

    review = TrainingSkillRegressionGate().review_candidate(candidate, batch_result)

    assert review["status"] == "ready_for_review"
    assert "candidate_context_violations" not in review


def test_training_skill_regression_gate_blocks_candidate_when_batch_fails() -> None:
    candidate = {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "临床推理链纠偏提示",
        "status": "draft",
    }
    batch_result = EvaluationBatchResult(
        total_cases=2,
        passed_cases=1,
        failed_cases=1,
        results=[
            EvaluationResult(
                session_id="session_one",
                actual_total_score=55,
                expected_total_score=55,
                forbidden_term_violations=[],
                passed=True,
                duration_ms=10,
            ),
            EvaluationResult(
                session_id="session_two",
                actual_total_score=0,
                expected_total_score=55,
                forbidden_term_violations=["治疗方案"],
                passed=False,
                duration_ms=12,
            ),
        ],
        passed=False,
        total_duration_ms=22,
    )

    review = TrainingSkillRegressionGate().review_candidate(candidate, batch_result)

    assert review == {
        "candidate_id": "skill_candidate_reasoning_core",
        "status": "blocked_by_regression",
        "regression_passed": False,
        "evaluation_total_cases": 2,
        "evaluation_passed_cases": 1,
        "evaluation_failed_cases": 1,
        "blocking_failures": [
            {
                "session_id": "session_two",
                "actual_total_score": 0,
                "expected_total_score": 55,
                "forbidden_term_violations": ["治疗方案"],
            }
        ],
    }


def test_training_skill_regression_gate_enforces_approval_agent_quality_failure() -> None:
    candidate = {
        "candidate_id": "skill_candidate_role_policy_blocked",
        "trigger_item_id": "reasoning_core",
        "title": "临床推理链纠偏提示",
        "status": "draft",
        "approval_agent_review": {
            "decision": "blocked",
            "quality_review": {
                "passed": False,
                "failed_checks": ["prohibited_content_policy_complete"],
            },
            "role_policy": {"passed": False},
        },
    }
    batch_result = EvaluationBatchResult(
        total_cases=1,
        passed_cases=1,
        failed_cases=0,
        results=[
            EvaluationResult(
                session_id="session_one",
                actual_total_score=55,
                expected_total_score=55,
                forbidden_term_violations=[],
                passed=True,
                duration_ms=10,
            )
        ],
        passed=True,
        total_duration_ms=10,
    )

    review = TrainingSkillRegressionGate().review_candidate(candidate, batch_result)

    assert review["status"] == "blocked_by_regression"
    assert review["regression_passed"] is False
    assert review["approval_agent_violations"] == [
        "approval_decision_blocked",
        "approval_quality_review_failed",
        "approval_check:prohibited_content_policy_complete",
        "approval_role_policy_failed",
    ]
