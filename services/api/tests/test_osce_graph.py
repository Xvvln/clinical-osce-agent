from datetime import UTC, datetime

import pytest

from app.graph import osce_graph as osce_graph_module
from app.graph.osce_graph import build_osce_graph, feedback_node
from app.models.rubric import LlmRubricRequest, LlmRubricResponse
from app.services import agent_rag_context_service as agent_rag_context_module
from app.services import gemini_patient_responder as patient_responder_module
from app.services.agent_rag_context_service import (
    MAX_AGENT_KNOWLEDGE_SNIPPET_CHARS,
)
from app.services.rag_knowledge_store import RagKnowledgeStore
from app.services.retrieval_index import RetrievalDocument
from app.services.turn_intent_agent import DeterministicTurnIntentAgent


def canonical_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


def silent_coach_agent(request: object) -> dict[str, object]:
    return {"should_emit": False, "hint": "", "trigger_kind": "none"}


def test_evaluation_projection_excludes_unconfigured_procedure_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_sessions: list[object] = []

    def fake_evaluate_session_rules(session: object, llm_scorer: object = None) -> dict[str, object]:
        captured_sessions.append(session)
        return {"rubric_scores": {}, "missed_items": []}

    monkeypatch.setattr(osce_graph_module, "evaluate_session_rules", fake_evaluate_session_rules)
    result = osce_graph_module.evaluation_node(
        {
            "session_id": "evaluation-safe-projection",
            "case_id": "appendicitis_001",
            "asked_questions": [],
            "requested_exams": ["abd.palpation.rebound", "vital.blood_pressure"],
            "requested_tests": ["lab.cbc", "ecg.st_segment"],
            "revealed_facts": [],
            "messages": [],
            "action_timeline": [
                {
                    "action_type": "physical_exam_requested",
                    "source_id": "abd.palpation.rebound",
                    "label": "反跳痛",
                },
                {
                    "action_type": "physical_exam_requested",
                    "source_id": "vital.blood_pressure",
                    "label": "未提供查体",
                },
                {
                    "action_type": "auxiliary_test_requested",
                    "source_id": "lab.cbc",
                    "label": "血常规",
                },
                {
                    "action_type": "auxiliary_test_requested",
                    "source_id": "ecg.st_segment",
                    "label": "未提供检查",
                },
                {
                    "action_type": "diagnosis_submitted",
                    "source_id": "final_submission",
                    "label": "提交诊断",
                },
            ],
            "final_submission": {"diagnosis": "待定", "reasoning": "证据不足"},
        }
    )

    assert result["feedback_report"] == {"rubric_scores": {}, "missed_items": []}
    assert len(captured_sessions) == 1
    evaluation_session = captured_sessions[0]
    assert getattr(evaluation_session, "requested_exams") == ["abd.palpation.rebound"]
    assert getattr(evaluation_session, "requested_tests") == ["lab.cbc"]
    assert [
        item["source_id"] for item in getattr(evaluation_session, "action_timeline")
    ] == ["abd.palpation.rebound", "lab.cbc", "final_submission"]


def mock_vector_rag_hits(monkeypatch, *knowledge_ids: str) -> None:
    monkeypatch.setattr(
        agent_rag_context_module,
        "search_retrieval_documents",
        lambda query, limit: [
            RetrievalDocument(
                reference=f"rag_knowledge:{knowledge_id}",
                source_type="rag_knowledge",
                title="vector hit",
                snippet="vector hit",
                score=max(0.0, 1.0 - index * 0.01),
            )
            for index, knowledge_id in enumerate(knowledge_ids)
        ][:limit],
        raising=False,
    )


def test_feedback_node_attaches_deep_diagnostic_contrast_analysis() -> None:
    result = feedback_node(
        {
            "session_id": "deep-report-session",
            "case_id": "appendicitis_001",
            "stage": "evaluation",
            "asked_questions": [],
            "revealed_facts": ["appendicitis_001.hf_02", "appendicitis_001.hf_05"],
            "requested_exams": [],
            "requested_tests": [],
            "final_submission": {
                "diagnosis": "急性胃肠炎",
                "reasoning": "患者恶心，我考虑急性胃肠炎。",
            },
            "feedback_report": {
                "session_id": "deep-report-session",
                "case_id": "appendicitis_001",
                "total_score": 0,
                "max_score": 100,
                "dimension_scores": {},
                "dimension_traces": {},
                "rubric_scores": {},
                "missed_items": [],
                "training_gaps": [],
            },
        }
    )

    analysis = result["feedback_report"]["deep_report_analysis"]
    diagnostic_contrast = analysis["diagnostic_contrast_analysis"]
    assert analysis["status"] == "generated"
    assert diagnostic_contrast["classification"] == "plausible_differential"
    assert diagnostic_contrast["submitted_diagnosis"] == "急性胃肠炎"
    assert diagnostic_contrast["target_diagnosis"] == "急性阑尾炎"
    assert diagnostic_contrast["matched_differential_name"] == "急性胃肠炎"
    assert any("明显腹泻" in item["label"] for item in diagnostic_contrast["evidence_against_submitted"])


def test_next_recommendations_are_ranked_grouped_and_limited() -> None:
    recommendations = osce_graph_module._build_next_recommendations(
        {
            "missed_items": [
                "history_partial",
                "exam_missing",
                "diagnosis_partial",
                "reasoning_missing",
                "humanistic_missing",
                "other_missing",
                "stale_full_score_item",
            ]
        },
        {
            "history_partial": {
                "score": 2,
                "max_score": 8,
                "dimension_id": "history_taking",
                "description": "补齐病史主线",
            },
            "exam_missing": {
                "score": 0,
                "max_score": 3,
                "dimension_id": "physical_exam",
                "description": "完成关键查体",
            },
            "diagnosis_partial": {
                "score": 7,
                "max_score": 10,
                "dimension_id": "main_diagnosis",
                "description": "校验主诊断",
            },
            "reasoning_missing": {
                "score": 0,
                "max_score": 7,
                "dimension_id": "reasoning",
                "description": "表达支持与排除依据",
            },
            "humanistic_missing": {
                "score": 0,
                "max_score": 4,
                "dimension_id": "relationship_building",
                "description": "回应患者担忧",
            },
            "other_missing": {
                "score": 0,
                "max_score": 12,
                "dimension_id": "custom_dimension",
                "description": "综合判断",
            },
            "stale_full_score_item": {
                "score": 5,
                "max_score": 5,
                "dimension_id": "reasoning",
                "description": "已经满分的项目",
            },
        },
    )

    assert recommendations == [
        "下一轮优先训练【综合能力】：“综合判断”（本轮尚有12分未获得）；"
        "下一轮完成后对照评分证据检查是否真正覆盖。",
        "下一轮优先训练【诊断与推理】：“表达支持与排除依据”、“校验主诊断”"
        "（本轮尚有10分未获得）；用“主诊断—支持证据—鉴别诊断及排除依据”完整表达。",
        "下一轮优先训练【信息采集】：“补齐病史主线”、“完成关键查体”（本轮尚有9分未获得）；"
        "围绕当前假设，按“问诊—关键查体—必要检查”补齐证据链。",
    ]
    assert all("已经满分的项目" not in item for item in recommendations)
    assert all("已完成" not in item for item in recommendations)


def base_hint_state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "session_id": "session_demo",
        "case_id": "appendicitis_001",
        "stage": "history_taking",
        "case_title": "右下腹痛教学病例",
        "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
        "hint_requested": True,
        "hint": "",
        "messages": [],
        "asked_questions": [],
        "intent_history": [],
        "agent_turn_memory": [],
        "revealed_facts": [],
        "requested_exams": [],
        "requested_tests": [],
        "student_hypotheses": [],
        "final_submission": None,
        "rubric_scores": {},
        "missed_items": [],
        "retrieved_sources": [],
        "feedback_report": None,
        "safety_flags": [],
        "evolution_candidates": [],
        "active_skill_context": {"skill_index": [], "selected_skills": [], "skipped_reasons": []},
    }
    state.update(overrides)
    return state


def test_current_intents_from_state_prefers_authoritative_intent_list() -> None:
    state = base_hint_state(
        current_intent="ask_location",
        current_intents=["ask_character", "ask_severity"],
        turn_analysis={"current_intents": ["ask_character", "ask_severity"]},
    )

    current_intents = osce_graph_module._current_intents_from_state(state)

    assert current_intents == ["ask_character", "ask_severity"]


def active_skill_context() -> dict[str, list[dict[str, object]]]:
    return {
        "skill_index": [
            {
                "skill_id": "skill_selected_history",
                "title": "腹痛迁移追问训练",
                "scope": "personal",
                "stage_scope": ["history_taking"],
                "trigger_item_ids": ["ht_migration"],
                "priority": 12,
                "why_candidate": "当前缺口命中 ht_migration",
                "summary": "腹痛迁移追问训练：近期反复遗漏迁移痛追问。",
                "when_to_use": "学生问诊已开始但未形成腹痛演变时间线时使用。",
                "when_not_to_use": "空白开局或学生已经覆盖疼痛演变时间线时不要使用。",
                "risk": "不得透露标准诊断或隐藏事实。",
            }
        ],
        "selected_skills": [
            {
                "skill_id": "skill_selected_history",
                "title": "腹痛迁移追问训练",
                "suggested_strategy": "先围绕疼痛迁移和加重过程做聚焦追问。",
                "intervention": {
                    "teaching_goal": "帮助学生先建立疼痛演变时间线。",
                    "coach_strategy": "先围绕疼痛迁移和加重过程做聚焦追问。",
                    "hint_ladder": ["先追问起病部位。", "再追问是否迁移。"],
                    "reflection_prompt": "复盘本轮是否先建立腹痛演变时间线。",
                    "avoid": ["不得透露标准诊断。"],
                },
                "stage_scope": ["history_taking"],
                "trigger_item_ids": ["ht_migration"],
                "priority": 12,
                "why_candidate": "当前缺口命中 ht_migration",
            }
        ],
        "skipped_reasons": [
            {"skill_id": "skill_legacy_generic", "reason": "not_selected_top_k"},
        ],
    }


def humanistic_active_skill_context() -> dict[str, list[dict[str, object]]]:
    return {
        "skill_index": [
            {
                "skill_id": "skill_relationship_repair",
                "title": "患者情绪回应训练",
                "stage_scope": ["history_taking"],
                "trigger_item_ids": ["rel_empathy"],
            }
        ],
        "selected_skills": [
            {
                "skill_id": "skill_relationship_repair",
                "skill_type": "relationship_repair",
                "title": "患者情绪回应训练",
                "suggested_strategy": "先识别情绪，再继续问诊。",
                "intervention": {
                    "teaching_goal": "识别并回应患者当前情绪。",
                    "coach_strategy": "先用一句话承认情绪，再继续问诊。",
                    "hint_ladder": ["先识别情绪。", "再继续医学问诊。"],
                    "avoid": ["不得虚构患者情绪。"],
                },
            }
        ],
        "skipped_reasons": [],
    }


def test_osce_graph_loads_case_intro_state() -> None:
    graph = build_osce_graph()

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "",
            "case_title": "",
            "chief_complaint": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["case_id"] == "appendicitis_001"
    assert result["stage"] == "case_intro"
    assert result["case_title"] == "右下腹痛教学病例"
    assert result["chief_complaint"] == "转移性右下腹痛 24 小时，伴恶心、低热"


def test_osce_graph_routes_history_question_and_returns_patient_reply() -> None:
    graph = build_osce_graph(patient_responder=canonical_patient_responder)

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "case_intro",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "什么时候开始疼的？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["stage"] == "history_taking"
    assert "current_intent" not in result
    assert result["current_intents"] == ["ask_onset"]
    assert result["reply"] == "24 小时前开始，最初是上腹部隐痛。"
    assert "急性阑尾炎" not in result["reply"]
    assert result["revealed_facts"] == ["appendicitis_001.hf_01"]
    assert result["asked_questions"] == ["什么时候开始疼的？"]
    assert result["intent_history"] == ["ask_onset"]
    assert result["messages"] == [
        {"role": "student", "content": "什么时候开始疼的？"},
        {"role": "patient", "content": "24 小时前开始，最初是上腹部隐痛。"},
    ]


def test_osce_graph_reveals_multiple_history_facts_from_one_student_message() -> None:
    captured_patient_requests: list[object] = []

    def fake_patient_responder(request: object) -> str:
        captured_patient_requests.append(request)
        return str(getattr(request, "canonical_answer"))

    graph = build_osce_graph(
        patient_responder=fake_patient_responder,
        coach_agent=silent_coach_agent,
        turn_intent_agent=DeterministicTurnIntentAgent(),
    )

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "case_intro",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "怎么个痛法？有多痛？哪里痛？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert "current_intent" not in result
    assert result["current_intents"] == ["ask_location", "ask_character", "ask_severity"]
    assert result["reply"] == (
        "开始在上腹部，大约 8 小时前转移并固定到右下腹。；"
        "现在是持续性胀痛，行走时加重。；"
        "大约 VAS 6/10，属于中等偏重的疼痛。"
    )
    assert result["revealed_facts"] == [
        "appendicitis_001.hf_02",
        "appendicitis_001.hf_03",
        "appendicitis_001.hf_04",
    ]
    assert result["asked_questions"] == ["怎么个痛法？有多痛？哪里痛？"]
    assert result["intent_history"] == ["ask_location", "ask_character", "ask_severity"]
    patient_request = captured_patient_requests[0]
    assert [item["fact_id"] for item in getattr(patient_request, "answerable_fact_candidates")] == [
        "appendicitis_001.hf_02",
        "appendicitis_001.hf_03",
        "appendicitis_001.hf_04",
    ]
    assert getattr(patient_request, "deterministic_hints")["answerable_fact_ids"] == [
        "appendicitis_001.hf_02",
        "appendicitis_001.hf_03",
        "appendicitis_001.hf_04",
    ]
    assert result["agent_turn_memory"][0]["revealed_fact_id"] == "appendicitis_001.hf_02"
    assert result["agent_turn_memory"][0]["revealed_fact_ids"] == [
        "appendicitis_001.hf_02",
        "appendicitis_001.hf_03",
        "appendicitis_001.hf_04",
    ]
    assert result["agent_turn_memory"][0]["current_intents"] == ["ask_location", "ask_character", "ask_severity"]
    expected_action_timeline = [
        {
            "turn_index": 1,
            "action_type": "history_fact_revealed",
            "source_id": "appendicitis_001.hf_02",
            "label": "追问疼痛部位及转移特征",
        },
        {
            "turn_index": 2,
            "action_type": "history_fact_revealed",
            "source_id": "appendicitis_001.hf_03",
            "label": "追问疼痛性质",
        },
        {
            "turn_index": 3,
            "action_type": "history_fact_revealed",
            "source_id": "appendicitis_001.hf_04",
            "label": "追问疼痛程度",
        },
    ]
    assert [
        {
            "turn_index": item["turn_index"],
            "action_type": item["action_type"],
            "source_id": item["source_id"],
            "label": item["label"],
        }
        for item in result["action_timeline"]
    ] == expected_action_timeline
    assert all(isinstance(item.get("message_turn_index"), int) and item["message_turn_index"] >= 1 for item in result["action_timeline"])


def test_osce_graph_only_marks_provider_selected_facts_as_revealed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = osce_graph_module._load_case("appendicitis_001").model_copy(deep=True)
    base_fact = case.history.hidden_facts[0]
    case.history.hidden_facts = [
        base_fact.model_copy(
            update={
                "fact_id": f"appendicitis_001.hf_bulk_{index:02d}",
                "canonical_answer": f"本轮可披露事实 {index:02d}😀",
                "variants": [f"口语事实 {index:02d}🙂"],
                "trigger_intents": ["ask_location"],
            }
        )
        for index in range(36)
    ]
    monkeypatch.setattr(osce_graph_module, "_load_case", lambda case_id: case)
    captured_patient_requests: list[object] = []

    def fake_patient_responder(request: object) -> str:
        captured_patient_requests.append(request)
        return str(getattr(request, "canonical_answer"))

    graph = build_osce_graph(
        patient_responder=fake_patient_responder,
        coach_agent=silent_coach_agent,
        turn_intent_agent=DeterministicTurnIntentAgent(),
    )
    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "case_intro",
            "case_title": case.case_title,
            "chief_complaint": case.chief_complaint,
            "student_message": "现在是哪里痛？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    expected_fact_ids = [
        f"appendicitis_001.hf_bulk_{index:02d}"
        for index in range(patient_responder_module.MAX_PATIENT_PROVIDER_FACT_CANDIDATES)
    ]
    patient_request = captured_patient_requests[0]
    request_candidates = getattr(patient_request, "answerable_fact_candidates")
    provider_payload, provider_fact_id_map = patient_responder_module._build_patient_provider_payload(
        patient_request
    )
    assert [candidate["fact_id"] for candidate in request_candidates] == expected_fact_ids
    assert result["revealed_facts"] == expected_fact_ids
    assert getattr(patient_request, "revealed_fact_ids") == expected_fact_ids
    assert getattr(patient_request, "deterministic_hints")["answerable_fact_ids"] == expected_fact_ids
    assert getattr(patient_request, "canonical_answer") == "；".join(
        f"本轮可披露事实 {index:02d}😀"
        for index in range(patient_responder_module.MAX_PATIENT_PROVIDER_FACT_CANDIDATES)
    )
    assert list(provider_fact_id_map.values()) == expected_fact_ids
    assert "本轮可披露事实 12😀" not in str(provider_payload)


def test_osce_graph_reveals_case_specific_multi_intent_history_facts() -> None:
    def fake_patient_responder(request: object) -> str:
        return str(getattr(request, "canonical_answer"))

    graph = build_osce_graph(
        patient_responder=fake_patient_responder,
        coach_agent=silent_coach_agent,
        turn_intent_agent=DeterministicTurnIntentAgent(),
    )

    result = graph.invoke(
        {
            "case_id": "acs_001",
            "stage": "case_intro",
            "case_title": "胸痛伴出汗教学病例",
            "chief_complaint": "胸骨后压榨性胸痛 2 小时，伴大汗。",
            "student_message": "胸痛什么时候开始的？什么性质？有没有放射痛？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert set(result["current_intents"]) == {"ask_onset", "ask_character", "ask_radiation"}
    assert result["reply"] == (
        "今天上午活动后开始胸口痛，到现在 2 个小时了。；"
        "胸口像被压着一样闷痛，不是针扎样疼。；"
        "疼痛会往左肩和左上臂放射。"
    )
    assert result["revealed_facts"] == [
        "acs_001.hf_01",
        "acs_001.hf_02",
        "acs_001.hf_03",
    ]


def test_osce_graph_keeps_keyword_intents_when_model_returns_unknown_for_multi_question() -> None:
    captured_patient_requests: list[object] = []

    def overly_cautious_turn_intent_agent(request: object) -> dict[str, object]:
        return {
            "current_intent": "unknown_history_intent",
            "confidence": 0.36,
            "is_off_topic": False,
            "unknown_kind": "possible_missed_medical_intent",
            "possible_intents": ["ask_location", "ask_character", "ask_severity"],
            "rationale": "模型认为问题还不够具体。",
        }

    def fake_patient_responder(request: object) -> str:
        captured_patient_requests.append(request)
        return str(getattr(request, "canonical_answer"))

    graph = build_osce_graph(
        patient_responder=fake_patient_responder,
        coach_agent=silent_coach_agent,
        turn_intent_agent=overly_cautious_turn_intent_agent,
    )

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "case_intro",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "怎么个痛法？有多痛？哪里痛？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert "current_intent" not in result
    assert result["current_intents"] == ["ask_location", "ask_character", "ask_severity"]
    assert result["reply"] == (
        "开始在上腹部，大约 8 小时前转移并固定到右下腹。；"
        "现在是持续性胀痛，行走时加重。；"
        "大约 VAS 6/10，属于中等偏重的疼痛。"
    )
    assert result["revealed_facts"] == [
        "appendicitis_001.hf_02",
        "appendicitis_001.hf_03",
        "appendicitis_001.hf_04",
    ]
    patient_request = captured_patient_requests[0]
    assert getattr(patient_request, "deterministic_hints")["current_intents"] == [
        "ask_location",
        "ask_character",
        "ask_severity",
    ]


def test_osce_graph_routes_patient_identity_unknown_kind_without_forced_coach_hint() -> None:
    captured_patient_requests: list[object] = []

    def fake_patient_responder(request: object) -> str:
        captured_patient_requests.append(request)
        return str(getattr(request, "canonical_answer"))

    def failing_coach_agent(request: object) -> dict[str, object]:
        raise AssertionError("identity clarification should not call coach, skill router, or RAG-dependent review")

    graph = build_osce_graph(patient_responder=fake_patient_responder, coach_agent=failing_coach_agent)

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "case_intro",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "你是谁？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["stage"] == "history_taking"
    assert "current_intent" not in result
    assert result["current_intents"] == []
    assert result["reply"] == "我是这次来看肚子疼的病人。"
    assert "转移性右下腹痛" not in result["reply"]
    assert "低热" not in result["reply"]
    assert "就诊的患者" not in result["reply"]
    assert result["messages"] == [
        {"role": "student", "content": "你是谁？"},
        {"role": "patient", "content": result["reply"]},
    ]
    assert result["asked_questions"] == []
    assert result["intent_history"] == ["unknown_history_intent"]
    assert result["revealed_facts"] == []
    assert "急性阑尾炎" not in result["reply"]
    assert len(captured_patient_requests) == 1
    assert getattr(captured_patient_requests[0], "turn_policy") == "patient_identity_redirect"
    assert getattr(captured_patient_requests[0], "current_intents") == []
    assert getattr(captured_patient_requests[0], "deterministic_hints")["keyword_intent"] == "unknown_history_intent"
    assert getattr(captured_patient_requests[0], "deterministic_hints")["unknown_kind"] == "patient_identity_unclear"
    assert result["agent_turn_memory"][0]["reply_role"] == "patient"
    assert result["agent_turn_memory"][0]["turn_policy"] == "patient_identity_redirect"
    assert result["agent_turn_memory"][0]["agent_path"] == ["input_router_node", "patient_response_node"]
    assert len(result["agent_turn_memory"]) == 1
    assert [step["step_id"] for step in result["processing_trace"]] == ["intent", "case_context", "patient_reply", "response"]


def test_osce_graph_skips_heavy_agents_for_social_greeting_without_revealing_case_fact() -> None:
    captured_patient_requests: list[object] = []

    def fake_turn_intent_agent(request: object) -> dict[str, object]:
        return {
            "current_intents": [],
            "confidence": 0.91,
            "is_off_topic": False,
            "unknown_kind": "social_greeting",
            "possible_intents": [],
            "rationale": "学生只是寒暄，没有提出具体问诊问题。",
        }

    def fake_patient_responder(request: object) -> str:
        captured_patient_requests.append(request)
        return "医生您好，我是因为肚子疼来看的。"

    def failing_coach_agent(request: object) -> dict[str, object]:
        raise AssertionError("social greeting should not call coach, skill router, or RAG-dependent review")

    graph = build_osce_graph(
        patient_responder=fake_patient_responder,
        turn_intent_agent=fake_turn_intent_agent,
        coach_agent=failing_coach_agent,
    )

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "case_intro",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "哈",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["current_intents"] == []
    assert result["reply"] == "医生您好，我是因为肚子疼来看的。"
    assert result["messages"] == [
        {"role": "student", "content": "哈"},
        {"role": "patient", "content": "医生您好，我是因为肚子疼来看的。"},
    ]
    assert result["revealed_facts"] == []
    assert len(captured_patient_requests) == 1
    assert getattr(captured_patient_requests[0], "turn_policy") == "social_greeting_response"
    assert getattr(captured_patient_requests[0], "answerable_fact_candidates") == []
    assert result["agent_turn_memory"][0]["turn_analysis"]["unknown_kind"] == "social_greeting"
    assert result["agent_turn_memory"][0]["turn_policy"] == "social_greeting_response"
    assert result["agent_turn_memory"][0]["agent_path"] == ["input_router_node", "patient_response_node"]
    assert len(result["agent_turn_memory"]) == 1
    assert [step["step_id"] for step in result["processing_trace"]] == ["intent", "case_context", "patient_reply", "response"]


def test_osce_graph_attaches_patient_emotion_to_visible_patient_reply() -> None:
    def fake_patient_responder(request: object) -> str:
        return "我有点害怕是不是很严重。"

    graph = build_osce_graph(patient_responder=fake_patient_responder, coach_agent=silent_coach_agent)

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "你现在最担心什么？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["reply"] == "我有点害怕是不是很严重。"
    assert result["messages"][-1] == {
        "role": "patient",
        "content": "我有点害怕是不是很严重。",
        "emotion": "担忧",
    }
    assert result["patient_affect_state"]["current_emotion"] == "anxious"
    assert result["patient_affect_state"]["unanswered_signal"] is True
    assert result["patient_affect_state"]["last_transition"] == "patient_signal_detected"
    patient_turn = next(turn for turn in result["agent_turn_memory"] if turn.get("reply_role") == "patient")
    assert patient_turn["patient_affect_transition"]["event"] == "patient_signal_detected"


def test_osce_graph_injects_patient_affect_state_and_student_repair_into_patient_responder() -> None:
    captured_requests: list[object] = []

    def fake_turn_intent_agent(request: object) -> dict[str, object]:
        return {
            "current_intent": "ask_onset",
            "current_intents": ["ask_onset"],
            "confidence": 0.9,
            "is_off_topic": False,
            "rationale": "测试中固定为问诊意图。",
        }

    def fake_patient_responder(request: object) -> dict[str, object]:
        captured_requests.append(request)
        return {"reply": "谢谢，你这么说我稍微安心一点。", "emotion": "欣慰", "fact_ids_used": []}

    graph = build_osce_graph(
        patient_responder=fake_patient_responder,
        turn_intent_agent=fake_turn_intent_agent,
        coach_agent=silent_coach_agent,
    )

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "我理解你的担心，我们先把疼痛情况问清楚，再判断下一步。",
            "current_intent": "",
            "reply": "",
            "messages": [
                {"role": "student", "content": "你现在最担心什么？"},
                {"role": "patient", "content": "我有点害怕是不是要开刀。", "emotion": "担忧"},
            ],
            "patient_affect_state": {
                "current_emotion": "anxious",
                "current_emotion_label": "担忧",
                "intensity": 2,
                "unanswered_signal": True,
                "last_transition": "patient_signal_detected",
                "last_student_response": "",
                "trajectory": [
                    {
                        "turn_id": "turn:1",
                        "event": "patient_signal_detected",
                        "emotion": "anxious",
                        "evidence": "我有点害怕是不是要开刀。",
                    }
                ],
            },
            "asked_questions": ["你现在最担心什么？"],
            "intent_history": ["ask_ideas_concerns_expectations"],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
            "active_skill_context": {"skill_index": [], "selected_skills": [], "skipped_reasons": []},
        }
    )

    assert len(captured_requests) == 1
    dialogue_context = getattr(captured_requests[0], "dialogue_context")
    assert dialogue_context["patient_affect_state"]["current_emotion"] == "relieved"
    assert dialogue_context["patient_affect_state"]["unanswered_signal"] is False
    assert dialogue_context["student_affect_response"]["response_type"] == "empathy_acknowledged"
    assert result["patient_affect_state"]["current_emotion"] == "relieved"
    assert result["patient_affect_state"]["unanswered_signal"] is False
    patient_turn = next(turn for turn in result["agent_turn_memory"] if turn.get("reply_role") == "patient")
    assert patient_turn["patient_affect_transition"]["event"] == "patient_relief_observed"


def test_osce_graph_routes_possible_missed_medical_unknown_kind_to_specific_hint() -> None:
    captured_patient_requests: list[object] = []
    captured_coach_requests: list[object] = []

    def fake_patient_responder(request: object) -> str:
        captured_patient_requests.append(request)
        return str(getattr(request, "canonical_answer"))

    def fake_coach_agent(request: object) -> dict[str, object]:
        captured_coach_requests.append(request)
        return {
            "should_emit": False,
            "hint": "",
            "trigger_kind": "none",
        }

    graph = build_osce_graph(patient_responder=fake_patient_responder, coach_agent=fake_coach_agent)

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "case_intro",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "还有没有其他不舒服？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert "current_intent" not in result
    assert result["current_intents"] == []
    assert result["reply"] == "这个问题有点宽泛，我不太确定你具体想问哪方面。"
    assert result["messages"][-1] == {
        "role": "coach",
        "content": "这个问题可能和问诊有关，但还不够具体。可以追问起病时间、疼痛部位、疼痛性质、疼痛程度或伴随症状。",
    }
    assert getattr(captured_patient_requests[0], "turn_policy") == "possible_missed_medical_intent"
    assert getattr(captured_patient_requests[0], "deterministic_hints")["unknown_kind"] == "possible_missed_medical_intent"
    assert getattr(captured_patient_requests[0], "deterministic_hints")["possible_intents"][:2] == ["ask_associated_nausea", "ask_fever"]
    assert len(captured_coach_requests) == 1
    assert getattr(captured_coach_requests[0], "base_hint") == (
        "这个问题可能和问诊有关，但还不够具体。可以追问起病时间、疼痛部位、疼痛性质、疼痛程度或伴随症状。"
    )
    assert result["agent_turn_memory"][0]["turn_analysis"]["unknown_kind"] == "possible_missed_medical_intent"
    assert result["agent_turn_memory"][1]["turn_policy"] == "passive_review_hint"


def test_osce_graph_routes_unclassified_unknown_kind_without_claiming_missing_case_info() -> None:
    captured_patient_requests: list[object] = []

    def fake_patient_responder(request: object) -> str:
        captured_patient_requests.append(request)
        return "医生，您刚才说的我没太听明白，可以再问得具体一点吗？"

    def failing_coach_agent(request: object) -> dict[str, object]:
        raise AssertionError("unclassified inputs should not call coach, skill router, or RAG-dependent review")

    graph = build_osce_graph(patient_responder=fake_patient_responder, coach_agent=failing_coach_agent)

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "case_intro",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "嗯",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert "current_intent" not in result
    assert result["current_intents"] == []
    assert result["reply"] == "医生，您刚才说的我没太听明白，可以再问得具体一点吗？"
    assert result["messages"] == [
        {"role": "student", "content": "嗯"},
        {"role": "patient", "content": "医生，您刚才说的我没太听明白，可以再问得具体一点吗？"},
    ]
    assert result["revealed_facts"] == []
    assert len(captured_patient_requests) == 1
    assert getattr(captured_patient_requests[0], "turn_policy") == "unclassified_input"
    assert getattr(captured_patient_requests[0], "current_intents") == []
    assert getattr(captured_patient_requests[0], "answerable_fact_candidates") == []
    assert result["agent_turn_memory"][0]["turn_analysis"]["unknown_kind"] == "unclassified_input"
    assert result["agent_turn_memory"][0]["turn_policy"] == "unclassified_input"
    assert result["agent_turn_memory"][0]["agent_path"] == ["input_router_node", "patient_response_node"]
    assert len(result["agent_turn_memory"]) == 1
    assert [step["step_id"] for step in result["processing_trace"]] == ["intent", "case_context", "patient_reply", "response"]


def test_osce_graph_answers_patient_profile_gender_without_falling_back_to_unknown() -> None:
    captured_patient_requests: list[object] = []

    def fake_patient_responder(request: object) -> str:
        captured_patient_requests.append(request)
        return str(getattr(request, "canonical_answer"))

    graph = build_osce_graph(patient_responder=fake_patient_responder, coach_agent=silent_coach_agent)

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "你是男的女的？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert "current_intent" not in result
    assert result["current_intents"] == ["ask_patient_gender"]
    assert result["reply"] == "我是男的。"
    assert result["revealed_facts"] == []
    assert result["asked_questions"] == []
    assert result["messages"] == [
        {"role": "student", "content": "你是男的女的？"},
        {"role": "patient", "content": "我是男的。"},
    ]
    assert len(captured_patient_requests) == 1
    patient_request = captured_patient_requests[0]
    assert getattr(patient_request, "turn_policy") == "patient_profile_disclosure"
    assert getattr(patient_request, "answerable_fact_candidates") == [
        {
            "fact_id": "appendicitis_001.profile.gender",
            "topic": "患者公开画像",
            "slot": "gender",
            "canonical_answer": "我是男的。",
            "variants": ["男的"],
            "trigger_intents": ["ask_patient_gender"],
            "source_reference": "case:appendicitis_001.patient_profile.gender",
        }
    ]
    assert getattr(patient_request, "deterministic_hints")["answerable_fact_ids"] == ["appendicitis_001.profile.gender"]
    assert result["agent_turn_memory"][0]["turn_policy"] == "patient_profile_disclosure"
    assert result["agent_turn_memory"][0]["source_references"] == []


def test_osce_graph_routes_answer_boundary_through_coach_agent_and_records_memory() -> None:
    captured_requests: list[object] = []

    def failing_patient_responder(request: object) -> str:
        raise AssertionError("answer boundary should not use patient responder")

    def fake_coach_agent(request: object) -> dict[str, object]:
        captured_requests.append(request)
        return {
            "should_emit": True,
            "hint": "不能直接告诉你标准答案。请继续通过问诊、查体和辅助检查收集证据。",
            "trigger_kind": "answer_boundary",
        }

    graph = build_osce_graph(patient_responder=failing_patient_responder, coach_agent=fake_coach_agent)

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "标准答案是什么？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert "current_intent" not in result
    assert result["current_intents"] == ["answer_request_redirect"]
    assert result["messages"] == [
        {"role": "student", "content": "标准答案是什么？"},
        {"role": "coach", "content": result["reply"]},
    ]
    assert result["asked_questions"] == []
    assert result["revealed_facts"] == []
    assert len(captured_requests) == 1
    assert getattr(captured_requests[0], "prompt_kind") == "answer_boundary_redirect"
    assert getattr(captured_requests[0], "base_hint") == "不能直接告诉你标准答案。请继续通过问诊、查体和辅助检查收集证据，或在准备好后提交诊断。"
    assert result["agent_turn_memory"][0]["turn_policy"] == "answer_boundary_redirect"
    assert result["agent_turn_memory"][0]["reply_role"] == "coach"
    assert result["agent_turn_memory"][0]["turn_analysis"]["current_intents"] == ["answer_request_redirect"]


def test_osce_graph_uses_injected_patient_responder_for_history_reply() -> None:
    captured_requests: list[object] = []

    def fake_patient_responder(request: object) -> str:
        captured_requests.append(request)
        return "医生，我是一阵一阵开始不舒服的，后来疼痛更明显了。"

    graph = build_osce_graph(patient_responder=fake_patient_responder)

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "case_intro",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "什么时候开始疼的？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["reply"] == "医生，我是一阵一阵开始不舒服的，后来疼痛更明显了。"
    assert "24 小时前开始" not in result["reply"]
    assert result["revealed_facts"] == ["appendicitis_001.hf_01"]
    assert len(captured_requests) == 1
    patient_request = captured_requests[0]
    assert getattr(patient_request, "canonical_answer") == "24 小时前开始，最初是上腹部隐痛。"
    assert getattr(patient_request, "student_message") == "什么时候开始疼的？"
    assert getattr(patient_request, "answerable_fact_candidates") == [
        {
            "fact_id": "appendicitis_001.hf_01",
            "topic": "现病史",
            "slot": "onset",
            "canonical_answer": "24 小时前开始，最初是上腹部隐痛。",
            "variants": ["昨天这个点开始的", "差不多一天前开始"],
            "trigger_intents": ["ask_onset", "ask_when_started"],
            "source_reference": "case:appendicitis_001.history.appendicitis_001.hf_01",
        }
    ]
    patient_private_context = getattr(patient_request, "patient_private_context")
    assert patient_private_context["case_id"] == "appendicitis_001"
    assert patient_private_context["patient_profile"]["age"] == "22岁"
    assert patient_private_context["patient_profile"]["gender"] == "男"
    assert "history" not in patient_private_context
    assert "marital_status" not in patient_private_context["patient_profile"]
    assert "social_background" not in patient_private_context["patient_profile"]
    assert "idea" not in patient_private_context["patient_profile"]
    assert "concern" not in patient_private_context["patient_profile"]
    assert "expectation" not in patient_private_context["patient_profile"]
    assert "diagnosis" not in patient_private_context
    forbidden_context = getattr(patient_request, "forbidden_context")
    assert "diagnosis_terms" not in forbidden_context
    assert "differential_diagnosis_terms" not in forbidden_context
    assert forbidden_context["blocked_reference_types"] == ["diagnosis", "rubric", "treatment", "dosage"]
    assert "rubric" not in patient_private_context
    assert (
        "有恶心，没吐出来，低热约 37.8 ℃；没有明显腹泻，也没有尿频、尿急或肉眼血尿。"
        in getattr(patient_request, "protected_fact_texts")
    )
    assert getattr(patient_request, "deterministic_hints")["answerable_fact_ids"] == ["appendicitis_001.hf_01"]


def test_osce_graph_projects_humanistic_skill_to_patient_style_without_strategy_or_facts() -> None:
    captured_requests: list[object] = []

    def capturing_patient_responder(request: object) -> str:
        captured_requests.append(request)
        return str(getattr(request, "canonical_answer"))

    graph = build_osce_graph(
        patient_responder=capturing_patient_responder,
        coach_agent=silent_coach_agent,
    )

    result = graph.invoke(
        base_hint_state(
            stage="history_taking",
            student_message="你现在最担心什么？",
            active_skill_context=humanistic_active_skill_context(),
        )
    )

    assert len(captured_requests) == 1
    role_policy = getattr(captured_requests[0], "role_skill_policy")
    assert role_policy["active"] is True
    assert role_policy["practice_focus"] == [
        "让当前已存在的患者情绪更容易被学生感知和回应"
    ]
    assert "skill_relationship_repair" not in str(role_policy)
    assert "先用一句话承认情绪" not in str(role_policy)
    patient_turn = result["agent_turn_memory"][0]
    assert patient_turn["selected_skill_ids"] == ["skill_relationship_repair"]
    audit_policy = patient_turn["turn_analysis"]["patient_skill_role_policy"]
    assert audit_policy["active"] is True
    assert audit_policy["source_skill_ids"] == ["skill_relationship_repair"]


def test_patient_responder_receives_revealed_facts_and_dialogue_context() -> None:
    captured_requests: list[object] = []

    def fake_turn_intent_agent(request: object) -> dict[str, object]:
        return {
            "current_intent": "ask_allergy",
            "current_intents": ["ask_allergy"],
            "confidence": 0.93,
            "is_off_topic": False,
            "rationale": "学生追问过敏史。",
        }

    def fake_patient_responder(request: object) -> str:
        captured_requests.append(request)
        return str(getattr(request, "canonical_answer"))

    graph = build_osce_graph(
        patient_responder=fake_patient_responder,
        turn_intent_agent=fake_turn_intent_agent,
        coach_agent=silent_coach_agent,
    )

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "有对什么过敏吗？",
            "current_intent": "",
            "reply": "",
            "messages": [
                {"role": "student", "content": "有对什么过敏吗？"},
                {"role": "patient", "content": "没有药物过敏，吃东西也没发现过敏。"},
            ],
            "asked_questions": ["有对什么过敏吗？"],
            "intent_history": ["ask_allergy"],
            "agent_turn_memory": [],
            "revealed_facts": ["appendicitis_001.hf_07"],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
            "active_skill_context": {"skill_index": [], "selected_skills": [], "skipped_reasons": []},
        }
    )

    assert result["revealed_facts"] == ["appendicitis_001.hf_07"]
    assert len(captured_requests) == 1
    patient_request = captured_requests[0]
    assert getattr(patient_request, "canonical_answer") == "否认药物和食物过敏。"
    assert getattr(patient_request, "revealed_fact_ids") == ["appendicitis_001.hf_07"]
    assert not hasattr(patient_request, "repeated_fact_ids")
    assert getattr(patient_request, "turn_policy") == "history_fact_disclosure"

    dialogue_context = getattr(patient_request, "dialogue_context")
    assert "is_repeated_fact_question" not in dialogue_context
    assert dialogue_context["current_intents"] == ["ask_allergy"]
    assert dialogue_context["answerable_fact_ids"] == ["appendicitis_001.hf_07"]
    assert dialogue_context["revealed_fact_ids"] == ["appendicitis_001.hf_07"]
    assert "repeated_fact_ids" not in dialogue_context
    assert dialogue_context["asked_questions"] == ["有对什么过敏吗？"]
    assert dialogue_context["intent_history"] == ["ask_allergy"]
    assert dialogue_context["recent_messages"] == [
        {"role": "student", "content": "有对什么过敏吗？"},
        {"role": "patient", "content": "没有药物过敏，吃东西也没发现过敏。"},
    ]


def test_osce_graph_uses_injected_turn_intent_agent_before_patient_reply() -> None:
    captured_intent_requests: list[object] = []
    captured_patient_requests: list[object] = []

    def fake_turn_intent_agent(request: object) -> dict[str, object]:
        captured_intent_requests.append(request)
        return {
            "current_intent": "ask_onset",
            "confidence": 0.93,
            "is_off_topic": False,
            "rationale": "学生在询问腹痛持续时间。",
        }

    def fake_patient_responder(request: object) -> str:
        captured_patient_requests.append(request)
        return str(getattr(request, "canonical_answer"))

    graph = build_osce_graph(
        patient_responder=fake_patient_responder,
        turn_intent_agent=fake_turn_intent_agent,
    )

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "腹痛持续多长时间了？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert "current_intent" not in result
    assert result["current_intents"] == ["ask_onset"]
    assert result["reply"] == "24 小时前开始，最初是上腹部隐痛。"
    assert result["revealed_facts"] == ["appendicitis_001.hf_01"]
    assert len(captured_intent_requests) == 1
    assert getattr(captured_intent_requests[0], "student_message") == "腹痛持续多长时间了？"
    assert getattr(captured_intent_requests[0], "keyword_intent") == "unknown_history_intent"
    assert len(captured_patient_requests) == 1
    patient_hints = getattr(captured_patient_requests[0], "deterministic_hints")
    assert patient_hints["turn_analysis"] == {
        "current_intents": ["ask_onset"],
        "confidence": 0.93,
        "is_off_topic": False,
        "rationale": "学生在询问腹痛持续时间。",
    }
    assert "current_intent" not in result["agent_turn_memory"][0]
    assert result["agent_turn_memory"][0]["current_intents"] == ["ask_onset"]
    assert result["agent_turn_memory"][0]["turn_analysis"] == patient_hints["turn_analysis"]


def test_osce_graph_passively_reviews_regular_history_turn_without_visible_hint() -> None:
    captured_coach_requests: list[object] = []

    def fake_coach_agent(request: object) -> dict[str, object]:
        captured_coach_requests.append(request)
        return {"should_emit": False, "hint": "", "trigger_kind": "none"}

    graph = build_osce_graph(patient_responder=canonical_patient_responder, coach_agent=fake_coach_agent)

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "什么时候开始疼的？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["reply"] == "24 小时前开始，最初是上腹部隐痛。"
    assert result["messages"] == [
        {"role": "student", "content": "什么时候开始疼的？"},
        {"role": "patient", "content": "24 小时前开始，最初是上腹部隐痛。"},
    ]
    assert len(captured_coach_requests) == 1
    assert getattr(captured_coach_requests[0], "prompt_kind") == "passive_turn_review"
    assert getattr(captured_coach_requests[0], "base_hint") == ""
    assert result["agent_turn_memory"][-1]["reply_role"] == "coach"
    assert result["agent_turn_memory"][-1]["reply"] == ""
    assert result["agent_turn_memory"][-1]["turn_policy"] == "passive_review_silent"


def test_osce_graph_passive_coach_failure_does_not_drop_patient_reply() -> None:
    def failing_coach_agent(request: object) -> dict[str, object]:
        raise RuntimeError("coach quota exhausted")

    graph = build_osce_graph(patient_responder=canonical_patient_responder, coach_agent=failing_coach_agent)

    result = graph.invoke(
        base_hint_state(
            hint_requested=False,
            student_message="什么时候开始疼的？",
            current_intent="",
            reply="",
        )
    )

    assert result["reply"] == "24 小时前开始，最初是上腹部隐痛。"
    assert result["messages"] == [
        {"role": "student", "content": "什么时候开始疼的？"},
        {"role": "patient", "content": "24 小时前开始，最初是上腹部隐痛。"},
    ]
    assert result["agent_turn_memory"][-1]["reply_role"] == "coach"
    assert result["agent_turn_memory"][-1]["reply"] == ""
    assert result["agent_turn_memory"][-1]["turn_policy"] == "passive_review_unavailable"
    assert result["agent_turn_memory"][-1]["turn_analysis"]["coach_error_type"] == "RuntimeError"


def test_osce_graph_passive_coach_suppresses_unforced_model_hint_after_successful_fact_disclosure() -> None:
    captured_coach_requests: list[object] = []

    def noisy_coach_agent(request: object) -> dict[str, object]:
        captured_coach_requests.append(request)
        return {
            "should_emit": True,
            "hint": "模型误判想打断学生，但这轮已经成功问到病史事实。",
            "trigger_kind": "model_overreach",
        }

    graph = build_osce_graph(patient_responder=canonical_patient_responder, coach_agent=noisy_coach_agent)

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "什么时候开始疼的？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert len(captured_coach_requests) == 1
    assert getattr(captured_coach_requests[0], "base_hint") == ""
    assert result["messages"] == [
        {"role": "student", "content": "什么时候开始疼的？"},
        {"role": "patient", "content": "24 小时前开始，最初是上腹部隐痛。"},
    ]
    assert result["agent_turn_memory"][-1]["reply"] == ""
    assert result["agent_turn_memory"][-1]["turn_policy"] == "passive_review_silent"


def test_osce_graph_short_circuits_off_topic_after_intent_without_heavy_agents() -> None:
    def failing_patient_responder(request: object) -> str:
        raise AssertionError("off-topic turns should not call the patient responder")

    def failing_coach_agent(request: object) -> dict[str, object]:
        raise AssertionError("off-topic turns should not call coach, skill router, or RAG-dependent review")

    graph = build_osce_graph(patient_responder=failing_patient_responder, coach_agent=failing_coach_agent)

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "student_message": "你喜欢打游戏吗？",
            "current_intent": "",
            "reply": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "agent_turn_memory": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["reply"] == "这个我不太了解，我这次主要是肚子疼来看的。"
    assert result["messages"] == [
        {"role": "student", "content": "你喜欢打游戏吗？"},
        {"role": "patient", "content": result["reply"]},
        {
            "role": "coach",
            "content": "这轮训练先回到腹痛问诊。可以从起病时间、疼痛部位、性质、程度和伴随症状继续问。",
        },
    ]
    assert result["revealed_facts"] == []
    assert result["current_intents"] == []
    assert result["agent_turn_memory"][0]["agent_path"] == ["input_router_node", "unknown_history_redirect_node"]
    assert result["agent_turn_memory"][0]["turn_policy"] == "off_topic_redirect"
    assert result["agent_turn_memory"][1]["agent_path"] == ["input_router_node", "unknown_history_redirect_node"]
    assert result["agent_turn_memory"][1]["turn_policy"] == "intent_short_circuit_hint"
    assert [step["step_id"] for step in result["processing_trace"]] == ["intent", "response"]


def test_osce_graph_does_not_fallback_when_patient_responder_fails() -> None:
    def failing_patient_responder(request: object) -> str:
        raise RuntimeError("patient llm unavailable")

    graph = build_osce_graph(patient_responder=failing_patient_responder)

    with pytest.raises(RuntimeError, match="patient llm unavailable"):
        graph.invoke(
            {
                "case_id": "appendicitis_001",
                "stage": "case_intro",
                "case_title": "右下腹痛教学病例",
                "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
                "student_message": "什么时候开始疼的？",
                "current_intent": "",
                "reply": "",
                "messages": [],
                "asked_questions": [],
                "intent_history": [],
                "revealed_facts": [],
                "requested_exams": [],
                "requested_tests": [],
                "student_hypotheses": [],
                "final_submission": None,
                "rubric_scores": {},
                "missed_items": [],
                "retrieved_sources": [],
                "feedback_report": None,
                "safety_flags": [],
                "evolution_candidates": [],
            }
        )


def test_osce_graph_routes_expanded_appendicitis_history_intents() -> None:
    graph = build_osce_graph(patient_responder=canonical_patient_responder)
    examples = [
        ("疼痛有没有转移？", "ask_migration", "appendicitis_001.hf_02", "转移并固定到右下腹"),
        ("疼痛是什么性质？", "ask_character", "appendicitis_001.hf_03", "持续性胀痛"),
        ("现在疼痛有几分？", "ask_severity", "appendicitis_001.hf_04", "VAS 6/10"),
        ("有没有发热？", "ask_fever", "appendicitis_001.hf_05", "低热约 37.8 ℃"),
        ("有没有尿频尿急？", "ask_urinary", "appendicitis_001.hf_05", "没有尿频、尿急"),
        ("有没有药物过敏？", "ask_allergy", "appendicitis_001.hf_07", "否认药物和食物过敏"),
        ("最近饮食和旅行情况怎么样？", "ask_diet", "appendicitis_001.hf_08", "近期无旅行史"),
        ("家族里有类似腹痛吗？", "ask_family", "appendicitis_001.hf_09", "无类似腹痛病史"),
        ("你现在最担心什么？", "ask_concern", "appendicitis_001.hf_10", "害怕要开刀"),
    ]

    for message, expected_intent, expected_fact_id, expected_reply_fragment in examples:
        result = graph.invoke(
            {
                "case_id": "appendicitis_001",
                "stage": "history_taking",
                "case_title": "右下腹痛教学病例",
                "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
                "student_message": message,
                "current_intent": "",
                "reply": "",
                "messages": [],
                "asked_questions": [],
                "intent_history": [],
                "revealed_facts": [],
                "requested_exams": [],
                "requested_tests": [],
                "student_hypotheses": [],
                "final_submission": None,
                "rubric_scores": {},
                "missed_items": [],
                "retrieved_sources": [],
                "feedback_report": None,
                "safety_flags": [],
                "evolution_candidates": [],
            }
        )

        assert "current_intent" not in result
        assert expected_intent in result["current_intents"]
        assert result["revealed_facts"] == [expected_fact_id]
        assert expected_reply_fragment in result["reply"]


def test_osce_graph_routes_natural_student_history_wording_to_patient_replies() -> None:
    graph = build_osce_graph(patient_responder=canonical_patient_responder)
    examples = [
        ("疼在哪儿？", "ask_location", "appendicitis_001.hf_02", "转移并固定到右下腹"),
        ("腹痛是怎么个疼法？", "ask_character", "appendicitis_001.hf_03", "持续性胀痛"),
        ("有多痛？", "ask_severity", "appendicitis_001.hf_04", "VAS 6/10"),
        ("有没有想吐？", "ask_associated_nausea", "appendicitis_001.hf_05", "有恶心"),
    ]

    for message, expected_intent, expected_fact_id, expected_reply_fragment in examples:
        result = graph.invoke(
            {
                "case_id": "appendicitis_001",
                "stage": "history_taking",
                "case_title": "右下腹痛教学病例",
                "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
                "student_message": message,
                "current_intent": "",
                "reply": "",
                "messages": [],
                "asked_questions": [],
                "intent_history": [],
                "revealed_facts": [],
                "requested_exams": [],
                "requested_tests": [],
                "student_hypotheses": [],
                "final_submission": None,
                "rubric_scores": {},
                "missed_items": [],
                "retrieved_sources": [],
                "feedback_report": None,
                "safety_flags": [],
                "evolution_candidates": [],
            }
        )

        assert "current_intent" not in result
        assert result["current_intents"] == [expected_intent]
        assert result["messages"][-1]["role"] == "patient"
        assert result["revealed_facts"] == [expected_fact_id]
        assert expected_reply_fragment in result["reply"]


def test_osce_graph_returns_physical_exam_result_from_case_library() -> None:
    graph = build_osce_graph()

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "exam_code": "abd.palpation.rebound",
            "exam_name_cn": "",
            "exam_result": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "revealed_facts": ["appendicitis_001.hf_01"],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["stage"] == "physical_exam"
    assert result["exam_code"] == "abd.palpation.rebound"
    assert result["exam_name_cn"] == "反跳痛（Blumberg 征）"
    assert result["exam_result"] == "右下腹反跳痛阳性。"
    assert result["requested_exams"] == ["abd.palpation.rebound"]


def test_osce_graph_marks_patient_affect_ignored_when_exam_requested_before_emotion_response() -> None:
    graph = build_osce_graph()

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "exam_code": "abd.palpation.rebound",
            "exam_name_cn": "",
            "exam_result": "",
            "messages": [
                {"role": "student", "content": "你现在最担心什么？"},
                {"role": "patient", "content": "我有点害怕是不是要开刀。", "emotion": "担忧"},
            ],
            "patient_affect_state": {
                "current_emotion": "anxious",
                "current_emotion_label": "担忧",
                "intensity": 2,
                "unanswered_signal": True,
                "last_transition": "patient_signal_detected",
                "trajectory": [],
            },
            "asked_questions": ["你现在最担心什么？"],
            "intent_history": ["ask_ideas_concerns_expectations"],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
            "agent_turn_memory": [],
            "action_timeline": [],
        }
    )

    assert result["patient_affect_state"]["unanswered_signal"] is True
    assert result["patient_affect_state"]["last_transition"] == "emotion_ignored"
    assert any(event["action_type"] == "patient_affect_ignored" for event in result["action_timeline"])


def test_osce_graph_returns_auxiliary_test_result_from_case_library() -> None:
    graph = build_osce_graph()

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "physical_exam",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "test_code": "lab.cbc",
            "test_name_cn": "",
            "test_result": "",
            "messages": [],
            "asked_questions": [],
            "intent_history": [],
            "revealed_facts": ["appendicitis_001.hf_01"],
            "requested_exams": ["abd.palpation.rebound"],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["stage"] == "auxiliary_test"
    assert result["test_code"] == "lab.cbc"
    assert result["test_name_cn"] == "血常规"
    assert result["test_result"] == "白细胞 14.2×10^9/L，中性粒细胞比例 85%。"
    assert result["requested_tests"] == ["lab.cbc"]


def test_osce_graph_records_final_diagnosis_submission() -> None:
    graph = build_osce_graph()

    result = graph.invoke(
        {
            "case_id": "appendicitis_001",
            "stage": "auxiliary_test",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "submitted_diagnosis": "急性阑尾炎",
            "submitted_reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
            "messages": [],
            "asked_questions": ["什么时候开始疼的？"],
            "intent_history": ["ask_onset"],
            "revealed_facts": ["appendicitis_001.hf_01"],
            "requested_exams": ["abd.palpation.rebound"],
            "requested_tests": ["lab.cbc"],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["stage"] == "diagnosis_submission"
    assert result["final_submission"] == {
        "diagnosis": "急性阑尾炎",
        "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
    }
    assert result["student_hypotheses"] == ["急性阑尾炎"]


def test_osce_graph_generates_rule_evaluation_report() -> None:
    graph = build_osce_graph()
    report_generation_started_at = datetime.now(UTC)

    result = graph.invoke(
        {
            "session_id": "session_demo",
            "case_id": "appendicitis_001",
            "stage": "diagnosis_submission",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "report_requested": True,
            "messages": [],
            "asked_questions": ["什么时候开始疼的？"],
            "intent_history": ["ask_onset"],
            "revealed_facts": ["appendicitis_001.hf_01"],
            "requested_exams": ["abd.palpation.rebound"],
            "requested_tests": ["lab.cbc"],
            "student_hypotheses": ["急性阑尾炎"],
            "final_submission": {
                "diagnosis": "急性阑尾炎",
                "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
            },
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )
    report_generation_finished_at = datetime.now(UTC)

    feedback_report = result["feedback_report"]

    assert result["stage"] == "feedback"
    assert feedback_report["report_id"] == "session_demo_report"
    assert feedback_report["session_id"] == "session_demo"
    assert feedback_report["case_id"] == "appendicitis_001"
    assert feedback_report["total_score"] == 22
    assert feedback_report["dimension_scores"] == {
        "history_taking": 2,
        "physical_exam": 4,
        "auxiliary_test": 3,
        "main_diagnosis": 10,
        "differential_diagnosis": 0,
        "reasoning": 3,
        "narrative_medicine": 0,
        "communication_skill": 0,
        "medical_ethics": 0,
        "relationship_building": 0,
    }
    assert "dimension_traces" in feedback_report
    assert result["rubric_scores"]["ht_onset"]["score"] == 2
    assert result["rubric_scores"]["ht_migration"]["score"] == 0
    assert result["rubric_scores"]["pe_rebound"]["score"] == 4
    assert result["rubric_scores"]["ax_cbc"]["score"] == 3
    assert result["rubric_scores"]["dx_main"]["score"] == 10
    assert result["rubric_scores"]["rs_support"]["score"] == 3
    assert "ht_migration" in result["missed_items"]
    assert "推理表达覆盖关键排除依据：评分轨迹未找到足够证据。" in feedback_report["reasoning_errors"]
    assert feedback_report["strengths"][:4] == [
        "追问起病时间：已完成。",
        "检查反跳痛：已完成。",
        "申请血常规：已完成。",
        "主要诊断命中急性阑尾炎：已完成。",
    ]
    assert feedback_report["strengths"][4] == (
        "推理表达覆盖典型阑尾炎支持证据（转移性痛、压痛反跳痛、WBC/CRP 升高、超声）：已部分覆盖（3/8）。"
    )
    assert (
        "推理表达覆盖典型阑尾炎支持证据（转移性痛、压痛反跳痛、WBC/CRP 升高、超声）："
        "已部分覆盖（3/8），仍需补充未覆盖要点。"
    ) in feedback_report["reasoning_errors"]
    assert len(feedback_report["next_recommendations"]) == 3
    assert feedback_report["next_recommendations"][0].startswith(
        "下一轮优先训练【人文沟通】："
    )
    assert "本轮尚有30分未获得" in feedback_report["next_recommendations"][0]
    assert feedback_report["next_recommendations"][1].startswith(
        "下一轮优先训练【信息采集】："
    )
    assert "本轮尚有29分未获得" in feedback_report["next_recommendations"][1]
    assert feedback_report["next_recommendations"][2].startswith(
        "下一轮优先训练【诊断与推理】："
    )
    assert "本轮尚有19分未获得" in feedback_report["next_recommendations"][2]
    assert all("已完成" not in item for item in feedback_report["next_recommendations"])
    assert feedback_report["knowledge_recommendations"][:3] == [
        {
            "reference": "rubric:appendicitis_001_rubric.item.ht_migration",
            "title": "追问疼痛部位及转移特征",
            "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
        },
        {
            "reference": "rubric:appendicitis_001_rubric.item.ht_character",
            "title": "追问疼痛性质",
            "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
        },
        {
            "reference": "rubric:appendicitis_001_rubric.item.ht_severity",
            "title": "追问疼痛程度",
            "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
        },
    ]
    assert {
        "reference": "case:acs_001",
        "title": "胸痛伴出汗教学病例",
        "reason": "病例库暂无同模块病例，推荐用于下一轮对照训练。",
    } in feedback_report["knowledge_recommendations"]
    assert result["retrieved_sources"][:5] == [
        "case:appendicitis_001",
        "source:fareez_osce_2022",
        "rubric:appendicitis_001_rubric.item.ht_migration",
        "rubric:appendicitis_001_rubric.item.ht_character",
        "rubric:appendicitis_001_rubric.item.ht_severity",
    ]
    assert "evidence:appendicitis_001.hf_01" in result["retrieved_sources"]
    assert "evidence:abd.palpation.rebound" in result["retrieved_sources"]
    assert "evidence:lab.cbc" in result["retrieved_sources"]
    assert "evidence:急性阑尾炎" in result["retrieved_sources"]
    assert feedback_report["source_references"] == result["retrieved_sources"]
    assert feedback_report["source_reference_items"][0] == {
        "reference": "case:appendicitis_001",
        "source_type": "case",
        "title": "右下腹痛教学病例",
        "metadata": {},
    }
    assert feedback_report["source_reference_items"][1]["reference"] == "source:fareez_osce_2022"
    assert feedback_report["source_reference_items"][1]["source_type"] == "source"
    assert feedback_report["source_reference_items"][1]["metadata"]["license"] == "CC BY 4.0"
    assert feedback_report["clinical_reasoning_trace"]["trace_version"] == "clinical_reasoning_trace_v1"
    assert {
        "weak_problem_representation",
        "thin_differential_reasoning",
    } <= {pattern["pattern_id"] for pattern in feedback_report["clinical_reasoning_trace"]["cognitive_patterns"]}
    assert {
        "reference": "rubric:appendicitis_001_rubric.item.ht_migration",
        "source_type": "rubric",
        "title": "追问疼痛部位及转移特征",
        "metadata": {},
    } in feedback_report["source_reference_items"]
    assert {
        "kind": "strength",
        "text": "主要诊断命中急性阑尾炎：已完成。",
        "rubric_item_id": "dx_main",
        "source_references": ["rubric:appendicitis_001_rubric.item.dx_main", "evidence:急性阑尾炎"],
    } in feedback_report["explanation_source_items"]
    assert {
        "kind": "reasoning_error",
        "text": "提出输尿管结石并说明排除依据：评分轨迹未找到足够证据。",
        "rubric_item_id": "dxd_urolith",
        "source_references": ["rubric:appendicitis_001_rubric.item.dxd_urolith"],
    } in feedback_report["explanation_source_items"]
    assert {
        "kind": "strength",
        "text": (
            "推理表达覆盖典型阑尾炎支持证据（转移性痛、压痛反跳痛、WBC/CRP 升高、超声）："
            "已部分覆盖（3/8）。"
        ),
        "rubric_item_id": "rs_support",
        "source_references": [
            "rubric:appendicitis_001_rubric.item.rs_support",
            "evidence:abd.palpation.rebound",
            "evidence:lab.cbc",
        ],
    } in feedback_report["explanation_source_items"]
    assert feedback_report["feedback_summary"] == "已根据评分轨迹生成教学反馈，内容仅用于 OSCE 训练复盘。"
    created_at = datetime.fromisoformat(feedback_report["created_at"].replace("Z", "+00:00"))
    assert created_at.utcoffset() == UTC.utcoffset(created_at)
    assert report_generation_started_at <= created_at <= report_generation_finished_at
    report_text = str(feedback_report)
    for forbidden_term in ["用药剂量", "治疗方案", "手术方案", "处置建议"]:
        assert forbidden_term not in report_text


def test_osce_graph_uses_injected_llm_scorer_for_llm_rubric_items() -> None:
    captured_requests: list[LlmRubricRequest] = []

    def fake_scorer(request: LlmRubricRequest) -> LlmRubricResponse:
        captured_requests.append(request)
        return LlmRubricResponse(
            score=9,
            covered_evidence=request.required_evidence[:1],
            missing_evidence=request.required_evidence[1:],
            rationale="排除依据覆盖尿常规，仍缺少完整鉴别说明。",
        )

    graph = build_osce_graph(llm_scorer=fake_scorer)

    result = graph.invoke(
        {
            "session_id": "session_demo",
            "case_id": "appendicitis_001",
            "stage": "diagnosis_submission",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "report_requested": True,
            "messages": [],
            "asked_questions": ["什么时候开始疼的？"],
            "intent_history": ["ask_onset"],
            "revealed_facts": ["appendicitis_001.hf_01", "appendicitis_001.hf_02"],
            "requested_exams": ["abd.palpation.rebound"],
            "requested_tests": ["lab.cbc"],
            "student_hypotheses": ["急性阑尾炎"],
            "final_submission": {
                "diagnosis": "急性阑尾炎",
                "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
            },
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["feedback_report"]["total_score"] == sum(result["feedback_report"]["dimension_scores"].values()) == 30
    assert result["feedback_report"]["dimension_scores"]["differential_diagnosis"] == 0
    assert result["feedback_report"]["dimension_scores"]["reasoning"] == 7
    assert result["rubric_scores"]["rs_support"]["score"] == 3
    assert result["rubric_scores"]["rs_exclude"]["score"] == 4
    assert result["feedback_report"]["llm_reasoning_feedback"] == [
        {
            "rubric_item_id": "rs_exclude",
            "description": "推理表达覆盖关键排除依据",
            "score": 4,
            "max_score": 4,
            "covered_evidence": ["appendicitis_001.rp_05"],
            "missing_evidence": ["appendicitis_001.rp_06"],
            "rationale": "排除依据覆盖尿常规，仍缺少完整鉴别说明。",
        },
    ]
    assert {
        "kind": "llm_reasoning_feedback",
        "text": "排除依据覆盖尿常规，仍缺少完整鉴别说明。",
        "rubric_item_id": "rs_exclude",
        "source_references": ["rubric:appendicitis_001_rubric.item.rs_exclude", "evidence:appendicitis_001.rp_05"],
    } in result["feedback_report"]["explanation_source_items"]
    assert [request.rubric_item_id for request in captured_requests] == ["rs_exclude"]
    assert captured_requests[0].student_final_reasoning == "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"


def test_osce_graph_returns_socratic_hint_as_coach_message_without_revealing_diagnosis() -> None:
    graph = build_osce_graph()

    result = graph.invoke(
        {
            "session_id": "session_demo",
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "hint_requested": True,
            "hint": "",
            "messages": [
                {"role": "student", "content": "什么时候开始疼的？"},
                {"role": "patient", "content": "24 小时前开始，最初是上腹部隐痛。"},
            ],
            "asked_questions": ["什么时候开始疼的？"],
            "intent_history": ["ask_onset"],
            "revealed_facts": ["appendicitis_001.hf_01"],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["stage"] == "history_taking"
    assert result["hint"] == "先围绕疼痛的部位、性质、程度、伴随症状和既往史继续追问，不要急于下诊断。"
    assert result["messages"][-1] == {"role": "coach", "content": result["hint"]}
    assert result["final_submission"] is None
    assert result["rubric_scores"] == {}
    for forbidden_term in ["急性阑尾炎", "阑尾炎", "手术", "治疗方案"]:
        assert forbidden_term not in result["hint"]


def test_osce_graph_uses_injected_coach_agent_for_hint_and_records_agent_turn(monkeypatch) -> None:
    captured_requests: list[object] = []
    mock_vector_rag_hits(
        monkeypatch,
        "case:appendicitis_001:coach:abdominal_pain_history_sequence",
    )

    def fake_coach_agent(request: object) -> dict[str, str]:
        captured_requests.append(request)
        return {"hint": "先追问疼痛是否转移，再决定下一步查体。"}

    graph = build_osce_graph(coach_agent=fake_coach_agent)

    result = graph.invoke(
        {
            "session_id": "session_demo",
            "case_id": "appendicitis_001",
            "stage": "history_taking",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "hint_requested": True,
            "hint": "",
            "messages": [
                {"role": "student", "content": "什么时候开始疼的？"},
                {"role": "patient", "content": "24 小时前开始，最初是上腹部隐痛。"},
            ],
            "asked_questions": ["什么时候开始疼的？"],
            "intent_history": ["ask_onset"],
            "agent_turn_memory": [],
            "revealed_facts": ["appendicitis_001.hf_01"],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
        }
    )

    assert result["hint"] == "先追问疼痛是否转移，再决定下一步查体。"
    assert result["messages"][-1] == {"role": "coach", "content": result["hint"]}
    assert len(captured_requests) == 1
    assert getattr(captured_requests[0], "base_hint") == "先围绕疼痛的部位、性质、程度、伴随症状和既往史继续追问，不要急于下诊断。"
    assert getattr(captured_requests[0], "prompt_kind") == "socratic_hint"
    clinical_state = getattr(captured_requests[0], "clinical_reasoning_state")
    assert clinical_state["pedagogical_phase"] == "needs_physical_exam"
    assert clinical_state["next_best_action"]["action_type"] == "request_physical_exam"
    assert "查体" in clinical_state["socratic_question"]
    assert "急性阑尾炎" not in str(getattr(captured_requests[0], "model_dump")())
    assert len(result["agent_turn_memory"]) == 1
    agent_turn = result["agent_turn_memory"][0]
    turn_analysis = agent_turn["turn_analysis"]
    assert {
        "turn_id": agent_turn["turn_id"],
        "student_message": agent_turn["student_message"],
        "reply": agent_turn["reply"],
        "reply_role": agent_turn["reply_role"],
        "current_intents": agent_turn["current_intents"],
        "turn_policy": agent_turn["turn_policy"],
        "agent_path": agent_turn["agent_path"],
        "revealed_fact_id": agent_turn["revealed_fact_id"],
        "safety_flags": agent_turn["safety_flags"],
    } == {
        "turn_id": "turn:1",
        "student_message": "请求提示",
        "reply": result["hint"],
        "reply_role": "coach",
        "current_intents": ["socratic_hint"],
        "turn_policy": "teaching_hint",
        "agent_path": ["socratic_hint_node", "coach_agent"],
        "revealed_fact_id": None,
        "safety_flags": [],
    }
    assert turn_analysis["current_intents"] == ["socratic_hint"]
    assert turn_analysis["confidence"] == 1.0
    assert turn_analysis["is_off_topic"] is False
    assert turn_analysis["rationale"] == "学生请求教学提示。"
    assert turn_analysis["hint_policy"]["intent"] == "history_progression"
    assert turn_analysis["hint_policy"]["candidate_goal_types"] == []
    assert "rag_knowledge:case:appendicitis_001:coach:abdominal_pain_history_sequence" in agent_turn[
        "source_references"
    ]
    assert agent_turn["knowledge_references"] == agent_turn["source_references"]
    assert agent_turn["retrieved_knowledge_context"]
    assert [step["step_id"] for step in agent_turn["processing_trace"]] == [
        "case_context",
        "rag",
        "skill",
        "coach",
        "response",
    ]
    assert isinstance(agent_turn["processing_duration_ms"], int)


def test_osce_graph_socratic_hint_falls_back_to_base_hint_when_coach_agent_fails() -> None:
    def failing_coach_agent(request: object) -> dict[str, object]:
        raise RuntimeError("coach model returned invalid json")

    graph = build_osce_graph(coach_agent=failing_coach_agent)

    result = graph.invoke(base_hint_state())

    assert result["hint"] == "你还没有开始问诊。第一步先用开放式问题建立病史主线，例如起病时间、疼痛部位、性质、程度和伴随症状。"
    assert result["messages"][-1] == {"role": "coach", "content": result["hint"]}
    agent_turn = result["agent_turn_memory"][-1]
    assert agent_turn["turn_policy"] == "teaching_hint_unavailable"
    assert agent_turn["agent_path"] == ["socratic_hint_node", "coach_agent_unavailable"]
    assert agent_turn["turn_analysis"]["coach_unavailable"] is True
    assert agent_turn["turn_analysis"]["coach_error_type"] == "RuntimeError"


def test_osce_graph_socratic_hint_uses_active_selected_skill_context() -> None:
    captured_requests: list[object] = []

    def echo_base_hint_coach_agent(request: object) -> dict[str, object]:
        captured_requests.append(request)
        return {"should_emit": True, "hint": str(getattr(request, "base_hint")), "trigger_kind": "socratic_hint"}

    graph = build_osce_graph(coach_agent=echo_base_hint_coach_agent)

    result = graph.invoke(
        base_hint_state(
            active_skill_context=active_skill_context(),
            evolution_candidates=["旧技能：旧策略不应再进入 Coach 提示。"],
            messages=[
                {"role": "student", "content": "什么时候开始疼的？"},
                {"role": "patient", "content": "24 小时前开始。"},
            ],
            asked_questions=["什么时候开始疼的？"],
            revealed_facts=["appendicitis_001.hf_01"],
        )
    )

    assert len(captured_requests) == 2
    assert getattr(captured_requests[0], "prompt_kind") == "skill_router"
    assert getattr(captured_requests[0], "skill_context") == []
    assert getattr(captured_requests[0], "hint_context")["skill_selection"]["available_skill_ids"] == [
        "skill_selected_history"
    ]
    assert getattr(captured_requests[1], "prompt_kind") == "socratic_hint"
    assert getattr(captured_requests[1], "skill_context") == [
        "腹痛迁移追问训练：先围绕疼痛迁移和加重过程做聚焦追问。\n"
        "教学目标：帮助学生先建立疼痛演变时间线。\n"
        "分层提示：先追问起病部位。 / 再追问是否迁移。\n"
        "复盘提示：复盘本轮是否先建立腹痛演变时间线。\n"
        "避免事项：不得透露标准诊断。"
    ]
    teacher_role_policy = getattr(captured_requests[1], "hint_context")["skill_selection"]["role_policy"]
    assert teacher_role_policy["active"] is True
    assert teacher_role_policy["precedence"][:3] == [
        "case_fact_boundary",
        "current_hint_policy",
        "safety_boundary",
    ]
    assert teacher_role_policy["interventions"][0]["skill_id"] == "skill_selected_history"
    assert "腹痛迁移追问训练" in getattr(captured_requests[1], "base_hint")
    assert "旧技能" not in getattr(captured_requests[1], "base_hint")
    assert result["agent_turn_memory"][-1]["selected_skill_ids"] == ["skill_selected_history"]
    assert result["agent_turn_memory"][-1]["skill_context"] == [
        "腹痛迁移追问训练：先围绕疼痛迁移和加重过程做聚焦追问。\n"
        "教学目标：帮助学生先建立疼痛演变时间线。\n"
        "分层提示：先追问起病部位。 / 再追问是否迁移。\n"
        "复盘提示：复盘本轮是否先建立腹痛演变时间线。\n"
        "避免事项：不得透露标准诊断。"
    ]
    assert result["agent_turn_memory"][-1]["turn_analysis"]["routed_skill_context"]["selection_policy"] == (
        "deterministic_fallback"
    )
    assert result["agent_turn_memory"][-1]["turn_analysis"]["routed_skill_context"]["role_policy"] == {
        "version": "skill_role_policy.v1",
        "active": True,
        "source_skill_ids": ["skill_selected_history"],
    }


def test_osce_graph_socratic_hint_does_not_inject_skill_before_student_action() -> None:
    captured_requests: list[object] = []

    def echo_base_hint_coach_agent(request: object) -> dict[str, object]:
        captured_requests.append(request)
        return {"should_emit": True, "hint": str(getattr(request, "base_hint")), "trigger_kind": "socratic_hint"}

    graph = build_osce_graph(coach_agent=echo_base_hint_coach_agent)

    result = graph.invoke(base_hint_state(active_skill_context=active_skill_context()))

    assert len(captured_requests) == 2
    request_payload = captured_requests[0].model_dump()
    assert getattr(captured_requests[0], "prompt_kind") == "skill_router"
    assert getattr(captured_requests[0], "skill_context") == []
    assert request_payload["hint_context"]["skill_selection"]["available_skill_ids"] == ["skill_selected_history"]
    assert getattr(captured_requests[1], "prompt_kind") == "socratic_hint"
    assert getattr(captured_requests[1], "skill_context") == []
    assert "role_policy" not in getattr(captured_requests[1], "hint_context")["skill_selection"]
    assert result["hint"] == "你还没有开始问诊。第一步先用开放式问题建立病史主线，例如起病时间、疼痛部位、性质、程度和伴随症状。"
    assert "本轮训练重点" not in result["hint"]
    assert result["agent_turn_memory"][-1]["selected_skill_ids"] == []
    assert "skill_context" not in result["agent_turn_memory"][-1]
    assert result["agent_turn_memory"][-1]["turn_analysis"]["routed_skill_context"]["selected_skill_ids"] == []


def test_osce_graph_socratic_hint_keeps_onboarding_before_untriggered_training_goal() -> None:
    captured_requests: list[object] = []

    def echo_base_hint_coach_agent(request: object) -> dict[str, object]:
        captured_requests.append(request)
        return {"should_emit": True, "hint": str(getattr(request, "base_hint")), "trigger_kind": "socratic_hint"}

    graph = build_osce_graph(coach_agent=echo_base_hint_coach_agent)

    result = graph.invoke(
        base_hint_state(
            stage="case_intro",
            active_skill_context={
                "skill_index": [],
                "selected_skills": [],
                "skipped_reasons": [],
                "current_training_gaps": [
                    {
                        "gap_type": "relationship_empathy_missing",
                        "label": "患者表达担忧后给予共情回应",
                        "trigger_stage": "history_taking",
                        "next_training_action": "下一轮患者表达担忧后，先回应情绪再继续医学问诊。",
                        "success_signal": "患者表达担忧后，先回应情绪再继续推进。",
                        "skill_type": "relationship_repair",
                        "status": "persistent",
                        "priority": 10,
                    }
                ],
                "humanistic_training_goals": [
                    {
                        "gap_type": "relationship_empathy_missing",
                        "label": "患者表达担忧后给予共情回应",
                        "trigger_stage": "history_taking",
                        "next_training_action": "下一轮患者表达担忧后，先回应情绪再继续医学问诊。",
                        "success_signal": "患者表达担忧后，先回应情绪再继续推进。",
                        "skill_type": "relationship_repair",
                        "status": "persistent",
                        "priority": 10,
                    }
                ],
            },
        )
    )

    assert len(captured_requests) == 1
    assert getattr(captured_requests[0], "prompt_kind") == "socratic_hint"
    assert getattr(captured_requests[0], "base_hint") == (
        "你还没有开始问诊。第一步先用开放式问题建立病史主线，例如起病时间、疼痛部位、性质、程度和伴随症状。"
    )
    assert result["hint"] == getattr(captured_requests[0], "base_hint")
    hint_context = getattr(captured_requests[0], "hint_context")
    assert hint_context["hint_policy"]["intent"] == "case_onboarding"
    assert hint_context["hint_policy"]["suppressed_goal_types"] == ["relationship_empathy_missing"]
    turn_hint_policy = result["agent_turn_memory"][-1]["turn_analysis"]["hint_policy"]
    assert turn_hint_policy["intent"] == "case_onboarding"
    assert turn_hint_policy["suppressed_goal_types"] == ["relationship_empathy_missing"]


def test_osce_graph_socratic_hint_uses_training_goal_without_long_term_skill() -> None:
    captured_requests: list[object] = []

    def echo_base_hint_coach_agent(request: object) -> dict[str, object]:
        captured_requests.append(request)
        return {"should_emit": True, "hint": str(getattr(request, "base_hint")), "trigger_kind": "socratic_hint"}

    graph = build_osce_graph(coach_agent=echo_base_hint_coach_agent)

    result = graph.invoke(
        base_hint_state(
            stage="physical_exam",
            messages=[
                {"role": "student", "content": "我想查一下腹部。"},
                {"role": "tool", "content": "已记录查体申请。"},
            ],
            asked_questions=["什么时候开始疼的？"],
            revealed_facts=["appendicitis_001.hf_01"],
            active_skill_context={
                "skill_index": [],
                "selected_skills": [],
                "skipped_reasons": [],
                "current_training_gaps": [
                    {
                        "gap_type": "ethics_consent_missing",
                        "label": "查体或检查前说明目的并征得同意",
                        "trigger_stage": "physical_exam",
                        "next_training_action": "下一轮查体或检查前先说明目的、可能不适并征得同意。",
                        "success_signal": "查体或检查前先说明目的并征得同意。",
                        "skill_type": "ethics_consent",
                        "status": "persistent",
                        "priority": 10,
                    }
                ],
                "humanistic_training_goals": [
                    {
                        "gap_type": "ethics_consent_missing",
                        "label": "查体或检查前说明目的并征得同意",
                        "trigger_stage": "physical_exam",
                        "next_training_action": "下一轮查体或检查前先说明目的、可能不适并征得同意。",
                        "success_signal": "查体或检查前先说明目的并征得同意。",
                        "skill_type": "ethics_consent",
                        "status": "persistent",
                        "priority": 10,
                    }
                ],
            },
        )
    )

    assert len(captured_requests) == 1
    assert "查体或检查前先说明目的、可能不适并征得同意" in getattr(captured_requests[0], "base_hint")
    assert result["hint"] == getattr(captured_requests[0], "base_hint")
    assert result["agent_turn_memory"][-1]["selected_skill_ids"] == []


def test_osce_graph_socratic_hint_preserves_training_goal_when_skill_is_selected() -> None:
    captured_requests: list[object] = []

    def echo_base_hint_coach_agent(request: object) -> dict[str, object]:
        captured_requests.append(request)
        return {"should_emit": True, "hint": str(getattr(request, "base_hint")), "trigger_kind": "socratic_hint"}

    graph = build_osce_graph(coach_agent=echo_base_hint_coach_agent)

    skill_context = active_skill_context()
    skill_context["current_training_gaps"] = [
        {
            "gap_type": "ethics_consent_missing",
            "label": "查体或检查前说明目的并征得同意",
            "trigger_stage": "physical_exam",
            "next_training_action": "下一轮查体或检查前先说明目的、可能不适并征得同意。",
            "success_signal": "查体或检查前先说明目的并征得同意。",
            "skill_type": "ethics_consent",
            "status": "persistent",
            "priority": 10,
        }
    ]
    skill_context["humanistic_training_goals"] = list(skill_context["current_training_gaps"])

    result = graph.invoke(
        base_hint_state(
            stage="physical_exam",
            messages=[
                {"role": "student", "content": "我想查一下腹部。"},
                {"role": "tool", "content": "已记录查体申请。"},
            ],
            asked_questions=["什么时候开始疼的？"],
            revealed_facts=["appendicitis_001.hf_01"],
            active_skill_context=skill_context,
        )
    )

    assert len(captured_requests) == 2
    coach_base_hint = str(getattr(captured_requests[1], "base_hint"))
    assert "查体或检查前先说明目的、可能不适并征得同意" in coach_base_hint
    assert "腹痛迁移追问训练" in coach_base_hint
    assert result["hint"] == "本轮查体或检查前先说明目的、可能不适并征得同意。"
    assert "本轮训练重点" not in result["hint"]
    assert result["agent_turn_memory"][-1]["selected_skill_ids"] == ["skill_selected_history"]


def test_osce_graph_socratic_hint_passes_comprehensive_hint_context_to_coach() -> None:
    captured_requests: list[object] = []

    def echo_base_hint_coach_agent(request: object) -> dict[str, object]:
        captured_requests.append(request)
        return {"should_emit": True, "hint": str(getattr(request, "base_hint")), "trigger_kind": "socratic_hint"}

    graph = build_osce_graph(coach_agent=echo_base_hint_coach_agent)

    graph.invoke(
        base_hint_state(
            training_difficulty="advanced",
            messages=[
                {"role": "student", "content": "什么时候开始疼的？"},
                {"role": "patient", "content": "24 小时前开始。"},
                {"role": "student", "content": "查一下 McBurney 点。"},
                {"role": "tool", "content": "右下腹 McBurney 点明显压痛。"},
            ],
            asked_questions=["什么时候开始疼的？"],
            intent_history=["ask_onset"],
            revealed_facts=["appendicitis_001.hf_01"],
            requested_exams=["abd.palpation.tenderness"],
            requested_tests=["lab.cbc"],
            student_hypotheses=["考虑急腹症，需要继续补充证据。"],
            active_skill_context=active_skill_context(),
        )
    )

    assert len(captured_requests) == 2
    assert getattr(captured_requests[0], "prompt_kind") == "skill_router"
    payload = captured_requests[1].model_dump()
    hint_context = payload["hint_context"]
    assert payload["training_difficulty"] == "advanced"
    assert hint_context["session"]["training_difficulty"] == "advanced"
    assert hint_context["conversation"]["recent_turns"][-1]["content"] == "右下腹 McBurney 点明显压痛。"
    assert hint_context["conversation"]["student_hypotheses"] == ["考虑急腹症，需要继续补充证据。"]
    assert hint_context["evidence_coverage"]["history"]["collected"][0]["id"] == "hf_01"
    assert hint_context["evidence_coverage"]["physical_exam"]["collected"][0]["id"] == "abd.palpation.tenderness"
    assert hint_context["evidence_coverage"]["auxiliary_test"]["collected"][0]["id"] == "lab.cbc"
    assert hint_context["next_step"]["base_hint"] == "整理已获得的病史、查体和检查证据，再提交主要诊断和推理依据。"
    assert "腹痛迁移追问训练" in payload["base_hint"]
    assert hint_context["next_step"]["clinical_reasoning_state"]["pedagogical_phase"]
    assert hint_context["difficulty_policy"]["mode"] == "advanced"
    assert "自由文本" in hint_context["difficulty_policy"]["student_action_boundary"]
    assert hint_context["skill_selection"]["selected_skills"][0]["skill_id"] == "skill_selected_history"
    assert hint_context["skill_selection"]["selected_skills"][0]["why_selected_label"]
    assert hint_context["skill_selection"]["selected_skills"][0]["when_to_use"] == "学生问诊已开始但未形成腹痛演变时间线时使用。"
    assert "suggested_strategy" not in hint_context["skill_selection"]["selected_skills"][0]
    assert "急性阑尾炎" not in str(payload)


def test_osce_graph_passive_coach_review_does_not_route_skill_or_retrieve_rag() -> None:
    captured_requests: list[object] = []

    def silent_capturing_coach_agent(request: object) -> dict[str, object]:
        captured_requests.append(request)
        return {"should_emit": False, "hint": "", "trigger_kind": "none"}

    graph = build_osce_graph(
        patient_responder=canonical_patient_responder,
        coach_agent=silent_capturing_coach_agent,
    )

    result = graph.invoke(
        base_hint_state(
            active_skill_context=active_skill_context(),
            evolution_candidates=["旧技能：旧策略不应再进入 Coach 提示。"],
            hint_requested=False,
            student_message="什么时候开始疼的？",
            current_intent="",
            reply="",
        )
    )

    assert len(captured_requests) == 1
    assert getattr(captured_requests[0], "prompt_kind") == "passive_turn_review"
    assert getattr(captured_requests[0], "skill_context") == []
    assert getattr(captured_requests[0], "retrieved_knowledge_context") == []
    assert "旧技能" not in str(getattr(captured_requests[0], "model_dump")())
    assert "selected_skill_ids" not in result["agent_turn_memory"][-1]
    assert "skill_context" not in result["agent_turn_memory"][-1]
    assert "knowledge_references" not in result["agent_turn_memory"][-1]
    assert result["agent_turn_memory"][-1]["agent_path"] == [
        "input_router_node",
        "patient_response_node",
        "coach_agent",
    ]
    assert [step["step_id"] for step in result["agent_turn_memory"][-1]["processing_trace"]] == [
        "intent",
        "case_context",
        "patient_reply",
        "coach",
    ]
    patient_turn = result["agent_turn_memory"][0]
    assert patient_turn["reply_role"] == "patient"
    assert [step["step_id"] for step in patient_turn["processing_trace"]] == [
        "intent",
        "case_context",
        "patient_reply",
        "response",
    ]
    assert "selected_skill_ids" not in patient_turn
    assert "knowledge_references" not in patient_turn


def test_osce_graph_injects_pre_submit_rag_context_into_coach_hint(tmp_path, monkeypatch) -> None:
    rag_tail_sentinel = "RAG-TAIL-MUST-NOT-ENTER-PROVIDER-OR-TURN-MEMORY"
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:coach:pain_migration_hint",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "coach_hint_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "source_id": "fareez_osce_2022",
            "title": "疼痛迁移问诊 Coach 提示",
            "text": (
                "训练中可以提示学生追问疼痛是否迁移，但不得说出诊断答案。"
                * 200
            )
            + rag_tail_sentinel,
            "tags": ["history_taking"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:secret:hidden_answer",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "internal_answer",
            "visibility": "secret_scoring_only",
            "allowed_agents": ["scoring"],
            "source_id": "",
            "title": "隐藏答案",
            "text": "隐藏答案：急性阑尾炎。",
            "tags": ["internal"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    monkeypatch.setattr(osce_graph_module, "rag_knowledge_store", store)
    mock_vector_rag_hits(
        monkeypatch,
        "case:appendicitis_001:coach:pain_migration_hint",
        "case:appendicitis_001:secret:hidden_answer",
    )
    captured_requests: list[object] = []

    def fake_coach_agent(request: object) -> dict[str, object]:
        captured_requests.append(request)
        return {"should_emit": True, "hint": str(getattr(request, "base_hint")), "trigger_kind": "socratic_hint"}

    graph = build_osce_graph(coach_agent=fake_coach_agent)

    result = graph.invoke(
        base_hint_state(
            messages=[
                {"role": "student", "content": "什么时候开始疼的？"},
                {"role": "patient", "content": "24 小时前开始。"},
            ],
            asked_questions=["什么时候开始疼的？"],
            intent_history=["ask_onset"],
            revealed_facts=["appendicitis_001.hf_01"],
        )
    )
    request_payload = captured_requests[0].model_dump()
    rag_context = request_payload["retrieved_knowledge_context"]

    assert rag_context[0]["reference"] == "rag_knowledge:case:appendicitis_001:coach:pain_migration_hint"
    assert rag_context[0]["visibility"] == "pre_submit_safe"
    assert len(rag_context[0]["snippet"]) <= MAX_AGENT_KNOWLEDGE_SNIPPET_CHARS
    assert rag_tail_sentinel not in str(request_payload)
    assert "隐藏答案" not in str(request_payload)
    assert "急性阑尾炎" not in str(request_payload)
    assert result["agent_turn_memory"][-1]["source_references"] == [
        "rag_knowledge:case:appendicitis_001:coach:pain_migration_hint"
    ]
    assert result["agent_turn_memory"][-1]["knowledge_references"] == [
        "rag_knowledge:case:appendicitis_001:coach:pain_migration_hint"
    ]
    assert result["agent_turn_memory"][-1]["retrieved_knowledge_context"][0]["reference"] == (
        "rag_knowledge:case:appendicitis_001:coach:pain_migration_hint"
    )
    assert result["agent_turn_memory"][-1]["retrieved_knowledge_context"][0]["visibility"] == "pre_submit_safe"
    assert len(
        result["agent_turn_memory"][-1]["retrieved_knowledge_context"][0][
            "snippet"
        ]
    ) <= MAX_AGENT_KNOWLEDGE_SNIPPET_CHARS
    assert rag_tail_sentinel not in str(result["agent_turn_memory"][-1])
    rag_step = next(step for step in result["agent_turn_memory"][-1]["processing_trace"] if step["step_id"] == "rag")
    assert rag_step["metadata"]["retrieved_count"] == 1
    assert rag_step["metadata"]["knowledge_references"] == [
        "rag_knowledge:case:appendicitis_001:coach:pain_migration_hint"
    ]


def test_osce_graph_socratic_hint_sanitizes_private_case_terms_from_coach_output() -> None:
    def leaking_coach_agent(request: object) -> dict[str, object]:
        return {
            "should_emit": True,
            "hint": "标准答案是急性阑尾炎，右下腹 McBurney 点明显压痛，不用再问。",
            "trigger_kind": "socratic_hint",
        }

    graph = build_osce_graph(coach_agent=leaking_coach_agent)

    result = graph.invoke(base_hint_state())

    assert "急性阑尾炎" not in result["hint"]
    assert "阑尾炎" not in result["hint"]
    assert "右下腹 McBurney 点明显压痛" not in result["hint"]
    assert "标准答案" not in result["hint"]


@pytest.mark.parametrize(
    ("state_updates", "expected_fragments"),
    [
        (
            {
                "messages": [
                    {"role": "student", "content": "什么时候开始疼的？"},
                    {"role": "patient", "content": "24 小时前开始。"},
                ],
                "asked_questions": ["什么时候开始疼的？"],
                "revealed_facts": ["appendicitis_001.hf_01"],
                "training_progress": {
                    "history": {"covered": 1, "pending_fact_ids": ["hf_02", "hf_03", "hf_04", "hf_05"]},
                    "physical_exam": {"requested": 0, "must_pending_codes": ["abd.palpation.rebound"]},
                    "auxiliary_test": {"requested": 0, "must_pending_codes": ["lab.cbc"]},
                },
            },
            ["病史线索还偏少", "继续补齐"],
        ),
        (
            {
                "messages": [
                    {"role": "student", "content": "什么时候开始疼的？"},
                    {"role": "patient", "content": "24 小时前开始。"},
                    {"role": "student", "content": "后来转移了吗？"},
                    {"role": "patient", "content": "后来右下腹更明显。"},
                ],
                "asked_questions": ["什么时候开始疼的？", "后来转移了吗？", "有没有恶心？"],
                "revealed_facts": ["appendicitis_001.hf_01", "appendicitis_001.hf_02", "appendicitis_001.hf_05"],
                "training_progress": {
                    "history": {"covered": 3, "pending_fact_ids": ["hf_03", "hf_04"]},
                    "physical_exam": {"requested": 0, "must_pending_codes": ["abd.palpation.rebound"]},
                    "auxiliary_test": {"requested": 0, "must_pending_codes": ["lab.cbc"]},
                },
            },
            ["病史链还不完整", "聚焦追问"],
        ),
        (
            {
                "asked_questions": ["什么时候开始疼的？", "哪里疼？", "怎么疼？", "多疼？", "有没有恶心？"],
                "revealed_facts": [
                    "appendicitis_001.hf_01",
                    "appendicitis_001.hf_02",
                    "appendicitis_001.hf_03",
                    "appendicitis_001.hf_04",
                    "appendicitis_001.hf_05",
                ],
                "training_progress": {
                    "history": {"covered": 5, "pending_fact_ids": ["hf_06"]},
                    "physical_exam": {"requested": 0, "must_pending_codes": ["abd.palpation.rebound"]},
                    "auxiliary_test": {"requested": 0, "must_pending_codes": ["lab.cbc"]},
                },
            },
            ["少量缺口", "关键查体"],
        ),
        (
            {
                "asked_questions": ["核心病史已问完"],
                "revealed_facts": ["appendicitis_001.hf_01", "appendicitis_001.hf_02", "appendicitis_001.hf_03"],
                "training_progress": {
                    "history": {"covered": 6, "pending_fact_ids": []},
                    "physical_exam": {"requested": 0, "must_pending_codes": ["abd.palpation.rebound"]},
                    "auxiliary_test": {"requested": 0, "must_pending_codes": ["lab.cbc"]},
                },
            },
            ["关键查体", "验证当前线索"],
        ),
        (
            {
                "stage": "physical_exam",
                "asked_questions": ["核心病史已问完"],
                "revealed_facts": ["appendicitis_001.hf_01", "appendicitis_001.hf_02", "appendicitis_001.hf_03"],
                "requested_exams": ["abd.palpation.rebound"],
                "training_progress": {
                    "history": {"covered": 6, "pending_fact_ids": []},
                    "physical_exam": {"requested": 1, "must_pending_codes": []},
                    "auxiliary_test": {"requested": 0, "must_pending_codes": ["lab.cbc"]},
                },
            },
            ["辅助检查", "验证当前假设"],
        ),
        (
            {
                "stage": "auxiliary_test",
                "asked_questions": ["核心病史已问完"],
                "revealed_facts": ["appendicitis_001.hf_01", "appendicitis_001.hf_02", "appendicitis_001.hf_03"],
                "requested_exams": ["abd.palpation.rebound"],
                "requested_tests": ["lab.cbc"],
                "training_progress": {
                    "history": {"covered": 6, "pending_fact_ids": []},
                    "physical_exam": {"requested": 1, "must_pending_codes": []},
                    "auxiliary_test": {"requested": 1, "must_pending_codes": []},
                    "reasoning": {"pending_evidence": ["abd.palpation.rebound"]},
                },
            },
            ["诊断假设", "证据整理"],
        ),
        (
            {
                "stage": "hypothesis",
                "asked_questions": ["核心病史已问完"],
                "revealed_facts": ["appendicitis_001.hf_01", "appendicitis_001.hf_02", "appendicitis_001.hf_03"],
                "requested_exams": ["abd.palpation.rebound"],
                "requested_tests": ["lab.cbc"],
                "student_hypotheses": ["考虑急腹症，需要结合病史、查体和检查整理证据链。"],
                "training_progress": {
                    "history": {"covered": 6, "pending_fact_ids": []},
                    "physical_exam": {"requested": 1, "must_pending_codes": []},
                    "auxiliary_test": {"requested": 1, "must_pending_codes": []},
                    "reasoning": {"pending_evidence": []},
                },
            },
            ["提交", "支持证据"],
        ),
    ],
)
def test_osce_graph_active_coach_hint_covers_progress_depths(state_updates: dict[str, object], expected_fragments: list[str]) -> None:
    captured_requests: list[object] = []

    def echo_base_hint_coach_agent(request: object) -> dict[str, object]:
        captured_requests.append(request)
        return {"should_emit": True, "hint": str(getattr(request, "base_hint")), "trigger_kind": "socratic_hint"}

    graph = build_osce_graph(coach_agent=echo_base_hint_coach_agent)

    result = graph.invoke(base_hint_state(**state_updates))

    assert len(captured_requests) == 1
    assert result["hint"] == getattr(captured_requests[0], "base_hint")
    for expected_fragment in expected_fragments:
        assert expected_fragment in result["hint"]
    for forbidden_term in ["急性阑尾炎", "阑尾炎", "治疗方案", "用药剂量"]:
        assert forbidden_term not in result["hint"]


def test_osce_graph_hint_explains_sequence_gap_after_auxiliary_test_before_physical_exam() -> None:
    graph = build_osce_graph()

    result = graph.invoke(
        {
            "session_id": "session_demo",
            "case_id": "appendicitis_001",
            "stage": "auxiliary_test",
            "case_title": "右下腹痛教学病例",
            "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
            "hint_requested": True,
            "hint": "",
            "messages": [
                {"role": "student", "content": "什么时候开始疼的？"},
                {"role": "patient", "content": "24 小时前开始。"},
            ],
            "asked_questions": ["什么时候开始疼的？"],
            "intent_history": ["ask_onset"],
            "agent_turn_memory": [],
            "revealed_facts": ["appendicitis_001.hf_01"],
            "requested_exams": [],
            "requested_tests": ["lab.cbc"],
            "student_hypotheses": [],
            "final_submission": None,
            "rubric_scores": {},
            "missed_items": [],
            "retrieved_sources": [],
            "feedback_report": None,
            "safety_flags": [],
            "evolution_candidates": [],
            "training_progress": {
                "physical_exam": {
                    "must_pending_codes": ["abd.palpation.rebound"],
                },
                "auxiliary_test": {
                    "requested": 1,
                },
            },
        }
    )

    assert "辅助检查" in result["hint"]
    assert "查体" in result["hint"]
    assert "为什么" in result["hint"] or "想一想" in result["hint"]
    assert "急性阑尾炎" not in result["hint"]
    assert "阑尾炎" not in result["hint"]
