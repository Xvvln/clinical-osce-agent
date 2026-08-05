from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


STUDENT_TRAINING_REPORT_VERSION = "student_training_report_v2"

_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_INTERNAL_TOKEN_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
_SPACE_PATTERN = re.compile(r"\s+")

_STAGE_LABELS = {
    "history_taking": "问诊",
    "physical_exam": "查体",
    "auxiliary_test": "辅助检查",
    "diagnosis_submission": "诊断提交",
    "diagnostic_reasoning": "诊断推理",
    "reasoning": "诊断推理",
    "humanistic_communication": "人文沟通",
    "medical_ethics": "医学伦理",
    "relationship_building": "医患关系",
}

_CLASSIFICATION_LABELS = {
    "correct": "主诊断与病例目标一致",
    "plausible_differential": "提交内容更接近合理鉴别诊断，但尚未命中主要诊断",
    "partially_correct": "诊断方向部分接近病例目标，但表达或证据仍不完整",
    "incorrect": "主诊断与病例目标不一致",
    "unsupported": "现有证据不足以支持提交的诊断",
    "not_submitted": "本轮尚未提交诊断",
}


def _validate_student_text(value: str) -> str:
    normalized = _normalize_text(value)
    if not normalized:
        raise ValueError("student-facing text must not be empty")
    if _UUID_PATTERN.search(normalized) or _INTERNAL_TOKEN_PATTERN.search(normalized):
        raise ValueError("student-facing text contains an internal identifier")
    if normalized.isascii() and not any(character.isdigit() for character in normalized):
        raise ValueError("student-facing text must be readable Chinese")
    return normalized


class StudentReportOutcome(BaseModel):
    summary: str
    score_summary: str
    diagnosis_status: Literal[
        "correct",
        "plausible_differential",
        "partially_correct",
        "incorrect",
        "unsupported",
        "not_submitted",
    ]
    diagnosis_summary: str
    safety_summary: str
    communication_summary: str

    @field_validator(
        "summary",
        "score_summary",
        "diagnosis_summary",
        "safety_summary",
        "communication_summary",
    )
    @classmethod
    def _student_text_only(cls, value: str) -> str:
        return _validate_student_text(value)


class StudentDecisionReplay(BaseModel):
    replay_id: str
    kind: Literal["strength", "reasoning", "evidence", "sequence", "safety", "humanistic"]
    phase: str
    title: str
    observed_evidence: str
    teacher_judgement: str
    why_it_matters: str
    next_action: str
    evidence_labels: list[str] = Field(default_factory=list, max_length=6)

    @field_validator(
        "phase",
        "title",
        "observed_evidence",
        "teacher_judgement",
        "why_it_matters",
        "next_action",
    )
    @classmethod
    def _student_text_only(cls, value: str) -> str:
        return _validate_student_text(value)

    @field_validator("evidence_labels")
    @classmethod
    def _student_labels_only(cls, values: list[str]) -> list[str]:
        return [_validate_student_text(value) for value in values]


class StudentTrainingPrescription(BaseModel):
    goal_id: str
    title: str
    trigger: str
    action: str
    success_signal: str

    @field_validator("title", "trigger", "action", "success_signal")
    @classmethod
    def _student_text_only(cls, value: str) -> str:
        return _validate_student_text(value)


class StudentLongitudinalSummary(BaseModel):
    status: Literal["insufficient_history", "first_seen", "repeated", "reactivated", "improving"]
    label: str
    summary: str
    first_seen_count: int = Field(default=0, ge=0)
    repeated_count: int = Field(default=0, ge=0)
    reactivated_count: int = Field(default=0, ge=0)
    temporarily_absent_count: int = Field(default=0, ge=0)

    @field_validator("label", "summary")
    @classmethod
    def _student_text_only(cls, value: str) -> str:
        return _validate_student_text(value)


class StudentTrainingReportV2(BaseModel):
    version: Literal["student_training_report_v2"] = STUDENT_TRAINING_REPORT_VERSION
    status: Literal["generated", "legacy_fallback"] = "generated"
    outcome: StudentReportOutcome
    decision_replays: list[StudentDecisionReplay] = Field(default_factory=list, max_length=3)
    training_prescriptions: list[StudentTrainingPrescription] = Field(default_factory=list, max_length=3)
    longitudinal_summary: StudentLongitudinalSummary
    personal_memory_summary: str

    @field_validator("personal_memory_summary")
    @classmethod
    def _student_text_only(cls, value: str) -> str:
        return _validate_student_text(value)


def build_student_training_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Compose one student-facing teaching report from trusted report evidence.

    Deep analysis remains an internal evidence engine. This projection is the
    only contract the student report UI needs for interpretation and next-step
    coaching, so technical identifiers and duplicated prose do not leak into
    the learning experience.
    """

    deep_analysis = _mapping(report.get("deep_report_analysis"))
    teacher_review = _mapping(report.get("ai_reflection_review"))
    payload = StudentTrainingReportV2(
        status="generated" if str(deep_analysis.get("status") or "") == "generated" else "legacy_fallback",
        outcome=_build_outcome(report, deep_analysis),
        decision_replays=_build_decision_replays(report, deep_analysis, teacher_review),
        training_prescriptions=_build_training_prescriptions(report, deep_analysis, teacher_review),
        longitudinal_summary=_build_longitudinal_summary(teacher_review),
        personal_memory_summary=_build_personal_memory_summary(report, teacher_review),
    )
    return payload.model_dump()


def _build_outcome(report: Mapping[str, Any], deep_analysis: Mapping[str, Any]) -> StudentReportOutcome:
    overall = _mapping(deep_analysis.get("overall_evaluation"))
    diagnostic = _mapping(deep_analysis.get("diagnostic_contrast_analysis"))
    humanistic = _mapping(deep_analysis.get("humanistic_communication_analysis"))
    classification = str(diagnostic.get("classification") or "unsupported")
    if classification not in _CLASSIFICATION_LABELS:
        classification = "unsupported"
    submitted_diagnosis = _safe_student_text(diagnostic.get("submitted_diagnosis"), fallback="")
    target_diagnosis = _safe_student_text(diagnostic.get("target_diagnosis"), fallback="")
    diagnosis_parts = [_CLASSIFICATION_LABELS[classification]]
    if submitted_diagnosis:
        diagnosis_parts.append(f"本轮提交为“{submitted_diagnosis}”")
    if target_diagnosis and classification != "correct":
        diagnosis_parts.append(f"病例目标为“{target_diagnosis}”")
    diagnosis_summary = "；".join(diagnosis_parts) + "。"

    score_summary = _safe_student_text(
        overall.get("score_interpretation"),
        fallback=f"本轮总分 {_score_text(report.get('total_score'))}/100。",
    )
    overall_summary = _safe_student_text(
        overall.get("summary"),
        fallback="本轮已形成可复盘的训练记录，下面只保留最影响下一轮表现的关键判断。",
    )
    missed_opportunities = _object_list(humanistic.get("missed_opportunities"))
    safety_count = sum(
        1
        for item in missed_opportunities
        if any(token in str(item.get("gap_type") or "").lower() for token in ("ethic", "consent", "safety"))
    )
    communication_count = max(len(missed_opportunities) - safety_count, 0)
    safety_summary = (
        f"本轮记录到 {safety_count} 个知情同意或安全顺序问题，需要在下一轮优先修复。"
        if safety_count
        else "本轮未记录明确的知情同意或安全顺序越界。"
    )
    communication_summary = (
        f"本轮记录到 {communication_count} 个沟通机会未被及时回应。"
        if communication_count
        else "本轮未记录明确的人文沟通漏项，仍可结合评分明细继续复核。"
    )
    return StudentReportOutcome(
        summary=overall_summary,
        score_summary=score_summary,
        diagnosis_status=classification,
        diagnosis_summary=diagnosis_summary,
        safety_summary=safety_summary,
        communication_summary=communication_summary,
    )


def _build_decision_replays(
    report: Mapping[str, Any],
    deep_analysis: Mapping[str, Any],
    teacher_review: Mapping[str, Any],
) -> list[StudentDecisionReplay]:
    positive_candidates = _positive_replay_candidates(report)
    gap_candidates = [
        *_humanistic_replay_candidates(deep_analysis),
        *_teacher_issue_replay_candidates(teacher_review),
        *_evidence_breakpoint_replay_candidates(deep_analysis),
        *_sequence_replay_candidates(deep_analysis),
        *_training_gap_replay_candidates(report),
    ]
    gap_candidates = _deduplicate_candidates(gap_candidates)
    if gap_candidates and positive_candidates:
        selected = [positive_candidates[0], *gap_candidates[:2]]
    elif gap_candidates:
        selected = gap_candidates[:3]
    else:
        selected = positive_candidates[:3]
    if not selected:
        selected = [
            {
                "kind": "strength",
                "phase": "本轮训练",
                "title": "完成了一轮完整训练",
                "observed_evidence": "系统已保存本轮问诊、操作和诊断提交记录。",
                "teacher_judgement": "当前材料可以用于下一轮迁移练习，但暂不足以形成更细的优势判断。",
                "why_it_matters": "保留完整训练轨迹后，后续反馈才能准确对应到具体动作。",
                "next_action": "下一轮继续完成完整流程，并主动说明每一步将验证或排除什么。",
                "evidence_labels": ["完整训练记录"],
            }
        ]
    return [
        StudentDecisionReplay(
            replay_id=f"decision-{index + 1}",
            kind=candidate["kind"],
            phase=candidate["phase"],
            title=candidate["title"],
            observed_evidence=candidate["observed_evidence"],
            teacher_judgement=candidate["teacher_judgement"],
            why_it_matters=candidate["why_it_matters"],
            next_action=candidate["next_action"],
            evidence_labels=candidate.get("evidence_labels", []),
        )
        for index, candidate in enumerate(selected)
    ]


def _positive_replay_candidates(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rubric_scores = _mapping(report.get("rubric_scores"))
    candidates: list[tuple[float, float, dict[str, Any]]] = []
    for dimension_id, raw_items in _mapping(report.get("dimension_traces")).items():
        for item in _object_list(raw_items):
            score = _number(item.get("score", item.get("awarded_score")))
            max_score = _number(item.get("max_score"))
            if score <= 0 or max_score <= 0:
                continue
            item_id = str(item.get("item_id") or item.get("rubric_item_id") or "")
            rubric_item = _mapping(rubric_scores.get(item_id))
            label = _safe_student_text(item.get("label") or rubric_item.get("description"), fallback="已覆盖的训练动作")
            matched_evidence = _student_text_list(item.get("matched_evidence"), limit=3)
            observed = matched_evidence[0] if matched_evidence else f"本轮已经完成“{label}”对应的评分动作。"
            candidate = {
                "kind": "strength",
                "phase": _stage_label(str(item.get("stage") or dimension_id)),
                "title": label,
                "observed_evidence": observed,
                "teacher_judgement": f"你已经完成“{label}”，这是本轮应当保留的有效做法。",
                "why_it_matters": "这个动作让后续判断能够建立在已获得的训练证据上。",
                "next_action": "下一轮在新病例中再次独立完成，并说明它支持或排除哪一个假设。",
                "evidence_labels": matched_evidence or [label],
            }
            candidates.append((score / max_score, score, candidate))
    return [item[2] for item in sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)]


def _humanistic_replay_candidates(deep_analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    humanistic = _mapping(deep_analysis.get("humanistic_communication_analysis"))
    candidates: list[dict[str, Any]] = []
    for item in _object_list(humanistic.get("missed_opportunities")):
        gap_type = str(item.get("gap_type") or "").lower()
        is_safety = any(token in gap_type for token in ("ethic", "consent", "safety"))
        expected = _safe_student_text(item.get("expected_response"), fallback="应先回应患者当下需要，再继续医学任务。")
        action = _safe_student_text(item.get("next_training_action"), fallback=expected)
        candidates.append(
            {
                "kind": "safety" if is_safety else "humanistic",
                "phase": _stage_label(str(item.get("stage") or "humanistic_communication")),
                "title": "知情同意与安全顺序" if is_safety else "及时回应患者感受",
                "observed_evidence": _safe_student_text(
                    item.get("trigger_evidence"),
                    fallback="患者已经给出需要回应的情绪或沟通信号。",
                ),
                "teacher_judgement": "该时机没有得到充分回应，需要在下一轮优先修复。",
                "why_it_matters": expected,
                "next_action": action,
                "evidence_labels": [expected],
            }
        )
    return candidates


def _teacher_issue_replay_candidates(teacher_review: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for issue in _object_list(teacher_review.get("major_issues")):
        title = _safe_student_text(issue.get("title"), fallback="临床思维链尚未闭合")
        candidates.append(
            {
                "kind": "reasoning",
                "phase": "临床推理",
                "title": title,
                "observed_evidence": _safe_student_text(
                    issue.get("observed_behavior"),
                    fallback=f"本轮“{title}”对应的评分证据不足。",
                ),
                "teacher_judgement": _safe_student_text(
                    issue.get("correct_approach"),
                    fallback="需要把当前信息先组织成可验证的假设，再选择后续动作。",
                ),
                "why_it_matters": _safe_student_text(
                    issue.get("why_it_matters"),
                    fallback="如果推理步骤没有连接起来，即使诊断名称接近，也难以说明判断为什么成立。",
                ),
                "next_action": _safe_student_text(
                    issue.get("next_action"),
                    fallback="下一轮先说出主要假设，再说明每一步要验证或排除什么。",
                ),
                "evidence_labels": _student_text_list(issue.get("linked_items"), limit=4) or [title],
            }
        )
    return candidates


def _evidence_breakpoint_replay_candidates(deep_analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence = _mapping(deep_analysis.get("evidence_utilization_analysis"))
    candidates: list[dict[str, Any]] = []
    for item in _object_list(evidence.get("evidence_chain_breakpoints")):
        statement = _safe_student_text(item.get("statement"), fallback="本轮诊断证据链存在尚未补齐的环节。")
        missing_labels = _student_text_list(item.get("missing_evidence_labels"), limit=4)
        candidates.append(
            {
                "kind": "evidence",
                "phase": "证据整合",
                "title": "证据链在关键环节断开",
                "observed_evidence": statement,
                "teacher_judgement": "现有材料还不能完整说明当前诊断为什么成立、相近诊断为什么被排除。",
                "why_it_matters": "诊断结论只有同时连接支持证据、反证依据和待验证问题，才是完整的临床推理。",
                "next_action": _safe_student_text(
                    item.get("teacher_action"),
                    fallback="下一轮提交前检查支持依据、排除依据和仍需验证的问题是否齐全。",
                ),
                "evidence_labels": missing_labels or ["证据链断点"],
            }
        )
    return candidates


def _sequence_replay_candidates(deep_analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    process = _mapping(deep_analysis.get("process_strategy_analysis"))
    fallback_actions = _student_text_list(process.get("premature_or_delayed_actions"), limit=3)
    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(_object_list(process.get("sequence_flags"))):
        label = _safe_student_text(item.get("label"), fallback="关键动作顺序需要调整")
        candidates.append(
            {
                "kind": "sequence",
                "phase": "操作顺序",
                "title": label,
                "observed_evidence": _safe_student_text(
                    item.get("evidence"),
                    fallback=f"本轮出现“{label}”的顺序信号。",
                ),
                "teacher_judgement": "当前动作时机削弱了后续证据采集的针对性。",
                "why_it_matters": "先形成初步假设，再选择验证动作，能减少无目标的信息收集。",
                "next_action": fallback_actions[index] if index < len(fallback_actions) else "下一轮先明确假设，再开展关键查体和检查。",
                "evidence_labels": [label],
            }
        )
    return candidates


def _training_gap_replay_candidates(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for gap in sorted(
        _object_list(report.get("training_gaps")),
        key=lambda item: _number(item.get("missing_score")),
        reverse=True,
    ):
        label = _safe_student_text(gap.get("label"), fallback="本轮关键训练点尚未覆盖")
        candidates.append(
            {
                "kind": "evidence",
                "phase": _stage_label(str(gap.get("dimension_id") or gap.get("stage") or "诊断推理")),
                "title": label,
                "observed_evidence": _safe_student_text(
                    gap.get("evidence_summary"),
                    fallback=f"评分轨迹没有找到足够证据证明你完成了“{label}”。",
                ),
                "teacher_judgement": "该训练点目前还没有形成稳定、可观察的完成证据。",
                "why_it_matters": "评分依据关注可观察的问诊、操作和推理表达，不能只依赖最终结论。",
                "next_action": _safe_student_text(
                    gap.get("next_training_action"),
                    fallback=f"下一轮主动完成“{label}”，并说明该动作如何影响判断。",
                ),
                "evidence_labels": [label],
            }
        )
    return candidates


def _build_training_prescriptions(
    report: Mapping[str, Any],
    deep_analysis: Mapping[str, Any],
    teacher_review: Mapping[str, Any],
) -> list[StudentTrainingPrescription]:
    plan = _mapping(deep_analysis.get("next_training_plan"))
    evidence_analysis = _mapping(deep_analysis.get("evidence_utilization_analysis"))
    process_analysis = _mapping(deep_analysis.get("process_strategy_analysis"))
    has_structured_gap = bool(
        _object_list(report.get("training_gaps"))
        or _object_list(report.get("missed_opportunities"))
        or _object_list(evidence_analysis.get("evidence_chain_breakpoints"))
        or _object_list(process_analysis.get("sequence_flags"))
    )
    if not has_structured_gap:
        return [
            StudentTrainingPrescription(
                goal_id="goal-1",
                title="迁移本轮有效做法",
                trigger="进入下一个新病例时",
                action="独立完成问诊、关键查体、必要检查和诊断推理，并说明每一步的目的。",
                success_signal="在不依赖提示的情况下形成完整证据链，且不新增明显安全或沟通问题。",
            )
        ]
    raw_candidates: list[dict[str, str]] = []
    for item in _object_list(plan.get("top_goals")):
        raw_candidates.append(
            {
                "title": _safe_student_text(item.get("label"), fallback="补齐本轮优先训练点"),
                "trigger": _safe_student_text(item.get("trigger"), fallback=_stage_trigger(item.get("stage"))),
                "action": _safe_student_text(item.get("next_training_action"), fallback="完成该训练点并说明它与当前假设的关系。"),
                "success_signal": _safe_student_text(item.get("success_signal"), fallback="评分轨迹能够找到对应动作和说明。"),
            }
        )
    for item in _object_list(plan.get("stage_triggered_actions")):
        raw_candidates.append(
            {
                "title": _safe_student_text(item.get("action"), fallback="按阶段完成关键动作"),
                "trigger": _safe_student_text(item.get("trigger"), fallback=_stage_trigger(item.get("stage"))),
                "action": _safe_student_text(item.get("action"), fallback="完成当前阶段的关键训练动作。"),
                "success_signal": _safe_student_text(item.get("success_signal"), fallback="能够在进入下一阶段前独立完成。"),
            }
        )
    for gap in _object_list(report.get("training_gaps")):
        label = _safe_student_text(gap.get("label"), fallback="补齐关键训练点")
        raw_candidates.append(
            {
                "title": label,
                "trigger": _stage_trigger(gap.get("stage") or gap.get("dimension_id")),
                "action": _safe_student_text(gap.get("next_training_action"), fallback=f"完成“{label}”并说明为什么要做。"),
                "success_signal": f"报告能够找到“{label}”对应的动作或推理表达。",
            }
        )
    for action in _student_text_list(teacher_review.get("next_practice_plan"), limit=3):
        raw_candidates.append(
            {
                "title": "执行教师建议",
                "trigger": "下一轮遇到相似临床任务时",
                "action": action,
                "success_signal": "能够不依赖提示完成该动作，并说出它将验证或排除什么。",
            }
        )
    deduplicated: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in raw_candidates:
        identity = _semantic_identity(candidate["action"])
        if not identity or identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(candidate)
        if len(deduplicated) == 3:
            break
    if not deduplicated:
        deduplicated.append(
            {
                "title": "迁移本轮有效做法",
                "trigger": "进入下一个新病例时",
                "action": "独立完成问诊、关键查体、必要检查和诊断推理，并说明每一步的目的。",
                "success_signal": "在不依赖提示的情况下形成完整证据链，且不新增明显安全或沟通问题。",
            }
        )
    return [
        StudentTrainingPrescription(goal_id=f"goal-{index + 1}", **candidate)
        for index, candidate in enumerate(deduplicated)
    ]


def _build_longitudinal_summary(teacher_review: Mapping[str, Any]) -> StudentLongitudinalSummary:
    context = _mapping(teacher_review.get("teacher_analysis_context"))
    longitudinal = _mapping(context.get("longitudinal_context"))
    counts = _mapping(longitudinal.get("gap_status_counts"))
    first_seen = _count(counts.get("first_seen_current_window"))
    repeated = _count(counts.get("repeated"))
    reactivated = _count(counts.get("reactivated_after_improvement"))
    temporarily_absent = _count(counts.get("recovered_since_previous_report"))
    profile = _mapping(context.get("clinical_thinking_profile"))
    supplied_summary = _safe_student_text(profile.get("longitudinal_gap_assessment"), fallback="")
    if reactivated:
        status = "reactivated"
        label = "改善后再次出现"
        fallback = f"最近训练中有 {reactivated} 个问题在暂时未出现后再次出现，需要优先恢复训练。"
    elif repeated:
        status = "repeated"
        label = "连续出现"
        fallback = f"最近训练中有 {repeated} 个问题连续出现，说明目前还没有形成稳定习惯。"
    elif temporarily_absent:
        status = "improving"
        label = "本轮暂未再现"
        fallback = f"上轮的 {temporarily_absent} 个问题本轮暂未再现，但还需要在新病例中继续验证。"
    elif first_seen:
        status = "first_seen"
        label = "本窗口首次出现"
        fallback = f"最近训练窗口中有 {first_seen} 个问题首次出现，暂不能判断是否会反复。"
    else:
        status = "insufficient_history"
        label = "历史不足"
        fallback = "当前缺少足够的可比较训练记录，暂不能判断问题是偶发还是反复。"
    return StudentLongitudinalSummary(
        status=status,
        label=label,
        summary=supplied_summary or fallback,
        first_seen_count=first_seen,
        repeated_count=repeated,
        reactivated_count=reactivated,
        temporarily_absent_count=temporarily_absent,
    )


def _build_personal_memory_summary(
    report: Mapping[str, Any],
    teacher_review: Mapping[str, Any],
) -> str:
    candidate = _mapping(report.get("personal_skill_candidate"))
    status = str(candidate.get("status") or "")
    title = _safe_student_text(candidate.get("title"), fallback="")
    if status == "approved" and title:
        return f"系统已记住训练重点“{title}”，后续相似场景会据此调整提示时机和层级。"
    if status in {"generation_pending", "not_complete"}:
        return "系统正在整理本轮训练重点；通过安全和回归检查后，才会用于后续相似场景。"
    if status in {"blocked_by_regression", "generation_failed"}:
        return "本轮候选训练策略未通过启用门禁，不会影响后续训练。"
    context = _mapping(teacher_review.get("teacher_analysis_context"))
    focus = _mapping(context.get("skill_memory_focus"))
    intervention = _safe_student_text(
        focus.get("recommended_intervention") or focus.get("problem_pattern_summary"),
        fallback="",
    )
    if intervention:
        return f"系统已记录本轮训练重点：{intervention}"
    return "系统尚未形成可复用的个人训练策略，本轮结论仍可直接用于下一次练习。"


def _deduplicate_candidates(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        identity = _semantic_identity(f"{candidate.get('title', '')}{candidate.get('next_action', '')}")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        result.append(candidate)
    return result


def _semantic_identity(value: Any) -> str:
    return "".join(character for character in _normalize_text(value).lower() if character.isalnum())[:120]


def _stage_label(value: str) -> str:
    return _STAGE_LABELS.get(value, _safe_student_text(value, fallback="本轮训练"))


def _stage_trigger(value: Any) -> str:
    return f"进入{_stage_label(str(value or '本轮训练'))}阶段时"


def _student_text_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    result: list[str] = []
    for item in value:
        text = _safe_student_text(item, fallback="")
        if text and text not in result:
            result.append(text)
        if len(result) == limit:
            break
    return result


def _safe_student_text(value: Any, *, fallback: str) -> str:
    normalized = _normalize_text(value)
    if not normalized:
        return _normalize_text(fallback)
    if _UUID_PATTERN.search(normalized) or _INTERNAL_TOKEN_PATTERN.search(normalized):
        return _normalize_text(fallback)
    if normalized.isascii() and not any(character.isdigit() for character in normalized):
        return _normalize_text(fallback)
    return normalized


def _normalize_text(value: Any) -> str:
    return _SPACE_PATTERN.sub(" ", str(value or "")).strip()


def _score_text(value: Any) -> str:
    number = _number(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _count(value: Any) -> int:
    return max(int(_number(value)), 0)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _object_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [item for item in value if isinstance(item, Mapping)]


__all__ = [
    "STUDENT_TRAINING_REPORT_VERSION",
    "StudentTrainingReportV2",
    "build_student_training_report",
]
