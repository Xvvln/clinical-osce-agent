from __future__ import annotations

from typing import Any

from app.models.case import Case
from app.services.model_context_window import bounded_provider_messages

MAX_COACH_HYPOTHESES = 5
MAX_COACH_HYPOTHESIS_CHARS = 1_280


def build_coach_hint_context(
    *,
    state: dict[str, Any],
    case: Case,
    pedagogy_state: dict[str, Any],
    base_hint: str,
    retrieved_knowledge_context: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a compact, safe planning context for Coach hints."""

    clinical_reasoning_state = _dict(pedagogy_state.get("clinical_reasoning_state"))
    student_hypotheses = _string_list(state.get("student_hypotheses", []))
    return {
        "session": {
            "session_id": str(state.get("session_id") or ""),
            "case_id": case.case_id,
            "case_title": case.case_title,
            "chief_complaint": case.chief_complaint,
            "stage": str(state.get("stage") or "case_intro"),
            "training_difficulty": _training_difficulty(state),
        },
        "conversation": {
            "recent_turns": _recent_turns(state.get("messages", [])),
            "asked_questions_count": len(_string_list(state.get("asked_questions", []))),
            "student_hypotheses": _recent_hypotheses(student_hypotheses),
            "student_hypotheses_total_count": len(student_hypotheses),
        },
        "evidence_coverage": _evidence_coverage(state, case, clinical_reasoning_state),
        "next_step": {
            "base_hint": base_hint,
            "active_learning_goal": str(pedagogy_state.get("active_learning_goal") or ""),
            "next_best_action": pedagogy_state.get("next_best_action"),
            "socratic_question": str(clinical_reasoning_state.get("socratic_question") or ""),
            "clinical_reasoning_state": clinical_reasoning_state,
            "hint_ladder": list(pedagogy_state.get("hint_ladder", []))
            if isinstance(pedagogy_state.get("hint_ladder"), list)
            else [],
        },
        "difficulty_policy": _difficulty_policy(_training_difficulty(state)),
        "skill_selection": _skill_selection(state),
        "rag_context": [
            {
                "reference": str(item.get("reference") or ""),
                "title": str(item.get("title") or ""),
                "visibility": str(item.get("visibility") or ""),
            }
            for item in retrieved_knowledge_context
            if isinstance(item, dict)
        ],
        "safety_boundary": {
            "purpose": "teaching_hint_only",
            "do_not_reveal": [
                "standard_diagnosis",
                "hidden_fact_text_not_asked_by_student",
                "unrequested_exam_or_test_result",
                "rubric_answer",
                "treatment_plan",
                "drug_dose",
            ],
        },
    }


def _evidence_coverage(
    state: dict[str, Any],
    case: Case,
    clinical_reasoning_state: dict[str, Any],
) -> dict[str, Any]:
    revealed_facts = set(_string_list(state.get("revealed_facts", [])))
    requested_exams = set(_string_list(state.get("requested_exams", [])))
    requested_tests = set(_string_list(state.get("requested_tests", [])))
    safe_pending_points = _dict(clinical_reasoning_state.get("safe_pending_points"))
    return {
        "history": {
            "collected": [
                {
                    "id": _safe_case_item_id(case, fact.fact_id),
                    "topic": fact.topic,
                    "slot": fact.slot or "",
                    "label": fact.canonical_answer,
                }
                for fact in case.history.hidden_facts
                if fact.fact_id in revealed_facts
            ],
            "pending_count": _nested_int(safe_pending_points, "history", "pending_count"),
            "pending_categories": _nested_list(safe_pending_points, "history", "pending_categories"),
        },
        "physical_exam": {
            "collected": [
                {"id": exam.exam_code, "label": exam.exam_name_cn, "result": exam.result}
                for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]
                if exam.exam_code in requested_exams
            ],
            "requested_count": len(requested_exams),
            "pending_count": len(_nested_list(safe_pending_points, "physical_exam", "pending_codes")),
            "must_pending_count": len(_nested_list(safe_pending_points, "physical_exam", "must_pending_codes")),
        },
        "auxiliary_test": {
            "collected": [
                {
                    "id": test.test_code,
                    "label": test.test_name_cn,
                    "category": str(test.category),
                    "result": test.result,
                }
                for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]
                if test.test_code in requested_tests
            ],
            "requested_count": len(requested_tests),
            "pending_count": len(_nested_list(safe_pending_points, "auxiliary_test", "pending_codes")),
            "must_pending_count": len(_nested_list(safe_pending_points, "auxiliary_test", "must_pending_codes")),
        },
        "reasoning": {
            "hypothesis_count": len(_string_list(state.get("student_hypotheses", []))),
            "pending_evidence_count": _nested_int(safe_pending_points, "reasoning", "pending_evidence_count"),
            "readiness": _dict(clinical_reasoning_state.get("readiness")).get("reasoning", ""),
        },
    }


def _difficulty_policy(training_difficulty: str) -> dict[str, str]:
    if training_difficulty == "advanced":
        return {
            "mode": "advanced",
            "student_action_boundary": "学生应使用自由文本说明想申请的查体或检查及其目的；Coach 只提示思路，不列出标准项目。",
            "coach_hint_style": "反问式、目的导向，强调证据链和鉴别排除。",
        }
    if training_difficulty == "intermediate":
        return {
            "mode": "intermediate",
            "student_action_boundary": "学生应从通用目录中自行选择查体或检查；Coach 可提示类别和目的，但不直接给出病例重点项目。",
            "coach_hint_style": "先问目的，再提示下一类动作。",
        }
    return {
        "mode": "beginner",
        "student_action_boundary": "学生可使用结构化按钮推进训练；Coach 可以更明确提示下一类动作。",
        "coach_hint_style": "短句、低负荷、按 OSCE 顺序提醒。",
    }


def _skill_selection(state: dict[str, Any]) -> dict[str, Any]:
    active_skill_context = state.get("active_skill_context", {})
    if not isinstance(active_skill_context, dict):
        active_skill_context = {}
    selected_skills = active_skill_context.get("selected_skills", [])
    if not isinstance(selected_skills, list):
        selected_skills = []
    skill_index_items = active_skill_context.get("skill_index", [])
    if not isinstance(skill_index_items, list):
        skill_index_items = []
    index_by_skill_id = {
        str(item.get("skill_id") or ""): item
        for item in skill_index_items
        if isinstance(item, dict) and str(item.get("skill_id") or "")
    }
    candidate_skills = [
        _compact_skill_selection_payload(
            skill,
            index_by_skill_id.get(str(skill.get("skill_id") or ""), {}),
        )
        for skill in selected_skills
        if isinstance(skill, dict)
    ]
    return {
        "selected_count": len([item for item in selected_skills if isinstance(item, dict)]),
        "available_skill_ids": [skill["skill_id"] for skill in candidate_skills if skill["skill_id"]],
        "candidate_skills": candidate_skills,
        "selected_skills": candidate_skills,
        "training_goals": _compact_training_goals(active_skill_context.get("current_training_gaps", [])),
        "humanistic_training_goals": _compact_training_goals(
            active_skill_context.get("humanistic_training_goals", [])
        ),
    }


def _compact_skill_selection_payload(skill: dict[str, Any], indexed_skill: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "skill_id": str(skill.get("skill_id") or ""),
        "title": str(skill.get("title") or ""),
        "why_selected_label": str(skill.get("why_selected_label") or skill.get("why_candidate") or ""),
        "trigger_item_labels": _string_list(skill.get("trigger_item_labels", [])),
        "stage_scope": _string_list(skill.get("stage_scope", [])),
    }
    for field_name in ("summary", "when_to_use", "when_not_to_use", "risk"):
        field_value = str(skill.get(field_name) or indexed_skill.get(field_name) or "").strip()
        if field_value:
            payload[field_name] = field_value
    return payload


def _compact_training_goals(value: Any, limit: int = 3) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    goals: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        goals.append(
            {
                "gap_type": str(item.get("gap_type") or ""),
                "label": str(item.get("label") or ""),
                "trigger_stage": str(item.get("trigger_stage") or item.get("stage") or ""),
                "next_training_action": str(item.get("next_training_action") or ""),
                "success_signal": str(item.get("success_signal") or ""),
                "skill_type": str(item.get("skill_type") or ""),
                "status": str(item.get("status") or ""),
                "priority": _int_value(item.get("priority")),
            }
        )
        if len(goals) >= limit:
            break
    return goals


def _recent_turns(messages: Any, limit: int = 8) -> list[dict[str, str]]:
    return bounded_provider_messages(messages, max_messages=limit)


def _recent_hypotheses(hypotheses: list[str]) -> list[str]:
    remaining_chars = MAX_COACH_HYPOTHESIS_CHARS
    newest_first: list[str] = []
    for hypothesis in reversed(hypotheses[-MAX_COACH_HYPOTHESES:]):
        if remaining_chars <= 0:
            break
        bounded = hypothesis[:remaining_chars]
        if not bounded:
            continue
        newest_first.append(bounded)
        remaining_chars -= len(bounded)
    return list(reversed(newest_first))


def _training_difficulty(state: dict[str, Any]) -> str:
    value = str(state.get("training_difficulty") or "beginner").strip()
    return value if value in {"beginner", "intermediate", "advanced"} else "beginner"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _nested_list(source: dict[str, Any], key: str, nested_key: str) -> list[str]:
    nested = source.get(key)
    if not isinstance(nested, dict):
        return []
    return _string_list(nested.get(nested_key, []))


def _nested_int(source: dict[str, Any], key: str, nested_key: str) -> int:
    nested = source.get(key)
    if not isinstance(nested, dict):
        return 0
    value = nested.get(nested_key, 0)
    return value if isinstance(value, int) else 0


def _int_value(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _safe_case_item_id(case: Case, item_id: str) -> str:
    return item_id.removeprefix(f"{case.case_id}.")
