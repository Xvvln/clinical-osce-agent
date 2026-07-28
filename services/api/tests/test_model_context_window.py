from __future__ import annotations

import json

from app.services.agent_rag_context_service import (
    MAX_AGENT_KNOWLEDGE_SNIPPET_CHARS,
    _serialize_agent_knowledge_item,
)
from app.services.coach_agent import CoachRequest, _coach_provider_payload
from app.services.coach_hint_context_service import (
    MAX_COACH_HYPOTHESES,
    MAX_COACH_HYPOTHESIS_CHARS,
    _recent_hypotheses,
)
from app.services.gemini_patient_responder import (
    PatientResponderRequest,
    _build_patient_provider_payload,
)
from app.services.model_context_window import (
    MAX_PROVIDER_PRIOR_MESSAGE_BYTES,
    MAX_PROVIDER_PRIOR_MESSAGE_CHARS,
    MAX_PROVIDER_PRIOR_MESSAGES,
    PROVIDER_DIALOGUE_ROLES,
    bounded_provider_messages,
)
from app.services.turn_intent_agent import (
    TurnIntentRequest,
    _turn_intent_provider_payload,
)


def _history(count: int, *, content_size: int = 0) -> list[dict[str, str]]:
    return [
        {
            "role": "student" if index % 2 == 0 else "patient",
            "content": (
                f"message-{index}"
                if content_size == 0
                else f"{index:02d}-" + ("x" * (content_size - 3))
            ),
        }
        for index in range(count)
    ]


def _history_content_utf8_bytes(messages: list[dict[str, str]]) -> int:
    return sum(len(message["content"].encode("utf-8")) for message in messages)


def test_bounded_provider_messages_keeps_recent_order_and_byte_budget() -> None:
    messages = _history(30)

    bounded = bounded_provider_messages(messages)

    assert bounded == messages[-MAX_PROVIDER_PRIOR_MESSAGES:]
    assert _history_content_utf8_bytes(bounded) <= MAX_PROVIDER_PRIOR_MESSAGE_BYTES

    oversized = bounded_provider_messages(_history(12, content_size=1_000))
    assert [message["content"][:2] for message in oversized] == [
        "08",
        "09",
        "10",
        "11",
    ]
    assert _history_content_utf8_bytes(oversized) == MAX_PROVIDER_PRIOR_MESSAGE_BYTES


def test_bounded_provider_messages_truncates_4000_emoji_without_splitting_unicode() -> None:
    bounded = bounded_provider_messages(
        [{"role": "student", "content": "🙂" * 4_000}],
    )

    assert bounded == [{"role": "student", "content": "🙂" * 1_000}]
    assert _history_content_utf8_bytes(bounded) == MAX_PROVIDER_PRIOR_MESSAGE_BYTES
    assert bounded[0]["content"].encode("utf-8").decode("utf-8") == bounded[0]["content"]


def test_bounded_provider_messages_spends_utf8_budget_newest_first() -> None:
    messages = [
        {"role": "student", "content": "最旧消息"},
        {"role": "patient", "content": "中" * 1_000},
        {"role": "coach", "content": "🙂" * 500},
    ]

    bounded = bounded_provider_messages(messages)

    assert bounded == [
        {"role": "patient", "content": "中" * 666},
        {"role": "coach", "content": "🙂" * 500},
    ]
    assert _history_content_utf8_bytes(bounded) == 3_998
    assert _history_content_utf8_bytes(bounded) <= MAX_PROVIDER_PRIOR_MESSAGE_BYTES


def test_bounded_provider_messages_filters_system_and_respects_dialogue_roles() -> None:
    messages = [
        {"role": "student", "content": "保留学生消息"},
        {"role": "system", "content": "系统指令" * 4_000},
        {"role": "tool", "content": "工具结果"},
        {"role": "assistant", "content": "未知角色"},
        {"role": "patient", "content": "保留患者消息"},
    ]

    assert bounded_provider_messages(messages) == [
        {"role": "student", "content": "保留学生消息"},
        {"role": "tool", "content": "工具结果"},
        {"role": "patient", "content": "保留患者消息"},
    ]
    assert bounded_provider_messages(
        messages,
        allowed_roles=PROVIDER_DIALOGUE_ROLES,
    ) == [
        {"role": "student", "content": "保留学生消息"},
        {"role": "patient", "content": "保留患者消息"},
    ]


def test_bounded_provider_messages_keeps_legacy_max_chars_keyword_as_byte_budget() -> None:
    expected = [{"role": "student", "content": "中🙂"}]

    assert bounded_provider_messages(
        [{"role": "student", "content": "中🙂文"}],
        max_bytes=7,
    ) == expected
    bounded_from_legacy_keyword = bounded_provider_messages(
        [{"role": "student", "content": "中🙂文"}],
        max_chars=7,
    )

    assert MAX_PROVIDER_PRIOR_MESSAGE_CHARS == MAX_PROVIDER_PRIOR_MESSAGE_BYTES
    assert bounded_from_legacy_keyword == expected
    assert _history_content_utf8_bytes(bounded_from_legacy_keyword) == 7


def test_realtime_conversation_providers_use_a_single_bounded_history() -> None:
    messages = _history(30, content_size=600)
    expected = bounded_provider_messages(messages)

    turn_intent_payload = _turn_intent_provider_payload(
        TurnIntentRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            stage="history_taking",
            student_message="现在还疼吗？",
            keyword_intent="unknown_history_intent",
            prior_messages=messages,
        )
    )
    coach_payload = _coach_provider_payload(
        CoachRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            stage="history_taking",
            prompt_kind="socratic_hint",
            base_hint="继续聚焦问诊。",
            prior_messages=messages,
        )
    )
    patient_payload, _ = _build_patient_provider_payload(
        PatientResponderRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            student_message="现在还疼吗？",
            canonical_answer="还是疼。",
            prior_messages=messages,
        )
    )

    assert turn_intent_payload["prior_messages"] == expected
    assert coach_payload["prior_messages"] == expected
    assert "prior_messages" not in patient_payload
    assert patient_payload["dialogue_context"]["recent_messages"] == expected
    assert len(expected) <= MAX_PROVIDER_PRIOR_MESSAGES
    assert _history_content_utf8_bytes(expected) <= MAX_PROVIDER_PRIOR_MESSAGE_BYTES


def test_provider_history_stays_bounded_after_redaction_and_is_not_duplicated() -> None:
    messages = [
        {
            "role": "student" if index % 2 == 0 else "patient",
            "content": "病" * 500,
        }
        for index in range(MAX_PROVIDER_PRIOR_MESSAGES)
    ]

    coach_payload = _coach_provider_payload(
        CoachRequest(
            case_id="case-without-history-match",
            case_title="测试病例",
            chief_complaint="测试主诉",
            stage="history_taking",
            prompt_kind="socratic_hint",
            base_hint="继续训练。",
            prior_messages=messages,
            hint_context={
                "conversation": {
                    "recent_turns": messages,
                },
            },
            forbidden_terms=["病"],
        )
    )
    patient_payload, _ = _build_patient_provider_payload(
        PatientResponderRequest(
            case_id="case-without-history-match",
            case_title="测试病例",
            chief_complaint="测试主诉",
            student_message="继续问诊",
            canonical_answer="继续回答",
            prior_messages=messages,
            dialogue_context={"recent_messages": messages},
            forbidden_terms=["病"],
        )
    )

    assert "prior_messages" not in coach_payload
    coach_history = coach_payload["hint_context"]["conversation"]["recent_turns"]
    assert "prior_messages" not in patient_payload
    patient_history = patient_payload["dialogue_context"]["recent_messages"]
    for history in (coach_history, patient_history):
        assert len(history) <= MAX_PROVIDER_PRIOR_MESSAGES
        assert _history_content_utf8_bytes(history) <= MAX_PROVIDER_PRIOR_MESSAGE_BYTES


def test_current_student_message_appears_once_and_never_enters_prior_history() -> None:
    current_message = "CURRENT-STUDENT-MESSAGE-SENTINEL"
    messages = _history(30)

    turn_intent_payload = _turn_intent_provider_payload(
        TurnIntentRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            stage="history_taking",
            student_message=current_message,
            keyword_intent="unknown_history_intent",
            prior_messages=messages,
        )
    )
    patient_payload, _ = _build_patient_provider_payload(
        PatientResponderRequest(
            case_id="appendicitis_001",
            case_title="急性腹痛问诊",
            chief_complaint="腹痛 1 天",
            student_message=current_message,
            canonical_answer="继续回答。",
            prior_messages=messages,
            dialogue_context={"recent_messages": messages},
        )
    )

    assert json.dumps(turn_intent_payload, ensure_ascii=False).count(
        current_message
    ) == 1
    assert json.dumps(patient_payload, ensure_ascii=False).count(
        current_message
    ) == 1
    assert all(
        current_message not in message["content"]
        for message in turn_intent_payload["prior_messages"]
    )
    assert all(
        current_message not in message["content"]
        for message in patient_payload["dialogue_context"]["recent_messages"]
    )


def test_agent_rag_context_keeps_metadata_but_bounds_provider_snippet() -> None:
    tail_sentinel = "RAG-TAIL-MUST-NOT-LEAVE-STORE"
    item = {
        "knowledge_id": "knowledge-long",
        "title": "长文教学知识",
        "text": ("安全教学摘要。" * 2_000) + tail_sentinel,
        "source_id": "manual-source",
        "case_id": "appendicitis_001",
        "visibility": "pre_submit_safe",
        "allowed_agents": ["coach"],
    }

    payload = _serialize_agent_knowledge_item(
        item,
        forbidden_terms=["急性阑尾炎"],
    )

    assert payload["reference"] == "rag_knowledge:knowledge-long"
    assert payload["source_id"] == "manual-source"
    assert len(payload["snippet"]) == MAX_AGENT_KNOWLEDGE_SNIPPET_CHARS
    assert tail_sentinel not in payload["snippet"]


def test_coach_hypothesis_context_keeps_only_a_bounded_recent_window() -> None:
    hypotheses = [
        f"{index:02d}-" + ("诊断假设" * 100)
        for index in range(20)
    ]

    bounded = _recent_hypotheses(hypotheses)

    assert len(bounded) <= MAX_COACH_HYPOTHESES
    assert sum(len(hypothesis) for hypothesis in bounded) <= (
        MAX_COACH_HYPOTHESIS_CHARS
    )
    assert bounded[-1].startswith("19-")
    assert all(not hypothesis.startswith("00-") for hypothesis in bounded)
