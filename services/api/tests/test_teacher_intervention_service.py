from __future__ import annotations

from app.services.teacher_intervention_service import (
    TeacherInterventionMode,
    append_teacher_decision_record,
    latest_student_safe_intervention,
    resolve_teacher_intervention,
)


def _state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "stage": "history_taking",
        "messages": [],
        "revealed_facts": [],
        "requested_exams": [],
        "requested_tests": [],
        "student_hypotheses": [],
        "patient_affect_state": {
            "current_emotion": "neutral",
            "unanswered_signal": False,
        },
        "teacher_decision_records": [],
    }
    state.update(overrides)
    return state


def _with_record(state: dict[str, object], decision: object) -> dict[str, object]:
    return {
        **state,
        "teacher_decision_records": append_teacher_decision_record(
            state.get("teacher_decision_records", []),
            decision,  # type: ignore[arg-type]
        ),
    }


def test_valid_history_progress_keeps_teacher_silent() -> None:
    decision = resolve_teacher_intervention(
        _state(revealed_facts=["appendicitis_001.hf_01"]),
        action_type="student_utterance",
    )

    assert decision.mode == TeacherInterventionMode.SILENT
    assert decision.reason_code == "no_intervention_needed"


def test_first_sequence_issue_is_observed_and_repeat_is_hinted() -> None:
    state = _state(
        stage="physical_exam",
        messages=[
            {
                "role": "student",
                "content": "我先说明腹部查体的目的和可能不适，请问您是否可以接受？",
            }
        ],
        requested_exams=["abd.palpation.rebound"],
    )
    first = resolve_teacher_intervention(state, action_type="physical_exam_requested")
    state = _with_record(state, first)
    second = resolve_teacher_intervention(state, action_type="physical_exam_requested")

    assert first.mode == TeacherInterventionMode.OBSERVE
    assert first.reason_code == "physical_exam_before_history"
    assert second.mode == TeacherInterventionMode.HINT
    assert "先补齐核心病史" in second.hint


def test_patient_signal_is_observed_then_ignored_signal_triggers_one_hint() -> None:
    signal_state = _state(
        patient_affect_state={"current_emotion": "anxious", "unanswered_signal": True},
    )
    observed = resolve_teacher_intervention(
        signal_state,
        action_type="student_utterance",
        affect_transition={"event": "patient_signal_detected"},
    )
    signal_state = _with_record(signal_state, observed)
    hinted = resolve_teacher_intervention(
        signal_state,
        action_type="student_utterance",
        affect_transition={"event": "emotion_ignored"},
    )
    signal_state = _with_record(signal_state, hinted)
    cooldown = resolve_teacher_intervention(
        signal_state,
        action_type="student_utterance",
        affect_transition={"event": "emotion_ignored"},
    )

    assert observed.mode == TeacherInterventionMode.OBSERVE
    assert hinted.mode == TeacherInterventionMode.HINT
    assert "回应患者" in hinted.hint
    assert cooldown.mode == TeacherInterventionMode.OBSERVE
    assert cooldown.reason_code == "patient_affect_hint_already_emitted"


def test_patient_repair_resolves_issue_and_stops_hinting() -> None:
    state = _state(
        patient_affect_state={"current_emotion": "anxious", "unanswered_signal": True},
    )
    hinted = resolve_teacher_intervention(
        state,
        action_type="student_utterance",
        affect_transition={"event": "emotion_ignored"},
    )
    state = _with_record(state, hinted)
    repaired_state = {
        **state,
        "patient_affect_state": {"current_emotion": "relieved", "unanswered_signal": False},
    }
    repaired = resolve_teacher_intervention(
        repaired_state,
        action_type="student_utterance",
        affect_transition={"event": "emotion_repaired"},
    )

    assert repaired.mode == TeacherInterventionMode.SILENT
    assert "humanistic:patient_affect_unanswered" in repaired.resolved_issue_ids


def test_procedure_without_consent_hints_once_and_consent_repairs_issue() -> None:
    state = _state(
        stage="physical_exam",
        revealed_facts=["appendicitis_001.hf_01"],
        requested_exams=["abd.palpation.rebound"],
    )
    first = resolve_teacher_intervention(state, action_type="physical_exam_requested")
    state = _with_record(state, first)
    repeated = resolve_teacher_intervention(state, action_type="physical_exam_requested")
    consented_state = {
        **state,
        "messages": [
            {
                "role": "student",
                "content": "我先说明腹部查体的目的和可能不适，请问您是否可以接受？",
            }
        ],
    }
    repaired = resolve_teacher_intervention(consented_state, action_type="physical_exam_requested")

    assert first.mode == TeacherInterventionMode.HINT
    assert first.reason_code == "procedure_without_consent_evidence"
    assert repeated.mode == TeacherInterventionMode.OBSERVE
    assert repaired.mode == TeacherInterventionMode.SILENT
    assert "humanistic:consent_before_procedure" in repaired.resolved_issue_ids


def test_answer_boundary_is_blocked_and_student_projection_is_safe() -> None:
    decision = resolve_teacher_intervention(
        _state(),
        action_type="student_utterance",
        boundary_kind="answer",
        forced_hint="我不能直接告诉你标准答案。",
    )
    records = append_teacher_decision_record([], decision)

    assert decision.mode == TeacherInterventionMode.BLOCK
    assert records[0]["created_at"].endswith("+00:00")
    assert latest_student_safe_intervention(records) == {
        "mode": "block",
        "trigger_kind": "answer_boundary",
        "message": "我不能直接告诉你标准答案。",
    }
