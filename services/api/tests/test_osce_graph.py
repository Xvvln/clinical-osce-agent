import pytest

from app.graph.osce_graph import build_osce_graph
from app.models.rubric import LlmRubricRequest, LlmRubricResponse


def canonical_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


def silent_coach_agent(request: object) -> dict[str, object]:
    return {"should_emit": False, "hint": "", "trigger_kind": "none"}


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
    }
    state.update(overrides)
    return state


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
    assert result["current_intent"] == "ask_onset"
    assert result["reply"] == "24 小时前开始，最初是上腹部隐痛。"
    assert "急性阑尾炎" not in result["reply"]
    assert result["revealed_facts"] == ["appendicitis_001.hf_01"]
    assert result["asked_questions"] == ["什么时候开始疼的？"]
    assert result["intent_history"] == ["ask_onset"]
    assert result["messages"] == [
        {"role": "student", "content": "什么时候开始疼的？"},
        {"role": "patient", "content": "24 小时前开始，最初是上腹部隐痛。"},
    ]


def test_osce_graph_routes_patient_identity_unknown_kind_without_forced_coach_hint() -> None:
    captured_patient_requests: list[object] = []
    captured_coach_requests: list[object] = []

    def fake_patient_responder(request: object) -> str:
        captured_patient_requests.append(request)
        return str(getattr(request, "canonical_answer"))

    def fake_coach_agent(request: object) -> dict[str, object]:
        captured_coach_requests.append(request)
        return {
            "should_emit": True,
            "hint": "可以先从起病时间、疼痛部位、性质、程度和伴随症状开始问。",
            "trigger_kind": "off_topic_redirect",
        }

    graph = build_osce_graph(patient_responder=fake_patient_responder, coach_agent=fake_coach_agent)

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
    assert result["current_intent"] == "unknown_history_intent"
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
    assert getattr(captured_patient_requests[0], "current_intent") == "unknown_history_intent"
    assert getattr(captured_patient_requests[0], "deterministic_hints")["keyword_intent"] == "unknown_history_intent"
    assert getattr(captured_patient_requests[0], "deterministic_hints")["unknown_kind"] == "patient_identity_unclear"
    assert len(captured_coach_requests) == 1
    assert getattr(captured_coach_requests[0], "prompt_kind") == "passive_turn_review"
    assert getattr(captured_coach_requests[0], "base_hint") == ""
    assert result["agent_turn_memory"][0]["reply_role"] == "patient"
    assert result["agent_turn_memory"][0]["turn_policy"] == "patient_identity_redirect"
    assert result["agent_turn_memory"][1]["reply_role"] == "coach"
    assert result["agent_turn_memory"][1]["turn_policy"] == "passive_review_silent"
    assert result["agent_turn_memory"][1]["agent_path"] == ["input_router_node", "patient_response_node", "coach_agent"]


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

    assert result["current_intent"] == "unknown_history_intent"
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

    assert result["current_intent"] == "ask_patient_gender"
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

    assert result["current_intent"] == "answer_request_redirect"
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
    assert result["agent_turn_memory"][0]["turn_analysis"]["current_intent"] == "answer_request_redirect"


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
    assert patient_private_context["history"]["present_illness_summary"] == (
        "患者 24 小时前无明显诱因出现上腹部隐痛，伴恶心，未呕吐，约 8 小时前疼痛转移并固定于右下腹，程度较前加重，行走时加重，伴低热。"
    )
    assert "appendicitis_001.hf_05" in {
        fact["fact_id"] for fact in patient_private_context["history"]["hidden_facts"]
    }
    assert "diagnosis" not in patient_private_context
    forbidden_context = getattr(patient_request, "forbidden_context")
    assert forbidden_context["diagnosis_terms"] == [
        "急性阑尾炎",
        "阑尾炎",
        "Acute appendicitis",
        "acute appendicitis",
    ]
    assert forbidden_context["blocked_reference_types"] == ["diagnosis", "rubric", "treatment", "dosage"]
    assert "rubric" not in patient_private_context
    assert getattr(patient_request, "deterministic_hints")["answerable_fact_ids"] == ["appendicitis_001.hf_01"]


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

    assert result["current_intent"] == "ask_onset"
    assert result["reply"] == "24 小时前开始，最初是上腹部隐痛。"
    assert result["revealed_facts"] == ["appendicitis_001.hf_01"]
    assert len(captured_intent_requests) == 1
    assert getattr(captured_intent_requests[0], "student_message") == "腹痛持续多长时间了？"
    assert getattr(captured_intent_requests[0], "keyword_intent") == "unknown_history_intent"
    assert len(captured_patient_requests) == 1
    patient_hints = getattr(captured_patient_requests[0], "deterministic_hints")
    assert patient_hints["turn_analysis"] == {
        "current_intent": "ask_onset",
        "confidence": 0.93,
        "is_off_topic": False,
        "rationale": "学生在询问腹痛持续时间。",
    }
    assert result["agent_turn_memory"][0]["current_intent"] == "ask_onset"
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


def test_osce_graph_forces_passive_coach_hint_when_backend_detects_off_topic_even_if_model_suppresses_it() -> None:
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

    assert len(captured_coach_requests) == 1
    assert getattr(captured_coach_requests[0], "base_hint") == (
        "这轮训练先回到腹痛问诊。可以从起病时间、疼痛部位、性质、程度和伴随症状继续问。"
    )
    assert result["messages"][-1] == {
        "role": "coach",
        "content": "这轮训练先回到腹痛问诊。可以从起病时间、疼痛部位、性质、程度和伴随症状继续问。",
    }
    assert result["agent_turn_memory"][-1]["turn_policy"] == "passive_review_hint"


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

        assert result["current_intent"] == expected_intent
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

        assert result["current_intent"] == expected_intent
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

    feedback_report = result["feedback_report"]

    assert result["stage"] == "feedback"
    assert feedback_report["report_id"] == "session_demo_report"
    assert feedback_report["session_id"] == "session_demo"
    assert feedback_report["case_id"] == "appendicitis_001"
    assert feedback_report["total_score"] == 32
    assert feedback_report["dimension_scores"] == {
        "history_taking": 3,
        "physical_exam": 5,
        "auxiliary_test": 5,
        "main_diagnosis": 15,
        "differential_diagnosis": 0,
        "reasoning": 4,
    }
    assert "dimension_traces" in feedback_report
    assert result["rubric_scores"]["ht_onset"]["score"] == 3
    assert result["rubric_scores"]["ht_migration"]["score"] == 0
    assert result["rubric_scores"]["pe_rebound"]["score"] == 5
    assert result["rubric_scores"]["ax_cbc"]["score"] == 5
    assert result["rubric_scores"]["dx_main"]["score"] == 15
    assert result["rubric_scores"]["rs_support"]["score"] == 4
    assert "ht_migration" in result["missed_items"]
    assert "推理表达覆盖关键排除依据：评分轨迹未找到足够证据。" in feedback_report["reasoning_errors"]
    assert feedback_report["strengths"][:4] == [
        "追问起病时间：已完成。",
        "检查反跳痛：已完成。",
        "申请血常规：已完成。",
        "主要诊断命中急性阑尾炎：已完成。",
    ]
    assert feedback_report["next_recommendations"][:3] == [
        "下一轮训练重点：追问疼痛部位及转移特征。",
        "下一轮训练重点：追问疼痛性质。",
        "下一轮训练重点：追问疼痛程度。",
    ]
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
    assert feedback_report["feedback_summary"] == "已根据评分轨迹生成教学反馈，内容仅用于 OSCE 训练复盘。"
    assert "created_at" in feedback_report
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

    assert result["feedback_report"]["total_score"] == 37
    assert result["feedback_report"]["dimension_scores"]["differential_diagnosis"] == 0
    assert result["feedback_report"]["dimension_scores"]["reasoning"] == 9
    assert result["rubric_scores"]["rs_support"]["score"] == 4
    assert result["rubric_scores"]["rs_exclude"]["score"] == 5
    assert result["feedback_report"]["llm_reasoning_feedback"] == [
        {
            "rubric_item_id": "rs_exclude",
            "description": "推理表达覆盖关键排除依据",
            "score": 5,
            "max_score": 5,
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


def test_osce_graph_uses_injected_coach_agent_for_hint_and_records_agent_turn() -> None:
    captured_requests: list[object] = []

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
    assert result["agent_turn_memory"] == [
        {
            "turn_id": "turn:1",
            "student_message": "请求提示",
            "reply": result["hint"],
            "reply_role": "coach",
            "current_intent": "socratic_hint",
            "turn_policy": "teaching_hint",
            "turn_analysis": {
                "current_intent": "socratic_hint",
                "confidence": 1.0,
                "is_off_topic": False,
                "rationale": "学生请求教学提示。",
            },
            "agent_path": ["socratic_hint_node", "coach_agent"],
            "revealed_fact_id": None,
            "source_references": [],
            "safety_flags": [],
        }
    ]


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
