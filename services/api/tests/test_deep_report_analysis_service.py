from __future__ import annotations

import json
from pathlib import Path

from app.services.deep_report_analysis_service import build_deep_report_analysis, build_diagnostic_contrast_analysis
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


def test_deep_report_analysis_builds_overall_task_and_evidence_sections() -> None:
    case = _load_case()
    report = _base_report("急性胃肠炎", "患者恶心，我考虑急性胃肠炎。") | {
        "total_score": 28,
        "max_score": 100,
        "score_groups": {
            "clinical_osce": {"score": 24, "max_score": 70},
            "humanistic_communication": {"score": 4, "max_score": 30},
        },
        "dimension_scores": {
            "history_taking": 12,
            "physical_exam": 0,
            "auxiliary_test": 0,
            "main_diagnosis": 0,
            "differential_diagnosis": 0,
            "reasoning": 2,
        },
        "dimension_traces": {
            "history_taking": [
                {
                    "item_id": "ht_migration",
                    "label": "追问疼痛转移",
                    "score": 4,
                    "max_score": 4,
                    "matched_evidence": ["appendicitis_001.hf_02"],
                }
            ],
            "physical_exam": [
                {
                    "item_id": "pe_rebound",
                    "label": "检查反跳痛",
                    "score": 0,
                    "max_score": 4,
                    "gap_type": "physical_exam_missing",
                    "next_training_action": "补充腹部局部体征。",
                }
            ],
            "reasoning": [
                {
                    "item_id": "rs_exclusion",
                    "label": "表达排除依据",
                    "score": 0,
                    "max_score": 4,
                    "gap_type": "reasoning_exclusion_missing",
                    "next_training_action": "提交前写出排除依据。",
                }
            ],
        },
        "evidence_graph_summary": {
            "covered_evidence_nodes": [
                {"node_id": "ev_migratory_rlq_pain", "source_id": "appendicitis_001.hf_02", "label": "转移并固定右下腹痛"},
                {"node_id": "nf_no_diarrhea", "source_id": "appendicitis_001.hf_05", "label": "无明显腹泻"},
            ],
            "missing_evidence_nodes": [
                {"node_id": "ev_peritoneal_signs", "source_id": "abd.palpation.rebound", "label": "反跳痛"},
                {"node_id": "nf_urinalysis_negative", "source_id": "lab.urinalysis", "label": "尿常规阴性"},
            ],
        },
        "clinical_reasoning_trace": {
            "cognitive_patterns": [
                {"pattern_id": "hypothesis_delayed", "label": "诊断假设生成偏晚", "severity": "medium"}
            ],
            "sequence_flags": [
                {"flag_id": "late_hypothesis", "label": "诊断假设生成偏晚", "severity": "medium", "evidence": "提交前才形成明确假设"}
            ],
        },
        "training_gaps": [
            {"gap_type": "physical_exam_missing", "label": "缺少腹部局部体征", "severity": "high"},
            {"gap_type": "reasoning_exclusion_missing", "label": "排除依据不足", "severity": "medium"},
        ],
    }

    analysis = build_deep_report_analysis(report=report, case=case)

    overall = analysis["overall_evaluation"]
    assert overall["score_interpretation"] == "本轮总分 28/100，临床 OSCE 24/70，人文沟通 4/30。"
    assert overall["completion_judgement"] == "needs_rebuild"
    assert any("病史采集" in item for item in overall["primary_strengths"])
    assert "缺少腹部局部体征" in overall["primary_weaknesses"]

    task = analysis["clinical_task_analysis"]["physical_exam"]
    assert task["label"] == "查体"
    assert task["completion_level"] == "missing"
    assert task["missed_items"][0]["label"] == "检查反跳痛"
    assert "补充腹部局部体征" in task["next_action"]

    evidence = analysis["evidence_utilization_analysis"]
    assert evidence["collected_key_evidence"][0]["label"] == "转移并固定右下腹痛"
    assert any(item["label"] == "尿常规阴性" for item in evidence["missing_key_evidence"])
    assert any("尿常规阴性有助于排除输尿管结石" in item["statement"] for item in evidence["evidence_chain_breakpoints"])

    process = analysis["process_strategy_analysis"]
    assert process["sequence_flags"][0]["label"] == "诊断假设生成偏晚"
    assert "先形成诊断假设" in process["premature_or_delayed_actions"][0]


def test_deep_report_analysis_hydrates_trace_summary_from_rubric_item_id() -> None:
    case = _load_case()
    report = _base_report("急性阑尾炎", "转移性右下腹痛支持阑尾炎。") | {
        "total_score": 30,
        "max_score": 100,
        "dimension_scores": {"physical_exam": 0},
        "rubric_scores": {
            "pe_tenderness": {"description": "检查压痛", "score": 0, "max_score": 3},
            "pe_rebound": {"description": "检查反跳痛", "score": 0, "max_score": 4},
        },
        "dimension_traces": {
            "physical_exam": [
                {
                    "rubric_item_id": "pe_tenderness",
                    "score": 0,
                    "max_score": 3,
                    "gap_type": "physical_exam_missing",
                },
                {
                    "rubric_item_id": "pe_rebound",
                    "score": 0,
                    "max_score": 4,
                    "gap_type": "physical_exam_missing",
                },
            ]
        },
    }

    analysis = build_deep_report_analysis(report=report, case=case)

    missed_items = analysis["clinical_task_analysis"]["physical_exam"]["missed_items"]
    assert [item["item_id"] for item in missed_items[:2]] == ["pe_tenderness", "pe_rebound"]
    assert [item["label"] for item in missed_items[:2]] == ["检查压痛", "检查反跳痛"]
    assert all(item["label"] != "未命名评分项" for item in missed_items)


def test_deep_report_analysis_builds_humanistic_review_and_next_training_plan() -> None:
    case = _load_case()
    report = _base_report("急性阑尾炎", "转移性右下腹痛支持阑尾炎。") | {
        "total_score": 64,
        "max_score": 100,
        "score_groups": {
            "clinical_osce": {"score": 54, "max_score": 70},
            "humanistic_communication": {"score": 10, "max_score": 30},
        },
        "dimension_scores": {
            "narrative_medicine": 3,
            "communication_skill": 2,
            "medical_ethics": 1,
            "relationship_building": 0,
        },
        "dimension_traces": {
            "narrative_medicine": [
                {
                    "item_id": "nm_patient_concern",
                    "label": "询问患者担忧",
                    "score": 3,
                    "max_score": 3,
                    "stage": "history_taking",
                    "matched_evidence": ["你现在最担心的是什么？"],
                    "match_method": "embedding_anchor",
                }
            ],
            "medical_ethics": [
                {
                    "item_id": "eth_exam_consent",
                    "label": "查体前说明目的并征得同意",
                    "score": 1,
                    "max_score": 3,
                    "stage": "physical_exam",
                    "gap_type": "ethics_consent_missing",
                    "matched_evidence": ["刚才查腹部是为了判断压痛，可以吗？"],
                    "timing_status": "late",
                    "next_training_action": "下一轮查体或检查前先说明目的、可能不适并征得同意。",
                }
            ],
        },
        "missed_opportunities": [
            {
                "opportunity_id": "relationship_empathy_missing:1",
                "gap_type": "relationship_empathy_missing",
                "stage": "history_taking",
                "trigger_evidence": "我很担心是不是严重的病。",
                "expected_response": "患者表达担忧后，应先回应情绪，再继续医学问诊。",
                "next_training_action": "下一轮患者表达焦虑或担忧后，先用一句话承认情绪并说明会一起处理。",
            }
        ],
        "training_gaps": [
            {
                "dimension_id": "medical_ethics",
                "rubric_item_id": "eth_exam_consent",
                "gap_type": "ethics_consent_missing",
                "label": "查体或检查前说明目的并征得同意",
                "missing_score": 2,
                "severity": "high",
                "stage": "physical_exam",
                "trigger_stage": "physical_exam",
                "next_training_action": "下一轮查体或检查前先说明目的、可能不适并征得同意。",
                "skill_type": "ethics_consent",
                "gap_source": "score_trace",
            },
            {
                "dimension_id": "relationship_building",
                "rubric_item_id": "rel_empathy_response",
                "gap_type": "relationship_empathy_missing",
                "label": "患者表达担忧后缺少共情回应",
                "missing_score": 2,
                "severity": "high",
                "stage": "history_taking",
                "trigger_stage": "history_taking",
                "next_training_action": "下一轮患者表达焦虑或担忧后，先用一句话承认情绪并说明会一起处理。",
                "skill_type": "relationship_repair",
                "gap_source": "missed_opportunity",
            },
        ],
    }

    analysis = build_deep_report_analysis(report=report, case=case)

    humanistic = analysis["humanistic_communication_analysis"]
    assert humanistic["dimension_scores"][0] == {
        "dimension_id": "narrative_medicine",
        "label": "叙事医学",
        "score": 3,
        "max_score": 8,
        "completion_level": "weak",
    }
    assert humanistic["matched_evidence"][0]["matched_evidence"] == ["你现在最担心的是什么？"]
    assert humanistic["missed_opportunities"][0]["gap_type"] == "relationship_empathy_missing"
    assert any("先用一句话承认情绪" in action for action in humanistic["relationship_repair_actions"])

    plan = analysis["next_training_plan"]
    assert plan["top_goals"][0]["gap_type"] == "relationship_empathy_missing"
    assert plan["top_goals"][0]["priority"] > plan["top_goals"][1]["priority"]
    assert plan["stage_triggered_actions"][0]["stage"] == "history_taking"
    assert "患者表达焦虑或担忧" in plan["stage_triggered_actions"][0]["trigger"]
    assert "完成标志" in plan["success_signals"][0]
    assert {gap["gap_type"] for gap in plan["linked_training_gaps"]} == {
        "relationship_empathy_missing",
        "ethics_consent_missing",
    }
