from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.services.agent_state_service import build_clinical_reasoning_state


MAX_TEACHER_DECISION_RECORDS = 120


class TeacherInterventionMode(StrEnum):
    SILENT = "silent"
    OBSERVE = "observe"
    HINT = "hint"
    BLOCK = "block"


@dataclass(frozen=True)
class TeacherInterventionDecision:
    mode: TeacherInterventionMode
    action_type: str
    trigger_kind: str
    reason_code: str
    reason: str
    issue_id: str = ""
    hint: str = ""
    resolved_issue_ids: tuple[str, ...] = ()
    context_snapshot: dict[str, Any] = field(default_factory=dict)


SEQUENCE_HINTS: dict[str, str] = {
    "physical_exam_before_history": "先暂停继续查体。请先补齐核心病史，再根据已有线索选择重点查体。",
    "auxiliary_test_before_history": "先暂停继续申请检查。请先建立核心病史，再决定哪些检查真正用于验证假设。",
    "auxiliary_test_before_physical_exam": "你已经进入辅助检查，但查体证据仍不足。先完成与当前线索相关的重点查体。",
    "auxiliary_test_without_hypothesis": "继续申请检查前，先形成一个可验证的初步假设，并说明检查准备验证或排除什么。",
    "hypothesis_before_core_history": "当前假设形成得较早。先补齐核心病史，再检查这个假设是否仍然成立。",
}

SEQUENCE_ACTION_FLAGS: dict[str, tuple[str, ...]] = {
    "physical_exam_requested": ("physical_exam_before_history",),
    "auxiliary_test_requested": (
        "auxiliary_test_before_history",
        "auxiliary_test_before_physical_exam",
        "auxiliary_test_without_hypothesis",
    ),
    "hypothesis_recorded": ("hypothesis_before_core_history",),
    "diagnosis_submitted": ("hypothesis_before_core_history",),
}

CONSENT_ISSUE_ID = "humanistic:consent_before_procedure"
PATIENT_AFFECT_ISSUE_ID = "humanistic:patient_affect_unanswered"

_CONSENT_EXPLICIT_TERMS = (
    "征得同意",
    "取得同意",
    "获得同意",
    "患者同意",
    "您同意",
    "你同意",
    "允许我",
)
_CONSENT_QUESTION_TERMS = ("可以吗", "是否可以", "您愿意", "你愿意", "好吗")
_PROCEDURE_CONTEXT_TERMS = ("查体", "检查", "触诊", "听诊", "按压", "抽血", "采血", "心电图", "影像")


def resolve_teacher_intervention(
    state: Mapping[str, Any],
    *,
    action_type: str,
    action_label: str = "",
    affect_transition: Mapping[str, Any] | None = None,
    explicit_hint: bool = False,
    boundary_kind: str = "",
    forced_hint: str = "",
    forced_reason_code: str = "",
) -> TeacherInterventionDecision:
    """Resolve one observable TeacherAgent intervention decision.

    The policy is intentionally conservative: valid progress stays silent, a
    first low-risk sequence issue is observed, repeated issues are hinted, and
    answer/safety boundaries are blocked immediately.
    """

    normalized_action_type = str(action_type or "student_action").strip()
    records = _decision_records(state.get("teacher_decision_records"))
    transition = dict(affect_transition) if isinstance(affect_transition, Mapping) else {}
    clinical_state = build_clinical_reasoning_state(dict(state))
    sequence_flags = [str(flag) for flag in clinical_state.get("sequence_flags", []) if str(flag)]
    resolved_issue_ids = _resolved_issue_ids(
        state,
        records=records,
        sequence_flags=sequence_flags,
        affect_transition=transition,
    )
    context_snapshot = _context_snapshot(
        state,
        action_label=action_label,
        sequence_flags=sequence_flags,
        affect_transition=transition,
    )

    if boundary_kind:
        reason_code = f"boundary:{boundary_kind}"
        reason = (
            "学生请求标准答案，教师智能体必须阻断并重定向到训练过程。"
            if boundary_kind == "answer"
            else "学生请求超出 OSCE 教学边界的真实诊疗建议，教师智能体必须阻断。"
        )
        return TeacherInterventionDecision(
            mode=TeacherInterventionMode.BLOCK,
            action_type=normalized_action_type,
            trigger_kind=f"{boundary_kind}_boundary",
            reason_code=reason_code,
            reason=reason,
            hint=forced_hint,
            resolved_issue_ids=tuple(resolved_issue_ids),
            context_snapshot=context_snapshot,
        )

    if explicit_hint:
        return TeacherInterventionDecision(
            mode=TeacherInterventionMode.HINT,
            action_type=normalized_action_type,
            trigger_kind="explicit_help_request",
            reason_code="student_requested_hint",
            reason="学生主动请求教学帮助，按当前提示层级生成苏格拉底式提示。",
            hint=forced_hint,
            resolved_issue_ids=tuple(resolved_issue_ids),
            context_snapshot=context_snapshot,
        )

    if forced_hint:
        return TeacherInterventionDecision(
            mode=TeacherInterventionMode.HINT,
            action_type=normalized_action_type,
            trigger_kind="context_redirect",
            reason_code=forced_reason_code or "deterministic_context_redirect",
            reason="当前输入未形成有效训练进展，需要短提示帮助学生回到病例任务。",
            hint=forced_hint,
            resolved_issue_ids=tuple(resolved_issue_ids),
            context_snapshot=context_snapshot,
        )

    affect_decision = _patient_affect_decision(
        state,
        action_type=normalized_action_type,
        records=records,
        transition=transition,
        resolved_issue_ids=resolved_issue_ids,
        context_snapshot=context_snapshot,
    )
    if affect_decision is not None:
        return affect_decision

    if normalized_action_type in {"physical_exam_requested", "auxiliary_test_requested"}:
        consent_decision = _consent_decision(
            state,
            action_type=normalized_action_type,
            records=records,
            resolved_issue_ids=resolved_issue_ids,
            context_snapshot=context_snapshot,
        )
        if consent_decision is not None:
            return consent_decision

    relevant_flags = [
        flag
        for flag in SEQUENCE_ACTION_FLAGS.get(normalized_action_type, ())
        if flag in sequence_flags
    ]
    if relevant_flags:
        flag = relevant_flags[0]
        issue_id = f"sequence:{flag}"
        if _issue_seen_since_resolution(records, issue_id):
            return TeacherInterventionDecision(
                mode=TeacherInterventionMode.HINT,
                action_type=normalized_action_type,
                trigger_kind="repeated_sequence_issue",
                reason_code=flag,
                reason="同一训练顺序问题再次出现，继续观察已不足以帮助学生纠正。",
                issue_id=issue_id,
                hint=SEQUENCE_HINTS[flag],
                resolved_issue_ids=tuple(resolved_issue_ids),
                context_snapshot=context_snapshot,
            )
        return TeacherInterventionDecision(
            mode=TeacherInterventionMode.OBSERVE,
            action_type=normalized_action_type,
            trigger_kind="sequence_risk_detected",
            reason_code=flag,
            reason="首次发现低风险训练顺序缺口，先记录并观察，不立即打断学生。",
            issue_id=issue_id,
            resolved_issue_ids=tuple(resolved_issue_ids),
            context_snapshot=context_snapshot,
        )

    return TeacherInterventionDecision(
        mode=TeacherInterventionMode.SILENT,
        action_type=normalized_action_type,
        trigger_kind="valid_progress",
        reason_code="no_intervention_needed",
        reason="当前操作形成有效训练进展，教师智能体保持静默。",
        resolved_issue_ids=tuple(resolved_issue_ids),
        context_snapshot=context_snapshot,
    )


def append_teacher_decision_record(
    existing_records: Sequence[Mapping[str, Any]] | None,
    decision: TeacherInterventionDecision,
    *,
    emitted_hint: str | None = None,
    selected_skill_ids: Sequence[str] = (),
    source_references: Sequence[str] = (),
    processing_status: str = "completed",
) -> list[dict[str, Any]]:
    records = [dict(record) for record in existing_records or [] if isinstance(record, Mapping)]
    final_hint = decision.hint if emitted_hint is None else str(emitted_hint or "")
    record = {
        "decision_id": f"teacher_decision:{len(records) + 1}",
        "created_at": datetime.now(UTC).isoformat(),
        "mode": decision.mode.value,
        "action_type": decision.action_type,
        "trigger_kind": decision.trigger_kind,
        "reason_code": decision.reason_code,
        "reason": decision.reason,
        "issue_id": decision.issue_id,
        "hint": final_hint,
        "hint_emitted": bool(final_hint) and decision.mode in {
            TeacherInterventionMode.HINT,
            TeacherInterventionMode.BLOCK,
        },
        "resolved_issue_ids": list(decision.resolved_issue_ids),
        "selected_skill_ids": [str(skill_id) for skill_id in selected_skill_ids if str(skill_id)],
        "source_references": [str(reference) for reference in source_references if str(reference)],
        "processing_status": str(processing_status or "completed"),
        "context_snapshot": dict(decision.context_snapshot),
    }
    return [*records, record][-MAX_TEACHER_DECISION_RECORDS:]


def latest_student_safe_intervention(records: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    normalized_records = [record for record in records or [] if isinstance(record, Mapping)]
    if not normalized_records:
        return {}
    record = normalized_records[-1]
    return {
        "mode": str(record.get("mode") or "silent"),
        "trigger_kind": str(record.get("trigger_kind") or ""),
        "message": str(record.get("hint") or "") if record.get("hint_emitted") else "",
    }


def _patient_affect_decision(
    state: Mapping[str, Any],
    *,
    action_type: str,
    records: list[dict[str, Any]],
    transition: Mapping[str, Any],
    resolved_issue_ids: list[str],
    context_snapshot: dict[str, Any],
) -> TeacherInterventionDecision | None:
    transition_event = str(transition.get("event") or "")
    affect_state = state.get("patient_affect_state")
    unanswered_signal = bool(affect_state.get("unanswered_signal")) if isinstance(affect_state, Mapping) else False

    if transition_event in {"emotion_repaired", "patient_relief_observed"}:
        return TeacherInterventionDecision(
            mode=TeacherInterventionMode.SILENT,
            action_type=action_type,
            trigger_kind="humanistic_issue_repaired",
            reason_code="patient_affect_repaired",
            reason="学生已经回应患者情绪，停止相关提示并恢复静默。",
            resolved_issue_ids=tuple(_with_unique(resolved_issue_ids, PATIENT_AFFECT_ISSUE_ID)),
            context_snapshot=context_snapshot,
        )

    if transition_event == "patient_signal_detected":
        return TeacherInterventionDecision(
            mode=TeacherInterventionMode.OBSERVE,
            action_type=action_type,
            trigger_kind="patient_affect_signal_detected",
            reason_code="patient_affect_waiting_for_student_response",
            reason="患者刚表达担忧或不适，先给学生一次自主回应机会。",
            issue_id=PATIENT_AFFECT_ISSUE_ID,
            resolved_issue_ids=tuple(resolved_issue_ids),
            context_snapshot=context_snapshot,
        )

    affect_was_ignored = transition_event == "emotion_ignored" or (
        unanswered_signal and action_type in {"physical_exam_requested", "auxiliary_test_requested"}
    )
    if not affect_was_ignored:
        return None
    if _issue_hinted_since_resolution(records, PATIENT_AFFECT_ISSUE_ID):
        return TeacherInterventionDecision(
            mode=TeacherInterventionMode.OBSERVE,
            action_type=action_type,
            trigger_kind="humanistic_hint_cooldown",
            reason_code="patient_affect_hint_already_emitted",
            reason="患者情绪问题仍未修复，但相同提示已经发出，进入冷却以避免重复打断。",
            issue_id=PATIENT_AFFECT_ISSUE_ID,
            resolved_issue_ids=tuple(resolved_issue_ids),
            context_snapshot=context_snapshot,
        )
    return TeacherInterventionDecision(
        mode=TeacherInterventionMode.HINT,
        action_type=action_type,
        trigger_kind="humanistic_issue_triggered",
        reason_code="patient_affect_ignored",
        reason="患者已经表达担忧，但学生继续推进医学操作，需主动提醒先完成沟通修复。",
        issue_id=PATIENT_AFFECT_ISSUE_ID,
        hint="先暂停医学问诊或操作，回应患者刚才的担忧，确认其感受后再继续。",
        resolved_issue_ids=tuple(resolved_issue_ids),
        context_snapshot=context_snapshot,
    )


def _consent_decision(
    state: Mapping[str, Any],
    *,
    action_type: str,
    records: list[dict[str, Any]],
    resolved_issue_ids: list[str],
    context_snapshot: dict[str, Any],
) -> TeacherInterventionDecision | None:
    if _has_recent_consent_evidence(state):
        if _issue_is_open(records, CONSENT_ISSUE_ID):
            return TeacherInterventionDecision(
                mode=TeacherInterventionMode.SILENT,
                action_type=action_type,
                trigger_kind="humanistic_issue_repaired",
                reason_code="procedure_consent_observed",
                reason="已识别学生说明操作并征得同意，不再提示知情同意。",
                resolved_issue_ids=tuple(_with_unique(resolved_issue_ids, CONSENT_ISSUE_ID)),
                context_snapshot=context_snapshot,
            )
        return None
    if _issue_hinted_since_resolution(records, CONSENT_ISSUE_ID):
        return TeacherInterventionDecision(
            mode=TeacherInterventionMode.OBSERVE,
            action_type=action_type,
            trigger_kind="humanistic_hint_cooldown",
            reason_code="consent_hint_already_emitted",
            reason="知情同意提示已经发出，暂不重复刷屏，继续等待学生修复。",
            issue_id=CONSENT_ISSUE_ID,
            resolved_issue_ids=tuple(resolved_issue_ids),
            context_snapshot=context_snapshot,
        )
    procedure_label = "查体" if action_type == "physical_exam_requested" else "辅助检查"
    return TeacherInterventionDecision(
        mode=TeacherInterventionMode.HINT,
        action_type=action_type,
        trigger_kind="humanistic_issue_triggered",
        reason_code="procedure_without_consent_evidence",
        reason=f"学生直接申请{procedure_label}，当前对话中没有可见的目的说明或同意证据。",
        issue_id=CONSENT_ISSUE_ID,
        hint=f"进行{procedure_label}前，请先向患者说明目的和可能的不适，并征得同意。",
        resolved_issue_ids=tuple(resolved_issue_ids),
        context_snapshot=context_snapshot,
    )


def _resolved_issue_ids(
    state: Mapping[str, Any],
    *,
    records: list[dict[str, Any]],
    sequence_flags: list[str],
    affect_transition: Mapping[str, Any],
) -> list[str]:
    open_issue_ids = _open_issue_ids(records)
    resolved: list[str] = []
    transition_event = str(affect_transition.get("event") or "")
    affect_state = state.get("patient_affect_state")
    unanswered = bool(affect_state.get("unanswered_signal")) if isinstance(affect_state, Mapping) else False
    if PATIENT_AFFECT_ISSUE_ID in open_issue_ids and (
        transition_event in {"emotion_repaired", "patient_relief_observed"} or not unanswered
    ):
        resolved.append(PATIENT_AFFECT_ISSUE_ID)
    if CONSENT_ISSUE_ID in open_issue_ids and _has_recent_consent_evidence(state):
        resolved.append(CONSENT_ISSUE_ID)
    current_sequence_issue_ids = {f"sequence:{flag}" for flag in sequence_flags}
    resolved.extend(
        issue_id
        for issue_id in open_issue_ids
        if issue_id.startswith("sequence:") and issue_id not in current_sequence_issue_ids
    )
    return _deduplicated(resolved)


def _context_snapshot(
    state: Mapping[str, Any],
    *,
    action_label: str,
    sequence_flags: list[str],
    affect_transition: Mapping[str, Any],
) -> dict[str, Any]:
    affect_state = state.get("patient_affect_state")
    affect_payload = dict(affect_state) if isinstance(affect_state, Mapping) else {}
    return {
        "stage": str(state.get("stage") or "case_intro"),
        "action_label": str(action_label or ""),
        "sequence_flags": list(sequence_flags),
        "patient_affect": {
            "emotion": str(affect_payload.get("current_emotion") or "neutral"),
            "unanswered_signal": bool(affect_payload.get("unanswered_signal")),
            "transition": str(affect_transition.get("event") or ""),
        },
    }


def _has_recent_consent_evidence(state: Mapping[str, Any]) -> bool:
    messages = state.get("messages")
    if not isinstance(messages, list):
        return False
    student_messages = [
        str(message.get("content") or "")
        for message in messages[-8:]
        if isinstance(message, Mapping) and str(message.get("role") or "") == "student"
    ]
    for message in reversed(student_messages):
        compact = "".join(message.split())
        if any(term in compact for term in _CONSENT_EXPLICIT_TERMS):
            return True
        if any(question in compact for question in _CONSENT_QUESTION_TERMS) and any(
            term in compact for term in _PROCEDURE_CONTEXT_TERMS
        ):
            return True
    return False


def _decision_records(value: Any) -> list[dict[str, Any]]:
    return [dict(record) for record in value if isinstance(record, Mapping)] if isinstance(value, list) else []


def _open_issue_ids(records: Sequence[Mapping[str, Any]]) -> set[str]:
    open_issues: set[str] = set()
    for record in records:
        for issue_id in record.get("resolved_issue_ids", []):
            open_issues.discard(str(issue_id))
        issue_id = str(record.get("issue_id") or "")
        if issue_id and str(record.get("mode") or "") in {
            TeacherInterventionMode.OBSERVE.value,
            TeacherInterventionMode.HINT.value,
        }:
            open_issues.add(issue_id)
    return open_issues


def _issue_is_open(records: Sequence[Mapping[str, Any]], issue_id: str) -> bool:
    return issue_id in _open_issue_ids(records)


def _issue_seen_since_resolution(records: Sequence[Mapping[str, Any]], issue_id: str) -> bool:
    for record in reversed(records):
        if issue_id in {str(item) for item in record.get("resolved_issue_ids", [])}:
            return False
        if str(record.get("issue_id") or "") == issue_id:
            return True
    return False


def _issue_hinted_since_resolution(records: Sequence[Mapping[str, Any]], issue_id: str) -> bool:
    for record in reversed(records):
        if issue_id in {str(item) for item in record.get("resolved_issue_ids", [])}:
            return False
        if str(record.get("issue_id") or "") == issue_id and str(record.get("mode") or "") == "hint":
            return True
    return False


def _with_unique(values: Sequence[str], value: str) -> list[str]:
    return _deduplicated([*values, value])


def _deduplicated(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


__all__ = [
    "MAX_TEACHER_DECISION_RECORDS",
    "TeacherInterventionDecision",
    "TeacherInterventionMode",
    "append_teacher_decision_record",
    "latest_student_safe_intervention",
    "resolve_teacher_intervention",
]
