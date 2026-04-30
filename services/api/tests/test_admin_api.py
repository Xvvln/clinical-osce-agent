from fastapi.testclient import TestClient

from app import main
from app.services.evaluation_result_store import EvaluationResultStore
from app.services.evaluation_runner import EvaluationBatchResult, EvaluationResult
from app.services.osce_session_service import OsceSession, osce_session_service
from app.services.osce_session_store import OsceSessionStore
from app.services.report_store import ReportStore
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_store import TrainingSkillStore


def test_admin_can_list_training_skill_candidate_summaries(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    candidate_store.save_candidate(
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
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)

    with TestClient(main.app) as client:
        response = client.get("/api/admin/evolution/candidates")

    assert response.status_code == 200
    assert response.json() == {
        "candidates": [
            {
                "candidate_id": "skill_candidate_reasoning_core",
                "trigger_item_id": "reasoning_core",
                "title": "临床推理链纠偏提示",
                "status": "ready_for_review",
                "regression_passed": True,
                "source_report_count": 3,
                "support_count": 2,
            }
        ]
    }


def test_admin_can_list_training_session_summaries(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    session_store.save_session(
        OsceSession(
            session_id="session_admin_old",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="history",
        )
    )
    session_store.save_session(
        OsceSession(
            session_id="session_admin_recent",
            student_id="student_b",
            case_id="hyperthyroid_001",
            stage="diagnosis_submitted",
        )
    )
    monkeypatch.setattr(osce_session_service, "session_store", session_store, raising=False)

    with TestClient(main.app) as client:
        response = client.get("/api/admin/sessions")

    assert response.status_code == 200
    payload = response.json()
    assert [session["session_id"] for session in payload["sessions"]] == ["session_admin_recent", "session_admin_old"]
    assert payload["sessions"][0]["student_id"] == "student_b"
    assert payload["sessions"][0]["case_id"] == "hyperthyroid_001"
    assert payload["sessions"][0]["stage"] == "diagnosis_submitted"
    assert isinstance(payload["sessions"][0]["created_at"], str)
    assert isinstance(payload["sessions"][0]["updated_at"], str)



def test_admin_can_read_session_training_events(tmp_path, monkeypatch) -> None:
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    event_store.append_event(
        session_id="session_admin_log",
        case_id="appendicitis_001",
        student_id="student_admin_log",
        event_type="session_created",
        payload={"stage": "history"},
    )
    event_store.append_event(
        session_id="session_admin_log",
        case_id="appendicitis_001",
        student_id="student_admin_log",
        event_type="history_message",
        payload={"message": "右下腹痛多久了？"},
    )
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)

    with TestClient(main.app) as client:
        response = client.get("/api/admin/sessions/session_admin_log/events")

    assert response.status_code == 200
    payload = response.json()
    assert [event["event_type"] for event in payload["events"]] == ["session_created", "history_message"]
    assert payload["events"][0]["session_id"] == "session_admin_log"
    assert payload["events"][0]["case_id"] == "appendicitis_001"
    assert payload["events"][0]["student_id"] == "student_admin_log"
    assert payload["events"][0]["payload"] == {"stage": "history"}
    assert payload["events"][1]["payload"] == {"message": "右下腹痛多久了？"}
    assert isinstance(payload["events"][0]["created_at"], str)



def test_admin_can_read_training_insights_from_all_sessions(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    session_store.save_session(
        OsceSession(
            session_id="session_insight_one",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="report_ready",
        )
    )
    session_store.save_session(
        OsceSession(
            session_id="session_insight_two",
            student_id="student_b",
            case_id="pneumonia_001",
            stage="report_ready",
        )
    )
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    event_store.append_event(
        session_id="session_insight_one",
        case_id="appendicitis_001",
        student_id="student_a",
        event_type="report_generated",
        payload={
            "report_id": "report_one",
            "total_score": 55,
            "missed_items": ["ht_location", "reasoning_core"],
            "knowledge_recommendations": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                    "title": "补充临床推理证据链",
                },
                {
                    "reference": "case:acs_001",
                    "title": "胸痛伴出汗教学病例",
                },
            ],
        },
    )
    event_store.append_event(
        session_id="session_insight_two",
        case_id="pneumonia_001",
        student_id="student_b",
        event_type="report_generated",
        payload={
            "report_id": "report_two",
            "total_score": 68,
            "missed_items": ["reasoning_core"],
            "knowledge_recommendations": [
                {
                    "reference": "rubric:pneumonia_001_rubric.item.reasoning_core",
                    "title": "补充临床推理证据链",
                }
            ],
        },
    )
    monkeypatch.setattr(osce_session_service, "session_store", session_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)

    with TestClient(main.app) as client:
        response = client.get("/api/admin/insights")

    assert response.status_code == 200
    assert response.json() == {
        "insights": {
            "session_count": 2,
            "report_count": 2,
            "frequent_missed_items": [
                {"item_id": "reasoning_core", "count": 2, "case_ids": ["appendicitis_001", "pneumonia_001"]},
                {"item_id": "ht_location", "count": 1, "case_ids": ["appendicitis_001"]},
            ],
            "frequent_learning_recommendations": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                    "title": "补充临床推理证据链",
                    "count": 1,
                },
                {
                    "reference": "rubric:pneumonia_001_rubric.item.reasoning_core",
                    "title": "补充临床推理证据链",
                    "count": 1,
                },
            ],
        }
    }



def test_admin_can_list_evaluation_batch_summaries(tmp_path, monkeypatch) -> None:
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    evaluation_store.save_batch_result(
        "batch_smoke",
        EvaluationBatchResult(total_cases=2, passed_cases=2, failed_cases=0, results=[], passed=True, total_duration_ms=120),
    )
    evaluation_store.save_batch_result(
        "batch_regression",
        EvaluationBatchResult(total_cases=3, passed_cases=2, failed_cases=1, results=[], passed=False, total_duration_ms=300),
    )
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)

    with TestClient(main.app) as client:
        response = client.get("/api/admin/evaluations")

    assert response.status_code == 200
    assert response.json() == {
        "evaluations": [
            {"batch_id": "batch_smoke", "total_cases": 2, "passed_cases": 2, "failed_cases": 0, "passed": True},
            {"batch_id": "batch_regression", "total_cases": 3, "passed_cases": 2, "failed_cases": 1, "passed": False},
        ]
    }



def test_admin_can_read_evaluation_batch_detail(tmp_path, monkeypatch) -> None:
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    evaluation_store.save_batch_result(
        "batch_regression",
        EvaluationBatchResult(
            total_cases=1,
            passed_cases=0,
            failed_cases=1,
            results=[
                EvaluationResult(
                    session_id="session_eval_failed",
                    actual_total_score=40,
                    expected_total_score=80,
                    forbidden_term_violations=["治疗方案"],
                    passed=False,
                    duration_ms=66,
                )
            ],
            passed=False,
            total_duration_ms=66,
        ),
    )
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)

    with TestClient(main.app) as client:
        response = client.get("/api/admin/evaluations/batch_regression")

    assert response.status_code == 200
    assert response.json() == {
        "evaluation": {
            "batch_id": "batch_regression",
            "total_cases": 1,
            "passed_cases": 0,
            "failed_cases": 1,
            "passed": False,
            "total_duration_ms": 66,
            "results": [
                {
                    "session_id": "session_eval_failed",
                    "actual_total_score": 40,
                    "expected_total_score": 80,
                    "forbidden_term_violations": ["治疗方案"],
                    "passed": False,
                    "duration_ms": 66,
                }
            ],
        }
    }



def test_admin_evaluation_detail_returns_404_for_missing_batch(tmp_path, monkeypatch) -> None:
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)

    with TestClient(main.app) as client:
        response = client.get("/api/admin/evaluations/missing_batch")

    assert response.status_code == 404
    assert response.json() == {"detail": "evaluation batch not found"}



def test_admin_can_read_session_report(tmp_path, monkeypatch) -> None:
    report_store = ReportStore(tmp_path / "reports.sqlite3")
    report_store.save_report(
        {
            "report_id": "report_session_admin_report",
            "session_id": "session_admin_report",
            "case_id": "appendicitis_001",
            "student_id": "student_admin_report",
            "total_score": 82,
            "dimension_scores": {"history_taking": 18, "reasoning": 14},
            "missed_items": ["reasoning_core"],
            "knowledge_recommendations": [
                {"title": "补充鉴别诊断证据链", "reference": "rubric:appendicitis_001_rubric.item.reasoning_core"}
            ],
        }
    )
    monkeypatch.setattr(osce_session_service, "report_store", report_store, raising=False)

    with TestClient(main.app) as client:
        response = client.get("/api/admin/sessions/session_admin_report/report")

    assert response.status_code == 200
    assert response.json() == {
        "report": {
            "report_id": "report_session_admin_report",
            "session_id": "session_admin_report",
            "case_id": "appendicitis_001",
            "student_id": "student_admin_report",
            "total_score": 82,
            "dimension_scores": {"history_taking": 18, "reasoning": 14},
            "missed_items": ["reasoning_core"],
            "knowledge_recommendations": [
                {"title": "补充鉴别诊断证据链", "reference": "rubric:appendicitis_001_rubric.item.reasoning_core"}
            ],
        }
    }



def test_admin_session_report_returns_404_for_missing_report(tmp_path, monkeypatch) -> None:
    report_store = ReportStore(tmp_path / "reports.sqlite3")
    monkeypatch.setattr(osce_session_service, "report_store", report_store, raising=False)

    with TestClient(main.app) as client:
        response = client.get("/api/admin/sessions/missing_session/report")

    assert response.status_code == 404
    assert response.json() == {"detail": "report not found"}



def test_admin_can_read_training_skill_candidate_detail(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
            "related_recommendations": ["补充鉴别诊断证据链"],
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
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)

    with TestClient(main.app) as client:
        response = client.get("/api/admin/evolution/candidates/skill_candidate_reasoning_core")

    assert response.status_code == 200
    assert response.json() == {
        "candidate": {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
            "related_recommendations": ["补充鉴别诊断证据链"],
            "review": {
                "candidate_id": "skill_candidate_reasoning_core",
                "status": "ready_for_review",
                "regression_passed": True,
                "evaluation_total_cases": 2,
                "evaluation_passed_cases": 2,
                "evaluation_failed_cases": 0,
                "blocking_failures": [],
            },
        }
    }


def test_admin_candidate_detail_returns_404_for_missing_candidate(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)

    with TestClient(main.app) as client:
        response = client.get("/api/admin/evolution/candidates/missing_candidate")

    assert response.status_code == 404
    assert response.json() == {"detail": "candidate not found"}


def test_admin_can_approve_candidate_and_enable_training_skill(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
            "related_recommendations": [],
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
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_skill_store", skill_store, raising=False)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/evolution/approve",
            json={"candidate_id": "skill_candidate_reasoning_core", "reviewer_id": "admin@example.test"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "candidate_id": "skill_candidate_reasoning_core",
        "status": "approved",
        "skill_id": "skill_reasoning_core",
    }
    assert candidate_store.get_candidate("skill_candidate_reasoning_core")["review"]["reviewer_id"] == "admin@example.test"
    assert skill_store.get_skill("skill_reasoning_core") == {
        "skill_id": "skill_reasoning_core",
        "source_candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "临床推理链纠偏提示",
        "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
        "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "status": "enabled",
        "source_report_count": 2,
        "support_count": 2,
    }


def test_admin_can_reject_candidate_without_enabling_training_skill(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
            "related_recommendations": [],
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
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_skill_store", skill_store, raising=False)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/evolution/reject",
            json={"candidate_id": "skill_candidate_reasoning_core", "reviewer_id": "admin@example.test"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "candidate_id": "skill_candidate_reasoning_core",
        "status": "rejected",
    }
    assert candidate_store.get_candidate("skill_candidate_reasoning_core")["review"]["reviewer_id"] == "admin@example.test"
    assert skill_store.list_enabled_skills() == []


def test_admin_review_returns_404_for_missing_candidate(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_skill_store", skill_store, raising=False)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/admin/evolution/approve",
            json={"candidate_id": "missing_candidate", "reviewer_id": "admin@example.test"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "candidate not found or not ready for review"}
