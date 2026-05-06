import json

import pytest

from app.services.derived_teaching_focus_service import (
    build_case_baseline_focus,
    build_session_teaching_focus,
)
from app.services.focus_sanitizer import assert_student_safe_focus_text
from app.services.osce_session_service import OsceSession, load_case_node


def _payload_text(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _student_visible_focus_text(focus: dict[str, object]) -> str:
    visible_parts: list[str] = []
    for pattern in focus["patterns"]:
        visible_parts.extend(
            [
                pattern["title"],
                pattern["description"],
                pattern["training_suggestion"],
                pattern["why_now"],
            ]
        )
    return "\n".join(visible_parts)


def test_dynamic_teaching_focus_never_leaks_main_diagnosis() -> None:
    focus = build_case_baseline_focus("appendicitis_001")

    focus_text = _student_visible_focus_text(focus)

    assert "急性阑尾炎" not in focus_text
    assert "阑尾炎" not in focus_text
    assert "Acute appendicitis" not in focus_text
    assert "appendicitis" not in focus_text.lower()


def test_dynamic_teaching_focus_never_leaks_hidden_facts() -> None:
    case = load_case_node("appendicitis_001")
    session = OsceSession(
        session_id="focus_session_hidden_fact",
        student_id="student_focus",
        case_id=case.case_id,
        stage="case_intro",
    )

    focus = build_session_teaching_focus(session)
    focus_text = _student_visible_focus_text(focus)

    for hidden_fact in case.history.hidden_facts:
        assert hidden_fact.canonical_answer not in focus_text


def test_dynamic_teaching_focus_blocks_treatment_language() -> None:
    with pytest.raises(ValueError, match="unsafe medical action language"):
        assert_student_safe_focus_text("建议直接给出真实用药剂量并安排急症处置方案。")


def test_dynamic_teaching_focus_id_is_deterministic() -> None:
    first_focus = build_case_baseline_focus("appendicitis_001")
    second_focus = build_case_baseline_focus("appendicitis_001")

    assert first_focus == second_focus
    assert [pattern["focus_id"] for pattern in first_focus["patterns"]] == [
        "case_baseline:appendicitis_001:history_taking",
        "case_baseline:appendicitis_001:physical_exam",
        "case_baseline:appendicitis_001:auxiliary_test",
        "case_baseline:appendicitis_001:differential_diagnosis",
        "case_baseline:appendicitis_001:reasoning",
    ]


def test_dynamic_teaching_focus_generalizes_to_acs_and_appendicitis() -> None:
    appendicitis_focus = build_case_baseline_focus("appendicitis_001")
    acs_focus = build_case_baseline_focus("acs_001")

    appendicitis_pattern_ids = {pattern["focus_id"] for pattern in appendicitis_focus["patterns"]}
    acs_pattern_ids = {pattern["focus_id"] for pattern in acs_focus["patterns"]}
    assert appendicitis_pattern_ids
    assert acs_pattern_ids
    assert appendicitis_pattern_ids != acs_pattern_ids

    acs_text = _student_visible_focus_text(acs_focus)
    assert "急性冠脉综合征" not in acs_text
    assert "ACS" not in acs_text
    assert "急性心肌梗死" not in acs_text

    assert any(
        set(pattern["trigger_item_ids"]) >= {"ht_onset", "ht_migration"}
        for pattern in appendicitis_focus["patterns"]
    )
    assert any(
        set(pattern["trigger_item_ids"]) >= {"at_ecg", "at_troponin"}
        for pattern in acs_focus["patterns"]
    )
