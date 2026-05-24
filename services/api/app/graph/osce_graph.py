from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.services.agent_rag_context_service import retrieve_agent_context
from app.services.agent_state_service import append_decision_trace, build_pedagogy_state, build_reflection_summary
from app.services.coach_agent import CoachRequest, create_default_coach_agent, normalize_coach_response, sanitize_coach_hint
from app.services.gemini_patient_responder import PatientResponderRequest, create_default_gemini_patient_responder
from app.services.knowledge_recommender import recommend_knowledge_items
from app.services.patient_language_service import (
    build_patient_context_redirect_utterance,
    patient_friendly_chief_complaint,
)
from app.services.rag_knowledge_store import rag_knowledge_store
from app.services.rule_evaluator import LlmRubricScorer, evaluate_session_rules
from app.services.source_retriever import FeedbackSourceItem, retrieve_feedback_source_items
from app.services.turn_intent_agent import (
    TurnIntentRequest,
    classify_unknown_history_message,
    create_default_turn_intent_agent,
    normalize_turn_intent_response,
)
from app.validators.case_validator import validate_case
from app.models.case import Case, HiddenFact

COACH_RAG_VISIBILITIES = {"pre_submit_safe"}
REFLECTION_RAG_VISIBILITIES = {"pre_submit_safe", "post_submit_review"}

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"
PatientResponder = Callable[[PatientResponderRequest], str]
TurnIntentAgent = Callable[[TurnIntentRequest], Any]
CoachAgent = Callable[[CoachRequest], Any]
SAFETY_BOUNDARY_FLAG = "real_medical_advice_request"
SAFETY_GUARDRAIL_REPLY = "本系统仅用于 OSCE 教学模拟训练，不能提供真实诊断、具体用药或急救处置建议；如有真实健康问题，请咨询合格医疗专业人员或及时就医。"
ANSWER_REQUEST_REDIRECT_REPLY = "不能直接告诉你标准答案。请继续通过问诊、查体和辅助检查收集证据，或在准备好后提交诊断。"
UNKNOWN_HISTORY_REDIRECT_REPLY = "病例脚本没有提供这方面信息。请回到本次腹痛训练目标，优先追问起病时间、部位变化、疼痛性质、疼痛程度和伴随症状。"


class OsceGraphState(TypedDict, total=False):
    case_id: str
    stage: str
    case_title: str
    chief_complaint: str
    session_id: str
    student_message: str
    keyword_intent: str
    keyword_intents: list[str]
    current_intents: list[str]
    turn_analysis: dict[str, Any]
    reply: str
    report_requested: bool
    hint_requested: bool
    hint: str
    training_progress: dict[str, Any]
    training_progress_next_focus: str
    exam_code: str
    exam_name_cn: str
    exam_result: str
    test_code: str
    test_name_cn: str
    test_result: str
    submitted_diagnosis: str
    submitted_reasoning: str
    messages: list[dict[str, str]]
    asked_questions: list[str]
    intent_history: list[str]
    revealed_facts: list[str]
    requested_exams: list[str]
    requested_tests: list[str]
    student_hypotheses: list[str]
    final_submission: dict[str, str] | None
    rubric_scores: dict[str, Any]
    missed_items: list[str]
    retrieved_sources: list[str]
    feedback_report: dict[str, Any] | None
    safety_flags: list[str]
    evolution_candidates: list[str]
    active_skill_context: dict[str, Any]
    agent_turn_memory: list[dict[str, Any]]
    pedagogy_state: dict[str, Any]
    agent_decision_trace: list[dict[str, Any]]
    reflection_summary: dict[str, Any] | None


def load_case_node(state: OsceGraphState) -> dict[str, str]:
    case = _load_case(state["case_id"])
    return {
        "case_id": case.case_id,
        "stage": state.get("stage") or "case_intro",
        "case_title": case.case_title,
        "chief_complaint": case.chief_complaint,
    }


def input_router_node(state: OsceGraphState, turn_intent_agent: TurnIntentAgent) -> dict[str, Any]:
    case = _load_case(state["case_id"])
    keyword_intents = _keyword_intents_for_message(state.get("student_message", ""))
    keyword_intent = keyword_intents[0] if keyword_intents else "unknown_history_intent"
    turn_analysis = normalize_turn_intent_response(
        turn_intent_agent(
            TurnIntentRequest(
                case_id=case.case_id,
                case_title=case.case_title,
                chief_complaint=case.chief_complaint,
                stage=state.get("stage") or "case_intro",
                student_message=state.get("student_message", ""),
                keyword_intent=keyword_intent,
                keyword_intents=keyword_intents,
                prior_messages=state.get("messages", []),
            )
        )
    )
    turn_analysis = _complete_unknown_turn_analysis(turn_analysis, state.get("student_message", ""))
    turn_analysis = _merge_turn_analysis_with_keyword_intents(turn_analysis, keyword_intents)
    return {
        "keyword_intent": keyword_intent,
        "keyword_intents": keyword_intents,
        "current_intents": list(turn_analysis.get("current_intents") or []),
        "turn_analysis": turn_analysis,
    }


def _keyword_intent_for_message(message: str) -> str:
    keyword_intents = _keyword_intents_for_message(message)
    return keyword_intents[0] if keyword_intents else "unknown_history_intent"


def _keyword_intents_for_message(message: str) -> list[str]:
    normalized = message.lower()
    intent_keywords = [
        ("ask_patient_gender", ["男的女的", "男还是女", "性别", "男生", "女生", "男孩", "女孩"]),
        ("ask_patient_age", ["多大", "几岁", "年龄"]),
        ("ask_patient_occupation", ["职业", "工作", "做什么", "上班", "学生吗"]),
        ("ask_migration", ["转移", "换地方", "跑到"]),
        ("ask_radiation", ["放射", "牵扯", "左肩", "左臂", "左上臂", "胳膊", "手臂"]),
        ("ask_progression", ["加重", "越来越", "活动后", "活动时", "走路", "走快"]),
        ("ask_orthopnea", ["憋醒", "平卧", "躺下", "躺着", "垫高", "夜间", "夜里", "晚上"]),
        ("ask_edema", ["水肿", "浮肿", "脚肿", "腿肿", "下肢肿"]),
        ("ask_sputum", ["咳痰", "痰", "黄痰", "咯血"]),
        ("ask_heat_intolerance", ["怕热", "多汗", "出汗", "体重下降", "消瘦", "吃得多"]),
        ("ask_bowel_change", ["大便次数", "排便", "便次"]),
        ("ask_menstrual_history", ["月经"]),
        ("ask_character", ["性质", "什么样", "胀痛", "绞痛", "刺痛"]),
        ("ask_chest_pain_character", ["胸痛性质", "胸口疼性质", "深呼吸", "咳嗽疼", "咳嗽时疼"]),
        ("ask_severity", ["几分", "多疼", "疼痛程度", "严重", "vas"]),
        ("ask_fever", ["发热", "发烧", "体温", "低热"]),
        ("ask_urinary", ["尿频", "尿急", "尿痛", "血尿", "小便"]),
        ("ask_stool", ["腹泻", "大便", "拉肚子"]),
        ("ask_associated_nausea", ["恶心", "呕吐", "想吐", "吐"]),
        ("ask_allergy", ["过敏"]),
        ("ask_diet", ["饮食", "吃了什么"]),
        ("ask_travel", ["旅行", "出远门"]),
        ("ask_personal", ["个人史", "抽烟", "吸烟", "喝酒", "饮酒"]),
        ("ask_family", ["家族", "家里人", "父母"]),
        ("ask_concern", ["担心", "害怕", "顾虑"]),
        ("ask_expectation", ["期望", "希望", "想要"]),
        ("ask_idea", ["想法", "觉得", "认为"]),
        ("ask_onset", ["什么时候", "何时", "多久", "开始"]),
        ("ask_location", ["哪里", "哪儿", "哪", "位置", "部位", "什么地方"]),
        ("ask_character", ["怎么疼", "怎么个疼", "疼法", "痛法"]),
        ("ask_severity", ["多痛", "多疼", "痛不痛", "疼不疼"]),
        ("ask_past_medical_history", ["既往", "以前", "手术史"]),
    ]
    matched_intents: list[str] = []
    for intent, keywords in intent_keywords:
        if intent not in matched_intents and any(keyword in normalized for keyword in keywords):
            matched_intents.append(intent)
    return matched_intents


def unknown_history_redirect_node(state: OsceGraphState) -> dict[str, Any]:
    student_message = state.get("student_message", "")
    messages = [*state.get("messages", [])]
    if student_message:
        messages.extend(
            [
                {"role": "student", "content": student_message},
                {"role": "coach", "content": UNKNOWN_HISTORY_REDIRECT_REPLY},
            ]
        )
    return {
        "stage": "history_taking",
        "current_intents": [],
        "reply": UNKNOWN_HISTORY_REDIRECT_REPLY,
        "messages": messages,
        "asked_questions": list(state.get("asked_questions", [])),
        "intent_history": [*state.get("intent_history", []), "unknown_history_intent"],
        "revealed_facts": list(state.get("revealed_facts", [])),
    }


def patient_response_node(state: OsceGraphState, patient_responder: PatientResponder, coach_agent: CoachAgent) -> dict[str, Any]:
    case = _load_case(state["case_id"])
    current_intents = _current_intents_from_state(state)
    primary_intent = _primary_intent_from_current_intents(current_intents)
    turn_analysis = state.get("turn_analysis", {})
    unknown_kind = _unknown_kind_from_turn_analysis(turn_analysis)
    previously_revealed_facts = list(state.get("revealed_facts", []))
    revealed_facts = [*previously_revealed_facts]
    canonical_answer = _unknown_patient_context_answer(case, unknown_kind)
    revealed_fact_id: str | None = None
    answerable_hidden_facts = _answerable_hidden_facts_for_intents(case, current_intents)
    answerable_profile_facts = _answerable_patient_profile_facts_for_intents(case, current_intents)
    if answerable_hidden_facts:
        revealed_fact_id = answerable_hidden_facts[0].fact_id
        for hidden_fact in answerable_hidden_facts:
            if hidden_fact.fact_id not in revealed_facts:
                revealed_facts.append(hidden_fact.fact_id)
    revealed_fact_ids = [hidden_fact.fact_id for hidden_fact in answerable_hidden_facts]
    answer_parts = [
        *[hidden_fact.canonical_answer for hidden_fact in answerable_hidden_facts],
        *[str(profile_fact["canonical_answer"]) for profile_fact in answerable_profile_facts],
    ]
    if answer_parts:
        canonical_answer = "；".join(answer_parts)
    answerable_fact_candidates = [
        *[_serialize_answerable_fact_candidate(case.case_id, hidden_fact) for hidden_fact in answerable_hidden_facts],
        *answerable_profile_facts,
    ]
    answerable_fact_ids = [
        str(candidate["fact_id"])
        for candidate in answerable_fact_candidates
        if isinstance(candidate, dict) and candidate.get("fact_id")
    ]
    turn_policy = (
        "patient_profile_disclosure"
        if answerable_profile_facts and not answerable_hidden_facts
        else _turn_policy_for_patient_response(primary_intent, revealed_fact_id, unknown_kind=unknown_kind)
    )

    student_message = state.get("student_message", "")
    reply = patient_responder(
        PatientResponderRequest(
            case_id=case.case_id,
            case_title=case.case_title,
            chief_complaint=case.chief_complaint,
            student_message=student_message,
            current_intents=current_intents,
            canonical_answer=canonical_answer,
            revealed_fact_id=revealed_fact_id,
            revealed_fact_ids=revealed_facts,
            patient_private_context=_build_patient_private_context(case),
            answerable_fact_candidates=answerable_fact_candidates,
            forbidden_terms=_patient_forbidden_terms(case),
            forbidden_context=_build_patient_forbidden_context(case),
            prior_messages=state.get("messages", []),
            dialogue_context=_build_patient_dialogue_context(
                state,
                student_message=student_message,
                current_intents=current_intents,
                answerable_fact_ids=answerable_fact_ids,
                revealed_fact_ids=revealed_facts,
            ),
            turn_policy=turn_policy,
            deterministic_hints=_deterministic_turn_hints(
                state,
                keyword_intent=state.get("keyword_intent", primary_intent),
                keyword_intents=list(state.get("keyword_intents", [])),
                current_intents=current_intents,
                revealed_fact_id=revealed_fact_id,
                revealed_fact_ids=revealed_fact_ids,
                answerable_fact_ids=answerable_fact_ids,
                turn_policy=turn_policy,
            ),
        )
    )
    messages = [*state.get("messages", [])]
    if student_message:
        messages.extend(
            [
                {"role": "student", "content": student_message},
                {"role": "patient", "content": reply},
            ]
        )

    agent_turn_memory = _append_agent_turn_memory(
        state,
        student_message=student_message,
        reply=reply,
        reply_role="patient",
        current_intents=current_intents,
        turn_policy=turn_policy,
        turn_analysis=turn_analysis,
        agent_path=["input_router_node", "patient_response_node"],
        revealed_fact_id=revealed_fact_id,
        revealed_fact_ids=revealed_fact_ids,
        safety_flags=list(state.get("safety_flags", [])),
    )
    messages, agent_turn_memory = _apply_passive_coach_review(
        state,
        case=case,
        coach_agent=coach_agent,
        student_message=student_message,
        patient_reply=reply,
        primary_intent=primary_intent,
        current_intents=current_intents,
        revealed_fact_id=revealed_fact_id,
        messages=messages,
        agent_turn_memory=agent_turn_memory,
        turn_analysis=turn_analysis,
    )

    return {
        "stage": "history_taking",
        "current_intents": current_intents,
        "reply": reply,
        "messages": messages,
        "asked_questions": _asked_questions_after_patient_turn(state, student_message, revealed_fact_id),
        "intent_history": [*state.get("intent_history", []), *(current_intents or [primary_intent])],
        "revealed_facts": revealed_facts,
        "agent_turn_memory": agent_turn_memory,
    }


def physical_exam_node(state: OsceGraphState) -> dict[str, Any]:
    case = _load_case(state["case_id"])
    exam_code = state.get("exam_code", "")
    requested_exams = list(state.get("requested_exams", []))
    if exam_code and exam_code not in requested_exams:
        requested_exams.append(exam_code)
    for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]:
        if exam.exam_code == exam_code:
            return {
                "stage": "physical_exam",
                "exam_code": exam.exam_code,
                "exam_name_cn": exam.exam_name_cn,
                "exam_result": exam.result,
                "requested_exams": requested_exams,
            }
    return {
        "stage": "physical_exam",
        "exam_code": exam_code,
        "exam_name_cn": "未提供查体",
        "exam_result": "本病例未提供该查体结果。",
        "requested_exams": requested_exams,
    }


def auxiliary_test_node(state: OsceGraphState) -> dict[str, Any]:
    case = _load_case(state["case_id"])
    test_code = state.get("test_code", "")
    requested_tests = list(state.get("requested_tests", []))
    if test_code and test_code not in requested_tests:
        requested_tests.append(test_code)
    for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]:
        if test.test_code == test_code:
            return {
                "stage": "auxiliary_test",
                "test_code": test.test_code,
                "test_name_cn": test.test_name_cn,
                "test_result": test.result,
                "requested_tests": requested_tests,
            }
    return {
        "stage": "auxiliary_test",
        "test_code": test_code,
        "test_name_cn": "未提供检查",
        "test_result": "本病例未提供该辅助检查结果。",
        "requested_tests": requested_tests,
    }


def diagnosis_submit_node(state: OsceGraphState) -> dict[str, Any]:
    diagnosis = state.get("submitted_diagnosis", "")
    reasoning = state.get("submitted_reasoning", "")
    return {
        "stage": "diagnosis_submission",
        "final_submission": {"diagnosis": diagnosis, "reasoning": reasoning},
        "student_hypotheses": [*state.get("student_hypotheses", []), diagnosis],
    }


def training_strategy_node(state: OsceGraphState) -> dict[str, Any]:
    pedagogy_state = build_pedagogy_state(dict(state))
    return {
        "pedagogy_state": pedagogy_state,
        "agent_decision_trace": append_decision_trace(
            state.get("agent_decision_trace", []),
            "training_strategy_node",
            pedagogy_state,
        ),
    }


def skill_context_node(state: OsceGraphState) -> dict[str, Any]:
    pedagogy_state = build_pedagogy_state(dict(state))
    return {
        "pedagogy_state": pedagogy_state,
        "agent_decision_trace": append_decision_trace(
            state.get("agent_decision_trace", []),
            "skill_context_node",
            pedagogy_state,
        ),
    }


def reflection_node(state: OsceGraphState) -> dict[str, Any]:
    reflection_summary = build_reflection_summary(dict(state))
    case = _load_case(state["case_id"])
    forbidden_terms = [case.diagnosis.main_diagnosis, *case.diagnosis.main_diagnosis_synonyms]
    retrieved_knowledge_context = _retrieve_reflection_knowledge_context(
        state,
        case=case,
        reflection_summary=reflection_summary,
        forbidden_terms=forbidden_terms,
    )
    if retrieved_knowledge_context:
        reflection_summary = {
            **reflection_summary,
            "knowledge_references": [item["reference"] for item in retrieved_knowledge_context],
            "retrieved_knowledge_context": retrieved_knowledge_context,
        }
    pedagogy_state = build_pedagogy_state({**dict(state), "reflection_summary": reflection_summary})
    return {
        "reflection_summary": reflection_summary,
        "pedagogy_state": pedagogy_state,
        "agent_decision_trace": append_decision_trace(
            state.get("agent_decision_trace", []),
            "reflection_node",
            pedagogy_state,
        ),
    }


def socratic_hint_node(state: OsceGraphState, coach_agent: CoachAgent) -> dict[str, Any]:
    case = _load_case(state["case_id"])
    pedagogy_state = build_pedagogy_state(dict(state))
    base_hint = _build_socratic_hint(state, pedagogy_state)
    selected_skill_context = _selected_skill_context_strings(state)
    selected_skill_ids = _selected_skill_ids(state)
    forbidden_terms = [case.diagnosis.main_diagnosis, *case.diagnosis.main_diagnosis_synonyms]
    retrieved_knowledge_context = _retrieve_coach_knowledge_context(
        state,
        case=case,
        query=base_hint,
        forbidden_terms=forbidden_terms,
    )
    turn_analysis = _boundary_turn_analysis("socratic_hint", "学生请求教学提示。")
    turn_policy = "teaching_hint"
    agent_path = ["socratic_hint_node", "coach_agent"]
    try:
        hint = sanitize_coach_hint(
            normalize_coach_response(
                coach_agent(
                    CoachRequest(
                        case_id=case.case_id,
                        case_title=case.case_title,
                        chief_complaint=case.chief_complaint,
                        stage=state.get("stage", "case_intro"),
                        prompt_kind="socratic_hint",
                        base_hint=base_hint,
                        prior_messages=state.get("messages", []),
                        pedagogy_state=pedagogy_state,
                        clinical_reasoning_state=pedagogy_state.get("clinical_reasoning_state", {}),
                        skill_context=selected_skill_context,
                        retrieved_knowledge_context=retrieved_knowledge_context,
                        forbidden_terms=[],
                    )
                )
            ).hint,
            forbidden_terms,
        )
    except Exception as exc:
        hint = sanitize_coach_hint(base_hint, forbidden_terms)
        turn_policy = "teaching_hint_unavailable"
        agent_path = ["socratic_hint_node", "coach_agent_unavailable"]
        turn_analysis = {
            **turn_analysis,
            "coach_unavailable": True,
            "coach_error_type": exc.__class__.__name__,
        }
    return {
        "stage": state.get("stage", "case_intro"),
        "hint": hint,
        "messages": [*state.get("messages", []), {"role": "coach", "content": hint}],
        "agent_turn_memory": _append_agent_turn_memory(
            state,
            student_message="请求提示",
            reply=hint,
            reply_role="coach",
            current_intents=["socratic_hint"],
            turn_policy=turn_policy,
            turn_analysis=turn_analysis,
            agent_path=agent_path,
            revealed_fact_id=None,
            safety_flags=list(state.get("safety_flags", [])),
            source_references=[item["reference"] for item in retrieved_knowledge_context],
            retrieved_knowledge_context=retrieved_knowledge_context,
            selected_skill_ids=selected_skill_ids,
            skill_context=selected_skill_context,
        ),
    }



def answer_request_redirect_node(state: OsceGraphState, coach_agent: CoachAgent) -> dict[str, Any]:
    turn_analysis = _boundary_turn_analysis("answer_request_redirect", "学生请求标准答案或诊断结论。")
    reply = _coach_reply_from_agent(
        state,
        coach_agent,
        primary_intent="answer_request_redirect",
        base_hint=ANSWER_REQUEST_REDIRECT_REPLY,
        turn_policy="answer_boundary_redirect",
        turn_analysis=turn_analysis,
    )
    student_message = state.get("student_message", "")
    messages = [*state.get("messages", [])]
    if student_message:
        messages.extend(
            [
                {"role": "student", "content": student_message},
                {"role": "coach", "content": reply},
            ]
        )
    return {
        "stage": state.get("stage") or "case_intro",
        "current_intents": ["answer_request_redirect"],
        "reply": reply,
        "messages": messages,
        "agent_turn_memory": _append_agent_turn_memory(
            state,
            student_message=student_message,
            reply=reply,
            reply_role="coach",
            current_intents=["answer_request_redirect"],
            turn_policy="answer_boundary_redirect",
            turn_analysis=turn_analysis,
            agent_path=["answer_request_redirect_node"],
            revealed_fact_id=None,
            safety_flags=list(state.get("safety_flags", [])),
        ),
    }



def safety_guardrail_node(state: OsceGraphState, coach_agent: CoachAgent) -> dict[str, Any]:
    turn_analysis = _boundary_turn_analysis("safety_boundary", "学生请求真实医疗建议、治疗方案或用药剂量。")
    reply = _coach_reply_from_agent(
        state,
        coach_agent,
        primary_intent="safety_boundary",
        base_hint=SAFETY_GUARDRAIL_REPLY,
        turn_policy="safety_boundary_redirect",
        turn_analysis=turn_analysis,
    )
    student_message = state.get("student_message", "")
    messages = [*state.get("messages", [])]
    if student_message:
        messages.extend(
            [
                {"role": "student", "content": student_message},
                {"role": "coach", "content": reply},
            ]
        )
    safety_flags = list(state.get("safety_flags", []))
    if SAFETY_BOUNDARY_FLAG not in safety_flags:
        safety_flags.append(SAFETY_BOUNDARY_FLAG)
    return {
        "stage": state.get("stage") or "case_intro",
        "current_intents": ["safety_boundary"],
        "reply": reply,
        "messages": messages,
        "safety_flags": safety_flags,
        "agent_turn_memory": _append_agent_turn_memory(
            state,
            student_message=student_message,
            reply=reply,
            reply_role="coach",
            current_intents=["safety_boundary"],
            turn_policy="safety_boundary_redirect",
            turn_analysis=turn_analysis,
            agent_path=["safety_guardrail_node"],
            revealed_fact_id=None,
            safety_flags=safety_flags,
        ),
    }


def evaluation_node(
    state: OsceGraphState,
    llm_scorer: LlmRubricScorer | None = None,
) -> dict[str, Any]:
    report = evaluate_session_rules(
        SimpleNamespace(
            session_id=state.get("session_id", ""),
            case_id=state["case_id"],
            asked_questions=state.get("asked_questions", []),
            requested_exams=state.get("requested_exams", []),
            requested_tests=state.get("requested_tests", []),
            final_submission=state.get("final_submission"),
            revealed_facts=state.get("revealed_facts", []),
        ),
        llm_scorer=llm_scorer,
    )
    return {
        "stage": "evaluation",
        "rubric_scores": report["rubric_scores"],
        "missed_items": report["missed_items"],
        "feedback_report": report,
    }


def feedback_node(state: OsceGraphState) -> dict[str, Any]:
    report = dict(state.get("feedback_report") or {})
    rubric_scores = report.get("rubric_scores", {})
    session_id = report.get("session_id", state.get("session_id", ""))

    strengths = [
        f"{item_score['description']}：已完成。"
        for item_score in rubric_scores.values()
        if item_score["score"] > 0
    ]
    reasoning_errors = [
        f"{item_score['description']}：评分轨迹未找到足够证据。"
        for item_score in rubric_scores.values()
        if item_score["dimension_id"] in {"differential_diagnosis", "reasoning"}
        and item_score["score"] < item_score["max_score"]
    ]
    next_recommendations = [
        f"下一轮训练重点：{rubric_scores[item_id]['description']}。"
        for item_id in report.get("missed_items", [])
        if item_id in rubric_scores
    ]
    knowledge_recommendations = recommend_knowledge_items(report)
    source_items = retrieve_feedback_source_items(report, state.get("revealed_facts", []))
    source_references = [item.reference for item in source_items]
    llm_reasoning_feedback = _build_llm_reasoning_feedback(rubric_scores)
    explanation_source_items = _build_explanation_source_items(
        report.get("case_id", ""),
        rubric_scores,
        report.get("dimension_traces", {}),
    )
    evidence_graph_summary = _build_evidence_graph_summary(
        report.get("case_id", ""),
        state.get("revealed_facts", []),
        state.get("requested_exams", []),
        state.get("requested_tests", []),
    )

    feedback_report = {
        **report,
        "report_id": f"{session_id}_report",
        "strengths": strengths,
        "reasoning_errors": reasoning_errors,
        "next_recommendations": next_recommendations,
        "knowledge_recommendations": knowledge_recommendations,
        "llm_reasoning_feedback": llm_reasoning_feedback,
        "explanation_source_items": explanation_source_items,
        "evidence_graph_summary": evidence_graph_summary,
        "source_references": source_references,
        "source_reference_items": [_serialize_feedback_source_item(item) for item in source_items],
        "feedback_summary": "已根据评分轨迹生成教学反馈，内容仅用于 OSCE 训练复盘。",
        "created_at": "2026-04-24T00:00:00Z",
    }
    return {"stage": "feedback", "retrieved_sources": source_references, "feedback_report": feedback_report}


def _serialize_feedback_source_item(item: FeedbackSourceItem) -> dict[str, Any]:
    return {
        "reference": item.reference,
        "source_type": item.source_type,
        "title": item.title,
        "metadata": item.metadata,
    }


def _build_evidence_graph_summary(
    case_id: str,
    revealed_facts: Any,
    requested_exams: Any,
    requested_tests: Any,
) -> dict[str, Any]:
    if not case_id:
        return _empty_evidence_graph_summary("")
    case = _load_case(case_id)
    direct_evidence_types = {"history_fact", "physical_exam", "auxiliary_test"}
    direct_nodes = [
        node
        for node in case.evidence_graph.evidence_nodes
        if node.node_type in direct_evidence_types
    ]
    if not direct_nodes:
        return _empty_evidence_graph_summary(case.case_id)

    collected_source_ids = _collected_source_ids(revealed_facts, requested_exams, requested_tests)
    covered_node_ids = {
        node.node_id
        for node in direct_nodes
        if node.source_id in collected_source_ids
    }
    node_labels = {node.node_id: node.label for node in case.evidence_graph.evidence_nodes}
    covered_nodes = [node for node in direct_nodes if node.node_id in covered_node_ids]
    missing_nodes = [node for node in direct_nodes if node.node_id not in covered_node_ids]
    covered_edges = [
        edge
        for edge in case.evidence_graph.evidence_edges
        if edge.from_node in covered_node_ids
    ]
    missing_edges = [
        edge
        for edge in case.evidence_graph.evidence_edges
        if edge.from_node not in covered_node_ids
    ]

    return {
        "case_id": case.case_id,
        "total_evidence_node_count": len(direct_nodes),
        "covered_evidence_node_count": len(covered_nodes),
        "missing_evidence_node_count": len(missing_nodes),
        "coverage_ratio": round(len(covered_nodes) / len(direct_nodes), 4),
        "covered_evidence_nodes": [_serialize_evidence_graph_node(node) for node in covered_nodes],
        "missing_evidence_nodes": [_serialize_evidence_graph_node(node) for node in missing_nodes],
        "covered_edges": [_serialize_evidence_graph_edge(edge, node_labels) for edge in covered_edges],
        "missing_edges": [_serialize_evidence_graph_edge(edge, node_labels) for edge in missing_edges],
        "scoring_boundary": "EvidenceGraph 仅用于复盘已收集和缺失的训练证据，不参与诊断裁判或评分。",
    }


def _empty_evidence_graph_summary(case_id: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "total_evidence_node_count": 0,
        "covered_evidence_node_count": 0,
        "missing_evidence_node_count": 0,
        "coverage_ratio": 0.0,
        "covered_evidence_nodes": [],
        "missing_evidence_nodes": [],
        "covered_edges": [],
        "missing_edges": [],
        "scoring_boundary": "EvidenceGraph 仅用于复盘已收集和缺失的训练证据，不参与诊断裁判或评分。",
    }


def _collected_source_ids(
    revealed_facts: Any,
    requested_exams: Any,
    requested_tests: Any,
) -> set[str]:
    source_ids: set[str] = set()
    for items in [revealed_facts, requested_exams, requested_tests]:
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, str) and item:
                source_ids.add(item)
    return source_ids


def _serialize_evidence_graph_node(node: Any) -> dict[str, str]:
    return {
        "node_id": node.node_id,
        "node_type": node.node_type,
        "source_id": node.source_id,
        "label": node.label,
    }


def _serialize_evidence_graph_edge(edge: Any, node_labels: dict[str, str]) -> dict[str, str]:
    return {
        "from_node": edge.from_node,
        "to_node": edge.to_node,
        "relation": edge.relation,
        "from_label": node_labels.get(edge.from_node, edge.from_node),
        "to_label": node_labels.get(edge.to_node, edge.to_node),
    }


def _build_llm_reasoning_feedback(rubric_scores: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "rubric_item_id": item_id,
            "description": item_score["description"],
            "score": item_score["score"],
            "max_score": item_score["max_score"],
            "covered_evidence": item_score["covered_evidence"],
            "missing_evidence": item_score["missing_evidence"],
            "rationale": item_score["rationale"],
        }
        for item_id, item_score in rubric_scores.items()
        if "rationale" in item_score
    ]


def _build_explanation_source_items(
    case_id: str,
    rubric_scores: dict[str, Any],
    dimension_traces: Any,
) -> list[dict[str, Any]]:
    explanation_items: list[dict[str, Any]] = []
    evidence_references_by_item = _evidence_references_by_rubric_item(rubric_scores, dimension_traces)
    for item_id, item_score in rubric_scores.items():
        evidence_references = evidence_references_by_item.get(item_id, [])
        if item_score["score"] > 0:
            explanation_items.append(
                _build_explanation_source_item(
                    case_id=case_id,
                    kind="strength",
                    text=f"{item_score['description']}：已完成。",
                    rubric_item_id=item_id,
                    evidence_references=evidence_references,
                )
            )
        if (
            item_score["dimension_id"] in {"differential_diagnosis", "reasoning"}
            and item_score["score"] < item_score["max_score"]
        ):
            explanation_items.append(
                _build_explanation_source_item(
                    case_id=case_id,
                    kind="reasoning_error",
                    text=f"{item_score['description']}：评分轨迹未找到足够证据。",
                    rubric_item_id=item_id,
                    evidence_references=evidence_references,
                )
            )
        if "rationale" in item_score:
            explanation_items.append(
                _build_explanation_source_item(
                    case_id=case_id,
                    kind="llm_reasoning_feedback",
                    text=str(item_score["rationale"]),
                    rubric_item_id=item_id,
                    evidence_references=evidence_references,
                )
            )
    return explanation_items


def _build_explanation_source_item(
    case_id: str,
    kind: str,
    text: str,
    rubric_item_id: str,
    evidence_references: list[str],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "text": text,
        "rubric_item_id": rubric_item_id,
        "source_references": [f"rubric:{case_id}_rubric.item.{rubric_item_id}", *evidence_references],
    }


def _evidence_references_by_rubric_item(
    rubric_scores: dict[str, Any],
    dimension_traces: Any,
) -> dict[str, list[str]]:
    references_by_item: dict[str, list[str]] = {}
    if isinstance(dimension_traces, dict):
        for traces in dimension_traces.values():
            if not isinstance(traces, list):
                continue
            for trace in traces:
                if not isinstance(trace, dict) or trace.get("match_kind") == "intent_keyword":
                    continue
                rubric_item_id = trace.get("rubric_item_id")
                if not isinstance(rubric_item_id, str) or not rubric_item_id:
                    continue
                _append_evidence_references(references_by_item, rubric_item_id, trace.get("matched_evidence", []))

    for item_id, item_score in rubric_scores.items():
        if not isinstance(item_id, str) or not isinstance(item_score, dict):
            continue
        _append_evidence_references(references_by_item, item_id, item_score.get("covered_evidence", []))
    return references_by_item


def _append_evidence_references(
    references_by_item: dict[str, list[str]],
    rubric_item_id: str,
    evidence_items: Any,
) -> None:
    if not isinstance(evidence_items, list):
        return
    for evidence in evidence_items:
        if not isinstance(evidence, str) or not evidence:
            continue
        evidence_reference = f"evidence:{evidence}"
        item_references = references_by_item.setdefault(rubric_item_id, [])
        if evidence_reference not in item_references:
            item_references.append(evidence_reference)


def _build_socratic_hint(state: OsceGraphState, pedagogy_state: dict[str, Any] | None = None) -> str:
    if state.get("final_submission") is not None:
        return "你已经提交诊断，建议到报告中复盘哪些证据支持或削弱你的判断。"
    skill_hint = _build_enabled_skill_hint(_selected_skill_context_strings(state))
    if skill_hint:
        return skill_hint
    clinical_reasoning_state = (pedagogy_state or {}).get("clinical_reasoning_state", {})
    if isinstance(clinical_reasoning_state, dict) and clinical_reasoning_state.get("sequence_flags"):
        next_best_action = clinical_reasoning_state.get("next_best_action", {})
        message = str(next_best_action.get("message") or "").strip() if isinstance(next_best_action, dict) else ""
        why = str(next_best_action.get("why") or "").strip() if isinstance(next_best_action, dict) else ""
        question = str(clinical_reasoning_state.get("socratic_question") or "").strip()
        if message and why and question:
            return f"{message} 为什么：{why} 想一想：{question}"
        if message:
            return message
    if isinstance(state.get("training_progress"), dict):
        progress_sensitive_hint = _build_progress_sensitive_socratic_hint(clinical_reasoning_state)
        if progress_sensitive_hint:
            return progress_sensitive_hint
    training_progress_hint = state.get("training_progress_next_focus", "")
    if training_progress_hint:
        return training_progress_hint
    if not state.get("asked_questions", []):
        return "先用开放式问题明确起病、部位、性质、程度和伴随症状。"
    if not state.get("requested_exams", []):
        return "先围绕疼痛的部位、性质、程度、伴随症状和既往史继续追问，不要急于下诊断。"
    if not state.get("requested_tests", []):
        return "你已经获得部分病史和查体信息，可以思考哪些基础检查能验证当前假设。"
    if not state.get("student_hypotheses", []):
        return "先记录一个诊断假设，再用已获得证据检查它是否被支持或需要排除。"
    return "整理已获得的病史、查体和检查证据，再提交主要诊断和推理依据。"


def _retrieve_coach_knowledge_context(
    state: OsceGraphState,
    *,
    case: Case,
    query: str,
    forbidden_terms: list[str],
    limit: int = 3,
) -> list[dict[str, Any]]:
    return retrieve_agent_context(
        agent_role="coach",
        case_ids=[case.case_id],
        query_terms=[
            query,
            case.case_title,
            case.chief_complaint,
            str(state.get("stage", "")),
            str(state.get("training_progress_next_focus", "")),
            " ".join(_selected_skill_context_strings(state)),
        ],
        allowed_visibilities=COACH_RAG_VISIBILITIES,
        forbidden_terms=forbidden_terms,
        limit=limit,
        store=rag_knowledge_store,
    )


def _retrieve_reflection_knowledge_context(
    state: OsceGraphState,
    *,
    case: Case,
    reflection_summary: dict[str, Any],
    forbidden_terms: list[str],
    limit: int = 3,
) -> list[dict[str, Any]]:
    return retrieve_agent_context(
        agent_role="reflection",
        case_ids=[case.case_id],
        query_terms=[
            case.case_id,
            case.case_title,
            *[str(item_id) for item_id in state.get("missed_items", []) if str(item_id)],
            *[str(item_id) for item_id in reflection_summary.get("missed_item_ids", []) if str(item_id)],
            str(reflection_summary.get("summary", "")),
            str(reflection_summary.get("next_focus", "")),
        ],
        allowed_visibilities=REFLECTION_RAG_VISIBILITIES,
        forbidden_terms=forbidden_terms,
        limit=limit,
        store=rag_knowledge_store,
    )


def _build_progress_sensitive_socratic_hint(clinical_reasoning_state: Any) -> str:
    if not isinstance(clinical_reasoning_state, dict):
        return ""
    phase = str(clinical_reasoning_state.get("pedagogical_phase") or "")
    safe_pending_points = clinical_reasoning_state.get("safe_pending_points", {})
    history_pending = 0
    if isinstance(safe_pending_points, dict):
        history_points = safe_pending_points.get("history", {})
        if isinstance(history_points, dict):
            raw_pending_count = history_points.get("pending_count", 0)
            history_pending = raw_pending_count if isinstance(raw_pending_count, int) else 0
    if phase == "needs_history":
        if history_pending >= 3:
            return "病史线索还偏少，先继续补齐起病、部位变化、性质、程度和伴随症状，再决定查体。"
        if history_pending >= 2:
            return "病史链还不完整，先围绕未覆盖的症状维度做聚焦追问，再进入查体。"
        if history_pending == 1:
            return "病史只剩少量缺口，可以用一个聚焦追问确认后，再选择关键查体验证当前线索。"
    if phase == "needs_physical_exam":
        if history_pending == 1:
            return "病史只剩少量缺口，可以用一个聚焦追问确认后，再选择关键查体验证当前线索。"
        return "已有较完整病史线索，下一步选择关键查体来验证当前线索，再决定是否需要辅助检查。"
    if phase == "needs_auxiliary_test":
        return "已有病史和查体证据，下一步选择能验证当前假设的辅助检查，并说明检查目的。"
    if phase == "needs_reasoning":
        return "先进行证据整理，把已获得的病史、查体和检查信息写成诊断假设，再继续查漏补缺。"
    if phase == "ready_for_submission":
        return "提交前先梳理支持证据和排除依据，再提交最终诊断与推理过程。"
    return ""


def _build_enabled_skill_hint(evolution_candidates: list[str]) -> str:
    for candidate in evolution_candidates:
        normalized_candidate = candidate.strip()
        if not normalized_candidate:
            continue
        if "：" not in normalized_candidate:
            return f"本轮训练重点：{normalized_candidate}"
        title, strategy = normalized_candidate.split("：", 1)
        normalized_strategy = strategy.replace("在学生提交诊断前，提示其", "提交诊断前，请")
        normalized_strategy = normalized_strategy.replace("学生", "你")
        return f"本轮训练重点是{title}。{normalized_strategy}"
    return ""


def _selected_skill_items(state: OsceGraphState) -> list[dict[str, Any]]:
    active_skill_context = state.get("active_skill_context", {})
    if not isinstance(active_skill_context, dict):
        return []
    selected_skills = active_skill_context.get("selected_skills", [])
    if not isinstance(selected_skills, list):
        return []
    return [skill for skill in selected_skills if isinstance(skill, dict)]


def _selected_skill_context_strings(state: OsceGraphState) -> list[str]:
    selected_skill_texts: list[str] = []
    for skill in _selected_skill_items(state):
        title = str(skill.get("title") or "").strip()
        strategy = str(skill.get("suggested_strategy") or "").strip()
        if title and strategy:
            selected_skill_texts.append(f"{title}：{strategy}")
        elif title:
            selected_skill_texts.append(title)
        elif strategy:
            selected_skill_texts.append(strategy)
    if selected_skill_texts:
        return selected_skill_texts
    return [str(skill) for skill in state.get("evolution_candidates", []) if str(skill).strip()]


def _selected_skill_ids(state: OsceGraphState) -> list[str]:
    selected_skill_ids = [
        str(skill.get("skill_id"))
        for skill in _selected_skill_items(state)
        if str(skill.get("skill_id") or "").strip()
    ]
    if selected_skill_ids:
        return selected_skill_ids
    legacy_candidates = [str(skill) for skill in state.get("evolution_candidates", []) if str(skill).strip()]
    return [f"enabled_skill:{index + 1}" for index, _skill in enumerate(legacy_candidates)]


def _selected_skill_reason_items(state: OsceGraphState) -> list[dict[str, Any]]:
    reason_items: list[dict[str, Any]] = []
    for skill in _selected_skill_items(state):
        skill_id = str(skill.get("skill_id", "")).strip()
        if not skill_id:
            continue
        reason_items.append(
            {
                "skill_id": skill_id,
                "title": str(skill.get("title", "")),
                "why_selected_label": str(skill.get("why_selected_label", "") or skill.get("why_candidate", "")),
                "trigger_item_labels": [
                    str(label).strip()
                    for label in skill.get("trigger_item_labels", [])
                    if str(label).strip()
                ],
                "effect_status": str(skill.get("effect_status", "insufficient_samples")),
            }
        )
    return reason_items


def _is_safety_boundary_message(message: str) -> bool:
    normalized = message.lower()
    safety_keywords = [
        "用药剂量",
        "治疗方案",
        "手术方案",
        "急救",
        "处置建议",
        "吃什么药",
        "开什么药",
        "该吃药",
        "怎么治疗",
        "如何治疗",
        "真实健康",
        "现实中",
        "现实里",
    ]
    return any(keyword in normalized for keyword in safety_keywords)



def _is_direct_answer_request(message: str, case_id: str) -> bool:
    normalized = message.lower()
    direct_answer_keywords = [
        "直接告诉我",
        "告诉我答案",
        "标准答案",
        "正确答案",
        "最终答案",
        "答案是什么",
        "是什么病",
        "什么诊断",
    ]
    if any(keyword in normalized for keyword in direct_answer_keywords):
        return True
    case = _load_case(case_id)
    diagnosis_terms = [case.diagnosis.main_diagnosis, *case.diagnosis.main_diagnosis_synonyms]
    diagnosis_mentioned = any(term.lower() in normalized for term in diagnosis_terms if term)
    diagnosis_question_markers = ["是不是", "是否", "是吗", "对吗", "诊断"]
    return diagnosis_mentioned and any(marker in normalized for marker in diagnosis_question_markers)


def _answerable_hidden_facts_for_intent(case: Case, intent: str) -> list[HiddenFact]:
    if not intent:
        return []
    return [hidden_fact for hidden_fact in case.history.hidden_facts if intent in hidden_fact.trigger_intents]


def _answerable_hidden_facts_for_intents(case: Case, intents: list[str]) -> list[HiddenFact]:
    intent_set = _expanded_history_intent_set(intents)
    if not intent_set:
        return []
    return [
        hidden_fact
        for hidden_fact in case.history.hidden_facts
        if any(intent in intent_set for intent in hidden_fact.trigger_intents)
    ]


def _expanded_history_intent_set(intents: list[str]) -> set[str]:
    alias_map = {
        "ask_character": ["ask_pain_character", "ask_chest_pain_character", "ask_quality_of_pain"],
        "ask_past_medical": ["ask_past_medical_history"],
        "ask_family": ["ask_family_history"],
        "ask_stool": ["ask_bowel_change"],
    }
    intent_set: set[str] = set()
    for intent in intents:
        if not intent or intent == "unknown_history_intent":
            continue
        intent_set.add(intent)
        intent_set.update(alias_map.get(intent, []))
    return intent_set


def _answerable_patient_profile_fact_for_intent(case: Case, intent: str) -> dict[str, Any] | None:
    patient_profile = case.patient_profile
    profile_fact_specs = {
        "ask_patient_gender": {
            "slot": "gender",
            "canonical_answer": f"我是{patient_profile.gender}的。",
            "variants": [f"{patient_profile.gender}的"],
        },
        "ask_patient_age": {
            "slot": "age",
            "canonical_answer": f"我 {patient_profile.age_value}{patient_profile.age_unit}。",
            "variants": [f"{patient_profile.age_value}{patient_profile.age_unit}"],
        },
        "ask_patient_occupation": {
            "slot": "occupation",
            "canonical_answer": f"我是{patient_profile.occupation}。",
            "variants": [patient_profile.occupation],
        },
    }
    profile_fact_spec = profile_fact_specs.get(intent)
    if profile_fact_spec is None:
        return None
    slot = str(profile_fact_spec["slot"])
    return {
        "fact_id": f"{case.case_id}.profile.{slot}",
        "topic": "患者公开画像",
        "slot": slot,
        "canonical_answer": str(profile_fact_spec["canonical_answer"]),
        "variants": list(profile_fact_spec["variants"]),
        "trigger_intents": [intent],
        "source_reference": f"case:{case.case_id}.patient_profile.{slot}",
    }


def _answerable_patient_profile_facts_for_intents(case: Case, intents: list[str]) -> list[dict[str, Any]]:
    profile_facts: list[dict[str, Any]] = []
    for intent in intents:
        profile_fact = _answerable_patient_profile_fact_for_intent(case, intent)
        if profile_fact is None:
            continue
        if all(existing.get("fact_id") != profile_fact["fact_id"] for existing in profile_facts):
            profile_facts.append(profile_fact)
    return profile_facts


def _serialize_answerable_fact_candidate(case_id: str, hidden_fact: HiddenFact) -> dict[str, Any]:
    return {
        "fact_id": hidden_fact.fact_id,
        "topic": hidden_fact.topic,
        "slot": hidden_fact.slot,
        "canonical_answer": hidden_fact.canonical_answer,
        "variants": list(hidden_fact.variants),
        "trigger_intents": list(hidden_fact.trigger_intents),
        "source_reference": f"case:{case_id}.history.{hidden_fact.fact_id}",
    }


def _build_patient_private_context(case: Case) -> dict[str, Any]:
    patient_profile = case.patient_profile
    return {
        "case_id": case.case_id,
        "case_title": case.case_title,
        "chief_complaint": case.chief_complaint,
        "patient_profile": {
            "age": f"{patient_profile.age_value}{patient_profile.age_unit}",
            "gender": patient_profile.gender,
            "occupation": patient_profile.occupation,
            "marital_status": patient_profile.marital_status,
            "address_city": patient_profile.address_city,
            "social_background": patient_profile.social_background,
            "hospital_department": patient_profile.hospital_department,
            "idea": patient_profile.idea,
            "concern": patient_profile.concern,
            "expectation": patient_profile.expectation,
        },
        "history": {
            "present_illness_summary": case.history.present_illness_summary,
            "hidden_facts": [
                _serialize_answerable_fact_candidate(case.case_id, hidden_fact)
                for hidden_fact in case.history.hidden_facts
            ],
            "past_medical_history": case.history.past_medical_history,
            "surgery_injury_history": case.history.surgery_injury_history,
            "transfusion_history": case.history.transfusion_history,
            "infection_history": case.history.infection_history,
            "allergy_history": case.history.allergy_history,
            "personal_history": case.history.personal_history,
            "menstrual_history": case.history.menstrual_history,
            "reproductive_history": case.history.reproductive_history,
            "family_history": case.history.family_history,
        },
        "disclosure_policy": {
            "use_private_context_for_persona": True,
            "only_disclose_answerable_fact_candidates": True,
        },
    }


def _build_patient_forbidden_context(case: Case) -> dict[str, Any]:
    return {
        "diagnosis_terms": [case.diagnosis.main_diagnosis, *case.diagnosis.main_diagnosis_synonyms],
        "differential_diagnosis_terms": [
            differential.disease_name for differential in case.diagnosis.differential_diagnoses
        ],
        "blocked_reference_types": ["diagnosis", "rubric", "treatment", "dosage"],
        "blocked_content_examples": ["标准答案", "评分标准", "治疗方案", "用药剂量", "手术方案", "处置建议"],
    }


def _patient_forbidden_terms(case: Case) -> list[str]:
    return [
        case.diagnosis.main_diagnosis,
        *case.diagnosis.main_diagnosis_synonyms,
        *[differential.disease_name for differential in case.diagnosis.differential_diagnoses],
        "治疗方案",
        "用药剂量",
        "手术方案",
        "处置建议",
    ]


def _complete_unknown_turn_analysis(turn_analysis: dict[str, Any], student_message: str) -> dict[str, Any]:
    if turn_analysis.get("current_intents"):
        return turn_analysis
    unknown_analysis = classify_unknown_history_message(student_message)
    if turn_analysis.get("unknown_kind") and turn_analysis.get("possible_intents") is not None:
        return turn_analysis
    return {
        **turn_analysis,
        "unknown_kind": turn_analysis.get("unknown_kind") or unknown_analysis["unknown_kind"],
        "is_off_topic": bool(turn_analysis.get("is_off_topic") or unknown_analysis["is_off_topic"]),
        "possible_intents": list(turn_analysis.get("possible_intents") or unknown_analysis["possible_intents"]),
        "rationale": turn_analysis.get("rationale") or unknown_analysis["rationale"],
    }


def _merge_turn_analysis_with_keyword_intents(
    turn_analysis: dict[str, Any],
    keyword_intents: list[str],
) -> dict[str, Any]:
    deterministic_intents = _dedupe_intents(
        [intent for intent in keyword_intents if intent and intent != "unknown_history_intent"]
    )
    if not deterministic_intents:
        return turn_analysis

    raw_current_intents = turn_analysis.get("current_intents")
    model_intents = [str(intent) for intent in raw_current_intents] if isinstance(raw_current_intents, list) else []
    if model_intents:
        merged_intents = _dedupe_intents([*model_intents, *deterministic_intents])
        return {
            **turn_analysis,
            "current_intents": merged_intents,
        }

    return {
        "current_intents": deterministic_intents,
        "confidence": max(float(turn_analysis.get("confidence") or 0), 0.75),
        "is_off_topic": False,
        "rationale": "模型未稳定识别，后端关键词命中明确问诊意图。",
    }


def _dedupe_intents(intents: list[str]) -> list[str]:
    deduped: list[str] = []
    for intent in intents:
        if intent and intent not in deduped:
            deduped.append(intent)
    return deduped


def _unknown_kind_from_turn_analysis(turn_analysis: Any) -> str:
    if not isinstance(turn_analysis, dict):
        return ""
    unknown_kind = turn_analysis.get("unknown_kind")
    return str(unknown_kind) if unknown_kind else ""


def _possible_intents_from_turn_analysis(turn_analysis: Any) -> list[str]:
    if not isinstance(turn_analysis, dict):
        return []
    possible_intents = turn_analysis.get("possible_intents")
    if not isinstance(possible_intents, list):
        return []
    return [str(intent) for intent in possible_intents if intent]


def _current_intents_from_state(state: OsceGraphState) -> list[str]:
    raw_current_intents: Any = state.get("current_intents")
    if not raw_current_intents and isinstance(state.get("turn_analysis"), dict):
        raw_current_intents = state["turn_analysis"].get("current_intents")
    legacy_current_intent = str(state.get("current_intent", "") or "")
    candidates: list[str] = []
    if isinstance(raw_current_intents, list):
        candidates.extend(str(intent) for intent in raw_current_intents if intent)
    if not candidates and legacy_current_intent and legacy_current_intent != "unknown_history_intent":
        candidates.append(legacy_current_intent)
    deduped: list[str] = []
    for intent in candidates:
        if intent != "unknown_history_intent" and intent not in deduped:
            deduped.append(intent)
    return deduped


def _primary_intent_from_current_intents(current_intents: list[str]) -> str:
    return current_intents[0] if current_intents else "unknown_history_intent"


def _patient_context_short_complaint(case: Any) -> str:
    complaint = str(case.chief_complaint)
    if "腹痛" in complaint or "腹疼" in complaint:
        return "肚子疼"
    if "胸痛" in complaint or "胸疼" in complaint:
        return "胸口疼"
    return patient_friendly_chief_complaint(complaint).split("，")[0]


def _unknown_patient_context_answer(case: Any, unknown_kind: str = "") -> str:
    complaint = _patient_context_short_complaint(case)
    if unknown_kind == "social_greeting":
        return f"医生您好，我是因为{complaint}来看的。"
    if unknown_kind == "patient_identity_unclear":
        return f"我是这次来看{complaint}的病人。"
    if unknown_kind == "possible_missed_medical_intent":
        return "这个问题有点宽泛，我不太确定你具体想问哪方面。"
    if unknown_kind == "off_topic":
        return f"这个我不太了解，我这次主要是{complaint}来看的。"
    if unknown_kind == "unsupported_case_question":
        return "这个我不太清楚，病例里没有这方面信息。"
    if unknown_kind == "unclassified_input":
        return "我没太听明白您具体想问哪方面，可以再问得具体一点吗？"
    return build_patient_context_redirect_utterance(str(case.chief_complaint))


def _turn_policy_for_patient_response(intent: str, revealed_fact_id: str | None, *, unknown_kind: str = "") -> str:
    if revealed_fact_id:
        return "history_fact_disclosure"
    if intent == "unknown_history_intent":
        if unknown_kind == "social_greeting":
            return "social_greeting_response"
        if unknown_kind == "patient_identity_unclear":
            return "patient_identity_redirect"
        if unknown_kind == "possible_missed_medical_intent":
            return "possible_missed_medical_intent"
        if unknown_kind == "off_topic":
            return "off_topic_redirect"
        if unknown_kind == "unsupported_case_question":
            return "unsupported_case_question"
        if unknown_kind == "unclassified_input":
            return "unclassified_input"
        return "patient_context_redirect"
    return "patient_limited_answer"


def _asked_questions_after_patient_turn(
    state: OsceGraphState,
    student_message: str,
    revealed_fact_id: str | None,
) -> list[str]:
    asked_questions = list(state.get("asked_questions", []))
    if student_message and revealed_fact_id is not None:
        asked_questions.append(student_message)
    return asked_questions


def _deterministic_turn_hints(
    state: OsceGraphState,
    *,
    keyword_intent: str,
    keyword_intents: list[str] | None = None,
    current_intents: list[str] | None = None,
    revealed_fact_id: str | None,
    revealed_fact_ids: list[str] | None = None,
    turn_policy: str,
    answerable_fact_ids: list[str] | None = None,
) -> dict[str, Any]:
    turn_analysis = state.get("turn_analysis", {})
    return {
        "keyword_intent": keyword_intent,
        "keyword_intents": list(keyword_intents or []),
        "current_intents": list(current_intents or []),
        "turn_analysis": turn_analysis,
        "unknown_kind": _unknown_kind_from_turn_analysis(turn_analysis),
        "possible_intents": _possible_intents_from_turn_analysis(turn_analysis),
        "turn_policy": turn_policy,
        "revealed_fact_id": revealed_fact_id,
        "revealed_fact_ids": list(revealed_fact_ids or []),
        "answerable_fact_ids": list(answerable_fact_ids or []),
        "patient_context_mode": "private_context_with_answerable_fact_candidates",
        "stage": state.get("stage") or "case_intro",
        "safety_flags": list(state.get("safety_flags", [])),
        "training_progress_next_focus": state.get("training_progress_next_focus", ""),
    }


def _build_patient_dialogue_context(
    state: OsceGraphState,
    *,
    student_message: str,
    current_intents: list[str],
    answerable_fact_ids: list[str],
    revealed_fact_ids: list[str],
) -> dict[str, Any]:
    return {
        "student_message": student_message,
        "recent_messages": _recent_dialogue_messages(state.get("messages", []), limit=8),
        "asked_questions": _recent_string_items(state.get("asked_questions", []), limit=8),
        "intent_history": _recent_string_items(state.get("intent_history", []), limit=8),
        "current_intents": list(current_intents),
        "answerable_fact_ids": list(answerable_fact_ids),
        "revealed_fact_ids": list(revealed_fact_ids),
    }


def _recent_dialogue_messages(messages: Any, *, limit: int) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        return []
    recent_messages: list[dict[str, str]] = []
    for message in messages[-limit:]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", ""))
        content = str(message.get("content", ""))
        if role not in {"student", "patient", "coach"} or not content:
            continue
        recent_messages.append({"role": role, "content": content})
    return recent_messages


def _recent_string_items(items: Any, *, limit: int) -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(item) for item in items[-limit:] if item]


def _build_passive_coach_hint(
    state: OsceGraphState,
    *,
    primary_intent: str,
    revealed_fact_id: str | None,
) -> str:
    turn_analysis = state.get("turn_analysis", {})
    is_off_topic = isinstance(turn_analysis, dict) and bool(turn_analysis.get("is_off_topic"))
    unknown_kind = _unknown_kind_from_turn_analysis(turn_analysis)
    if primary_intent == "unknown_history_intent":
        if unknown_kind in {"social_greeting", "patient_identity_unclear"}:
            return ""
        if unknown_kind == "possible_missed_medical_intent":
            return "这个问题可能和问诊有关，但还不够具体。可以追问起病时间、疼痛部位、疼痛性质、疼痛程度或伴随症状。"
        if unknown_kind == "unsupported_case_question":
            return "病例脚本没有提供这方面信息。可以换成与本次症状相关的具体问法。"
        if unknown_kind == "off_topic":
            return "这轮训练先回到腹痛问诊。可以从起病时间、疼痛部位、性质、程度和伴随症状继续问。"
        if unknown_kind == "unclassified_input":
            return "本轮输入未能稳定识别为具体问诊意图。请换成更具体的问法，例如起病时间、疼痛部位、性质、程度或伴随症状。"
        return "可以先从起病时间、疼痛部位、性质、程度和伴随症状开始问。"
    if is_off_topic:
        return "可以先从起病时间、疼痛部位、性质、程度和伴随症状开始问。"
    if not revealed_fact_id:
        return ""
    return ""


def _apply_passive_coach_review(
    state: OsceGraphState,
    *,
    case: Any,
    coach_agent: CoachAgent,
    student_message: str,
    patient_reply: str,
    primary_intent: str,
    current_intents: list[str],
    revealed_fact_id: str | None,
    messages: list[dict[str, str]],
    agent_turn_memory: list[dict[str, Any]],
    turn_analysis: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    if not student_message:
        return messages, agent_turn_memory
    forbidden_terms = [case.diagnosis.main_diagnosis, *case.diagnosis.main_diagnosis_synonyms]
    base_hint = _build_passive_coach_hint(
        state,
        primary_intent=primary_intent,
        revealed_fact_id=revealed_fact_id,
    )
    retrieved_knowledge_context = _retrieve_coach_knowledge_context(
        state,
        case=case,
        query=" ".join([base_hint, student_message, patient_reply]),
        forbidden_terms=forbidden_terms,
    )
    selected_skill_context = _selected_skill_context_strings(state)
    selected_skill_ids = _selected_skill_ids(state)
    pedagogy_state = build_pedagogy_state(
        {
            **dict(state),
            "current_intents": current_intents,
            "turn_analysis": turn_analysis,
            "messages": messages,
        }
    )
    try:
        coach_response = normalize_coach_response(
            coach_agent(
                CoachRequest(
                    case_id=case.case_id,
                    case_title=case.case_title,
                    chief_complaint=case.chief_complaint,
                    stage=state.get("stage", "case_intro"),
                    prompt_kind="passive_turn_review",
                    base_hint=base_hint,
                    prior_messages=messages,
                    pedagogy_state={
                        **pedagogy_state,
                        "patient_reply": patient_reply,
                        "revealed_fact_id": revealed_fact_id,
                    },
                    clinical_reasoning_state=pedagogy_state.get("clinical_reasoning_state", {}),
                    skill_context=selected_skill_context,
                    retrieved_knowledge_context=retrieved_knowledge_context,
                    forbidden_terms=forbidden_terms,
                )
            )
        )
    except Exception as exc:
        unavailable_turn_analysis = {
            **turn_analysis,
            "coach_unavailable": True,
            "coach_error_type": exc.__class__.__name__,
        }
        return messages, _append_agent_turn_memory(
            {**dict(state), "agent_turn_memory": agent_turn_memory},
            student_message=student_message,
            reply="",
            reply_role="coach",
            current_intents=current_intents,
            turn_policy="passive_review_unavailable",
            turn_analysis=unavailable_turn_analysis,
            agent_path=["input_router_node", "patient_response_node", "coach_agent_unavailable"],
            revealed_fact_id=None,
            safety_flags=list(state.get("safety_flags", [])),
            selected_skill_ids=selected_skill_ids,
            skill_context=selected_skill_context,
        )
    forced_hint = base_hint.strip()
    response_hint = coach_response.hint.strip()
    unknown_kind = _unknown_kind_from_turn_analysis(turn_analysis)
    should_suppress_unforced_hint = (
        revealed_fact_id is not None
        or (primary_intent == "unknown_history_intent" and unknown_kind in {"social_greeting", "patient_identity_unclear"})
    )
    should_emit = bool(
        forced_hint or (not should_suppress_unforced_hint and coach_response.should_emit and response_hint)
    )
    coach_hint = sanitize_coach_hint(response_hint or forced_hint, forbidden_terms) if should_emit else ""
    next_messages = [*messages]
    if should_emit:
        next_messages.append({"role": "coach", "content": coach_hint})
    next_agent_turn_memory = _append_agent_turn_memory(
        {**dict(state), "agent_turn_memory": agent_turn_memory},
        student_message=student_message,
        reply=coach_hint,
        reply_role="coach",
        current_intents=current_intents,
        turn_policy="passive_review_hint" if should_emit else "passive_review_silent",
        turn_analysis=turn_analysis,
        agent_path=["input_router_node", "patient_response_node", "coach_agent"],
        revealed_fact_id=None,
        safety_flags=list(state.get("safety_flags", [])),
        source_references=[item["reference"] for item in retrieved_knowledge_context] if should_emit else [],
        retrieved_knowledge_context=retrieved_knowledge_context if should_emit else [],
        selected_skill_ids=selected_skill_ids,
        skill_context=selected_skill_context,
    )
    return next_messages, next_agent_turn_memory


def _coach_reply_from_agent(
    state: OsceGraphState,
    coach_agent: CoachAgent,
    *,
    primary_intent: str,
    base_hint: str,
    turn_policy: str,
    turn_analysis: dict[str, Any],
) -> str:
    case = _load_case(state["case_id"])
    forbidden_terms = [case.diagnosis.main_diagnosis, *case.diagnosis.main_diagnosis_synonyms]
    retrieved_knowledge_context = _retrieve_coach_knowledge_context(
        state,
        case=case,
        query=base_hint,
        forbidden_terms=forbidden_terms,
    )
    coach_response = normalize_coach_response(
        coach_agent(
            CoachRequest(
                case_id=case.case_id,
                case_title=case.case_title,
                chief_complaint=case.chief_complaint,
                stage=state.get("stage") or "case_intro",
                prompt_kind=turn_policy,
                base_hint=base_hint,
                prior_messages=state.get("messages", []),
                pedagogy_state={
                    **(
                        pedagogy_state := build_pedagogy_state(
                            {**dict(state), "current_intents": [primary_intent], "turn_analysis": turn_analysis}
                        )
                    ),
                    "turn_analysis": turn_analysis,
                },
                clinical_reasoning_state=pedagogy_state.get("clinical_reasoning_state", {}),
                skill_context=_selected_skill_context_strings(state),
                retrieved_knowledge_context=retrieved_knowledge_context,
                forbidden_terms=forbidden_terms,
            )
        )
    )
    return sanitize_coach_hint(coach_response.hint.strip() or base_hint, forbidden_terms)


def _append_agent_turn_memory(
    state: OsceGraphState,
    *,
    student_message: str,
    reply: str,
    reply_role: str,
    current_intents: list[str],
    turn_policy: str,
    turn_analysis: dict[str, Any],
    agent_path: list[str],
    revealed_fact_id: str | None,
    safety_flags: list[str],
    revealed_fact_ids: list[str] | None = None,
    source_references: list[str] | None = None,
    retrieved_knowledge_context: list[dict[str, Any]] | None = None,
    selected_skill_ids: list[str] | None = None,
    skill_context: list[str] | None = None,
) -> list[dict[str, Any]]:
    turn_memory = list(state.get("agent_turn_memory", []))
    history_fact_ids = list(revealed_fact_ids or ([revealed_fact_id] if revealed_fact_id else []))
    turn_source_references = [f"case:{state['case_id']}.history.{fact_id}" for fact_id in history_fact_ids if fact_id]
    for reference in source_references or []:
        if reference and reference not in turn_source_references:
            turn_source_references.append(reference)
    turn_knowledge_context = _turn_knowledge_context(retrieved_knowledge_context or [], turn_source_references)
    turn_payload = {
        "turn_id": f"turn:{len(turn_memory) + 1}",
        "student_message": student_message,
        "reply": reply,
        "reply_role": reply_role,
        "current_intents": list(current_intents),
        "turn_policy": turn_policy,
        "turn_analysis": dict(turn_analysis),
        "agent_path": list(agent_path),
        "revealed_fact_id": revealed_fact_id,
        "source_references": turn_source_references,
        "safety_flags": list(safety_flags),
    }
    if revealed_fact_ids:
        turn_payload["revealed_fact_ids"] = list(revealed_fact_ids)
    if turn_knowledge_context:
        turn_payload["knowledge_references"] = [item["reference"] for item in turn_knowledge_context]
        turn_payload["retrieved_knowledge_context"] = turn_knowledge_context
    if selected_skill_ids:
        turn_payload["selected_skill_ids"] = list(selected_skill_ids)
    selected_skill_reasons = _selected_skill_reason_items(state)
    if selected_skill_reasons:
        turn_payload["selected_skill_reasons"] = selected_skill_reasons
    if skill_context:
        turn_payload["skill_context"] = list(skill_context)
    turn_memory.append(turn_payload)
    return turn_memory


def _turn_knowledge_context(
    retrieved_knowledge_context: list[dict[str, Any]],
    source_references: list[str],
) -> list[dict[str, Any]]:
    source_reference_set = set(source_references)
    return [
        item
        for item in retrieved_knowledge_context
        if isinstance(item, dict)
        and isinstance(item.get("reference"), str)
        and item["reference"] in source_reference_set
    ]


def _boundary_turn_analysis(intent: str, rationale: str) -> dict[str, Any]:
    return {
        "current_intents": [intent],
        "confidence": 1.0,
        "is_off_topic": False,
        "rationale": rationale,
    }


def _route_after_input_router(state: OsceGraphState) -> str:
    return "patient_response_node"


def _route_after_load_case(state: OsceGraphState) -> str:
    student_message = state.get("student_message", "")
    if student_message:
        if _is_safety_boundary_message(student_message):
            return "safety_guardrail_node"
        if _is_direct_answer_request(student_message, state["case_id"]):
            return "answer_request_redirect_node"
        return "input_router_node"
    if state.get("hint_requested"):
        return "socratic_hint_node"
    if state.get("exam_code"):
        return "physical_exam_node"
    if state.get("test_code"):
        return "auxiliary_test_node"
    if state.get("submitted_diagnosis"):
        return "diagnosis_submit_node"
    if state.get("report_requested"):
        return "evaluation_node"
    return END


def _load_case(case_id: str) -> Any:
    case_path = CASES_DIR / f"{case_id}.json"
    case_payload = json.loads(case_path.read_text(encoding="utf-8"))
    return validate_case(case_payload)


def build_osce_graph(
    llm_scorer: LlmRubricScorer | None = None,
    patient_responder: PatientResponder | None = None,
    turn_intent_agent: TurnIntentAgent | None = None,
    coach_agent: CoachAgent | None = None,
) -> Any:
    active_patient_responder = patient_responder or create_default_gemini_patient_responder()
    active_turn_intent_agent = turn_intent_agent or create_default_turn_intent_agent()
    active_coach_agent = coach_agent or create_default_coach_agent()
    builder = StateGraph(OsceGraphState)
    builder.add_node(load_case_node)
    builder.add_node("input_router_node", lambda state: input_router_node(state, active_turn_intent_agent))
    builder.add_node(unknown_history_redirect_node)
    builder.add_node("patient_response_node", lambda state: patient_response_node(state, active_patient_responder, active_coach_agent))
    builder.add_node(physical_exam_node)
    builder.add_node(auxiliary_test_node)
    builder.add_node(diagnosis_submit_node)
    builder.add_node("socratic_hint_node", lambda state: socratic_hint_node(state, active_coach_agent))
    builder.add_node(
        "answer_request_redirect_node",
        lambda state: answer_request_redirect_node(state, active_coach_agent),
    )
    builder.add_node("safety_guardrail_node", lambda state: safety_guardrail_node(state, active_coach_agent))
    builder.add_node("evaluation_node", lambda state: evaluation_node(state, llm_scorer=llm_scorer))
    builder.add_node(feedback_node)
    builder.add_edge(START, "load_case_node")
    builder.add_conditional_edges(
        "load_case_node",
        _route_after_load_case,
        {
            "input_router_node": "input_router_node",
            "physical_exam_node": "physical_exam_node",
            "auxiliary_test_node": "auxiliary_test_node",
            "diagnosis_submit_node": "diagnosis_submit_node",
            "socratic_hint_node": "socratic_hint_node",
            "answer_request_redirect_node": "answer_request_redirect_node",
            "safety_guardrail_node": "safety_guardrail_node",
            "evaluation_node": "evaluation_node",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "input_router_node",
        _route_after_input_router,
        {
            "patient_response_node": "patient_response_node",
        },
    )
    builder.add_edge("unknown_history_redirect_node", END)
    builder.add_edge("patient_response_node", END)
    builder.add_edge("physical_exam_node", END)
    builder.add_edge("auxiliary_test_node", END)
    builder.add_edge("diagnosis_submit_node", END)
    builder.add_edge("socratic_hint_node", END)
    builder.add_edge("answer_request_redirect_node", END)
    builder.add_edge("safety_guardrail_node", END)
    builder.add_edge("evaluation_node", "feedback_node")
    builder.add_edge("feedback_node", END)
    return builder.compile()


osce_graph = build_osce_graph()
