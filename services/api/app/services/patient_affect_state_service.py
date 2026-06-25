from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.services.patient_emotion import infer_patient_emotion, normalize_patient_emotion

MAX_DEFAULT_TRAJECTORY_ITEMS = 20

EMOTION_LABEL_BY_CODE = {
    "neutral": "",
    "anxious": "焦虑",
    "pain": "痛苦",
    "confused": "困惑",
    "frustrated": "受挫",
    "relieved": "欣慰",
}
NEGATIVE_EMOTION_CODES = {"anxious", "pain", "confused", "frustrated"}

EMPATHY_RESPONSE_TERMS = (
    "理解",
    "明白",
    "能感受",
    "能体会",
    "担心",
    "害怕",
    "焦虑",
    "紧张",
    "不安",
    "顾虑",
    "辛苦",
    "难受",
    "一起",
    "帮你",
    "帮助你",
    "别怕",
)
PATIENT_PERSPECTIVE_TERMS = (
    "最担心",
    "担忧",
    "顾虑",
    "希望",
    "期待",
    "想法",
    "影响",
    "生活",
    "学习",
    "工作",
)


def build_initial_patient_affect_state() -> dict[str, Any]:
    return {
        "current_emotion": "neutral",
        "current_emotion_label": "",
        "intensity": 0,
        "unanswered_signal": False,
        "last_trigger_type": "",
        "last_trigger_turn_id": "",
        "last_student_response": "",
        "last_transition": "initial",
        "trajectory": [],
    }


def normalize_patient_affect_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = build_initial_patient_affect_state()
    if isinstance(state, Mapping):
        normalized.update({key: deepcopy(value) for key, value in state.items() if key in normalized})
    current_emotion = str(normalized.get("current_emotion") or "neutral")
    if current_emotion not in {*NEGATIVE_EMOTION_CODES, "neutral", "relieved"}:
        current_emotion = _emotion_code_from_label(current_emotion)
    normalized["current_emotion"] = current_emotion
    normalized["current_emotion_label"] = str(
        normalized.get("current_emotion_label") or EMOTION_LABEL_BY_CODE.get(current_emotion, "")
    )
    normalized["intensity"] = max(0, min(3, _int_value(normalized.get("intensity"))))
    normalized["unanswered_signal"] = bool(normalized.get("unanswered_signal"))
    trajectory = normalized.get("trajectory")
    normalized["trajectory"] = [dict(item) for item in trajectory if isinstance(item, Mapping)] if isinstance(trajectory, list) else []
    return normalized


def classify_student_affect_response(student_message: str) -> dict[str, Any]:
    message = str(student_message or "").strip()
    matched_terms = _matched_terms(message, EMPATHY_RESPONSE_TERMS)
    perspective_terms = _matched_terms(message, PATIENT_PERSPECTIVE_TERMS)
    if matched_terms:
        return {
            "response_type": "empathy_acknowledged",
            "effective": True,
            "matched_terms": matched_terms,
            "evidence": message,
        }
    if perspective_terms:
        return {
            "response_type": "patient_perspective_followup",
            "effective": True,
            "matched_terms": perspective_terms,
            "evidence": message,
        }
    return {
        "response_type": "ignored",
        "effective": False,
        "matched_terms": [],
        "evidence": message,
    }


def update_affect_before_patient_reply(
    state: Mapping[str, Any] | None,
    *,
    student_message: str,
    turn_id: str = "",
    action_type: str = "student_utterance",
    max_trajectory: int = MAX_DEFAULT_TRAJECTORY_ITEMS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    next_state = normalize_patient_affect_state(state)
    response = classify_student_affect_response(student_message)
    if not next_state.get("unanswered_signal"):
        return next_state, {
            "event": "no_pending_patient_affect_signal",
            "turn_id": turn_id,
            "student_response_type": response["response_type"],
        }

    if response["effective"]:
        next_state.update(
            {
                "current_emotion": "relieved",
                "current_emotion_label": "欣慰",
                "intensity": max(1, _int_value(next_state.get("intensity")) - 1),
                "unanswered_signal": False,
                "last_student_response": response["response_type"],
                "last_transition": "emotion_repaired",
            }
        )
        transition = {
            "event": "emotion_repaired",
            "turn_id": turn_id,
            "student_response_type": response["response_type"],
            "action_type": action_type,
            "evidence": response["evidence"],
            "matched_terms": list(response["matched_terms"]),
            "emotion": next_state["current_emotion"],
            "intensity": next_state["intensity"],
        }
        _append_transition(next_state, transition, max_trajectory=max_trajectory)
        return next_state, transition

    next_state.update(
        {
            "intensity": min(3, max(1, _int_value(next_state.get("intensity"))) + 1),
            "unanswered_signal": True,
            "last_student_response": "ignored",
            "last_transition": "emotion_ignored",
        }
    )
    transition = {
        "event": "emotion_ignored",
        "turn_id": turn_id,
        "student_response_type": "ignored",
        "action_type": action_type,
        "evidence": response["evidence"],
        "emotion": next_state["current_emotion"],
        "intensity": next_state["intensity"],
    }
    _append_transition(next_state, transition, max_trajectory=max_trajectory)
    return next_state, transition


def update_affect_after_patient_reply(
    state: Mapping[str, Any] | None,
    *,
    patient_reply: str,
    patient_emotion: str | None = "",
    turn_id: str = "",
    max_trajectory: int = MAX_DEFAULT_TRAJECTORY_ITEMS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    next_state = normalize_patient_affect_state(state)
    label = normalize_patient_emotion(patient_emotion) or infer_patient_emotion(patient_reply)
    emotion_code = _emotion_code_from_label(label)
    if emotion_code in NEGATIVE_EMOTION_CODES:
        previous_intensity = _int_value(next_state.get("intensity"))
        intensity = min(3, max(2, previous_intensity + 1 if next_state.get("unanswered_signal") else 2))
        next_state.update(
            {
                "current_emotion": emotion_code,
                "current_emotion_label": label or EMOTION_LABEL_BY_CODE[emotion_code],
                "intensity": intensity,
                "unanswered_signal": True,
                "last_trigger_type": _trigger_type_for_emotion(emotion_code),
                "last_trigger_turn_id": turn_id,
                "last_transition": "patient_signal_detected",
            }
        )
        transition = {
            "event": "patient_signal_detected",
            "turn_id": turn_id,
            "emotion": emotion_code,
            "emotion_label": next_state["current_emotion_label"],
            "intensity": intensity,
            "evidence": str(patient_reply or "").strip(),
        }
        _append_transition(next_state, transition, max_trajectory=max_trajectory)
        return next_state, transition

    if emotion_code == "relieved":
        next_state.update(
            {
                "current_emotion": "relieved",
                "current_emotion_label": "欣慰",
                "intensity": 1,
                "unanswered_signal": False,
                "last_transition": "patient_relief_observed",
            }
        )
        transition = {
            "event": "patient_relief_observed",
            "turn_id": turn_id,
            "emotion": "relieved",
            "emotion_label": "欣慰",
            "intensity": 1,
            "evidence": str(patient_reply or "").strip(),
        }
        _append_transition(next_state, transition, max_trajectory=max_trajectory)
        return next_state, transition

    return next_state, {
        "event": "no_visible_patient_affect_change",
        "turn_id": turn_id,
        "emotion": next_state["current_emotion"],
        "intensity": next_state["intensity"],
    }


def _emotion_code_from_label(label: str) -> str:
    normalized = normalize_patient_emotion(label)
    lowered = normalized.lower()
    if lowered in {"anxious", "worry", "worried", "fear", "fearful"} or normalized in {"焦虑", "担忧", "害怕", "紧张"}:
        return "anxious"
    if lowered in {"pain", "painful"} or normalized in {"痛苦", "难受"}:
        return "pain"
    if lowered in {"confused", "confusion"} or normalized in {"困惑", "犹豫"}:
        return "confused"
    if lowered in {"frustrated", "frustration"} or normalized in {"受挫", "烦躁", "不满"}:
        return "frustrated"
    if lowered in {"relieved", "relief"} or normalized in {"欣慰", "安心", "放心"}:
        return "relieved"
    return "neutral"


def _trigger_type_for_emotion(emotion_code: str) -> str:
    return {
        "anxious": "worry",
        "pain": "pain",
        "confused": "confusion",
        "frustrated": "frustration",
    }.get(emotion_code, "")


def _matched_terms(message: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term and term in message]


def _append_transition(state: dict[str, Any], transition: dict[str, Any], *, max_trajectory: int) -> None:
    trajectory = [dict(item) for item in state.get("trajectory", []) if isinstance(item, Mapping)]
    trajectory.append(dict(transition))
    state["trajectory"] = trajectory[-max(1, max_trajectory):]


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "build_initial_patient_affect_state",
    "classify_student_affect_response",
    "normalize_patient_affect_state",
    "update_affect_after_patient_reply",
    "update_affect_before_patient_reply",
]
