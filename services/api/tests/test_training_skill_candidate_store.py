from app.services.training_skill_candidate_store import TrainingSkillCandidateStore


def test_training_skill_candidate_store_persists_candidate_with_review_across_instances(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    candidate = {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "临床推理链纠偏提示",
        "description": "3 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001、pneumonia_001。",
        "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "status": "draft",
        "source_report_count": 3,
        "support_count": 2,
        "related_recommendations": [
            "rubric:appendicitis_001_rubric.item.reasoning_core",
            "knowledge:appendicitis_001.rp_03",
        ],
    }
    review = {
        "candidate_id": "skill_candidate_reasoning_core",
        "status": "ready_for_review",
        "regression_passed": True,
        "evaluation_total_cases": 2,
        "evaluation_passed_cases": 2,
        "evaluation_failed_cases": 0,
        "blocking_failures": [],
    }

    TrainingSkillCandidateStore(database_path).save_candidate(candidate, review)
    loaded_candidate = TrainingSkillCandidateStore(database_path).get_candidate("skill_candidate_reasoning_core")

    assert loaded_candidate == {
        **candidate,
        "review": review,
    }


def test_training_skill_candidate_store_lists_candidate_summaries_in_insert_order(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)

    store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    store.save_candidate(
        {
            "candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "title": "OSCE 漏项纠偏提示",
            "status": "draft",
            "source_report_count": 4,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_ht_location",
            "status": "blocked_by_regression",
            "regression_passed": False,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 1,
            "blocking_failures": [
                {
                    "session_id": "session_fail",
                    "actual_total_score": 0,
                    "expected_total_score": 55,
                    "forbidden_term_violations": ["治疗方案"],
                }
            ],
        },
    )

    summaries = TrainingSkillCandidateStore(database_path).list_candidate_summaries()

    assert summaries == [
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "status": "ready_for_review",
            "regression_passed": True,
            "source_report_count": 3,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "title": "OSCE 漏项纠偏提示",
            "status": "blocked_by_regression",
            "regression_passed": False,
            "source_report_count": 4,
            "support_count": 2,
        },
    ]


def test_training_skill_candidate_store_does_not_overwrite_reviewed_candidate_when_saving_unless_reviewed(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)
    store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    assert store.approve_candidate("skill_candidate_reasoning_core", reviewer_id="teacher_demo") is True

    saved = store.save_candidate_unless_reviewed(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "刷新后的候选",
            "status": "draft",
            "source_report_count": 5,
            "support_count": 5,
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "blocked_by_regression",
            "regression_passed": False,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 1,
            "blocking_failures": [],
        },
    )

    candidate = TrainingSkillCandidateStore(database_path).get_candidate("skill_candidate_reasoning_core")
    assert saved is False
    assert candidate["title"] == "临床推理链纠偏提示"
    assert candidate["source_report_count"] == 2
    assert candidate["support_count"] == 2
    assert candidate["review"]["status"] == "approved"
    assert candidate["review"]["reviewer_id"] == "teacher_demo"


def test_training_skill_candidate_store_refreshes_unreviewed_candidate_when_saving_unless_reviewed(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)
    store.save_candidate(
        {
            "candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "title": "旧候选",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_ht_location",
            "status": "blocked_by_regression",
            "regression_passed": False,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 1,
            "blocking_failures": [],
        },
    )

    saved = store.save_candidate_unless_reviewed(
        {
            "candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "title": "刷新后的候选",
            "status": "draft",
            "source_report_count": 4,
            "support_count": 4,
        },
        {
            "candidate_id": "skill_candidate_ht_location",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )

    candidate = TrainingSkillCandidateStore(database_path).get_candidate("skill_candidate_ht_location")
    assert saved is True
    assert candidate["title"] == "刷新后的候选"
    assert candidate["source_report_count"] == 4
    assert candidate["support_count"] == 4
    assert candidate["review"]["status"] == "ready_for_review"


def test_training_skill_candidate_store_approves_ready_candidate(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)
    store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )

    approved = store.approve_candidate("skill_candidate_reasoning_core", reviewer_id="teacher_demo")

    assert approved is True
    assert TrainingSkillCandidateStore(database_path).get_candidate("skill_candidate_reasoning_core") == {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "临床推理链纠偏提示",
        "status": "draft",
        "source_report_count": 3,
        "support_count": 2,
        "review": {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "approved",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
            "reviewer_id": "teacher_demo",
        },
    }


def test_training_skill_candidate_store_rejects_ready_candidate(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)
    store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )

    rejected = store.reject_candidate("skill_candidate_reasoning_core", reviewer_id="teacher_demo")

    assert rejected is True
    assert TrainingSkillCandidateStore(database_path).get_candidate("skill_candidate_reasoning_core")["review"]["status"] == "rejected"


def test_training_skill_candidate_store_does_not_approve_blocked_candidate(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)
    store.save_candidate(
        {
            "candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "title": "OSCE 漏项纠偏提示",
            "status": "draft",
            "source_report_count": 4,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_ht_location",
            "status": "blocked_by_regression",
            "regression_passed": False,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 1,
            "blocking_failures": [],
        },
    )

    approved = store.approve_candidate("skill_candidate_ht_location", reviewer_id="teacher_demo")

    assert approved is False
    assert TrainingSkillCandidateStore(database_path).get_candidate("skill_candidate_ht_location")["review"]["status"] == "blocked_by_regression"
