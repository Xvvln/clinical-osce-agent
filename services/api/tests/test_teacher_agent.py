from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from app.services import teacher_agent as module
from app.services.anthropic_chat_client import AnthropicSettings
from app.services.gemini_patient_responder import GeminiPatientSettings
from app.services.openai_compatible_chat_client import OpenAICompatibleSettings


class RecordingStructuredClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type[module.TeacherAnalysisResponse],
        temperature: float,
    ) -> module.TeacherAnalysisResponse:
        self.payloads.append(payload)
        return response_model()


class RecordingGeminiModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: object,
    ) -> object:
        self.calls.append(
            {
                "model": model,
                "contents": contents,
                "config": config,
            }
        )

        class Response:
            text = "{}"

        return Response()


class RecordingGeminiClient:
    def __init__(self) -> None:
        self.models = RecordingGeminiModels()


def _request(*, oversized: bool = False) -> module.TeacherAnalysisRequest:
    repeated = (
        "学生在此处需要把病史、查体与证据链连接起来🩺\n"
        '"不能只重复结论"\\'
    )
    detail = repeated * (16 if oversized else 1)
    cognitive_patterns = [
        {
            "pattern_id": "low_priority",
            "label": detail,
            "category": "metacognition",
            "severity": "low",
            "evidence": detail,
            "why_it_matters": detail,
            "remediation": detail,
            "source_signal_ids": [detail] * 12,
            "trigger_item_ids": [detail] * 12,
        },
        {
            "pattern_id": "high_priority",
            "label": "证据整合不足",
            "category": "evidence_synthesis",
            "severity": "high",
            "evidence": detail,
            "why_it_matters": detail,
            "remediation": detail,
            "source_signal_ids": [detail] * 12,
            "trigger_item_ids": [detail] * 12,
        },
        {
            "pattern_id": "medium_priority",
            "label": "假设形成偏晚",
            "category": "hypothesis_testing",
            "severity": "medium",
            "evidence": detail,
            "why_it_matters": detail,
            "remediation": detail,
            "source_signal_ids": [detail] * 12,
            "trigger_item_ids": [detail] * 12,
        },
    ]
    breakpoints = [
        {
            "breakpoint_id": "breakpoint_1",
            "statement": detail,
            "kind": "support",
            "status": "broken",
            "covered_evidence": [detail] * 12,
            "covered_evidence_labels": [detail] * 12,
            "missing_evidence": [detail] * 12,
            "missing_evidence_labels": [detail] * 12,
            "teacher_action": detail,
        },
        {
            "breakpoint_id": "breakpoint_2",
            "statement": detail,
            "kind": "exclude",
            "status": "broken",
            "missing_evidence_labels": [detail] * 12,
            "teacher_action": detail,
        },
    ]
    major_issue = {
        "title": detail,
        "observed_behavior": detail,
        "why_it_matters": detail,
        "correct_approach": detail,
        "next_action": detail,
        "linked_items": [detail] * 12,
    }
    coaching_section = {
        "section_id": "case_framing",
        "title": detail,
        "teacher_comment": detail,
        "why_it_matters": detail,
        "next_move": detail,
        "evidence_labels": [detail] * 12,
    }
    return module.TeacherAnalysisRequest(
        case_id="case_001",
        case_title=detail,
        score_text="72/100 分",
        missed_items=[detail] * 16,
        missed_labels=[detail] * 16,
        covered_labels=[detail] * 16,
        pending_labels=[detail] * 16,
        student_submission={
            "diagnosis": detail,
            "reasoning": detail,
        },
        clinical_reasoning_trace={
            "trace_version": "clinical_reasoning_trace_v1",
            "action_timeline": [
                {
                    "turn_index": index,
                    "action_type": "history_fact_revealed",
                    "raw_payload": detail,
                }
                for index in range(12)
            ],
            "problem_representation": {
                "semantic_qualifiers": [{"raw_payload": detail}] * 12,
            },
            "illness_script_alignment": {
                "script_elements": [{"raw_payload": detail}] * 12,
            },
            "cognitive_patterns": cognitive_patterns,
            "evidence_chain_breakpoints": breakpoints,
        },
        reasoning_trace_summary={
            "trace_version": "clinical_reasoning_trace_v1",
            "dominant_patterns": cognitive_patterns,
            "problem_representation_status": detail,
            "illness_script_status": detail,
            "evidence_synthesis_status": detail,
            "sequence_flags": [
                {
                    "flag_id": "premature_testing",
                    "label": detail,
                    "severity": "high",
                    "evidence": detail,
                }
            ],
            "action_order_summary": {
                "first_history_turn_index": 1,
                "first_physical_exam_turn_index": 3,
                "first_auxiliary_test_turn_index": 5,
                "diagnosis_submission_turn_index": 9,
            },
            "evidence_chain_breakpoints": breakpoints,
            "evidence_chain_focus": breakpoints,
        },
        base_reflection={
            "summary": detail,
            "overall_comment": detail,
            "major_issues": [major_issue] * 4,
            "teacher_coaching_review": [coaching_section] * 6,
            "reasoning_chain_review": detail,
            "next_practice_plan": [detail] * 5,
            "teacher_feedback": detail,
            "next_focus": detail,
            "teacher_note": detail,
            "reasoning_trace_summary": {
                "duplicated_full_summary": detail,
            },
        },
        source_reference_items=[
            {
                "reference": detail,
                "source_type": "training_material",
                "title": detail,
                "metadata": {"raw_document": detail},
            }
            for _ in range(8)
        ],
        longitudinal_context={
            "schema_version": "teacher_longitudinal_context_v1",
            "report_window_size": 3,
            "score_trend": {
                "order": "oldest_to_newest",
                "direction": "improving",
                "points": [
                    {"report_offset": 2, "case_id": "case_001", "score_percent": 55.0},
                    {"report_offset": 1, "case_id": "case_001", "score_percent": 70.0},
                    {"report_offset": 0, "case_id": "case_001", "score_percent": 76.0},
                ],
            },
            "current_gap_statuses": [
                {
                    "gap_id": "weak_hypothesis_testing",
                    "gap_type": "reasoning_pattern",
                    "label": "假设验证不足",
                    "status": "repeated",
                    "raw_dialogue": detail,
                }
            ],
            "recovered_gaps": [],
            "gap_status_counts": {
                "first_seen_current_window": 0,
                "repeated": 1,
                "reactivated_after_improvement": 0,
                "recovered_since_previous_report": 0,
            },
            "applied_personal_skills": [
                {
                    "report_offset": 0,
                    "title": "先形成假设再检查",
                    "skill_type": "reasoning_bridge",
                    "effect_status": "insufficient_samples",
                    "evidence": "training_skill_applied_event",
                    "hidden_fact": detail,
                }
            ],
            "evidence_boundary": "仅基于最近三份已完成训练报告。",
        },
    )


def test_teacher_provider_projection_bounds_large_multibyte_payload_without_mutating_local_request() -> None:
    request = _request(oversized=True)
    original_trace = deepcopy(request.clinical_reasoning_trace)

    first_payload = module._build_teacher_provider_payload(request)
    second_payload = module._build_teacher_provider_payload(request)
    serialized = json.dumps(first_payload, ensure_ascii=False)

    assert first_payload == second_payload
    assert len(serialized.encode("utf-8")) <= module.MAX_TEACHER_PROVIDER_PAYLOAD_BYTES
    assert json.loads(serialized) == first_payload
    assert "\ufffd" not in serialized
    assert (
        list(first_payload["clinical_reasoning_trace"])
        == [
            "trace_version",
            "cognitive_patterns",
            "evidence_chain_breakpoints",
        ]
    )
    assert "action_timeline" not in first_payload["clinical_reasoning_trace"]
    assert (
        first_payload["clinical_reasoning_trace"]["cognitive_patterns"][0][
            "pattern_id"
        ]
        == "high_priority"
    )
    assert (
        first_payload["clinical_reasoning_trace"]["evidence_chain_breakpoints"][
            0
        ]["breakpoint_id"]
        == "breakpoint_1"
    )
    assert first_payload["reasoning_trace_summary"]["dominant_patterns"]
    assert first_payload["student_submission"]["diagnosis"]
    assert first_payload["student_submission"]["reasoning"]
    assert first_payload["base_reflection"]["major_issues"]
    assert "reasoning_trace_summary" not in first_payload["base_reflection"]
    assert "metadata" not in first_payload["source_reference_items"][0]
    assert first_payload["longitudinal_context"]["current_gap_statuses"][0]["status"] == "repeated"
    assert "raw_dialogue" not in first_payload["longitudinal_context"]["current_gap_statuses"][0]
    assert "hidden_fact" not in first_payload["longitudinal_context"]["applied_personal_skills"][0]
    assert request.clinical_reasoning_trace == original_trace
    assert len(
        json.dumps(request.model_dump(), ensure_ascii=False).encode("utf-8")
    ) > module.MAX_TEACHER_PROVIDER_PAYLOAD_BYTES


def test_teacher_providers_share_the_same_bounded_projection() -> None:
    request = _request()
    openai_client = RecordingStructuredClient()
    anthropic_client = RecordingStructuredClient()
    gemini_client = RecordingGeminiClient()

    module.OpenAICompatibleTeacherAgent(
        OpenAICompatibleSettings(
            enabled=True,
            api_key="test-key",
            model="test-model",
        ),
        client=openai_client,
    )(request)
    module.AnthropicTeacherAgent(
        AnthropicSettings(
            enabled=True,
            api_key="test-key",
            model="test-model",
        ),
        client=anthropic_client,
    )(request)
    module.GeminiTeacherAgent(
        GeminiPatientSettings(
            api_key="test-key",
            model="test-model",
            proxy_url="direct",
        ),
        client=gemini_client,
    )(request)

    gemini_payload = json.loads(
        str(gemini_client.models.calls[0]["contents"])
    )
    assert openai_client.payloads[0] == anthropic_client.payloads[0]
    assert anthropic_client.payloads[0] == gemini_payload
    assert len(
        json.dumps(gemini_payload, ensure_ascii=False).encode("utf-8")
    ) <= module.MAX_TEACHER_PROVIDER_PAYLOAD_BYTES


def test_openai_compatible_teacher_uses_an_isolated_extended_timeout_budget(
    monkeypatch: Any,
) -> None:
    configured_settings: list[OpenAICompatibleSettings] = []

    class RecordingConfiguredClient:
        def __init__(self, settings: OpenAICompatibleSettings) -> None:
            configured_settings.append(settings)

    monkeypatch.setattr(module, "OpenAICompatibleChatClient", RecordingConfiguredClient)
    original = OpenAICompatibleSettings(
        enabled=True,
        api_key="test-key",
        model="test-model",
        timeout_seconds=30.0,
        attempt_timeout_seconds=12.0,
    )

    agent = module.OpenAICompatibleTeacherAgent(original)

    assert original.timeout_seconds == 30.0
    assert original.attempt_timeout_seconds == 12.0
    assert agent._settings is not original
    assert agent._settings.timeout_seconds == module.TEACHER_OPENAI_MIN_TOTAL_TIMEOUT_SECONDS
    assert agent._settings.attempt_timeout_seconds == module.TEACHER_OPENAI_MIN_ATTEMPT_TIMEOUT_SECONDS
    assert configured_settings == [agent._settings]

    already_extended = OpenAICompatibleSettings(
        enabled=True,
        api_key="test-key",
        model="test-model",
        timeout_seconds=70.0,
        attempt_timeout_seconds=27.0,
    )
    extended_agent = module.OpenAICompatibleTeacherAgent(already_extended)

    assert extended_agent._settings.timeout_seconds == 70.0
    assert extended_agent._settings.attempt_timeout_seconds == 27.0
    assert configured_settings[-1] == extended_agent._settings


def test_teacher_text_budget_counts_serialized_utf8_bytes() -> None:
    source = ('临床🩺\n"证据"\\' * 200)

    bounded = module._bounded_teacher_provider_text(
        source,
        max_json_bytes=97,
    )

    assert bounded.endswith("…")
    assert "\ufffd" not in bounded
    assert len(json.dumps(bounded, ensure_ascii=False).encode("utf-8")) <= 97
    assert (
        module._bounded_teacher_provider_text(
            source,
            max_json_bytes=97,
        )
        == bounded
    )


def test_deterministic_teacher_keeps_the_full_local_request(
    monkeypatch: Any,
) -> None:
    request = _request()
    original_trace = deepcopy(request.clinical_reasoning_trace)

    def fail_if_projected(_: module.TeacherAnalysisRequest) -> dict[str, Any]:
        raise AssertionError("deterministic analysis must not build a provider projection")

    monkeypatch.setattr(module, "_build_teacher_provider_payload", fail_if_projected)

    response = module.DeterministicTeacherAgent()(request)

    assert response.agent_id == "teacher_agent_deterministic"
    assert request.clinical_reasoning_trace == original_trace
    assert request.clinical_reasoning_trace["action_timeline"]
    assert response.clinical_thinking_profile["longitudinal_gap_assessment"] == "1 个问题连续出现"


def test_teacher_response_limits_next_practice_plan_to_three_actions() -> None:
    response = module.TeacherAnalysisResponse.model_validate(
        {
            "next_practice_plan": [
                "动作一",
                "动作二",
                "动作三",
                "动作四",
                "动作五",
            ]
        }
    )

    assert response.next_practice_plan == ["动作一", "动作二", "动作三"]
