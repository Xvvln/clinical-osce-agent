from __future__ import annotations

import json
from types import SimpleNamespace

from app.services.osce_session_service import _personal_skill_payload_for_report
from app.services.teacher_longitudinal_context_service import (
    build_teacher_longitudinal_context,
)


def _entry(
    session_id: str,
    *,
    score: int,
    missed_items: list[str],
    patterns: list[tuple[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "case_id": "appendicitis_001",
        "report": {
            "session_id": session_id,
            "case_id": "appendicitis_001",
            "total_score": score,
            "max_score": 100,
            "missed_items": missed_items,
            "clinical_reasoning_trace": {
                "cognitive_patterns": [
                    {"pattern_id": pattern_id, "label": label}
                    for pattern_id, label in (patterns or [])
                ],
                "action_timeline": [{"raw_payload": "完整对话不应进入纵向上下文"}],
            },
            "hidden_case_fact": "不应进入纵向上下文",
        },
    }


def test_longitudinal_context_distinguishes_first_repeated_reactivated_and_recovered_gaps() -> None:
    entries = [
        _entry(
            "current",
            score=72,
            missed_items=["ht_migration", "pe_tenderness", "rs_exclude"],
            patterns=[("weak_hypothesis_testing", "假设验证不足")],
        ),
        _entry(
            "previous",
            score=80,
            missed_items=["pe_tenderness", "ax_cbc"],
            patterns=[("weak_hypothesis_testing", "假设验证不足")],
        ),
        _entry(
            "older",
            score=55,
            missed_items=["ht_migration"],
        ),
    ]
    events_by_session = {
        "current": [
            {
                "event_type": "training_skill_applied",
                "payload": {
                    "skill_id": "skill_personal_previous",
                    "scope": "personal",
                    "title": "先形成假设再检查",
                    "skill_type": "reasoning_bridge",
                    "effect_status": "improving",
                },
            },
            {
                "event_type": "training_skill_applied",
                "payload": {
                    "skill_id": "skill_global_history",
                    "scope": "global",
                    "title": "全局 Skill",
                },
            },
        ]
    }

    context = build_teacher_longitudinal_context(
        entries,
        events_by_session=events_by_session,
    )

    statuses = {
        item["gap_id"]: item["status"]
        for item in context["current_gap_statuses"]
    }
    assert statuses["ht_migration"] == "reactivated_after_improvement"
    assert statuses["pe_tenderness"] == "repeated"
    assert statuses["rs_exclude"] == "first_seen_current_window"
    assert statuses["weak_hypothesis_testing"] == "repeated"
    assert context["recovered_gaps"][0]["gap_id"] == "ax_cbc"
    assert context["score_trend"]["direction"] == "improving"
    assert [point["score_percent"] for point in context["score_trend"]["points"]] == [55.0, 80.0, 72.0]
    assert context["applied_personal_skills"] == [
        {
            "report_offset": 0,
            "title": "先形成假设再检查",
            "skill_type": "reasoning_bridge",
            "effect_status": "improving",
            "evidence": "training_skill_applied_event",
        }
    ]
    serialized = json.dumps(context, ensure_ascii=False)
    assert "完整对话不应进入纵向上下文" not in serialized
    assert "hidden_case_fact" not in serialized
    assert '"current"' not in serialized
    assert "student_id" not in serialized


def test_longitudinal_context_uses_only_three_most_recent_reports() -> None:
    context = build_teacher_longitudinal_context(
        [
            _entry("current", score=70, missed_items=[]),
            _entry("previous", score=65, missed_items=[]),
            _entry("older", score=60, missed_items=[]),
            _entry("outside-window", score=10, missed_items=["ht_onset"]),
        ]
    )

    assert context["report_window_size"] == 3
    assert [point["score_percent"] for point in context["score_trend"]["points"]] == [60.0, 65.0, 70.0]
    assert context["current_gap_statuses"] == []


def test_longitudinal_score_points_do_not_claim_direction_across_mixed_cases() -> None:
    current = _entry("current", score=90, missed_items=[])
    previous = _entry("previous", score=40, missed_items=[])
    current["case_id"] = "acs_001"
    current["report"]["case_id"] = "acs_001"

    context = build_teacher_longitudinal_context([current, previous])

    assert context["score_trend"]["direction"] == "mixed_context_not_directly_comparable"


def test_report_enrichment_passes_same_students_recent_context_to_personal_skill_service() -> None:
    current_report = _entry(
        "current",
        score=68,
        missed_items=["ht_migration"],
    )["report"]
    historical_reports = {
        "previous": _entry(
            "previous",
            score=76,
            missed_items=[],
        )["report"],
        "older": _entry(
            "older",
            score=50,
            missed_items=["ht_migration"],
        )["report"],
        "outside-window": _entry(
            "outside-window",
            score=10,
            missed_items=["ax_cbc"],
        )["report"],
    }

    class SessionStore:
        def list_user_session_summaries(self, student_id: str) -> list[dict[str, object]]:
            assert student_id == "student-a"
            return [
                {"session_id": "current", "case_id": "appendicitis_001", "has_report": True},
                {"session_id": "previous", "case_id": "appendicitis_001", "has_report": True},
                {"session_id": "older", "case_id": "appendicitis_001", "has_report": True},
                {"session_id": "outside-window", "case_id": "appendicitis_001", "has_report": True},
            ]

    class ReportStore:
        def get_report(self, session_id: str) -> dict[str, object] | None:
            return historical_reports.get(session_id)

    class EventStore:
        def list_events_for_sessions(self, session_ids: list[str]) -> dict[str, list[dict[str, object]]]:
            assert session_ids == ["current", "previous", "older"]
            return {
                "current": [
                    {
                        "event_type": "training_skill_applied",
                        "payload": {
                            "skill_id": "skill_personal_previous",
                            "scope": "personal",
                            "title": "补齐问题表征",
                        },
                    }
                ]
            }

    class CapturingPersonalSkillService:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        def generate_for_completed_session(self, **kwargs: object) -> dict[str, object]:
            self.kwargs = kwargs
            return {
                "personal_skill_candidate": {"status": "approved"},
                "ai_reflection_review": {"status": "generated"},
            }

    personal_skill_service = CapturingPersonalSkillService()
    service = SimpleNamespace(
        personal_skill_service=personal_skill_service,
        session_store=SessionStore(),
        report_store=ReportStore(),
        training_event_store=EventStore(),
        training_skill_candidate_store=object(),
        training_skill_store=object(),
    )
    session = SimpleNamespace(
        session_id="current",
        student_id="student-a",
        case_id="appendicitis_001",
        training_difficulty="intermediate",
        final_submission={"diagnosis": "已提交"},
        feedback_report=current_report,
    )

    payload = _personal_skill_payload_for_report(
        service,
        session,
        SimpleNamespace(case_id="appendicitis_001"),
    )

    context = personal_skill_service.kwargs["teacher_longitudinal_context"]
    assert isinstance(context, dict)
    assert context["report_window_size"] == 3
    assert context["current_gap_statuses"][0]["status"] == "reactivated_after_improvement"
    assert context["applied_personal_skills"][0]["title"] == "补齐问题表征"
    assert payload["personal_skill_candidate"]["status"] == "approved"
