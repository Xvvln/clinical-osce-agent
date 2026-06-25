from __future__ import annotations

from app.services.patient_affect_state_service import (
    build_initial_patient_affect_state,
    update_affect_after_patient_reply,
    update_affect_before_patient_reply,
)


def test_patient_reply_with_worry_creates_unanswered_affect_signal() -> None:
    state = build_initial_patient_affect_state()

    next_state, transition = update_affect_after_patient_reply(
        state,
        patient_reply="我有点害怕，是不是需要马上开刀？",
        patient_emotion="焦虑",
        turn_id="turn:1",
    )

    assert next_state["current_emotion"] == "anxious"
    assert next_state["current_emotion_label"] == "焦虑"
    assert next_state["intensity"] == 2
    assert next_state["unanswered_signal"] is True
    assert next_state["last_transition"] == "patient_signal_detected"
    assert transition["event"] == "patient_signal_detected"
    assert transition["turn_id"] == "turn:1"


def test_empathy_response_repairs_unanswered_affect_signal() -> None:
    state, _ = update_affect_after_patient_reply(
        build_initial_patient_affect_state(),
        patient_reply="我很担心是不是很严重。",
        patient_emotion="担忧",
        turn_id="turn:1",
    )

    next_state, transition = update_affect_before_patient_reply(
        state,
        student_message="我理解你的担心，我们先把疼痛情况问清楚，再判断下一步。",
        turn_id="turn:2",
    )

    assert next_state["current_emotion"] == "relieved"
    assert next_state["current_emotion_label"] == "欣慰"
    assert next_state["intensity"] == 1
    assert next_state["unanswered_signal"] is False
    assert next_state["last_student_response"] == "empathy_acknowledged"
    assert transition["event"] == "emotion_repaired"
    assert transition["student_response_type"] == "empathy_acknowledged"


def test_medical_question_after_patient_worry_marks_emotion_ignored() -> None:
    state, _ = update_affect_after_patient_reply(
        build_initial_patient_affect_state(),
        patient_reply="我有点害怕是不是要手术。",
        patient_emotion="焦虑",
        turn_id="turn:1",
    )

    next_state, transition = update_affect_before_patient_reply(
        state,
        student_message="疼痛有没有向其他地方转移？",
        turn_id="turn:2",
    )

    assert next_state["current_emotion"] == "anxious"
    assert next_state["intensity"] == 3
    assert next_state["unanswered_signal"] is True
    assert next_state["last_student_response"] == "ignored"
    assert transition["event"] == "emotion_ignored"
    assert transition["student_response_type"] == "ignored"


def test_patient_affect_state_trajectory_is_bounded() -> None:
    state = build_initial_patient_affect_state()

    for index in range(15):
        state, _ = update_affect_after_patient_reply(
            state,
            patient_reply=f"第 {index} 次担心。",
            patient_emotion="担忧",
            turn_id=f"turn:{index}",
            max_trajectory=5,
        )

    assert len(state["trajectory"]) == 5
    assert state["trajectory"][0]["turn_id"] == "turn:10"
