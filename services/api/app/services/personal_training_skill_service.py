from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from app.models.case import Case
from app.services.admin_display_resolver import rubric_item_labels
from app.services.clinical_reasoning_trace_service import (
    action_order_summary_from_report,
    evidence_chain_breakpoints_from_report,
    sequence_flags_from_report,
)
from app.services.model_call_policy import ModelProviderPolicyError
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_auto_approval_service import AUTO_APPROVAL_AGENT_ID, TrainingSkillApprovalAgent
from app.services.training_skill_candidate_service import (
    TemplateTrainingSkillCandidateGenerator,
    TrainingSkillCandidateContext,
    TrainingSkillCandidateGenerationError,
    TrainingSkillCandidateGenerator,
    TrainingSkillCandidateMissedItem,
    TrainingSkillCandidateTurnPattern,
    create_default_training_skill_candidate_generator,
)
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_regression_gate import TrainingSkillRegressionGate
from app.services.training_skill_store import TrainingSkillStore
from app.services.teacher_agent import (
    DeterministicTeacherAgent,
    TeacherAnalysisRequest,
    create_default_teacher_agent,
    normalize_teacher_analysis_response,
)

MAX_APPROVAL_AGENT_ROUNDS = 3
TEACHER_REFLECTION_PROMPT_VERSION = "teacher_reflection_v3"

TEACHER_REFLECTION_PROMPT_CONTRACT = """你是 OSCE 训练报告里的教师复盘 Agent。

你的读者是刚完成一次训练的学生。你的任务不是证明系统评分正确，也不是展示 RAG 来源或 Skill 内部记录，
而是用老师讲评的口吻帮助学生理解：本轮哪里做得好、哪里没做好、为什么会影响临床推理、正确顺序是什么、下一轮怎么练。

硬性规则：
- 只能基于后端提供的病例标题、rubric 中文训练点、已覆盖/未覆盖线索、维度得分和学生提交内容讲评。
- 不得新增病例事实、修改标准诊断、改写 rubric 或泄露隐藏材料。
- 不得输出真实诊疗建议、治疗方案、用药剂量或处置指令。
- 不要机械罗列每个 missed_item；必须把漏项归纳成 2-4 个临床思维问题组。
- 如果输入包含 clinical_reasoning_trace，必须优先围绕其中的 cognitive_patterns 讲评；missed_items 只作为具体证据例子。
- 每个问题组必须包含：学生本轮表现、为什么重要、正确做法、下一轮具体练习动作。
- 额外输出 teacher_coaching_review，用 6 个小节带学生重走本轮临床思路：病例表征、假设路径、验证路径、鉴别诊断、证据整合、下一轮演练脚本。
- teacher_coaching_review 面向学生主阅读区：每个小节 2-3 句以内，只讲一个核心判断，不堆砌全部证据链。
- 证据链断点只摘要最关键的 2-3 个中文训练点；不要把多个已带句号的片段硬拼成“。、”“。。”或超长段落。
- 语言要像老师当面讲评：先指出本轮问题，再说明为什么影响推理，最后给下一轮动作；避免机械列字段、技术 ID 或泛泛口号。
- 用老师对学生说话的语气，明确、具体、可执行，避免“加强学习”这类空话。
- 如果学生已经覆盖较完整，重点转为证据表达、支持/排除依据和迁移训练。
- 输出结构化 JSON：overall_comment、strengths_review、major_issues、teacher_coaching_review、reasoning_chain_review、next_practice_plan、teacher_note。
"""

ISSUE_GROUP_PRIORITY = ["history", "physical_exam", "auxiliary_test", "reasoning"]

ISSUE_GROUP_DEFINITIONS: dict[str, dict[str, str]] = {
    "history": {
        "title": "病史时间线与关键症状结构不完整",
        "observed": "本轮病史采集还没有把主诉、病程演变和关键伴随信息串成稳定的问题表征。",
        "why": "问诊要先形成清晰的时间线和症状结构；关键病史不完整时，后续查体、检查和诊断假设都会缺少依据。",
        "correct": "先用开放式问题确认主诉和病程，再根据当前病例的关键训练点补齐症状特征、伴随信息和相关阴性信息。",
        "next": "下一轮先完成本病例的关键病史训练点，用一句话概括后再进入查体或检查申请。",
    },
    "physical_exam": {
        "title": "查体没有围绕诊断假设补足关键体征",
        "observed": "本轮查体选择没有充分覆盖能验证或反驳当前诊断假设的关键体征。",
        "why": "查体是把主诉和诊断假设连接起来的中间证据；缺少关键体征会让后续检查和诊断表达显得跳跃。",
        "correct": "在完成基本病史后，选择与当前假设直接相关的查体，并说明每项结果支持或反驳什么。",
        "next": "下一轮在申请辅助检查前，先完成与当前假设直接相关的关键查体。",
    },
    "auxiliary_test": {
        "title": "辅助检查没有形成支持与排除证据",
        "observed": "本轮辅助检查申请还没有完整覆盖能支持主要假设或排除相近诊断的关键证据。",
        "why": "辅助检查不是为了堆项目，而是为了支持主要诊断、修正风险判断，并排除容易混淆的鉴别诊断。",
        "correct": "根据病史和查体结果选择能验证当前假设的检查，并说明每项检查要支持或排除什么。",
        "next": "下一轮每申请一个检查，都补一句它支持什么或排除什么。",
    },
    "reasoning": {
        "title": "鉴别诊断和证据表达没有闭环",
        "observed": "本轮推理表达还没有把阳性依据、阴性依据和鉴别排除依据组织成完整链条。",
        "why": "OSCE 不只看最终诊断名称，更看你是否能说明为什么支持它、为什么暂不支持其他可能。",
        "correct": "提交前按“支持依据、反证/排除依据、仍需验证的问题”组织诊断推理。",
        "next": "下一轮提交诊断前，先口头整理至少两条支持依据和一条排除依据。",
    },
}

HISTORY_SLOT_TRAINING_LABELS = {
    "onset": "追问起病时间",
    "duration": "追问持续时间",
    "location": "追问疼痛部位",
    "character": "追问疼痛性质",
    "radiation": "追问放射或转移",
    "severity": "追问疼痛程度",
    "aggravating": "追问加重因素",
    "relieving": "追问缓解因素",
    "progression": "追问症状演变",
    "associated_symptom": "追问伴随症状",
    "frequency": "追问发作频率",
    "timing": "追问发作时段",
    "context": "追问诱发背景",
    "negation": "追问阴性症状",
}


def build_not_ready_personal_skill_payload() -> dict[str, Any]:
    return {
        "personal_skill_candidate": {
            "status": "not_complete",
            "reason": "final_submission_required",
            "scope": "personal",
            "candidate_id": None,
            "skill_id": None,
            "web_check_status": "not_configured",
            "external_evidence_checks": [],
        },
        "ai_reflection_review": {
            "status": "not_ready",
            "reason": "final_submission_required",
            "summary": "提交诊断并生成完整评分报告后，系统会生成教师复盘和下一轮个人训练 Skill。",
            "mistake_patterns": [],
            "teacher_feedback": "",
            "next_focus": "",
            "source_references": [],
            "source_reference_items": [],
        },
    }


def build_generation_failed_personal_skill_payload(
    *,
    report: dict[str, Any],
    case: Case,
    teacher_agent: Any | None = None,
    teacher_longitudinal_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "personal_skill_candidate": {
            "status": "generation_failed",
            "reason": "skill_candidate_generation_failed",
            "scope": "personal",
            "candidate_id": None,
            "skill_id": None,
            "web_check_status": "not_configured",
            "external_evidence_checks": [],
            "summary": "个人训练 Skill 暂未生成；请检查当前账号的模型服务配置后重试打开报告。",
        },
        "ai_reflection_review": _build_ai_reflection_review(
            report,
            case,
            teacher_agent=teacher_agent,
            teacher_longitudinal_context=teacher_longitudinal_context,
        ),
    }


class PersonalTrainingSkillService:
    def __init__(
        self,
        *,
        generator: TrainingSkillCandidateGenerator | None = None,
        approval_agent: TrainingSkillApprovalAgent | None = None,
        regression_gate: TrainingSkillRegressionGate | None = None,
        teacher_agent: Any | None = None,
    ) -> None:
        self._generator = generator
        self._approval_agent = approval_agent or TrainingSkillApprovalAgent()
        self._regression_gate = regression_gate or TrainingSkillRegressionGate()
        self._teacher_agent = teacher_agent if teacher_agent is not None else create_default_teacher_agent()

    def generate_for_completed_session(
        self,
        *,
        session: Any,
        case: Case,
        report: dict[str, Any],
        candidate_store: TrainingSkillCandidateStore,
        skill_store: TrainingSkillStore,
        event_store: TrainingEventStore,
        teacher_longitudinal_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidate_id = _personal_candidate_id(str(session.session_id))
        existing_candidate = candidate_store.get_candidate(candidate_id)
        if existing_candidate is None:
            teacher_reflection = _build_ai_reflection_review(
                report,
                case,
                teacher_agent=self._teacher_agent,
                teacher_longitudinal_context=teacher_longitudinal_context,
            )
            candidate = self._generate_candidate(
                session=session,
                case=case,
                report=report,
                teacher_analysis_context=_teacher_analysis_context_for_skill(teacher_reflection),
            )
            candidate, review, approval_dialogue = self._review_candidate(candidate, case)
            candidate["approval_dialogue"] = approval_dialogue
            candidate["review"] = review
            candidate["review_revision"] = _personal_skill_review_revision(candidate, review)
            candidate["ai_reflection_review"] = deepcopy(teacher_reflection)
            candidate_store.save_candidate(candidate, review)
        else:
            candidate = existing_candidate
            _validate_personal_candidate_ownership(candidate, session)
            review = candidate.get("review")
            if not isinstance(review, dict) or not str(review.get("status", "")).strip():
                raise RuntimeError("个人训练 Skill 候选缺少有效审核状态。")
            candidate["review_revision"] = _personal_skill_review_revision(candidate, review)
            stored_reflection = candidate.get("ai_reflection_review")
            teacher_reflection = (
                deepcopy(stored_reflection)
                if isinstance(stored_reflection, dict)
                else _build_ai_reflection_review(
                    report,
                    case,
                    teacher_agent=self._teacher_agent,
                    teacher_longitudinal_context=teacher_longitudinal_context,
                )
            )

        skill_id = _personal_skill_id(str(session.session_id))
        enabled_skill: dict[str, Any] | None = None
        if review["status"] == "approved":
            enabled_skill = _ensure_personal_skill_enabled(
                candidate=candidate,
                skill_store=skill_store,
                skill_id=skill_id,
            )
        _append_personal_skill_events(
            candidate=candidate,
            review=review,
            event_store=event_store,
            session=session,
            skill_id=skill_id if enabled_skill is not None else None,
        )
        return {
            "personal_skill_candidate": _report_candidate_summary(
                candidate,
                enabled_skill=enabled_skill,
            ),
            "ai_reflection_review": teacher_reflection,
        }

    def _generate_candidate(
        self,
        *,
        session: Any,
        case: Case,
        report: dict[str, Any],
        teacher_analysis_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = str(session.session_id)
        report_id = str(report.get("report_id") or f"{session_id}_report")
        missed_items = _missed_items_from_report(report, case.case_id)
        reasoning_turn_patterns = _reasoning_turn_patterns_from_report(
            report,
            case_id=case.case_id,
            session_id=session_id,
            report_id=report_id,
        )
        reasoning_pattern_ids = [pattern.pattern_id for pattern in reasoning_turn_patterns]
        reasoning_pattern_labels = [pattern.title for pattern in reasoning_turn_patterns]
        trace_version = _trace_version_from_report(report)
        context = TrainingSkillCandidateContext(
            pattern_id=f"personal_{session_id}",
            missed_items=missed_items,
            support_count=1,
            case_ids=[case.case_id],
            source_report_count=1,
            related_recommendations=_related_recommendations(report),
            turn_patterns=reasoning_turn_patterns,
            teacher_analysis_context=teacher_analysis_context or {},
        )
        generator = self._generator or create_default_training_skill_candidate_generator()
        try:
            candidate = generator.generate_candidate(context)
        except (TrainingSkillCandidateGenerationError, ModelProviderPolicyError) as exc:
            candidate = TemplateTrainingSkillCandidateGenerator().generate_candidate(context)
            candidate["generation_mode"] = "template_fallback"
            candidate["generation_warnings"] = [str(exc)]
        trigger_item_ids = [item.item_id for item in missed_items] or ["reflection:structured_expression"]
        stage_scope = ["case_intro", "history_taking", "physical_exam", "auxiliary_testing", "diagnosis_submission"]
        candidate.update(
            {
                "candidate_id": _personal_candidate_id(session_id),
                "trigger_item_id": f"personal_{session_id}",
                "trigger_item_ids": trigger_item_ids,
                "case_ids": [case.case_id],
                "scope": "personal",
                "owner_student_id": str(session.student_id),
                "source_session_id": session_id,
                "source_session_ids": [session_id],
                "source_report_ids": [report_id],
                "source_report_count": 1,
                "support_count": 1,
                "stage_scope": stage_scope,
                "effect_status": "insufficient_samples",
                "applies_when": {
                    "case_ids": [case.case_id],
                    "stage_scope": stage_scope,
                    "trigger_item_ids": trigger_item_ids,
                    "current_missing_evidence": trigger_item_ids,
                    "reasoning_pattern_ids": reasoning_pattern_ids,
                    "min_support_count": 1,
                    "owner_student_id": str(session.student_id),
                    "source_session_id": session_id,
                },
                "reasoning_pattern_ids": reasoning_pattern_ids,
                "reasoning_pattern_labels": reasoning_pattern_labels,
                "source_trace_version": trace_version,
                "rag_evidence_items": _rag_evidence_items(report),
                "web_check_status": "not_configured",
                "external_evidence_checks": [],
            }
        )
        if candidate.get("title") == "OSCE 训练模式纠偏提示":
            candidate["title"] = "个人复盘训练 Skill"
        return candidate

    def _review_candidate(self, candidate: dict[str, Any], case: Case) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        current_candidate = deepcopy(candidate)
        approval_dialogue: list[dict[str, Any]] = []
        protected_terms = [case.diagnosis.main_diagnosis, *case.diagnosis.main_diagnosis_synonyms]
        review: dict[str, Any] = {}
        for round_index in range(1, MAX_APPROVAL_AGENT_ROUNDS + 1):
            reviewed_candidate = self._approval_agent.review_candidate(
                current_candidate,
                protected_terms=protected_terms,
            )
            review = self._regression_gate.review_candidate(reviewed_candidate, _passing_batch_result())
            approved = review["status"] == "ready_for_review"
            agent_review = reviewed_candidate.get("approval_agent_review", {})
            approval_dialogue.append(
                {
                    "round": round_index,
                    "agent_id": AUTO_APPROVAL_AGENT_ID,
                    "decision": "approved" if approved else "revise",
                    "revision_status": agent_review.get("revision_status", "unchanged"),
                    "changed_fields": list(agent_review.get("changed_fields", [])),
                    "rag_reference_count": len(reviewed_candidate.get("rag_evidence_items", [])),
                    "web_check_status": reviewed_candidate.get("web_check_status", "not_configured"),
                    "blocking_failures": list(review.get("blocking_failures", [])),
                    "candidate_safety_violations": list(review.get("candidate_safety_violations", [])),
                    "candidate_context_violations": list(review.get("candidate_context_violations", [])),
                }
            )
            current_candidate = reviewed_candidate
            if approved:
                return current_candidate, {
                    **review,
                    "status": "approved",
                    "reviewer_id": AUTO_APPROVAL_AGENT_ID,
                    "approval_mode": "auto_agent_personal",
                }, approval_dialogue
        return current_candidate, {
            **review,
            "status": "blocked_by_regression",
            "reviewer_id": AUTO_APPROVAL_AGENT_ID,
            "approval_mode": "auto_agent_personal",
        }, approval_dialogue


def _passing_batch_result() -> Any:
    return SimpleNamespace(
        total_cases=0,
        passed_cases=0,
        failed_cases=0,
        results=[],
        passed=True,
        total_duration_ms=0,
    )


def _missed_items_from_report(report: dict[str, Any], case_id: str) -> list[TrainingSkillCandidateMissedItem]:
    missed_items = [str(item_id) for item_id in report.get("missed_items", []) if str(item_id)]
    if not missed_items:
        missed_items = ["reflection:structured_expression"]
    return [
        TrainingSkillCandidateMissedItem(
            item_id=item_id,
            count=1,
            case_ids=[case_id],
        )
        for item_id in missed_items[:8]
    ]


def _related_recommendations(report: dict[str, Any]) -> list[str]:
    references = [
        str(recommendation.get("reference"))
        for recommendation in report.get("knowledge_recommendations", [])
        if isinstance(recommendation, dict) and recommendation.get("reference")
    ]
    if references:
        return references
    return [str(reference) for reference in report.get("source_references", [])[:8]]


def _rag_evidence_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    source_items = report.get("source_reference_items", [])
    if not isinstance(source_items, list):
        return []
    return [
        {
            "reference": str(item.get("reference", "")),
            "source_type": str(item.get("source_type", "")),
            "title": str(item.get("title", "")),
            "metadata": item.get("metadata", {}),
        }
        for item in source_items
        if isinstance(item, dict) and item.get("reference")
    ][:12]


def _trace_version_from_report(report: dict[str, Any]) -> str:
    trace = report.get("clinical_reasoning_trace")
    if not isinstance(trace, dict):
        return ""
    return str(trace.get("trace_version") or "")


def _reasoning_patterns_from_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    trace = report.get("clinical_reasoning_trace")
    if not isinstance(trace, dict):
        return []
    patterns = trace.get("cognitive_patterns", [])
    if not isinstance(patterns, list):
        return []
    normalized_patterns: list[dict[str, Any]] = []
    for pattern in patterns:
        if not isinstance(pattern, dict):
            continue
        pattern_id = str(pattern.get("pattern_id") or "").strip()
        if not pattern_id:
            continue
        normalized_patterns.append(
            {
                **pattern,
                "pattern_id": pattern_id,
                "label": str(pattern.get("label") or pattern_id),
                "category": str(pattern.get("category") or "clinical_reasoning"),
                "severity": str(pattern.get("severity") or "medium"),
                "source_signal_ids": _normalized_string_list(pattern.get("source_signal_ids")),
                "trigger_item_ids": _normalized_string_list(pattern.get("trigger_item_ids")),
            }
        )
    return normalized_patterns


def _reasoning_turn_patterns_from_report(
    report: dict[str, Any],
    *,
    case_id: str,
    session_id: str,
    report_id: str,
) -> list[TrainingSkillCandidateTurnPattern]:
    result: list[TrainingSkillCandidateTurnPattern] = []
    seen_pattern_ids: set[str] = set()
    for pattern in _reasoning_patterns_from_report(report)[:4]:
        trigger_item_ids = _reasoning_pattern_trigger_item_ids(pattern, report)
        pattern_id = str(pattern["pattern_id"])
        seen_pattern_ids.add(pattern_id)
        result.append(
            TrainingSkillCandidateTurnPattern(
                pattern_id=pattern_id,
                pattern_type=str(pattern.get("category") or "clinical_reasoning"),
                title=str(pattern.get("label") or pattern["pattern_id"]),
                count=1,
                trigger_item_ids=trigger_item_ids,
                case_ids=[case_id],
                session_ids=[session_id],
                source_report_ids=[report_id],
                source_report_count=1,
            )
        )
    for flag in sequence_flags_from_report(report)[:2]:
        pattern_id = str(flag.get("flag_id") or "").strip()
        if not pattern_id or pattern_id in seen_pattern_ids:
            continue
        seen_pattern_ids.add(pattern_id)
        result.append(
            TrainingSkillCandidateTurnPattern(
                pattern_id=pattern_id,
                pattern_type="sequence_issue",
                title=str(flag.get("label") or pattern_id),
                count=1,
                trigger_item_ids=_trace_signal_trigger_item_ids(
                    _normalized_string_list(flag.get("source_signal_ids")),
                    report,
                ),
                case_ids=[case_id],
                session_ids=[session_id],
                source_report_ids=[report_id],
                source_report_count=1,
            )
        )
    for breakpoint in evidence_chain_breakpoints_from_report(report)[:4]:
        breakpoint_id = str(breakpoint.get("breakpoint_id") or breakpoint.get("statement") or "").strip()
        if not breakpoint_id:
            continue
        pattern_id = f"evidence_chain_{_safe_pattern_id_fragment(breakpoint_id)}"
        if pattern_id in seen_pattern_ids:
            continue
        seen_pattern_ids.add(pattern_id)
        result.append(
            TrainingSkillCandidateTurnPattern(
                pattern_id=pattern_id,
                pattern_type="evidence_chain_breakpoint",
                title=str(breakpoint.get("statement") or breakpoint_id),
                count=1,
                trigger_item_ids=_trace_signal_trigger_item_ids(
                    _normalized_string_list(breakpoint.get("missing_evidence")),
                    report,
                ),
                case_ids=[case_id],
                session_ids=[session_id],
                source_report_ids=[report_id],
                source_report_count=1,
            )
        )
    return result


def _reasoning_pattern_trigger_item_ids(pattern: dict[str, Any], report: dict[str, Any]) -> list[str]:
    trigger_item_ids = _normalized_string_list(pattern.get("trigger_item_ids"))
    if trigger_item_ids:
        return trigger_item_ids[:12]
    source_signal_ids = _normalized_string_list(pattern.get("source_signal_ids"))
    concrete_signals = [
        signal
        for signal in source_signal_ids
        if signal and ":" not in signal and "." not in signal
    ]
    if concrete_signals:
        return concrete_signals[:12]
    return [str(item_id) for item_id in report.get("missed_items", []) if str(item_id)][:8]


def _trace_signal_trigger_item_ids(signal_ids: list[str], report: dict[str, Any]) -> list[str]:
    concrete_signals = [
        signal
        for signal in signal_ids
        if signal and ":" not in signal and "." not in signal
    ]
    if concrete_signals:
        return concrete_signals[:12]
    return [str(item_id) for item_id in report.get("missed_items", []) if str(item_id)][:8]


def _safe_pattern_id_fragment(value: str) -> str:
    normalized = "".join(character if character.isalnum() or character == "_" else "_" for character in value)
    normalized = "_".join(part for part in normalized.split("_") if part)
    return normalized[:96] or "unknown"


def build_teacher_reflection_review_payload(
    report: dict[str, Any],
    case: Case | None = None,
    *,
    teacher_agent: Any | None = None,
    teacher_longitudinal_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _build_ai_reflection_review(
        report,
        case,
        teacher_agent=teacher_agent,
        teacher_longitudinal_context=teacher_longitudinal_context,
    )


def _build_ai_reflection_review(
    report: dict[str, Any],
    case: Case | None = None,
    *,
    teacher_agent: Any | None = None,
    teacher_longitudinal_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    missed_items = [str(item_id) for item_id in report.get("missed_items", [])]
    case_id = str(report.get("case_id") or getattr(case, "case_id", "") or "")
    case_title = str(getattr(case, "case_title", "") or case_id or "当前病例")
    missed_labels = rubric_item_labels(missed_items[:8], [case_id]) if missed_items else []
    covered_labels = _coverage_map_labels(report, "covered", limit=4, case=case)
    pending_labels = _coverage_map_labels(report, "pending", limit=4, case=case)
    reasoning_patterns = _reasoning_patterns_from_report(report)
    reasoning_trace_summary = _teacher_reasoning_trace_summary(report)
    source_reference_items = _rag_evidence_items(report)
    source_references = [item["reference"] for item in source_reference_items]
    score_text = _score_text(report)
    strengths_review = _build_strengths_review(report, covered_labels)
    major_issues = _build_teacher_major_issues(
        report=report,
        case=case,
        case_id=case_id,
        missed_items=missed_items,
        missed_labels=missed_labels,
        pending_labels=pending_labels,
        reasoning_patterns=reasoning_patterns,
    )
    overall_comment = _build_overall_teacher_comment(
        case_title=case_title,
        score_text=score_text,
        missed_items=missed_items,
        major_issues=major_issues,
    )
    reasoning_chain_review = _build_reasoning_chain_review(
        case_title=case_title,
        major_issues=major_issues,
        reasoning_trace_summary=reasoning_trace_summary,
    )
    next_practice_plan = _build_next_practice_plan(major_issues, pending_labels)
    teacher_coaching_review = _build_teacher_coaching_review(
        case_title=case_title,
        major_issues=major_issues,
        reasoning_chain_review=reasoning_chain_review,
        next_practice_plan=next_practice_plan,
        reasoning_trace_summary=reasoning_trace_summary,
        pending_labels=pending_labels,
    )
    teacher_note = (
        "复盘时先看问题背后的推理顺序：先把病史问完整，再用查体和检查验证假设，最后用证据说明支持与排除。"
    )
    if missed_items:
        summary = (
            f"本轮病例「{case_title}」得到 {score_text}；主诊断方向已建立，但仍有 {len(missed_items)} "
            f"个训练点需要复盘，重点是{_compact_list_text(missed_labels, limit=3, fallback='本轮未覆盖的关键评分点')}。"
        )
        teacher_feedback = (
            "从老师视角看，本轮不是单个知识点问题，而是病例评估链条还不够闭合。"
            f"你已经覆盖了{_compact_list_text(covered_labels, limit=4, fallback='部分关键证据')}，这些能支撑主要判断；"
            f"但{_compact_list_text(missed_labels, limit=4, fallback='本轮未覆盖的关键评分点')}没有充分呈现，"
            "会让鉴别诊断和排除依据显得不稳。为什么要补这些：OSCE 评分看的是能否把病史、查体、检查和鉴别排除串成证据链，"
            "而不只是写出可能诊断。"
        )
    else:
        summary = f"本轮病例「{case_title}」得到 {score_text}；核心评分项覆盖较完整，复盘重点转为表达结构和迁移训练。"
        teacher_feedback = (
            f"从老师视角看，本轮对「{case_title}」的主要证据链比较完整。"
            "下一步要把每个阳性和阴性依据说清楚：它支持什么、排除了什么、还有什么不确定。"
            "为什么要这样做：临床推理评价关注证据与结论之间的关系，而不是只看最终诊断名称。"
        )
    if pending_labels:
        next_focus = (
            "下一轮先按“病史补全 → 关键查体 → 必要检查 → 鉴别排除”的顺序练习，"
            f"优先补{_compact_list_text(pending_labels, limit=4, fallback='未覆盖的关键线索')}，并说明每一步为什么会改变判断。"
        )
    else:
        next_focus = "下一轮继续练习把已收集证据整理成支持依据、反证依据和仍需验证的问题。"
    review = {
        "status": "generated",
        "summary": summary,
        "overall_comment": overall_comment,
        "strengths_review": strengths_review,
        "major_issues": major_issues,
        "teacher_coaching_review": teacher_coaching_review,
        "reasoning_chain_review": reasoning_chain_review,
        "next_practice_plan": next_practice_plan,
        "teacher_note": teacher_note,
        "mistake_patterns": [pattern["pattern_id"] for pattern in reasoning_patterns[:8]] or missed_items[:8],
        "reasoning_trace_summary": reasoning_trace_summary,
        "teacher_feedback": teacher_feedback,
        "next_focus": next_focus,
        "source_references": source_references,
        "source_reference_items": source_reference_items,
        "generated_by": "teacher_reflection_agent",
        "teaching_prompt_version": TEACHER_REFLECTION_PROMPT_VERSION,
        "safety_note": "本轮教师复盘仅用于 OSCE 教学训练，不改变病例事实、rubric、标准诊断或评分规则。",
    }
    if teacher_agent is None:
        return review
    return _apply_teacher_agent_analysis(
        review=review,
        teacher_agent=teacher_agent,
        report=report,
        case_id=case_id,
        case_title=case_title,
        score_text=score_text,
        missed_items=missed_items,
        missed_labels=missed_labels,
        covered_labels=covered_labels,
        pending_labels=pending_labels,
        reasoning_trace_summary=reasoning_trace_summary,
        source_reference_items=source_reference_items,
        teacher_longitudinal_context=teacher_longitudinal_context or {},
    )


def _apply_teacher_agent_analysis(
    *,
    review: dict[str, Any],
    teacher_agent: Any,
    report: dict[str, Any],
    case_id: str,
    case_title: str,
    score_text: str,
    missed_items: list[str],
    missed_labels: list[str],
    covered_labels: list[str],
    pending_labels: list[str],
    reasoning_trace_summary: dict[str, Any],
    source_reference_items: list[dict[str, Any]],
    teacher_longitudinal_context: dict[str, Any],
) -> dict[str, Any]:
    request = TeacherAnalysisRequest(
        case_id=case_id,
        case_title=case_title,
        score_text=score_text,
        missed_items=missed_items,
        missed_labels=missed_labels,
        covered_labels=covered_labels,
        pending_labels=pending_labels,
        student_submission=_dict(report.get("final_submission")),
        clinical_reasoning_trace=_dict(report.get("clinical_reasoning_trace")),
        reasoning_trace_summary=reasoning_trace_summary,
        base_reflection=_teacher_agent_base_reflection(review),
        source_reference_items=source_reference_items,
        longitudinal_context=teacher_longitudinal_context,
    )
    try:
        analysis = normalize_teacher_analysis_response(teacher_agent(request))
    except Exception as exc:
        warnings = list(review.get("generation_warnings", []))
        warnings.append(
            {
                "module": "teacher_agent_analysis",
                "error_type": type(exc).__name__,
                "message": str(exc)[:240],
            }
        )
        fallback_analysis = DeterministicTeacherAgent()(request)
        fallback_payload = fallback_analysis.model_dump()
        fallback_context = _teacher_analysis_context_from_response(
            fallback_payload,
            teacher_longitudinal_context=teacher_longitudinal_context,
        )
        return {
            **review,
            "generated_by": fallback_analysis.agent_id,
            "teacher_analysis_context": fallback_context,
            "generation_warnings": warnings,
        }
    analysis_payload = analysis.model_dump()
    if (
        analysis.agent_id != "teacher_agent_deterministic"
        and analysis.analysis_mode != "deterministic_baseline"
    ):
        analysis_payload = _backfill_teacher_analysis_payload(
            analysis_payload,
            request=request,
        )
    analysis_context = _teacher_analysis_context_from_response(
        analysis_payload,
        teacher_longitudinal_context=teacher_longitudinal_context,
    )
    if analysis.agent_id == "teacher_agent_deterministic" or analysis.analysis_mode == "deterministic_baseline":
        return {
            **review,
            "generated_by": analysis.agent_id,
            "teacher_analysis_context": analysis_context,
        }
    return _merge_teacher_agent_analysis(
        review,
        analysis_payload,
        teacher_analysis_context=analysis_context,
    )


def _backfill_teacher_analysis_payload(
    analysis: dict[str, Any],
    *,
    request: TeacherAnalysisRequest,
) -> dict[str, Any]:
    enriched = deepcopy(analysis)
    deterministic = DeterministicTeacherAgent()(request).model_dump()
    for field_name in (
        "analysis_summary",
        "student_thinking_hypothesis",
        "clinical_thinking_profile",
        "skill_memory_focus",
    ):
        if not _has_meaningful_teacher_value(enriched.get(field_name)):
            enriched[field_name] = deepcopy(deterministic.get(field_name))

    profile = deepcopy(_dict(enriched.get("clinical_thinking_profile")))
    existing_longitudinal_assessment = profile.get("longitudinal_gap_assessment")
    if (
        not isinstance(existing_longitudinal_assessment, str)
        or not existing_longitudinal_assessment.strip()
    ):
        deterministic_profile = _dict(deterministic.get("clinical_thinking_profile"))
        longitudinal_assessment = str(
            deterministic_profile.get("longitudinal_gap_assessment") or ""
        ).strip()
        if not longitudinal_assessment:
            longitudinal_assessment = (
                "最近训练窗口内未识别到连续出现、改善后再现或上轮暂未再现的问题。"
                if request.longitudinal_context
                else "当前缺少可比较的历史报告，暂不能判断问题是否恢复或复发。"
            )
        profile["longitudinal_gap_assessment"] = longitudinal_assessment
    enriched["clinical_thinking_profile"] = profile
    return enriched


def _teacher_agent_base_reflection(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": review.get("summary", ""),
        "overall_comment": review.get("overall_comment", ""),
        "major_issues": review.get("major_issues", []),
        "teacher_coaching_review": review.get("teacher_coaching_review", []),
        "reasoning_chain_review": review.get("reasoning_chain_review", ""),
        "next_practice_plan": review.get("next_practice_plan", []),
        "teacher_feedback": review.get("teacher_feedback", ""),
        "next_focus": review.get("next_focus", ""),
        "reasoning_trace_summary": review.get("reasoning_trace_summary", {}),
    }


def _merge_teacher_agent_analysis(
    review: dict[str, Any],
    analysis: dict[str, Any],
    *,
    teacher_analysis_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(review)
    for field in [
        "overall_comment",
        "major_issues",
        "teacher_coaching_review",
        "reasoning_chain_review",
        "next_practice_plan",
        "teacher_note",
    ]:
        value = analysis.get(field)
        if _has_meaningful_teacher_value(value):
            merged[field] = value
    analysis_summary = str(analysis.get("analysis_summary") or "").strip()
    if analysis_summary:
        merged["teacher_feedback"] = analysis_summary
    next_plan = analysis.get("next_practice_plan")
    if isinstance(next_plan, list) and next_plan:
        merged["next_focus"] = str(next_plan[0])
    merged["generated_by"] = str(analysis.get("agent_id") or "teacher_agent")
    merged["teacher_analysis_context"] = (
        teacher_analysis_context
        if teacher_analysis_context is not None
        else _teacher_analysis_context_from_response(analysis)
    )
    return merged


def _teacher_analysis_context_from_response(
    analysis: dict[str, Any],
    *,
    teacher_longitudinal_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    major_issues = analysis.get("major_issues")
    major_issue_titles = [
        str(issue.get("title"))
        for issue in major_issues
        if isinstance(issue, dict) and str(issue.get("title") or "").strip()
    ] if isinstance(major_issues, list) else []
    context = {
        "agent_id": str(analysis.get("agent_id") or "teacher_agent"),
        "analysis_mode": str(analysis.get("analysis_mode") or "post_session_teacher_analysis"),
        "analysis_summary": str(analysis.get("analysis_summary") or "").strip(),
        "student_thinking_hypothesis": str(analysis.get("student_thinking_hypothesis") or "").strip(),
        "clinical_thinking_profile": _dict(analysis.get("clinical_thinking_profile")),
        "major_issue_titles": major_issue_titles[:6],
        "skill_memory_focus": _dict(analysis.get("skill_memory_focus")),
        "source_anchor_labels": _normalized_string_list(analysis.get("source_anchor_labels"))[:8],
        "teaching_prompt_version": TEACHER_REFLECTION_PROMPT_VERSION,
    }
    if teacher_longitudinal_context:
        context["longitudinal_context"] = deepcopy(teacher_longitudinal_context)
    return context


def _teacher_analysis_context_for_skill(reflection: dict[str, Any]) -> dict[str, Any]:
    context = reflection.get("teacher_analysis_context")
    if not isinstance(context, dict):
        return {}
    # The three-report teaching window helps TeacherAgent interpret this review,
    # but it is not source material for a new persistent Skill. Keeping it out of
    # the candidate avoids copying historical report summaries into later skills.
    return {
        key: deepcopy(value)
        for key, value in context.items()
        if key != "longitudinal_context"
    }


def _has_meaningful_teacher_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, dict):
        return bool(value)
    return value is not None


def _build_overall_teacher_comment(
    *,
    case_title: str,
    score_text: str,
    missed_items: list[str],
    major_issues: list[dict[str, Any]],
) -> str:
    if missed_items:
        issue_titles = [str(issue.get("title", "")) for issue in major_issues[:2] if issue.get("title")]
        issue_text = _compact_list_text(issue_titles, limit=2, fallback="证据采集和推理表达")
        return (
            f"这次「{case_title}」得到 {score_text}。你已经进入主要诊断方向，但证据链还没有闭合，"
            f"核心问题集中在{issue_text}。"
        )
    return (
        f"这次「{case_title}」得到 {score_text}。核心证据链比较完整，后续重点是把支持依据、"
        "排除依据和仍需验证的问题表达得更清楚。"
    )


def _build_strengths_review(report: dict[str, Any], covered_labels: list[str]) -> list[str]:
    strengths = [str(item).strip() for item in report.get("strengths", []) if str(item).strip()]
    if strengths:
        return strengths[:3]
    if covered_labels:
        return [f"你已经覆盖了{_compact_list_text(covered_labels, limit=3, fallback='部分关键线索')}，说明问诊或检查方向已有基础。"]
    return ["你完成了病例训练并提交了诊断，后续可以在证据链组织上继续提升。"]


def _build_teacher_major_issues(
    *,
    report: dict[str, Any],
    case: Case | None,
    case_id: str,
    missed_items: list[str],
    missed_labels: list[str],
    pending_labels: list[str],
    reasoning_patterns: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    reasoning_issues = _teacher_major_issues_from_reasoning_patterns(
        reasoning_patterns or [],
        case=case,
        case_id=case_id,
    )
    if reasoning_issues:
        return reasoning_issues[:4]

    grouped_items = _group_teacher_issue_items(missed_items, missed_labels, case_id)
    pending_by_group = _coverage_map_labels_by_group(report, "pending", limit_per_group=4, case=case)
    issues: list[dict[str, Any]] = []
    for group in ISSUE_GROUP_PRIORITY:
        linked_items = [*grouped_items.get(group, []), *pending_by_group.get(group, [])]
        linked_items = _dedupe_texts(linked_items)[:6]
        if not linked_items:
            continue
        definition = _teacher_issue_definition(group, linked_items)
        issues.append(
            {
                "title": definition["title"],
                "observed_behavior": f"{definition['observed']} 本轮相关训练点包括：{_compact_list_text(linked_items, limit=4, fallback='关键训练点')}。",
                "why_it_matters": definition["why"],
                "correct_approach": definition["correct"],
                "next_action": definition["next"],
                "linked_items": linked_items,
            }
        )
        if len(issues) >= 4:
            break
    if issues:
        return issues
    return [
        {
            "title": "证据表达还可以继续精炼",
            "observed_behavior": "本轮关键采集较完整，主要提升点是把已获得信息整理成更清楚的支持与排除依据。",
            "why_it_matters": ISSUE_GROUP_DEFINITIONS["reasoning"]["why"],
            "correct_approach": ISSUE_GROUP_DEFINITIONS["reasoning"]["correct"],
            "next_action": ISSUE_GROUP_DEFINITIONS["reasoning"]["next"],
            "linked_items": [],
        }
    ]


def _teacher_major_issues_from_reasoning_patterns(
    reasoning_patterns: list[dict[str, Any]],
    *,
    case: Case | None,
    case_id: str,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for pattern in reasoning_patterns[:4]:
        label = str(pattern.get("label") or pattern.get("pattern_id") or "").strip()
        if not label:
            continue
        linked_items = _reasoning_pattern_linked_labels(pattern, case=case, case_id=case_id)
        evidence = str(pattern.get("evidence") or "").strip()
        why = str(pattern.get("why_it_matters") or "").strip()
        remediation = str(pattern.get("remediation") or "").strip()
        issues.append(
            {
                "title": label,
                "observed_behavior": evidence or f"本轮训练暴露出“{label}”这一临床思维问题。",
                "why_it_matters": why or "该问题会影响病史、查体、检查和诊断表达之间的证据链闭合。",
                "correct_approach": remediation or "先形成结构化问题表征，再用查体、检查和鉴别排除逐步验证诊断假设。",
                "next_action": remediation or "下一轮提交诊断前，先整理支持依据、排除依据和仍需验证的问题。",
                "linked_items": linked_items,
            }
        )
    return issues


def _teacher_issue_definition(group: str, linked_items: list[str]) -> dict[str, str]:
    definition = dict(ISSUE_GROUP_DEFINITIONS[group])
    focus = _compact_list_text(linked_items, limit=4, fallback="本病例的关键训练点")
    if group == "history":
        definition["correct"] = (
            f"先用开放式问题确认主诉和病程，再依次完成：{focus}；"
            "按起病与演变、核心症状、伴随与阴性信息整理。"
        )
        definition["next"] = f"下一轮先完成：{focus}；用一句话概括后再进入查体或检查申请。"
    elif group == "physical_exam":
        definition["correct"] = f"围绕当前诊断假设完成以下查体：{focus}；并说明每项结果支持或反驳什么。"
        definition["next"] = f"下一轮在申请辅助检查前，先完成以下查体：{focus}；再根据结果调整假设。"
    elif group == "auxiliary_test":
        definition["correct"] = f"根据病史和查体结果选择以下辅助检查：{focus}；逐项说明要验证或排除什么。"
        definition["next"] = f"下一轮选择以下辅助检查：{focus}；每项都补一句它支持或排除哪个假设。"
    elif linked_items:
        definition["correct"] = f"围绕{focus}，按“支持依据、反证/排除依据、仍需验证的问题”组织诊断推理。"
        definition["next"] = f"下一轮提交诊断前，先用{focus}整理至少两条支持依据和一条排除依据。"
    return definition


def _reasoning_pattern_linked_labels(
    pattern: dict[str, Any],
    *,
    case: Case | None,
    case_id: str,
) -> list[str]:
    item_ids = [
        *(_normalized_string_list(pattern.get("trigger_item_ids"))),
        *(_normalized_string_list(pattern.get("source_signal_ids"))),
    ]
    labels: list[str] = []
    for item_id in item_ids:
        if not item_id or item_id.startswith("event:") or item_id.startswith("sequence:"):
            continue
        label = _case_training_point_label(case, item_id) if case is not None else ""
        if not label and "." not in item_id and ":" not in item_id:
            label = rubric_item_labels([item_id], [case_id])[0] if case_id else item_id
        if label and label not in labels:
            labels.append(label)
    return labels[:6]


def _group_teacher_issue_items(missed_items: list[str], missed_labels: list[str], case_id: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {group: [] for group in ISSUE_GROUP_PRIORITY}
    for index, item_id in enumerate(missed_items[:8]):
        label = missed_labels[index] if index < len(missed_labels) and missed_labels[index] else item_id
        group = _teacher_issue_group_for_item(item_id)
        if label not in grouped[group]:
            grouped[group].append(label)
    return grouped


def _teacher_issue_group_for_item(item_id: str) -> str:
    normalized = item_id.lower()
    if normalized.startswith(("ht_", "history", "hf_")):
        return "history"
    if normalized.startswith(("pe_", "exam", "physical")):
        return "physical_exam"
    if normalized.startswith(("ax_", "at_", "lab", "image", "test")):
        return "auxiliary_test"
    if normalized.startswith(("rs_", "dxd_", "dx_", "diagnosis", "reasoning")):
        return "reasoning"
    if "exam" in normalized or "rebound" in normalized or "tender" in normalized:
        return "physical_exam"
    if "test" in normalized or "cbc" in normalized or "crp" in normalized or "urine" in normalized:
        return "auxiliary_test"
    return "reasoning"


def _coverage_map_labels_by_group(
    report: dict[str, Any],
    status: str,
    *,
    limit_per_group: int,
    case: Case | None = None,
) -> dict[str, list[str]]:
    snapshot = report.get("training_progress_snapshot")
    coverage_map = snapshot.get("coverage_map") if isinstance(snapshot, dict) else None
    if not isinstance(coverage_map, dict):
        return {}
    group_map = {
        "history": "history",
        "physical_exam": "physical_exam",
        "auxiliary_test": "auxiliary_test",
        "reasoning": "reasoning",
    }
    result: dict[str, list[str]] = {}
    for coverage_group, issue_group in group_map.items():
        items = coverage_map.get(coverage_group, [])
        if not isinstance(items, list):
            continue
        labels: list[str] = []
        for item in items:
            if not isinstance(item, dict) or item.get("status") != status:
                continue
            label = _teacher_training_point_label(item, case)
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= limit_per_group:
                break
        if labels:
            result[issue_group] = labels
    return result


def _build_reasoning_chain_review(
    *,
    case_title: str,
    major_issues: list[dict[str, Any]],
    reasoning_trace_summary: dict[str, Any] | None = None,
) -> str:
    reasoning_trace_summary = reasoning_trace_summary or {}
    issue_titles = [str(issue.get("title", "")) for issue in major_issues[:3] if issue.get("title")]
    sequence_flags = [
        flag for flag in reasoning_trace_summary.get("sequence_flags", []) if isinstance(flag, dict)
    ][:2]
    breakpoints = [
        breakpoint
        for breakpoint in reasoning_trace_summary.get("evidence_chain_breakpoints", [])
        if isinstance(breakpoint, dict)
    ][:3]
    sequence_text = ""
    if sequence_flags:
        sequence_labels = _compact_sentence_list_text(
            [str(flag.get("label") or flag.get("flag_id") or "") for flag in sequence_flags],
            limit=2,
            fallback="推理顺序问题",
        )
        sequence_text = f"顺序上先修正：{sequence_labels}。"
    breakpoint_text = ""
    if breakpoints:
        breakpoint_statements: list[str] = []
        missing_focus: list[str] = []
        for breakpoint in breakpoints:
            statement = _sentence_fragment(breakpoint.get("statement") or breakpoint.get("breakpoint_id") or "证据链")
            if statement:
                breakpoint_statements.append(statement)
            missing_focus.extend(_normalized_string_list(breakpoint.get("missing_evidence_labels")))
        breakpoint_text = (
            f"证据链先补：{_compact_sentence_list_text(missing_focus, limit=4, fallback='关键证据')}；"
            f"断点包括：{_compact_sentence_list_text(breakpoint_statements, limit=2, fallback='关键推理点')}。"
        )
    if issue_titles:
        return (
            f"围绕「{case_title}」，更合理的路径是先补全病史时间线，再用查体验证局部体征，"
            "最后用检查支持或排除诊断。"
            f"{sequence_text}{breakpoint_text}"
            f"本轮优先修正：{_compact_sentence_list_text(issue_titles, limit=3, fallback='证据链闭合')}。"
        )
    if sequence_text or breakpoint_text:
        return (
            f"围绕「{case_title}」，下一轮要把每一步都连接到诊断假设：先问清病史，再查体验证，"
            f"最后用检查补强或排除。{sequence_text}{breakpoint_text}"
        )
    return (
        f"围绕「{case_title}」，你已经完成主要证据链。下一步要练习把证据按支持、反证和未确定问题三类表达出来。"
    )


def _build_next_practice_plan(major_issues: list[dict[str, Any]], pending_labels: list[str]) -> list[str]:
    plan = [str(issue.get("next_action", "")).strip() for issue in major_issues if str(issue.get("next_action", "")).strip()]
    plan = _dedupe_texts(plan)
    if pending_labels:
        plan.insert(0, f"先补齐{_compact_list_text(pending_labels, limit=3, fallback='未覆盖关键线索')}。")
    if not plan:
        plan = ["下一轮先整理支持依据、排除依据和仍需验证的问题，再提交诊断。"]
    return plan[:3]


def _build_teacher_coaching_review(
    *,
    case_title: str,
    major_issues: list[dict[str, Any]],
    reasoning_chain_review: str,
    next_practice_plan: list[str],
    reasoning_trace_summary: dict[str, Any],
    pending_labels: list[str],
) -> list[dict[str, Any]]:
    issue_titles = [str(issue.get("title", "")).strip() for issue in major_issues if str(issue.get("title", "")).strip()]
    linked_labels = _dedupe_texts(
        [
            label
            for issue in major_issues
            for label in _normalized_string_list(issue.get("linked_items"))
        ]
    )
    pending_focus = _compact_list_text(pending_labels or linked_labels, limit=3, fallback="本轮未闭合的关键线索")
    sequence_flags = [
        flag for flag in reasoning_trace_summary.get("sequence_flags", []) if isinstance(flag, dict)
    ]
    sequence_labels = _dedupe_texts(
        [_sentence_fragment(flag.get("label") or flag.get("flag_id") or "") for flag in sequence_flags]
    )
    sequence_evidence = _compact_sentence_list_text(
        [str(flag.get("evidence") or "").strip() for flag in sequence_flags],
        limit=2,
        fallback="本轮没有记录明显顺序跳步",
    )
    breakpoints = [
        breakpoint
        for breakpoint in reasoning_trace_summary.get("evidence_chain_breakpoints", [])
        if isinstance(breakpoint, dict)
    ]
    breakpoint_labels = _dedupe_texts(
        [
            label
            for breakpoint in breakpoints
            for label in _normalized_string_list(breakpoint.get("missing_evidence_labels"))
        ]
    )
    breakpoint_statements = _dedupe_texts(
        [_sentence_fragment(breakpoint.get("statement") or breakpoint.get("breakpoint_id") or "") for breakpoint in breakpoints]
    )
    breakpoint_actions = _dedupe_texts(
        [_sentence_fragment(breakpoint.get("teacher_action") or "") for breakpoint in breakpoints]
    )
    next_moves = next_practice_plan or ["下一轮按病史、查体、检查、鉴别和证据表达的顺序完整演练一次。"]
    next_move_fragments = _dedupe_texts([_next_round_action_fragment(move) for move in next_moves])
    first_sequence_evidence = sequence_evidence if sequence_flags else "本轮没有记录明显顺序跳步"
    first_breakpoint_action = (
        f"证据链先补：{_compact_sentence_list_text(breakpoint_labels, limit=3, fallback=pending_focus)}，再说明它们支持或排除哪个假设。"
        if breakpoint_labels
        else f"下一轮优先补{pending_focus}，再进入最终诊断表达。"
    )
    concise_reasoning_chain_review = _short_teacher_text(
        reasoning_chain_review,
        fallback=(
            f"本轮要把已收集线索分成支持依据、排除依据和仍需验证的问题。"
            f"优先处理{_compact_sentence_list_text(issue_titles, limit=2, fallback='证据链闭合')}。"
        ),
        max_chars=210,
    )

    return [
        {
            "section_id": "case_framing",
            "title": "病例表征",
            "teacher_comment": (
                f"先把「{case_title}」压缩成一句临床问题，而不是急着跳到答案。"
                f"本轮最需要抓住的是{_compact_list_text(issue_titles, limit=2, fallback='问题表征和证据链闭合')}。"
            ),
            "why_it_matters": "病例表征决定后续问什么、查什么、用什么证据验证；表征不清，后面的检查会变成散点操作。",
            "next_move": f"下一轮开局先用一句话说清主诉、时间线、关键阳性/阴性信息，再决定下一步。",
            "evidence_labels": linked_labels[:4],
        },
        {
            "section_id": "hypothesis_path",
            "title": "假设形成路径",
            "teacher_comment": (
                f"形成假设前先看顺序。本轮顺序问题："
                f"{_compact_sentence_list_text(sequence_labels, limit=2, fallback='未见明显顺序跳步')}。"
                f"依据：{first_sequence_evidence}。"
            ),
            "why_it_matters": "临床思维不是先列检查单，而是用病史形成初步假设，再让查体和检查服务于验证或排除。",
            "next_move": "下一轮先提出可验证的诊断假设，再说明你准备通过哪一个查体或检查去验证它。",
            "evidence_labels": sequence_labels[:4],
        },
        {
            "section_id": "verification_path",
            "title": "验证路径",
            "teacher_comment": (
                f"本轮证据链断点：{_compact_sentence_list_text(breakpoint_statements, limit=2, fallback='关键推理点')}。"
                f"还缺：{_compact_sentence_list_text(breakpoint_labels, limit=4, fallback=pending_focus)}。"
            ),
            "why_it_matters": "验证路径要回答“这个证据支持什么、缺了它会让哪个判断不稳”，这样诊断推理才不是凭印象跳跃。",
            "next_move": first_breakpoint_action,
            "evidence_labels": breakpoint_labels[:6],
        },
        {
            "section_id": "differential_reasoning",
            "title": "鉴别诊断",
            "teacher_comment": (
                "提交诊断时不要只写最可能答案，还要说明为什么其他可能暂不支持。"
                f"本轮可以把{pending_focus}转成支持或排除依据。"
            ),
            "why_it_matters": "鉴别诊断训练的是排除路径；没有排除依据，即使主诊断方向正确，也难以说明推理可靠。",
            "next_move": "下一轮至少写出一个需要排除的诊断，并给出对应的阴性病史、查体或检查证据。",
            "evidence_labels": pending_labels[:4],
        },
        {
            "section_id": "evidence_synthesis",
            "title": "证据整合",
            "teacher_comment": concise_reasoning_chain_review,
            "why_it_matters": "证据整合要把零散线索组织成支持、反证和未确定三类，让别人能复查你的推理链。",
            "next_move": "下一轮提交前，用“支持依据、排除依据、仍需验证”三栏整理一次。",
            "evidence_labels": linked_labels[:6],
        },
        {
            "section_id": "next_drill_script",
            "title": "下一轮演练脚本",
            "teacher_comment": "把复盘落到动作上：下一轮不要只记住漏项名称，而要把每一步都连到诊断假设。",
            "why_it_matters": "可重复的训练脚本能把一次报告里的问题转成下一次会话中的行为变化。",
            "next_move": "下一轮：" + "；".join(next_move_fragments[:3]) + "。",
            "evidence_labels": _dedupe_texts([*pending_labels[:4], *linked_labels[:4]]),
        },
    ]


def _teacher_reasoning_trace_summary(report: dict[str, Any]) -> dict[str, Any]:
    trace = report.get("clinical_reasoning_trace")
    if not isinstance(trace, dict):
        return {
            "trace_version": "",
            "dominant_patterns": [],
            "problem_representation_status": "",
            "illness_script_status": "",
            "evidence_synthesis_status": "",
            "sequence_flags": [],
            "action_order_summary": {},
            "evidence_chain_breakpoints": [],
            "evidence_chain_focus": [],
        }
    patterns = _reasoning_patterns_from_report(report)
    sequence_flags = sequence_flags_from_report(report)
    action_order_summary = action_order_summary_from_report(report)
    evidence_chain_breakpoints = evidence_chain_breakpoints_from_report(report)
    return {
        "trace_version": str(trace.get("trace_version") or ""),
        "dominant_patterns": [
            {
                "pattern_id": str(pattern.get("pattern_id") or ""),
                "label": str(pattern.get("label") or ""),
                "category": str(pattern.get("category") or ""),
                "severity": str(pattern.get("severity") or ""),
            }
            for pattern in patterns[:5]
        ],
        "problem_representation_status": str(
            (trace.get("problem_representation") or {}).get("status")
            if isinstance(trace.get("problem_representation"), dict)
            else ""
        ),
        "illness_script_status": str(
            (trace.get("illness_script_alignment") or {}).get("status")
            if isinstance(trace.get("illness_script_alignment"), dict)
            else ""
        ),
        "evidence_synthesis_status": str(
            (trace.get("evidence_synthesis") or {}).get("status")
            if isinstance(trace.get("evidence_synthesis"), dict)
            else ""
        ),
        "sequence_flags": sequence_flags,
        "action_order_summary": action_order_summary,
        "evidence_chain_breakpoints": evidence_chain_breakpoints[:5],
        "evidence_chain_focus": [
            {
                "breakpoint_id": str(breakpoint.get("breakpoint_id") or ""),
                "statement": str(breakpoint.get("statement") or ""),
                "missing_evidence_labels": _normalized_string_list(breakpoint.get("missing_evidence_labels"))[:6],
                "teacher_action": str(breakpoint.get("teacher_action") or ""),
            }
            for breakpoint in evidence_chain_breakpoints[:3]
        ],
    }


def _dedupe_texts(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        normalized = str(item).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _sentence_fragment(value: Any) -> str:
    normalized = str(value).strip()
    if not normalized:
        return ""
    return normalized.rstrip(" \t\r\n。；;，,、.")


def _next_round_action_fragment(value: Any) -> str:
    normalized = _sentence_fragment(value)
    if normalized.startswith("下一轮先"):
        return "先" + normalized.removeprefix("下一轮先")
    if normalized.startswith("下一轮要"):
        return "要" + normalized.removeprefix("下一轮要")
    if normalized.startswith("下一轮请"):
        return "请" + normalized.removeprefix("下一轮请")
    if normalized.startswith("下一轮"):
        return normalized.removeprefix("下一轮").lstrip("：:，, ")
    return normalized


def _compact_sentence_list_text(items: list[str], *, limit: int, fallback: str) -> str:
    return _compact_list_text([_sentence_fragment(item) for item in items], limit=limit, fallback=fallback)


def _short_teacher_text(value: str, *, fallback: str, max_chars: int) -> str:
    normalized = str(value).strip()
    if not normalized:
        return fallback
    if len(normalized) <= max_chars:
        return normalized
    first_sentence = normalized.split("。", 1)[0].strip()
    if 24 <= len(first_sentence) <= max_chars:
        return f"{first_sentence}。"
    return f"{normalized[: max_chars - 1].rstrip('，,；;、 ')}。"


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw_item).strip() for raw_item in value) if item]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coverage_map_labels(report: dict[str, Any], status: str, *, limit: int, case: Case | None = None) -> list[str]:
    snapshot = report.get("training_progress_snapshot")
    coverage_map = snapshot.get("coverage_map") if isinstance(snapshot, dict) else None
    if not isinstance(coverage_map, dict):
        return []

    labels: list[str] = []
    for group in ["history", "physical_exam", "auxiliary_test", "reasoning"]:
        items = coverage_map.get(group, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or item.get("status") != status:
                continue
            label = _teacher_training_point_label(item, case)
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= limit:
                return labels
    return labels


def _teacher_training_point_label(item: dict[str, Any], case: Case | None) -> str:
    item_id = str(item.get("id", "")).strip()
    if case and item_id:
        label = _case_training_point_label(case, item_id)
        if label:
            return label
    raw_label = str(item.get("label", "")).strip()
    return _strip_answer_value_from_label(raw_label)


def _case_training_point_label(case: Case, item_id: str) -> str:
    full_item_id = item_id if item_id.startswith(f"{case.case_id}.") else f"{case.case_id}.{item_id}"
    for fact in case.history.hidden_facts:
        if item_id in {fact.fact_id, fact.fact_id.removeprefix(f"{case.case_id}.")} or full_item_id == fact.fact_id:
            if fact.linked_rubric_items:
                linked_labels = rubric_item_labels(fact.linked_rubric_items[:1], [case.case_id])
                label = linked_labels[0] if linked_labels else ""
                if label:
                    return label
            if fact.slot:
                return HISTORY_SLOT_TRAINING_LABELS.get(str(fact.slot), f"追问{fact.topic}")
            return f"追问{fact.topic}"
    for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]:
        if item_id == exam.exam_code:
            if exam.linked_rubric_items:
                linked_labels = rubric_item_labels(exam.linked_rubric_items[:1], [case.case_id])
                label = linked_labels[0] if linked_labels else ""
                if label:
                    return label
            return exam.exam_name_cn
    for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]:
        if item_id == test.test_code:
            if test.linked_rubric_items:
                linked_labels = rubric_item_labels(test.linked_rubric_items[:1], [case.case_id])
                label = linked_labels[0] if linked_labels else ""
                if label:
                    return label
            return test.test_name_cn
    for reasoning_point in case.diagnosis.reasoning_points:
        if item_id in {reasoning_point.point_id, reasoning_point.point_id.removeprefix(f"{case.case_id}.")}:
            return reasoning_point.statement
    return ""


def _strip_answer_value_from_label(label: str) -> str:
    normalized = str(label).strip()
    if not normalized:
        return ""
    for delimiter in ("：", ":"):
        if delimiter not in normalized:
            continue
        prefix = normalized.split(delimiter, 1)[0].strip(" 。，；;")
        if 1 <= len(prefix) <= 32:
            return prefix
    return normalized


def _compact_list_text(items: list[str], *, limit: int, fallback: str) -> str:
    clean_items: list[str] = []
    for item in items:
        normalized = str(item).strip()
        if normalized and normalized not in clean_items:
            clean_items.append(normalized)
    if not clean_items:
        return fallback
    selected_items = clean_items[:limit]
    suffix = f"等 {len(clean_items)} 项" if len(clean_items) > limit else ""
    return "、".join(selected_items) + suffix


def _score_text(report: dict[str, Any]) -> str:
    total_score = report.get("total_score")
    max_score = report.get("max_score")
    if isinstance(total_score, (int, float)) and isinstance(max_score, (int, float)) and max_score > 0:
        return f"{total_score:g}/{max_score:g} 分"
    if isinstance(total_score, (int, float)):
        return f"{total_score:g} 分"
    return "已生成评分"


def _append_personal_skill_events(
    *,
    candidate: dict[str, Any],
    review: dict[str, Any],
    event_store: TrainingEventStore,
    session: Any,
    skill_id: str | None,
) -> None:
    candidate_id = str(candidate["candidate_id"])
    review_revision = _personal_skill_review_revision(candidate, review)

    def append_event(
        *,
        session_id: str,
        case_id: str,
        student_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        event_store.append_event(
            session_id=session_id,
            case_id=case_id,
            student_id=student_id,
            event_type=event_type,
            event_key=f"personal-skill:{candidate_id}:{event_type}:{review_revision}",
            payload={
                **payload,
                "review_revision": review_revision,
            },
        )

    append_event(
        session_id=str(session.session_id),
        case_id=str(session.case_id),
        student_id=str(session.student_id),
        event_type="personal_training_skill_generated",
        payload={
            "candidate_id": candidate_id,
            "skill_id": skill_id,
            "review_status": review["status"],
            "scope": "personal",
            "web_check_status": candidate.get("web_check_status", "not_configured"),
        },
    )
    for event_type, payload in [
        (
            "personal_skill_candidate_generated",
            {
                "candidate_id": candidate["candidate_id"],
                "source_session_id": candidate["source_session_id"],
                "source_report_ids": list(candidate.get("source_report_ids", [])),
            },
        ),
        (
            "personal_skill_candidate_agent_reviewed",
            {
                "candidate_id": candidate["candidate_id"],
                "review_status": review["status"],
                "approval_dialogue": list(candidate.get("approval_dialogue", [])),
                "web_check_status": candidate.get("web_check_status", "not_configured"),
            },
        ),
    ]:
        append_event(
            session_id=candidate_id,
            case_id=str(candidate["trigger_item_id"]),
            student_id=AUTO_APPROVAL_AGENT_ID,
            event_type=event_type,
            payload=payload,
        )
    if review["status"] == "approved":
        if not skill_id:
            raise RuntimeError("个人训练 Skill 尚未启用，不能记录自动启用事件。")
        append_event(
            session_id=candidate_id,
            case_id=str(candidate["trigger_item_id"]),
            student_id=AUTO_APPROVAL_AGENT_ID,
            event_type="personal_skill_candidate_auto_enabled",
            payload={
                "candidate_id": candidate["candidate_id"],
                "skill_id": skill_id,
                "scope": "personal",
                "owner_student_id": candidate["owner_student_id"],
            },
        )


def _report_candidate_summary(
    candidate: dict[str, Any],
    *,
    enabled_skill: dict[str, Any] | None = None,
) -> dict[str, Any]:
    review = candidate.get("review", {})
    is_approved_and_enabled = review.get("status") == "approved" and enabled_skill is not None
    return {
        "status": "approved" if is_approved_and_enabled else review.get("status", candidate.get("status", "draft")),
        "candidate_id": candidate["candidate_id"],
        "skill_id": str(enabled_skill["skill_id"]) if is_approved_and_enabled else None,
        "title": candidate["title"],
        "description": candidate.get("description", ""),
        "suggested_strategy": candidate.get("suggested_strategy", ""),
        "scope": candidate.get("scope", "personal"),
        "owner_student_id": candidate.get("owner_student_id", ""),
        "source_session_id": candidate.get("source_session_id", ""),
        "source_report_ids": list(candidate.get("source_report_ids", [])),
        "trigger_item_ids": list(candidate.get("trigger_item_ids", [])),
        "reasoning_pattern_ids": list(candidate.get("reasoning_pattern_ids", [])),
        "reasoning_pattern_labels": list(candidate.get("reasoning_pattern_labels", [])),
        "source_trace_version": candidate.get("source_trace_version", ""),
        "review": review,
        "approval_agent_review": candidate.get("approval_agent_review", {}),
        "approval_dialogue": list(candidate.get("approval_dialogue", [])),
        "teacher_analysis_context": candidate.get("teacher_analysis_context", {}),
        "rag_evidence_items": list(candidate.get("rag_evidence_items", [])),
        "web_check_status": candidate.get("web_check_status", "not_configured"),
        "external_evidence_checks": list(candidate.get("external_evidence_checks", [])),
    }


def _validate_personal_candidate_ownership(candidate: dict[str, Any], session: Any) -> None:
    expected_session_id = str(session.session_id)
    expected_student_id = str(session.student_id)
    expected_candidate_id = _personal_candidate_id(expected_session_id)
    if (
        str(candidate.get("candidate_id", "")) != expected_candidate_id
        or str(candidate.get("scope", "")) != "personal"
        or str(candidate.get("source_session_id", "")) != expected_session_id
        or str(candidate.get("owner_student_id", "")) != expected_student_id
    ):
        raise RuntimeError("个人训练 Skill 候选与当前训练归属不一致。")
    case_ids = [str(case_id) for case_id in candidate.get("case_ids", []) if str(case_id)]
    if case_ids and str(session.case_id) not in case_ids:
        raise RuntimeError("个人训练 Skill 候选与当前病例不一致。")


def _ensure_personal_skill_enabled(
    *,
    candidate: dict[str, Any],
    skill_store: TrainingSkillStore,
    skill_id: str,
) -> dict[str, Any]:
    enabled_skill = skill_store.get_skill(skill_id)
    if not _is_matching_enabled_personal_skill(enabled_skill, candidate):
        if not skill_store.enable_candidate(candidate):
            raise RuntimeError("个人训练 Skill 启用失败。")
        enabled_skill = skill_store.get_skill(skill_id)
    if not _is_matching_enabled_personal_skill(enabled_skill, candidate):
        raise RuntimeError("个人训练 Skill 启用后未能读取到对应记录。")
    return enabled_skill


def _is_matching_enabled_personal_skill(
    skill: dict[str, Any] | None,
    candidate: dict[str, Any],
) -> bool:
    if skill is None:
        return False
    return (
        str(skill.get("status", "")) == "enabled"
        and str(skill.get("source_candidate_id", "")) == str(candidate["candidate_id"])
        and str(skill.get("scope", "")) == "personal"
        and str(skill.get("owner_student_id", "")) == str(candidate.get("owner_student_id", ""))
        and str(skill.get("source_session_id", "")) == str(candidate.get("source_session_id", ""))
    )


def _personal_skill_review_revision(
    candidate: dict[str, Any],
    review: dict[str, Any],
) -> str:
    revision_material = {
        "review": review,
        "approval_agent_review": candidate.get("approval_agent_review", {}),
        "approval_dialogue": candidate.get("approval_dialogue", []),
    }
    canonical_material = json.dumps(
        revision_material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"v1-{hashlib.sha256(canonical_material.encode('utf-8')).hexdigest()[:16]}"


def _personal_candidate_id(session_id: str) -> str:
    return f"personal_skill_candidate_{session_id}"


def _personal_skill_id(session_id: str) -> str:
    return f"skill_personal_{session_id}" if session_id else ""


personal_training_skill_service = PersonalTrainingSkillService()
