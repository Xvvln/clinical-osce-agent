from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.clinical_reasoning_trace_service import build_clinical_reasoning_trace
from app.validators.case_validator import validate_case


ROOT_DIR = Path(__file__).resolve().parents[3]


def _load_case(case_id: str = "appendicitis_001"):
    return validate_case(json.loads((ROOT_DIR / "data" / "cases" / f"{case_id}.json").read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("case_id", "expected_focus"),
    [
        ("appendicitis_001", "追问疼痛部位及转移特征"),
        ("acs_001", "追问胸痛起病时间与诱因"),
        ("heart_failure_001", "追问气短进展情况"),
        ("hyperthyroid_001", "追问怕热多汗与多食消瘦"),
        ("pneumonia_001", "追问痰液性质"),
    ],
)
def test_problem_representation_guidance_uses_each_case_rubric_labels(
    case_id: str,
    expected_focus: str,
) -> None:
    case = _load_case(case_id)
    session = SimpleNamespace(
        session_id=f"{case_id}-semantic-regression",
        case_id=case_id,
        revealed_facts=[],
        requested_exams=[],
        requested_tests=[],
        student_hypotheses=[],
        final_submission={"diagnosis": "待完善", "reasoning": ""},
    )
    report = {
        "report_id": f"{case_id}-semantic-regression_report",
        "case_id": case_id,
        "missed_items": [],
        "dimension_scores": {},
    }

    trace = build_clinical_reasoning_trace(session=session, case=case, report=report)

    weak_pattern = next(
        pattern
        for pattern in trace["cognitive_patterns"]
        if pattern["pattern_id"] == "weak_problem_representation"
    )
    guidance_text = json.dumps(
        {
            "pattern": weak_pattern,
            "questions": trace["teacher_focus_questions"],
        },
        ensure_ascii=False,
    )
    assert expected_focus in guidance_text
    if case_id != "appendicitis_001":
        for irrelevant_phrase in ["腹痛六问", "急腹症", "部位变化", "腹膜刺激征"]:
            assert irrelevant_phrase not in guidance_text


def test_trace_extracts_general_reasoning_patterns_from_case_schema() -> None:
    case = _load_case()
    session = SimpleNamespace(
        session_id="trace-session",
        case_id=case.case_id,
        revealed_facts=["appendicitis_001.hf_01"],
        requested_exams=[],
        requested_tests=["lab.cbc"],
        student_hypotheses=[],
        final_submission={"diagnosis": "急性阑尾炎", "reasoning": "考虑急性阑尾炎。"},
    )
    report = {
        "report_id": "trace-session_report",
        "case_id": case.case_id,
        "missed_items": ["ht_migration", "ht_character", "dxd_urolith", "rs_exclude"],
        "dimension_scores": {
            "history_taking": 3,
            "physical_exam": 0,
            "auxiliary_test": 2,
            "differential_diagnosis": 0,
            "reasoning": 0,
        },
    }

    trace = build_clinical_reasoning_trace(session=session, case=case, report=report)

    assert trace["trace_version"] == "clinical_reasoning_trace_v1"
    assert trace["problem_representation"]["status"] == "weak"
    missing_labels = {item["label"] for item in trace["problem_representation"]["missing_semantic_qualifiers"]}
    assert "追问疼痛部位及转移特征" in missing_labels
    assert "追问疼痛性质" in missing_labels

    script_missing = trace["illness_script_alignment"]["missing_script_elements"]
    assert any("转移性右下腹痛" in item["statement"] for item in script_missing)

    pattern_ids = {pattern["pattern_id"] for pattern in trace["cognitive_patterns"]}
    assert {
        "weak_problem_representation",
        "premature_testing_before_exam",
        "delayed_hypothesis_generation",
        "thin_differential_reasoning",
    } <= pattern_ids
    for pattern in trace["cognitive_patterns"]:
        assert pattern["label"]
        assert pattern["why_it_matters"]
        assert pattern["remediation"]
        assert isinstance(pattern["source_signal_ids"], list)


def test_trace_uses_action_timeline_to_detect_tests_before_later_exam() -> None:
    case = _load_case()
    session = SimpleNamespace(
        session_id="timeline-session",
        case_id=case.case_id,
        revealed_facts=["appendicitis_001.hf_01"],
        requested_exams=["abd.palpation.rebound"],
        requested_tests=["lab.cbc"],
        student_hypotheses=[],
        final_submission={"diagnosis": "急性阑尾炎", "reasoning": "考虑急性阑尾炎。"},
        action_timeline=[
            {
                "turn_index": 1,
                "action_type": "history_fact_revealed",
                "source_id": "appendicitis_001.hf_01",
                "label": "起病时间",
            },
            {
                "turn_index": 2,
                "action_type": "auxiliary_test_requested",
                "source_id": "lab.cbc",
                "label": "血常规",
            },
            {
                "turn_index": 3,
                "action_type": "physical_exam_requested",
                "source_id": "abd.palpation.rebound",
                "label": "反跳痛",
            },
            {
                "turn_index": 4,
                "action_type": "diagnosis_submitted",
                "source_id": "final_submission",
                "label": "提交诊断",
            },
        ],
    )
    report = {
        "report_id": "timeline-session_report",
        "case_id": case.case_id,
        "missed_items": ["ht_migration", "pe_tenderness", "rs_exclude"],
        "dimension_scores": {"reasoning": 0},
    }

    trace = build_clinical_reasoning_trace(session=session, case=case, report=report)

    assert trace["action_order_summary"]["first_auxiliary_test_turn_index"] == 2
    assert trace["action_order_summary"]["first_physical_exam_turn_index"] == 3
    assert trace["action_timeline"][1]["action_type"] == "auxiliary_test_requested"
    flag_ids = {flag["flag_id"] for flag in trace["hypothesis_testing"]["sequence_flags"]}
    assert "premature_testing_before_exam" in flag_ids
    pattern_ids = {pattern["pattern_id"] for pattern in trace["cognitive_patterns"]}
    assert "premature_testing_before_exam" in pattern_ids


def test_trace_builds_readable_evidence_chain_breakpoints_from_reasoning_points() -> None:
    case = _load_case()
    session = SimpleNamespace(
        session_id="breakpoint-session",
        case_id=case.case_id,
        revealed_facts=["appendicitis_001.hf_01"],
        requested_exams=[],
        requested_tests=["lab.cbc"],
        student_hypotheses=[],
        final_submission={"diagnosis": "急性阑尾炎", "reasoning": "考虑急性阑尾炎。"},
    )
    report = {
        "report_id": "breakpoint-session_report",
        "case_id": case.case_id,
        "missed_items": ["ht_migration", "pe_tenderness", "rs_exclude"],
        "dimension_scores": {"reasoning": 0, "differential_diagnosis": 0},
    }

    trace = build_clinical_reasoning_trace(session=session, case=case, report=report)

    breakpoints = trace["evidence_chain_breakpoints"]
    assert breakpoints
    first = breakpoints[0]
    assert first["breakpoint_id"]
    assert first["statement"]
    assert first["kind"] in {"support", "exclude", "differentiate", "risk"}
    assert first["missing_evidence"]
    assert first["missing_evidence_labels"]
    assert all("." not in label for label in first["missing_evidence_labels"])
    assert first["teacher_action"]
