from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_effect_service import TrainingSkillEffectService


def test_training_skill_effect_service_compares_sessions_with_and_without_skill(tmp_path) -> None:
    store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    store.append_event(
        session_id="session_with_skill",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="training_skill_applied",
        payload={
            "skill_id": "skill_reasoning_core",
            "title": "临床推理链纠偏提示",
            "suggested_strategy": "提醒学生组织证据链。",
        },
    )
    store.append_event(
        session_id="session_with_skill",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="report_generated",
        payload={
            "report_id": "session_with_skill_report",
            "total_score": 70,
            "missed_items": ["ht_location"],
            "knowledge_recommendations": [],
        },
    )
    store.append_event(
        session_id="session_without_skill",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="report_generated",
        payload={
            "report_id": "session_without_skill_report",
            "total_score": 55,
            "missed_items": ["ht_location", "reasoning_core"],
            "knowledge_recommendations": [],
        },
    )

    comparison = TrainingSkillEffectService(store).compare_sessions(
        ["session_with_skill", "session_without_skill"]
    )

    assert comparison == {
        "with_skill": {
            "session_count": 1,
            "average_total_score": 70.0,
            "missed_item_counts": {"ht_location": 1},
            "skill_ids": ["skill_reasoning_core"],
        },
        "without_skill": {
            "session_count": 1,
            "average_total_score": 55.0,
            "missed_item_counts": {"ht_location": 1, "reasoning_core": 1},
            "skill_ids": [],
        },
    }


def test_training_skill_effect_service_marks_summary_insufficient_when_groups_are_too_small(tmp_path) -> None:
    store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    store.append_event(
        session_id="session_with_skill",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="training_skill_applied",
        payload={
            "skill_id": "skill_reasoning_core",
            "title": "临床推理链纠偏提示",
            "suggested_strategy": "提醒学生组织证据链。",
        },
    )
    store.append_event(
        session_id="session_with_skill",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="report_generated",
        payload={
            "report_id": "session_with_skill_report",
            "total_score": 70,
            "missed_items": ["ht_location"],
            "knowledge_recommendations": [],
        },
    )
    store.append_event(
        session_id="session_without_skill",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="report_generated",
        payload={
            "report_id": "session_without_skill_report",
            "total_score": 55,
            "missed_items": ["ht_location", "reasoning_core"],
            "knowledge_recommendations": [],
        },
    )

    summary = TrainingSkillEffectService(store).summarize_sessions(
        ["session_with_skill", "session_without_skill"],
        min_sessions_per_group=2,
    )

    assert summary == {
        "status": "insufficient_samples",
        "label": "样本不足",
        "min_sessions_per_group": 2,
        "score_delta": None,
        "with_skill": {
            "session_count": 1,
            "average_total_score": 70.0,
            "missed_item_counts": {"ht_location": 1},
            "skill_ids": ["skill_reasoning_core"],
        },
        "without_skill": {
            "session_count": 1,
            "average_total_score": 55.0,
            "missed_item_counts": {"ht_location": 1, "reasoning_core": 1},
            "skill_ids": [],
        },
    }
