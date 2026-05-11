from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

KNOWN_HISTORY_INTENTS = [
    "ask_onset",
    "ask_location",
    "ask_migration",
    "ask_character",
    "ask_severity",
    "ask_fever",
    "ask_urinary",
    "ask_stool",
    "ask_associated_nausea",
    "ask_allergy",
    "ask_diet",
    "ask_travel",
    "ask_personal",
    "ask_family",
    "ask_concern",
    "ask_expectation",
    "ask_idea",
    "ask_past_medical_history",
    "unknown_history_intent",
]


class TurnIntentRequest(BaseModel):
    case_id: str
    case_title: str
    chief_complaint: str
    stage: str
    student_message: str
    keyword_intent: str
    prior_messages: list[dict[str, str]] = Field(default_factory=list)
    allowed_intents: list[str] = Field(default_factory=lambda: list(KNOWN_HISTORY_INTENTS))


class TurnIntentResponse(BaseModel):
    current_intent: str
    confidence: float = Field(default=0.5, ge=0, le=1)
    is_off_topic: bool = False
    rationale: str = ""


class DeterministicTurnIntentAgent:
    def __call__(self, request: TurnIntentRequest) -> TurnIntentResponse:
        keyword_intent = request.keyword_intent
        if keyword_intent in request.allowed_intents and keyword_intent != "unknown_history_intent":
            return TurnIntentResponse(
                current_intent=keyword_intent,
                confidence=0.9,
                is_off_topic=False,
                rationale="命中后端确定性问诊意图提示。",
            )
        return TurnIntentResponse(
            current_intent="unknown_history_intent",
            confidence=0.35,
            is_off_topic=True,
            rationale="未命中当前病例问诊意图提示，作为患者身份或训练目标引导处理。",
        )


def normalize_turn_intent_response(response: TurnIntentResponse | dict[str, Any]) -> dict[str, Any]:
    if isinstance(response, TurnIntentResponse):
        normalized = response
    else:
        normalized = TurnIntentResponse.model_validate(response)
    if normalized.current_intent not in KNOWN_HISTORY_INTENTS:
        normalized = normalized.model_copy(update={"current_intent": "unknown_history_intent", "is_off_topic": True})
    return normalized.model_dump(mode="json")


def create_default_turn_intent_agent() -> DeterministicTurnIntentAgent:
    return DeterministicTurnIntentAgent()


__all__ = [
    "KNOWN_HISTORY_INTENTS",
    "DeterministicTurnIntentAgent",
    "TurnIntentRequest",
    "TurnIntentResponse",
    "create_default_turn_intent_agent",
    "normalize_turn_intent_response",
]
