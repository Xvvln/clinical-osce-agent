from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.services.personal_training_skill_service import PersonalTrainingSkillService, build_teacher_reflection_review_payload
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_store import TrainingSkillStore
from app.validators.case_validator import validate_case


ROOT_DIR = Path(__file__).resolve().parents[3]


def _load_case(case_id: str = "appendicitis_001"):
    return validate_case(json.loads((ROOT_DIR / "data" / "cases" / f"{case_id}.json").read_text(encoding="utf-8")))


class CapturingGenerator:
    def __init__(self) -> None:
        self.contexts: list[Any] = []

    def generate_candidate(self, context: Any) -> dict[str, Any]:
        self.contexts.append(context)
        return {
            "title": "个人复盘训练 Skill",
            "description": "围绕本轮暴露出的临床思维模式训练。",
            "suggested_strategy": "下一轮先建立问题表征，再决定查体和检查顺序。",
            "status": "draft",
        }


class ApprovingAgent:
    def review_candidate(self, candidate: dict[str, Any], *, protected_terms: list[str]) -> dict[str, Any]:
        return {
            **candidate,
            "approval_agent_review": {
                "revision_status": "unchanged",
                "changed_fields": [],
                "protected_terms_checked": len(protected_terms),
            },
        }


class PassingGate:
    def review_candidate(self, candidate: dict[str, Any], batch_result: Any) -> dict[str, Any]:
        return {
            "status": "ready_for_review",
            "regression_passed": True,
            "blocking_failures": [],
            "candidate_safety_violations": [],
            "candidate_context_violations": [],
        }


def test_personal_skill_uses_reasoning_trace_patterns_for_candidate_and_reflection(tmp_path) -> None:
    case = _load_case()
    generator = CapturingGenerator()
    service = PersonalTrainingSkillService(
        generator=generator,
        approval_agent=ApprovingAgent(),
        regression_gate=PassingGate(),
    )
    session = SimpleNamespace(
        session_id="personal-trace-session",
        case_id=case.case_id,
        student_id="student-a",
    )
    report = {
        "report_id": "personal-trace-session_report",
        "case_id": case.case_id,
        "total_score": 18,
        "max_score": 40,
        "missed_items": ["ht_migration", "ht_character", "dxd_urolith"],
        "clinical_reasoning_trace": {
            "trace_version": "clinical_reasoning_trace_v1",
            "cognitive_patterns": [
                {
                    "pattern_id": "weak_problem_representation",
                    "label": "问题表征薄弱",
                    "category": "problem_representation",
                    "severity": "high",
                    "evidence": "病史只覆盖起病时间，未形成疼痛演变时间线。",
                    "why_it_matters": "问题表征薄弱会导致后续查体和检查缺少明确假设。",
                    "remediation": "下一轮先补齐起病、部位、性质、程度和伴随症状。",
                    "source_signal_ids": ["ht_migration", "ht_character"],
                }
            ],
        },
        "training_progress_snapshot": {"coverage_map": {}},
        "source_reference_items": [],
    }

    payload = service.generate_for_completed_session(
        session=session,
        case=case,
        report=report,
        candidate_store=TrainingSkillCandidateStore(tmp_path / "candidates.sqlite3"),
        skill_store=TrainingSkillStore(tmp_path / "skills.sqlite3"),
        event_store=TrainingEventStore(tmp_path / "events.sqlite3"),
    )

    assert generator.contexts
    assert generator.contexts[0].turn_patterns[0].pattern_id == "weak_problem_representation"
    candidate = payload["personal_skill_candidate"]
    assert candidate["reasoning_pattern_ids"] == ["weak_problem_representation"]
    assert candidate["source_trace_version"] == "clinical_reasoning_trace_v1"

    reflection = payload["ai_reflection_review"]
    assert reflection["teaching_prompt_version"] == "teacher_reflection_v3"
    assert reflection["major_issues"][0]["title"] == "问题表征薄弱"
    assert reflection["reasoning_trace_summary"]["dominant_patterns"][0]["pattern_id"] == "weak_problem_representation"


def test_teacher_reflection_uses_sequence_flags_and_evidence_chain_breakpoints() -> None:
    case = _load_case()
    report = {
        "report_id": "trace-breakpoint-report",
        "case_id": case.case_id,
        "total_score": 18,
        "max_score": 40,
        "missed_items": ["ht_migration", "pe_tenderness", "rs_exclude"],
        "clinical_reasoning_trace": {
            "trace_version": "clinical_reasoning_trace_v1",
            "cognitive_patterns": [
                {
                    "pattern_id": "premature_testing_before_exam",
                    "label": "检查顺序前置",
                    "category": "hypothesis_testing",
                    "severity": "medium",
                    "evidence": "第 2 轮已申请血常规，第 3 轮才补做右下腹压痛。",
                    "why_it_matters": "没有先用查体确认局部体征，辅助检查就缺少明确验证目标。",
                    "remediation": "先用病史和查体形成假设，再申请检查验证或排除。",
                    "source_signal_ids": ["sequence:auxiliary_before_physical_exam"],
                }
            ],
            "action_order_summary": {
                "first_history_turn_index": 1,
                "first_auxiliary_test_turn_index": 2,
                "first_physical_exam_turn_index": 3,
                "diagnosis_submission_turn_index": 4,
            },
            "hypothesis_testing": {
                "sequence_flags": [
                    {
                        "flag_id": "premature_testing_before_exam",
                        "label": "辅助检查早于关键查体",
                        "severity": "medium",
                        "evidence": "第 2 轮已申请血常规，第 3 轮才补做右下腹压痛。",
                    }
                ]
            },
            "evidence_chain_breakpoints": [
                {
                    "breakpoint_id": "rp_migration_support",
                    "statement": "迁移痛推理点",
                    "kind": "support",
                    "status": "broken",
                    "missing_evidence": ["appendicitis_001.hf_02"],
                    "missing_evidence_labels": ["追问疼痛部位及转移特征"],
                    "teacher_action": "先补齐疼痛部位和转移过程，再决定查体与检查。",
                }
            ],
        },
        "training_progress_snapshot": {"coverage_map": {}},
        "source_reference_items": [],
    }

    reflection = build_teacher_reflection_review_payload(report, case)
    trace_summary = reflection["reasoning_trace_summary"]

    assert trace_summary["sequence_flags"][0]["flag_id"] == "premature_testing_before_exam"
    assert trace_summary["action_order_summary"]["first_auxiliary_test_turn_index"] == 2
    assert trace_summary["evidence_chain_breakpoints"][0]["statement"] == "迁移痛推理点"
    assert trace_summary["evidence_chain_breakpoints"][0]["missing_evidence_labels"] == ["追问疼痛部位及转移特征"]
    assert "迁移痛推理点" in reflection["reasoning_chain_review"]
    assert "追问疼痛部位及转移特征" in reflection["reasoning_chain_review"]


def test_personal_skill_candidate_context_includes_evidence_chain_breakpoint_pattern(tmp_path) -> None:
    case = _load_case()
    generator = CapturingGenerator()
    service = PersonalTrainingSkillService(
        generator=generator,
        approval_agent=ApprovingAgent(),
        regression_gate=PassingGate(),
    )
    session = SimpleNamespace(
        session_id="personal-breakpoint-session",
        case_id=case.case_id,
        student_id="student-a",
    )
    report = {
        "report_id": "personal-breakpoint-report",
        "case_id": case.case_id,
        "total_score": 18,
        "max_score": 40,
        "missed_items": ["ht_migration", "pe_tenderness", "rs_exclude"],
        "clinical_reasoning_trace": {
            "trace_version": "clinical_reasoning_trace_v1",
            "cognitive_patterns": [],
            "evidence_chain_breakpoints": [
                {
                    "breakpoint_id": "rp_migration_support",
                    "statement": "迁移痛推理点",
                    "kind": "support",
                    "status": "broken",
                    "missing_evidence": ["appendicitis_001.hf_02"],
                    "missing_evidence_labels": ["追问疼痛部位及转移特征"],
                    "teacher_action": "先补齐疼痛部位和转移过程，再决定查体与检查。",
                }
            ],
        },
        "training_progress_snapshot": {"coverage_map": {}},
        "source_reference_items": [],
    }

    payload = service.generate_for_completed_session(
        session=session,
        case=case,
        report=report,
        candidate_store=TrainingSkillCandidateStore(tmp_path / "candidates.sqlite3"),
        skill_store=TrainingSkillStore(tmp_path / "skills.sqlite3"),
        event_store=TrainingEventStore(tmp_path / "events.sqlite3"),
    )

    context = generator.contexts[0]
    assert context.turn_patterns[0].pattern_type == "evidence_chain_breakpoint"
    assert context.turn_patterns[0].title == "迁移痛推理点"
    assert context.turn_patterns[0].trigger_item_ids == ["ht_migration", "pe_tenderness", "rs_exclude"]
    assert payload["personal_skill_candidate"]["reasoning_pattern_ids"] == ["evidence_chain_rp_migration_support"]
