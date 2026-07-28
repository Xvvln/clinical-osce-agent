from __future__ import annotations

from app.services.admin_learning_analytics_service import AdminLearningAnalyticsService
from app.services.osce_session_service import OsceSession
from app.services.osce_session_store import OsceSessionStore
from app.services.report_store import ReportStore


def _report(
    session_id: str,
    *,
    student_id: str,
    total_score: int,
    clinical_score: int,
    humanistic_score: int,
    missed_items: list[str],
    training_gaps: list[dict[str, object]],
    missed_opportunities: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "case_id": "appendicitis_001",
        "student_id": student_id,
        "total_score": total_score,
        "score_groups": {
            "clinical_osce": {"score": clinical_score, "max_score": 70},
            "humanistic_communication": {"score": humanistic_score, "max_score": 30},
        },
        "missed_items": missed_items,
        "training_gaps": training_gaps,
        "missed_opportunities": missed_opportunities,
    }


def test_admin_learning_analytics_aggregates_case_and_student_dimensions(tmp_path) -> None:
    session_store = OsceSessionStore(tmp_path / "sessions.sqlite3")
    report_store = ReportStore(tmp_path / "reports.sqlite3")
    session_store.create_session(
        OsceSession(
            session_id="session_case_one",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="feedback",
            patient_affect_state={
                "current_emotion": "anxious",
                "current_emotion_label": "焦虑",
                "intensity": 3,
                "unanswered_signal": True,
                "last_transition": "emotion_ignored",
                "trajectory": [
                    {"event": "patient_signal_detected", "turn_id": "turn:1"},
                    {"event": "emotion_ignored", "turn_id": "turn:2"},
                ],
            },
        )
    )
    session_store.create_session(
        OsceSession(
            session_id="session_case_two",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="feedback",
            patient_affect_state={
                "current_emotion": "relieved",
                "current_emotion_label": "欣慰",
                "intensity": 1,
                "unanswered_signal": False,
                "last_transition": "emotion_repaired",
                "trajectory": [
                    {"event": "patient_signal_detected", "turn_id": "turn:1"},
                    {"event": "emotion_repaired", "turn_id": "turn:2"},
                ],
            },
        )
    )
    report_store.save_report(
        _report(
            "session_case_one",
            student_id="student_a",
            total_score=60,
            clinical_score=43,
            humanistic_score=17,
            missed_items=["ht_onset", "reasoning_core"],
            training_gaps=[
                {
                    "gap_type": "relationship_empathy_missing",
                    "dimension_id": "relationship_building",
                    "label": "未回应患者担忧",
                    "missing_score": 3,
                    "next_training_action": "患者表达担忧后先回应情绪。",
                }
            ],
            missed_opportunities=[
                {
                    "gap_type": "relationship_empathy_missing",
                    "expected_response": "先承认患者担忧，再继续问诊。",
                }
            ],
        )
    )
    report_store.save_report(
        _report(
            "session_case_two",
            student_id="student_a",
            total_score=70,
            clinical_score=50,
            humanistic_score=20,
            missed_items=["reasoning_core"],
            training_gaps=[
                {
                    "gap_type": "ethics_consent_missing",
                    "dimension_id": "medical_ethics",
                    "label": "查体前缺少同意",
                    "missing_score": 2,
                    "next_training_action": "查体前说明目的并征得同意。",
                }
            ],
            missed_opportunities=[],
        )
    )

    analytics = AdminLearningAnalyticsService(session_store=session_store, report_store=report_store).summarize()

    assert analytics["summary"]["session_count"] == 2
    assert analytics["summary"]["report_count"] == 2
    assert analytics["summary"]["case_count"] == 1
    assert analytics["summary"]["student_count"] == 1

    cohort_analytics = analytics["cohort_analytics"]
    assert cohort_analytics["scope"] == "all_users"
    assert cohort_analytics["session_count"] == 2
    assert cohort_analytics["report_count"] == 2
    assert cohort_analytics["case_count"] == 1
    assert cohort_analytics["student_count"] == 1
    assert cohort_analytics["average_total_score"] == 65
    assert cohort_analytics["average_clinical_score"] == 46.5
    assert cohort_analytics["average_humanistic_score"] == 18.5
    assert cohort_analytics["frequent_missed_items"][0]["item_id"] == "reasoning_core"
    assert cohort_analytics["frequent_humanistic_gaps"][0]["gap_type"] == "ethics_consent_missing"
    assert cohort_analytics["frequent_missed_opportunities"][0]["gap_type"] == "relationship_empathy_missing"
    assert cohort_analytics["affect_signals"] == {"signal_count": 2, "repaired_count": 1, "ignored_count": 1}
    assert any("全用户" in action for action in cohort_analytics["teaching_actions"])
    assert any(
        drill["scope"] == "all_users"
        and drill["source"] == "humanistic_gap"
        and drill["target_gap_type"] == "ethics_consent_missing"
        and "查体前说明目的" in drill["student_action"]
        for drill in cohort_analytics["training_drills"]
    )
    assert any(
        drill["scope"] == "all_users"
        and drill["source"] == "affect_response"
        and "情绪" in drill["success_signal"]
        for drill in cohort_analytics["training_drills"]
    )

    case_analytics = analytics["case_analytics"][0]
    assert case_analytics["case_id"] == "appendicitis_001"
    assert case_analytics["session_count"] == 2
    assert case_analytics["report_count"] == 2
    assert case_analytics["average_total_score"] == 65
    assert case_analytics["average_clinical_score"] == 46.5
    assert case_analytics["average_humanistic_score"] == 18.5
    assert case_analytics["frequent_missed_items"][0]["item_id"] == "reasoning_core"
    assert case_analytics["frequent_humanistic_gaps"][0]["gap_type"] == "ethics_consent_missing"
    assert case_analytics["frequent_missed_opportunities"][0]["gap_type"] == "relationship_empathy_missing"
    assert case_analytics["affect_signals"] == {"signal_count": 2, "repaired_count": 1, "ignored_count": 1}
    assert any("患者情绪" in action for action in case_analytics["teaching_actions"])
    assert case_analytics["training_drills"][0]["scope"] == "case"
    assert case_analytics["training_drills"][0]["scope_id"] == "appendicitis_001"
    assert case_analytics["training_drills"][0]["trigger_stage"]
    assert case_analytics["training_drills"][0]["student_action"]
    assert case_analytics["training_drills"][0]["success_signal"]

    student_analytics = analytics["student_analytics"][0]
    assert student_analytics["student_id"] == "student_a"
    assert student_analytics["report_count"] == 2
    assert student_analytics["persistent_gaps"][0]["gap_type"] == "ethics_consent_missing"
    assert student_analytics["current_humanistic_gaps"][0]["gap_type"] == "ethics_consent_missing"
    assert student_analytics["affect_response"] == {"signal_count": 2, "repaired_count": 1, "ignored_count": 1}
    assert any("查体前说明目的" in action for action in student_analytics["recommended_next_actions"])
    assert any(
        drill["scope"] == "student"
        and drill["scope_id"] == "student_a"
        and drill["target_gap_type"] == "ethics_consent_missing"
        and "查体前说明目的" in drill["student_action"]
        for drill in student_analytics["training_drills"]
    )


def test_admin_learning_analytics_filters_by_case_and_student(tmp_path) -> None:
    session_store = OsceSessionStore(tmp_path / "sessions.sqlite3")
    report_store = ReportStore(tmp_path / "reports.sqlite3")
    session_store.create_session(OsceSession(session_id="session_a", student_id="student_a", case_id="appendicitis_001", stage="feedback"))
    session_store.create_session(OsceSession(session_id="session_b", student_id="student_b", case_id="pneumonia_001", stage="feedback"))
    report_store.save_report(_report("session_a", student_id="student_a", total_score=60, clinical_score=43, humanistic_score=17, missed_items=[], training_gaps=[], missed_opportunities=[]))
    report_store.save_report(_report("session_b", student_id="student_b", total_score=80, clinical_score=58, humanistic_score=22, missed_items=[], training_gaps=[], missed_opportunities=[]))

    analytics = AdminLearningAnalyticsService(session_store=session_store, report_store=report_store).summarize(
        case_id="appendicitis_001",
        student_id="student_a",
    )

    assert analytics["summary"]["session_count"] == 1
    assert [item["case_id"] for item in analytics["case_analytics"]] == ["appendicitis_001"]
    assert [item["student_id"] for item in analytics["student_analytics"]] == ["student_a"]
