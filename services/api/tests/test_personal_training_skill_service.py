from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import personal_training_skill_service as personal_skill_module
from app.services.personal_training_skill_service import PersonalTrainingSkillService, build_teacher_reflection_review_payload
from app.services.teacher_agent import DeterministicTeacherAgent
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_candidate_service import TrainingSkillCandidateGenerationError
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_store import TrainingSkillStore
from app.validators.case_validator import validate_case


ROOT_DIR = Path(__file__).resolve().parents[3]


def _load_case(case_id: str = "appendicitis_001"):
    return validate_case(json.loads((ROOT_DIR / "data" / "cases" / f"{case_id}.json").read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("case_id", "missed_items", "expected_actions"),
    [
        (
            "appendicitis_001",
            ["ht_migration", "pe_tenderness", "ax_us"],
            ["追问疼痛部位及转移特征", "检查腹部压痛", "申请腹部超声"],
        ),
        (
            "acs_001",
            ["ht_onset", "pe_blood_pressure", "at_ecg"],
            ["追问胸痛起病时间与诱因", "检查血压", "申请心电图"],
        ),
        (
            "heart_failure_001",
            ["ht_progression", "pe_rales", "at_bnp"],
            ["追问气短进展情况", "检查肺部湿啰音", "申请 BNP 检查"],
        ),
        (
            "hyperthyroid_001",
            ["ht_hypermetabolic", "pe_goiter", "at_tsh"],
            ["追问怕热多汗与多食消瘦", "检查甲状腺肿大", "申请 TSH 检查"],
        ),
        (
            "pneumonia_001",
            ["ht_sputum", "pe_crackle", "at_chest_xray"],
            ["追问痰液性质", "检查肺部湿啰音", "申请胸部 X 线"],
        ),
    ],
)
def test_teacher_fallback_actions_use_each_case_rubric_labels(
    case_id: str,
    missed_items: list[str],
    expected_actions: list[str],
) -> None:
    case = _load_case(case_id)
    report = {
        "report_id": f"{case_id}-semantic-regression_report",
        "case_id": case_id,
        "total_score": 0,
        "max_score": 100,
        "missed_items": missed_items,
        "training_progress_snapshot": {"coverage_map": {}},
        "source_reference_items": [],
    }

    reflection = build_teacher_reflection_review_payload(report, case)

    reflection_text = json.dumps(reflection, ensure_ascii=False)
    for expected_action in expected_actions:
        assert expected_action in reflection_text
    if case_id != "appendicitis_001":
        for irrelevant_phrase in [
            "腹痛六问",
            "急腹症",
            "部位变化",
            "恶心呕吐发热腹泻尿痛",
            "腹膜刺激征",
        ]:
            assert irrelevant_phrase not in reflection_text


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


class FailingGenerator:
    def generate_candidate(self, context: Any) -> dict[str, Any]:
        raise TrainingSkillCandidateGenerationError("configured provider unavailable")


class FailingTeacherAgent:
    def __call__(self, request: Any) -> dict[str, Any]:
        raise RuntimeError("teacher reflection should be reused from the saved candidate")


class FakeTeacherAgent:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def __call__(self, request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {
            "agent_id": "teacher_agent",
            "analysis_mode": "post_session_teacher_analysis",
            "analysis_summary": "学生没有把疼痛迁移、关键查体和鉴别排除连成验证链。",
            "overall_comment": "这次训练的问题不是单个漏项，而是假设形成后缺少验证路径。",
            "major_issues": [
                {
                    "title": "假设验证链断裂",
                    "observed_behavior": "学生较早提出诊断方向，但没有先补齐迁移痛和局部腹膜刺激征。",
                    "why_it_matters": "没有验证链，诊断表达会像结论先行。",
                    "correct_approach": "先建立疼痛演变时间线，再用查体和检查验证或排除。",
                    "next_action": "下一轮每申请一个查体或检查前，先说它要验证什么。",
                    "linked_items": ["追问疼痛部位及转移特征", "检查腹部压痛"],
                }
            ],
            "teacher_coaching_review": [
                {
                    "section_id": "case_framing",
                    "title": "病例表征",
                    "teacher_comment": "先把主诉压缩成有时间线和部位变化的临床问题。",
                    "why_it_matters": "病例表征决定后续验证路径。",
                    "next_move": "下一轮先说清起病、部位变化和伴随症状。",
                    "evidence_labels": ["追问疼痛部位及转移特征"],
                }
            ],
            "reasoning_chain_review": "推理链断在假设形成后的验证步骤。",
            "next_practice_plan": ["下一轮先补病史时间线，再进入查体。"],
            "teacher_note": "这是 TeacherAgent 基于本轮材料生成的教学分析。",
            "student_thinking_hypothesis": "学生过早进入结论，尚未把病史、查体和排除依据组织成验证链。",
            "clinical_thinking_profile": {
                "problem_representation": "主诉和疼痛演变尚未压缩成稳定问题表征。",
                "hypothesis_management": "诊断假设形成偏早，验证动作不足。",
                "verification_strategy": "查体和检查没有围绕假设形成支持与排除证据。",
                "next_teacher_move": "用反问要求学生先说明下一步证据要验证什么。",
            },
            "skill_memory_focus": {
                "problem_pattern_summary": "假设形成后缺少验证路径",
                "recommended_intervention": "Coach 后续用反问提醒学生说明下一步验证目的。",
            },
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


class FailingOnceSkillStore:
    def __init__(self, delegate: TrainingSkillStore) -> None:
        self.delegate = delegate
        self.remaining_failures = 1

    def enable_candidate(self, candidate: dict[str, Any]) -> bool:
        if self.remaining_failures:
            self.remaining_failures -= 1
            raise RuntimeError("injected skill persistence failure")
        return self.delegate.enable_candidate(candidate)

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        return self.delegate.get_skill(skill_id)


class FailAfterPersistingEventStore:
    def __init__(self, delegate: TrainingEventStore, *, fail_on_call: int) -> None:
        self.delegate = delegate
        self.fail_on_call = fail_on_call
        self.call_count = 0
        self.failed = False

    def append_event(self, **kwargs: Any) -> bool:
        inserted = self.delegate.append_event(**kwargs)
        self.call_count += 1
        if not self.failed and self.call_count == self.fail_on_call:
            self.failed = True
            raise RuntimeError("injected crash after event persistence")
        return inserted


def _recovery_scenario(session_id: str) -> tuple[Any, Any, dict[str, Any], CapturingGenerator, PersonalTrainingSkillService]:
    case = _load_case()
    session = SimpleNamespace(
        session_id=session_id,
        case_id=case.case_id,
        student_id="student-recovery",
    )
    report = {
        "report_id": f"{session_id}_report",
        "case_id": case.case_id,
        "total_score": 18,
        "max_score": 40,
        "missed_items": ["ht_migration"],
        "training_progress_snapshot": {"coverage_map": {}},
        "source_reference_items": [],
    }
    generator = CapturingGenerator()
    service = PersonalTrainingSkillService(
        generator=generator,
        approval_agent=ApprovingAgent(),
        regression_gate=PassingGate(),
        teacher_agent=FakeTeacherAgent(),
    )
    return case, session, report, generator, service


def _call_personal_skill_generation(
    service: PersonalTrainingSkillService,
    *,
    case: Any,
    session: Any,
    report: dict[str, Any],
    candidate_store: TrainingSkillCandidateStore,
    skill_store: Any,
    event_store: Any,
) -> dict[str, Any]:
    return service.generate_for_completed_session(
        session=session,
        case=case,
        report=report,
        candidate_store=candidate_store,
        skill_store=skill_store,
        event_store=event_store,
    )


def _personal_skill_events(
    event_store: TrainingEventStore,
    *,
    session_id: str,
    candidate_id: str,
) -> list[dict[str, Any]]:
    return [
        *event_store.list_session_events(session_id),
        *event_store.list_session_events(candidate_id),
    ]


def test_personal_skill_default_generator_is_resolved_when_generating(tmp_path, monkeypatch) -> None:
    case = _load_case()
    late_generator = CapturingGenerator()
    service = PersonalTrainingSkillService(
        approval_agent=ApprovingAgent(),
        regression_gate=PassingGate(),
    )
    monkeypatch.setattr(
        personal_skill_module,
        "create_default_training_skill_candidate_generator",
        lambda: late_generator,
    )
    session = SimpleNamespace(
        session_id="personal-late-generator-session",
        case_id=case.case_id,
        student_id="student-a",
    )
    report = {
        "report_id": "personal-late-generator-report",
        "case_id": case.case_id,
        "total_score": 18,
        "max_score": 40,
        "missed_items": ["ht_migration"],
        "training_progress_snapshot": {"coverage_map": {}},
        "source_reference_items": [],
    }

    service.generate_for_completed_session(
        session=session,
        case=case,
        report=report,
        candidate_store=TrainingSkillCandidateStore(tmp_path / "candidates.sqlite3"),
        skill_store=TrainingSkillStore(tmp_path / "skills.sqlite3"),
        event_store=TrainingEventStore(tmp_path / "events.sqlite3"),
    )

    assert late_generator.contexts


def test_personal_skill_retry_enables_saved_approved_candidate_after_skill_failure(tmp_path) -> None:
    case, session, report, generator, service = _recovery_scenario("personal-skill-retry-session")
    candidate_store = TrainingSkillCandidateStore(tmp_path / "candidates.sqlite3")
    durable_skill_store = TrainingSkillStore(tmp_path / "skills.sqlite3")
    failing_skill_store = FailingOnceSkillStore(durable_skill_store)
    event_store = TrainingEventStore(tmp_path / "events.sqlite3")
    candidate_id = f"personal_skill_candidate_{session.session_id}"
    skill_id = f"skill_personal_{session.session_id}"

    try:
        _call_personal_skill_generation(
            service,
            case=case,
            session=session,
            report=report,
            candidate_store=candidate_store,
            skill_store=failing_skill_store,
            event_store=event_store,
        )
    except RuntimeError as exc:
        assert str(exc) == "injected skill persistence failure"
    else:
        raise AssertionError("首次技能持久化故障应向调用方报告失败")

    assert candidate_store.get_candidate(candidate_id) is not None
    assert durable_skill_store.get_skill(skill_id) is None
    assert _personal_skill_events(
        event_store,
        session_id=session.session_id,
        candidate_id=candidate_id,
    ) == []

    service._teacher_agent = FailingTeacherAgent()
    payload = _call_personal_skill_generation(
        service,
        case=case,
        session=session,
        report=report,
        candidate_store=candidate_store,
        skill_store=failing_skill_store,
        event_store=event_store,
    )

    assert len(generator.contexts) == 1
    assert payload["personal_skill_candidate"]["status"] == "approved"
    assert payload["personal_skill_candidate"]["skill_id"] == skill_id
    enabled_skill = durable_skill_store.get_skill(skill_id)
    assert enabled_skill is not None
    assert enabled_skill["source_candidate_id"] == candidate_id


def test_personal_skill_retry_completes_partial_events_exactly_once(tmp_path) -> None:
    case, session, report, generator, service = _recovery_scenario("personal-event-retry-session")
    candidate_store = TrainingSkillCandidateStore(tmp_path / "candidates.sqlite3")
    skill_store = TrainingSkillStore(tmp_path / "skills.sqlite3")
    durable_event_store = TrainingEventStore(tmp_path / "events.sqlite3")
    failing_event_store = FailAfterPersistingEventStore(durable_event_store, fail_on_call=2)
    candidate_id = f"personal_skill_candidate_{session.session_id}"

    try:
        _call_personal_skill_generation(
            service,
            case=case,
            session=session,
            report=report,
            candidate_store=candidate_store,
            skill_store=skill_store,
            event_store=failing_event_store,
        )
    except RuntimeError as exc:
        assert str(exc) == "injected crash after event persistence"
    else:
        raise AssertionError("事件写入后的注入故障应中断首次生成")

    partial_events = _personal_skill_events(
        durable_event_store,
        session_id=session.session_id,
        candidate_id=candidate_id,
    )
    assert [event["event_type"] for event in partial_events] == [
        "personal_training_skill_generated",
        "personal_skill_candidate_generated",
    ]

    payload = _call_personal_skill_generation(
        service,
        case=case,
        session=session,
        report=report,
        candidate_store=candidate_store,
        skill_store=skill_store,
        event_store=failing_event_store,
    )

    assert len(generator.contexts) == 1
    assert payload["personal_skill_candidate"]["status"] == "approved"
    events = _personal_skill_events(
        durable_event_store,
        session_id=session.session_id,
        candidate_id=candidate_id,
    )
    assert [event["event_type"] for event in events] == [
        "personal_training_skill_generated",
        "personal_skill_candidate_generated",
        "personal_skill_candidate_agent_reviewed",
        "personal_skill_candidate_auto_enabled",
    ]
    assert len({event["event_key"] for event in events}) == 4
    assert len({event["payload"]["review_revision"] for event in events}) == 1
    for event in events:
        assert event["event_key"] == (
            f"personal-skill:{candidate_id}:{event['event_type']}:"
            f"{event['payload']['review_revision']}"
        )


def test_personal_skill_retry_of_complete_candidate_does_not_duplicate_events(tmp_path) -> None:
    case, session, report, generator, service = _recovery_scenario("personal-complete-retry-session")
    candidate_store = TrainingSkillCandidateStore(tmp_path / "candidates.sqlite3")
    skill_store = TrainingSkillStore(tmp_path / "skills.sqlite3")
    event_store = TrainingEventStore(tmp_path / "events.sqlite3")
    candidate_id = f"personal_skill_candidate_{session.session_id}"

    first_payload = _call_personal_skill_generation(
        service,
        case=case,
        session=session,
        report=report,
        candidate_store=candidate_store,
        skill_store=skill_store,
        event_store=event_store,
    )
    second_payload = _call_personal_skill_generation(
        service,
        case=case,
        session=session,
        report=report,
        candidate_store=candidate_store,
        skill_store=skill_store,
        event_store=event_store,
    )

    assert len(generator.contexts) == 1
    assert second_payload["personal_skill_candidate"] == first_payload["personal_skill_candidate"]
    events = _personal_skill_events(
        event_store,
        session_id=session.session_id,
        candidate_id=candidate_id,
    )
    assert len(events) == 4
    assert len({event["event_key"] for event in events}) == 4


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


def test_personal_skill_and_teacher_reflection_use_teacher_agent_analysis_context(tmp_path) -> None:
    case = _load_case()
    generator = CapturingGenerator()
    teacher_agent = FakeTeacherAgent()
    service = PersonalTrainingSkillService(
        generator=generator,
        approval_agent=ApprovingAgent(),
        regression_gate=PassingGate(),
        teacher_agent=teacher_agent,
    )
    session = SimpleNamespace(
        session_id="personal-teacher-agent-session",
        case_id=case.case_id,
        student_id="student-a",
    )
    report = {
        "report_id": "personal-teacher-agent-report",
        "case_id": case.case_id,
        "total_score": 21,
        "max_score": 60,
        "missed_items": ["ht_migration", "pe_tenderness", "rs_exclude"],
        "clinical_reasoning_trace": {
            "trace_version": "clinical_reasoning_trace_v1",
            "cognitive_patterns": [
                {
                    "pattern_id": "weak_hypothesis_testing",
                    "label": "假设验证不足",
                    "category": "hypothesis_testing",
                    "severity": "high",
                    "evidence": "提出诊断方向后缺少关键查体和排除依据。",
                    "why_it_matters": "验证不足会让最终诊断像猜测。",
                    "remediation": "下一轮先说明每个查体和检查要验证什么。",
                    "source_signal_ids": ["ht_migration", "pe_tenderness", "rs_exclude"],
                }
            ],
        },
        "training_progress_snapshot": {"coverage_map": {}},
        "source_reference_items": [],
    }

    longitudinal_context = {
        "schema_version": "teacher_longitudinal_context_v1",
        "report_window_size": 3,
        "score_trend": {"direction": "stable", "points": []},
        "current_gap_statuses": [
            {
                "gap_id": "ht_migration",
                "gap_type": "rubric_item",
                "label": "追问疼痛部位及转移特征",
                "status": "reactivated_after_improvement",
            }
        ],
        "recovered_gaps": [],
        "gap_status_counts": {
            "first_seen_current_window": 0,
            "repeated": 0,
            "reactivated_after_improvement": 1,
            "recovered_since_previous_report": 0,
        },
        "applied_personal_skills": [],
        "evidence_boundary": "仅基于最近三份报告。",
    }
    payload = service.generate_for_completed_session(
        session=session,
        case=case,
        report=report,
        candidate_store=TrainingSkillCandidateStore(tmp_path / "candidates.sqlite3"),
        skill_store=TrainingSkillStore(tmp_path / "skills.sqlite3"),
        event_store=TrainingEventStore(tmp_path / "events.sqlite3"),
        teacher_longitudinal_context=longitudinal_context,
    )

    assert teacher_agent.requests
    assert teacher_agent.requests[0].case_id == case.case_id
    assert teacher_agent.requests[0].clinical_reasoning_trace["trace_version"] == "clinical_reasoning_trace_v1"
    assert teacher_agent.requests[0].longitudinal_context == longitudinal_context
    context = generator.contexts[0]
    assert "longitudinal_context" not in context.teacher_analysis_context
    assert context.teacher_analysis_context["analysis_summary"] == "学生没有把疼痛迁移、关键查体和鉴别排除连成验证链。"
    assert context.teacher_analysis_context["skill_memory_focus"]["problem_pattern_summary"] == "假设形成后缺少验证路径"
    assert context.teacher_analysis_context["student_thinking_hypothesis"] == "学生过早进入结论，尚未把病史、查体和排除依据组织成验证链。"
    assert context.teacher_analysis_context["clinical_thinking_profile"]["hypothesis_management"] == "诊断假设形成偏早，验证动作不足。"
    reflection = payload["ai_reflection_review"]
    assert reflection["generated_by"] == "teacher_agent"
    assert reflection["overall_comment"] == "这次训练的问题不是单个漏项，而是假设形成后缺少验证路径。"
    assert reflection["major_issues"][0]["title"] == "假设验证链断裂"
    assert reflection["teacher_analysis_context"]["skill_memory_focus"]["recommended_intervention"].startswith("Coach 后续用反问")
    assert reflection["teacher_analysis_context"]["clinical_thinking_profile"]["verification_strategy"] == "查体和检查没有围绕假设形成支持与排除证据。"
    assert reflection["teacher_analysis_context"]["longitudinal_context"] == longitudinal_context


def test_personal_skill_generator_failure_falls_back_to_template_candidate(tmp_path) -> None:
    case = _load_case()
    service = PersonalTrainingSkillService(
        generator=FailingGenerator(),
        approval_agent=ApprovingAgent(),
        regression_gate=PassingGate(),
        teacher_agent=FakeTeacherAgent(),
    )
    session = SimpleNamespace(
        session_id="personal-fallback-session",
        case_id=case.case_id,
        student_id="student-a",
    )
    report = {
        "report_id": "personal-fallback-report",
        "case_id": case.case_id,
        "total_score": 18,
        "max_score": 60,
        "missed_items": ["ht_migration", "pe_tenderness", "rs_exclude"],
        "clinical_reasoning_trace": {
            "trace_version": "clinical_reasoning_trace_v1",
            "cognitive_patterns": [
                {
                    "pattern_id": "weak_hypothesis_testing",
                    "label": "假设验证不足",
                    "category": "hypothesis_testing",
                    "severity": "high",
                    "source_signal_ids": ["ht_migration", "pe_tenderness", "rs_exclude"],
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

    candidate = payload["personal_skill_candidate"]
    assert candidate["status"] == "approved"
    assert candidate["title"] == "个人复盘训练 Skill"
    assert candidate["candidate_id"] == "personal_skill_candidate_personal-fallback-session"
    assert candidate["teacher_analysis_context"]["student_thinking_hypothesis"]
    assert payload["ai_reflection_review"]["teacher_analysis_context"]["clinical_thinking_profile"]


def test_deterministic_teacher_agent_still_writes_analysis_context() -> None:
    case = _load_case()
    report = {
        "report_id": "deterministic-teacher-context-report",
        "case_id": case.case_id,
        "total_score": 18,
        "max_score": 60,
        "missed_items": ["ht_migration", "pe_tenderness", "rs_exclude"],
        "clinical_reasoning_trace": {
            "trace_version": "clinical_reasoning_trace_v1",
            "cognitive_patterns": [
                {
                    "pattern_id": "weak_problem_representation",
                    "label": "问题表征薄弱",
                    "category": "problem_representation",
                    "severity": "high",
                    "source_signal_ids": ["ht_migration"],
                }
            ],
        },
        "training_progress_snapshot": {"coverage_map": {}},
        "source_reference_items": [],
    }

    reflection = build_teacher_reflection_review_payload(
        report,
        case,
        teacher_agent=DeterministicTeacherAgent(),
    )

    context = reflection["teacher_analysis_context"]
    assert reflection["generated_by"] == "teacher_agent_deterministic"
    assert context["analysis_mode"] == "deterministic_baseline"
    assert context["student_thinking_hypothesis"]
    assert context["clinical_thinking_profile"]["verification_strategy"]


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
    coaching_sections = reflection["teacher_coaching_review"]
    assert [section["section_id"] for section in coaching_sections] == [
        "case_framing",
        "hypothesis_path",
        "verification_path",
        "differential_reasoning",
        "evidence_synthesis",
        "next_drill_script",
    ]
    hypothesis_section = next(section for section in coaching_sections if section["section_id"] == "hypothesis_path")
    assert "辅助检查早于关键查体" in hypothesis_section["teacher_comment"]
    verification_section = next(section for section in coaching_sections if section["section_id"] == "verification_path")
    assert verification_section["evidence_labels"] == ["追问疼痛部位及转移特征"]
    assert "迁移痛推理点" in verification_section["teacher_comment"]
    drill_section = next(section for section in coaching_sections if section["section_id"] == "next_drill_script")
    assert "下一轮" in drill_section["next_move"]


def test_teacher_coaching_review_uses_concise_natural_student_facing_language() -> None:
    case = _load_case()
    report = {
        "report_id": "trace-language-quality-report",
        "case_id": case.case_id,
        "total_score": 37,
        "max_score": 60,
        "missed_items": [
            "ht_character",
            "ht_severity",
            "pe_tenderness",
            "pe_guarding",
            "pe_rovsing",
            "ax_crp",
            "ax_us",
            "ax_ua",
            "dxd_urolith",
            "rs_exclude",
        ],
        "clinical_reasoning_trace": {
            "trace_version": "clinical_reasoning_trace_v1",
            "cognitive_patterns": [
                {
                    "pattern_id": "weak_problem_representation",
                    "label": "问题表征薄弱",
                    "category": "problem_representation",
                    "severity": "medium",
                    "evidence": "问题表征缺少追问疼痛性质、追问疼痛程度。",
                    "why_it_matters": "起病、部位、性质、程度和伴随症状不清，后续诊断假设会缺少支点。",
                    "remediation": "下一轮先补齐疼痛性质和程度，再进入查体。",
                    "source_signal_ids": ["ht_character", "ht_severity"],
                },
                {
                    "pattern_id": "premature_testing_before_exam",
                    "label": "检查申请早于关键查体",
                    "category": "hypothesis_testing",
                    "severity": "medium",
                    "evidence": "本轮先申请辅助检查，随后才记录关键查体，验证顺序偏检查驱动。",
                    "why_it_matters": "跳过关键查体会让检查选择变成列表式申请。",
                    "remediation": "下一轮先说明当前假设，再选择能验证假设的查体。",
                    "source_signal_ids": ["event:auxiliary_test_requested"],
                },
            ],
            "hypothesis_testing": {
                "sequence_flags": [
                    {
                        "flag_id": "premature_testing_before_exam",
                        "label": "检查申请早于关键查体",
                        "severity": "medium",
                        "evidence": "本轮先申请辅助检查，随后才记录关键查体，验证顺序偏检查驱动。",
                    },
                    {
                        "flag_id": "delayed_hypothesis_generation",
                        "label": "诊断假设生成偏晚",
                        "severity": "medium",
                        "evidence": "训练记录中未看到提交诊断前形成过明确诊断假设。",
                    },
                ]
            },
            "evidence_chain_breakpoints": [
                {
                    "breakpoint_id": "appendicitis_001.rp_02",
                    "statement": "McBurney 点压痛、反跳痛、肌紧张和 Rovsing 征提示右下腹腹膜刺激征。",
                    "kind": "support",
                    "status": "partial",
                    "missing_evidence": [
                        "abd.palpation.tenderness",
                        "abd.palpation.guarding",
                        "abd.special.rovsing",
                    ],
                    "missing_evidence_labels": ["McBurney 点压痛", "肌紧张", "Rovsing 征"],
                    "teacher_action": "先补齐 McBurney 点压痛、肌紧张、Rovsing 征，再说明这些证据如何支持当前诊断假设。",
                },
                {
                    "breakpoint_id": "appendicitis_001.rp_03",
                    "statement": "白细胞升高伴 CRP 升高支持炎症性腹痛。",
                    "kind": "support",
                    "status": "partial",
                    "missing_evidence": ["lab.crp"],
                    "missing_evidence_labels": ["C 反应蛋白"],
                    "teacher_action": "先补齐 C 反应蛋白，再说明这些证据如何支持当前诊断假设。",
                },
                {
                    "breakpoint_id": "appendicitis_001.rp_04",
                    "statement": "腹部超声或腹部 CT 的阑尾异常表现支持阑尾区炎症。",
                    "kind": "support",
                    "status": "missing",
                    "missing_evidence": ["img.abd_us", "img.abd_ct"],
                    "missing_evidence_labels": ["腹部超声", "腹部 CT"],
                    "teacher_action": "先补齐腹部超声、腹部 CT，再说明这些证据如何支持当前诊断假设。",
                },
            ],
        },
        "training_progress_snapshot": {"coverage_map": {}},
        "source_reference_items": [],
    }

    reflection = build_teacher_reflection_review_payload(report, case)
    sections = reflection["teacher_coaching_review"]
    section_by_id = {section["section_id"]: section for section in sections}

    all_student_facing_text = "\n".join(
        str(section.get(field, ""))
        for section in sections
        for field in ["teacher_comment", "why_it_matters", "next_move"]
    )
    for awkward_fragment in ["。、", "。；", "。。", "；；", "，。", "等 5 项；还缺"]:
        assert awkward_fragment not in all_student_facing_text

    assert len(section_by_id["evidence_synthesis"]["teacher_comment"]) <= 220
    assert "本轮顺序问题" in section_by_id["hypothesis_path"]["teacher_comment"]
    assert "证据链先补" in section_by_id["verification_path"]["next_move"]
    assert section_by_id["next_drill_script"]["next_move"].count("下一轮") == 1
    assert "固定顺序" not in section_by_id["next_drill_script"]["teacher_comment"]


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
