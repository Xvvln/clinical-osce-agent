from app.services.training_event_store import TrainingEventStore


def test_training_event_store_appends_and_reads_session_events(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    store = TrainingEventStore(database_path)

    store.append_event(
        session_id="session_demo",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="history_message",
        payload={"message": "什么时候开始疼的？", "reply": "24 小时前开始，最初是上腹部隐痛。"},
    )
    store.append_event(
        session_id="session_demo",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="physical_exam_requested",
        payload={"exam_code": "abd.palpation.rebound"},
    )

    events = TrainingEventStore(database_path).list_session_events("session_demo")

    assert [event["event_type"] for event in events] == ["history_message", "physical_exam_requested"]
    assert events[0]["session_id"] == "session_demo"
    assert events[0]["case_id"] == "appendicitis_001"
    assert events[0]["student_id"] == "student_demo"
    assert events[0]["payload"] == {"message": "什么时候开始疼的？", "reply": "24 小时前开始，最初是上腹部隐痛。"}
    assert "created_at" in events[0]
    assert events[1]["payload"] == {"exam_code": "abd.palpation.rebound"}
