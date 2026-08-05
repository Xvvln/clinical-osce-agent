from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.services.deep_report_analysis_service import build_deep_report_analysis
from app.services.personal_training_skill_service import build_teacher_reflection_review_payload
from app.services.student_training_report_service import build_student_training_report
from app.services.teacher_agent import DeterministicTeacherAgent
from app.validators.case_validator import validate_case


ROOT_DIR = Path(__file__).resolve().parents[3]
INTERNAL_TOKEN_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
UUID_PATTERN = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.IGNORECASE)


def _load_case():
    return validate_case(
        json.loads(
            (ROOT_DIR / "data" / "cases" / "appendicitis_001.json").read_text(
                encoding="utf-8"
            )
        )
    )


def _base_report(*, diagnosis: str = "急性阑尾炎", score: int = 83) -> dict[str, Any]:
    return {
        "case_id": "appendicitis_001",
        "total_score": score,
        "max_score": 100,
        "score_groups": {
            "clinical_osce": {"score": min(score, 70), "max_score": 70},
            "humanistic_communication": {"score": max(score - 70, 0), "max_score": 30},
        },
        "dimension_scores": {
            "history_taking": 14,
            "physical_exam": 3,
            "auxiliary_test": 4,
            "main_diagnosis": 10 if diagnosis == "急性阑尾炎" else 0,
            "differential_diagnosis": 3,
            "reasoning": 5,
        },
        "rubric_scores": {
            "ht_migration": {
                "description": "追问疼痛转移",
                "dimension_id": "history_taking",
                "score": 4,
                "max_score": 4,
            },
            "pe_temperature": {
                "description": "检查体温",
                "dimension_id": "physical_exam",
                "score": 0,
                "max_score": 3,
            },
            "rs_exclusion": {
                "description": "表达鉴别诊断排除依据",
                "dimension_id": "reasoning",
                "score": 0,
                "max_score": 4,
            },
        },
        "dimension_traces": {
            "history_taking": [
                {
                    "item_id": "ht_migration",
                    "label": "追问疼痛转移",
                    "score": 4,
                    "max_score": 4,
                    "stage": "history_taking",
                    "matched_evidence": ["患者说明疼痛从上腹逐渐转移到右下腹。"],
                }
            ],
            "physical_exam": [
                {
                    "item_id": "pe_temperature",
                    "label": "检查体温",
                    "score": 0,
                    "max_score": 3,
                    "stage": "physical_exam",
                    "gap_type": "physical_exam_missing",
                    "next_training_action": "下一轮在形成感染性假设后主动检查体温。",
                }
            ],
            "reasoning": [
                {
                    "item_id": "rs_exclusion",
                    "label": "表达鉴别诊断排除依据",
                    "score": 0,
                    "max_score": 4,
                    "stage": "diagnosis_submission",
                    "gap_type": "reasoning_exclusion_missing",
                    "next_training_action": "提交诊断前写出至少一个相近诊断及其排除依据。",
                }
            ],
        },
        "missed_items": ["pe_temperature", "rs_exclusion"],
        "training_gaps": [
            {
                "dimension_id": "physical_exam",
                "rubric_item_id": "pe_temperature",
                "gap_type": "physical_exam_missing",
                "label": "检查体温",
                "missing_score": 3,
                "severity": "medium",
                "stage": "physical_exam",
                "trigger": "形成感染性疾病假设后",
                "evidence_summary": "评分轨迹没有找到体温检查记录。",
                "next_training_action": "下一轮在形成感染性假设后主动检查体温。",
                "skill_type": "evidence_collection",
                "gap_source": "rubric_trace",
            },
            {
                "dimension_id": "reasoning",
                "rubric_item_id": "rs_exclusion",
                "gap_type": "reasoning_exclusion_missing",
                "label": "表达鉴别诊断排除依据",
                "missing_score": 4,
                "severity": "high",
                "stage": "diagnosis_submission",
                "trigger": "准备提交诊断时",
                "evidence_summary": "提交内容列出了相近诊断，但没有给出明确排除依据。",
                "next_training_action": "提交诊断前写出至少一个相近诊断及其排除依据。",
                "skill_type": "clinical_reasoning",
                "gap_source": "rubric_trace",
            },
        ],
        "missed_opportunities": [],
        "strengths": ["追问疼痛转移：已完成。"],
        "reasoning_errors": ["鉴别诊断缺少排除依据。"],
        "next_recommendations": ["提交诊断前补充相近诊断的排除依据。"],
        "final_submission": {
            "diagnosis": diagnosis,
            "reasoning": "转移性右下腹痛支持当前判断，并考虑胃肠炎和泌尿系结石。",
        },
        "evidence_graph_summary": {
            "covered_evidence_nodes": [
                {
                    "node_id": "ev_migratory_rlq_pain",
                    "source_id": "appendicitis_001.hf_02",
                    "label": "转移并固定右下腹痛",
                }
            ],
            "missing_evidence_nodes": [
                {
                    "node_id": "ev_temperature",
                    "source_id": "vital.temperature",
                    "label": "体温信息",
                }
            ],
        },
        "clinical_reasoning_trace": {
            "cognitive_patterns": [
                {
                    "pattern_id": "thin_differential_reasoning",
                    "label": "鉴别诊断排除依据不足",
                    "severity": "high",
                }
            ],
            "sequence_flags": [],
        },
    }


def _complete_report(
    report: dict[str, Any],
    *,
    longitudinal_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case = _load_case()
    completed = deepcopy(report)
    completed["deep_report_analysis"] = build_deep_report_analysis(
        report=completed,
        case=case,
    )
    completed["ai_reflection_review"] = build_teacher_reflection_review_payload(
        completed,
        case,
        teacher_agent=DeterministicTeacherAgent(),
        teacher_longitudinal_context=longitudinal_context or {},
    )
    completed["personal_skill_candidate"] = {
        "status": "approved",
        "title": "提交前补齐鉴别诊断排除依据",
    }
    return completed


def _assert_student_text_is_clean(student_report: dict[str, Any]) -> None:
    visible_values = [
        student_report["outcome"][field]
        for field in (
            "summary",
            "score_summary",
            "diagnosis_summary",
            "safety_summary",
            "communication_summary",
        )
    ]
    for replay in student_report["decision_replays"]:
        visible_values.extend(
            replay[field]
            for field in (
                "phase",
                "title",
                "observed_evidence",
                "teacher_judgement",
                "why_it_matters",
                "next_action",
            )
        )
        visible_values.extend(replay["evidence_labels"])
    for goal in student_report["training_prescriptions"]:
        visible_values.extend(
            goal[field] for field in ("title", "trigger", "action", "success_signal")
        )
    visible_values.extend(
        [
            student_report["longitudinal_summary"]["label"],
            student_report["longitudinal_summary"]["summary"],
            student_report["personal_memory_summary"],
        ]
    )
    assert all(value.strip() for value in visible_values)
    assert not any(UUID_PATTERN.search(value) for value in visible_values)
    assert not any(INTERNAL_TOKEN_PATTERN.search(value) for value in visible_values)


def test_real_scenario_correct_diagnosis_with_weak_evidence_gets_actionable_report() -> None:
    student_report = build_student_training_report(
        _complete_report(_base_report())
    )

    assert student_report["outcome"]["diagnosis_status"] == "correct"
    assert len(student_report["decision_replays"]) == 3
    assert student_report["decision_replays"][0]["kind"] == "strength"
    assert any(item["kind"] == "reasoning" for item in student_report["decision_replays"])
    assert 1 <= len(student_report["training_prescriptions"]) <= 3
    assert all(item["trigger"] and item["success_signal"] for item in student_report["training_prescriptions"])
    _assert_student_text_is_clean(student_report)


def test_real_scenario_plausible_wrong_diagnosis_keeps_differential_context() -> None:
    student_report = build_student_training_report(
        _complete_report(_base_report(diagnosis="急性胃肠炎", score=61))
    )

    assert student_report["outcome"]["diagnosis_status"] == "plausible_differential"
    assert "合理鉴别诊断" in student_report["outcome"]["diagnosis_summary"]
    assert "病例目标" in student_report["outcome"]["diagnosis_summary"]
    _assert_student_text_is_clean(student_report)


def test_real_scenario_safety_order_violation_is_prioritized() -> None:
    report = _base_report(score=58)
    report["missed_opportunities"] = [
        {
            "opportunity_id": "ethics_consent_missing:1",
            "gap_type": "ethics_consent_missing",
            "stage": "physical_exam",
            "trigger_evidence": "学生直接申请腹部查体，没有先说明目的并征得同意。",
            "expected_response": "查体前应说明目的、可能不适并征得患者同意。",
            "next_training_action": "下一轮每次查体前先说明目的和可能不适，获得同意后再操作。",
        }
    ]
    student_report = build_student_training_report(_complete_report(report))

    assert "知情同意" in student_report["outcome"]["safety_summary"]
    assert any(item["kind"] == "safety" for item in student_report["decision_replays"])
    _assert_student_text_is_clean(student_report)


def test_real_scenario_missed_empathy_opportunity_becomes_observable_action() -> None:
    report = _base_report(score=67)
    report["missed_opportunities"] = [
        {
            "opportunity_id": "relationship_empathy_missing:1",
            "gap_type": "relationship_empathy_missing",
            "stage": "history_taking",
            "trigger_evidence": "患者说自己很担心是不是严重疾病，学生立即继续追问疼痛。",
            "expected_response": "患者表达担忧后，应先回应情绪，再继续医学问诊。",
            "next_training_action": "下一轮患者表达焦虑后，先承认担忧并说明会一起处理。",
        }
    ]
    student_report = build_student_training_report(_complete_report(report))

    humanistic = next(item for item in student_report["decision_replays"] if item["kind"] == "humanistic")
    assert "担心" in humanistic["observed_evidence"]
    assert "先承认担忧" in humanistic["next_action"]
    _assert_student_text_is_clean(student_report)


def test_real_scenario_high_performer_does_not_receive_fabricated_weakness() -> None:
    report = _base_report(score=96)
    report["missed_items"] = []
    report["training_gaps"] = []
    report["reasoning_errors"] = []
    report["missed_opportunities"] = []
    report["clinical_reasoning_trace"] = {"cognitive_patterns": [], "sequence_flags": []}
    report["evidence_graph_summary"]["missing_evidence_nodes"] = []
    for rubric_score in report["rubric_scores"].values():
        rubric_score["score"] = rubric_score["max_score"]
    for traces in report["dimension_traces"].values():
        for item in traces:
            item["score"] = item["max_score"]
            item.pop("gap_type", None)
            item.pop("next_training_action", None)
    student_report = build_student_training_report(_complete_report(report))

    assert student_report["decision_replays"]
    assert all(item["kind"] == "strength" for item in student_report["decision_replays"])
    assert student_report["training_prescriptions"][0]["title"] == "迁移本轮有效做法"
    assert "明显安全或沟通问题" in student_report["training_prescriptions"][0]["success_signal"]
    _assert_student_text_is_clean(student_report)


def test_real_scenario_repeated_and_reactivated_gaps_use_longitudinal_language() -> None:
    longitudinal_context = {
        "gap_status_counts": {
            "first_seen_current_window": 1,
            "repeated": 2,
            "reactivated_after_improvement": 1,
            "recovered_since_previous_report": 1,
        }
    }
    completed = _complete_report(
        _base_report(score=72),
        longitudinal_context=longitudinal_context,
    )
    completed["ai_reflection_review"]["teacher_analysis_context"]["clinical_thinking_profile"] = {
        "problem_representation": "strong",
        "hypothesis_management": "delayed_and_undifferentiated",
        "verification_strategy": "evidence_collection_without_target",
        "differential_reasoning": "narrow_and_exclusion_absent",
        "metacognitive_next_move": "explicit_hypothesis_before_physical_exam",
        "longitudinal_gap_assessment": "1 个问题改善后再次出现，2 个问题连续出现。",
    }
    student_report = build_student_training_report(completed)

    longitudinal = student_report["longitudinal_summary"]
    assert longitudinal["status"] == "reactivated"
    assert longitudinal["repeated_count"] == 2
    assert longitudinal["reactivated_count"] == 1
    assert "改善后再次出现" in longitudinal["summary"]
    assert "delayed_and_undifferentiated" not in json.dumps(student_report, ensure_ascii=False)
    _assert_student_text_is_clean(student_report)
