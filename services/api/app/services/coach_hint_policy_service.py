from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


PATIENT_EMOTION_KEYWORDS = ("担心", "担忧", "害怕", "焦虑", "怕", "紧张")
EMPATHY_RESPONSE_KEYWORDS = ("理解", "担心", "害怕", "焦虑", "别担心", "正常", "一起", "会帮", "我明白")

EMPTY_SESSION_ALLOWED_GAP_TYPES = {
    "communication_intro_missing",
    "communication_open_question_missing",
}


class HintIntent(StrEnum):
    CASE_ONBOARDING = "case_onboarding"
    HISTORY_PROGRESSION = "history_progression"
    OPPORTUNITY_PREPARATION = "opportunity_preparation"
    RELATIONSHIP_REPAIR = "relationship_repair"
    ETHICS_CONSENT_BEFORE_ACTION = "ethics_consent_before_action"
    STAGE_SUMMARY = "stage_summary"
    DIAGNOSTIC_REASONING = "diagnostic_reasoning"
    TRAINING_GOAL = "training_goal"


@dataclass(frozen=True)
class InteractionContext:
    stage: str
    has_student_training_action: bool
    asked_questions_count: int
    revealed_facts_count: int
    requested_exams_count: int
    requested_tests_count: int
    student_hypotheses_count: int
    has_patient_emotion_signal: bool
    has_unanswered_patient_emotion_signal: bool

    @property
    def collected_evidence_count(self) -> int:
        return self.revealed_facts_count + self.requested_exams_count + self.requested_tests_count


@dataclass(frozen=True)
class CoachHintPolicyDecision:
    intent: HintIntent
    hint: str
    training_goal_hint: str = ""
    selected_goal_type: str = ""
    trigger_state: str = "none"
    suppressed_goal_types: list[str] = field(default_factory=list)
    candidate_goal_types: list[str] = field(default_factory=list)

    def to_context_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent.value,
            "selected_goal_type": self.selected_goal_type,
            "candidate_goal_types": list(self.candidate_goal_types),
            "suppressed_goal_types": list(self.suppressed_goal_types),
            "training_goal_hint": self.training_goal_hint,
            "trigger_state": self.trigger_state,
        }


def resolve_coach_hint_policy(
    *,
    state: Mapping[str, Any],
    default_hint: str,
    training_goals: Sequence[Mapping[str, Any]] | None = None,
) -> CoachHintPolicyDecision:
    context = build_interaction_context(state)
    normalized_goals = [goal for goal in training_goals or [] if isinstance(goal, Mapping)]
    candidate_goal_types = [_goal_type(goal) for goal in normalized_goals if _goal_type(goal)]
    if not normalized_goals:
        return CoachHintPolicyDecision(intent=_default_intent(context), hint=default_hint)

    suppressed_goal_types: list[str] = []
    for goal in normalized_goals:
        if _goal_status(goal) == "recovered":
            continue
        gap_type = _goal_type(goal)

        stage_applies = _training_goal_stage_applies(context.stage, _goal_trigger_stage(goal))
        if stage_applies and _training_goal_triggered(goal, context):
            training_goal_hint = _training_goal_action_text(goal)
            if not training_goal_hint:
                suppressed_goal_types.append(gap_type)
                continue
            return CoachHintPolicyDecision(
                intent=_intent_for_goal(gap_type, context),
                hint=default_hint,
                training_goal_hint=training_goal_hint,
                selected_goal_type=gap_type,
                trigger_state="triggered",
                suppressed_goal_types=suppressed_goal_types,
                candidate_goal_types=candidate_goal_types,
            )

        preparation_hint = _training_goal_preparation_hint(goal, context)
        if not preparation_hint:
            suppressed_goal_types.append(gap_type)
            continue
        return CoachHintPolicyDecision(
            intent=HintIntent.OPPORTUNITY_PREPARATION,
            hint=default_hint,
            training_goal_hint=preparation_hint,
            selected_goal_type=gap_type,
            trigger_state="preparation",
            suppressed_goal_types=suppressed_goal_types,
            candidate_goal_types=candidate_goal_types,
        )

    return CoachHintPolicyDecision(
        intent=_default_intent(context),
        hint=default_hint,
        suppressed_goal_types=suppressed_goal_types,
        candidate_goal_types=candidate_goal_types,
    )


def active_training_goals_from_state(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    active_skill_context = state.get("active_skill_context", {})
    if not isinstance(active_skill_context, Mapping):
        return []
    goals = active_skill_context.get("humanistic_training_goals") or active_skill_context.get("current_training_gaps")
    if not isinstance(goals, list):
        return []
    return [dict(goal) for goal in goals if isinstance(goal, Mapping)]


def build_interaction_context(state: Mapping[str, Any]) -> InteractionContext:
    messages = _message_list(state.get("messages"))
    return InteractionContext(
        stage=str(state.get("stage") or "case_intro"),
        has_student_training_action=has_student_training_action(state),
        asked_questions_count=len(_string_list(state.get("asked_questions"))),
        revealed_facts_count=len(_string_list(state.get("revealed_facts"))),
        requested_exams_count=len(_string_list(state.get("requested_exams"))),
        requested_tests_count=len(_string_list(state.get("requested_tests"))),
        student_hypotheses_count=len(_string_list(state.get("student_hypotheses"))),
        has_patient_emotion_signal=_has_patient_emotion_signal(messages),
        has_unanswered_patient_emotion_signal=_has_unanswered_patient_emotion_signal(messages),
    )


def has_student_training_action(state: Mapping[str, Any]) -> bool:
    if _string_list(state.get("asked_questions")) or _string_list(state.get("revealed_facts")):
        return True
    if _string_list(state.get("requested_exams")) or _string_list(state.get("requested_tests")):
        return True
    if _string_list(state.get("student_hypotheses")):
        return True
    for message in _message_list(state.get("messages")):
        if message.get("role") == "student" and str(message.get("content") or "").strip():
            return True
    return False


def _training_goal_triggered(goal: Mapping[str, Any], context: InteractionContext) -> bool:
    gap_type = _goal_type(goal)
    if not context.has_student_training_action:
        return gap_type in EMPTY_SESSION_ALLOWED_GAP_TYPES
    if gap_type == "relationship_empathy_missing":
        return context.has_unanswered_patient_emotion_signal
    if gap_type in {"relationship_supportive_language_missing", "relationship_collaborative_expression_missing"}:
        return context.has_unanswered_patient_emotion_signal
    if gap_type in {"ethics_consent_missing", "ethics_privacy_comfort_missing"}:
        return _normalized_stage(context.stage) == "physical_exam"
    if gap_type == "ethics_autonomy_missing":
        return _normalized_stage(context.stage) == "auxiliary_test"
    if gap_type == "communication_summary_missing":
        return context.collected_evidence_count >= 2 or _normalized_stage(context.stage) in {
            "physical_exam",
            "auxiliary_test",
            "diagnosis_submission",
        }
    if gap_type == "communication_confirm_understanding_missing":
        return _normalized_stage(context.stage) in {"auxiliary_test", "diagnosis_submission", "feedback"}
    if gap_type in {
        "narrative_patient_perspective_missing",
        "narrative_life_impact_missing",
        "narrative_patient_perspective_reflection_missing",
        "communication_intro_missing",
        "communication_open_question_missing",
    }:
        return _normalized_stage(context.stage) in {"case_intro", "history_taking"}
    return True


def _training_goal_preparation_hint(goal: Mapping[str, Any], context: InteractionContext) -> str:
    if not context.has_student_training_action:
        return ""
    gap_type = _goal_type(goal)
    normalized_stage = _normalized_stage(context.stage)
    if gap_type in {
        "relationship_empathy_missing",
        "relationship_supportive_language_missing",
        "relationship_collaborative_expression_missing",
    }:
        if context.has_patient_emotion_signal or normalized_stage not in {"case_intro", "history_taking"}:
            return ""
        if context.asked_questions_count == 0 and context.revealed_facts_count == 0:
            return ""
        return (
            "本轮可以主动询问患者最担心什么、希望解决什么，或这次不适对学习生活的影响；"
            "如果患者表达担忧，再先回应情绪再继续问诊。"
        )
    if gap_type in {"ethics_consent_missing", "ethics_privacy_comfort_missing"}:
        if normalized_stage != "history_taking" or context.collected_evidence_count < 2:
            return ""
        return "本轮准备进入查体或检查前，先说明目的、可能不适并征得同意。"
    return ""


def _default_intent(context: InteractionContext) -> HintIntent:
    if not context.has_student_training_action:
        return HintIntent.CASE_ONBOARDING
    normalized_stage = _normalized_stage(context.stage)
    if normalized_stage in {"case_intro", "history_taking"}:
        return HintIntent.HISTORY_PROGRESSION
    if normalized_stage in {"diagnosis_submission", "feedback"}:
        return HintIntent.DIAGNOSTIC_REASONING
    return HintIntent.TRAINING_GOAL


def _intent_for_goal(gap_type: str, context: InteractionContext) -> HintIntent:
    if not context.has_student_training_action:
        return HintIntent.CASE_ONBOARDING
    if gap_type.startswith("relationship_"):
        return HintIntent.RELATIONSHIP_REPAIR
    if gap_type.startswith("ethics_"):
        return HintIntent.ETHICS_CONSENT_BEFORE_ACTION
    if gap_type == "communication_summary_missing":
        return HintIntent.STAGE_SUMMARY
    if gap_type.startswith("communication_") or gap_type.startswith("narrative_"):
        return HintIntent.HISTORY_PROGRESSION
    return HintIntent.TRAINING_GOAL


def _training_goal_stage_applies(stage: str, trigger_stage: str) -> bool:
    if not trigger_stage:
        return True
    normalized_stage = _normalized_stage(stage)
    normalized_trigger = _normalized_stage(trigger_stage)
    if normalized_stage == normalized_trigger:
        return True
    return normalized_trigger == "history_taking" and normalized_stage == "case_intro"


def _training_goal_action_text(goal: Mapping[str, Any]) -> str:
    action = str(goal.get("next_training_action") or "").strip()
    if action:
        return action.replace("下一轮", "本轮")
    success_signal = str(goal.get("success_signal") or "").strip()
    if success_signal:
        return f"本轮训练目标：{success_signal}"
    label = str(goal.get("label") or "").strip()
    return f"本轮训练目标：{label}。" if label else ""


def _has_unanswered_patient_emotion_signal(messages: list[dict[str, str]]) -> bool:
    last_emotion_index: int | None = None
    for index, message in enumerate(messages):
        if message.get("role") == "patient" and _contains_any(str(message.get("content") or ""), PATIENT_EMOTION_KEYWORDS):
            last_emotion_index = index
    if last_emotion_index is None:
        return False
    for message in messages[last_emotion_index + 1 :]:
        if message.get("role") == "student":
            return not _contains_any(str(message.get("content") or ""), EMPATHY_RESPONSE_KEYWORDS)
        if message.get("role") == "patient" and _contains_any(str(message.get("content") or ""), PATIENT_EMOTION_KEYWORDS):
            return True
    return True


def _has_patient_emotion_signal(messages: list[dict[str, str]]) -> bool:
    return any(
        message.get("role") == "patient" and _contains_any(str(message.get("content") or ""), PATIENT_EMOTION_KEYWORDS)
        for message in messages
    )


def _goal_type(goal: Mapping[str, Any]) -> str:
    return str(goal.get("gap_type") or "").strip()


def _goal_trigger_stage(goal: Mapping[str, Any]) -> str:
    return str(goal.get("trigger_stage") or goal.get("stage") or "").strip()


def _goal_status(goal: Mapping[str, Any]) -> str:
    return str(goal.get("status") or "").strip()


def _normalized_stage(stage: str) -> str:
    normalized = str(stage or "case_intro")
    return "auxiliary_test" if normalized == "auxiliary_testing" else normalized


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _message_list(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    messages: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role and content:
            messages.append({"role": role, "content": content})
    return messages


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]
