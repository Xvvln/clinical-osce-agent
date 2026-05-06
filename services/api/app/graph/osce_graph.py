from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.services.gemini_patient_responder import PatientResponderRequest, create_default_gemini_patient_responder
from app.services.agent_state_service import append_decision_trace, build_pedagogy_state, build_reflection_summary
from app.services.knowledge_recommender import recommend_knowledge_items
from app.services.rule_evaluator import LlmRubricScorer, evaluate_session_rules
from app.services.source_retriever import FeedbackSourceItem, retrieve_feedback_source_items
from app.validators.case_validator import validate_case

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"
PatientResponder = Callable[[PatientResponderRequest], str]
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
    current_intent: str
    reply: str
    report_requested: bool
    hint_requested: bool
    hint: str
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


def input_router_node(state: OsceGraphState) -> dict[str, str]:
    normalized = state.get("student_message", "").lower()
    intent_keywords = [
        ("ask_migration", ["转移", "换地方", "跑到"]),
        ("ask_character", ["性质", "什么样", "胀痛", "绞痛", "刺痛"]),
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
        ("ask_location", ["哪里", "位置", "部位"]),
        ("ask_past_medical_history", ["既往", "以前", "手术史"]),
    ]
    for intent, keywords in intent_keywords:
        if any(keyword in normalized for keyword in keywords):
            return {"current_intent": intent}
    return {"current_intent": "unknown_history_intent"}


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
        "current_intent": "unknown_history_intent",
        "reply": UNKNOWN_HISTORY_REDIRECT_REPLY,
        "messages": messages,
        "asked_questions": list(state.get("asked_questions", [])),
        "intent_history": [*state.get("intent_history", []), "unknown_history_intent"],
        "revealed_facts": list(state.get("revealed_facts", [])),
    }


def patient_response_node(state: OsceGraphState, patient_responder: PatientResponder) -> dict[str, Any]:
    case = _load_case(state["case_id"])
    intent = state.get("current_intent", "")
    revealed_facts = list(state.get("revealed_facts", []))
    canonical_answer = "这个问题我不太确定，或者病例中没有提供相关信息。"
    revealed_fact_id: str | None = None
    for hidden_fact in case.history.hidden_facts:
        if intent in hidden_fact.trigger_intents:
            revealed_fact_id = hidden_fact.fact_id
            if hidden_fact.fact_id not in revealed_facts:
                revealed_facts.append(hidden_fact.fact_id)
            canonical_answer = hidden_fact.canonical_answer
            break

    student_message = state.get("student_message", "")
    reply = patient_responder(
        PatientResponderRequest(
            case_id=case.case_id,
            case_title=case.case_title,
            chief_complaint=case.chief_complaint,
            student_message=student_message,
            current_intent=intent,
            canonical_answer=canonical_answer,
            revealed_fact_id=revealed_fact_id,
            forbidden_terms=[case.diagnosis.main_diagnosis, *case.diagnosis.main_diagnosis_synonyms],
            prior_messages=state.get("messages", []),
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

    return {
        "stage": "history_taking",
        "reply": reply,
        "messages": messages,
        "asked_questions": [*state.get("asked_questions", []), student_message],
        "intent_history": [*state.get("intent_history", []), intent],
        "revealed_facts": revealed_facts,
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


def socratic_hint_node(state: OsceGraphState) -> dict[str, Any]:
    hint = _build_socratic_hint(state)
    return {
        "stage": state.get("stage", "case_intro"),
        "hint": hint,
        "messages": [*state.get("messages", []), {"role": "coach", "content": hint}],
    }



def answer_request_redirect_node(state: OsceGraphState) -> dict[str, Any]:
    student_message = state.get("student_message", "")
    messages = [*state.get("messages", [])]
    if student_message:
        messages.extend(
            [
                {"role": "student", "content": student_message},
                {"role": "coach", "content": ANSWER_REQUEST_REDIRECT_REPLY},
            ]
        )
    return {
        "stage": state.get("stage") or "case_intro",
        "current_intent": "answer_request_redirect",
        "reply": ANSWER_REQUEST_REDIRECT_REPLY,
        "messages": messages,
    }



def safety_guardrail_node(state: OsceGraphState) -> dict[str, Any]:
    student_message = state.get("student_message", "")
    messages = [*state.get("messages", [])]
    if student_message:
        messages.extend(
            [
                {"role": "student", "content": student_message},
                {"role": "coach", "content": SAFETY_GUARDRAIL_REPLY},
            ]
        )
    safety_flags = list(state.get("safety_flags", []))
    if SAFETY_BOUNDARY_FLAG not in safety_flags:
        safety_flags.append(SAFETY_BOUNDARY_FLAG)
    return {
        "stage": state.get("stage") or "case_intro",
        "current_intent": "safety_boundary",
        "reply": SAFETY_GUARDRAIL_REPLY,
        "messages": messages,
        "safety_flags": safety_flags,
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

    feedback_report = {
        **report,
        "report_id": f"{session_id}_report",
        "strengths": strengths,
        "reasoning_errors": reasoning_errors,
        "next_recommendations": next_recommendations,
        "knowledge_recommendations": knowledge_recommendations,
        "llm_reasoning_feedback": llm_reasoning_feedback,
        "explanation_source_items": explanation_source_items,
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


def _build_socratic_hint(state: OsceGraphState) -> str:
    if state.get("final_submission") is not None:
        return "你已经提交诊断，建议到报告中复盘哪些证据支持或削弱你的判断。"
    skill_hint = _build_enabled_skill_hint(state.get("evolution_candidates", []))
    if skill_hint:
        return skill_hint
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


def _route_after_input_router(state: OsceGraphState) -> str:
    if state.get("current_intent") == "unknown_history_intent":
        return "unknown_history_redirect_node"
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
) -> Any:
    active_patient_responder = patient_responder or create_default_gemini_patient_responder()
    builder = StateGraph(OsceGraphState)
    builder.add_node(load_case_node)
    builder.add_node(input_router_node)
    builder.add_node(unknown_history_redirect_node)
    builder.add_node("patient_response_node", lambda state: patient_response_node(state, active_patient_responder))
    builder.add_node(physical_exam_node)
    builder.add_node(auxiliary_test_node)
    builder.add_node(diagnosis_submit_node)
    builder.add_node(socratic_hint_node)
    builder.add_node(answer_request_redirect_node)
    builder.add_node(safety_guardrail_node)
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
            "unknown_history_redirect_node": "unknown_history_redirect_node",
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
