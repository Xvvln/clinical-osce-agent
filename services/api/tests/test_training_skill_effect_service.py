from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_effect_service import TrainingSkillEffectService


class BatchOnlyTrainingEventStore:
    def __init__(self, events_by_session: dict[str, list[dict[str, object]]]) -> None:
        self.events_by_session = events_by_session
        self.batch_calls: list[list[str]] = []

    def list_events_for_sessions(self, session_ids: list[str]) -> dict[str, list[dict[str, object]]]:
        self.batch_calls.append(session_ids)
        return {session_id: self.events_by_session.get(session_id, []) for session_id in session_ids}

    def list_session_events(self, session_id: str) -> list[dict[str, object]]:
        raise AssertionError(f"skill effect summary should batch-load events, got {session_id}")


def test_training_skill_effect_service_batch_loads_events_for_large_admin_summaries() -> None:
    store = BatchOnlyTrainingEventStore(
        {
            "session_with_skill": [
                {
                    "session_id": "session_with_skill",
                    "case_id": "appendicitis_001",
                    "student_id": "student_demo",
                    "event_type": "training_skill_applied",
                    "payload": {"skill_id": "skill_reasoning_core"},
                    "created_at": "2026-05-01T00:00:00+00:00",
                },
                {
                    "session_id": "session_with_skill",
                    "case_id": "appendicitis_001",
                    "student_id": "student_demo",
                    "event_type": "report_generated",
                    "payload": {"report_id": "report_one", "total_score": 70, "missed_items": []},
                    "created_at": "2026-05-01T00:00:01+00:00",
                },
            ],
            "session_without_skill": [
                {
                    "session_id": "session_without_skill",
                    "case_id": "appendicitis_001",
                    "student_id": "student_demo",
                    "event_type": "report_generated",
                    "payload": {"report_id": "report_two", "total_score": 50, "missed_items": ["ht_location"]},
                    "created_at": "2026-05-01T00:00:02+00:00",
                }
            ],
        }
    )

    comparison = TrainingSkillEffectService(store).compare_sessions(["session_with_skill", "session_without_skill"])

    assert store.batch_calls == [["session_with_skill", "session_without_skill"]]
    assert comparison["with_skill"]["session_count"] == 1
    assert comparison["without_skill"]["session_count"] == 1


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


def test_training_skill_effect_service_marks_sufficient_samples_as_descriptive_only(tmp_path) -> None:
    store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    for index, score in enumerate([70, 74], start=1):
        session_id = f"session_with_skill_{index}"
        store.append_event(
            session_id=session_id,
            case_id="appendicitis_001",
            student_id=f"student_with_{index}",
            event_type="training_skill_applied",
            payload={
                "skill_id": "skill_reasoning_core",
                "title": "临床推理链纠偏提示",
                "suggested_strategy": "提醒学生组织证据链。",
            },
        )
        store.append_event(
            session_id=session_id,
            case_id="appendicitis_001",
            student_id=f"student_with_{index}",
            event_type="report_generated",
            payload={
                "report_id": f"{session_id}_report",
                "total_score": score,
                "missed_items": ["ht_location"],
                "knowledge_recommendations": [],
            },
        )
    for index, score in enumerate([50, 54], start=1):
        session_id = f"session_without_skill_{index}"
        store.append_event(
            session_id=session_id,
            case_id="appendicitis_001",
            student_id=f"student_without_{index}",
            event_type="report_generated",
            payload={
                "report_id": f"{session_id}_report",
                "total_score": score,
                "missed_items": ["ht_location", "reasoning_core"],
                "knowledge_recommendations": [],
            },
        )

    summary = TrainingSkillEffectService(store).summarize_sessions(
        [
            "session_with_skill_1",
            "session_with_skill_2",
            "session_without_skill_1",
            "session_without_skill_2",
        ],
        min_sessions_per_group=2,
    )

    assert summary["status"] == "descriptive_only"
    assert summary["label"] == "描述性对比"
    assert summary["score_delta"] == 20.0
