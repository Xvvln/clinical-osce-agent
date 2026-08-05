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

_DIMENSION_MAX_SCORES = {
    "history_taking": 18,
    "physical_exam": 10,
    "auxiliary_test": 10,
    "main_diagnosis": 10,
    "differential_diagnosis": 10,
    "reasoning": 12,
    "narrative_medicine": 8,
    "communication_skill": 10,
    "medical_ethics": 7,
    "relationship_building": 5,
}

_COVERAGE_ANGLES: tuple[dict[str, Any], ...] = (
    {
        "angle_id": "information_collection",
        "label": "病史采集",
        "dimension_ids": ("history_taking",),
        "capability": "关键病史采集",
    },
    {
        "angle_id": "examination_and_tests",
        "label": "查体与辅助检查",
        "dimension_ids": ("physical_exam", "auxiliary_test"),
        "capability": "针对当前假设选择查体和检查",
    },
    {
        "angle_id": "main_diagnosis",
        "label": "主诊断判断",
        "dimension_ids": ("main_diagnosis",),
        "capability": "主诊断判断",
    },
    {
        "angle_id": "differential_diagnosis",
        "label": "鉴别诊断",
        "dimension_ids": ("differential_diagnosis",),
        "capability": "鉴别诊断及排除依据",
    },
    {
        "angle_id": "clinical_reasoning",
        "label": "临床推理",
        "dimension_ids": ("reasoning",),
        "capability": "支持证据、反证依据和待验证问题的推理链",
    },
    {
        "angle_id": "narrative_and_concerns",
        "label": "患者叙事与关切",
        "dimension_ids": ("narrative_medicine",),
        "capability": "患者想法、担忧和期望的回应",
    },
    {
        "angle_id": "communication_and_relationship",
        "label": "沟通与关系",
        "dimension_ids": ("communication_skill", "relationship_building"),
        "capability": "解释、共情和医患关系建立",
    },
    {
        "angle_id": "ethics_and_safety",
        "label": "伦理与安全",
        "dimension_ids": ("medical_ethics",),
        "capability": "知情同意、隐私和安全顺序",
    },
)


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
    category: Literal["information", "reasoning", "humanistic_safety"]
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


class StudentAnalysisCoverage(BaseModel):
    angle_id: str
    label: str
    status: Literal["sufficient", "partial", "missing", "not_observed"]
    summary: str
    score: float = Field(default=0, ge=0)
    max_score: float = Field(default=0, ge=0)

    @field_validator("label", "summary")
    @classmethod
    def _student_text_only(cls, value: str) -> str:
        return _validate_student_text(value)


class StudentEvidenceQuality(BaseModel):
    level: Literal["limited", "moderate", "rich"]
    label: str
    summary: str
    observed_item_count: int = Field(default=0, ge=0)
    total_item_count: int = Field(default=0, ge=0)
    analyzed_angle_count: int = Field(default=0, ge=0)
    total_angle_count: int = Field(default=0, ge=0)

    @field_validator("label", "summary")
    @classmethod
    def _student_text_only(cls, value: str) -> str:
        return _validate_student_text(value)


class StudentTrainingReportV2(BaseModel):
    version: Literal["student_training_report_v2"] = STUDENT_TRAINING_REPORT_VERSION
    status: Literal["generated", "legacy_fallback"] = "generated"
    outcome: StudentReportOutcome
    evidence_quality: StudentEvidenceQuality
    analysis_coverage: list[StudentAnalysisCoverage] = Field(default_factory=list, max_length=10)
    decision_replays: list[StudentDecisionReplay] = Field(default_factory=list, max_length=6)
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
    analysis_coverage = _build_analysis_coverage(report, deep_analysis)
    payload = StudentTrainingReportV2(
        status="generated" if str(deep_analysis.get("status") or "") == "generated" else "legacy_fallback",
        outcome=_build_outcome(report, deep_analysis),
        evidence_quality=_build_evidence_quality(report, analysis_coverage),
        analysis_coverage=analysis_coverage,
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
    ethics_score, ethics_max = _dimension_score_pair(report, ("medical_ethics",))
    communication_score, communication_max = _dimension_score_pair(
        report,
        ("narrative_medicine", "communication_skill", "relationship_building"),
    )
    safety_summary = (
        f"本轮记录到 {safety_count} 个知情同意或安全顺序问题，需要在下一轮优先修复。"
        if safety_count
        else (
            "本轮评分轨迹未找到知情同意、隐私或安全顺序的完成证据；不能据此断言没有风险。"
            if ethics_max > 0 and ethics_score <= 0
            else f"本轮伦理与安全获得 {_score_text(ethics_score)}/{_score_text(ethics_max)} 分，仍需结合具体动作复核。"
        )
    )
    communication_summary = (
        f"本轮记录到 {communication_count} 个沟通机会未被及时回应。"
        if communication_count
        else (
            "本轮评分轨迹未找到患者关切、共情或关系建立的完成证据；这表示尚未观察到，不代表确认没有漏项。"
            if communication_max > 0 and communication_score <= 0
            else f"本轮人文沟通获得 {_score_text(communication_score)}/{_score_text(communication_max)} 分，未触发的场景不作过度推断。"
        )
    )
    return StudentReportOutcome(
        summary=overall_summary,
        score_summary=score_summary,
        diagnosis_status=classification,
        diagnosis_summary=diagnosis_summary,
        safety_summary=safety_summary,
        communication_summary=communication_summary,
    )


def _build_analysis_coverage(
    report: Mapping[str, Any],
    deep_analysis: Mapping[str, Any],
) -> list[StudentAnalysisCoverage]:
    coverage: list[StudentAnalysisCoverage] = []
    for angle in _COVERAGE_ANGLES:
        score, max_score = _dimension_score_pair(report, angle["dimension_ids"])
        status = _score_coverage_status(score, max_score)
        capability = str(angle["capability"])
        if status == "sufficient":
            summary = f"本轮获得 {_score_text(score)}/{_score_text(max_score)} 分，{capability}已有较完整的可观察证据。"
        elif status == "partial":
            summary = f"本轮获得 {_score_text(score)}/{_score_text(max_score)} 分，已观察到部分{capability}，但证据仍未闭合。"
        elif status == "missing":
            summary = f"评分轨迹未找到{capability}的完成证据；这表示本轮无法确认完成，不等于认定学生从未具备该能力。"
        else:
            summary = f"本轮没有足够材料判断{capability}，该角度不作过度推断。"
        coverage.append(
            StudentAnalysisCoverage(
                angle_id=str(angle["angle_id"]),
                label=str(angle["label"]),
                status=status,
                summary=summary,
                score=score,
                max_score=max_score,
            )
        )

    evidence = _mapping(deep_analysis.get("evidence_utilization_analysis"))
    collected_count = len(_object_list(evidence.get("collected_key_evidence")))
    missing_count = len(_object_list(evidence.get("missing_key_evidence")))
    breakpoint_count = len(_object_list(evidence.get("evidence_chain_breakpoints")))
    if collected_count and not missing_count and not breakpoint_count:
        evidence_status = "sufficient"
        evidence_summary = f"本轮已连接 {collected_count} 类关键证据，未发现明确的证据链断点。"
    elif collected_count:
        evidence_status = "partial"
        evidence_summary = f"本轮已采集 {collected_count} 类关键证据，仍缺 {missing_count} 类，并存在 {breakpoint_count} 个需要补齐的链路。"
    elif missing_count or breakpoint_count:
        evidence_status = "missing"
        evidence_summary = f"本轮尚未形成可确认的关键证据链，仍有 {missing_count} 类证据和 {breakpoint_count} 个链路需要补齐。"
    else:
        evidence_status = "not_observed"
        evidence_summary = "本轮缺少可比较的证据节点记录，暂不能评价证据链完整性。"
    coverage.append(
        StudentAnalysisCoverage(
            angle_id="evidence_chain",
            label="证据链",
            status=evidence_status,
            summary=evidence_summary,
        )
    )

    process = _mapping(deep_analysis.get("process_strategy_analysis"))
    sequence_flags = _object_list(process.get("sequence_flags"))
    order_summary = _safe_student_text(process.get("action_order_summary"), fallback="")
    if sequence_flags:
        sequence_status = "partial"
        first_flag = sequence_flags[0]
        sequence_summary = _safe_student_text(
            first_flag.get("evidence") or first_flag.get("label"),
            fallback=f"本轮记录到 {len(sequence_flags)} 个动作顺序问题，需要调整介入时机。",
        )
    elif order_summary and not any(token in order_summary for token in ("暂缺", "不足", "无法")):
        sequence_status = "sufficient"
        sequence_summary = f"{order_summary} 当前未发现明确的顺序越界，但仍只对已记录动作负责。"
    else:
        sequence_status = "not_observed"
        sequence_summary = "本轮动作记录较少，暂不足以确认操作顺序和介入时机是否稳定。"
    coverage.append(
        StudentAnalysisCoverage(
            angle_id="sequence_and_timing",
            label="操作顺序与时机",
            status=sequence_status,
            summary=sequence_summary,
        )
    )
    return coverage


def _build_evidence_quality(
    report: Mapping[str, Any],
    coverage: Sequence[StudentAnalysisCoverage],
) -> StudentEvidenceQuality:
    traces = [
        item
        for raw_items in _mapping(report.get("dimension_traces")).values()
        for item in _object_list(raw_items)
    ]
    if traces:
        total_item_count = len(traces)
        observed_item_count = sum(
            1
            for item in traces
            if _number(item.get("score", item.get("awarded_score"))) > 0
            or bool(_student_text_list(item.get("matched_evidence"), limit=1))
        )
    else:
        rubric_items = [item for item in _mapping(report.get("rubric_scores")).values() if isinstance(item, Mapping)]
        total_item_count = len(rubric_items)
        observed_item_count = sum(1 for item in rubric_items if _number(item.get("score")) > 0)
    ratio = observed_item_count / total_item_count if total_item_count else 0
    if observed_item_count <= 4 or ratio < 0.2:
        level = "limited"
        label = "本轮证据较少"
        caution = "当前结论只说明已记录动作，不对未发生或未记录的过程作推测。"
    elif observed_item_count <= 10 or ratio < 0.6:
        level = "moderate"
        label = "本轮证据中等"
        caution = "主要问题已有依据，未触发场景仍需在下一轮继续观察。"
    else:
        level = "rich"
        label = "本轮证据较丰富"
        caution = "多数角度已有可观察依据，仍需结合逐项证据理解结论边界。"
    analyzed_angle_count = sum(1 for item in coverage if item.status != "not_observed")
    summary = (
        f"评分轨迹可确认 {observed_item_count}/{total_item_count} 个训练点，"
        f"{analyzed_angle_count}/{len(coverage)} 个分析角度具备判断材料。{caution}"
    )
    return StudentEvidenceQuality(
        level=level,
        label=label,
        summary=summary,
        observed_item_count=observed_item_count,
        total_item_count=total_item_count,
        analyzed_angle_count=analyzed_angle_count,
        total_angle_count=len(coverage),
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
    selected: list[dict[str, Any]] = []
    if positive_candidates:
        selected.append(positive_candidates[0])
    for kind in ("safety", "reasoning", "evidence", "sequence", "humanistic"):
        candidate = next(
            (
                item
                for item in gap_candidates
                if item.get("kind") == kind and item not in selected
            ),
            None,
        )
        if candidate is not None:
            selected.append(candidate)
        if len(selected) == 6:
            break
    for candidate in [*gap_candidates, *positive_candidates[1:]]:
        if candidate not in selected:
            selected.append(candidate)
        if len(selected) == 6:
            break
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
        dimension_id = str(gap.get("dimension_id") or gap.get("stage") or "")
        gap_type = str(gap.get("gap_type") or "").lower()
        if dimension_id in {"reasoning", "differential_diagnosis", "main_diagnosis"}:
            kind = "reasoning"
        elif dimension_id == "medical_ethics" or any(token in gap_type for token in ("ethic", "consent", "safety")):
            kind = "safety"
        elif dimension_id in {"narrative_medicine", "communication_skill", "relationship_building"}:
            kind = "humanistic"
        else:
            kind = "evidence"
        candidates.append(
            {
                "kind": kind,
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
                category="reasoning",
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
                "category": _prescription_category(item),
                "title": _safe_student_text(item.get("label"), fallback="补齐本轮优先训练点"),
                "trigger": _safe_student_text(item.get("trigger"), fallback=_stage_trigger(item.get("stage"))),
                "action": _safe_student_text(item.get("next_training_action"), fallback="完成该训练点并说明它与当前假设的关系。"),
                "success_signal": _safe_student_text(item.get("success_signal"), fallback="评分轨迹能够找到对应动作和说明。"),
            }
        )
    for item in _object_list(plan.get("stage_triggered_actions")):
        raw_candidates.append(
            {
                "category": _prescription_category(item),
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
                "category": _prescription_category(gap),
                "title": label,
                "trigger": _stage_trigger(gap.get("stage") or gap.get("dimension_id")),
                "action": _safe_student_text(gap.get("next_training_action"), fallback=f"完成“{label}”并说明为什么要做。"),
                "success_signal": f"报告能够找到“{label}”对应的动作或推理表达。",
            }
        )
    humanistic = _mapping(deep_analysis.get("humanistic_communication_analysis"))
    for item in _object_list(humanistic.get("missed_opportunities")):
        raw_candidates.append(
            {
                "category": "humanistic_safety",
                "title": "补上沟通与安全动作",
                "trigger": _stage_trigger(item.get("stage") or "humanistic_communication"),
                "action": _safe_student_text(
                    item.get("next_training_action") or item.get("expected_response"),
                    fallback="先回应患者关切，说明操作目的并获得同意后再继续。",
                ),
                "success_signal": "评分轨迹能够找到回应患者、说明目的或获得同意的具体表达。",
            }
        )
    for action in _student_text_list(teacher_review.get("next_practice_plan"), limit=3):
        raw_candidates.append(
            {
                "category": _prescription_category({"label": action}),
                "title": "执行教师建议",
                "trigger": "下一轮遇到相似临床任务时",
                "action": action,
                "success_signal": "能够不依赖提示完成该动作，并说出它将验证或排除什么。",
            }
        )
    raw_candidates.extend(_fallback_prescription_candidates(report))
    deduplicated: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in raw_candidates:
        identity = _semantic_identity(candidate["action"])
        if not identity or identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(candidate)
    selected: list[dict[str, str]] = []
    for category in ("information", "reasoning", "humanistic_safety"):
        candidate = next((item for item in deduplicated if item["category"] == category), None)
        if candidate is not None:
            selected.append(candidate)
    for candidate in deduplicated:
        if candidate not in selected:
            selected.append(candidate)
        if len(selected) == 3:
            break
    if not selected:
        selected.append(
            {
                "category": "reasoning",
                "title": "迁移本轮有效做法",
                "trigger": "进入下一个新病例时",
                "action": "独立完成问诊、关键查体、必要检查和诊断推理，并说明每一步的目的。",
                "success_signal": "在不依赖提示的情况下形成完整证据链，且不新增明显安全或沟通问题。",
            }
        )
    return [
        StudentTrainingPrescription(goal_id=f"goal-{index + 1}", **candidate)
        for index, candidate in enumerate(selected[:3])
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


def _dimension_score_pair(
    report: Mapping[str, Any],
    dimension_ids: Sequence[str],
) -> tuple[float, float]:
    dimension_scores = _mapping(report.get("dimension_scores"))
    rubric_scores = _mapping(report.get("rubric_scores"))
    score = sum(max(_number(dimension_scores.get(dimension_id)), 0) for dimension_id in dimension_ids)
    max_score = 0.0
    for dimension_id in dimension_ids:
        rubric_max = sum(
            max(_number(item.get("max_score")), 0)
            for item in rubric_scores.values()
            if isinstance(item, Mapping) and str(item.get("dimension_id") or "") == dimension_id
        )
        max_score += max(rubric_max, float(_DIMENSION_MAX_SCORES.get(dimension_id, 0)))
    return score, max_score


def _score_coverage_status(
    score: float,
    max_score: float,
) -> Literal["sufficient", "partial", "missing", "not_observed"]:
    if max_score <= 0:
        return "not_observed"
    if score <= 0:
        return "missing"
    return "sufficient" if score / max_score >= 0.8 else "partial"


def _prescription_category(candidate: Mapping[str, Any]) -> str:
    dimension_id = str(candidate.get("dimension_id") or candidate.get("stage") or "").lower()
    if dimension_id in {"history_taking", "physical_exam", "auxiliary_test"}:
        return "information"
    if dimension_id in {"main_diagnosis", "differential_diagnosis", "reasoning", "diagnosis_submission", "diagnostic_reasoning"}:
        return "reasoning"
    if dimension_id in {"narrative_medicine", "communication_skill", "medical_ethics", "relationship_building", "humanistic_communication"}:
        return "humanistic_safety"
    searchable = " ".join(
        str(candidate.get(key) or "")
        for key in (
            "dimension_id",
            "stage",
            "gap_type",
            "skill_type",
            "label",
            "action",
            "next_training_action",
        )
    ).lower()
    if any(
        token in searchable
        for token in (
            "humanistic",
            "communication",
            "relationship",
            "narrative",
            "ethic",
            "consent",
            "safety",
            "沟通",
            "共情",
            "患者",
            "同意",
            "隐私",
            "伦理",
        )
    ):
        return "humanistic_safety"
    if any(
        token in searchable
        for token in (
            "reasoning",
            "diagnosis",
            "differential",
            "hypothesis",
            "推理",
            "诊断",
            "鉴别",
            "假设",
            "排除",
        )
    ):
        return "reasoning"
    return "information"


def _fallback_prescription_candidates(report: Mapping[str, Any]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    information_score, information_max = _dimension_score_pair(
        report,
        ("history_taking", "physical_exam", "auxiliary_test"),
    )
    if information_max > 0 and information_score < information_max:
        candidates.append(
            {
                "category": "information",
                "title": "补齐关键病史与检查",
                "trigger": "形成初步诊断假设后",
                "action": "围绕当前假设补问关键病史，选择必要查体和检查，并说明每一步要验证什么。",
                "success_signal": "报告能够找到关键病史、查体和检查动作，以及它们与诊断假设的对应关系。",
            }
        )
    reasoning_score, reasoning_max = _dimension_score_pair(
        report,
        ("differential_diagnosis", "reasoning"),
    )
    if reasoning_max > 0 and reasoning_score < reasoning_max:
        candidates.append(
            {
                "category": "reasoning",
                "title": "闭合鉴别诊断证据链",
                "trigger": "准备提交诊断前",
                "action": "写出主要诊断、至少一个相近诊断，并分别说明支持依据和排除依据。",
                "success_signal": "诊断提交同时包含主诊断支持证据、鉴别诊断和明确排除依据。",
            }
        )
    humanistic_score, humanistic_max = _dimension_score_pair(
        report,
        ("narrative_medicine", "communication_skill", "medical_ethics", "relationship_building"),
    )
    if humanistic_max > 0 and humanistic_score < humanistic_max:
        candidates.append(
            {
                "category": "humanistic_safety",
                "title": "补上患者回应与知情同意",
                "trigger": "患者表达担忧或准备进行查体检查时",
                "action": "先回应患者关切，再说明操作目的、可能不适并获得同意后继续。",
                "success_signal": "评分轨迹能够找到回应情绪、解释目的和获得同意三个可观察动作。",
            }
        )
    return candidates


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
