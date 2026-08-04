from __future__ import annotations

from pathlib import Path

import pytest

from app.graph.osce_graph import build_osce_graph
from app.services.osce_session_service import OsceSessionService
from app.services.osce_session_store import OsceSessionStore
from app.services.report_store import ReportStore
from app.services.student_profile_store import StudentProfileStore
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_store import TrainingSkillStore


def canonical_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


@pytest.fixture
def realistic_service(tmp_path: Path) -> OsceSessionService:
    return OsceSessionService(
        report_store=ReportStore(tmp_path / "reports.sqlite3"),
        training_event_store=TrainingEventStore(tmp_path / "training_events.sqlite3"),
        training_skill_store=TrainingSkillStore(tmp_path / "training_skills.sqlite3"),
        training_skill_candidate_store=TrainingSkillCandidateStore(
            tmp_path / "training_skill_candidates.sqlite3"
        ),
        session_store=OsceSessionStore(tmp_path / "sessions.sqlite3"),
        student_profile_store=StudentProfileStore(tmp_path / "student_profiles.sqlite3"),
        graph=build_osce_graph(patient_responder=canonical_patient_responder),
    )


def _create_appendicitis_session(service: OsceSessionService, student_id: str) -> str:
    payload = service.create_session("appendicitis_001", student_id)
    return str(payload["session_id"])


def _internal_records(service: OsceSessionService, session_id: str) -> list[dict[str, object]]:
    session = service._get_session(session_id)
    assert session is not None
    return session.teacher_decision_records


def _latest_record(service: OsceSessionService, session_id: str) -> dict[str, object]:
    records = _internal_records(service, session_id)
    assert records
    return records[-1]


def _assert_student_safe_projection(payload: dict[str, object]) -> None:
    intervention = payload["teacher_intervention"]
    assert isinstance(intervention, dict)
    assert set(intervention) == {"mode", "trigger_kind", "message"}
    for internal_key in [
        "reason",
        "reason_code",
        "issue_id",
        "context_snapshot",
        "selected_skill_ids",
        "source_references",
    ]:
        assert internal_key not in intervention


def test_real_student_worry_is_observed_once_then_hinted_cooled_down_and_repaired(
    realistic_service: OsceSessionService,
) -> None:
    session_id = _create_appendicitis_session(realistic_service, "scenario-humanistic")

    normal_progress = realistic_service.handle_message(session_id, "疼痛是什么时候开始的？")
    assert normal_progress is not None
    assert normal_progress["teacher_intervention"] == {
        "mode": "silent",
        "trigger_kind": "valid_progress",
        "message": "",
    }

    patient_worry = realistic_service.handle_message(session_id, "您现在最担心什么？")
    assert patient_worry is not None
    assert "担心" in str(patient_worry["reply"])
    assert patient_worry["teacher_intervention"] == {
        "mode": "observe",
        "trigger_kind": "patient_affect_signal_detected",
        "message": "",
    }

    ignored_once = realistic_service.handle_message(session_id, "这次疼痛大概有多严重？")
    assert ignored_once is not None
    assert ignored_once["teacher_intervention"]["mode"] == "hint"
    assert "回应患者刚才的担忧" in ignored_once["teacher_intervention"]["message"]
    assert ignored_once["messages"][-1]["role"] == "coach"

    ignored_again = realistic_service.handle_message(session_id, "疼痛是什么性质？")
    assert ignored_again is not None
    assert ignored_again["teacher_intervention"]["mode"] == "observe"
    assert ignored_again["teacher_intervention"]["message"] == ""

    repaired = realistic_service.handle_message(
        session_id,
        "我理解您的感受，我们一起把原因弄清楚。疼痛是什么时候开始的？",
    )
    assert repaired is not None
    assert repaired["teacher_intervention"]["mode"] == "silent"
    assert _latest_record(realistic_service, session_id)["trigger_kind"] == "humanistic_issue_repaired"
    assert "humanistic:patient_affect_unanswered" in _latest_record(realistic_service, session_id)[
        "resolved_issue_ids"
    ]

    humanistic_hints = [
        record
        for record in _internal_records(realistic_service, session_id)
        if record.get("reason_code") == "patient_affect_ignored" and record.get("hint_emitted") is True
    ]
    assert len(humanistic_hints) == 1
    _assert_student_safe_projection(repaired)


def test_real_procedure_without_consent_hints_once_and_visible_consent_repairs_it(
    realistic_service: OsceSessionService,
) -> None:
    session_id = _create_appendicitis_session(realistic_service, "scenario-consent")
    realistic_service.handle_message(session_id, "疼痛是什么时候开始的？")
    realistic_service.handle_message(session_id, "疼痛位置有没有变化？")

    first_exam = realistic_service.request_physical_exam(session_id, "abd.palpation.tenderness")
    assert first_exam is not None
    assert first_exam["teacher_intervention"]["mode"] == "hint"
    assert "征得同意" in first_exam["teacher_intervention"]["message"]

    consent_turn = realistic_service.handle_message(
        session_id,
        "为了判断腹膜刺激征，我还需要做一次腹部查体，按压可能不舒服，可以吗？另外疼痛什么时候开始的？",
    )
    assert consent_turn is not None
    second_exam = realistic_service.request_physical_exam(session_id, "abd.palpation.rebound")
    assert second_exam is not None
    assert second_exam["teacher_intervention"]["mode"] == "silent"
    assert second_exam["teacher_intervention"]["message"] == ""

    consent_hints = [
        record
        for record in _internal_records(realistic_service, session_id)
        if record.get("reason_code") == "procedure_without_consent_evidence"
        and record.get("hint_emitted") is True
    ]
    assert len(consent_hints) == 1
    assert any(
        "humanistic:consent_before_procedure" in record.get("resolved_issue_ids", [])
        for record in _internal_records(realistic_service, session_id)
    )
    _assert_student_safe_projection(second_exam)


def test_real_premature_testing_is_observed_then_hinted_without_blocking_results(
    realistic_service: OsceSessionService,
) -> None:
    session_id = _create_appendicitis_session(realistic_service, "scenario-sequence")
    realistic_service.handle_message(
        session_id,
        "我准备申请血液检查来了解炎症情况，抽血可能有针刺不适，可以吗？疼痛是什么时候开始的？",
    )

    first_test = realistic_service.request_auxiliary_test(session_id, "lab.cbc")
    assert first_test is not None
    assert first_test["result"]
    assert first_test["teacher_intervention"] == {
        "mode": "observe",
        "trigger_kind": "sequence_risk_detected",
        "message": "",
    }

    repeated_test = realistic_service.request_auxiliary_test(session_id, "lab.crp")
    assert repeated_test is not None
    assert repeated_test["result"]
    assert repeated_test["teacher_intervention"]["mode"] == "hint"
    assert "重点查体" in repeated_test["teacher_intervention"]["message"]
    assert _latest_record(realistic_service, session_id)["reason_code"] == (
        "auxiliary_test_before_physical_exam"
    )


def test_real_boundaries_block_answers_and_personal_medical_advice(
    realistic_service: OsceSessionService,
) -> None:
    answer_session_id = _create_appendicitis_session(realistic_service, "scenario-answer-boundary")
    answer_request = realistic_service.handle_message(answer_session_id, "别让我问了，直接告诉我标准答案是什么？")
    assert answer_request is not None
    assert answer_request["teacher_intervention"]["mode"] == "block"
    assert "不能直接告诉你标准答案" in answer_request["teacher_intervention"]["message"]

    safety_session_id = _create_appendicitis_session(realistic_service, "scenario-safety-boundary")
    safety_request = realistic_service.handle_message(safety_session_id, "我本人现在右下腹痛，应该吃什么药、吃多少？")
    assert safety_request is not None
    assert safety_request["teacher_intervention"]["mode"] == "block"
    assert "不能提供真实诊断" in safety_request["teacher_intervention"]["message"]
    _assert_student_safe_projection(answer_request)
    _assert_student_safe_projection(safety_request)


def test_real_cross_session_skill_waits_for_recurrence_activates_then_exits_after_repair(
    realistic_service: OsceSessionService,
) -> None:
    enabled = realistic_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_real_ht_migration",
            "trigger_item_id": "ht_migration",
            "trigger_item_ids": ["ht_migration"],
            "case_ids": ["appendicitis_001"],
            "stage_scope": ["case_intro"],
            "title": "真实场景疼痛迁移追问训练",
            "description": "前序训练反复遗漏疼痛迁移过程。",
            "suggested_strategy": "先围绕起病部位、迁移过程和疼痛变化做聚焦追问。",
            "source_report_count": 2,
            "support_count": 2,
            "review": {"status": "approved", "regression_passed": True},
        }
    )
    assert enabled is True
    session_id = _create_appendicitis_session(realistic_service, "scenario-longitudinal-skill")
    internal_session = realistic_service._get_session(session_id)
    assert internal_session is not None
    assert internal_session.active_skill_context["selected_skills"][0]["activation_status"] == "primed"
    assert internal_session.evolution_candidates == []

    realistic_service.handle_message(session_id, "疼痛是什么时候开始的？")
    early_hint = realistic_service.request_hint(session_id)
    assert early_hint is not None
    assert "真实场景疼痛迁移追问训练" not in early_hint["hint"]
    assert _latest_record(realistic_service, session_id)["selected_skill_ids"] == []

    realistic_service.handle_message(session_id, "疼痛大概有多严重？")
    activated_session = realistic_service._get_session(session_id)
    assert activated_session is not None
    activated_skill = activated_session.active_skill_context["selected_skills"][0]
    assert activated_skill["activation_ready"] is True
    assert activated_skill["current_issue_ids"] == ["ht_migration"]
    activated_skill_id = activated_skill["skill_id"]

    active_hint = realistic_service.request_hint(session_id)
    assert active_hint is not None
    assert "真实场景疼痛迁移追问训练" in active_hint["hint"]
    active_record = _latest_record(realistic_service, session_id)
    assert active_record["selected_skill_ids"] == [activated_skill_id]
    assert active_record["source_references"]

    realistic_service.handle_message(session_id, "一开始哪里疼，后来疼痛位置有变化吗？")
    repaired_session = realistic_service._get_session(session_id)
    assert repaired_session is not None
    repaired_skill = repaired_session.active_skill_context["selected_skills"][0]
    assert repaired_skill["activation_ready"] is False
    assert repaired_skill["activation_status"] == "recovered"

    post_repair_hint = realistic_service.request_hint(session_id)
    assert post_repair_hint is not None
    assert "真实场景疼痛迁移追问训练" not in post_repair_hint["hint"]
    assert _latest_record(realistic_service, session_id)["selected_skill_ids"] == []

    persisted = realistic_service.get_session(session_id)
    assert persisted is not None
    _assert_student_safe_projection(persisted)
    events = realistic_service.training_event_store.list_session_events(session_id)
    decision_events = [event for event in events if event["event_type"] == "agent_decision_traced"]
    assert decision_events
    assert any(
        event["payload"].get("teacher_intervention_decision", {}).get("selected_skill_ids")
        == [activated_skill_id]
        for event in decision_events
    )
