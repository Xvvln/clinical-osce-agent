import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

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


def test_training_event_store_migrates_legacy_schema_and_preserves_unkeyed_events(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE training_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                student_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO training_events (
                session_id,
                case_id,
                student_id,
                event_type,
                payload_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy_session",
                "legacy_case",
                "legacy_student",
                "legacy_event",
                '{"legacy": true}',
                "2026-07-28T00:00:00+00:00",
            ),
        )

    store = TrainingEventStore(database_path)

    assert store.append_event(
        session_id="legacy_session",
        case_id="legacy_case",
        student_id="legacy_student",
        event_type="unkeyed_event",
        payload={"sequence": 1},
    )
    assert store.append_event(
        session_id="legacy_session",
        case_id="legacy_case",
        student_id="legacy_student",
        event_type="unkeyed_event",
        payload={"sequence": 2},
    )

    events = store.list_session_events("legacy_session")
    assert [event["event_key"] for event in events] == [None, None, None]
    assert [event["payload"] for event in events] == [
        {"legacy": True},
        {"sequence": 1},
        {"sequence": 2},
    ]


def test_training_event_store_replays_keyed_event_without_duplicate_insert(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    store = TrainingEventStore(database_path)

    first_result = store.append_event(
        session_id="session_demo",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="report_generated",
        payload={"attempt": 1},
        event_key="report/session_demo/final",
    )
    replay_result = store.append_event(
        session_id="session_demo",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="report_generated",
        payload={"attempt": 2},
        event_key="report/session_demo/final",
    )
    different_key_result = store.append_event(
        session_id="session_demo",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="report_generated",
        payload={"attempt": 3},
        event_key="report/session_demo/revision-2",
    )

    assert first_result is True
    assert replay_result is False
    assert different_key_result is True
    events = store.list_session_events("session_demo")
    assert len(events) == 2
    assert events[0] == {
        "session_id": "session_demo",
        "case_id": "appendicitis_001",
        "student_id": "student_demo",
        "event_type": "report_generated",
        "event_key": "report/session_demo/final",
        "payload": {"attempt": 1},
        "created_at": events[0]["created_at"],
    }
    assert events[1]["event_key"] == "report/session_demo/revision-2"
    assert events[1]["payload"] == {"attempt": 3}


def test_training_event_store_event_key_is_globally_unique(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    store = TrainingEventStore(database_path)

    assert store.append_event(
        session_id="session_a",
        case_id="case_a",
        student_id="student_a",
        event_type="report_generated",
        payload={"owner": "a"},
        event_key="report/stable-domain-key",
    )
    assert not store.append_event(
        session_id="session_b",
        case_id="case_b",
        student_id="student_b",
        event_type="report_generated",
        payload={"owner": "b"},
        event_key="report/stable-domain-key",
    )

    events_by_session = store.list_events_for_sessions(["session_a", "session_b"])
    assert [event["payload"] for event in events_by_session["session_a"]] == [{"owner": "a"}]
    assert events_by_session["session_b"] == []


def test_training_event_store_two_instances_insert_same_event_key_once(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    stores = [TrainingEventStore(database_path), TrainingEventStore(database_path)]
    barrier = Barrier(2)

    def append(store: TrainingEventStore, attempt: int) -> bool:
        barrier.wait()
        return store.append_event(
            session_id="session_concurrent",
            case_id="appendicitis_001",
            student_id="student_demo",
            event_type="report_generated",
            payload={"attempt": attempt},
            event_key="report/session_concurrent/final",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(append, stores, (1, 2)))

    assert sorted(results) == [False, True]
    events = TrainingEventStore(database_path).list_session_events("session_concurrent")
    assert len(events) == 1
    assert events[0]["event_key"] == "report/session_concurrent/final"
    assert events[0]["payload"] in ({"attempt": 1}, {"attempt": 2})
