from __future__ import annotations

import json
from pathlib import Path

from app.services.deep_report_analysis_service import build_diagnostic_contrast_analysis
from app.validators.case_validator import validate_case


ROOT_DIR = Path(__file__).resolve().parents[3]


def _load_case(case_id: str = "appendicitis_001"):
    return validate_case(json.loads((ROOT_DIR / "data" / "cases" / f"{case_id}.json").read_text(encoding="utf-8")))


def _base_report(diagnosis: str, reasoning: str = "") -> dict:
    return {
        "case_id": "appendicitis_001",
        "final_submission": {"diagnosis": diagnosis, "reasoning": reasoning},
        "evidence_graph_summary": {
            "covered_evidence_nodes": [
                {"source_id": "appendicitis_001.hf_02", "label": "转移并固定右下腹痛"},
                {"source_id": "appendicitis_001.hf_05", "label": "无明显腹泻"},
            ],
            "missing_evidence_nodes": [
                {"source_id": "lab.urinalysis", "label": "尿常规"},
            ],
        },
        "clinical_reasoning_trace": {
            "cognitive_patterns": [
                {"pattern_id": "thin_differential_reasoning", "label": "鉴别诊断过窄", "severity": "medium"}
            ]
        },
        "training_gaps": [
            {"gap_type": "differential_reasoning_missing", "label": "补充鉴别诊断证据"}
        ],
    }


def test_diagnostic_contrast_explains_plausible_but_wrong_gastroenteritis() -> None:
    case = _load_case()

    analysis = build_diagnostic_contrast_analysis(
        report=_base_report("急性胃肠炎", "患者恶心，我考虑急性胃肠炎。"),
        case=case,
    )

    assert analysis["classification"] == "plausible_differential"
    assert analysis["submitted_diagnosis"] == "急性胃肠炎"
    assert analysis["target_diagnosis"] == "急性阑尾炎"
    assert analysis["matched_differential_name"] == "急性胃肠炎"
    assert any("恶心" in item for item in analysis["why_student_may_choose_it"])
    assert any("无明显腹泻" in item["label"] for item in analysis["evidence_against_submitted"])
    assert any("转移" in item["label"] for item in analysis["evidence_supporting_target"])
    assert any("尿常规" in item["label"] for item in analysis["missed_discriminating_evidence"])
    assert "先列支持依据" in analysis["next_training_action"]


def test_diagnostic_contrast_marks_main_diagnosis_correct_by_synonym() -> None:
    case = _load_case()

    analysis = build_diagnostic_contrast_analysis(
        report=_base_report("阑尾炎", "转移性右下腹痛支持阑尾炎。"),
        case=case,
    )

    assert analysis["classification"] == "correct"
    assert analysis["matched_target_terms"] == ["阑尾炎"]
    assert analysis["matched_differential_name"] == ""
    assert analysis["evidence_against_submitted"] == []
